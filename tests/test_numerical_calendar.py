"""Candidate calendar/evidence qualification before browser controls."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'scripts')]
import test_numerical_trials as trial_tests
from numerical_portfolio import compare_results
import numerical_calendar as calendar
import numerical_random
import portfolio_results


class CalendarTests(unittest.TestCase):
    setUp=trial_tests.NumericalTrialsTests.setUp
    evaluator=trial_tests.NumericalTrialsTests.evaluator

    def test_week_month_evaluation_24_trials_replay_filters_and_empty(self):
        inputs,provider,portfolio,store=self.evaluator()
        for unit,count in [('week',1),('week',2),('week',104),('month',2),('month',24)]:
            for pool in ('legacy','cached'):
                request=dict(calendar=dict(version=1,start='2015-01-02',end='2016-12-30',interval=dict(unit=unit,count=count)),
                             pool=pool,rank_to=3,min_cap=0.,min_ev=0.)
                pairs,first,selection,metadata=calendar.periods(portfolio._calendar().sessions,request)
                expected=self.s.backtest_periods(self.db,pairs,months=12,**selection) if hasattr(self,'s') else inputs.s.backtest_periods(self.db,pairs,months=12,**selection)
                expected.pop('months');expected.update(metadata)
                actual=portfolio.backtest_calendar(**request)['result']
                self.assertTrue(compare_results(expected,actual)['exact'])
        request=dict(calendar=dict(version=1,start='2015-01-02',end='2015-02-27',interval=dict(unit='week',count=1)),
                     pool='cached',rank_to=3,min_cap=0.,min_ev=0.,trials=24,seed=42)
        for filters in ([],[dict(field='pe',op='lt',value=20.)],[dict(field='pe',op='gt',value=1e9)]):
            planned=calendar.plan(portfolio._calendar().sessions,dict(request,filters=filters))
            self.assertEqual(calendar.validate_plan(portfolio._calendar().sessions,planned),planned)
            experiment=store.open(numerical_random.checkpoint_binding(portfolio,planned))
            captured=[]
            result=numerical_random.run(portfolio,planned,experiment,capture=lambda n,r:captured.append(r))['result']
            self.assertEqual(result['completed'],24);self.assertEqual(len(captured),24)
            for dates,actual in zip(planned['samples'],captured):
                config=planned['calendar']
                expected=inputs.s.backtest_dates(self.db,dates=dates,start=config['start'],end=config['end'],months=12,**planned['options'])
                expected.pop('months');expected['calendar']=config
                self.assertTrue(compare_results(expected,actual)['exact'])
                portfolio_results.validate_completed(actual)
            replay=numerical_random.run(portfolio,planned,experiment)['result']
            self.assertEqual(replay['distributions'],result['distributions'])
            self.assertEqual(replay['execution']['recovered_trials'],24)
            self.assertEqual(result['valid'],0 if filters and filters[0]['op']=='gt' else 24)

    def test_request_rejections_and_immutable_recorded_samples(self):
        value=dict(calendar=dict(version=1,start='2015-01-02',end='2015-02-27',interval=dict(unit='week',count=1)))
        for key,item in [('months',12),('start','2015-01-02'),('version',1),('interval',{})]:
            with self.assertRaises(ValueError):calendar.decode_request(dict(value,**{key:item}))
        for count in [None,True,0,105,1.5]:
            invalid=deepcopy(value);invalid['calendar']['interval']['count']=count
            with self.assertRaises(ValueError):calendar.decode_request(invalid)
        sessions=[date(2015,1,2),date(2015,1,5),date(2015,1,9),date(2015,1,12),date(2015,2,27)]
        plan=calendar.plan(sessions,dict(value,trials=1,seed=42))
        original=deepcopy(plan)
        plan['samples'][0][0]='2015-01-05'
        self.assertEqual(calendar.validate_plan(sessions,plan),plan)
        self.assertEqual(original['seed'],plan['seed'])
        self.assertEqual(calendar.metadata({'months':12}),{'months':12})
        with self.assertRaises(ValueError):calendar.metadata(dict(value,months=12))


if __name__=='__main__':unittest.main()
