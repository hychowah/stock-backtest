"""Explicit bounded runtime/Candidate/Jobs only. No application route changes."""
from copy import deepcopy
from contextlib import ExitStack
import io
import json
from pathlib import Path
import sys
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'website'),str(ROOT/'tests')]
import backtest_control
import backtest_jobs
import numerical_runtime
import numerical_transfer
import result_evidence
import robustness
from numerical_portfolio import compare_results
import test_numerical_runtime as runtime_fixtures
import test_candidate_calculations as candidate_fixtures
from test_result_evidence import collect

LIMIT=4*1024**2


class BoundedRuntimeTests(unittest.TestCase):
    setUp=runtime_fixtures.RuntimeTests.setUp
    make=runtime_fixtures.RuntimeTests.make
    options=runtime_fixtures.RuntimeTests.options
    assert_closed=runtime_fixtures.RuntimeTests.assert_closed
    candidate=candidate_fixtures.CandidateTests.candidate

    def into(self,value,mode='custom',options=None,**kwargs):
        stream=io.BytesIO()
        completion=value.calculate_into(mode,options or self.options(),stream,max_bytes=LIMIT,**kwargs)
        reader=result_evidence.Reader(stream,max_bytes=LIMIT)
        self.assertEqual(reader.manifest,completion['manifest'])
        return collect(reader),completion,reader

    def test_complete_fixed_random_fresh_and_recovery_eager_agreement_and_limits(self):
        value=self.make(session_options=dict(result_workspace_bytes=48*1024))
        actual,_,_=self.into(value)
        expected=self.fixture.s.backtest(self.fixture.db,**self.options())
        self.assertTrue(compare_results(expected,actual[0])['exact'])
        options=self.options(trials=3,seed=42);plan=robustness.plan(self.fixture.db,**options)
        configurations=[];events=[]
        actual,completion,_=self.into(value,'random',options,planned=plan,configuration=configurations.append,progress=events.append)
        self.assertEqual(configurations,[plan]);self.assertEqual(completion['manifest']['trials'],3)
        self.assertEqual(completion['manifest']['summary']['execution']['calculated_trials'],3)
        for dates,trial in zip(plan['samples'],actual,strict=True):
            reference=self.fixture.s.backtest_dates(self.fixture.db,dates=dates,**{k:v for k,v in options.items() if k not in ('trials','seed')})
            self.assertTrue(compare_results(reference,trial)['exact'])
        books=value.last_stats['provider']['books']
        recovered,replay,_=self.into(value,'random',options,planned=plan)
        self.assertEqual(recovered,actual)
        self.assertEqual(replay['manifest']['summary']['execution']['recovered_trials'],3)
        self.assertEqual(value.last_stats['provider']['books'],books)
        self.assertFalse(any((value.scratch/n).exists() for n in numerical_transfer.OWNED_FILES))
        value.close();self.assert_closed(value)
        eager=self.make(session_options=dict(result_workspace_bytes=48*1024))
        with self.assertRaisesRegex(ValueError,'workspace bound'):eager.calculate('random',options,planned=plan)
        self.assert_closed(eager)
        with self.assertRaisesRegex(ValueError,'IPC payload'):numerical_runtime.encoded({'x':'x'*1024**2},1024**2)
        with self.assertRaises(TypeError):value.calculate_into('custom',self.options(),io.BytesIO(),max_bytes=LIMIT,capture=lambda *a:None)

    def test_callback_failure_before_after_checkpoint_commit_and_declined_retention(self):
        options=self.options(trials=2,seed=13)
        for completed in (0,1):
            value=self.make();original=LookupError('original bounded observer')
            def broken(event):
                if event['completed']==completed:raise original
            with self.assertRaises(LookupError) as caught:
                self.into(value,'random',options,progress=broken)
            self.assertIs(caught.exception,original);self.assert_closed(value)
            with self.make() as recovered:
                rows,envelope,_=self.into(recovered,'random',options)
                self.assertEqual(len(rows),2)
                self.assertEqual(envelope['manifest']['summary']['execution']['recovered_trials'],completed)
            # Isolate the next case from the completed recovery.
            (self.root/'trials.sqlite').unlink()
        value=self.make(session_options=dict(checkpoint_payload_bytes=1))
        rows,envelope,_=self.into(value,'random',options)
        self.assertEqual(len(rows),2)
        self.assertEqual(envelope['manifest']['summary']['execution']['unretained_trials'],2)
        self.assertEqual(value.last_stats['checkpoints']['trials'],0)

    def test_transfer_receiver_failure_corrupt_event_bad_ack_and_cancellation(self):
        class Broken(io.BytesIO):
            def write(self,data):raise LookupError('original bounded receiver')
        value=self.make()
        with self.assertRaisesRegex(LookupError,'original bounded receiver'):
            value.calculate_into('custom',self.options(),Broken(),max_bytes=LIMIT)
        self.assert_closed(value)
        stopped=Event();original=RuntimeError('original receiver during Stop')
        class StoppingReceiver(io.BytesIO):
            def write(self,data):stopped.set();raise original
        value=self.make()
        with self.assertRaises(RuntimeError) as caught:
            value.calculate_into('custom',self.options(),StoppingReceiver(),max_bytes=LIMIT,cancelled=stopped.is_set)
        self.assertIs(caught.exception,original);self.assert_closed(value)
        for fault in ('sequence','corrupt','ack'):
            value=self.make();event=value._event;send=value._send
            def changed():
                message=event()
                if message.get('event')=='transfer_piece':
                    if fault=='sequence':message['sequence']+=1
                    if fault=='corrupt':(value.scratch/'transfer.bin').write_bytes(b'corrupt')
                return message
            def wrong_ack(message):
                if fault=='ack' and message.get('command')=='transfer_ack':message=dict(message,sequence=999)
                send(message)
            with patch.object(value,'_event',side_effect=changed),patch.object(value,'_send',side_effect=wrong_ack):
                with self.assertRaises(ValueError):self.into(value)
            self.assert_closed(value)
        value=self.make();stopped=Event();send=value._send
        def stop_at_piece(message):
            if message.get('command')=='transfer_ack' and message['sequence']==0:stopped.set();return
            send(message)
        with patch.object(value,'_send',side_effect=stop_at_piece):
            with self.assertRaises(backtest_control.Cancelled):self.into(value,cancelled=stopped.is_set)
        self.assert_closed(value)
        self.assertFalse(any((value.scratch/n).exists() for n in numerical_transfer.OWNED_FILES))

    def test_backpressure_stalled_receiver_close_retains_owner_until_callback_drains(self):
        value=self.make(close_seconds=.2);entered=Event();release=Event();errors=[]
        class Blocking(io.BytesIO):
            def write(self,data):entered.set();release.wait(5);return super().write(data)
        stream=Blocking()
        def work():
            try:value.calculate_into('custom',self.options(),stream,max_bytes=LIMIT)
            except BaseException as error:errors.append(error)
        thread=Thread(target=work);thread.start();self.assertTrue(entered.wait(30))
        slot=(value.scratch/'transfer.bin').read_bytes();time.sleep(.05)
        self.assertEqual((value.scratch/'transfer.bin').read_bytes(),slot)
        with self.assertRaises(numerical_runtime.ClosureError):value.close()
        self.assertNotEqual(value.state,'closed')
        release.set();thread.join(10);self.assertFalse(thread.is_alive());self.assertTrue(errors)
        value.close();self.assert_closed(value)

    def test_current_input_generation_and_recorded_settings_reject_before_reuse(self):
        options=self.options(trials=1,seed=7);plan=robustness.plan(self.fixture.db,**options)
        value=self.make();self.into(value,'random',options,planned=plan)
        before=value.last_stats['provider']['books']
        with self.assertRaisesRegex(ValueError,'settings differ'):
            self.into(value,'random',dict(options,rank_to=2),planned=plan)
        self.assert_closed(value)
        value=self.make();self.into(value,'random',options,planned=plan)
        changed=deepcopy(self.fixture.binding);changed['prices']={'revision':1}
        (self.root/'binding.json').write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError,'stale'):self.into(value,'random',options,planned=plan)
        self.assert_closed(value)

    def test_jobs_idempotence_four_run_retention_expiry_pins_and_parent_handoff(self):
        owner=self.candidate();jobs=backtest_jobs.Jobs(owner,evidence_root=self.root/'job-evidence',evidence_bytes=96*1024**2)
        self.addCleanup(jobs.close)
        options=self.options(trials=2,seed=11);plan=robustness.plan(self.fixture.db,**options)
        jobs.start_evidence('a'*32,'random',options,planned=plan,max_bytes=LIMIT)
        jobs.runs['a'*32]['thread'].join(30)
        self.assertEqual(jobs.snapshot('a'*32)['state'],'complete',jobs.snapshot('a'*32))
        self.assertIsNone(jobs.snapshot('a'*32)['result']);self.assertTrue(jobs.snapshot('a'*32)['evidence'])
        self.assertEqual(jobs.start_evidence('a'*32,'random',options,planned=plan,max_bytes=LIMIT)['state'],'complete')
        with self.assertRaisesRegex(ValueError,'different settings'):jobs.start('a'*32,'random',options,planned=plan)
        with jobs.open_evidence('a'*32) as reader:
            runtime=owner.created[-1]
            with owner.parent_operation():
                self.assert_closed(runtime)
                with self.fixture.owner.hold(timeout=0):pass
            self.assertEqual(len(list(reader.trials())),2)
            jobs.runs['a'*32]['finished']=time.time()-86401
            with self.assertRaises(backtest_jobs.Missing):jobs.snapshot('a'*32)
            self.assertEqual(jobs.evidence.measurements()['active_readers'],1)
            self.assertTrue(list(reader.trials()))
        self.assertEqual(jobs.evidence.measurements()['reserved_bytes'],0)
        for n in range(1,6):
            identifier=format(n,'032x');jobs.start_evidence(identifier,'custom',self.options(),max_bytes=LIMIT)
            jobs.runs[identifier]['thread'].join(30)
            self.assertEqual(jobs.snapshot(identifier)['state'],'complete')
        self.assertEqual(len(jobs.runs),4)
        self.assertEqual(len(jobs.evidence.entries),4)
        jobs.evidence.max_bytes=jobs.evidence.measurements()['reserved_bytes']+1
        with self.assertRaisesRegex(ValueError,'exhausted'):jobs.start_evidence('b'*32,'custom',self.options(),max_bytes=LIMIT)
        self.assertEqual(len(jobs.runs),4)

    def test_jobs_stop_during_transfer_preserves_committed_recovery_and_reader_status_lock(self):
        owner=self.candidate();jobs=backtest_jobs.Jobs(owner,evidence_root=self.root/'transfer-stop',evidence_bytes=96*1024**2)
        self.addCleanup(jobs.close)
        # Attach a controlled child so the first transfer can be interrupted.
        runtime=owner.preparation._runtime();owner.runtime=runtime;runtime.start()
        send=runtime._send
        def stopped(message):
            if message.get('command')=='transfer_ack' and message['sequence']==0:
                jobs.cancel('e'*32)
            send(message)
        options=self.options(trials=2,seed=21)
        with patch.object(runtime,'_send',side_effect=stopped):
            jobs.start_evidence('e'*32,'random',options,max_bytes=LIMIT)
            jobs.runs['e'*32]['thread'].join(30)
        self.assertEqual(jobs.snapshot('e'*32)['state'],'cancelled')
        self.assert_closed(runtime);self.assertIsNone(owner.runtime)
        self.assertEqual(jobs.evidence.measurements()['reserved_bytes'],0)
        jobs.start_evidence('f'*32,'random',options,max_bytes=LIMIT)
        jobs.runs['f'*32]['thread'].join(30)
        self.assertEqual(jobs.snapshot('f'*32)['evidence']['manifest']['summary']['execution']['recovered_trials'],2)
        entered=Event();release=Event();original=jobs.evidence.read;errors=[]
        def blocked(*args):entered.set();release.wait(5);return original(*args)
        def reader():
            try:
                with jobs.open_evidence('f'*32) as evidence:self.assertEqual(evidence.manifest['trials'],2)
            except BaseException as error:errors.append(error)
        with patch.object(jobs.evidence,'read',side_effect=blocked):
            thread=Thread(target=reader);thread.start();self.assertTrue(entered.wait(2))
            self.assertEqual(jobs.snapshot('f'*32)['state'],'complete')
            release.set();thread.join(5);self.assertFalse(thread.is_alive());self.assertEqual(errors,[])

    def test_bounded_generation_change_and_source_change_close_before_reuse(self):
        options=self.options(trials=1,seed=17)
        value=self.make();self.into(value,'random',options)
        # Inject a pointer replacement only in this disposable fixture. Real
        # publication must retire the child before taking financial ownership.
        import cache_access
        with patch.object(self.fixture.store,'coordinator',cache_access.WorkspaceAccess(self.root/'fixture-publication.lock')):
            self.fixture.advance()
        (self.root/'binding.json').write_text(json.dumps(self.fixture.binding))
        with self.assertRaisesRegex(ValueError,'generation changed'):self.into(value,'random',options)
        self.assert_closed(value)
        # Preserve all actual source files. Change only an owned private export.
        import shutil
        private=self.root/'private-bounded-source';private.mkdir()
        for folder in ('scripts','website','tools','tests'):
            shutil.copytree(ROOT/folder,private/folder,ignore=shutil.ignore_patterns('__pycache__','local','dist','node_modules'))
        value=numerical_runtime.NumericalRuntime(source_root=private,scratch=self.root/'source-bounded-runtime',
            generation_path=self.fixture.store.path,checkpoint_path=self.root/'source-bounded.sqlite',threads=1,
            python=sys.executable,session_factory='numerical_runtime_fixture:Session',coordinator=self.fixture.owner)
        self.addCleanup(value.close);self.into(value,'random',options)
        path=private/'scripts'/'metrics.py';path.write_bytes(path.read_bytes()+b'\n# Fictional changed source.\n')
        with self.assertRaisesRegex(ValueError,'Loaded calculation source changed'):self.into(value,'random',options)
        self.assert_closed(value)

    def test_bounded_descendant_and_native_file_handles_close_before_release(self):
        value=self.make(session_options=dict(fault='descendant'),close_seconds=.5)
        self.into(value);generation=value.last_stats['generation'];value.close();self.assert_closed(value)
        marker=json.loads((value.scratch/'fixture-state.json').read_bytes())
        for field in ('portfolio_closed','provider_closed','mappings_closed','record_db_closed','sql_closed','checkpoint_db_closed'):
            self.assertTrue(marker[field],marker)
        path=self.fixture.store.path/generation/'raw_values.npy';renamed=path.with_suffix('.closed')
        path.rename(renamed);renamed.rename(path)

    def test_jobs_stop_and_shutdown_do_not_publish_partial_evidence(self):
        for shutdown in (False,True):
            owner=self.candidate(session_options=dict(fault='cancel'),close_seconds=.5)
            jobs=backtest_jobs.Jobs(owner,evidence_root=self.root/('stopped-'+str(shutdown)))
            jobs.start_evidence('d'*32,'custom',self.options(),max_bytes=LIMIT)
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                runtime=owner.runtime
                marker=runtime.scratch/'fixture-state.json' if runtime is not None else None
                if marker and marker.exists() and json.loads(marker.read_bytes()).get('running'):break
                time.sleep(.02)
            else:self.fail('Bounded job did not enter calculation')
            if shutdown:owner.close()
            else:jobs.cancel('d'*32)
            jobs.close();self.assertEqual(jobs.snapshot('d'*32)['state'],'cancelled')
            self.assert_closed(runtime);self.assertIsNone(owner.runtime)
            self.assertEqual(jobs.evidence.measurements()['reserved_bytes'],0)


if __name__=='__main__':unittest.main()
