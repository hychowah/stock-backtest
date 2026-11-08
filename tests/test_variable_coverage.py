"""Synthetic complete-scope coverage and failure checks."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import unittest
from unittest.mock import patch
from backtest.application import variable_coverage as coverage, scalar_execution
from backtest.variables import definitions
from test_scalar_execution import Fixture
import test_strategy_requests as requests
import test_variable_definitions as language
from backtest.application import strategy_requests
from backtest.variables import library
from backtest.inputs import book_store
from backtest.runtime import backtest_control
from backtest.application.original_calculations import Original
from prepared_inputs_fixture import PreparedInputs, history

def checked(capture):
    """The restored strategy that inspect takes (Original.coverage passes check_options' result)."""
    return strategy_requests.require_strategy(capture)


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.fixture=Fixture(4);self.addCleanup(self.fixture.close)
    def test_latest_pools_and_filters_do_not_shrink_population(self):
        for pool in ('cached','legacy'):
            with self.fixture.view() as view:
                listing=coverage.scopes(self.fixture.db,view)
                scope=next(item for item in listing['scopes'] if item['mode']=='latest' and item['pool']==pool)
                scope=dict(scope,generation=listing['generation'])
                result=coverage.inspect(checked(self.fixture.capture(pool=pool,first=2,last=2)),scope,self.fixture.db,view)
                self.assertEqual(result['population'],4)
                self.assertEqual(result['outputs'][0]['valid']+result['outputs'][0]['unavailable'],4)
                with self.assertRaises(ValueError):coverage.inspect(checked(self.fixture.capture(pool=pool)),dict(scope,generation='bad'),self.fixture.db,view)
    def test_empty_and_orphan_scope(self):
        self.fixture.db.execute("DELETE FROM book_rows WHERE book=2 AND pool='cached'");self.fixture.db.commit()
        with self.fixture.view() as view:
            listing=coverage.scopes(self.fixture.db,view);scope=next(x for x in listing['scopes'] if x['mode']=='latest' and x['pool']=='cached')
            result=coverage.inspect(checked(self.fixture.capture()),dict(scope,generation=listing['generation']),self.fixture.db,view)
            self.assertEqual(result['population'],0);self.assertEqual(result['outputs'][0]['valid'],0)
        self.fixture.db.research.execute("DELETE FROM companies WHERE symbol='A0000'")
        with self.fixture.view() as view:
            listing=coverage.scopes(self.fixture.db,view);scope=next(x for x in listing['scopes'] if x['mode']=='latest' and x['pool']=='legacy')
            with self.assertRaises(definitions.FormulaError):coverage.inspect(checked(self.fixture.capture(pool='legacy')),dict(scope,generation=listing['generation']),self.fixture.db,view)
    def test_discovery_lists_the_stored_open_book_by_its_id(self):
        with self.fixture.view() as view:
            listing=coverage.scopes(self.fixture.db,view)
            self.assertEqual(listing['scopes'],[dict(mode='latest',pool=pool,context_date='2015-01-05',book=self.fixture.latest)
                                                for pool in ('legacy','cached')])
            # A scope that names another stored book is not discovered; nothing is observed.
            with patch.object(coverage.columns.Formulas,'evaluate',side_effect=AssertionError('observed')):
                with self.assertRaises(definitions.FormulaError) as failure:
                    coverage.inspect(checked(self.fixture.capture()),dict(listing['scopes'][1],generation=listing['generation'],
                                                                 book=self.fixture.dated),self.fixture.db,view)
                self.assertEqual(failure.exception.code,'STALE_INPUT_GENERATION')
    def test_repeated_output_counts_once_per_company(self):
        capture=self.fixture.capture();wire=capture.to_dict();root=wire['variables']['program']['bundle']['roots'][0]
        source=dict(kind='formula',**root)
        intent=requests.intent(source,[requests.condition(source,'1','USD'),requests.condition(source,'2','USD')])
        intent['pool']='cached'
        entries=definitions.authored_bundle(library.VariableCapture(definitions.canonical(wire['variables'])).program)['definitions']
        repeated=strategy_requests.capture_strategy(intent,submitted=entries)
        with self.fixture.view() as view:
            listing=coverage.scopes(self.fixture.db,view);scope=next(x for x in listing['scopes'] if x['mode']=='latest' and x['pool']=='cached')
            result=coverage.inspect(checked(repeated),dict(scope,generation=listing['generation']),self.fixture.db,view)
            self.assertEqual(len(result['outputs']),1)
            self.assertEqual(result['outputs'][0]['valid']+result['outputs'][0]['unavailable'],result['population'])
            with self.assertRaises(definitions.FormulaError):coverage.inspect(checked(repeated),dict(scope,generation=listing['generation'],book=False),self.fixture.db,view)
    def test_only_latest_scopes_and_cancellation(self):
        for pool in ('cached','legacy'):
            with self.fixture.view() as view:
                listing=coverage.scopes(self.fixture.db,view)
                self.assertEqual({x['mode'] for x in listing['scopes']},{'latest'})
                scope=dict(next(x for x in listing['scopes'] if x['pool']==pool),generation=listing['generation'])
                with self.assertRaises(definitions.FormulaError):
                    coverage.inspect(checked(self.fixture.capture(pool=pool)),dict(scope,mode='historical',context_date='2015-01-02',book=1),self.fixture.db,view)
                def cancel():raise backtest_control.Cancelled()
                with self.assertRaises(backtest_control.Cancelled):coverage.inspect(checked(self.fixture.capture(pool=pool)),scope,self.fixture.db,view,checkpoint=cancel)
    def test_observation_leaf_reads_are_narrow_and_read_only(self):
        with self.fixture.view() as view:
            listing=coverage.scopes(self.fixture.db,view);scope=next(x for x in listing['scopes'] if x['mode']=='latest' and x['pool']=='cached')
            statements=[]
            self.fixture.db.set_trace_callback(statements.append)
            try:coverage.inspect(checked(self.fixture.capture()),dict(scope,generation=listing['generation']),self.fixture.db,view)
            finally:self.fixture.db.set_trace_callback(None)
            self.assertFalse(any(s.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','REPLACE','CREATE','DROP')) for s in statements))
            leaves=[s for s in statements if 'FROM research.annual_facts' in s]
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
            result=coverage.inspect(checked(capture),dict(scope,generation=listing['generation']),self.fixture.db,view)
            self.assertEqual({item['variable_id'] for item in result['outputs']},{'local:first','local:second'})
            self.assertTrue(all(item['valid']+item['unavailable']==4 for item in result['outputs']))
    def test_prepared_owner_missing_lanes_and_equal_date_derived_policy(self):
        store=book_store.store
        def adversarial(db,book):
            # Stored owner lanes of the latest book: Q0000 keeps its book rows
            # but loses every metric and filter; Q0001 loses only ev_ebitda.
            stored=store(db,book)
            db.execute('UPDATE book_rows SET '+','.join(column+'=NULL' for column in book_store.LANES)+
                       " WHERE book=? AND symbol='Q0000'",(stored,))
            db.execute("UPDATE book_rows SET m_ev_ebitda_multiple=NULL,m_ev_ebitda_yield=NULL "
                       "WHERE book=? AND symbol='Q0001'",(stored,))
            return stored
        with patch.object(book_store,'store',side_effect=adversarial):
            with PreparedInputs(configure=history(4,2015,2016)):
                owner=Original()
                listing=owner.coverage()
                for mode in ('latest',):
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
