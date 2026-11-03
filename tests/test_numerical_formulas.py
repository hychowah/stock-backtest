"""Independent arithmetic expectations and complete reference/Numba comparison.

All financial inputs are synthetic. SQLite fixtures close explicitly. Native
execution uses the existing outer offline guard; process coverage remains WSL.
"""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

import struct
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from backtest import observations
from backtest.application import calculations, scalar_execution
from backtest.engines.numerical import formulas as f, identity, policy
from backtest.variables import definitions as d, evaluation as e, library, reference as r
import test_observations as source
import test_variable_definitions as language
from test_variable_evaluation import parameter, annual, program
from test_scalar_execution import Fixture


def exact(value):
    """Compare every floating-point bit, including the sign of zero."""
    if type(value) is float:
        return ('binary64', struct.pack('>d', value).hex())
    if isinstance(value, dict):
        return {key: exact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [exact(item) for item in value]
    return value


class FormulaTests(unittest.TestCase):
    def setUp(self):
        self.fixture = source.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.evaluator = f.Evaluator()
        self.addCleanup(self.evaluator.close)

    def roots(self, **changes):
        return [{**dict(symbol='A', pool='legacy', mode='historical', date=self.fixture.root_date), **changes}]

    def error(self, code, call, *args, **kwargs):
        with self.assertRaises(d.FormulaError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def compare_plan(self, plan, view=None, evaluator=None):
        view = view or self.fixture.view()
        reference = r.evaluate(plan, view).to_dict()
        numerical = (evaluator or self.evaluator).evaluate(plan, view).to_dict()
        self.assertEqual(reference['identity']['plan'], numerical['identity']['plan'])
        self.assertNotEqual(reference['calculation_identity'], numerical['calculation_identity'])
        self.assertEqual(numerical['identity']['policy']['backend'], 'numba-formulas')
        self.assertFalse(numerical['identity']['policy']['compiler']['fastmath'])
        for block in (reference, numerical):
            block.pop('identity')
            block.pop('calculation_identity')
        self.assertEqual(exact(reference), exact(numerical))
        return numerical

    def compare(self, expression, unit='scalar', *, roots=None, view=None):
        display = 'usd' if unit == 'USD' else 'number'
        return self.compare_plan(r.plan(program(expression, unit, display), roots or self.roots()), view)

    def test_callable_capability_is_exact_and_bounded_application_is_declared(self):
        capability = f.capabilities()
        # Direct reference observations have expanded; numerical admission has not.
        self.assertEqual(capability['parameter_ids'], ['annual.revenue', 'annual.operating_income',
            'annual.operating_margin', 'market.enterprise_value'])
        self.assertEqual(set(capability['operations']), {'constant','parameter','annual','ref','at','lookback','neg','add','sub','mul','div'})
        self.assertTrue(capability['application_admission'])
        self.assertFalse(capability['eager']);self.assertFalse(capability['sample_preview'])
        self.assertEqual(capability['limits'], dict(r.CEILINGS))
        capability['parameter_ids'].clear()
        self.assertEqual(len(f.capabilities()['parameter_ids']), 4)

    def test_binary64_order_has_independent_expected_values(self):
        c, b = language.constant, language.binary
        cases = [(b('add', b('add', c('1e16'), c('-1e16')), c('1')), 1.),
                 (b('add', c('1e16'), b('add', c('-1e16'), c('1'))), 0.),
                 (b('sub', c('7'), c('9')), -2.),
                 (dict(op='neg', arg=c('0')), -0.),
                 (b('div', c('0'), c('-3')), -0.),
                 (b('mul', c('5e-324'), c('1')), 5e-324),
                 (b('mul', c('5e-324'), c('0.1')), 0.)]
        for expression, expected in cases:
            with self.subTest(expected=expected):
                block = self.compare(expression)
                self.assertEqual(exact(block['results'][0]['value']), exact(expected))

    def test_signed_division_zero_and_nonfinite_cases(self):
        c, b = language.constant, language.binary
        for left, right, expected in [('-12','-3',4.), ('12','-3',-4.)]:
            self.assertEqual(self.compare(b('div', c(left), c(right)))['results'][0]['value'], expected)
        for denominator in (c('0'), dict(op='neg',arg=c('0'))):
            result = self.compare(b('div',c('12'),denominator))['results'][0]
            self.assertEqual((result['value'],result['valid'],result['reason']), (None,False,'ZERO_DENOMINATOR'))
        for expression in [b('mul',c('1e308'),c('2')),b('add',c('1e308'),c('1e308')),
                           b('div',c('1e308'),c('5e-324'))]:
            self.assertEqual(self.compare(expression)['results'][0]['reason'], 'NONFINITE_RESULT')

    def test_all_four_parameters_keep_provider_values_and_evidence(self):
        for name, expected, unit in [('annual.revenue',100.,'USD'),
                ('annual.operating_income',20.,'USD'),('annual.operating_margin',.2,'scalar'),
                ('market.enterprise_value',180e6,'USD')]:
            block = self.compare(parameter(name), unit)
            self.assertEqual(block['results'][0]['value'], expected)
            self.assertEqual(block['observations']['results'][0]['parameter'], name)

    def test_annual_mean_uses_oldest_first_and_count_one_preserves_zero(self):
        for year, income in [(2012,1e16),(2013,-1e16),(2014,1.)]:
            self.fixture.annual[f'{year}-06-30'] = source.annual(1.,income)
        block = self.compare(annual())
        self.assertEqual(block['operations'][0]['inputs'], [1e16,-1e16,1.])
        self.assertEqual(block['results'][0]['value'], 1./3)
        for year, income in [(2012,2**53),(2013,1.),(2014,-(2**53))]:
            self.fixture.annual[f'{year}-06-30'] = source.annual(1.,income)
        self.assertEqual(self.compare(annual(name='annual.operating_income'),'USD')['results'][0]['value'],0.)
        self.fixture.annual['2014-06-30'] = source.annual(1.,-0.)
        self.assertEqual(exact(self.compare(annual(count=1))['results'][0]['value']),exact(-0.))

    def test_annual_extrema_retain_first_equal_signed_zero_and_full_history(self):
        self.fixture.reports = [source.statement(f'{year}-06-30') for year in range(2005,2015)]
        self.fixture.annual = {f'{year}-06-30':source.annual(1.,-0. if year==2005 else 0.) for year in range(2005,2015)}
        for stat in ('min','max'):
            block = self.compare(annual(stat,10))
            self.assertEqual(exact(block['results'][0]['value']),exact(-0.))
            self.assertEqual(len(block['operations'][0]['inputs']),10)

    def test_annual_missing_year_and_nonfinite_fold_stay_unavailable(self):
        self.fixture.annual.pop('2013-06-30')
        for stat in ('mean','min','max'):
            block=self.compare(annual(stat))
            self.assertEqual(block['results'][0]['reason'],'MISSING_FISCAL_YEAR')
            self.assertEqual(len(block['operations'][0]['inputs']),3)
        for year in (2012,2013,2014):
            self.fixture.annual[f'{year}-06-30']=source.annual(1.,1e308)
        self.assertEqual(self.compare(annual())['results'][0]['reason'],'NONFINITE_RESULT')

    def test_missing_first_operand_and_zero_multiplication_preserve_reasons(self):
        self.fixture.annual['2014-06-30']['revenue']=source.state(None,'CONFLICTING_INPUT')
        self.fixture.annual['2014-06-30']['operatingIncome']=source.state(None,'NON_USD_INPUT')
        b,c=language.binary,language.constant
        for left,right,reason in [(parameter(),parameter('annual.operating_income'),'CONFLICTING_INPUT'),
                (parameter('annual.operating_income'),parameter(),'NON_USD_INPUT')]:
            self.assertEqual(self.compare(b('add',left,right),'USD')['results'][0]['reason'],reason)
        for left,right in [(parameter(),c('0')),(c('0'),parameter())]:
            block=self.compare(b('mul',left,right),'USD')
            self.assertEqual(block['results'][0]['reason'],'CONFLICTING_INPUT')
            self.assertIn(None,block['operations'][-1]['inputs'])
            self.assertIn(0.,block['operations'][-1]['inputs'])

    def test_provider_denominator_nonfinite_and_root_admission_are_unchanged(self):
        self.fixture.annual['2014-06-30']=source.annual(-100.,-20.)
        self.assertEqual(self.compare(parameter('annual.operating_margin'))['results'][0]['reason'],'NONPOSITIVE_DENOMINATOR')
        self.assertEqual(self.compare(language.binary('div',parameter('annual.operating_income'),parameter()))['results'][0]['value'],.2)
        self.fixture.annual['2014-06-30']['revenue']=source.state(None,'NONFINITE_RESULT')
        self.assertEqual(self.compare(parameter(),'USD')['results'][0]['reason'],'NONFINITE_RESULT')
        roots=self.roots(mode='latest',date=self.fixture.latest_date)
        for expression,unit in [(language.constant('12'),'scalar'),(parameter(),'USD')]:
            block=self.compare(expression,unit,roots=roots,view=self.fixture.view(admitted=False))
            self.assertEqual(block['results'][0]['reason'],'ROOT_NOT_ADMITTED')

    def test_temporal_references_and_month_clamping_keep_contexts(self):
        self.fixture.root_date='2015-03-31'
        base=language.entry(language.definition(parameter(),'USD','usd'),'saved:revenue')
        outer=language.entry(language.definition(dict(op='lookback',months=1,arg=dict(op='lookback',months=1,arg=language.reference(base))),'USD','usd'),'draft:history')
        compiled=d.validate(language.bundle(base,outer))
        block=self.compare_plan(r.plan(compiled,self.roots()))
        self.assertEqual([item['date'] for item in block['observations']['contexts']],['2015-03-31','2015-02-28','2015-01-28'])
        block=self.compare(dict(op='at',date='2013-12-31',arg=parameter('annual.operating_income')),'USD')
        self.assertEqual(block['results'][0]['value'],0.)
        self.assertEqual(block['observations']['results'][0]['anchor'],'2013-06-30')
        self.fixture.root_date='2024-05-31'
        block=self.compare(dict(op='lookback',months=3,arg=language.constant()))
        self.assertEqual(block['observations']['contexts'][1]['date'],'2024-02-29')

    def test_equal_date_latest_and_derived_valuation_remain_distinct(self):
        ev=parameter('market.enterprise_value')
        block=self.compare(language.binary('sub',ev,dict(op='at',date=self.fixture.latest_date,arg=ev)),
            'USD',roots=self.roots(mode='latest',date=self.fixture.latest_date))
        self.assertEqual(block['results'][0]['value'],10e6)
        self.assertEqual([item['members'][0]['value'] for item in block['observations']['results']],[190e6,180e6])

    def test_shared_dependencies_repeated_roots_and_requests_keep_slots(self):
        base=language.entry(language.definition(parameter(),'USD','usd'),'saved:base')
        used=language.entry(language.definition(language.binary('add',language.reference(base),language.reference(base)),'USD','usd'),'draft:twice')
        compiled=d.validate(language.bundle(base,used,roots=[language.root(used),language.root(base),language.root(used)]))
        plan=r.plan(compiled,self.roots()*2)
        self.assertEqual(len(plan.to_dict()['tasks']),4)
        block=self.compare_plan(plan)
        self.assertEqual([item['value'] for item in block['results']],[200.,100.,200.]*2)
        self.assertEqual([item['request'] for item in block['results']],[0,0,0,1,1,1])

    def test_exact_old_revisions_survive_library_deletion_and_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'variables.sqlite';store=library.Store(path)
            first=store.create('First',language.definition(language.constant('1e100')))
            second=store.edit(first['variable_id'],1,language.definition(language.constant('2')))
            capture=store.capture([language.root(first),language.root(second),language.root(first)])
            store.delete(second['variable_id'],second['version']);path.unlink()
            restored=d.require_program(capture.program)
            self.assertEqual([root['revision'] for root in restored['bundle']['roots']],
                [first['revision'],second['revision'],first['revision']])
            with patch.object(d,'validate',side_effect=AssertionError('No raw restoration')):
                block=self.compare_plan(r.plan(capture.program,self.roots()))
            self.assertEqual([item['value'] for item in block['results']],[1e100,2.,1e100])

    def test_malformed_plans_fail_before_compiler_or_financial_access(self):
        valid=r.plan(program(),self.roots())
        for field,value in [('tasks',[]),('outputs',[]),('provider',{}),('version',True)]:
            submitted=valid.to_dict();submitted[field]=value;view=Mock()
            self.error('INVALID_SHAPE',self.evaluator.evaluate,r.EvaluationPlan(d.canonical(submitted)),view)
            self.assertEqual(view.mock_calls,[])
        self.assertIsNone(self.evaluator._kernel)
        self.assertEqual(self.evaluator.cache,{})

    def test_forged_operation_and_future_context_fail_without_inputs(self):
        self.error('FUTURE_DATE',r.plan,program(dict(op='at',date='2015-01-03',arg=language.constant())),self.roots())
        checked=r.plan(program(),self.roots()).to_dict()
        checked['program']['nodes'][0]['op']='calendar'
        view=Mock()
        with patch.object(e,'require_plan',return_value=checked):
            self.error('INVALID_SHAPE',self.evaluator.evaluate,r.EvaluationPlan('{}'),view)
        self.assertEqual(view.mock_calls,[])
        self.assertIsNone(self.evaluator._kernel)

    def test_resources_and_compiler_are_prepared_before_input_validation(self):
        plan=r.plan(program(),self.roots());view=self.fixture.view();events=[]
        original_warm=self.evaluator._warm;validate=view.validate
        def warmed(checkpoint):
            original_warm(checkpoint);events.append('warmed')
        def validated():
            self.assertTrue(self.evaluator._kernel.nopython_signatures)
            events.append('input');return validate()
        with patch.object(self.evaluator,'_warm',side_effect=warmed),patch.object(view,'validate',side_effect=validated):
            self.evaluator.evaluate(plan,view)
        self.assertEqual(events[0],'warmed')
        self.assertGreater(self.evaluator.stats['peak_workspace_bytes'],0)

    def test_buffer_limit_fails_before_allocation_compilation_and_observation(self):
        plan=r.plan(program(),self.roots());view=Mock()
        with patch.object(e,'workspace_limit',return_value=1),patch.object(f,'_lower',side_effect=AssertionError('No buffers')):
            self.error('WORK_LIMIT',self.evaluator.evaluate,plan,view)
        self.assertEqual(view.mock_calls,[])
        self.assertIsNone(self.evaluator._kernel)
        self.assertEqual(self.evaluator.cache,{})
        for arguments in ({'cache_bytes':True},{'cache_bytes':f.MAX_CACHE_BYTES+1},
                {'chunk_steps':0},{'chunk_steps':257}):
            self.error('INVALID_SHAPE',f.Evaluator,**arguments)

    def test_evidence_exhaustion_returns_no_partial_block(self):
        self.fixture.annual['2012-06-30']['revenue']['rows']=[dict(index=i,sha256='c'*64) for i in range(500)]
        plan=r.plan(program(parameter(),'USD','usd'),self.roots(),dict(retained_bytes=20000))
        with self.assertRaises((ValueError,d.FormulaError,observations.ObservationError)):
            self.evaluator.evaluate(plan,self.fixture.view())
        self.assertEqual(self.evaluator.stats['native_chunks'],0)

    def test_cancellation_between_annual_members_and_final_encoding(self):
        plan=r.plan(program(annual()),self.roots());view=self.fixture.view()
        with f.Evaluator(chunk_steps=1) as evaluator:
            def cancelled():
                if evaluator.stats['native_chunks']==1:
                    raise RuntimeError('Private annual cancellation')
            with self.assertRaisesRegex(RuntimeError,'Private annual cancellation'):
                evaluator.evaluate(plan,view,cancelled)
            self.assertEqual(evaluator.stats['native_chunks'],1)
        self.assertEqual(evaluator.stats['retained_tape_bytes'],0)
        self.assertIsNone(evaluator._kernel)
        original=e._encode
        def fail_final(value,maximum,checkpoint=lambda:None):
            if isinstance(value,dict) and value.get('format')=='formula-evaluation' and value['operations']:
                raise RuntimeError('Private encoding cancellation')
            return original(value,maximum,checkpoint)
        with patch.object(e,'_encode',side_effect=fail_final),self.assertRaisesRegex(RuntimeError,'Private encoding cancellation'):
            self.evaluator.evaluate(plan,view)

    def test_cancellation_before_compile_and_changed_signature_fail(self):
        plan=r.plan(program(),self.roots());view=Mock()
        def cancel():raise RuntimeError('Private preflight cancellation')
        with self.assertRaisesRegex(RuntimeError,'Private preflight cancellation'):
            self.evaluator.evaluate(plan,view,cancel)
        self.assertEqual(view.mock_calls,[])
        self.assertIsNone(self.evaluator._kernel)
        self.compare_plan(plan)
        self.evaluator._signatures=()
        with self.assertRaisesRegex(RuntimeError,'signature changed'):
            self.evaluator.evaluate(plan,view)
        self.assertEqual(view.mock_calls,[])

    def test_stale_source_environment_and_inputs_abort_without_completion(self):
        plan=r.plan(program(),self.roots());view=Mock()
        for owner,field in [(f,'_LOADED_FORMULAS'),(e,'_LOADED_EVALUATION'),(identity,'_LOADED_IDENTITY')]:
            with patch.object(owner,field,'changed'):
                self.error('STALE_INPUT_GENERATION',self.evaluator.evaluate,plan,view)
        self.assertEqual(view.mock_calls,[])
        self.compare_plan(plan)
        environment=identity.compiler_environment(1);environment['threads']=2
        with patch.object(identity,'compiler_environment',return_value=environment):
            self.error('STALE_INPUT_GENERATION',self.evaluator.evaluate,plan,view)
        actual=self.fixture.view();original=observations.observe
        def replaced(*args,**kwargs):
            result=original(*args,**kwargs);actual.identity='changed';return result
        with patch.object(observations,'observe',side_effect=replaced):
            self.error('STALE_INPUT_GENERATION',self.evaluator.evaluate,plan,actual)

    def test_source_and_input_changes_during_final_encoding_are_rechecked(self):
        plan=r.plan(program(),self.roots());view=self.fixture.view();original=e._encode
        def changed(value,maximum,checkpoint=lambda:None):
            document=original(value,maximum,checkpoint)
            if isinstance(value,dict) and value.get('format')=='formula-evaluation' and value['operations']:
                self.fixture.stale=True
            return document
        with patch.object(e,'_encode',side_effect=changed),self.assertRaisesRegex(ValueError,'stale'):
            self.evaluator.evaluate(plan,view)
        self.fixture.stale=False
        with tempfile.TemporaryDirectory() as folder:
            private=Path(folder)/'formulas.py';private.write_bytes(Path(f.__file__).read_bytes())
            def edited(value,maximum,checkpoint=lambda:None):
                document=original(value,maximum,checkpoint)
                if isinstance(value,dict) and value.get('format')=='formula-evaluation' and value['operations']:
                    private.write_bytes(private.read_bytes()+b'\n# private edit\n')
                return document
            with patch.object(f,'__file__',str(private)),patch.object(e,'_encode',side_effect=edited):
                self.error('STALE_INPUT_GENERATION',self.evaluator.evaluate,plan,view)

    def test_tape_reuse_reobserves_values_and_binds_whole_ordered_plan(self):
        p=program(parameter(),'USD','usd');plan=r.plan(p,self.roots())
        first=self.evaluator.evaluate(plan,self.fixture.view()).to_dict()
        self.fixture.annual['2014-06-30']=source.annual(105.,20.)
        second=self.evaluator.evaluate(plan,self.fixture.view()).to_dict()
        self.assertEqual((first['results'][0]['value'],second['results'][0]['value']),(100.,105.))
        self.assertNotEqual(first['calculation_identity'],second['calculation_identity'])
        self.fixture.root_date='2014-12-31'
        changed=self.evaluator.evaluate(r.plan(p,self.roots()),self.fixture.view()).to_dict()
        self.assertNotEqual(second['plan_revision'],changed['plan_revision'])
        self.assertEqual(self.evaluator.stats['tape_builds'],1)
        self.assertEqual(self.evaluator.stats['tape_hits'],2)
        self.assertEqual(self.evaluator.stats['kernel_compilations'],1)

    def test_cache_eviction_and_close_release_only_compiler_resources(self):
        view=self.fixture.view()
        with f.Evaluator(cache_bytes=1200) as evaluator:
            for number in range(5):
                self.compare_plan(r.plan(program(language.constant(str(number))),self.roots()),view,evaluator)
                self.assertLessEqual(evaluator.stats['retained_tape_bytes'],1200)
            self.assertGreater(evaluator.stats['tape_builds'],1)
        self.assertEqual(evaluator.cache,{})
        self.assertIsNone(evaluator._kernel)
        view.validate()
        with self.assertRaisesRegex(ValueError,'closed'):
            evaluator.evaluate(r.plan(program(),self.roots()),view)

    def test_multiple_provider_chunks_keep_complete_ordered_results(self):
        fixture=Fixture(300)
        self.addCleanup(fixture.db.close)
        capture=fixture.capture().to_dict()
        captured=library.VariableCapture(d.canonical(capture['variables'])).program
        roots=[dict(symbol=f'A{i:04d}',pool='cached',mode='historical',date='2015-01-02') for i in range(300)]
        plans=scalar_execution._plans(captured,roots,8*1024*1024,lambda:None)
        self.assertGreater(len(plans),1)
        values=[]
        with fixture.view() as view:
            for plan in plans:
                block=self.compare_plan(plan,view)
                values.extend(item['value'] for item in block['results'])
        self.assertEqual(values,[float(i+1) for i in range(300)])

    def test_public_application_and_direct_policy_reject_before_readiness(self):
        preparation=Mock();owner=calculations.Selectable(preparation)
        self.addCleanup(owner.close);self.addCleanup(owner.retire)
        options=dict(engine='experimental',strategy={})
        for call in [lambda:owner.preflight(options),lambda:owner.calculate_into('latest',options,Mock(),None,None)]:
            self.error('INVALID_STRATEGY',call)
        preparation.status.assert_not_called();preparation._runtime.assert_not_called()
        with self.assertRaises(d.FormulaError) as caught:
            policy.require_supported(options)
        self.assertEqual(caught.exception.code,'INVALID_STRATEGY')

    def test_original_import_and_real_dated_execution_without_numerical_packages(self):
        code=r'''
import importlib.abc,sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'numpy','numba','llvmlite'}:
            raise AssertionError('Original imported numerical dependency')
sys.meta_path.insert(0,Block())
from contextlib import nullcontext
from unittest.mock import patch
from backtest.application.original_calculations import Original
from backtest.variables import reference
from backtest.inputs import daily
from test_schedules import BacktestTests
fixture=BacktestTests('runTest');fixture.setUp()
owner=Original();owner.ready=lambda:True
try:
    with patch.object(owner,'_financial',return_value=nullcontext()),patch.object(daily,'connect',return_value=fixture.db):
        result=owner.calculate('custom',dict(start='2015-01-01',end='2015-07-01',months=3,rank_to=1,min_cap=0,min_ev=0),None,None)
    assert [period['portfolio'] for period in result['periods']]==[.5,-.5]
    assert not any(name.split('.')[0] in {'numpy','numba','llvmlite'} for name in sys.modules)
finally:
    owner.close();fixture.doCleanups()
'''
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(Path(__file__).resolve().parents[1])],
            capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':
    unittest.main()
