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

    def test_entry_valuation_needs_no_holding_or_exit_prices(self):
        statement=dict(fiscal=date(2014,6,30),market_cap=100e6,enterprise=150e6,**{'yield':.2})
        calls=[]
        def lookup(day,column,forward,slack):
            calls.append((day,column,forward,slack))
            self.assertEqual(column,'price')
            return day,10. if day==statement['fiscal'] else 20.
        fiscal,entry,cap,ev,ebitda=books.entry_valuation(statement,date(2015,1,2),lookup)
        self.assertEqual((cap,ev,ebitda),(200e6,250e6,30e6))
        self.assertEqual(calls,[(statement['fiscal'],'price',False,7),(date(2015,1,2),'price',True,4)])
        self.assertEqual((fiscal,entry),((statement['fiscal'],10.),(date(2015,1,2),20.)))

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

    def test_canonical_storage_has_no_original_engine_dependency(self):
        for path in (ROOT/'backtest/inputs').glob('*.py'):
            tree=ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom):
                    self.assertFalse((node.module or '').startswith(('scripts','tools','website','backtest.engines.original')),path)
        for path in (ROOT/'backtest').rglob('__init__.py'):
            self.assertTrue(all(isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) for n in ast.parse(path.read_text(encoding="utf-8")).body),path)
        for path in (ROOT/'backtest/engines/numerical').glob('*.py'):
            tree=ast.parse(path.read_text(encoding="utf-8"))
            self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr=='s' for n in ast.walk(tree)),path)


if __name__=='__main__':unittest.main()
