"""Complete synthetic scopes, bounded reference chunks and one global selection."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from contextlib import closing
from datetime import date
import json
import sqlite3
import unittest
from unittest.mock import patch

from backtest.inputs import daily, observation_inputs, sqlite_observations
from backtest.application import scalar_execution as x, strategy_requests as s
from backtest.variables import definitions as d, library, reference
from backtest import observations
import test_variable_definitions as language
import test_strategy_requests as requests
import test_observations as provider


class Fixture:
    def __init__(self, count=300):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.executescript(daily.SCHEMA)
        for i in range(count):
            symbol=f'A{i:04d}'
            self.db.execute('INSERT INTO companies VALUES(?,?,?,?)',(symbol,symbol,'NYSE','Technology'))
            self.db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',(symbol,'2014-06-30','2014-09-28',150e6,180e6,54e6,.3))
            self.db.executemany('INSERT INTO prices VALUES(?,?,?,?)',[(symbol,day,10.,10.) for day in ['2014-06-30','2015-01-02','2015-01-05']])
            for pool in ('legacy','cached'):
                self.db.execute('INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(pool,1,symbol,i+1,'2014-06-30','2015-01-02','2015-01-05',150e6,180e6,54e6,.3,3.,.28,i/1000,'Scheduled exit'))
                self.db.execute('INSERT INTO latest_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(pool,symbol,i+1,'2014-06-30','2014-09-28','2015-01-05',10.,150e6,180e6,.3,3.,.28))
                self.db.execute('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',('historical',pool,1,symbol,'ev_ebitda',3.,.3))
                self.db.execute('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',('latest',pool,0,symbol,'ev_ebitda',3.,.3))
                self.db.execute('INSERT INTO filter_values VALUES(?,?,?,?,?,?)',('historical',pool,1,symbol,'profit_margin',i-150.))
            annual=provider.annual(float(i+1),float(i+1)/10)
            self.db.execute('INSERT INTO observation_annual VALUES(?,?,?,?)',(symbol,'income-statement','2014-06-30',observation_inputs.encoded(annual)))
            state=dict(root_date='2015-01-05',admitted=True,reason=None,candidate_rank=i+1,
                statement=observation_inputs.ReadView._statement(provider.statement('2014-06-30')),
                valuation=dict(market_cap=150e6,enterprise_value=180e6,ebitda=54e6),
                adjusted_price=['2015-01-05',10.],fiscal_price=['2014-06-30',10.],valuation_price=['2015-01-05',10.])
            for pool in ('legacy','cached'):observation_inputs.store_latest(self.db,symbol,pool,state)
        self.db.executemany('INSERT INTO sessions VALUES(?,?)',[('2015-01-02',100.),('2015-01-05',110.)])
        self.db.execute('INSERT INTO periods VALUES(?,?,?,?,?,?,?)',(1,'2015-01-02','2015-01-05',.1,.02,250,count))
        self.db.execute('INSERT INTO period_pools VALUES(?,?)',(1,'legacy'))
        self.db.execute('INSERT INTO period_pools VALUES(?,?)',(1,'cached'))
        self.db.execute('INSERT INTO metadata VALUES(?,?)',('daily_inputs',json.dumps(dict(inputs=dict(historical_through='2015-01-05')))))
        observation_inputs.finish(self.db, '2015-01-05', inputs='fixture');self.db.commit()
    def view(self):return sqlite_observations.prepared_view(self.db,lambda:None)
    def capture(self, expression=None, *, pool='cached', direction='highest', order='filter_first', conditions=None, first=1,last=5):
        authored=language.entry(language.definition(expression or dict(op='parameter',id='annual.revenue'),'USD' if expression is None else 'scalar','usd' if expression is None else 'number'),'draft:ranking')
        intent=requests.intent(requests.formula(authored),conditions,rank_from=first,rank_to=last,selection_order=order)
        intent['selection']['ranking']['direction']=direction;intent['pool']=pool
        return s.capture_strategy(intent,submitted=[authored])
    def select(self,capture, *, latest=False, record_bytes=8*1024**2):
        records=[]
        with self.view() as view:
            result=x.Executor(capture,view,records.append,record_bytes=record_bytes).select(self.db,None if latest else 1,date(2015,1,5) if latest else date(2015,1,2),None if latest else date(2015,1,5),latest=latest)
        return result,records


class ScalarTests(unittest.TestCase):
    def setUp(self):
        self.fixture=Fixture();self.addCleanup(self.fixture.db.close)
    def test_orphan_snapshot_rejects_complete_scope(self):
        self.fixture.db.execute("DELETE FROM companies WHERE symbol='A0000'")
        with self.assertRaises(d.FormulaError) as failure:self.fixture.select(self.fixture.capture())
        self.assertEqual(failure.exception.path,'/population')
    def test_more_than_256_candidates_rank_globally_with_complete_chunks(self):
        stocks,records=self.fixture.select(self.fixture.capture())
        self.assertEqual([h['symbol'] for h in stocks],[f'A{i:04d}' for i in range(299,294,-1)])
        blocks=[r['value'] for r in records if r['type']=='evaluation']
        self.assertGreater(len(blocks),1)
        self.assertEqual(sum(len(b['block']['requests']) for b in blocks),300)
        self.assertEqual([r['value']['rows'] for r in records if r['type']=='scope'],[300])
        self.assertTrue(all(h['ranking_unit']=='USD' for h in stocks))
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
    def test_legacy_buffer_denies_prepared_rows_outside_250(self):
        stocks,_=self.fixture.select(self.fixture.capture(pool='legacy'))
        self.assertEqual(stocks[0]['symbol'],'A0249')
        builtin=requests.intent();builtin['pool']='legacy'
        stocks,records=self.fixture.select(s.capture_strategy(builtin))
        self.assertEqual(len(stocks),50)
        receipt=next(r['value'] for r in records if r['type']=='scope')
        self.assertEqual(receipt['provider_admitted_in_prepared_scope'],250)
        self.assertTrue(any(r['type']=='admission' for r in records))
    def test_missing_only_active_source_excludes(self):
        self.fixture.db.execute("DELETE FROM observation_annual WHERE symbol='A0299'")
        self.fixture.db.execute('DELETE FROM observation_metadata');observation_inputs.finish(self.fixture.db, '2015-01-05', inputs='fixture')
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
            result=x.preview(capture,[dict(symbol='A0001',pool='cached',mode='historical',date='2015-01-02')],view)
        self.assertEqual(result['population'],'explicit-request-scopes')
        self.assertEqual(result['evaluations'][0]['results'][0]['value'],2.)
        with self.fixture.view() as view:
            with self.assertRaises(d.FormulaError):x.preview(capture,[],view)
    def test_latest_has_no_future_fields(self):
        stocks,_=self.fixture.select(self.fixture.capture(),latest=True)
        self.assertEqual(stocks[0]['symbol'],'A0299')
        self.assertFalse(any(key in stocks[0] for key in ('return_value','exit','weight','contribution_pp')))
    def test_view_closure_does_not_close_borrowed_connection(self):
        view=self.fixture.view();view.close()
        with self.assertRaises(ValueError):view.validate()
        self.assertEqual(self.fixture.db.execute('SELECT count(*) FROM companies').fetchone()[0],300)
    def test_stale_binding_rejected_and_no_connections_owned(self):
        view=self.fixture.view()
        self.fixture.db.execute("UPDATE metadata SET value='{}' WHERE key='daily_inputs'")
        with self.assertRaises(ValueError):view.validate()
        view.close()
    def test_small_record_limit_fails_explicitly(self):
        with self.assertRaises(d.FormulaError):self.fixture.select(self.fixture.capture(),record_bytes=100)
    def test_temporal_contexts_shrink_chunks_below_256_companies(self):
        expression=dict(op='lookback',months=1,arg=dict(op='parameter',id='annual.operating_margin'))
        stocks,records=self.fixture.select(self.fixture.capture(expression))
        blocks=[record['value']['block'] for record in records if record['type']=='evaluation']
        self.assertGreaterEqual(len(blocks),3)
        self.assertTrue(all(len(block['requests'])<=128 for block in blocks))
        self.assertEqual(len(stocks),5)
    def test_entry_admission_and_missing_return_rows_have_distinct_scope_counts(self):
        self.fixture.db.execute("DELETE FROM snapshots WHERE symbol='A0299'")
        stocks,records=self.fixture.select(self.fixture.capture())
        receipt=next(record['value'] for record in records if record['type']=='scope')
        self.assertEqual(receipt['source_population'],300)
        self.assertEqual(receipt['rows'],299)
        self.assertEqual(receipt['provider_admitted_in_prepared_scope'],299)
        with self.fixture.view() as view:
            value=x.preview(self.fixture.capture(),[dict(symbol='A0299',pool='cached',mode='historical',date='2015-01-02')],view)
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
