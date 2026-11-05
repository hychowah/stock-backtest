"""Synthetic complete-scope coverage and failure checks."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import unittest
from unittest.mock import patch
from backtest.application import variable_coverage as coverage, scalar_execution
from backtest.variables import definitions
from test_scalar_execution import Fixture, scopes as prepared_scopes
import test_strategy_requests as requests
import test_variable_definitions as language
from backtest.application import strategy_requests
from backtest.variables import library
from backtest.inputs import facts
from backtest.runtime import backtest_control
from backtest.application.original_calculations import Original
from prepared_inputs_fixture import PreparedInputs, history

class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.fixture=Fixture(4);self.addCleanup(self.fixture.db.close)
    def test_latest_pools_and_filters_do_not_shrink_population(self):
        for pool in ('cached','legacy'):
            with self.fixture.view() as view:
                listing=coverage.scopes(self.fixture.db,view)
                scope=next(item for item in listing['scopes'] if item['mode']=='latest' and item['pool']==pool)
                scope=dict(scope,generation=listing['generation'])
                result=coverage.inspect(self.fixture.capture(pool=pool,first=2,last=2),scope,self.fixture.db,view)
                self.assertEqual(result['population'],4)
                self.assertEqual(result['outputs'][0]['valid']+result['outputs'][0]['unavailable'],4)
                with self.assertRaises(ValueError):coverage.inspect(self.fixture.capture(pool=pool),dict(scope,generation='bad'),self.fixture.db,view)
    def test_empty_and_orphan_scope(self):
        self.fixture.db.execute("DELETE FROM latest_snapshots WHERE pool='cached'")
        with self.fixture.view() as view:
            listing=coverage.scopes(self.fixture.db,view);scope=next(x for x in listing['scopes'] if x['mode']=='latest' and x['pool']=='cached')
            result=coverage.inspect(self.fixture.capture(),dict(scope,generation=listing['generation']),self.fixture.db,view)
            self.assertEqual(result['population'],0);self.assertEqual(result['outputs'][0]['valid'],0)
        self.fixture.db.execute("DELETE FROM companies WHERE symbol='A0000'")
        with self.fixture.view() as view:
            listing=coverage.scopes(self.fixture.db,view);scope=next(x for x in listing['scopes'] if x['mode']=='latest' and x['pool']=='legacy')
            with self.assertRaises(definitions.FormulaError):coverage.inspect(self.fixture.capture(pool='legacy'),dict(scope,generation=listing['generation']),self.fixture.db,view)
    def test_metadata_bound_before_observation(self):
        with self.fixture.view() as view:
            listing=coverage.scopes(self.fixture.db,view);scope=next(x for x in listing['scopes'] if x['mode']=='latest' and x['pool']=='cached')
            bound=scalar_execution._size(view.projection)-1
            with patch.object(scalar_execution,'MAX_METADATA_BYTES',bound),patch.object(coverage.columns.Formulas,'evaluate',side_effect=AssertionError('observed')):
                with self.assertRaises(definitions.FormulaError) as failure:coverage.inspect(self.fixture.capture(),dict(scope,generation=listing['generation']),self.fixture.db,view)
                self.assertEqual(failure.exception.code,'WORK_LIMIT')
    def test_repeated_output_counts_once_per_company(self):
        capture=self.fixture.capture();wire=capture.to_dict();root=wire['variables']['program']['bundle']['roots'][0]
        source=dict(kind='formula',**root)
        intent=requests.intent(source,[requests.condition(source,'1','USD'),requests.condition(source,'2','USD')])
        intent['pool']='cached'
        entries=definitions.authored_bundle(library.VariableCapture(definitions.canonical(wire['variables'])).program)['definitions']
        repeated=strategy_requests.capture_strategy(intent,submitted=entries)
        with self.fixture.view() as view:
            listing=coverage.scopes(self.fixture.db,view);scope=next(x for x in listing['scopes'] if x['mode']=='latest' and x['pool']=='cached')
            result=coverage.inspect(repeated,dict(scope,generation=listing['generation']),self.fixture.db,view)
            self.assertEqual(len(result['outputs']),1)
            self.assertEqual(result['outputs'][0]['valid']+result['outputs'][0]['unavailable'],result['population'])
            with self.assertRaises(definitions.FormulaError):coverage.inspect(repeated,dict(scope,generation=listing['generation'],book=False),self.fixture.db,view)
    def test_recorded_january_and_cancellation(self):
        self.fixture.db.execute('DELETE FROM fact_metadata')
        facts.finish(self.fixture.db, '2015-01-05', inputs='fixture',scopes=prepared_scopes(historical=[('2015-01-02',1)]))
        for pool in ('cached','legacy'):
            with self.fixture.view() as view:
                listing=coverage.scopes(self.fixture.db,view);scope=next(x for x in listing['scopes'] if x['mode']=='historical' and x['pool']==pool)
                result=coverage.inspect(self.fixture.capture(pool=pool),dict(scope,generation=listing['generation']),self.fixture.db,view)
                self.assertEqual(result['population'],4)
                self.assertEqual(result['outputs'][0]['valid']+result['outputs'][0]['unavailable'],4)
                def cancel():raise backtest_control.Cancelled()
                with self.assertRaises(backtest_control.Cancelled):coverage.inspect(self.fixture.capture(pool=pool),dict(scope,generation=listing['generation']),self.fixture.db,view,checkpoint=cancel)
    def test_observation_leaf_reads_are_narrow_and_read_only(self):
        with self.fixture.view() as view:
            listing=coverage.scopes(self.fixture.db,view);scope=next(x for x in listing['scopes'] if x['mode']=='latest' and x['pool']=='cached')
            statements=[];self.fixture.db.set_trace_callback(statements.append)
            try:coverage.inspect(self.fixture.capture(),dict(scope,generation=listing['generation']),self.fixture.db,view)
            finally:self.fixture.db.set_trace_callback(None)
            self.assertFalse(any(s.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','REPLACE','CREATE','DROP')) for s in statements))
            leaves=[s for s in statements if 'FROM annual_facts' in s]
            self.assertTrue(leaves,statements)
            self.assertTrue(all('symbol=' in s.lower() and 'limit ' in s.lower() for s in leaves),leaves)
    def test_distinct_outputs_share_a_dependency(self):
        dependency=language.entry(language.definition(language.constant('2')),'local:dependency')
        first=language.entry(language.definition(language.reference(dependency)),'local:first')
        second=language.entry(language.definition(dict(op='neg',arg=language.reference(dependency))),'local:second')
        source1=requests.formula(first);source2=requests.formula(second)
        intent=requests.intent(source1,[requests.condition(source2,'0','number')]);intent['pool']='cached'
        capture=strategy_requests.capture_strategy(intent,submitted=[dependency,first,second])
        with self.fixture.view() as view:
            listing=coverage.scopes(self.fixture.db,view);scope=next(x for x in listing['scopes'] if x['mode']=='latest' and x['pool']=='cached')
            result=coverage.inspect(capture,dict(scope,generation=listing['generation']),self.fixture.db,view)
            self.assertEqual({item['variable_id'] for item in result['outputs']},{'local:first','local:second'})
            self.assertTrue(all(item['valid']+item['unavailable']==4 for item in result['outputs']))
    def test_prepared_owner_missing_lanes_and_equal_date_derived_policy(self):
        finish=facts.finish
        def adversarial(db,*args,**kwargs):
            # Stored owner lanes: Q0000 keeps its book rows but loses every
            # metric and filter; Q0001 loses only ev_ebitda.
            for table in ('screening_metrics','filter_values'):
                db.execute('DELETE FROM '+table+" WHERE symbol='Q0000'")
            db.execute("DELETE FROM screening_metrics WHERE symbol='Q0001' AND metric='ev_ebitda'")
            return finish(db,*args,**kwargs)
        with patch.object(facts,'finish',side_effect=adversarial):
            with PreparedInputs(configure=history(4,2015,2016)):
                owner=Original()
                listing=owner.coverage()
                for mode in ('historical','latest'):
                    scope=next(x for x in listing['scopes'] if x['mode']==mode and x['pool']=='cached')
                    parameter=dict(op='parameter',id='owner.ev_ebitda')
                    examples=[(parameter,2),(dict(op='at',date=scope['context_date'],arg=parameter),0)]
                    if mode=='latest':examples.append((dict(op='lookback',months=1,arg=parameter),0))
                    for expression,expected in examples:
                        definition=language.definition(expression);definition.update(version=3,parameter_catalog='financial-parameters/3')
                        entry=language.entry(definition,'coverage:owner');intent=requests.intent(requests.formula(entry));intent['pool']='cached'
                        capture=strategy_requests.capture_strategy(intent,submitted=[entry])
                        result=owner.coverage(capture.to_dict(),dict(scope,generation=listing['generation']))
                        self.assertEqual(result['population'],4)
                        self.assertEqual(result['outputs'][0]['unavailable'],expected,(mode,expression,result))
                        if expected:
                            self.assertEqual(result['outputs'][0]['reasons'],{'LEGACY_MEASURE_UNAVAILABLE':2})

if __name__=='__main__':unittest.main()
