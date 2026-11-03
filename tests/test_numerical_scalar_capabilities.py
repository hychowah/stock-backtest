"""Financial-free declared support and explicit bounded numerical admission."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import io
import json
from copy import deepcopy
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock,patch

from backtest.application import strategy_requests,calculations,candidate_calculations,original_calculations
from backtest.engines.numerical import formula_capabilities,formulas,policy
from backtest.engines.numerical.runtime import NumericalRuntime
from backtest.engines.numerical.session import Session
from backtest.variables import library,definitions,reference
from backtest.variables import selection as original_selection
from backtest import observations
import test_strategy_requests as requests
import test_variable_definitions as language

ROOT=Path(__file__).resolve().parents[1]


class CapabilityTests(unittest.TestCase):
    def capture(self):
        authored=language.entry(language.definition(language.binary('div',
            language.constant('1'),language.constant('2'))),'capability:old')
        return strategy_requests.capture_strategy(requests.intent(requests.formula(authored)),submitted=[authored])

    def owner(self):
        preparation=Mock()
        owner=calculations.Selectable(preparation)
        self.addCleanup(owner.retire);self.addCleanup(owner.close)
        return owner,preparation

    def test_declaration_matches_compiler_and_is_detached(self):
        value=formula_capabilities.capabilities()
        self.assertEqual(value,formulas.capabilities())
        self.assertEqual(set(formula_capabilities.IMPLEMENTED_OPERATIONS),set(formulas._OPS))
        self.assertEqual(set(formula_capabilities.IMPLEMENTED_PARAMETERS),set(formulas._PARAMETERS))
        self.assertTrue(set(value['operations']) <= set(formulas._OPS))
        self.assertTrue(set(value['parameter_ids']) <= set(formulas._PARAMETERS))
        self.assertEqual(value['application_modes'],['latest','january','custom','random'])
        self.assertFalse(value['eager']);self.assertFalse(value['sample_preview'])
        original_count=len(value['parameter_ids']);value['parameter_ids'].clear()
        self.assertEqual(len(formula_capabilities.capabilities()['parameter_ids']),original_count)
        capture=self.capture()
        program=library.VariableCapture(definitions.canonical(capture.to_dict()['variables'])).program
        self.assertEqual(formula_capabilities.require_program(program),definitions.require_program(program))

    def test_supported_capture_preserves_exact_content_and_original_default(self):
        capture=self.capture().to_dict()
        for engine in ('original','experimental'):
            self.assertEqual(strategy_requests.check_options(dict(strategy=capture,engine=engine)),capture)
        self.assertEqual(strategy_requests.check_options(dict(strategy=capture)),capture)
        owner,preparation=self.owner()
        self.assertEqual(owner.preflight(dict(strategy=capture)),'original')
        self.assertEqual(owner.preflight(dict(strategy=capture,engine='experimental')),'experimental')
        preparation.status.assert_not_called();preparation._runtime.assert_not_called()

    def test_future_recognition_does_not_expand_either_qualified_gate(self):
        captured=library.VariableCapture(definitions.canonical(self.capture().to_dict()['variables'])).program
        checked=definitions.require_program(captured)
        future_namespace=deepcopy(checked)
        extra=deepcopy(future_namespace['bundle']['definitions'][0])
        extra['definition']['version']=4
        future_namespace['bundle']['definitions'].append(extra)
        future_parameter=deepcopy(checked)
        future_parameter['nodes'].append(dict(op='parameter',parameter='annual.future_probe',path='/future'))
        with patch.object(observations, 'catalog', return_value=observations.catalog()+[dict(id='annual.future_probe')]), \
             patch.object(formula_capabilities, 'IMPLEMENTED_PARAMETERS', formula_capabilities.IMPLEMENTED_PARAMETERS+('annual.future_probe',)), \
             patch.object(reference, 'require_program', side_effect=AssertionError('No reference or financial work')):
            for projection in (future_namespace, future_parameter):
                with patch.object(definitions, 'require_program', return_value=projection):
                    for gate in (original_selection.require_program,formula_capabilities.require_program):
                        with self.subTest(gate=gate.__module__, future=projection is future_namespace), \
                             self.assertRaises(definitions.FormulaError) as caught:
                            gate(captured)
                        self.assertEqual(caught.exception.code,'UNSUPPORTED_CAPABILITY')

    def test_each_definition_catalog_combination_uses_the_declared_gate(self):
        expanded = 3 in formula_capabilities.capabilities()['definition_versions']
        for version in (1, 2, 3):
            for catalog in ('financial-parameters/1', 'financial-parameters/2', 'financial-parameters/3'):
                definition = language.definition(language.constant('1'))
                definition.update(version=version, parameter_catalog=catalog)
                program = definitions.validate(language.bundle(language.entry(definition)))
                for gate in (original_selection.require_program, formula_capabilities.require_program):
                    with self.subTest(version=version, catalog=catalog, gate=gate.__module__):
                        if expanded or (version == 1 and catalog == 'financial-parameters/1'):
                            self.assertEqual(gate(program), program.to_dict())
                        else:
                            with self.assertRaises(definitions.FormulaError) as caught:
                                gate(program)
                            self.assertEqual(caught.exception.code, 'UNSUPPORTED_CAPABILITY')

    def test_callable_compiler_uses_the_declared_subset_before_observations(self):
        captured=library.VariableCapture(definitions.canonical(self.capture().to_dict()['variables'])).program
        plan=reference.plan(captured,[dict(symbol='A',pool='cached',mode='historical',date='2015-01-02')])
        view=Mock();view.validate.side_effect=AssertionError('No financial observation')
        field = 'QUALIFIED_OPERATIONS' if 3 in formula_capabilities.capabilities()['definition_versions'] else 'OPERATIONS'
        with formulas.Evaluator() as evaluator,patch.object(formula_capabilities,field,
                tuple(op for op in getattr(formula_capabilities,field) if op!='div')):
            with self.assertRaises(definitions.FormulaError) as caught:evaluator.evaluate(plan,view)
            self.assertEqual(caught.exception.code,'UNSUPPORTED_CAPABILITY')
            self.assertEqual(evaluator.stats['kernel_compilations'],0)
        view.validate.assert_not_called()

    def test_unsupported_subset_raw_alias_and_malformed_capture_precede_readiness(self):
        capture=self.capture().to_dict();owner,preparation=self.owner()
        field = 'QUALIFIED_OPERATIONS' if 3 in formula_capabilities.capabilities()['definition_versions'] else 'OPERATIONS'
        with patch.object(formula_capabilities,field,tuple(op for op in getattr(formula_capabilities,field) if op!='div')):
            with self.assertRaises(definitions.FormulaError) as caught:
                owner.calculate_into('latest',dict(strategy=capture,engine='experimental'),io.BytesIO(),None,None)
            self.assertEqual(caught.exception.code,'UNSUPPORTED_CAPABILITY')
            self.assertEqual(owner.preflight(dict(strategy=capture)),'original')
        for options in (dict(strategy={},engine='experimental'),dict(strategy=capture,engine='unknown'),
                        dict(formula={},engine='experimental'),dict(program=None),dict(variables=[])):
            with self.subTest(options=list(options)),self.assertRaises(ValueError):policy.require_supported(options)
        preparation.status.assert_not_called();preparation._runtime.assert_not_called()

    def test_eager_and_invalid_modes_reject_at_every_public_boundary_before_inputs(self):
        capture=self.capture().to_dict();owner,preparation=self.owner()
        candidate=owner.experimental
        for engine in ('original','experimental'):
            with self.assertRaises(ValueError):owner.calculate('latest',dict(strategy=capture,engine=engine),None,None)
        with self.assertRaises(ValueError):candidate.calculate('custom',dict(strategy=capture),None,None)
        runtime=object.__new__(NumericalRuntime);session=object.__new__(Session)
        for value in (runtime,session):
            with self.assertRaises(ValueError):value.calculate('custom',dict(strategy=capture),None,None)
        for value in (owner,candidate):
            with self.assertRaises(definitions.FormulaError) as caught:
                value.calculate_into('preview',dict(strategy=capture,engine='experimental'),io.BytesIO(),None,None)
            self.assertEqual(caught.exception.code,'UNSUPPORTED_CAPABILITY')
        preparation.status.assert_not_called();preparation._runtime.assert_not_called()

    def test_direct_original_and_numerical_entries_never_switch_a_pin(self):
        capture=self.capture().to_dict()
        original=original_calculations.Original();self.addCleanup(original.close)
        with patch.object(original,'_financial',side_effect=AssertionError('No input work')):
            with self.assertRaises(definitions.FormulaError):original.calculate_into('latest',
                dict(strategy=capture,engine='experimental'),io.BytesIO(),None,None)
        with self.assertRaises(definitions.FormulaError):policy.require_supported(dict(strategy=capture,engine='original'))

    def test_numerical_sample_preview_fails_before_parent_lifetime_or_financial_work(self):
        owner,preparation=self.owner();capture=self.capture().to_dict()
        with patch.object(owner.experimental,'parent_operation',side_effect=AssertionError('No lifetime work')):
            with self.assertRaises(definitions.FormulaError) as caught:owner.preview(capture,[],engine='experimental')
            self.assertEqual((caught.exception.code,caught.exception.path),('UNSUPPORTED_CAPABILITY','/engine'))
        with patch.object(owner.original,'_financial',side_effect=AssertionError('No financial work')):
            with self.assertRaises(definitions.FormulaError):owner.original.preview(capture,[],engine='experimental')
        preparation.status.assert_not_called();preparation._runtime.assert_not_called()

    def test_original_actual_scalar_execution_and_capability_inspection_without_optional_imports(self):
        code=r'''
import importlib.abc,sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'numpy','numba','llvmlite'}:raise AssertionError('Optional numerical import')
sys.meta_path.insert(0,Block())
from contextlib import nullcontext
from unittest.mock import Mock,patch
import io,json,sqlite3
from backtest.application.calculations import Selectable
from backtest.inputs import daily
from backtest import result_evidence
db=sqlite3.connect(sys.argv[2]);db.row_factory=sqlite3.Row
capture=json.loads(sys.argv[3]);preparation=Mock();preparation.status.return_value={'state':'current'}
owner=Selectable(preparation)
try:
    capabilities=owner.capabilities()
    assert capabilities['sample_preview']['engine']=='original'
    assert capabilities['engines'][1]['scalar']['formulas']['parameter_ids']==json.loads(sys.argv[4])
    with patch.object(owner.original,'_financial',return_value=nullcontext()),patch.object(daily,'connect',return_value=db),patch.object(daily,'fingerprint',return_value={'inputs':{'historical_through':'2015-01-05'}}):
        output=io.BytesIO()
        owner.calculate_into('custom',dict(strategy=capture,start='2015-01-02',end='2015-01-05',months=12),output,None,None)
        reader=result_evidence.open_reader(output,max_bytes=256*1024**2)
        assert reader.manifest['holdings']==5
    assert not any(name.split('.')[0] in {'numpy','numba','llvmlite'} for name in sys.modules)
finally:
    db.close();owner.close();owner.retire()
'''
        # Fixture preparation may use numerical test helpers. The fresh child
        # receives only SQLite bytes and captured intent, and blocks every
        # optional numerical import throughout capability inspection/execution.
        from test_scalar_execution import Fixture
        fixture=Fixture(12)
        try:
            capture=fixture.capture().to_dict()
            with TemporaryDirectory(prefix='cv-original-no-numerical-') as folder:
                path=Path(folder)/'daily.sqlite';target=sqlite3.connect(path)
                try:fixture.db.backup(target)
                finally:target.close()
                outcome=subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT),str(path),json.dumps(capture),json.dumps(formula_capabilities.capabilities()['parameter_ids'])],
                    capture_output=True,text=True)
        finally:fixture.db.close()
        self.assertEqual(outcome.returncode,0,outcome.stderr)


if __name__=='__main__':unittest.main()
