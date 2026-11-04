"""Canonical candidate queue plans survive shutdown before numerical execution."""
import json
from threading import Event,Thread
from unittest.mock import patch
import unittest

import test_candidate_calculations as candidate_tests
from backtest.application import queue as backtest_queue
from backtest.application import calculations as engine_selection
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.runtime import backtest_control as backtest_control
import test_calculations as calculation_tests
from unittest.mock import Mock
from test_queue import request


class CalendarRecoveryTests(unittest.TestCase):
    setUp=candidate_tests.CandidateTests.setUp
    make=candidate_tests.CandidateTests.make
    options=candidate_tests.CandidateTests.options
    candidate=candidate_tests.CandidateTests.candidate
    assert_closed=candidate_tests.CandidateTests.assert_closed

    def test_busy_queue_submission_is_advisory_but_unavailable_is_rejected(self):
        candidate=self.candidate()
        owner=engine_selection.Selectable(candidate.preparation);owner.experimental=candidate
        # Inspect the fictional candidate directly; dependency probing is separate.
        owner.status=candidate.status;self.service=owner
        options=dict(self.options(),engine='experimental')
        store=backtest_queue.Store(self.root/'busy-queue.sqlite')
        queue=backtest_queue.Queue(store,calculations=owner,library=backtest_queue.saved_backtests.Store((store).path.with_name('saved-library.sqlite')))
        handler=calculation_tests.CalculationTests.handler(self,'/api/backtest-queue',request(options=options))
        handler.server.backtest_queue=queue;handler.command='POST'
        candidate.operation.acquire()
        try:
            self.assertFalse(candidate.ready())
            with patch.object(candidate,'calculate',side_effect=AssertionError('No calculation during submission')):
                calculation_tests.serve.backtests.queue_request(handler,calculation_tests.serve.DATA_JOBS)
            self.assertEqual(handler.replies[0][0],200)
            self.assertEqual(store.listing()['records'][0]['state'],'queued')
        finally:candidate.operation.release()
        candidate.preparation.status.return_value=dict(state='unavailable')
        unavailable=calculation_tests.CalculationTests.handler(self,'/api/backtest-queue',request(options=options))
        self.assertFalse(calculation_tests.serve.backtests.require_calculation(unavailable,options));self.assertEqual(unavailable.replies[0][0],503)
        self.assertFalse(candidate.ready());queue.close()

    def test_canonical_plan_shutdown_requeue_replay_and_complete_snapshot(self):
        owner=self.candidate()
        options=dict(calendar=dict(version=1,start='2015-01-02',end='2015-02-27',interval=dict(unit='week',count=1)),trials=24,seed=42,rank_to=3)
        store=backtest_queue.Store(self.root/'canonical-queue.sqlite')
        item=store.enqueue(request(mode='random',options=options))
        queue=backtest_queue.Queue(store,calculations=owner,library=backtest_queue.saved_backtests.Store((store).path.with_name('saved-library.sqlite')));planned=Event();release=Event();original=store.progress;plans=[]
        def progress(identifier,field,value):
            original(identifier,field,value)
            if field=='configuration':
                plans.append(value);planned.set();release.wait(10);backtest_control.checkpoint()
        with patch.object(store,'progress',side_effect=progress):
            thread=Thread(target=queue._run,args=(store.claim(),));thread.start()
            self.assertTrue(planned.wait(30))
            queue.request_stop();owner.close();release.set();thread.join(30)
            self.assertFalse(thread.is_alive())
        self.assertEqual(store.get(item['id'])['state'],'queued')
        owner.retire();replacement=self.candidate();queue=backtest_queue.Queue(store,calculations=replacement,library=backtest_queue.saved_backtests.Store((store).path.with_name('saved-library.sqlite')))
        job=store.claim();self.assertEqual(json.loads(job['plan']),plans[0]);queue._run(job)
        record=store.get(item['id']);self.assertEqual(record['state'],'complete')
        result=record['snapshot']['result']
        self.assertEqual(result['configuration'],plans[0]);self.assertEqual(len(result['trial_results']),24)
        self.assertEqual(record['snapshot']['settings']['calendar'],options['calendar'])
        queue.close()


if __name__=='__main__':unittest.main()
