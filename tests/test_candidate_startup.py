"""Closed candidate preparation and recovery, on disposable private inputs."""
import sys as _owner_sys
from pathlib import Path as _OwnerPath
_owner_sys.path.insert(0,str(_OwnerPath(__file__).resolve().parents[1]))
from backtest.inputs import daily, cache_assets
from contextlib import ExitStack
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).absolute().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT),str(ROOT/'tests')]
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.application import preparation as preparation
from backtest.runtime import cache_access as cache_access
from website.server import data_manager
from website.rendering import state as build_state
from website.server import app as serve
from website import serve_candidate
from backtest.application import queue as backtest_queue
from backtest.application import library as saved_backtests
from test_saved_backtests import snapshot
from test_queue import request


class PreparationContractTests(unittest.TestCase):
    def setUp(self):
        self.context=ExitStack();self.addCleanup(self.context.close)
        self.root=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.context.enter_context(patch.object(preparation.research,'ROOT',self.root))
        self.owner=cache_access.WorkspaceAccess(self.root/'data'/'financial.lock')
        self.context.enter_context(patch.object(cache_access,'workspace',self.owner))
        self.value=preparation.Preparation(self.root,python='explicit-venv-entry',ensure_presentation=build_state.ensure_presentation)
        self.context.enter_context(patch.object(preparation,'dependencies',return_value={'packages':preparation.PINS,'profile':'numba_compiled','rust_required':False}))
        self.context.enter_context(patch.object(cache_assets,'source_problem',return_value=False))
        self.context.enter_context(patch.object(preparation.baseline,'Baseline',return_value=Mock()))
        self.context.enter_context(patch.object(daily,'prepare'))
        self.context.enter_context(patch('website.rendering.state.current_build',return_value=True))
        self.context.enter_context(patch.object(self.value,'inventory',return_value='inventory'))
        self.store=Mock();self.store.prepare.return_value=dict(identity='generation',reused=True)
        self.context.enter_context(patch.object(self.value,'_store',return_value=self.store))
        self.runtime=Mock(last_stats=dict(generation='generation',provider=dict(backend='numba',candidate_assembly='compiled',
            nopython_signatures={key:['verified'] for key in ('reports','prices','factors','decisions','materialize')})))
        self.runtime.calculate.return_value={'verified':True,'profile':'numba_compiled'}
        self.runtime.closure.return_value=dict(state='closed',process=dict(closed=True))
        self.context.enter_context(patch.object(self.value,'_runtime',return_value=self.runtime))

    def test_order_and_financial_handoff_and_detached_closed_report(self):
        calls=[]
        preparation.baseline.Baseline.return_value.recover.side_effect=lambda:calls.append('recover')
        daily.prepare.side_effect=lambda:calls.append('base')
        self.store.prepare.side_effect=lambda check:calls.append('generation') or dict(identity='generation',reused=True)
        def start(**options):
            self.assertFalse(getattr(self.owner.state,'held',False));calls.append('runtime')
        self.runtime.start.side_effect=start
        self.runtime.close.side_effect=lambda:calls.append('close')
        def presentation():
            self.assertIsNone(self.value.runtime)
            self.assertTrue(getattr(self.owner.state,'held',False))
            calls.append('presentation')
        self.value.ensure_presentation=presentation
        report=self.value.prepare()
        self.assertEqual(calls,['recover','base','generation','runtime','close','presentation'])
        self.assertEqual(report['closure']['state'],'closed');self.assertIsNone(self.value.runtime)
        report['runtime']['generation']='edited';self.assertEqual(self.value.status()['runtime']['generation'],'generation')

    def test_publication_recovery_precedes_invalid_input_check(self):
        calls=[]
        preparation.baseline.Baseline.return_value.recover.side_effect=lambda:calls.append('recover')
        cache_assets.source_problem.side_effect=lambda:calls.append('inputs') or True
        with self.assertRaises(preparation.PreparationError):self.value.prepare()
        self.assertEqual(calls,['recover','inputs']);self.runtime.start.assert_not_called()

    def test_publication_failure_never_opens_readers_or_runtime(self):
        preparation.baseline.Baseline.return_value.recover.side_effect=ValueError('private unsafe detail')
        with self.assertRaises(preparation.PreparationError) as error:self.value.prepare()
        self.assertEqual(error.exception.category,'publication needs recovery')
        self.assertNotIn('private unsafe',str(error.exception))
        daily.prepare.assert_not_called();self.runtime.start.assert_not_called()

    def test_dependency_failure_never_imports_numerical_store_or_calls_network(self):
        preparation.dependencies.side_effect=preparation.PreparationError('dependencies unavailable')
        with self.assertRaises(preparation.PreparationError):self.value.prepare()
        self.value._store.assert_not_called();self.runtime.start.assert_not_called()

    def test_runtime_failure_closes_before_recovery(self):
        self.runtime.start.side_effect=RuntimeError('https://unsafe.test/provider?key=secret')
        with self.assertRaises(preparation.PreparationError) as error:self.value.prepare()
        self.runtime.close.assert_called_once();self.assertIsNone(self.value.runtime)
        self.assertNotIn('https:',str(error.exception));self.assertEqual(self.value.status()['state'],'failed')

    def test_uncertain_close_retains_strong_owner_and_cannot_publish_ready(self):
        from backtest.engines.numerical.runtime import ClosureError
        self.runtime.close.side_effect=ClosureError(self.runtime)
        with self.assertRaises(ClosureError):self.value.prepare()
        self.assertIs(self.value.runtime,self.runtime);self.assertNotEqual(self.value.status()['state'],'current')
        self.runtime.close.side_effect=None;self.value.close();self.assertIsNone(self.value.runtime)

    def test_build_failure_occurs_after_runtime_closure(self):
        with patch('website.rendering.state.current_build',return_value=False),patch('subprocess.run',side_effect=OSError('unsafe')):
            with self.assertRaises(preparation.PreparationError):self.value.prepare()
        self.runtime.close.assert_called_once();self.assertIsNone(self.value.runtime)

    def test_presentation_input_change_rejects_ready_publication(self):
        self.value.ensure_presentation=lambda:setattr(self.value.inventory,'return_value','changed')
        with self.assertRaises(preparation.PreparationError):self.value.prepare()
        self.runtime.close.assert_called_once()
        self.assertEqual(json.loads(self.value.path.read_text())['state'],'failed')

    def test_numerical_only_preparation_omits_presentation(self):
        self.value.ensure_presentation=None
        with patch('website.rendering.state.current_build',side_effect=AssertionError('No presentation dependency')):
            self.assertEqual(self.value.prepare()['state'],'current')

    def test_changed_inputs_between_child_and_build_reject(self):
        self.value.inventory.side_effect=['before','after']
        with self.assertRaises(preparation.PreparationError):self.value.prepare()
        self.assertIsNone(self.value.runtime)

    def test_unchanged_restart_reuses_generation_but_checks_fresh_runtime(self):
        self.value.prepare();self.value.prepare()
        self.assertEqual(self.store.prepare.call_count,2);self.assertEqual(self.runtime.start.call_count,2)
        self.assertEqual(self.runtime.close.call_count,2)

    def test_pending_journals_invalidate_success_report(self):
        self.value.prepare()
        for relative in ('research.sqlite.publication.json','numerical/publication.json','deployment.pending.json'):
            path=self.root/'data'/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
            self.assertEqual(self.value.status()['state'],'stale');path.unlink()

    def test_cancelled_start_does_not_publish_completion(self):
        self.runtime.start.side_effect=preparation.backtest_control.Cancelled()
        with self.assertRaises(preparation.backtest_control.Cancelled):self.value.prepare()
        self.runtime.close.assert_called_once();self.assertNotEqual(self.value.status()['state'],'current')

    def test_two_preparations_serialize_across_financial_handoff(self):
        began=Event();release=Event();entries=[];errors=[]
        def start(**options):
            entries.append('start');began.set();release.wait(3)
        self.runtime.start.side_effect=start
        def work():
            try:self.value.prepare()
            except BaseException as error:errors.append(error)
        first=Thread(target=work);second=Thread(target=work)
        first.start();self.assertTrue(began.wait(2));second.start();time.sleep(.1)
        self.assertEqual(entries,['start']);release.set();first.join(4);second.join(4)
        self.assertFalse(first.is_alive() or second.is_alive());self.assertEqual(errors,[])
        self.assertEqual(entries,['start','start'])


