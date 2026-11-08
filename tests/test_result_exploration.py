"""Saved return windows and original rank subsets, using private evidence."""
from copy import deepcopy
from datetime import date
import json
import io
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from backtest import portfolio_results as portfolio
from backtest import result_evidence
from backtest.application import result_exploration as explore
from backtest.engines.original import robustness
from backtest.runtime import backtest_control
from test_portfolio_results import holding
from test_durable_evidence import source


def selection():
    return dict(trial=1,period_from=1,period_to=3,rank_from=1,rank_to=30)


def fixture(order='filter_first'):
    days=[date(year,1,2) for year in range(2007,2011)]
    pairs=list(zip(days,days[1:]))
    books={}
    for index,(entry,exit_day) in enumerate(pairs):
        rows=[holding('S'+str(rank),rank,(rank-15)/100*(index+1),entry=str(entry),exit=str(exit_day))
              for rank in range(1,31) if order=='filter_first' or rank%4]
        books[entry]=dict(entry=str(entry),exit=str(exit_day),holdings=rows,spy=[.1,-.2,.3][index])
    result=portfolio.evaluate(pairs,lambda a,b:books[a])
    result['options']=dict(rank_from=1,rank_to=30,selection_order=order)
    return result


def batch_fixture(trials=24, *, gaps=False):
    """Fictional 2000–2025 top-50 batch, independent of financial inputs."""
    originals=[];rows=[];samples=[]
    for trial in range(1,trials+1):
        days=[date(year,1,trial+1) for year in range(2000,2025)]+[date(2025,1,27)]
        pairs=list(zip(days,days[1:]))
        def book(entry,exit_day):
            holdings=[holding('S'+str(rank),rank,(rank-20+trial+(entry.year-2000)%4)/100,
                entry=str(entry),exit=str(exit_day)) for rank in range(1,51)
                if not gaps or rank%4 and not (trial==1 and entry.year==2012 and 20<=rank<=30)]
            return dict(entry=str(entry),exit=str(exit_day),holdings=holdings,spy=.02+(entry.year%3)/100)
        result=portfolio.evaluate(pairs,book,common_start=date(2000,1,1))
        result.update(options=dict(rank_from=1,rank_to=50,selection_order='rank_first'),seconds=.1)
        dates=[str(day) for day in days[:-1]]
        originals.append(result);samples.append(dates);rows.append(robustness.summarize(result,trial,dates))
    plan=dict(seed=42,requested=trials,start='2000-01-01',end='2025-01-27',months=12,
        window_start='2000-01-01',window_end='2025-01-27',options=originals[0]['options'],samples=samples,
        blocks=[dict(start=str(date(year,1,1))) for year in range(2000,2025)])
    return dict(robustness.summarize_trials(plan,rows,0),trial_results=originals)


