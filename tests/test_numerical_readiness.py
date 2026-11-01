"""Startup ordering and closure faults without financial calculation timing."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock
ROOT=Path(__file__).absolute().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.runtime import backtest_control as backtest_control
from backtest.engines.numerical.execution import ExecutionPolicy
from backtest.engines.numerical import trial_pool as pools


class ConcurrentReadinessTests(unittest.TestCase):
    def make(self,workers=4):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        policy=ExecutionPolicy(dict(workers=workers,threads_per_worker=1,lane_budget=workers))
        value=pools.TrialPool(source_root=ROOT,scratch=Path(folder.name)/'pool',reference={'identity':'generation'},
            source_identity={},compiler_identity={'signature':'compiler'},policy=policy)
        self.addCleanup(pools._PENDING.pop,id(value),None)
        return value

    def fake(self,pool,*,fault=None):
        constructed=[]
        def ready(index):
            return dict(event='ready',generation='generation',source=pool.source_identity_hash,
                backend='numba',compiler='compiler',threads=1,pid=index+1,measurements={'sampled_private_bytes':1000})
        class Worker:
            def __init__(self,owner,index,launch):
                self.index=index;self.ready=None
                constructed.append(index)
                if index==0:owner.events.put((index,ready(index)))
                elif index==3:
                    for number in (3,1,2):
                        event=ready(number)
                        if fault=='mismatch' and number==2:event['compiler']='changed'
                        if fault=='failure' and number==2:event={'event':'failed'}
                        owner.events.put((number,event))
        pool.source_identity_hash=pools.trial_checkpoints.digest(pools.trial_checkpoints.canonical(pool.source_identity))
        return Worker,constructed

    def test_probe_precedes_duplication_and_remaining_readiness_can_arrive_out_of_order(self):
        pool=self.make();worker,constructed=self.fake(pool)
        def admit(measurement):
            self.assertEqual(constructed,[0]);return {'admitted':True}
        with patch.object(pools,'_Worker',worker),patch.object(pool.policy,'admit_cold_worker',side_effect=admit):
            pool.start()
        self.assertEqual(constructed,[0,1,2,3])
        self.assertEqual([row['pid'] for row in pool.stats['readiness']],[1,4,2,3])
        self.assertEqual(pool.stats['started_workers'],4)

    def test_late_failure_or_identity_mismatch_closes_every_adopted_worker(self):
        for fault,error in (('failure',RuntimeError),('mismatch',ValueError)):
            pool=self.make();worker,constructed=self.fake(pool,fault=fault)
            with patch.object(pools,'_Worker',worker),patch.object(pool.policy,'admit_cold_worker'),patch.object(pool,'close') as close:
                with self.assertRaises(error):pool.start()
                close.assert_called_once()
            self.assertTrue(pool.poisoned);self.assertEqual(constructed,[0,1,2,3])

    def test_partial_launch_cancellation_adopts_before_close(self):
        pool=self.make();worker,constructed=self.fake(pool)
        original=worker.__init__
        def fail(value,owner,index,launch):
            if index==2:
                self.assertIs(owner.workers[2],value)
                raise backtest_control.Cancelled()
            original(value,owner,index,launch)
        with patch.object(worker,'__init__',fail),patch.object(pools,'_Worker',worker),patch.object(pool.policy,'admit_cold_worker'),patch.object(pool,'close') as close:
            with self.assertRaises(backtest_control.Cancelled):pool.start()
            close.assert_called_once()
        self.assertEqual(len(pool.workers),3)

    def test_six_workers_can_emit_the_complete_startup_protocol_before_drain(self):
        pool=self.make(6)
        source=pools.trial_checkpoints.digest(pools.trial_checkpoints.canonical(pool.source_identity))
        class Worker:
            def __init__(self,owner,index,launch):
                self.index=index;self.ready=None
                for stage in ('source-owned','attaching','initializing'):
                    owner.events.put_nowait((index,{'event':'stage','stage':stage}))
                owner.events.put_nowait((index,dict(event='ready',generation='generation',source=source,
                    backend='numba',compiler='compiler',threads=1,pid=index+1,measurements={'sampled_private_bytes':1000})))
        with patch.object(pools,'_Worker',Worker),patch.object(pool.policy,'admit_cold_worker'):
            pool.start()
        self.assertEqual(pool.stats['started_workers'],6)
        self.assertFalse(pool.transport_failure)

    def test_staggered_deadlines_expire_earliest_unfinished_worker_amid_interleaved_events(self):
        pool=self.make();pool.policy.start_seconds=10.
        source=pools.trial_checkpoints.digest(pools.trial_checkpoints.canonical(pool.source_identity))
        clock=[0.]
        def ready(index):return dict(event='ready',generation='generation',source=source,backend='numba',
            compiler='compiler',threads=1,pid=index+1,measurements={'sampled_private_bytes':1000})
        class Worker:
            def __init__(self,owner,index,launch):
                self.index=index;self.ready=None;clock[0]+=2
                if index==0:owner.events.put((0,ready(0)))
                elif index==3:
                    owner.events.put((3,{'event':'stage','stage':'attaching'}))
                    owner.events.put((2,ready(2)))
                    owner.events.put((3,{'event':'stage','stage':'initializing'}))
        original=pool.events.get;count=[0]
        def event(*args,**kwargs):
            value=original(*args,**kwargs);count[0]+=1
            clock[0]={1:2.,2:9.,3:11.,4:12.5}[count[0]]
            return value
        with patch.object(pools,'_Worker',Worker),patch.object(pools.time,'monotonic',side_effect=lambda:clock[0]),patch.object(pool.events,'get',side_effect=event),patch.object(pool.policy,'admit_cold_worker'),patch.object(pool,'close') as close,patch.object(pool,'_send') as send:
            with self.assertRaises(TimeoutError):pool.start()
            close.assert_called_once();send.assert_not_called()
        # Worker 1's deadline is 12; worker 2 became ready before its 14,
        # while worker 3's own deadline is 16. Its traffic cannot extend 12.
        self.assertEqual(clock[0],12.5)
        self.assertEqual([row['pid'] for row in pool.stats['readiness']],[1,3])
        self.assertEqual(len(pool.workers),4);self.assertTrue(pool.poisoned)

if __name__=='__main__':unittest.main()