class DependencyAndIsolationTests(unittest.TestCase):
    def test_repeated_interrupts_preserve_uncertain_owner_until_close_is_proved(self):
        from backtest.engines.numerical.runtime import ClosureError
        capability=Mock();capability.close.side_effect=[ClosureError(capability),KeyboardInterrupt(),ClosureError(capability),None]
        pause=Mock(side_effect=[KeyboardInterrupt(),KeyboardInterrupt()])
        with patch('builtins.print'):
            serve_candidate.close_before_source_release(capability,pause=pause)
        self.assertEqual(capability.close.call_count,4);self.assertEqual(pause.call_count,2)

    def test_repeated_interrupt_during_application_join_retries_before_runtime_close(self):
        capability=Mock();server=Mock();jobs=Mock()
        jobs.close.side_effect=[KeyboardInterrupt(),None]
        with patch.object(serve,'DATA_JOBS',jobs):serve.close_candidate_owners(server,capability)
        self.assertEqual(jobs.close.call_count,2);server.server_close.assert_called_once();capability.close.assert_called_once()

    def test_capability_rejects_root_different_from_loaded_application(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError,'loaded application source'):
                preparation.Preparation(temporary)

    def test_metadata_probe_rejects_missing_wrong_packages_and_unsupported_python(self):
        for versions in ({},dict(preparation.PINS,numpy='wrong')):
            def version(name):
                if name not in versions:raise preparation.metadata.PackageNotFoundError(name)
                return versions[name]
            with patch.object(preparation.metadata,'version',side_effect=version):
                with self.assertRaises(preparation.PreparationError):preparation.dependencies()
        with patch.object(preparation.sys,'version_info',(3,11,0)):
            with self.assertRaises(preparation.PreparationError):preparation.dependencies()

    def test_private_entry_rejects_registered_installed_and_source_checkout_roots(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(serve_candidate,'ROOT',Path(temporary)):
            root=Path(temporary);(root/'data').mkdir()
            self.assertEqual(serve_candidate.private_root(root),root)
            for marker in ('data/workspace.json','data/deployment.json','data/deployment.pending.json','.git','.git-local'):
                path=root/marker;path.write_text('{}')
                with self.assertRaises(ValueError):serve_candidate.private_root(root)
                path.unlink()
            with self.assertRaises(ValueError):serve_candidate.private_root(root/'another')


class MutationAndHttpTests(unittest.TestCase):
    def test_late_http_rebuild_body_cannot_start_after_shutdown_joins_data_owner(self):
        from website import runtime_access
        with tempfile.TemporaryDirectory() as temporary,ExitStack() as context:
            root=Path(temporary);capability=Mock();jobs=data_manager.Jobs(preparation=capability)
            context.enter_context(patch.object(serve,'DATA_JOBS',jobs))
            context.enter_context(patch.object(data_manager,'inspect',return_value={'warnings':[]}))
            consumer=backtest_queue.Queue(backtest_queue.Store(root/'queue.sqlite'),library=backtest_queue.saved_backtests.Store((backtest_queue.Store(root/'queue.sqlite')).path.with_name('saved-library.sqlite')))
            context.enter_context(patch.object(serve.backtest_queue,'Queue',return_value=consumer))
            entered=Event();joining=Event();source_released=Event();handled=Event();errors=[];responses=[]
            original_request=serve.data.data_request
            def late_request(handler,*args):
                entered.set();return original_request(handler,*args)
            context.enter_context(patch.object(serve.data,'data_request',late_request))
            server=serve.Server(('127.0.0.1',0),serve.Handler)
            original_close=server.server_close
            def join_handlers():
                joining.set();original_close()
            context.enter_context(patch.object(server,'server_close',side_effect=join_handlers))
            listener=Thread(target=server.serve_forever);listener.start()
            client=socket.create_connection(server.server_address,timeout=5)
            client.settimeout(5)
            body=b'{}'
            headers=(f'POST /api/data/rebuild HTTP/1.1\r\nHost: 127.0.0.1:{server.server_address[1]}\r\n'
                     f'Content-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n').encode()
            def finish_body():
                try:
                    if not joining.wait(5):raise AssertionError('HTTP owner did not reach request join')
                    if source_released.is_set():raise AssertionError('Source released before accepted request completed')
                    if not jobs.closing or not jobs.cancel.is_set():raise AssertionError('Data admission was not closed before HTTP join')
                    with self.assertRaises(RuntimeError):
                        with runtime_access.ownership(root,exclusive=True,timeout=0):pass
                    client.sendall(body)
                    response=bytearray()
                    while True:
                        part=client.recv(8192)
                        if not part:break
                        response.extend(part)
                    responses.append(bytes(response));handled.set()
                except BaseException as error:errors.append(error)
                finally:client.close()
            sender=Thread(target=finish_body)
            try:
                with runtime_access.ownership(root):
                    client.sendall(headers);self.assertTrue(entered.wait(3))
                    server.shutdown();listener.join(3)
                    sender.start()
                    serve.close_candidate_owners(server,capability)
                    self.assertTrue(handled.wait(3));self.assertEqual(errors,[])
                    capability.prepare.assert_not_called()
                    self.assertIsNone(jobs.thread);self.assertTrue(jobs.cancel.is_set())
                source_released.set()
                sender.join(3)
                self.assertIn(b' 400 ',responses[0].split(b'\r\n',1)[0])
                with runtime_access.ownership(root,exclusive=True,timeout=0):pass
            finally:
                client.close()
                if listener.is_alive():server.shutdown();listener.join(3)
                server.server_close()
                if sender.ident is not None:sender.join(3)

    def test_queue_rechecks_freshness_under_financial_ownership_and_defers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);owner=cache_access.WorkspaceAccess(root/'financial.lock')
            store=backtest_queue.Store(root/'queue.sqlite');record=store.enqueue(request())
            consumer=backtest_queue.Queue(store,library=backtest_queue.saved_backtests.Store((store).path.with_name('saved-library.sqlite')))
            def ready():
                self.assertTrue(getattr(owner.state,'held',False));return False
            consumer.ready=ready
            with patch.object(cache_access,'workspace',owner),patch.object(daily,'connect') as calculate:
                consumer._run(store.claim())
            calculate.assert_not_called();self.assertEqual(store.get(record['id'])['state'],'queued')

    def test_background_admission_rechecks_freshness_inside_financial_snapshot(self):
        from backtest.application import jobs as backtest_jobs
        with tempfile.TemporaryDirectory() as temporary:
            owner=cache_access.WorkspaceAccess(Path(temporary)/'financial.lock');jobs=backtest_jobs.Jobs()
            def ready():
                self.assertTrue(getattr(owner.state,'held',False));return False
            jobs.ready=ready
            with patch.object(cache_access,'workspace',owner),patch.object(daily,'connect') as calculate:
                identifier='a'*32;jobs.start(identifier,'custom',{})
                jobs.runs[identifier]['thread'].join(3)
            calculate.assert_not_called();self.assertEqual(jobs.snapshot(identifier)['state'],'failed')

    def test_explicit_stop_wins_when_stale_queue_admission_defers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);owner=cache_access.WorkspaceAccess(root/'financial.lock')
            store=backtest_queue.Store(root/'queue.sqlite');record=store.enqueue(request())
            consumer=backtest_queue.Queue(store,library=backtest_queue.saved_backtests.Store((store).path.with_name('saved-library.sqlite')));claimed=store.claim()
            def ready():
                current=store.get(record['id'])
                store.change(record['id'],'stop',dict(revision=current['revision']))
                return False
            consumer.ready=ready
            with patch.object(cache_access,'workspace',owner),patch.object(daily,'connect') as calculate:
                consumer._run(claimed)
            calculate.assert_not_called();self.assertEqual(store.get(record['id'])['state'],'cancelled')

    def test_partial_download_and_repair_failure_or_cancel_invalidates_before_unlock(self):
        for kind in ('series','annual','full-financial','repair'):
            for error in (ValueError('partial'),data_manager.Cancelled()):
                with tempfile.TemporaryDirectory() as temporary:
                    owner=cache_access.WorkspaceAccess(Path(temporary)/'financial.lock')
                    capability=Mock();job=data_manager.Jobs(preparation=capability)
                    observed=[]
                    capability.invalidate.side_effect=lambda:observed.append(getattr(owner.state,'held',False))
                    def partial(*args):
                        (Path(temporary)/kind).write_text('one completed synthetic asset')
                        raise error
                    with patch.object(cache_access,'workspace',owner),patch.object(data_manager,'download',side_effect=partial):
                        job.work('download',dict(scope='cached',start='2020-01-01',end='2020-01-31',datasets=['prices'],symbols=[]))
                    self.assertEqual(observed,[True]);self.assertFalse(job.state['running']);self.assertFalse(job.rebuilt)

    def test_candidate_rebuild_dispatches_without_parent_financial_ownership(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner=cache_access.WorkspaceAccess(Path(temporary)/'financial.lock');capability=Mock()
            capability.prepare.side_effect=lambda **kw:self.assertFalse(getattr(owner.state,'held',False))
            job=data_manager.Jobs(preparation=capability)
            with patch.object(cache_access,'workspace',owner),patch.object(data_manager,'inspect',return_value={'warnings':[]}):
                job.work('rebuild',dict(scope='cached',start='2020-01-01',end='2020-01-31',datasets=['prices'],symbols=[]))
            self.assertTrue(job.rebuilt);capability.prepare.assert_called_once()

    def test_actual_recovery_http_reads_stored_results_and_holds_without_calculation(self):
        with tempfile.TemporaryDirectory() as temporary,ExitStack() as context:
            root=Path(temporary);library=saved_backtests.Store(root/'library.sqlite')
            record=library.save('Original',snapshot())
            store=backtest_queue.Store(root/'queue.sqlite');queued=store.enqueue(request('Held'))
            held=store.change(queued['id'],'hold',dict(revision=queued['revision']))
            completed=store.enqueue(request('Completed'));running=store.claim()
            complete_snapshot=snapshot('custom');complete_snapshot['version']=2
            complete_snapshot['presentation']={};complete_snapshot.pop('context')
            store.finish(running['id'],'complete',snapshot=complete_snapshot)
            consumer=backtest_queue.Queue(store,library=backtest_queue.saved_backtests.Store((store).path.with_name('saved-library.sqlite')));context.enter_context(patch.object(serve.backtest_queue,'Queue',return_value=consumer))
            context.enter_context(patch.object(serve,'SAVED_BACKTESTS',library))
            capability=Mock();capability.status.return_value=dict(state='failed')
            context.enter_context(patch.object(serve,'DATA_JOBS',data_manager.Jobs(preparation=capability)))
            server=serve.Server(('127.0.0.1',0),serve.Handler)
            # This case models the isolated candidate entry. Normal servers
            # now keep Original available when optional preparation fails.
            from backtest.application.candidate_calculations import Candidate
            server.calculations=Candidate(capability)
            server.candidate_preparation=capability;server.data_recovery=True
            server.backtest_queue.ready=lambda:False
            thread=Thread(target=server.serve_forever);thread.start()
            def http(method,path,body=None):
                connection=HTTPConnection('127.0.0.1',server.server_address[1],timeout=5)
                try:
                    connection.request(method,path,body=json.dumps(body) if body is not None else None,
                                       headers={'Content-Type':'application/json'})
                    response=connection.getresponse();return response.status,response.read()
                finally:connection.close()
            try:
                self.assertEqual(http('GET','/data.html')[0],200)
                status,body=http('GET','/api/backtests/'+record['id']);self.assertEqual(status,200)
                self.assertEqual(json.loads(body)['snapshot'],snapshot())
                self.assertEqual(json.loads(http('GET','/api/backtest-queue/'+held['id'])[1])['state'],'held')
                self.assertEqual(json.loads(http('GET','/api/backtest-queue/'+completed['id'])[1])['snapshot'],complete_snapshot)
                for path in ('/api/schedule','/api/robustness','/api/backtest-runs/new','/api/backtest-queue'):
                    self.assertEqual(http('POST',path,{})[0],503)
                self.assertIsNone(consumer.thread)
            finally:
                server.shutdown();server.server_close();thread.join(3)
            self.assertEqual(saved_backtests.Store(library.path).get(record['id'])['snapshot'],snapshot())
            self.assertEqual(backtest_queue.Store(store.path).get(held['id'])['state'],'held')


class ActualPreparationTests(unittest.TestCase):
    def test_cold_unchanged_changed_publication_recovery_and_moved_restart(self):
        from bench_source_service_fixture import FictionalWorkspace
        with FictionalWorkspace() as fixture:
            output=fixture.root/'candidate.json';log=fixture.root/'candidate.log'
            command=[sys.executable,'-I','-B',str(ROOT/'tests/candidate_preparation_fixture.py'),
                     str(fixture.source),str(ROOT/'tests'),str(output)]
            with log.open('wb') as stream:
                # This fixture repeats preparation, calculation and recovery
                # operations. Each runtime keeps its own bounded
                # startup/closure allowances; no batch calculation watchdog.
                process=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT)
            if process.returncode:self.fail(log.read_text(encoding='utf-8',errors='replace'))
            evidence=json.loads(output.read_bytes())
            moved=fixture.root/'relocated-source'
            shutil.move(fixture.source,moved);fixture.source=moved
            command[4]=str(moved);command.append(evidence['changed']['identity'])
            with log.open('ab') as stream:
                process=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,timeout=120)
            if process.returncode:self.fail(log.read_text(encoding='utf-8',errors='replace'))
            self.assertTrue(json.loads(output.read_bytes())['moved'])
            self.assertTrue(evidence['offline']);self.assertTrue(evidence['publication_recovered'])
            print(json.dumps(dict(check='actual-candidate-preparation',**evidence)),flush=True)

    def test_actual_entry_failures_success_and_ordinary_restart_preserve_stores(self):
        from bench_source_service_fixture import FictionalWorkspace
        from backtest.runtime.process_owner import OwnedProcess, ProcessLimits
        with FictionalWorkspace() as fixture:
            library=saved_backtests.Store(fixture.source/'data/saved-backtests.sqlite')
            record=library.save('Original',snapshot())
            store=backtest_queue.Store(fixture.source/'data/backtest-queue.sqlite')
            item=store.enqueue(request('Held'))
            held=store.change(item['id'],'hold',dict(revision=item['revision']))
            done=store.enqueue(request('Completed'));store.claim()
            complete_snapshot=snapshot('custom');complete_snapshot['version']=2
            complete_snapshot['presentation']={};complete_snapshot.pop('context')
            store.finish(done['id'],'complete',snapshot=complete_snapshot)
            saved_metrics=(fixture.source/'raw/metrics.jsonl').read_bytes()
            for scenario in ('dependencies','raw','publication','build','success','ordinary'):
                if scenario=='raw':(fixture.source/'raw/metrics.jsonl').unlink()
                if scenario=='publication':(fixture.source/'data/research.sqlite.publication.json').write_text('{}')
                owner=OwnedProcess([sys.executable,'-I','-B',str(ROOT/'tests/candidate_service_fixture.py'),
                    str(fixture.source),str(ROOT/'tests'),scenario],
                    env=dict(os.environ,OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',OMP_NUM_THREADS='2',NUMBA_NUM_THREADS='2'),
                    limits=ProcessLimits(2*1024**3,16,25,close_seconds=5.,user_cpu_seconds=180.))
                logs=[];port=None
                try:
                    until=time.monotonic()+120
                    while time.monotonic()<until:
                        event=owner.event(.05)
                        if event is None:break
                        logs.append(event)
                        text=event.get('text','')
                        if text.startswith('Open http://127.0.0.1:'):
                            port=int(text.split(':')[2].split()[0]);break
                    self.assertIsNotNone(port,logs)
                    def http(method,path,body=None):
                        connection=HTTPConnection('127.0.0.1',port,timeout=30)
                        try:
                            connection.request(method,path,body=json.dumps(body) if body is not None else None,
                                headers={'Content-Type':'application/json'})
                            response=connection.getresponse();return response.status,response.read()
                        finally:connection.close()
                    self.assertEqual(http('GET','/data.html')[0],200)
                    status,body=http('GET','/api/backtests/'+record['id'])
                    self.assertEqual(status,200,body)
                    self.assertEqual(json.loads(body)['snapshot'],snapshot())
                    self.assertEqual(json.loads(http('GET','/api/backtest-queue/'+held['id'])[1])['state'],'held')
                    queued=json.loads(http('GET','/api/backtest-queue/'+done['id'])[1])
                    if queued['state']=='archived':
                        self.assertEqual(queued['transfer']['state'],'archived')
                        imported=json.loads(http('GET','/api/backtests/'+queued['transfer']['saved_id'])[1])
                        self.assertEqual(imported['snapshot'],complete_snapshot)
                    else:
                        self.assertEqual(queued['state'],'complete')
                        self.assertEqual(queued['snapshot'],complete_snapshot)
                    if scenario not in ('success','ordinary'):
                        self.assertEqual(http('POST','/api/schedule',{})[0],503)
                        self.assertEqual(http('GET','/')[0],302)
                    elif scenario=='success':
                        state=json.loads(http('GET','/api/data/status')[1])
                        deadline=time.monotonic()+30
                        while state['candidate'].get('busy') and time.monotonic()<deadline:
                            time.sleep(.05);state=json.loads(http('GET','/api/data/status')[1])
                        self.assertEqual(state['candidate']['state'],'current',state['candidate'])
                        self.assertEqual(state['candidate']['closure']['state'],'closed')
                    owner.process.stdin.write('close\n');owner.process.stdin.flush()
                finally:
                    owner.close()
                    if scenario=='raw':(fixture.source/'raw/metrics.jsonl').write_bytes(saved_metrics)
                    if scenario=='publication':(fixture.source/'data/research.sqlite.publication.json').unlink(missing_ok=True)
                self.assertTrue(owner.closed and owner.descendants_empty and owner.eof,owner.closure())
                self.assertEqual(owner.process.returncode,0,logs)
                print(json.dumps(dict(check='candidate-entry',scenario=scenario,closure=owner.closure())),flush=True)


if __name__=='__main__':unittest.main()
