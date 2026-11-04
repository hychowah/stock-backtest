"""Input/engine boundaries and narrow financial-source normalization."""
import ast
import copy
from datetime import date
import importlib.util
import inspect
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backtest.financial import books
from backtest.engines.numerical.policy import PolicyProgram, _normalized_snapshot


class OwnershipTests(unittest.TestCase):
    def changed(self, function, before, after):
        text=inspect.getsource(function)
        self.assertIn(before,text)
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        path=Path(temporary.name)/'policy_change.py';path.write_text(text.replace(before,after))
        spec=importlib.util.spec_from_file_location('policy_change',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return getattr(module,function.__name__)

    def test_pair_normalization_is_exact_predecessor(self):
        import textwrap
        predecessor = inspect.getsource(books.snapshot).replace(
            '*ebitda_yield_and_multiple(ebitda,ev)', 'ebitda/ev,ev/ebitda')
        old = ast.parse(textwrap.dedent(predecessor)).body[0]
        helper = ast.parse(textwrap.dedent(inspect.getsource(books.entry_valuation))).body[0]
        def body(tree):
            return tree.body[1:] if isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) else tree.body
        old.body = copy.deepcopy(body(helper)[:-1] + body(old)[3:])
        self.assertEqual(ast.dump(_normalized_snapshot()), ast.dump(old))
        self.assertEqual(books.ebitda_yield_and_multiple(1., 49.), (1. / 49., 49. / 1.))
        self.assertIn(Path(inspect.getsourcefile(books.ebitda_yield_and_multiple)), PolicyProgram().source_paths)

    def test_pair_helper_and_call_mutations_are_rejected(self):
        pair = books.ebitda_yield_and_multiple
        wrapper = books.snapshot
        cases = [
            (pair, 'ebitda, enterprise_value', 'ebitda, enterprise_value, extra=None'),
            (pair, 'def ebitda_yield_and_multiple', 'async def ebitda_yield_and_multiple'),
            (pair, 'def ebitda_yield_and_multiple', '@staticmethod\ndef ebitda_yield_and_multiple'),
            (pair, 'ebitda, enterprise_value', 'ebitda: float, enterprise_value'),
            (pair, 'return ebitda / enterprise_value, enterprise_value / ebitda', 'return enterprise_value / ebitda, ebitda / enterprise_value'),
            (pair, 'return ebitda / enterprise_value, enterprise_value / ebitda', 'return ebitda / enterprise_value, 1 / (ebitda / enterprise_value)'),
            (pair, 'return ebitda / enterprise_value, enterprise_value / ebitda', 'pass\n    return ebitda / enterprise_value, enterprise_value / ebitda'),
            (wrapper, '*ebitda_yield_and_multiple(ebitda,ev)', '*ebitda_yield_and_multiple(ev,ebitda)'),
            (wrapper, '*ebitda_yield_and_multiple(ebitda,ev)', '*ebitda_yield_and_multiple(ebitda=ebitda,enterprise_value=ev)'),
            (wrapper, '*ebitda_yield_and_multiple(ebitda,ev)', '*ebitda_yield_and_multiple(ebitda,ev), *ebitda_yield_and_multiple(ebitda,ev)'),
            (wrapper, 'ebitda,*ebitda_yield_and_multiple(ebitda,ev)', '*ebitda_yield_and_multiple(ebitda,ev),ebitda'),
        ]
        for function, before, after in cases:
            with self.subTest(after=after):
                changed = self.changed(function, before, after)
                if isinstance(changed, staticmethod): changed = changed.__func__
                changed.__globals__['entry_valuation'] = books.entry_valuation
                changed.__globals__['ebitda_yield_and_multiple'] = books.ebitda_yield_and_multiple
                with patch.object(books, function.__name__, changed), self.assertRaisesRegex(ValueError, 'Unsupported'):
                    PolicyProgram()
        changed = self.changed(wrapper, 'if bankruptcy:', 'if bankruptcy:')
        changed.__globals__['entry_valuation'] = books.entry_valuation
        changed.__globals__['ebitda_yield_and_multiple'] = lambda *args: (0, 0)
        with patch.object(books, 'snapshot', changed), self.assertRaisesRegex(ValueError, 'Unsupported'):
            PolicyProgram()

    def test_supported_status_mutation_still_changes_decision_identity(self):
        before = PolicyProgram()
        changed = self.changed(books.snapshot, "status='Last available price'", "status='Stopped'" )
        changed.__globals__['entry_valuation'] = books.entry_valuation
        changed.__globals__['ebitda_yield_and_multiple'] = books.ebitda_yield_and_multiple
        with patch.object(books, 'snapshot', changed):
            after = PolicyProgram()
            self.assertNotEqual(before.signature, after.signature)
            self.assertNotEqual(before.decisions.signature, after.decisions.signature)
            self.assertIn('Stopped', ast.unparse(after.snapshot_tree))

    def test_guard_mutation_changes_normalized_entry_decisions_and_identity(self):
        before=PolicyProgram()
        changed=self.changed(books.entry_valuation,'cap<=0','cap<=160000000')
        with patch.object(books,'entry_valuation',changed):
            after=PolicyProgram()
            self.assertNotEqual(before.signature,after.signature)
            self.assertNotEqual(before.field_schema,after.field_schema)
            self.assertNotEqual(before.decisions.signature,after.decisions.signature)
            self.assertIn('160000000',ast.unparse(after.snapshot_tree))
            statement=dict(fiscal=date(2014,6,30),market_cap=150e6,enterprise=180e6,**{'yield':1/3})
            self.assertIsNone(books.entry_valuation(statement,date(2015,1,2),lambda day,*args:(day,10.)))

    def test_unsupported_helper_and_wrapper_forms_fail_before_projection(self):
        cases=[(books.entry_valuation,'statement, entry_day, lookup','statement, entry_day, lookup, extra=None'),
               (books.entry_valuation,"fiscal_px=lookup", "fiscal_px=unknown"),
               (books.entry_valuation,'return fiscal_px,entry_px,cap,ev,ebitda','return entry_px,fiscal_px,cap,ev,ebitda'),
               (books.entry_valuation,"'price',False,7","'price',False,10"),
               (books.entry_valuation,"    ebitda=", "    if cap>1:\n        cap=2\n    ebitda="),
               (books.snapshot,"    start=", "    if cap>1:\n        cap=2\n    start="),
               (books.snapshot,'if valuation is None:','if not valuation:'),
               (books.snapshot,'fiscal_px,entry_px,cap,ev,ebitda=valuation','fiscal_px,entry_px,ev,cap,ebitda=valuation')]
        for function,before,after in cases:
            with self.subTest(before=before):
                changed=self.changed(function,before,after)
                # Wrapper dependency must still refer to the actual helper.
                changed.__globals__['entry_valuation']=books.entry_valuation
                with patch.object(books,function.__name__,changed),self.assertRaisesRegex(ValueError,'Unsupported'):
                    PolicyProgram()

    def test_async_financial_functions_fail_before_projection(self):
        for function in (books.entry_valuation,books.snapshot,books.benchmark_return,books.yield_spread):
            with self.subTest(function=function.__name__):
                changed=self.changed(function,'def '+function.__name__,'async def '+function.__name__)
                changed.__globals__['entry_valuation']=books.entry_valuation
                with patch.object(books,function.__name__,changed),self.assertRaisesRegex(ValueError,'function kind'):
                    PolicyProgram()

    def test_named_arithmetic_rejects_unknown_dependencies(self):
        before=PolicyProgram()
        changed=self.changed(books.benchmark_return,'exit_price/entry_price-1','exit_price/entry_price-2')
        with patch.object(books,'benchmark_return',changed):
            after=PolicyProgram()
            self.assertEqual(after.spy_return(10.,20.),0.)
            self.assertNotEqual(before.signature,after.signature)
        changed=self.changed(books.yield_spread,'earnings_yield-treasury_yield','unknown(earnings_yield)')
        with patch.object(books,'yield_spread',changed),self.assertRaisesRegex(ValueError,'Unsupported'):
            PolicyProgram()


if __name__=='__main__':unittest.main()
