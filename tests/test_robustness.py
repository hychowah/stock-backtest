"""Independent sampled rebalances, comparable averages and recoverable batches."""
import sys as _owner_sys
from pathlib import Path as _OwnerPath
_owner_sys.path.insert(0,str(_OwnerPath(__file__).resolve().parents[1]))
from backtest.application.original_calculations import Original
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.inputs import daily, facts
from backtest.financial import books as financial_books
from backtest.runtime import cache_access
from datetime import date,timedelta
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
from backtest.engines.original import robustness as r
from backtest.engines.original import schedules as s
from backtest.application import jobs as backtest_jobs
sys.path.insert(0,str(ROOT/'tests'))
import book_store_fixture as store
class RobustnessTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        coordinator=patch.object(cache_access,'workspace',cache_access.WorkspaceAccess(Path(folder.name)/'cache.lock'))
        coordinator.start();self.addCleanup(coordinator.stop)
        # The daily cache in memory; its research facts in a private file.
        self.research=Path(folder.name)/'research.sqlite'
        self.db=store.connection(self.research)
        self.addCleanup(self.db.close)
        store.company(self.db,'A')
        self.db.research.execute("INSERT INTO statements VALUES('A','2014-06-30','2014-09-28',100000000,150000000,30000000,.2)")
        self.db.research.execute("INSERT INTO statements VALUES('A','2015-06-30','2015-09-28',100000000,150000000,30000000,.2)")
        store.price(self.db,'A','2014-06-30',10)
        day=date(2015,1,1);i=0
        while day<=date(2016,12,30):
            if day.weekday()<5:
                store.session(self.db,str(day),100+i*.02)
                store.price(self.db,'A',str(day),10+i*.01);i+=1
            day+=timedelta(days=1)
        self.db.commit()

    def config(self,**options):
        return r.plan(self.db,start='2015-01-01',end='2016-12-30',rank_to=1,**options)

    def calculate(self,mode,options,configuration=None,**kwargs):
        def connection():
            db=sqlite3.connect(':memory:',uri=True);db.row_factory=sqlite3.Row
            self.db.backup(db);daily.attach(db,self.research);return db
        with patch.object(daily,'connect',side_effect=connection):
            return Original().calculate(mode,options,None,configuration,**kwargs)

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
        with patch.object(financial_books,'book',side_effect=AssertionError('Cached entries must be reused')):
            repeat=r.run(self.db,config)
        self.assertEqual([t['cagr'] for t in repeat['trials']],expected)

    def test_all_cash_trials_keep_full_window_and_paired_spy(self):
        result=r.run(self.db,self.config(trials=3,sector='No matches'))
        self.assertEqual(result['valid'],3);self.assertEqual(result['incomplete'],0)
        self.assertEqual(len(result['trials']),3)
        self.assertEqual(result['distributions']['cagr']['mean'],0.)
        self.assertEqual(result['distributions']['spy_cagr']['n'],3)
        self.assertTrue(all(row['growth']==1. and row['cagr']==0. and row['spy_cagr']>0 for row in result['trials']))
        self.assertTrue(all(row['empty_periods']>0 for row in result['trials']))

    def test_selection_order_survives_plan_and_reuses_random_books(self):
        store.company(self.db,'B',sector='Technology')
        research=self.db.research
        research.execute("INSERT INTO statements SELECT 'B',fiscal,known,market_cap,enterprise_value,ebitda/2,ebitda_yield/2 FROM statements WHERE symbol='A'")
        research.execute("INSERT INTO stock_days SELECT 'B',day,adjusted,adjusted_reason,volume,volume_reason FROM stock_days WHERE symbol='A'")
        research.execute("INSERT INTO fact_sources SELECT 'B',endpoint,sha256,disposition FROM fact_sources WHERE symbol='A'")
        options=dict(trials=2,seed=11,pool='cached',sector='Technology')
        first=self.config(**options);captured=[]
        r.run(self.db,first,capture=lambda number,result:captured.append(result))
        self.assertTrue(all(h['symbol']=='B' for result in captured for period in result['periods'] for h in period['holdings']))
        after=self.config(**options,selection_order='rank_first')
        self.assertEqual(after['samples'],first['samples'])
        self.assertEqual(after['options']['selection_order'],'rank_first')
        captured=[]
        with patch.object(financial_books,'book',side_effect=AssertionError('Reuse prepared random books')):
            result=r.run(self.db,after,capture=lambda number,result:captured.append(result))
        self.assertEqual(result['incomplete'],0)
        self.assertTrue(all(p['names']==0 for trial in captured for p in trial['periods']))
        self.assertTrue(all(trial['options']['selection_order']=='rank_first' for trial in captured))

    def test_interrupted_batch_keeps_completed_trial_books_for_retry(self):
        config=self.config(trials=3)
        def interrupt(event):
            if event['completed']==1:raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):r.run(self.db,config,interrupt)
        retained=self.db.execute('SELECT COUNT(*) FROM books WHERE latest=0').fetchone()[0]
        self.assertGreater(retained,0)
        result=r.run(self.db,config)
        self.assertEqual(result['completed'],3)
        self.assertGreaterEqual(self.db.execute('SELECT COUNT(*) FROM books WHERE latest=0').fetchone()[0],retained)

    def test_pool_switch_commits_each_trial_and_preserves_original_pool(self):
        original=self.config(trials=3,seed=11,pool='legacy')
        first=r.run(self.db,original)
        periods=self.db.execute('SELECT COUNT(*) FROM books WHERE latest=0').fetchone()[0]
        legacy=[tuple(row) for row in self.db.execute("SELECT * FROM book_rows WHERE pool='legacy' ORDER BY book,symbol")]
        wider=self.config(trials=3,seed=11,pool='cached')
        def interrupt(event):
            if event['completed']==1:raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):r.run(self.db,wider,interrupt)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM book_pools WHERE pool='cached'").fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM books WHERE latest=0').fetchone()[0],periods)
        self.assertEqual([tuple(row) for row in self.db.execute("SELECT * FROM book_rows WHERE pool='legacy' ORDER BY book,symbol")],legacy)
        with patch.object(financial_books,'book',side_effect=AssertionError('Original pool remains complete')),patch.object(facts.BookFacts,'reports',side_effect=AssertionError('Original pool remains complete')):
            replay=r.run(self.db,original)
        self.assertEqual([row['cagr'] for row in replay['trials']],[row['cagr'] for row in first['trials']])
        retry=r.run(self.db,wider)
        self.assertEqual([row['cagr'] for row in retry['trials']],[row['cagr'] for row in first['trials']])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM book_pools').fetchone()[0],2*periods)

    def test_optional_capture_keeps_full_trial_results_without_changing_summary(self):
        configuration=self.config(trials=3,seed=42)
        captured=[]
        result=r.run(self.db,configuration,capture=lambda number,trial:captured.append((number,trial)))
        self.assertEqual([number for number,trial in captured],[1,2,3])
        self.assertNotIn('trial_results',result)
        for (number,trial),summary in zip(captured,result['trials']):
            ordinary=s.backtest_dates(self.db,dates=configuration['samples'][number-1],start=configuration['start'],end=configuration['end'],months=configuration['months'],**configuration['options'])
            self.assertEqual({k:v for k,v in trial.items() if k!='seconds'},{k:v for k,v in ordinary.items() if k!='seconds'})
            self.assertEqual(trial['cagr'],summary['cagr'])
            self.assertTrue(trial['periods'][0]['holdings'])
        replay=r.run(self.db,configuration)
        self.assertEqual(result['distributions'],replay['distributions'])

    def test_calculation_owner_keeps_every_trial_holding(self):
        configuration=self.config(trials=2,seed=42)
        result=self.calculate('random',{},planned=configuration)
        self.assertEqual(len(result['trial_results']),2)
        for detail,summary in zip(result['trial_results'],result['trials']):
            self.assertEqual(len(detail['periods']),summary['periods'])
            self.assertEqual(detail['cagr'],summary['cagr'])
            self.assertEqual(detail['periods'][0]['holdings'][0]['symbol'],'A')

    def test_interrupted_batch_publishes_replay_identity_before_work(self):
        configuration=self.config(trials=2);published=[]
        with patch.object(r,'run',side_effect=ValueError('interrupted')),self.assertRaisesRegex(ValueError,'interrupted'):
            self.calculate('random',{},published.append,planned=configuration)
        self.assertEqual(published,[configuration])
        replay=r.plan(self.db,start=configuration['start'],end=configuration['end'],months=configuration['months'],trials=configuration['requested'],seed=configuration['seed'],**configuration['options'])
        self.assertEqual(replay['samples'],configuration['samples'])

    def test_exact_trial_dates_reproduce_the_trial(self):
        result=self.calculate('random',dict(start='2015-01-01',end='2016-12-30',months=24,trials=2,seed=42,rank_to=1))
        inspected=self.calculate('custom',dict(start='2015-01-01',end='2016-12-30',months=24,dates=result['trials'][0]['dates'],rank_to=1))
        self.assertAlmostEqual(inspected['cagr'],result['trials'][0]['cagr'])


if __name__=='__main__':unittest.main()
