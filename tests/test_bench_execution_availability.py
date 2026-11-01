"""Actual HTTP, priority and orderly restart on private synthetic roots only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.client import RemoteDisconnected
import json
import hashlib
import os
from pathlib import Path
import socket
import sqlite3
import struct
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'scripts'), str(ROOT / 'website')]
from bench_service_fixture import SyntheticService, expanded_fixture, _pending_services
from bench_comparison import ComparisonError
from bench_methods import clean
import bench_execution_observation as observations
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.runtime import cache_access as cache_access
from backtest.engines.original import schedules
import runtime_access
import test_bench_execution as fixtures


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExecutionTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.cleanup_fixture)
        self.request, self.scale = expanded_fixture(self.fixture)
        self.f = self.fixture.fixture
        self.access = cache_access.WorkspaceAccess(self.f.source / 'data/website-data-0.lock')
        self.provider = observations.CurrentObservation(self.request, schedules, seconds=15.)
        # Declare five trials and rank 1..4 for HTTP and direct-function evidence.
        self.fixture.configuration['options']['rank_to'] = 4
        self.originals = self.immutable()
        self.addCleanup(lambda: self.assertEqual(self.originals, self.immutable()))

    def immutable(self):
        return {p.relative_to(self.f.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for folder in (self.f.capture, *(self.f.source / name for name in ('scripts', 'website', 'raw', 'results')))
                for p in folder.rglob('*') if p.is_file()}

    def cleanup_fixture(self):
        # Unittest continues later cleanups after an error. Do not let the
        # enclosing temporary-root cleanup remove a retained service's controls.
        if any(service.fixture is self.fixture.fixture and not service.closed
               for service in _pending_services.values()):
            raise AssertionError('Synthetic service ownership retained; fixture cleanup deferred.')
        self.fixture.doCleanups()

    def service(self, **scenario):
        service = SyntheticService(self.f, self.request, **scenario)
        self.addCleanup(service.close)
        return service.start()

    def explicit(self, number=0):
        c = self.fixture.configuration
        return dict(dates=c['samples'][number], start=c['start'], end=c['end'], months=c['months'], **c['options'])

    def random(self):
        c = self.fixture.configuration
        return dict(start=c['start'], end=c['end'], months=c['months'], trials=c['requested'], seed=c['seed'], **c['options'])

    def wait_intent(self):
        deadline = time.monotonic() + 10.
        while not self.access.live_pending():
            if time.monotonic() > deadline: self.fail('HTTP request did not announce ordinary live intent.')
            time.sleep(.005)

    def release(self, service, name):
        (service.control / (name + '.release')).touch()

    def report(self, check, **values):
        print(json.dumps(dict(check=check, platform=sys.platform, **values)), flush=True)

    def test_http_workflows_equal_ordinary_functions_and_receive_complete_stream(self):
        service = self.service(oracle=True)
        expected = json.loads((service.control / 'expected.json').read_bytes())
        ready = next(row for row in service.events if row['event'] == 'ready')
        self.assertEqual(ready['sources'], self.f.sources)
        self.assertIn(b'Disposable static delivery fixture', service.request('GET', '/'))
        panel = service.request('GET', '/data.html')
        self.assertIn(b'<html', panel.lower())
        self.assertNotIn(b'__DATA_SCRIPT__', panel)
        status = service.request('GET', '/api/data/status')
        self.assertFalse(status['job']['running'])
        first = service.request('POST', '/api/schedule', self.explicit())
        repeated = service.request('POST', '/api/schedule', self.explicit())
        self.assertEqual(clean(first), clean(expected['inspections'][0]))
        self.assertEqual(clean(first), clean(repeated))
        with closing(sqlite3.connect(self.request['database'])) as db:
            before = db.execute('SELECT count(*) FROM period_pools').fetchone()[0]
        rows = service.request('POST', '/api/robustness', self.random())
        self.assertEqual(rows[0]['configuration'], self.fixture.configuration)
        result = rows[-1]['result']
        self.assertEqual(clean(result), clean(expected['random']))
        self.assertGreater(result['execution']['missing_books'], 0)
        self.assertEqual(sorted({r['completed'] for r in rows[1:-1] if r['type'] == 'progress'}), list(range(6)))
        cached = service.request('POST', '/api/robustness', self.random())[-1]['result']
        self.assertEqual(clean(result), clean(cached))
        self.assertEqual(cached['execution']['missing_books'], 0)
        self.assertGreater(cached['execution']['reused_books'], 0)
        inspected = service.request('POST', '/api/schedule', self.explicit(2))
        self.assertEqual(clean(inspected), clean(expected['inspections'][2]))
        service.close()
        self.assertEqual(service.owned.process.returncode, 0)
        self.assertTrue(service.owned.closure()['closed'])
        self.report('http_workflows', scale=self.scale, trials=len(result['trials']),
            cached_books=cached['execution']['reused_books'], panel_bytes=len(panel),
            before_pools=before, financial_agreement='exact', maximum_absolute=0., maximum_relative=0.,
            closure=service.owned.closure())

    def test_three_http_arrivals_preempt_observation_without_reacquisition(self):
        # Three prospective rounds: scan, 64 KiB hash and SQLite metadata unit.
        service = self.service(hold_request=True)
        handoffs = []
        with ThreadPoolExecutor(max_workers=1) as clients:
            for operation in ('signature', 'file_hash', 'metadata'):
                gate = service.control / 'request_held.release'
                if gate.exists(): gate.unlink()
                original = getattr(observations, operation)
                requests, started = [], []
                def trigger(*args, **kwargs):
                    # Compatibility hash calls have no checkpoint. The current
                    # observation's read units always pass one explicitly.
                    checkpoint = kwargs.get('checkpoint') or (args[1] if len(args) > 1 else None)
                    if checkpoint is None: return original(*args, **kwargs)
                    def interrupt():
                        if not requests:
                            requests.append(clients.submit(service.request, 'POST', '/api/schedule', self.explicit()))
                            self.wait_intent()
                            started.append(time.monotonic())
                        checkpoint()
                    return original(args[0], interrupt)
                with patch.object(observations, operation, side_effect=trigger):
                    with self.assertRaisesRegex(ComparisonError, 'busy'): self.provider.current()
                acquired = service.wait('acquired')
                handoff = acquired['at'] - started[0]
                self.assertGreaterEqual(handoff, 0.)
                self.assertLess(handoff, 2.)
                service.wait('request_held')
                with self.assertRaisesRegex(ComparisonError, 'busy'): self.provider.current()
                self.release(service, 'request_held')
                self.assertTrue(requests[0].result(timeout=30)['periods'])
                service.wait('released')
                handoffs.append(dict(unit=operation, seconds=handoff))
        self.provider.current()
        service.close()
        self.report('http_priority', rounds=3, handoffs=handoffs, bound_seconds=2.,
                    source_before_cache=True, no_reacquisition_during_intent=True)

    def test_live_http_request_stops_only_experimental_calculation(self):
        service = self.service(hold_request=True)
        owner = self.fixture.owner(fixture_observation_root=None, coordinated_observation_root=self.f.source)
        marker = self.f.root / 'experiment-calculating'
        code = 'import sys,time;from pathlib import Path;assert input()=="GO";Path(sys.argv[1]).touch();time.sleep(30)'
        check = owner._check
        live = []
        from bench_execution import admission
        with ThreadPoolExecutor(max_workers=1) as clients:
            def arrival():
                if marker.exists() and not live:
                    live.append(clients.submit(service.request, 'POST', '/api/schedule', self.explicit()))
                    self.wait_intent()
                check()
            try:
                with patch.object(admission, 'require_execution'), patch.object(owner, '_check', side_effect=arrival), \
                        patch.object(owner, '_command', return_value=[sys.executable, '-c', code, str(marker)]):
                    with self.assertRaisesRegex(ComparisonError, 'busy'):
                        with owner: owner.compare()
                self.assertEqual(owner._ledger.stopped, 'busy')
                self.assertIsNone(owner._owned)
                self.assertFalse(owner._workspace._active)
                service.wait('request_held')
            finally: self.release(service, 'request_held')
            self.assertTrue(live[0].result(timeout=30)['periods'])
        self.assertIn(b'Disposable static delivery fixture', service.request('GET', '/'))
        service.close()
        self.report('http_preempts_experiment', stopped=owner._ledger.stopped,
                    experiment_closed=True, live_http_completed=True)

    def test_disconnect_retains_partial_trial_and_fresh_interpreter_reuses_it(self):
        service = self.service(disconnect=True, oracle=True)
        expected = json.loads((service.control / 'expected.json').read_bytes())
        with service.connection() as client:
            client.request('POST', '/api/robustness', json.dumps(self.random()), {'Content-Type': 'application/json'})
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            while True:
                row = json.loads(response.readline())
                if row['type'] == 'progress' and row['completed'] == 1: break
            service.wait('trial_committed')
            # RST makes the next actual stream write fail after a committed trial.
            sock = response.fp.raw._sock
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('hh' if os.name == 'nt' else 'ii', 1, 0))
            response.close()
        self.release(service, 'trial_committed')
        service.wait('released')
        with closing(sqlite3.connect(self.request['database'])) as db:
            saved = db.execute("SELECT count(*) FROM period_pools WHERE pool='cached'").fetchone()[0]
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(saved, len(self.fixture.configuration['samples'][0]))
        self.assertLess(saved, expected['random']['execution']['unique_books'])
        old_pid = service.owned.process.pid
        service.close()
        self.assertEqual(service.owned.process.returncode, 0)
        with runtime_access.ownership(self.f.source, exclusive=True, timeout=0):
            path = Path(self.request['database'])
            moved = path.with_suffix('.closed'); path.rename(moved); moved.rename(path)
        restarted = service.restart()
        self.addCleanup(restarted.close)
        self.assertNotEqual(restarted.owned.process.pid, old_pid)
        result = restarted.request('POST', '/api/robustness', self.random())[-1]['result']
        self.assertEqual(clean(result), clean(expected['random']))
        self.assertEqual(result['execution']['reused_books'], saved)
        self.assertGreater(result['execution']['missing_books'], 0)
        cached = restarted.request('POST', '/api/robustness', self.random())[-1]['result']
        self.assertEqual(cached['execution']['missing_books'], 0)
        self.assertEqual(clean(cached), clean(expected['random']))
        self.assertEqual(clean(restarted.request('POST', '/api/schedule', self.explicit())), clean(expected['inspections'][0]))
        restarted.close()
        self.report('http_disconnect_restart', completed_before_disconnect=1, saved_books=saved,
            total_books=result['execution']['unique_books'], reused_after_restart=result['execution']['reused_books'],
            fresh_interpreter=True, financial_agreement='exact', closure=restarted.owned.closure())

    def test_shutdown_keeps_source_until_active_request_and_reader_close(self):
        service = self.service(hold_request=True)
        with ThreadPoolExecutor(max_workers=2) as clients:
            work = clients.submit(service.request, 'POST', '/api/schedule', self.explicit())
            service.wait('request_held')
            # Close the listener while the handler retains financial ownership.
            closing_service = clients.submit(service.close)
            service.wait('shutdown_started')
            self.assertIsNone(service.owned.process.poll())
            self.assertFalse(closing_service.done())
            with self.assertRaises(RuntimeError):
                with runtime_access.ownership(self.f.source, exclusive=True, timeout=0): pass
            self.release(service, 'request_held')
            # Normal shutdown cancels the active Original calculation.
            with self.assertRaises(RemoteDisconnected): work.result(timeout=30)
            closing_service.result(timeout=20)
        self.assertEqual(service.owned.process.returncode, 0)
        self.assertTrue(service.owned.closure()['closed'])
        with runtime_access.ownership(self.f.source, exclusive=True, timeout=0): pass
        self.report('http_active_request_shutdown', source_held_until_handler_closed=True,
                    closure=service.owned.closure())

    def test_failed_startup_and_cleanup_retry_keep_strong_owners(self):
        failed = SyntheticService(self.f, self.request, fail_start=True)
        self.addCleanup(failed.close)
        with self.assertRaises(AssertionError): failed.start()
        self.assertTrue(failed.closed)
        self.assertTrue(failed.owned.closure()['closed'])
        self.assertNotIn(id(failed), _pending_services)
        service = self.service()
        with patch.object(service.owned, 'close', side_effect=TimeoutError('Synthetic closure failure')):
            with self.assertRaises(TimeoutError): service.close()
        self.assertFalse(service.closed)
        self.assertIs(_pending_services[id(service)], service)
        with self.assertRaisesRegex(AssertionError, 'ownership retained'): self.cleanup_fixture()
        self.assertTrue(self.f.root.exists())
        self.assertTrue(service.control.exists())
        service.close()
        self.assertNotIn(id(service), _pending_services)
        self.assertTrue(service.owned.closure()['closed'])
        with runtime_access.ownership(self.f.source, exclusive=True, timeout=0): pass

    def test_source_mismatch_and_pending_source_publication_reject_startup(self):
        path = self.f.source / 'website/data-panel.js'
        original = path.read_bytes()
        path.write_bytes(original + b'\n')
        failed = SyntheticService(self.f, self.request)
        self.addCleanup(failed.close)
        try:
            with self.assertRaises(AssertionError): failed.start()
            self.assertTrue(failed.owned.closure()['closed'])
        finally: path.write_bytes(original)
        journal = self.f.source / 'data/deployment.pending.json'
        journal.write_text('{}')
        blocked = SyntheticService(self.f, self.request)
        self.addCleanup(blocked.close)
        try:
            with self.assertRaises(AssertionError): blocked.start()
            self.assertTrue(blocked.owned.closure()['closed'])
        finally: journal.unlink()


if __name__ == '__main__': unittest.main()
