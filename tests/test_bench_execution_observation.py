"""Fresh observations and cooperative priority, using only disposable roots."""
from contextlib import contextmanager
from pathlib import Path
import json
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'scripts'), str(ROOT / 'website')]
import cache_access
import runtime_access
import bench_execution_observation as observations
from bench_comparison import ComparisonError
import test_bench_execution as fixture_module


def stable_workflow(request_path):
    """Actual financial workflows on a separate disposable mutable daily DB."""
    from bench_execution_worker import _bind
    request = json.loads(Path(request_path).read_bytes())
    s, robust, _ = _bind(request)
    s.r.signature = lambda: request['captured_freshness']['inputs']
    (Path(request['database']).parent / 'binding.json').write_text(json.dumps(request))
    import sqlite3
    from contextlib import closing
    from bench_methods import clean
    with closing(s.connect()) as db:
        config = request['configuration']
        planned = robust.plan(db, start=config['start'], end=config['end'], months=config['months'],
            trials=config['requested'], seed=config['seed'], **config['options'])
        fresh = robust.run(db, planned)
        cached = robust.run(db, planned)
        fixed = s.backtest_dates(db, dates=config['samples'][0], start=config['start'],
            end=config['end'], months=config['months'], **config['options'])
        selected = clean(fixed)
        exported = json.dumps(selected, allow_nan=False)
        saved = db.execute('SELECT count(*) FROM period_pools').fetchone()[0]
    # Source-only page rendering and cached data inspection need no listener,
    # identity state, installed launcher, key or provider requests.
    import serve_app
    panel = serve_app.data_page()
    assert '<html' in panel.lower()
    report = dict(fresh_trials=len(fresh['trials']), cached_reuse=cached['execution']['reused_books'],
                  saved_pools=saved, export_bytes=len(exported.encode()), panel_bytes=len(panel.encode()))
    (Path(request_path).parent / 'live-workflow-result.json').write_text(json.dumps(report))


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.ExecutionTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture.fixture
        self.root = f.source
        self.access = cache_access.WorkspaceAccess(self.root / 'data/website-data-0.lock')
        self.request = dict(observation_root=str(self.root), observation_mode='coordinated',
            sources=f.sources, captured_freshness=f.freshness, captured_metadata=f.meta)
        import schedules
        self.s = schedules

    def provider(self, **changes):
        return observations.CurrentObservation(self.request, self.s, **changes)

    def live(self, mode='hold'):
        code = '''import os,sys,time
from pathlib import Path
sys.path[:0]=[sys.argv[1],sys.argv[4],sys.argv[5]]
from cache_access import WorkspaceAccess
with WorkspaceAccess(Path(sys.argv[2])).hold(timeout=5):
    print('owned',flush=True)
    if sys.argv[3]=='crash':os._exit(0)
    if sys.argv[3]=='workflow':
        from test_bench_execution_observation import stable_workflow
        stable_workflow(sys.argv[6])
    sys.stdin.readline()
'''
        workflow = self.fixture.fixture.root / 'live-request.json'
        if mode == 'workflow':
            request = dict(self.request, source=str(self.root), capture=str(self.fixture.fixture.capture),
                database=str(self.root / 'data/schedules.sqlite'), configuration=self.fixture.configuration,
                binding=dict(generation='synthetic-live-workflow'))
            workflow.write_text(json.dumps(request))
        process = subprocess.Popen([sys.executable, '-X', 'utf8', '-c', code,
            str(ROOT / 'scripts'), str(self.access.path), mode, str(ROOT / 'tests'),
            str(ROOT / 'website'), str(workflow)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def cleanup():
            if process.poll() is None:
                process.stdin.write('done\n'); process.stdin.flush()
            try: process.wait(timeout=10)
            finally:
                if process.poll() is None: process.kill(); process.wait()
                for stream in (process.stdin, process.stdout, process.stderr): stream.close()
        self.addCleanup(cleanup)
        return process

    def wait_intent(self):
        until = time.monotonic() + 5
        while not self.access.live_pending():
            if time.monotonic() > until: self.fail('Live intent was not published before ownership.')
            time.sleep(.005)

    def test_current_binding_releases_all_ownership_before_calculation(self):
        actual = self.provider().current()
        self.assertEqual(actual, self.request['captured_freshness']['inputs'])
        with runtime_access.ownership(self.root, exclusive=True, timeout=0):
            with self.access.hold(timeout=0): pass
        self.assertEqual(actual, self.provider().current())

    def test_live_owner_and_waiter_always_defer_observation(self):
        process = self.live()
        self.assertEqual(process.stdout.readline().strip(), 'owned')
        with self.assertRaisesRegex(ComparisonError, 'busy'): self.provider().current()
        # A second live operation waits; both intent leases remain visible.
        waiting = self.live()
        self.wait_intent()
        self.assertTrue(self.access.live_pending())
        with self.assertRaisesRegex(ComparisonError, 'busy'): self.provider().current()
        process.stdin.write('done\n'); process.stdin.flush(); process.wait(timeout=5)
        self.assertEqual(waiting.stdout.readline().strip(), 'owned')
        with self.assertRaisesRegex(ComparisonError, 'busy'): self.provider().current()

    def test_arriving_live_work_preempts_scan_and_no_reacquisition(self):
        real_signature = observations.signature
        handoffs = []
        def interrupt(research, checkpoint):
            process = self.live()
            self.wait_intent()
            started = time.monotonic()
            try: return real_signature(research, checkpoint)
            finally: handoffs.append((process, started))
        with patch.object(observations, 'signature', side_effect=interrupt):
            with self.assertRaisesRegex(ComparisonError, 'busy'): self.provider().current()
        process, started = handoffs[0]
        self.assertEqual(process.stdout.readline().strip(), 'owned')
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2., 'Disposable handoff exceeded its prospective two-second bound.')
        print(json.dumps(dict(check='cooperative_handoff', seconds=elapsed, platform=sys.platform)), flush=True)
        with self.assertRaisesRegex(ComparisonError, 'busy'): self.provider().current()

    def test_live_arrival_inside_hash_and_sql_units_releases_before_handoff(self):
        for operation in ('file_hash', 'metadata'):
            with self.subTest(operation=operation):
                original = getattr(observations, operation)
                live = []
                started = []
                def work(path, checkpoint=None):
                    if checkpoint is None: return original(path)
                    def interrupt():
                        if not live:
                            live.append(self.live()); self.wait_intent(); started.append(time.monotonic())
                        checkpoint()
                    return original(path, interrupt)
                with patch.object(observations, operation, side_effect=work):
                    with self.assertRaisesRegex(ComparisonError, 'busy'): self.provider().current()
                self.assertEqual(live[0].stdout.readline().strip(), 'owned')
                elapsed = time.monotonic() - started[0]
                self.assertLess(elapsed, 2.)
                print(json.dumps(dict(check='cooperative_handoff', unit=operation,
                                     seconds=elapsed, platform=sys.platform)), flush=True)
                live[0].stdin.write('done\n'); live[0].stdin.flush(); live[0].wait(timeout=5)

    def test_crashed_live_lease_does_not_permanently_block(self):
        process = self.live('crash')
        self.assertEqual(process.stdout.readline().strip(), 'owned')
        self.assertEqual(process.wait(timeout=5), 0)
        self.assertTrue(list(self.access.intents.iterdir()))
        self.assertFalse(self.access.live_pending())
        self.provider().current()

    def test_source_ownership_precedes_cache_and_blocks_pending_publication(self):
        events = []
        own_source, own_cache = runtime_access.ownership, cache_access.WorkspaceAccess.observe
        @contextmanager
        def source(*a, **kw):
            events.append('source')
            with own_source(*a, **kw): yield
        @contextmanager
        def cache(owner):
            events.append('cache')
            with own_cache(owner) as checkpoint: yield checkpoint
        with patch.object(runtime_access, 'ownership', source), patch.object(cache_access.WorkspaceAccess, 'observe', cache):
            self.provider().current()
        self.assertEqual(events, ['source', 'cache'])
        (self.root / 'data/deployment.pending.json').write_text('{}')
        with self.assertRaises(ComparisonError): self.provider().current()

    def test_add_remove_replace_timestamp_report_source_and_journals_reject(self):
        candidates = ['raw/financial-inputs/income/new.json', 'raw/financial-inputs/income/A.json',
                      'raw/metrics.jsonl', 'results/summary-exits.txt', 'scripts/metrics.py',
                      'data/research.sqlite.publication.json']
        for relative in candidates:
            with self.subTest(relative=relative):
                path = self.root / relative
                old = path.read_bytes() if path.exists() else None
                info = path.stat() if old is not None else None
                try:
                    if relative.endswith('/A.json'): path.unlink()
                    else: path.write_bytes((old or b'') + b'\n')
                    with self.assertRaises(ComparisonError): self.provider().current()
                finally:
                    if old is None: path.unlink()
                    else:
                        path.write_bytes(old); os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        path = self.root / 'raw/metrics.jsonl'; info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
        with self.assertRaisesRegex(ComparisonError, 'stale'): self.provider().current()

    def test_nonparticipating_coordination_source_cannot_claim_priority(self):
        self.request['sources'] = dict(self.request['sources'])
        self.request['sources']['scripts/cache_access.py'] = '0' * 64
        with self.assertRaisesRegex(ComparisonError, 'unsupported'): self.provider().current()

    def test_cancel_and_limit_leave_no_source_or_cache_ownership(self):
        for changes in (dict(cancel=lambda: True), dict(seconds=-1)):
            with self.assertRaises(ComparisonError): self.provider(**changes).current()
            with runtime_access.ownership(self.root, exclusive=True, timeout=0):
                with self.access.hold(timeout=0): pass

    def test_coordinated_actual_reference_and_numba_comparison(self):
        owner = self.fixture.owner(fixture_observation_root=None, coordinated_observation_root=self.root)
        from bench_execution import admission
        with patch.object(admission, 'require_execution'), patch.object(owner, '_command',
                side_effect=lambda request: self.fixture.fixture_command(owner, request)):
            with owner: owner.compare()
        self.assertEqual(owner.result['status'], 'fixture_pair_complete')
        self.assertEqual(len(owner._resources), 4)
        self.assertTrue(all(row['closure']['closed'] for row in owner._resources))
        with self.access.hold(timeout=0): pass

    def test_live_work_arriving_during_calculation_stops_only_experiment(self):
        owner = self.fixture.owner(fixture_observation_root=None, coordinated_observation_root=self.root)
        marker = self.fixture.fixture.root / 'calculation-started'
        code = "import sys,time;from pathlib import Path;assert input()=='GO';Path(sys.argv[1]).write_text('started');time.sleep(20)"
        original_check = owner._check
        live = []
        def check():
            if marker.exists() and not live:
                live.append(self.live('workflow')); self.wait_intent()
            return original_check()
        from bench_execution import admission
        with patch.object(admission, 'require_execution'), patch.object(owner, '_check', side_effect=check), \
                patch.object(owner, '_command', return_value=[sys.executable, '-c', code, str(marker)]):
            with self.assertRaisesRegex(ComparisonError, 'busy'):
                with owner: owner.compare()
        self.assertEqual(live[0].stdout.readline().strip(), 'owned')
        self.assertIsNone(owner._owned)
        self.assertTrue(self.access.live_pending())
        self.assertEqual(owner._ledger.stopped, 'busy')
        result_path = self.fixture.fixture.root / 'live-workflow-result.json'
        deadline = time.monotonic() + 30
        while not result_path.exists() and live[0].poll() is None and time.monotonic() < deadline: time.sleep(.01)
        self.assertTrue(result_path.exists(), 'Disposable live financial workflows did not finish.')
        workflows = json.loads(result_path.read_bytes())
        self.assertEqual(workflows['fresh_trials'], 5)
        self.assertGreater(workflows['cached_reuse'], 0)
        self.assertGreater(workflows['saved_pools'], 0)
        self.assertGreater(workflows['export_bytes'], 0)
        self.assertGreater(workflows['panel_bytes'], 0)

    def test_cancellation_at_child_phase_boundaries_and_private_disk_limit(self):
        from bench_execution import admission
        for phase in ('setup', 'proof', 'request', 'collection', 'disk'):
            with self.subTest(phase=phase):
                marker = self.fixture.fixture.root / ('phase-' + phase)
                owner = self.fixture.owner()
                events = ('setup', 'proof', 'request')
                count = ('setup', 'proof', 'request', 'collection').index(phase) if phase != 'disk' else 0
                # Emit completed preceding phases; cancellation owns the active
                # phase. These are lifecycle fixtures, not financial evidence.
                body = "import sys,json,time;from pathlib import Path;assert input()=='GO';"
                body += ''.join("print(json.dumps(dict(event='phase',name=" + repr(name) + ")),flush=True);" for name in events[:count])
                if phase == 'disk':
                    body += "Path(sys.argv[1]).with_name('private-growth.bin').write_bytes(b'x'*(65*1024**2));"
                body += "Path(sys.argv[1]).write_text('started');time.sleep(20)"
                if phase != 'disk': owner.cancel = lambda marker=marker: marker.exists()
                with patch.object(admission, 'require_execution'), patch.object(owner, '_command',
                        side_effect=lambda request, body=body, marker=marker: [sys.executable, '-c', body,
                            str(request.parent / marker.name) if phase == 'disk' else str(marker)]):
                    with self.assertRaisesRegex((ComparisonError, __import__('bench_execution_inputs').ExecutionInputError),
                                               'limit' if phase == 'disk' else 'cancelled'):
                        with owner: owner.compare()
                self.assertIsNone(owner._owned)
                self.assertFalse(owner._workspace._active)


if __name__ == '__main__': unittest.main()
