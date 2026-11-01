"""Atomic derived-trial publication and failure-closed replay on private stores."""

# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))
from copy import deepcopy
from contextlib import closing
from datetime import date
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from backtest import portfolio_results as portfolio_results
import trial_checkpoints as checkpoints


def binding(**changes):
    config=dict(start='2015-01-01',end='2016-01-04',window_start='2015-01-01',window_end='2016-01-04',
                months=12,seed=42,requested=2,options={},blocks=[],samples=[['2015-01-02'],['2015-01-02']])
    result=dict(generation='generation-1',policy='policy-1',schema='schema-1',result_contract=1,
                implementation={'source':'sha-1'},execution={'python':'fixture'},configuration=config)
    result.update(changes)
    return result


def completed(spy=.2):
    result=portfolio_results.evaluate([(date(2015,1,2),date(2016,1,4))],
        lambda entry,exit_day:dict(entry=str(entry),exit=str(exit_day),holdings=[],spy=spy),
        common_start=date(2015,1,1))
    result.update(months=12,options={},seconds=.1)
    return result


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'trials.sqlite'

    def store(self,**limits):
        store=checkpoints.Store(self.path,**limits);self.addCleanup(store.close)
        return store

    def test_roundtrip_order_distinct_trials_idempotence_and_detachment(self):
        store=self.store();experiment=store.open(binding());original=completed()
        experiment.save(2,original);experiment.save(1,original)
        self.assertEqual([number for number,result in experiment.read()],[1,2])
        self.assertEqual(experiment.load(1),original)
        changed=experiment.load(1);changed['periods'].clear()
        self.assertEqual(experiment.load(1),original)
        retry=deepcopy(original);retry['seconds']=999.
        self.assertTrue(experiment.save(1,retry)['retained'])
        self.assertEqual(experiment.load(1)['seconds'],.1)
        with self.assertRaisesRegex(ValueError,'Conflicting'):experiment.save(1,completed(.3))
        self.assertEqual(experiment.load(1),original)
        store.close()
        self.assertEqual(self.store().open(binding()).load(2),original)

    def test_each_calculation_binding_dimension_changes_identity_and_misses(self):
        store=self.store();experiment=store.open(binding());experiment.save(1,completed())
        for field in ('generation','policy','schema','implementation','execution'):
            value=deepcopy(binding());value[field]=('changed' if isinstance(value[field],str) else {'changed':True})
            other=store.open(value)
            self.assertNotEqual(other.identity,experiment.identity);self.assertIsNone(other.load(1))
        for field,value in (('seed',43),('months',3),('requested',1),('options',{'rank_to':1}),
                            ('start','2014-12-31'),('samples',[['2015-01-05'],['2015-01-02']])):
            changed=binding();changed['configuration'][field]=value
            if field=='requested':changed['configuration']['samples']=changed['configuration']['samples'][:1]
            self.assertIsNone(store.open(changed).load(1))
        for value in (float('nan'),float('inf'),object(),(1,2)):
            changed=binding();changed['execution']['invalid']=value
            with self.assertRaises(ValueError):store.open(changed)
        for number in (0,3,True,1.):
            with self.assertRaises(ValueError):experiment.load(number)

    def test_binding_digest_payload_identity_and_result_corruption_fail_closed(self):
        store=self.store();experiment=store.open(binding());experiment.save(1,completed())
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE experiments SET binding=?',('{}',))
        with self.assertRaisesRegex(ValueError,'binding'):store.open(binding())
        with self.assertRaisesRegex(ValueError,'binding'):experiment.load(1)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE experiments SET binding=?',(checkpoints.binding_json(binding()),))
            db.execute('UPDATE trials SET payload=?',('{}',))
        with self.assertRaisesRegex(ValueError,'Corrupt'):experiment.load(1)
        for mutate in (lambda r:r.pop('periods'),lambda r:r.update(cagr=0.),lambda r:r.update(cash_days=True),
                       lambda r:r.update(spy_growth=True),lambda r:r.update(spy_cagr=True),
                       lambda r:r['periods'][0].update(names=1),lambda r:r.update(options={'rank_to':1}),
                       lambda r:r['periods'][0].update(entry='2015-01-05'),
                       lambda r:r.update(seconds=float('nan'))):
            result=completed();mutate(result)
            with self.assertRaises(ValueError):experiment.save(2,result)
        # A matching content hash cannot make malformed financial evidence valid.
        result=completed();result['periods'][0]['names']=100
        payload=checkpoints.canonical(result)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE trials SET payload=?,sha256=?,bytes=?',(payload,checkpoints.digest(payload),len(payload.encode())))
        with self.assertRaises(ValueError):experiment.load(1)

    def test_foreign_databases_and_versions_are_not_checkpoint_stores(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE user_records(name TEXT)')
            db.execute("INSERT INTO user_records VALUES('preserve')")
        with self.assertRaisesRegex(ValueError,'different database'):self.store()
        with closing(sqlite3.connect(self.path)) as db,db:
            self.assertEqual(db.execute('SELECT * FROM user_records').fetchall(),[('preserve',)])
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),[('user_records',)])

    def test_active_coordinator_blocks_other_experiment_writes_without_a_pin(self):
        store=self.store();one=store.open(binding());two=store.open(binding(generation='other'))
        with store.coordinating(one):
            one.save(1,completed())
            with self.assertRaisesRegex(ValueError,'Another experiment'):two.save(1,completed())
            with self.assertRaisesRegex(ValueError,'active coordinator'):
                with store.coordinating(one):pass
            self.assertIsNotNone(one.load(1));self.assertIsNone(two.load(1))
        self.assertTrue(two.save(1,completed())['retained'])

    def test_precommit_cancel_and_independent_connection_atomic_visibility(self):
        store=self.store();experiment=store.open(binding());calls=0
        reader=sqlite3.connect(self.path);self.addCleanup(reader.close)
        def inspect():
            nonlocal calls
            calls+=1
            self.assertEqual(reader.execute('SELECT COUNT(*) FROM trials').fetchone()[0],0)
            if calls==2:
                self.assertGreater(Path(str(self.path)+'-journal').stat().st_size,0)
                raise KeyboardInterrupt()
        with patch.object(checkpoints.backtest_control,'checkpoint',side_effect=inspect):
            with self.assertRaises(KeyboardInterrupt):experiment.save(1,completed())
        self.assertIsNone(experiment.load(1));self.assertFalse(store.db.in_transaction)
        experiment.save(1,completed())
        self.assertEqual(reader.execute('SELECT COUNT(*) FROM trials').fetchone()[0],1)
        with patch.object(checkpoints.backtest_control,'checkpoint',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):experiment.save(2,completed())
        self.assertIsNone(experiment.load(2))

    def test_process_exit_before_during_and_after_commit(self):
        # A new owned child per stage; parent waits for termination before reopen.
        code='''import sys,os,json
from pathlib import Path
root=Path(sys.argv[1]);sys.path[:0]=[str(root/'scripts'),str(root/'website')]
import runtime_access
with runtime_access.ownership(root):
 import trial_checkpoints as t
 path=Path(sys.argv[2]);stage=sys.argv[3]
 store=t.Store(path);exp=store.open(json.loads(sys.argv[4]));result=json.loads(sys.argv[5])
 calls=0
 def stop():
  global calls
  calls+=1
  if (stage=='before' and calls==1) or (stage=='during' and calls==2):
   Path(str(path)+'.status').write_text(json.dumps(store.measurements()))
   os._exit(73)
 t.backtest_control.checkpoint=stop
 exp.save(1,result)
 Path(str(path)+'.status').write_text(json.dumps(store.measurements()))
 os._exit(73)
'''
        measurements=[]
        for stage in ('before','during','after'):
            path=Path(self.folder.name)/(stage+'.sqlite')
            process=subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT),str(path),stage,
                                    json.dumps(binding()),json.dumps(completed())],capture_output=True,timeout=30)
            self.assertEqual(process.returncode,73,process.stderr.decode(errors='replace'))
            measured=json.loads(Path(str(path)+'.status').read_text());measurements.append(dict(stage=stage,**measured))
            with checkpoints.Store(path) as store:
                self.assertEqual(store.open(binding()).load(1),completed() if stage=='after' else None)
            if stage=='during':self.assertGreater(measured['journal_bytes'],0)
        print(json.dumps(dict(check='checkpoint-interruption-storage',measurements=measurements)),flush=True)

    def test_retention_oversize_whole_experiments_and_atomic_eviction(self):
        size=len(checkpoints.canonical(completed()).encode())
        store=self.store(max_payload_bytes=size*2,max_experiments=2)
        one=store.open(binding());one.save(1,completed());one.save(2,completed())
        two=store.open(binding(generation='generation-2'));two.save(1,completed())
        self.assertIsNone(one.load(1));self.assertIsNone(one.load(2))
        self.assertEqual(store.measurements()['experiments'],1)
        self.assertEqual(two.load(1),completed())
        # The same experiment may fill its whole budget, then complete a larger
        # result without retaining it; it never erases its earlier trials.
        bigger=completed();bigger['extra']='x'*size
        outcome=two.save(2,bigger);self.assertFalse(outcome['retained'])
        self.assertIsNone(two.load(2));self.assertEqual(two.load(1),completed())
        store.max_experiments=1
        calls=0
        def cancel():
            nonlocal calls
            calls+=1
            if calls==2:raise KeyboardInterrupt()
        three=store.open(binding(generation='generation-3'))
        with patch.object(checkpoints.backtest_control,'checkpoint',side_effect=cancel):
            with self.assertRaises(KeyboardInterrupt):three.save(1,completed())
        self.assertIsNone(three.load(1));self.assertEqual(two.load(1),completed())
        self.assertTrue(three.save(1,completed())['retained']);self.assertIsNone(two.load(1))
        measured=store.measurements()
        self.assertLessEqual(measured['payload_bytes'],size*2)
        self.assertLessEqual(measured['experiments'],1)
        self.assertGreater(measured['file_bytes'],measured['payload_bytes'])
        print(json.dumps(dict(check='checkpoint-retention-storage',**measured)),flush=True)


if __name__=='__main__':unittest.main()
