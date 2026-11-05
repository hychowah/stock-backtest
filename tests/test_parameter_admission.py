"""Unqualified semantics fail before Original or provider work."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import io
import subprocess
import unittest
from functools import wraps
from unittest.mock import Mock, patch
from backtest.variables import columns, definitions as d, parameters, library, selection
from backtest.application import strategy_requests as s, scalar_execution, variable_authoring
from backtest.application.original_calculations import Original
from test_variable_definitions import definition, constant, entry, root, bundle
from test_strategy_requests import intent, formula, condition
from test_parameter_contract import expanded

ROOTS=[dict(symbol='A',pool='cached',mode='historical',date='2015-01-02')]


def restrict_catalog_two(test):
    """Model a recognized catalog which Original has not qualified."""
    @wraps(test)
    def run(*args, **kwargs):
        original = frozenset(item for item in selection.QUALIFIED_NAMESPACES
                             if item[1] != parameters.V2)
        with patch.object(selection, 'QUALIFIED_NAMESPACES', original):
            return test(*args, **kwargs)
    return run


def capture(entries):
    return s.capture_strategy(intent(formula(entries[0])),submitted=entries)


def expanded_cases():
    yield [entry(expanded())]
    yield [entry(expanded(dict(op='parameter',id='annual.revenue'),'USD','usd'))]
    for identity,unit,display in (
        ('annual.net_income','USD','usd'),('annual.equity','USD','usd'),
        ('annual.net_acquisitions','USD','usd'),('market.volume','share','shares'),
        ('treasury.us_3m','scalar','percent'),('market.adjusted_price','USD/share','usd_per_share')):
        yield [entry(expanded(dict(op='parameter',id=identity),unit,display))]
    yield [entry(definition(),'old-root'),entry(expanded(),'unused-new')]


class AdmissionTests(unittest.TestCase):
    def error(self, callback):
        with self.assertRaises(d.FormulaError) as caught:callback()
        self.assertEqual(caught.exception.code,'UNSUPPORTED_CAPABILITY')

    def test_every_v2_case_restores_and_obeys_the_original_gate(self):
        for entries in expanded_cases():
            with self.subTest(parameter=entries[0]['definition']['expression']):
                captured=capture(entries)
                self.assertEqual(s.require_strategy(captured),captured.to_dict())
                variable=library.VariableCapture(d.canonical(captured.to_dict()['variables']))
                self.assertEqual(library.require_capture(variable),variable.to_dict())
                program=variable.program
                self.assertEqual(d.require_program(program),program.to_dict())
                self.assertEqual(columns.require_program(program),program.to_dict())
                self.assertEqual(selection.require_program(program),program.to_dict())
                options=dict(strategy=captured.to_dict(),engine='original')
                self.assertEqual(s.check_options(options),captured.to_dict())

    @restrict_catalog_two
    def test_application_modes_reject_before_readiness_or_financial_input(self):
        owner=Original()
        with patch.object(owner,'ready',side_effect=AssertionError('No readiness')), \
             patch.object(owner,'_financial',side_effect=AssertionError('No financial input')):
            for entries in expanded_cases():
                captured=capture(entries).to_dict()
                options=dict(strategy=captured,engine='original')
                for mode in ('latest','january','custom','random'):
                    self.error(lambda:owner.calculate_into(mode,options,io.BytesIO(),None,None))
                    self.error(lambda:owner.calculate(mode,options,None,None))
                self.error(lambda:s.check_request(dict(kind='random',options=options)))
                self.error(lambda:owner.preview(captured,ROOTS))
                self.error(lambda:owner.calculate_into('latest',dict(strategy=captured),io.BytesIO(),None,None))

    @restrict_catalog_two
    def test_preview_rejects_before_root_checks_or_evaluator(self):
        class Untouched:
            def __getattribute__(self, name):
                raise AssertionError('No view access before admission: ' + name)
        for entries in expanded_cases():
            captured=capture(entries)
            with patch.object(scalar_execution.columns,'require_roots',side_effect=AssertionError('No root checks')), \
                 patch.object(scalar_execution.columns,'Formulas',side_effect=AssertionError('No evaluator construction')):
                self.error(lambda:scalar_execution.check_preview(captured,ROOTS))
                self.error(lambda:scalar_execution.preview(captured,ROOTS,Untouched()))

    def test_column_evaluator_accepts_constants_old_inputs_and_unused_v2_definitions(self):
        # The column evaluator's own support check reaches input admission.
        # Qualified selection accepts or rejects the complete capture by its policy.
        for entries in (list(expanded_cases())[0],list(expanded_cases())[1],list(expanded_cases())[-1]):
            program=d.validate(bundle(*entries,roots=[root(entries[0])]))
            inputs=Mock();inputs.admit.side_effect=AssertionError('Column evaluation reached inputs')
            self.assertEqual(columns.require_program(program),program.to_dict())
            self.assertEqual(selection.require_program(program),program.to_dict())
            inputs.admit.assert_not_called()
            with self.assertRaisesRegex(AssertionError,'Column evaluation reached inputs'):
                scalar_execution.evaluate_preview(program,ROOTS,inputs)
            inputs.admit.assert_called_once()

    @restrict_catalog_two
    def test_restoration_and_evaluator_support_grant_no_qualification(self):
        cases=list(expanded_cases())
        for entries in (cases[0],cases[1],cases[-1]):
            captured=capture(entries)
            # Semantic restoration stays independent of runtime support.
            self.assertEqual(s.require_strategy(captured),captured.to_dict())
            program=library.VariableCapture(d.canonical(captured.to_dict()['variables'])).program
            self.assertEqual(columns.require_program(program),program.to_dict())
            self.error(lambda:selection.require_program(program))
            self.error(lambda:s.check_options(dict(strategy=captured.to_dict(),engine='original')))

    @restrict_catalog_two
    def test_callable_executor_rejects_before_scope_view_or_sink_access(self):
        class Untouched:
            def __getattribute__(self, name):
                raise AssertionError('No database/view access before admission: ' + name)
        cases=list(expanded_cases())
        for entries in (cases[0],cases[1],cases[-1]):
            sink=Mock()
            with patch.object(scalar_execution,'scope_rows',
                    side_effect=AssertionError('No prepared scope before admission')) as scope:
                self.error(lambda:scalar_execution.Executor(capture(entries),Untouched(),sink))
                scope.assert_not_called()
            sink.assert_not_called()

    def test_recognized_unqualified_parameters_differ_from_unknown_parameters(self):
        for entries in list(expanded_cases())[1:-1]:
            program=d.validate(bundle(*entries,roots=[root(entries[0])]))
            identity=entries[0]['definition']['expression']['id']
            with self.subTest(parameter=identity), patch.object(selection,'QUALIFIED_PARAMETERS',
                    tuple(item for item in selection.QUALIFIED_PARAMETERS if item!=identity)):
                self.assertEqual(columns.require_program(program),program.to_dict())
                with self.assertRaises(d.FormulaError) as caught:selection.require_program(program)
                self.assertEqual(caught.exception.code,'UNSUPPORTED_CAPABILITY')
                self.assertEqual(caught.exception.path,program.to_dict()['nodes'][0]['path'])
        with self.assertRaises(d.FormulaError) as caught:
            entry(expanded(dict(op='parameter',id='annual.unknown')))
        self.assertEqual((caught.exception.code,caught.exception.path),('UNKNOWN_PARAMETER','/expression/id'))

    def test_legacy_catalog_stays_four_while_expanded_authoring_supports_shares(self):
        expected=['annual.revenue','annual.operating_income','annual.operating_margin','market.enterprise_value']
        self.assertEqual(len(columns.catalog()),77)
        self.assertEqual([item['id'] for item in columns.catalog()][:4],expected)
        value=variable_authoring.catalog()
        self.assertEqual([item['id'] for item in value['parameters']],expected)
        self.assertEqual(value['displays']['share'],parameters.units(parameters.V3)['share']['displays'])
        for catalog in (parameters.V1,parameters.V2):
            quantity=entry(dict(definition(constant('100','USD'),'USD','usd'),parameter_catalog=catalog))
            captured=s.capture_strategy(intent(formula(quantity),[condition(formula(quantity),'0.0001','usd_million')]),submitted=[quantity])
            self.assertEqual(captured.to_dict()['selection']['conditions'][0]['threshold'],dict(value='100',unit='USD'))
        shares=entry(expanded(constant('100','share'),'share','shares'))
        captured=s.capture_strategy(intent(formula(shares),[condition(formula(shares),'1.25e2','shares')]),submitted=[shares])
        self.assertEqual(captured.to_dict()['selection']['conditions'][0]['threshold'],dict(value='125',unit='share'))
        self.assertEqual(s.require_strategy(captured),captured.to_dict())

    def test_new_semantic_source_changes_current_policy_identity(self):
        first=d.policy_fingerprint()
        with patch.object(parameters,'policy_fingerprint',return_value='b'*64):
            self.assertNotEqual(d.policy_fingerprint(),first)
        self.assertIsInstance(d.policy_fingerprint(),str)

    def test_semantic_validation_restore_and_original_admission_need_no_optional_packages(self):
        code='''import importlib.abc,sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,name,*args):
  if name.split('.')[0] in ('numpy','numba','llvmlite'):raise AssertionError(name)
sys.meta_path.insert(0,Block())
from test_parameter_admission import expanded_cases,capture
from backtest.application import strategy_requests as s
from backtest.variables import library,definitions as d,columns,selection
for entries in expanded_cases():
 c=capture(entries);s.require_strategy(c)
 program=library.VariableCapture(d.canonical(c.to_dict()['variables'])).program
 columns.require_program(program)
 selection.require_program(program)
'''
        subprocess.run([sys.executable,'-B','-c',code],cwd=Path(__file__).resolve().parent,
                       env={**__import__('os').environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1])},check=True)


if __name__=='__main__':unittest.main()
