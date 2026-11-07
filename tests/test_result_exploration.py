"""Saved return windows and original rank subsets, using private evidence."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from backtest import portfolio_results as portfolio
from backtest.application import result_exploration as explore
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


class ExplorationTests(unittest.TestCase):
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
        self.assertEqual(empty['empty'],2);self.assertIsNone(empty['growth']);self.assertIsNone(empty['total_return'])
        self.assertIsNone(empty['cagr']);self.assertIsNotNone(empty['spy_cagr']);self.assertEqual(empty['cash_days'],0)
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
