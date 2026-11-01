"""Candidate calendar/evidence qualification before browser controls."""

# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))
from copy import deepcopy
from datetime import date
from datetime import timedelta
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'scripts')]
import test_numerical_trials as trial_tests
from numerical_portfolio import compare_results
from backtest import calendar_requests as calendar
import numerical_random
from backtest import portfolio_results as portfolio_results


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

    def test_weekly_complete_trailing_mixed_and_empty_source_guard_reference(self):
        inputs,provider,portfolio,store=trial_tests.NumericalTrialsTests.evaluator(self,'source')
        trailing=[dict(field=name,op='gt',value=0.) for name in ('return_1y','return_3y')]
        observations=[]
        for pool in ('cached','legacy'):
            for count in (1,2,13,104):
                for filters in (trailing,trailing+[dict(field='pe',op='lt',value=20.)],
                                trailing+[dict(field='pe',op='gt',value=1e9)]):
                    options=dict(calendar=dict(version=1,start='2015-01-05',end='2015-03-31',
                        interval=dict(unit='week',count=count)),pool=pool,rank_to=100,
                        metric='ev_ebitda_3y',min_cap=0.,min_ev=0.,filters=filters,trials=3,seed=42)
                    plan=calendar.plan(portfolio._calendar().sessions,options)
                    experiment=store.open(numerical_random.checkpoint_binding(portfolio,plan))
                    self.assertEqual(experiment.read(),[])
                    captured=[]
                    result=numerical_random.run(portfolio,plan,experiment,capture=lambda n,r:captured.append(r))['result']
                    empty=filters[-1]['op']=='gt' and filters[-1]['field']=='pe'
                    self.assertEqual((result['completed'],result['valid']),(3,0 if empty else 3))
                    maximum_absolute=maximum_relative=0.
                    for dates,actual in zip(plan['samples'],captured,strict=True):
                        expected=inputs.s.backtest_dates(self.db,dates=dates,start=plan['calendar']['start'],
                            end=plan['calendar']['end'],months=12,**plan['options'])
                        expected.pop('months');expected['calendar']=plan['calendar']
                        agreement=compare_results(expected,actual);self.assertTrue(agreement['exact'],agreement)
                        maximum_absolute=max(maximum_absolute,agreement['maximum_absolute'])
                        maximum_relative=max(maximum_relative,agreement['maximum_relative'])
                    observations.append(dict(configuration=plan,valid=result['valid'],incomplete=result['incomplete'],
                        maximum_absolute=maximum_absolute,maximum_relative=maximum_relative))
        print(__import__('json').dumps(dict(check='weekly-filter-source-reference',observations=observations)),flush=True)

    def test_full_window_default_result_admission_capacity_failure(self):
        # Run the actual Session preflight without preparing a huge fixture or
        # weakening its bound. Passing this regression records a FAILED release
        # capacity gate: these promised workloads cannot currently be admitted.
        from types import SimpleNamespace
        from unittest.mock import Mock
        from numerical_session import Session
        sessions=[];day=date(1997,1,1)
        while day<=date(2025,12,31):
            if day.weekday()<5:sessions.append(day)
            day+=timedelta(days=1)
        observations=[]
        for unit,count,trials in [('week',1,24),('week',1,100),('month',12,100)]:
            options=dict(calendar=dict(version=1,start='1997-01-01',end='2025-12-31',
                interval=dict(unit=unit,count=count)),trials=trials,seed=42,pool='cached',rank_to=50)
            plan=calendar.plan(sessions,options)
            owner=object.__new__(Session)
            owner.validate=Mock();owner.plan=Mock(return_value=plan)
            owner.inputs=SimpleNamespace(symbols=list(range(64)))
            owner.result_workspace_bytes=256*1024**2
            owner.checkpoints=SimpleNamespace(open=Mock(side_effect=AssertionError('No checkpoint before admission')))
            callback=Mock(side_effect=AssertionError('No configuration before admission'))
            with self.assertRaisesRegex(ValueError,'result workspace bound'):
                owner.calculate('random',options,None,callback)
            owner.validate.assert_called_once();owner.checkpoints.open.assert_not_called();callback.assert_not_called()
            periods=sum(len(v) for v in plan['samples'])
            observations.append(dict(options=options,periods=periods,
                estimated_result_bytes=periods*(16384+4096*50),result_workspace_bytes=owner.result_workspace_bytes,
                release_gate='failed',outcome='rejected before configuration/checkpoint/calculation'))
        print(__import__('json').dumps(dict(check='full-window-admission',
            scope='fictional weekday calendar and 64 symbols; structural admission, no timing/capacity execution',
            observations=observations)),flush=True)


if __name__=='__main__':unittest.main()