class ExplorationTests(unittest.TestCase):
    def test_16_quarterly_trials_keep_cash_in_124_period_rank_selection(self):
        trials=[];rows=[];samples=[]
        for number in range(1,17):
            days=[date(1996+i//4,1+3*(i%4),number+1) for i in range(124)]+[date(2026,10,21)]
            def book(entry,exit_day):
                # Fifteen trials once lack ranks 20–30; their other books have rank 20.
                ranks=range(1,20) if number<16 and entry==days[number] else [20]
                stocks=[holding('S'+str(rank),rank,.01,entry=str(entry),exit=str(exit_day)) for rank in ranks]
                return dict(entry=str(entry),exit=str(exit_day),holdings=stocks,spy=.005)
            trial=portfolio.evaluate(list(zip(days,days[1:])),book,common_start=date(1996,1,2))
            trial.update(options=dict(rank_from=1,rank_to=50),seconds=0.)
            dates=list(map(str,days[:-1]));samples.append(dates)
            trials.append(trial);rows.append(robustness.summarize(trial,number,dates))
        plan=dict(seed=42,requested=16,options=trials[0]['options'],samples=samples)
        original=dict(robustness.summarize_trials(plan,rows,0),trial_results=trials)
        actual=explore.eager(original,dict(trial='all',period_from=1,period_to=124,rank_from=20,rank_to=30))
        self.assertEqual((actual['valid'],actual['incomplete']),(16,0))
        self.assertEqual([row['empty_periods'] for row in actual['trials']],[1]*15+[0])
        self.assertEqual(actual['distributions']['cagr']['n'],16)
        self.assertEqual(actual['distributions']['spy_cagr']['n'],16)
        for number,row in enumerate(actual['trials'],1):
            growth=1.
            for _ in range(123 if number<16 else 124):growth*=1.01
            self.assertEqual(row['growth'],growth)
            self.assertEqual((row['start'],row['end']),('1996-01-02','2026-10-21'))

    def test_legacy_empty_periods_apply_cash_without_rewriting_saved_values(self):
        original=batch_fixture(2)
        for trial,row in zip(original['trial_results'],original['trials']):
            trial['periods'][1].update(holdings=[],names=0,portfolio=None)
            trial.update(growth=None,cagr=None)
            row.update(growth=None,cagr=None,total_return=None,excess_cagr=None,empty_periods=1)
        original.update(valid=0,incomplete=2)
        before=json.dumps(original)
        chosen=dict(trial='all',period_from=1,period_to=25,rank_from=1,rank_to=50)
        eager=explore.eager(original,chosen)
        self.assertEqual((eager['valid'],eager['incomplete']),(2,0))
        stream=io.BytesIO()
        writer=result_evidence.Writer(stream,trials=2,metadata=dict(mode='random'),max_bytes=16*1024**2)
        for number,trial in enumerate(original['trial_results'],1):
            writer.start_trial(number)
            for period in trial['periods']:writer.period(period)
            writer.end_trial({key:value for key,value in trial.items() if key!='periods'})
        writer.finish({key:value for key,value in original.items() if key!='trial_results'})
        encoded=stream.getvalue();reader=result_evidence.Reader(stream,max_bytes=16*1024**2)
        bounded=explore.evidence(reader,chosen)
        self.assertEqual(bounded['trials'],eager['trials'])
        for number,trial in enumerate(original['trial_results'],1):
            expected=1.
            for period in trial['periods']:expected*=1+(period['portfolio'] or 0.)
            value=explore.eager(trial,dict(chosen,trial=1))
            self.assertEqual(value['growth'],expected)
            self.assertEqual(bounded['trials'][number-1]['growth'],expected)
        self.assertEqual(json.dumps(original),before);self.assertEqual(stream.getvalue(),encoded)
        for names,holdings,value in ((1,[original['trial_results'][0]['periods'][0]['holdings'][0]],None),(0,[],.1)):
            broken=deepcopy(original['trial_results'][0])
            broken['periods'][1].update(names=names,holdings=holdings,portfolio=value)
            with self.assertRaises(ValueError):explore.eager(broken,dict(chosen,trial=1))
        broken=deepcopy(original['trial_results'][0]);del broken['periods'][1]['portfolio']
        with self.assertRaises(ValueError):explore.eager(broken,dict(chosen,trial=1))

    def test_all_24_trials_date_rank_subsets_and_shared_window(self):
        original=batch_fixture();before=json.dumps(original)
        chosen=dict(trial='all',period_from=11,period_to=15,rank_from=20,rank_to=30)
        with patch('sqlite3.connect',side_effect=AssertionError('No inputs or stores')):
            actual=explore.eager(original,chosen)
        self.assertEqual((actual['completed'],actual['valid'],actual['incomplete']),(24,24,0))
        self.assertEqual(actual['exploration']['start'],'2010-01-02')
        self.assertEqual(actual['exploration']['end'],'2015-01-25')
        years=(date(2015,1,25)-date(2010,1,2)).days/365.25
        for number,(row,trial) in enumerate(zip(actual['trials'],original['trial_results']),1):
            growth=spy=1.
            for period in trial['periods'][10:15]:
                values=[h['return_value'] for h in period['holdings'] if 20<=h['rank']<=30]
                growth*=1+sum(values)/len(values);spy*=1+period['spy']
            self.assertEqual(row['growth'],growth);self.assertEqual(row['spy_growth'],spy)
            self.assertEqual(row['cagr'],growth**(1/years)-1)
            self.assertEqual(row['spy_cagr'],spy**(1/years)-1)
            self.assertEqual(row['cash_days'],number-1)
            self.assertEqual(row['final_cash_days'],24-number)
            self.assertEqual(row['dates'],original['configuration']['samples'][number-1][10:15])
        for key in ('cagr','spy_cagr','excess_cagr','total_return','growth'):
            self.assertEqual(actual['distributions'][key],robustness.distribution([row[key] for row in actual['trials']]))
        self.assertEqual(json.dumps(original),before)
        self.assertNotIn('trial_results',actual)
        original['distributions']['cagr']['mean']=.12345
        whole=explore.eager(original,dict(chosen,period_from=1,period_to=25,rank_from=1,rank_to=50))
        self.assertEqual({key:value for key,value in whole.items() if key!='exploration'},
                         {key:value for key,value in original.items() if key!='trial_results'})

    def test_batch_codec_agrees_in_two_scans_and_includes_cash_periods(self):
        original=batch_fixture(3,gaps=True);stream=io.BytesIO()
        writer=result_evidence.Writer(stream,trials=3,metadata=dict(mode='random'),max_bytes=16*1024**2)
        for number,trial in enumerate(original['trial_results'],1):
            writer.start_trial(number)
            for period in trial['periods']:writer.period(period)
            writer.end_trial({key:value for key,value in trial.items() if key!='periods'})
        writer.finish({key:value for key,value in original.items() if key!='trial_results'})
        reader=result_evidence.Reader(stream,max_bytes=16*1024**2);before=stream.getvalue()
        chosen=dict(trial='all',period_from=11,period_to=15,rank_from=20,rank_to=30)
        with patch.object(reader,'verified_records',wraps=reader.verified_records) as reads:
            actual=explore.evidence(reader,chosen)
        self.assertEqual(reads.call_count,2,'Two batch scans, independent of trial count')
        expected=explore.eager(original,chosen)
        actual.pop('seconds');expected.pop('seconds');self.assertEqual(actual,expected)
        self.assertEqual((actual['valid'],actual['incomplete']),(3,0))
        self.assertEqual(actual['trials'][0]['empty_periods'],1)
        self.assertIsNotNone(actual['trials'][0]['cagr'])
        self.assertEqual(actual['distributions']['spy_cagr']['n'],3)
        self.assertEqual(stream.getvalue(),before)
        for changes in ({'period_to':26},{'rank_to':51}):
            with self.assertRaises(ValueError):explore.evidence(reader,dict(chosen,**changes))
        with self.assertRaises(ValueError):explore.eager(fixture(),chosen)
        with patch.object(backtest_control,'checkpoint',side_effect=backtest_control.Cancelled):
            with self.assertRaises(backtest_control.Cancelled):explore.evidence(reader,chosen)

    def test_date_and_rank_subsets_match_direct_selection_without_changing_original(self):
        for order in ('filter_first','rank_first'):
            original=fixture(order);before=json.dumps(original)
            for first,last in ((1,30),(1,10),(20,30)):
                for period_from in (1,2):
                    chosen=dict(trial=1,period_from=period_from,period_to=3,rank_from=first,rank_to=last)
                    value=explore.eager(original,chosen)
                    periods=original['periods'][period_from-1:]
                    growth=spy=1.
                    for period in periods:
                        returns=[h['return_value'] for h in period['holdings'] if first<=h['rank']<=last]
                        growth*=1+sum(returns)/len(returns)
                        spy*=1+period['spy']
                    self.assertEqual(value['growth'],growth)
                    self.assertEqual(value['spy_growth'],spy)
                    self.assertEqual(value['start'],periods[0]['entry'])
                    self.assertEqual(value['total_return'],growth-1)
                    self.assertEqual(json.dumps(original),before)

    def test_eager_and_bounded_readers_agree_for_both_random_trials(self):
        reader,_,originals=source('random')
        before=reader.stream.getvalue()
        for trial,original in enumerate(originals,1):
            for bounds in ((1,3,1,53),(2,3,1,2),(1,2,2,2)):
                first,last,lower,upper=bounds
                chosen=dict(trial=trial,period_from=first,period_to=last,rank_from=lower,rank_to=upper)
                with patch('sqlite3.connect',side_effect=AssertionError('No inputs or stores')):
                    actual=explore.evidence(reader,chosen)
                    expected=explore.eager(original,dict(chosen,trial=1))
                self.assertEqual(actual,expected)
        self.assertEqual(reader.stream.getvalue(),before)

    def test_empty_subset_loss_cash_and_recorded_rounding(self):
        original=fixture()
        original.update(start='2006-12-29',cash_days=4,first_trade='2007-01-02')
        for period in original['periods']:
            period['holdings']=[h for h in period['holdings'] if h['rank']<20]
            period['names']=len(period['holdings'])
        empty=explore.eager(original,selection())  # Stored period means remain original.
        self.assertEqual(empty['cash_days'],4)
        chosen=dict(trial=1,period_from=2,period_to=3,rank_from=20,rank_to=30)
        empty=explore.eager(original,chosen)
        self.assertEqual(empty['empty'],2);self.assertEqual(empty['growth'],1.);self.assertEqual(empty['total_return'],0.)
        self.assertEqual(empty['cagr'],0.);self.assertIsNotNone(empty['spy_cagr']);self.assertEqual(empty['cash_days'],0)
        for period in original['periods']:
            period['holdings'][0]['return_value']=-1.
        loss=explore.eager(original,dict(chosen,rank_from=1,rank_to=1))
        self.assertEqual((loss['growth'],loss['total_return'],loss['cagr']),(0.,-1.,-1.))
        original.update(growth=1.12345,spy_growth=1.23456,cagr=.01234,spy_cagr=.02345)
        saved=explore.eager(original,selection())
        self.assertEqual(tuple(saved[k] for k in ('growth','spy_growth','cagr','spy_cagr')),(1.12345,1.23456,.01234,.02345))

    def test_legacy_year_labels_allow_total_return_without_inventing_cagr(self):
        original=fixture()
        original['periods'][0]['exit']='2008'
        original['periods'][1].update(entry='2008',exit='2009')
        original['periods'][2]['entry']='2009'
        chosen=dict(trial=1,period_from=2,period_to=3,rank_from=1,rank_to=10)
        value=explore.eager(original,chosen)
        self.assertEqual(value['start'],'2008');self.assertIsNotNone(value['total_return'])
        self.assertIsNone(value['cagr']);self.assertIsNone(value['spy_cagr'])

    def test_bad_selections_and_missing_returns_fail_without_fallback(self):
        original=fixture()
        valid=selection()
        for changes in ({'period_from':0},{'period_to':4},{'rank_from':0},{'rank_to':31},
                        {'rank_from':True},{'trial':2},{'extra':1},{'rank_from':20,'rank_to':10}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):explore.eager(original,dict(valid,**changes))
        for value in (None,float('nan'),float('inf'),-1.1,True):
            changed=deepcopy(original);changed['periods'][0]['holdings'][0]['return_value']=value
            with self.subTest(value=value),self.assertRaises(ValueError):
                explore.eager(changed,dict(valid,rank_to=1))
        changed=deepcopy(original);changed['periods'][0]['holdings'][0].pop('rank')
        with self.assertRaises(ValueError):explore.eager(changed,dict(valid,rank_to=1))
        with backtest_control.cancel_when(lambda:False):
            with patch.object(backtest_control,'checkpoint',side_effect=backtest_control.Cancelled):
                with self.assertRaises(backtest_control.Cancelled):explore.eager(original,valid)

    def test_shared_reducer_preserves_original_python_arithmetic_exactly(self):
        rng=random.Random(109)
        for _ in range(200):
            returns=[[rng.uniform(-1,8) for _ in range(30)] for _ in range(3)]
            means=[sum(values)/len(values) for values in returns]
            self.assertEqual([portfolio.mean_return(iter(values)) for values in returns],means)
            growth=1.
            for value in means:growth=growth*(1+value)
            actual=portfolio.reduce_returns(((value,.01) for value in means),start=date(2008,1,2),end=date(2011,1,2))
            self.assertEqual(actual['growth'],growth)
            self.assertEqual(actual['cagr'],growth**(1/((date(2011,1,2)-date(2008,1,2)).days/365.25))-1)


if __name__=='__main__':unittest.main()
