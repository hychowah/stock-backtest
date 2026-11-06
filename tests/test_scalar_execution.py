"""Complete synthetic scopes, bounded reference chunks and one global selection."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from contextlib import closing
from datetime import date
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backtest.inputs import fact_view, facts
from backtest.application import scalar_execution as x, strategy_requests as s
from backtest.variables import definitions as d, library
import test_variable_definitions as language
import test_strategy_requests as requests
import book_store_fixture as store


def preview(capture, roots, view):
    """Restore, check, then explain explicit roots, as Original.preview does under cache ownership."""
    return x.evaluate_preview(x.check_preview(s.require_strategy(capture), roots), roots, view)


def state(value, reason=None):
    return dict(value=value, valid=reason is None, reason=reason)


class Fixture:
    """A dated book (id 1, 2015-01-02 to 2015-01-05) and the latest book (id 2, 2015-01-05) of count companies.

    db is the daily connection with the research file attached (book_store_fixture);
    db.research writes the research rows.
    """
    def __init__(self, count=300):
        self.folder=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db=store.connection(Path(self.folder.name)/'research.sqlite')
        research=self.db.research
        for day,spy in [('2015-01-02',100.),('2015-01-05',110.)]:
            store.session(self.db,day,spy,2.)
        rows={'dated':{},'latest':{}};pairs={'dated':{},'latest':{}};values={'dated':{}}
        for i in range(count):
            symbol=f'A{i:04d}'
            store.company(self.db,symbol,sector='Technology')
            research.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',(symbol,'2014-06-30','2014-09-28',150e6,180e6,54e6,.3))
            for day in ['2014-06-30','2015-01-02','2015-01-05']:
                store.price(self.db,symbol,day,10.)
            for pool in ('legacy','cached'):
                columns=dict(candidate_rank=i+1,fiscal='2014-06-30',known='2014-09-28',price=10.,market_cap=150e6,
                             enterprise_value=180e6,ebitda=54e6,ebitda_yield=.3,ev_ebitda=3.,spread=.28)
                rows['dated'].setdefault(pool,{})[symbol]=dict(columns,entry='2015-01-02',exit='2015-01-05',
                                                               return_value=i/1000,status='Scheduled exit')
                rows['latest'].setdefault(pool,{})[symbol]=dict(columns,entry='2015-01-05')
                for kind in ('dated','latest'):
                    pairs[kind].setdefault(pool,{})[symbol]={'ev_ebitda':(3.,.3)}
                values['dated'].setdefault(pool,{})[symbol]={'profit_margin':i-150.}
            annual=dict(revenue=state(float(i+1)),operatingIncome=state(float(i+1)/10))
            facts.store_annual(research,symbol,dict(sources={},annual={'income-statement':{'2014-06-30':annual}}))
        self.dated=store.book(self.db,'2015-01-02','2015-01-05',spy=.1,candidates=count,rows=rows['dated'],
                              metrics=pairs['dated'],values=values['dated'])
        self.latest=store.book(self.db,'2015-01-05',None,candidates=count,rows=rows['latest'],metrics=pairs['latest'])
        store.record(research,self.db,'2015-01-05');self.db.commit()
    def close(self):
        self.db.close();self.folder.cleanup()
    def view(self):return fact_view.View(self.db,lambda:None,lambda:None)
    def capture(self, expression=None, *, pool='cached', direction='highest', order='filter_first', conditions=None, first=1,last=5):
        authored=language.entry(language.definition(expression or dict(op='parameter',id='annual.revenue'),'USD' if expression is None else 'scalar','usd' if expression is None else 'number'),'draft:ranking')
        intent=requests.intent(requests.formula(authored),conditions,rank_from=first,rank_to=last,selection_order=order)
        intent['selection']['ranking']['direction']=direction;intent['pool']=pool
        return s.capture_strategy(intent,submitted=[authored])
    def select(self,capture, *, latest=False, record_bytes=8*1024**2):
        records=[]
        with self.view() as view:
            result=x.Executor(capture,view,records.append,record_bytes=record_bytes).select(self.db,self.latest if latest else self.dated,date(2015,1,5) if latest else date(2015,1,2),None if latest else date(2015,1,5),latest=latest)
        return result,records


class ScalarTests(unittest.TestCase):
    def setUp(self):
        self.fixture=Fixture();self.addCleanup(self.fixture.close)
    def test_orphan_snapshot_rejects_complete_scope(self):
        self.fixture.db.research.execute("DELETE FROM companies WHERE symbol='A0000'")
        with self.assertRaises(d.FormulaError) as failure:self.fixture.select(self.fixture.capture())
        self.assertEqual(failure.exception.path,'/population')
    def test_more_than_256_candidates_rank_globally_and_explain_only_selected_rows(self):
        stocks,records=self.fixture.select(self.fixture.capture())
        self.assertEqual([h['symbol'] for h in stocks],[f'A{i:04d}' for i in range(299,294,-1)])
        # Formulas run for all 300 candidates; explanations cover the 5 selected rows.
        blocks=[r['value'] for r in records if r['type']=='evaluation']
        self.assertEqual(sum(len(b['block']['requests']) for b in blocks),5)
        self.assertEqual([r['value']['rows'] for r in records if r['type']=='scope'],[300])
        self.assertTrue(all(h['ranking_unit']=='USD' for h in stocks))
    def test_explanation_larger_than_one_record_is_split(self):
        expected,records=self.fixture.select(self.fixture.capture())
        whole=[r['value']['block'] for r in records if r['type']=='evaluation']
        self.assertEqual([len(b['requests']) for b in whole],[5])
        limit=len(d.canonical(whole[0]))+4096-1
        stocks,records=self.fixture.select(self.fixture.capture(),record_bytes=limit)
        self.assertEqual([h['symbol'] for h in stocks],[h['symbol'] for h in expected])
        blocks=[r['value'] for r in records if r['type']=='evaluation']
        self.assertEqual(([b['chunk'] for b in blocks],[len(b['block']['requests']) for b in blocks]),([0,1],[2,3]))
        self.assertTrue(all(len(d.canonical(b['block']))<=limit-4096 for b in blocks))
        lanes=[h['scalar_evidence']['lanes']['ranking'] for h in stocks]
        self.assertEqual([(lane['chunk'],lane['request']) for lane in lanes],[(0,0),(0,1),(1,0),(1,1),(1,2)])
        with self.assertRaises(d.FormulaError) as failure:self.fixture.select(self.fixture.capture(),record_bytes=4096+64)
        self.assertEqual(failure.exception.code,'WORK_LIMIT')
    def test_result_size_is_checked_before_work(self):
        from backtest.application import scalar_runs
        class Writer:max_bytes=4*1024**2
        with self.fixture.view() as view:
            executor=x.Executor(self.fixture.capture(),view,lambda record:None)
            scalar_runs.check_size(Writer(),executor,100)
            with self.assertRaisesRegex(d.FormulaError,'about [0-9]+ MB of results'):
                scalar_runs.check_size(Writer(),executor,10000)
    def test_random_runs_keep_formula_values_without_traces(self):
        expected,_=self.fixture.select(self.fixture.capture())
        records=[]
        with self.fixture.view() as view:
            stocks=x.Executor(self.fixture.capture(),view,records.append,explain=False).select(self.fixture.db,1,date(2015,1,2),date(2015,1,5))
        self.assertEqual([h['symbol'] for h in stocks],[h['symbol'] for h in expected])
        self.assertFalse(any(r['type']=='evaluation' for r in records))
        lanes=[h['scalar_evidence']['lanes']['ranking'] for h in stocks]
        self.assertEqual([lane['value'] for lane in lanes],[h['ranking_value'] for h in expected])
        self.assertTrue(all('chunk' not in lane and lane['unit']=='USD' for lane in lanes))
    def test_ties_across_chunks_use_candidate_rank_then_symbol(self):
        stocks,records=self.fixture.select(self.fixture.capture(language.constant('-1'),first=253,last=258))
        self.assertEqual([h['symbol'] for h in stocks],[f'A{i:04d}' for i in range(252,258)])
        self.assertTrue(all(h['ranking_value']==-1 for h in stocks))
    def test_lowest_and_signed_zero_keep_original_ties(self):
        stocks,_=self.fixture.select(self.fixture.capture(direction='lowest'))
        self.assertEqual(stocks[0]['symbol'],'A0000')
        stocks,_=self.fixture.select(self.fixture.capture(language.constant('-0'),direction='lowest'))
        self.assertEqual(stocks[0]['symbol'],'A0000')
    def test_both_selection_orders_keep_survivor_ranks_and_no_replacements(self):
        c=requests.condition(requests.builtin('filter:profit_margin'),'147','percent')
        for order,expected in [('filter_first',2),('rank_first',2)]:
            capture=self.fixture.capture(conditions=[c],order=order)
            stocks,_=self.fixture.select(capture)
            self.assertEqual(len(stocks),expected)
            self.assertEqual(stocks[0]['rank'],1)
        c=requests.condition(requests.builtin('filter:profit_margin'),'0','percent',op='lt')
        stocks,_=self.fixture.select(self.fixture.capture(conditions=[c],order='rank_first'))
        self.assertEqual(stocks,[])
        stocks,_=self.fixture.select(self.fixture.capture(conditions=[c],order='filter_first'))
        self.assertEqual(len(stocks),5)
    def test_a_stored_row_is_its_roots_admission(self):
        # books.book stored only admitted rows; no scope re-screens them, even
        # the fixture's legacy rows outside the 250-report buffer.
        from backtest.financial import books
        with patch.object(books,'Screen',side_effect=AssertionError('re-admitted')), \
                patch.object(fact_view.View,'admit',side_effect=AssertionError('re-admitted')):
            for latest in (False,True):
                stocks,records=self.fixture.select(self.fixture.capture(pool='legacy'),latest=latest)
                self.assertEqual(stocks[0]['symbol'],'A0299')
                receipt=next(r['value'] for r in records if r['type']=='scope')
                self.assertEqual(receipt['provider_admitted_in_prepared_scope'],300)
                block=next(r['value']['block'] for r in records if r['type']=='evaluation')
                admission=block['observations']['roots'][0]
                self.assertEqual((admission['admitted'],admission['candidate_rank']),(True,300))
                self.assertEqual(admission['valuation'],dict(market_cap=150e6,enterprise_value=180e6,ebitda=54e6))
    def test_owner_lanes_of_every_scope_read_its_stored_book(self):
        from backtest import measure_observations
        from backtest.variables import parameters
        definition=language.definition(dict(op='parameter',id='owner.profit_margin'),'scalar','number')
        definition.update(version=3,parameter_catalog=parameters.V3)
        authored=language.entry(definition,'draft:margin')
        intent=requests.intent(requests.formula(authored),None,rank_from=1,rank_to=5);intent['pool']='cached'
        capture=s.capture_strategy(intent,submitted=[authored])
        for latest,book,margin in ((False,self.fixture.dated,1.49),(True,self.fixture.latest,None)):
            with patch.object(measure_observations,'dated',side_effect=AssertionError('recalculated')):
                stocks,records=self.fixture.select(capture,latest=latest)
            if margin is None:
                # The latest book stores no profit margin: unavailable, never recalculated.
                self.assertEqual(stocks,[])
                continue
            block=next(r['value']['block'] for r in records if r['type']=='evaluation')
            self.assertTrue(all(item['owner_scope']==dict(kind='prepared',book=book) for item in block['requests']))
            self.assertEqual((stocks[0]['symbol'],stocks[0]['ranking_value']),('A0299',margin))
            [observation]=[item for item in block['observations']['results'] if item['root']==block['results'][0]['root']]
            self.assertEqual((observation['anchor'],observation['members'][0]['fiscal_date']),('2014-06-30','2014-06-30'))
            self.assertEqual(observation['members'][0]['evidence'],dict(source='filters',key='profit_margin',stored=149.,
                                                                        conversion='percent-divided-by-100'))
    def test_missing_only_active_source_excludes(self):
        self.fixture.db.research.execute("DELETE FROM annual_facts WHERE symbol='A0299'")
        stocks,_=self.fixture.select(self.fixture.capture())
        self.assertEqual(stocks[0]['symbol'],'A0298')
        stocks,_=self.fixture.select(self.fixture.capture(language.constant('1')))
        self.assertEqual(len(stocks),5)
    def test_builtin_storage_scale_and_complete_canonical_evidence(self):
        intent=requests.intent(requests.builtin('filter:profit_margin'));intent['pool']='cached'
        stocks,records=self.fixture.select(s.capture_strategy(intent))
        self.assertEqual(stocks[0]['ranking_value'],1.49)
        lane=stocks[0]['scalar_evidence']['lanes']['ranking']
        self.assertEqual((lane['stored'],lane['canonical']),(149.,1.49))
        self.assertFalse(any(r['type']=='evaluation' for r in records))
    def test_explicit_preview_never_claims_pool_coverage(self):
        capture=self.fixture.capture()
        with self.fixture.view() as view:
            result=preview(capture,[dict(symbol='A0001',pool='cached',mode='historical',date='2015-01-02')],view)
        self.assertEqual(result['population'],'explicit-request-scopes')
        self.assertEqual(result['evaluations'][0]['results'][0]['value'],2.)
        with self.fixture.view() as view:
            with self.assertRaises(d.FormulaError):preview(capture,[],view)
    def test_a_prepared_scope_is_a_stored_book_named_by_its_id(self):
        capture=self.fixture.capture()
        latest=dict(symbol='A0001',pool='cached',mode='latest',date='2015-01-05')
        with self.fixture.view() as view:
            result=preview(capture,[latest],view)
            self.assertTrue(result['evaluations'][0]['results'][0]['valid'])
            # A request names no book: a preview root with an owner scope is refused before any input is read.
            for scope in (dict(kind='prepared',book=self.fixture.latest),dict(kind='dated')):
                with self.assertRaises(d.FormulaError) as failure:
                    preview(capture,[dict(latest,owner_scope=scope)],view)
                self.assertEqual((failure.exception.code,failure.exception.path),('INVALID_SHAPE','/requests/0'))
            # The one check (book_store.require_scope): only the open book of that day and pool.
            executor=x.Executor(capture,view,lambda record:None)
            for book,day,latest_scope in ((self.fixture.dated,date(2015,1,5),True),(99,date(2015,1,5),True),
                                          (self.fixture.latest,date(2015,1,5),False),(self.fixture.dated,date(2015,1,5),False)):
                with self.assertRaises(d.FormulaError) as failure:
                    executor.select(self.fixture.db,book,day,latest=latest_scope)
                self.assertEqual(failure.exception.path,'/owner_scope')
        # A latest scope records its real book id in every root's owner scope.
        _,records=self.fixture.select(capture,latest=True)
        requests=[item for r in records if r['type']=='evaluation' for item in r['value']['block']['requests']]
        self.assertTrue(requests)
        self.assertTrue(all(item['owner_scope']==dict(kind='prepared',book=self.fixture.latest) for item in requests))
    def test_latest_has_no_future_fields(self):
        stocks,_=self.fixture.select(self.fixture.capture(),latest=True)
        self.assertEqual(stocks[0]['symbol'],'A0299')
        self.assertFalse(any(key in stocks[0] for key in ('return_value','exit','weight','contribution_pp')))
    def test_view_closure_does_not_close_borrowed_connection(self):
        view=self.fixture.view();view.close()
        with self.assertRaises(ValueError):view.validate()
        self.assertEqual(self.fixture.db.execute('SELECT count(*) FROM research.companies').fetchone()[0],300)
    def test_stale_binding_rejected_and_no_connections_owned(self):
        view=self.fixture.view()
        self.fixture.db.execute("UPDATE metadata SET value='{}' WHERE key='daily_inputs'")
        with self.assertRaises(ValueError):view.validate()
        view.close()
    def test_small_record_limit_fails_explicitly(self):
        with self.assertRaises(d.FormulaError):self.fixture.select(self.fixture.capture(),record_bytes=100)
    def test_entry_admission_and_missing_return_rows_have_distinct_scope_counts(self):
        self.fixture.db.execute("DELETE FROM book_rows WHERE book=1 AND symbol='A0299'")
        stocks,records=self.fixture.select(self.fixture.capture())
        receipt=next(record['value'] for record in records if record['type']=='scope')
        self.assertEqual(receipt['source_population'],300)
        self.assertEqual(receipt['rows'],299)
        self.assertEqual(receipt['provider_admitted_in_prepared_scope'],299)
        with self.fixture.view() as view:
            value=preview(self.fixture.capture(),[dict(symbol='A0299',pool='cached',mode='historical',date='2015-01-02')],view)
        self.assertTrue(value['evaluations'][0]['results'][0]['valid'])
        self.assertEqual(stocks[0]['symbol'],'A0298')
    def test_cancellation_after_first_chunk_never_returns_partial_selection(self):
        from backtest.runtime import backtest_control
        emitted=[];stopped=False
        def emit(row):
            nonlocal stopped
            emitted.append(row)
            if row['type']=='evaluation':stopped=True
        def check():
            if stopped:raise backtest_control.Cancelled()
        with self.fixture.view() as view:
            with self.assertRaises(backtest_control.Cancelled):
                x.Executor(self.fixture.capture(),view,emit,checkpoint=check).select(self.fixture.db,1,date(2015,1,2),date(2015,1,5))
        self.assertEqual(len(emitted),1)
        self.assertEqual(emitted[0]['type'],'evaluation')

    def test_cancellation_reaches_chunk_evaluation(self):
        def stop():raise RuntimeError('cancelled')
        with self.fixture.view() as view:
            with self.assertRaisesRegex(RuntimeError,'cancelled'):
                x.Executor(self.fixture.capture(),view,lambda row:None,checkpoint=stop).select(self.fixture.db,1,date(2015,1,2),date(2015,1,5))


if __name__=='__main__':unittest.main()
