"""Actual adapters share canonical calendars, selection and immutable evidence."""

# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))
from contextlib import ExitStack
from copy import deepcopy
import json
import sqlite3
import unittest
from unittest.mock import patch

import test_engine_selection as selection_tests
import test_candidate_calculations as candidate_tests
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.engines.numerical.portfolio import compare_results
from test_operating_spread_engine import financial_inputs, FILTERS
import engine_selection
from backtest import calendar_requests as calendar_requests
import backtest_queue
from test_queue import request


class WebsiteAlignmentTests(unittest.TestCase):
    setUp=selection_tests.RuntimeSelectionTests.setUp
    make=selection_tests.RuntimeSelectionTests.make
    assert_closed=selection_tests.RuntimeSelectionTests.assert_closed

    def owner(self):
        financial_inputs(self.fixture.fixture.db)
        self.fixture.binding['daily']=dict(alignment=True)
        self.fixture.prepare()
        (self.root/'binding.json').write_text(json.dumps(self.fixture.binding))
        candidate=candidate_tests.CandidateTests.candidate(self)
        owner=engine_selection.Selectable(candidate.preparation);owner.experimental=candidate
        owner.status=lambda:dict(state='current')
        self.addCleanup(owner.close);self.addCleanup(owner.retire)
        def connect():
            db=sqlite3.connect(self.fixture.fixture.path);db.row_factory=sqlite3.Row;return db
        context=ExitStack();self.addCleanup(context.close)
        context.enter_context(patch('backtest.inputs.daily.connect',side_effect=connect))
        context.enter_context(patch('backtest.runtime.cache_access.workspace',self.fixture.owner))
        return owner,candidate

    def compare(self,a,b):
        self.assertEqual(a['producer']['engine'],'original')
        self.assertEqual(b['producer']['engine'],'experimental')
        if 'trial_results' in a:
            self.assertEqual(a['configuration'],b['configuration'])
            self.assertEqual(a['distributions'],b['distributions'])
            for x,y in zip(a['trial_results'],b['trial_results'],strict=True):
                self.assertTrue(compare_results(x,y)['exact'])
        else:self.assertTrue(compare_results({k:v for k,v in a.items() if k!='producer'},
                                                  {k:v for k,v in b.items() if k!='producer'})['exact'])

    def test_canonical_week_month_both_pools_orders_and_explicit_dates(self):
        owner,candidate=self.owner()
        for unit,count in (('week',2),('month',2)):
            calendar=dict(version=1,start='2015-01-05',end='2015-04-30',interval=dict(unit=unit,count=count))
            for pool in ('legacy','cached'):
                for order in ('filter_first','rank_first'):
                    options=dict(calendar=calendar,pool=pool,selection_order=order,rank_to=3,
                                 min_cap=0.,min_ev=0.,filters=FILTERS)
                    a=owner.calculate('custom',dict(options,engine='original'),None,None)
                    b=owner.calculate('custom',dict(options,engine='experimental'),None,None)
                    self.compare(a,b);self.assertEqual(a['calendar'],calendar);self.assertNotIn('months',a)
                    self.assertIsNone(candidate.runtime);self.assert_closed(candidate.created[-1])
            explicit=dict(options,dates=['2015-01-20','2015-03-03'])
            self.compare(owner.calculate('custom',dict(explicit,engine='original'),None,None),
                         owner.calculate('custom',dict(explicit,engine='experimental'),None,None))

    def test_full_plan_original_to_experimental_queue_recovery_without_resampling(self):
        owner,candidate=self.owner()
        options=dict(calendar=dict(version=1,start='2015-01-05',end='2015-03-31',interval=dict(unit='week',count=2)),
                     pool='cached',rank_to=3,min_cap=0.,min_ev=0.,trials=3,seed=2607948532,filters=FILTERS)
        plans=[];a=owner.calculate('random',dict(options,engine='original'),None,plans.append)
        before=deepcopy(plans[0])
        with patch.object(calendar_requests,'plan',side_effect=AssertionError('Must retain exact submitted plan')):
            b=owner.calculate('random',dict(options,engine='experimental'),None,None,planned=plans[0])
            self.compare(a,b)
            for engine in ('original','experimental'):
                store=backtest_queue.Store(self.root/(engine+'-alignment.sqlite'))
                item=store.enqueue(request(mode='random',options=dict(options,engine=engine)))
                store.claim();store.progress(item['id'],'configuration',plans[0]);store.recover()
                queue=backtest_queue.Queue(backtest_queue.Store(store.path),calculations=owner,library=backtest_queue.saved_backtests.Store((backtest_queue.Store(store.path)).path.with_name('saved-library.sqlite')))
                queue._run(queue.store.claim());record=queue.store.get(item['id'])
                self.assertEqual(record['state'],'complete');self.assertEqual(record['snapshot']['result']['producer']['engine'],engine)
                self.assertEqual(record['snapshot']['result']['configuration'],before)
        self.assertEqual(plans[0],before)
        with self.assertRaisesRegex(ValueError,'differ'):
            owner.calculate('random',dict(options,selection_order='rank_first'),None,None,planned=before)
        self.assertIsNone(candidate.runtime)


if __name__=='__main__':unittest.main()
