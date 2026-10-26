"""Independent sampled rebalances, comparable averages and recoverable batches."""
from datetime import date,timedelta
from pathlib import Path
import io
import json
import sqlite3
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'website')]
import robustness as r
import schedules as s
import serve


class RobustnessTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close);self.db.executescript(s.SCHEMA)
        self.db.execute("INSERT INTO companies VALUES('A','A','NYSE','Energy')")
        self.db.execute("INSERT INTO statements VALUES('A','2014-06-30','2014-09-28',100000000,150000000,30000000,.2)")
        self.db.execute("INSERT INTO statements VALUES('A','2015-06-30','2015-09-28',100000000,150000000,30000000,.2)")
        self.db.execute("INSERT INTO prices VALUES('A','2014-06-30',10,10)")
        day=date(2015,1,1);i=0
        while day<=date(2016,12,30):
            if day.weekday()<5:
                self.db.execute('INSERT INTO sessions VALUES(?,?)',(str(day),100+i*.02))
                self.db.execute("INSERT INTO prices VALUES('A',?,?,?)",(str(day),10+i*.01,10+i*.01));i+=1
            day+=timedelta(days=1)
        self.db.commit()

    def config(self,**options):
        return r.plan(self.db,start='2015-01-01',end='2016-12-30',rank_to=1,**options)

    def test_seed_count_and_independent_draws_in_each_block(self):
        plan=self.config(trials=24,seed=11)
        self.assertEqual(plan,self.config(trials=24,seed=11))
        self.assertNotEqual(plan['samples'],self.config(trials=24,seed=12)['samples'])
        self.assertEqual(len(plan['samples']),24)
        self.assertEqual(len(self.config(trials=3)['samples']),3)
        self.assertEqual(self.config(trials=3,seed=11)['samples'],plan['samples'][:3])
        self.assertTrue(any(row[0][5:]!=row[1][5:] for row in plan['samples']))
        for row in plan['samples']:
            self.assertEqual(row,sorted(set(row)))
            for day,block in zip(row,plan['blocks']):
                self.assertTrue(block['start']<=day<block['end'])
        for options in ({'trials':0},{'trials':101},{'trials':2.5},{'seed':-1}):
            with self.assertRaises(ValueError):self.config(**options)

    def test_fresh_dates_by_default_with_replay_key(self):
        with patch.object(r.random,'SystemRandom') as generator:
            generator.return_value.getrandbits.side_effect=[12345,98765]
            first=self.config(trials=3);second=self.config(trials=3)
        self.assertEqual(first['seed'],12345);self.assertEqual(second['seed'],98765)
        self.assertNotEqual(first['samples'],second['samples'])
        self.assertEqual(first['samples'],self.config(trials=3,seed=first['seed'])['samples'])

    def test_two_year_interval_and_common_cash_window(self):
        config=self.config(months=24,trials=3)
        self.assertTrue(all(len(row)==1 for row in config['samples']))
        result=r.run(self.db,config)
        self.assertEqual(result['valid'],3)
        duration=(date(2016,12,30)-date(2015,1,1)).days/365.25
        for row in result['trials']:
            self.assertEqual(row['start'],'2015-01-01')
            self.assertEqual(row['end'],'2016-12-30')
            self.assertGreaterEqual(row['cash_days'],0)
            self.assertAlmostEqual(row['cagr'],row['growth']**(1/duration)-1)
            self.assertAlmostEqual(row['spy_cagr'],row['spy_growth']**(1/duration)-1)

    def test_distribution_and_complete_batch_matches_individual_runs(self):
        config=self.config(trials=4,seed=9)
        events=[];result=r.run(self.db,config,events.append)
        expected=[]
        for dates in config['samples']:
            one=s.backtest_dates(self.db,dates=dates,start=config['start'],end=config['end'],months=12,rank_to=1)
            expected.append(one['cagr'])
        self.assertAlmostEqual(result['distributions']['cagr']['mean'],sum(expected)/4)
        self.assertEqual(result['distributions']['cagr']['min'],min(expected))
        self.assertEqual(result['distributions']['cagr']['max'],max(expected))
        self.assertEqual([e['completed'] for e in events if e['type']=='progress'],[0,1,1,2,2,3,3,4])
        self.assertEqual(r.distribution([0,10])['median'],5)
        self.assertEqual(r.distribution([0,10])['p10'],1)
        self.assertEqual(r.distribution([0,10])['stddev'],5)
        # New filters over the same sampled books never re-read raw/daily prices.
        with patch.object(s,'price',side_effect=AssertionError('Cached books must be reused')):
            repeat=r.run(self.db,config)
        self.assertEqual([t['cagr'] for t in repeat['trials']],expected)

    def test_incomplete_trials_are_visible_and_not_counted_as_zero(self):
        result=r.run(self.db,self.config(trials=3,sector='No matches'))
        self.assertEqual(result['valid'],0);self.assertEqual(result['incomplete'],3)
        self.assertEqual(len(result['trials']),3)
        self.assertIsNone(result['distributions']['cagr']['mean'])
        self.assertEqual(result['distributions']['spy_cagr']['n'],0)
        self.assertTrue(all(row['empty_periods']>0 for row in result['trials']))

    def test_interrupted_batch_keeps_completed_trial_books_for_retry(self):
        config=self.config(trials=3)
        def interrupt(event):
            if event['completed']==1:raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):r.run(self.db,config,interrupt)
        retained=self.db.execute('SELECT COUNT(*) FROM periods').fetchone()[0]
        self.assertGreater(retained,0)
        result=r.run(self.db,config)
        self.assertEqual(result['completed'],3)
        self.assertGreaterEqual(self.db.execute('SELECT COUNT(*) FROM periods').fetchone()[0],retained)

    def test_pool_switch_commits_each_trial_and_preserves_original_pool(self):
        original=self.config(trials=3,seed=11,pool='legacy')
        first=r.run(self.db,original)
        periods=self.db.execute('SELECT COUNT(*) FROM periods').fetchone()[0]
        legacy=[tuple(row) for row in self.db.execute("SELECT * FROM snapshots WHERE pool='legacy' ORDER BY year,symbol")]
        wider=self.config(trials=3,seed=11,pool='cached')
        def interrupt(event):
            if event['completed']==1:raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):r.run(self.db,wider,interrupt)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM period_pools WHERE pool='cached'").fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM periods').fetchone()[0],periods)
        self.assertEqual([tuple(row) for row in self.db.execute("SELECT * FROM snapshots WHERE pool='legacy' ORDER BY year,symbol")],legacy)
        with patch.object(s,'price',side_effect=AssertionError('Original pool remains complete')),patch.object(s,'histories',side_effect=AssertionError('Original pool remains complete')):
            replay=r.run(self.db,original)
        self.assertEqual([row['cagr'] for row in replay['trials']],[row['cagr'] for row in first['trials']])
        retry=r.run(self.db,wider)
        self.assertEqual([row['cagr'] for row in retry['trials']],[row['cagr'] for row in first['trials']])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM period_pools').fetchone()[0],2*periods)

    def test_ndjson_handler_contract(self):
        handler=object.__new__(serve.Handler);handler.wfile=io.BytesIO()
        statuses=[];handler.send_response=statuses.append
        handler.send_header=lambda *args:None;handler.end_headers=lambda:None
        configuration=self.config(trials=2)
        handler.stream_batch(self.db,configuration)
        events=[json.loads(line) for line in handler.wfile.getvalue().splitlines()]
        self.assertEqual(statuses,[200]);self.assertEqual(events[0]['type'],'configuration')
        self.assertEqual(events[0]['configuration'],configuration)
        self.assertEqual(events[-1]['type'],'complete')
        self.assertEqual(events[-1]['result']['completed'],2)

    def test_interrupted_stream_publishes_replay_identity_before_work(self):
        handler=object.__new__(serve.Handler);handler.wfile=io.BytesIO()
        handler.send_response=lambda *args:None
        handler.send_header=lambda *args:None;handler.end_headers=lambda:None
        configuration=self.config(trials=2)
        with patch.object(serve.robustness,'run',side_effect=ValueError('interrupted')):
            handler.stream_batch(self.db,configuration)
        events=[json.loads(line) for line in handler.wfile.getvalue().splitlines()]
        self.assertEqual(events[0],dict(type='configuration',configuration=configuration))
        self.assertEqual(events[1]['type'],'error')
        replay=r.plan(self.db,start=configuration['start'],end=configuration['end'],months=configuration['months'],trials=configuration['requested'],seed=configuration['seed'],**configuration['options'])
        self.assertEqual(replay['samples'],configuration['samples'])

    def test_http_route_streams_and_inspects_exact_dates(self):
        def connection():
            db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
            self.db.backup(db);return db
        def handler(path,payload):
            obj=object.__new__(serve.Handler);body=json.dumps(payload).encode()
            obj.server=SimpleNamespace(lifecycle=None)
            obj.disconnect_check=lambda:lambda:False
            obj.path=path;obj.rfile=io.BytesIO(body);obj.wfile=io.BytesIO()
            obj.headers={'Content-Length':str(len(body)),'Host':'127.0.0.1:8765'}
            obj.statuses=[];obj.send_response=obj.statuses.append
            obj.send_header=lambda *args:None;obj.end_headers=lambda:None
            obj.replies=[];obj.reply=lambda status,value:obj.replies.append((status,value))
            return obj
        batch=handler('/api/robustness',dict(start='2015-01-01',end='2016-12-30',months=24,trials=2,seed=42,rank_to=1))
        with patch.object(serve.schedules,'connect',side_effect=connection):batch.do_POST()
        self.assertEqual(batch.statuses,[200])
        result=json.loads(batch.wfile.getvalue().splitlines()[-1])['result']
        inspect=handler('/api/schedule',dict(start='2015-01-01',end='2016-12-30',months=24,dates=result['trials'][0]['dates'],rank_to=1))
        with patch.object(serve.schedules,'connect',side_effect=connection):inspect.do_POST()
        self.assertEqual(inspect.replies[0][0],200)
        self.assertAlmostEqual(inspect.replies[0][1]['cagr'],result['trials'][0]['cagr'])


if __name__=='__main__':unittest.main()
