"""Scoped comparison evidence/reset/ownership checks on fictional files only."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sys
import tempfile
import shutil
import sqlite3
from threading import Event, Thread
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/name) for name in ('tools','scripts','website')]
import parallel_comparison as pc


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='cb19f-synthetic-')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.case=dict(label='first',backend='numba',workers=1,threads=1,state='fresh_application',
                       checkpoint='first',repeat_of=None,purpose='Fictional orchestration verification')
        self.declaration=dict(version=1,base_commit='fictional',source_root=str(self.root/'source'),
            source_sha256={'scripts/test.py':'f'*64},capture=str(self.root/'capture'),
            capture_manifest_sha256=pc.CAPTURE,destination=str(self.root/'private'),
            copy_max_bytes=1024,storage_max_bytes=4096,request=dict(trials=2),
            cleanup_owner='test TemporaryDirectory',scope='Fictional files only')

    def observation(self,label='one',seconds=1.):
        path=self.root/(label+'.result.json')
        pc.write(path,dict(trial_results=[dict(periods=[dict(entry='2015-01-02',holdings=[
            dict(symbol='A',rank=1,return_value=.25,exit_basis='last price',missing=None)])],seconds=seconds)],
            execution=dict(recovered=seconds),seconds=seconds))
        return dict(status='complete',binding=dict(source='same',plan='same'),case=dict(self.case,label=label),
                    elapsed_seconds=seconds,result_path=str(path),result_sha256=pc.file_hash(path))

    def test_complete_financial_comparison_keeps_stock_identity_and_exact_categories(self):
        first=self.observation();second=self.observation('two',2.)
        compared=pc.compare([first,second])
        self.assertTrue(all(row['exact'] for row in compared['agreement']))
        self.assertEqual(compared['timings']['numba:1x1:fresh_application']['raw_seconds'],[1.,2.])
        changed=pc.read(second['result_path']);changed['trial_results'][0]['periods'][0]['holdings'][0]['rank']=2
        pc.write(second['result_path'],changed);second['result_sha256']=pc.file_hash(second['result_path'])
        with self.assertRaisesRegex(ValueError,'financial disagreement'):pc.compare([first,second])

    def test_missingness_numeric_tolerance_and_evidence_hash_remain_authoritative(self):
        first=self.observation();second=self.observation('two')
        path=Path(second['result_path']);value=pc.read(path)
        value['trial_results'][0]['periods'][0]['holdings'][0]['return_value']+=1e-13
        pc.write(path,value)
        with self.assertRaisesRegex(ValueError,'evidence changed'):pc.compare([first,second])
        second['result_sha256']=pc.file_hash(path);self.assertTrue(pc.compare([first,second])['agreement'][1]['exact'])
        value['trial_results'][0]['periods'][0]['holdings'][0]['missing']=0.
        pc.write(path,value);second['result_sha256']=pc.file_hash(path)
        with self.assertRaisesRegex(ValueError,'financial disagreement'):pc.compare([first,second])

    def test_failure_or_different_binding_cannot_become_latency_evidence(self):
        first=self.observation();second=self.observation('two')
        second['status']='failed'
        with self.assertRaisesRegex(ValueError,'completed observations'):pc.compare([first,second])
        second['status']='complete';second['binding']['plan']='different'
        with self.assertRaisesRegex(ValueError,'binding differs'):pc.compare([first,second])

    def test_decision_needs_repeated_complete_selected_layout_and_handoff(self):
        compared=pc.compare([self.observation(),self.observation('two',2.)])
        result=pc.decide(compared,backend='numba',workers=1,threads=1,rationale='Comparable measured work',
            limitations=['Fictional inputs'],g_handoff=['Verify native workflow'])
        self.assertTrue(result['original_remains_default'])
        with self.assertRaisesRegex(ValueError,'comparable repetitions'):
            pc.decide(compared,backend='rust',workers=1,threads=1,rationale='Unsupported choice',limitations=[],g_handoff=['G'])

    def test_capture_path_and_storage_declaration_reject_overlap(self):
        self.assertEqual(pc.validate_declaration(self.declaration),self.declaration)
        for key,value in (('destination',str(self.root/'source/child')),('capture_manifest_sha256','0'*64),
                          ('storage_max_bytes',1)):
            with self.subTest(key=key),self.assertRaises(ValueError):
                pc.validate_declaration(dict(self.declaration,**{key:value}))

    def test_case_identity_state_and_owned_tokens_are_validated_before_launch(self):
        self.assertEqual(pc.validate_case(self.case),self.case)
        for changes in (dict(label='../outside'),dict(state='full_recovery'),dict(backend='unknown'),
                        dict(backend='original',state='initialized_fresh'),dict(workers=True)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):pc.validate_case(dict(self.case,**changes))

    def test_source_binding_is_complete_and_rejects_added_or_changed_source(self):
        source=self.root/'source';(source/'scripts').mkdir(parents=True)
        (source/'scripts/a.py').write_text('value=1\n');expected=pc.sources(source)
        pc.assert_sources(source,expected)
        (source/'scripts/b.py').write_text('value=2\n')
        with self.assertRaisesRegex(ValueError,'contents changed'):pc.assert_sources(source,expected)

    def test_existing_destination_cannot_be_reset_by_preparation(self):
        destination=Path(self.declaration['destination']);destination.mkdir()
        protected=destination/'raw.json';protected.write_text('preserve')
        with patch.object(pc,'assert_sources'),self.assertRaisesRegex(ValueError,'fresh task-owned'):
            pc.prepare(self.declaration)
        self.assertEqual(protected.read_text(),'preserve')

    def test_interruption_requests_cooperative_close_retains_failure_and_waits(self):
        evidence=self.root/'comparison';evidence.mkdir()
        class Process:
            calls=0
            def wait(inner):
                inner.calls+=1
                if inner.calls==1:raise KeyboardInterrupt()
                self.assertTrue((evidence/'interrupt.cancel').exists())
                return 1
        process=Process()
        with patch.object(pc.subprocess,'Popen',return_value=process),self.assertRaises(KeyboardInterrupt):
            pc.launch(self.root,'case',{},'interrupt')
        self.assertEqual(process.calls,2)
        self.assertTrue((evidence/'interrupt.request.json').is_file())
        with self.assertRaisesRegex(ValueError,'already used'):pc.launch(self.root,'case',{},'interrupt')

    def test_failed_child_receipt_is_retained_without_success_timing(self):
        evidence=self.root/'comparison';evidence.mkdir()
        class Process:
            def wait(inner):
                pc.write(evidence/'failure.json',dict(status='failed',error_type='FictionalFailure',closure=True))
                return 1
        with patch.object(pc.subprocess,'Popen',return_value=Process()),self.assertRaisesRegex(RuntimeError,'retained'):
            pc.launch(self.root,'case',{},'failure')
        result=pc.read(evidence/'failure.json')
        self.assertEqual(result['status'],'failed');self.assertTrue(result['closure'])
        self.assertNotIn('elapsed_seconds',result)

    def test_failed_materialization_retains_declared_attempt_before_copy(self):
        attempt=Path(self.declaration['destination']).with_name('private.comparison-attempt.json')
        def failed(*args,**kwargs):
            saved=pc.read(attempt)
            self.assertEqual(saved['declaration'],self.declaration)
            self.assertIn('resources',saved)
            return dict(status='failed',error_type='FictionalCopyFailure')
        with patch.object(pc,'assert_sources'),patch.object(pc,'observe',return_value=dict(disk=dict(free_bytes=8192))), \
             patch('offline_input_copy.materialize_inputs',side_effect=failed),self.assertRaisesRegex(ValueError,'materialization failed'):
            pc.prepare(self.declaration)
        saved=pc.read(attempt)
        self.assertEqual(saved['copier_outcome']['error_type'],'FictionalCopyFailure')
        self.assertGreaterEqual(saved['materialization_seconds'],0.)

    def test_child_cleanup_failure_stops_sampler_and_keeps_unconfirmed_closure(self):
        stopped=Event();watcher=Thread(target=lambda:stopped.wait());watcher.start();record={}
        class Runtime:
            last_stats={'completed':1};clocks=[{'stage':'calculated'}];diagnostics=[]
            def close(inner):raise OSError('Fictional uncertain cleanup')
            def closure(inner):return dict(state='closing',confirmed=False)
        runtime=Runtime()
        with self.assertRaises(OSError):pc.close_observation(None,runtime,[runtime],stopped,watcher,record)
        self.assertTrue(record['sampler_stopped']);self.assertEqual(record['cleanup_error_types'],['OSError'])
        self.assertFalse(record['runtime_observations'][0]['closure']['confirmed'])
        self.assertEqual(record['runtime_observations'][0]['stats']['completed'],1)

    def test_sample_retention_is_bounded_while_peaks_include_dropped_rows(self):
        sample=pc.Samples(maximum=2,max_bytes=4096)
        for index in range(10):sample.add(dict(processes={'1':dict(threads=10-index,private_bytes=index)},provisional_artifact_bytes=index))
        saved=sample.evidence()
        self.assertEqual(len(saved['samples']),2);self.assertEqual(saved['total_samples'],10)
        self.assertEqual(saved['dropped_samples'],8);self.assertEqual(saved['sampled_peaks']['threads'],10)
        self.assertLessEqual(saved['retained_bytes'],4096)

    def test_disk_samples_separate_artifacts_scratch_and_current_checkpoint(self):
        scratch=self.root/'runtime';pool=scratch/'trial-pool';pool.mkdir(parents=True)
        (pool/'slot-0.evidence').write_bytes(b'111')
        (pool/'slot-0.json').write_bytes(b'22')
        (scratch/'payload.json').write_bytes(b'4444')
        checkpoint=self.root/'current.sqlite';checkpoint.write_bytes(b'55')
        checkpoint.with_name('current.sqlite-wal').write_bytes(b'666')
        (self.root/'unrelated.sqlite').write_bytes(b'7777777')
        self.assertEqual(pc.sampled_storage([scratch],checkpoint),dict(runtime_scratch_bytes=9,
            provisional_artifact_bytes=3,current_checkpoint_bytes=5))


class FixedChildTests(unittest.TestCase):
    def test_ordinary_private_preparation_application_closure_and_exact_recovery(self):
        # This runs the actual fixed child, ordinary preparation, both existing
        # adapters and real contained workers. The complete raw universe is
        # fictional; no historical benchmark/service admission is invoked.
        sys.path.insert(0,str(ROOT/'tests'))
        from bench_source_service_fixture import FictionalWorkspace
        with FictionalWorkspace() as workspace:
            private=workspace.source
            for name in pc.sources(ROOT):
                target=private/name;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(ROOT/name,target)
            declaration=dict(version=1,base_commit='synthetic-current-source',source_root=str(ROOT),
                source_sha256=pc.sources(private),capture=str(workspace.root/'unused-capture'),
                capture_manifest_sha256=pc.CAPTURE,destination=str(private),copy_max_bytes=64*1024**2,
                storage_max_bytes=512*1024**2,request=dict(start='2015-01-02',end='2017-01-03',months=12,
                    trials=2,seed=42,pool='cached',rank_to=5),cleanup_owner='FictionalWorkspace',scope='Fictional inputs only')
            pc.write(private/'comparison/declaration.json',declaration)
            prepared=pc.launch(private,'prepare',{},'preparation')
            pc.write(private/'comparison/workspace.json',dict(version=1,declaration_sha256=pc.digest(declaration),
                preparation=prepared))
            case=dict(label='new',backend='numba',workers=1,threads=1,state='fresh_application',
                checkpoint='fresh',repeat_of=None,purpose='Fictional application lifetime')
            fresh=pc.run_case(private,case)
            recovered=pc.run_case(private,dict(case,label='recovered',state='full_recovery',repeat_of='new'))
            original=pc.run_case(private,dict(case,label='original',backend='original',checkpoint='original'))
            reused=pc.run_case(private,dict(case,label='reuse',backend='original',state='original_reuse',
                checkpoint='original',repeat_of='original'))
            compared=pc.compare([original,fresh,recovered,reused])
            self.assertTrue(all(row['exact'] for row in compared['agreement']))
            self.assertIsNone(recovered['runtime_observations'][0]['stats']['trial_pool'])
            self.assertEqual(original['books_before'],0)
            self.assertEqual(original['books_after'],reused['books_after'])
            for row in (fresh,recovered):
                closure=row['runtime_observations'][0]['closure']
                self.assertEqual(closure['state'],'closed')
                self.assertTrue(closure['process']['descendants_empty'])
                self.assertTrue(closure['process']['native_handles_released'])
            with self.assertRaisesRegex(ValueError,'already used'):pc.run_case(private,case)
            # Simulate the exact persistent state left by an interrupted fresh
            # reset. A historic successful predecessor cannot qualify reuse.
            with closing(sqlite3.connect(private/'data/schedules.sqlite')) as db,db:
                db.execute('DELETE FROM period_pools');db.execute('DELETE FROM periods')
            with self.assertRaisesRegex(RuntimeError,'retained'):
                pc.run_case(private,dict(case,label='after-reset',backend='original',state='original_reuse',
                    checkpoint='original',repeat_of='original'))
            failed=pc.read(private/'comparison/after-reset.json')
            self.assertEqual(failed['status'],'failed');self.assertNotIn('elapsed_seconds',failed)
            print(json.dumps(dict(check='cb19f-fixed-child',agreement=compared['agreement'],
                current_source=pc.digest(declaration['source_sha256']),closed=True)),flush=True)


if __name__=='__main__':unittest.main()
