"""Protocol checks for isolation, frozen samples, complete evidence and recovery."""
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.inputs import daily, research
from datetime import date, timedelta
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get('BACKTEST_BASELINE_RUNTIME', ROOT))
if '--runtime' in sys.argv:
    index = sys.argv.index('--runtime')
    RUNTIME = Path(sys.argv[index+1]).resolve()
    del sys.argv[index:index+2]
sys.path.insert(0, str(ROOT/'tools'))
import bench_baseline as bench
bench.bootstrap(RUNTIME)
s, r = bench.s, bench.robust


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        # Only this disposable calculation fixture bypasses execution admission.
        self.enterContext(patch.object(bench.admission, 'require_execution'))
        self.path = self.root/'daily.sqlite'
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(daily.SCHEMA)
        self.db.execute("INSERT INTO companies VALUES('A','A','NYSE','Energy')")
        for year in range(2011, 2017):
            self.db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',
                            ('A', f'{year}-06-30', f'{year}-09-28', 150e6, 150e6, 30e6, .2))
        self.db.execute("INSERT INTO prices VALUES('A','2014-06-30',10,10)")
        day = date(2015, 1, 1)
        index = 0
        while day <= date(2016, 12, 30):
            if day.weekday() < 5:
                self.db.execute('INSERT INTO sessions VALUES(?,?)', (str(day), 100+index*.02))
                self.db.execute('INSERT INTO prices VALUES(?,?,?,?)', ('A', str(day), 10+index*.01, 10+index*.01))
                index += 1
            day += timedelta(days=1)
        self.db.commit()
        self.addCleanup(self.db.close)

    def fixture(self, profile='F0'):
        config = r.plan(self.db, start='2015-01-01', end='2016-12-30', trials=24,
                        months=12, seed=42, **bench.options('legacy', profile))
        # All trials deliberately share one schedule: this tests repeated-trial
        # evidence without starting a process pool in an in-memory-sized fixture.
        samples = [config['samples'][0]] * 24
        config['samples'] = samples
        manifest = dict(start=config['start'], end=config['end'], months=12, trials=24,
                        samples={'42': {key: value for key, value in config.items() if key != 'options'}})
        case = dict(id='legacy-'+profile+'-42', pool='legacy', profile=profile, seed=42)
        return manifest, case, config

    def test_freeze_profiles_dates_and_explicit_defaults(self):
        # Supply full endpoint coverage without fabricating missing production data.
        self.db.execute("INSERT INTO sessions VALUES('1995-01-03',50)")
        self.db.execute("INSERT INTO sessions VALUES('2026-10-21',200)")
        manifest = bench.freeze(self.db)
        self.assertEqual(len(manifest['primary_cases']), 18)
        self.assertEqual(manifest['defaults']['max_cap'], None)
        self.assertEqual(manifest['worker_policy']['requested'], None)
        self.assertEqual(manifest['profiles']['F1'][1], dict(field='roe', op='gt', value=10.))
        self.assertEqual(manifest['profiles']['F2'][1]['field'], 'return_3y')
        for case in manifest['primary_cases']:
            config = bench.configuration(manifest, case, self.db)
            self.assertEqual(config['options']['filters'], bench.PROFILES[case['profile']])
            self.assertEqual(config['samples'], manifest['samples'][str(case['seed'])]['samples'])
        bench.validate_manifest(manifest, self.db)
        manifest['trials'] = 23
        with self.assertRaisesRegex(ValueError, 'identity'):
            bench.validate_manifest(manifest, self.db)

    def test_endpoint_coverage_is_required(self):
        with self.assertRaisesRegex(ValueError, 'endpoints'):
            bench.freeze(self.db)

    def test_clear_removes_threshold_rows_and_keeps_base_inputs(self):
        manifest, case, config = self.fixture()
        r.run(self.db, config, workers=1)
        self.db.execute("INSERT OR REPLACE INTO filter_values VALUES('historical','legacy',1,'A','pb',2)")
        self.db.commit()
        before = {name: [tuple(row) for row in self.db.execute('SELECT * FROM '+name)]
                  for name in ('companies', 'statements', 'prices', 'sessions')}
        self.assertGreater(self.db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0], 0)
        self.assertTrue(all(value == 0 for value in bench.clear_books(self.db).values()))
        for name, rows in before.items():
            self.assertEqual(rows, [tuple(row) for row in self.db.execute('SELECT * FROM '+name)])

    def test_full_evidence_fresh_replay_and_empty_filters(self):
        manifest, case, config = self.fixture()
        original = r.plan
        def planner(db, **unused):
            return config
        def connection(path):
            db = sqlite3.connect(path);db.row_factory = sqlite3.Row
            return db
        with patch.object(daily,'connect', connection), patch.object(r, 'plan', planner):
            measurement, fresh = bench.request(self.path, manifest, case, self.root/'telemetry/fresh')
            replay_measurement, replay = bench.request(self.path, manifest, case, self.root/'telemetry/replay', require_fresh=False)
            self.assertEqual(len(fresh), 24)
            self.assertTrue(bench.compare(fresh, replay)['exact'])
            self.assertEqual(measurement['response']['bytes'], measurement['response']['received_bytes'])
            self.assertEqual(measurement['execution']['reused_books'], 0)
            self.assertEqual(replay_measurement['execution']['workers'], 0)
            holding = fresh[0]['periods'][0]['holdings'][0]
            for field in ('rank', 'symbol', 'fiscal', 'entry', 'exit', 'market_cap', 'return_value', 'weight', 'contribution_pp', 'status'):
                self.assertIn(field, holding)
            changed = json.loads(json.dumps(fresh));changed[0]['periods'][0]['holdings'][0]['status'] = 'changed'
            with self.assertRaises(ValueError):
                bench.compare(fresh, changed)
            bench.clear_books(self.db)
            with self.assertRaisesRegex(ValueError, 'Fresh request'):
                # Existing results are still visible on the fixture connection
                # only after the prior committed run; insert one result explicitly.
                self.db.execute("INSERT INTO periods(entry,exit) VALUES('2015-01-01','2015-01-02')")
                self.db.commit()
                bench.request(self.path, manifest, case, self.root/'telemetry/rejected')
        self.assertIsNotNone(original)
        bench.clear_books(self.db)
        manifest, case, config = self.fixture('F1')
        with patch.object(daily,'connect', connection), patch.object(r, 'plan', planner):
            measurement, evidence = bench.request(self.path, manifest, case, self.root/'telemetry/empty')
        self.assertEqual(measurement['valid'], 0)
        self.assertEqual(measurement['incomplete'], 24)
        self.assertTrue(all(trial['growth'] is None for trial in evidence))

    def test_numeric_tolerance_does_not_hide_identity_mismatch(self):
        self.assertFalse(bench.compare(dict(value=1.), dict(value=1.+1e-13))['exact'])
        with self.assertRaises(ValueError):
            bench.compare(dict(rank=1), dict(rank=2))
        for value in (1., 1.0000000000001, True):
            with self.assertRaisesRegex(ValueError, 'type'):
                bench.compare(dict(rank=1), dict(rank=value))
        with self.assertRaises(ValueError):
            bench.compare(dict(value=None), dict(value=0.))
        with self.assertRaises(ValueError):
            bench.compare(dict(value=1.), dict(value=1.1))

    def test_only_content_bound_complete_checkpoints_resume(self):
        manifest, case, config = self.fixture()
        evidence = self.root/'evidence/case.json'
        document = dict(fresh=[dict(value=1.)]*24, replay=[dict(value=1.)]*24)
        bench.publish(evidence, document)
        checkpoint = self.root/'case.json'
        binding = dict(workload='frozen', inputs='same')
        value = dict(status='complete', binding=binding, evidence_file='evidence/case.json',
                     evidence_sha256=bench.file_hash(evidence),
                     measurement=dict(summary=dict(valid=24)), replay=dict(summary=dict(valid=24)))
        bench.publish(checkpoint, value)
        self.assertEqual(bench.verify_checkpoint(checkpoint, binding, self.root), value)
        with self.assertRaisesRegex(ValueError, 'different inputs'):
            bench.verify_checkpoint(checkpoint, dict(inputs='different'), self.root)
        evidence.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'content'):
            bench.verify_checkpoint(checkpoint, binding, self.root)
        value['status'] = 'running';bench.publish(checkpoint, value)
        with self.assertRaisesRegex(ValueError, 'different inputs'):
            bench.verify_checkpoint(checkpoint, binding, self.root)

    def test_resources_are_explicit_and_workdir_is_bounded(self):
        resources = bench.Resources();resources.start();report = resources.finish()
        self.assertEqual(report['supported'], sys.platform == 'win32')
        if sys.platform == 'win32':
            self.assertGreater(report['sampled_tree_peaks']['processes'], 0)
            self.assertGreater(report['sampled_tree_peaks']['private_bytes'], 0)
        bench.assert_workdir(self.root, self.root/'tmp/benchmark')
        for path in (self.root, self.root/'tmp', self.root/'data'):
            with self.assertRaises(ValueError):
                bench.assert_workdir(self.root, path)

    def test_spawned_workers_use_runtime_source_and_report_real_initialization(self):
        unused, case, config = self.fixture()
        telemetry = self.root/'spawn';telemetry.mkdir()
        with patch.dict(os.environ, BACKTEST_BASELINE_RUNTIME=str(RUNTIME),
                        BACKTEST_BASELINE_TELEMETRY=str(telemetry)), \
                patch.object(bench.batch, 'initialize_worker', bench.observed_initialize):
            result = r.run(self.db, config, workers=2)
        self.assertEqual(result['completed'], 24)
        self.assertEqual(result['execution']['workers'], 2)
        observations = [bench.load(path) for path in telemetry.glob('*.json')]
        self.assertTrue(observations)
        self.assertTrue(all(row['pid'] != os.getpid() and row['initialization_seconds'] > 0
                            for row in observations))

    def test_interrupted_request_cannot_reuse_worker_telemetry(self):
        manifest, case, config = self.fixture()
        telemetry = self.root/'retry'
        def connection(path):
            db = sqlite3.connect(path);db.row_factory = sqlite3.Row
            return db
        def interrupted(*unused, **options):
            attempt = Path(os.environ['BACKTEST_BASELINE_TELEMETRY'])
            bench.publish(attempt/'old-worker.json', dict(pid=-1, initialization_seconds=100.))
            raise KeyboardInterrupt()
        with patch.object(daily,'connect', connection), patch.object(r, 'plan', return_value=config):
            with patch.object(r, 'run', interrupted):
                with self.assertRaises(KeyboardInterrupt):
                    bench.request(self.path, manifest, case, telemetry)
            measurement, unused = bench.request(self.path, manifest, case, telemetry)
        self.assertEqual(len(list(telemetry.glob('attempt-*'))), 2)
        self.assertEqual(measurement['worker_initialization'], [])
        self.assertTrue((telemetry/measurement['telemetry_attempt']).is_dir())

    def test_runner_closes_connections_before_disposable_file_cleanup(self):
        manifest, case, config = self.fixture()
        manifest.update(primary_cases=[case], sha256='synthetic', correctness_inventory=[])
        manifest_path = self.root/'workloads.json'
        bench.publish(manifest_path, manifest)
        workdir = self.root/'tmp/baseline'
        args = SimpleNamespace(runtime=self.root, workdir=workdir, manifest=manifest_path,
                               command='run', report=self.root/'report.json', limit=None)
        connections = []
        connect = sqlite3.connect
        def tracked(path, *args, **options):
            db = connect(path, *args, **options);db.row_factory = sqlite3.Row
            connections.append(db)
            return db
        # Keep strong references to every handle. This makes the check detect
        # missing close() calls on Linux too, without relying on GC or Windows.
        with patch.dict(os.environ), patch.object(bench, 'bootstrap'), \
                patch.object(bench.coordinator, 'access', nullcontext), \
                patch.object(bench, 'identity', return_value=dict(inputs='synthetic')), \
                patch.object(bench, 'validate_manifest'), \
                patch.object(research, 'connect', side_effect=lambda **unused: tracked(self.path)), \
                patch.object(daily,'connect', side_effect=lambda unused=None: tracked(unused or self.path)), \
                patch.object(r, 'plan', return_value=config), \
                patch.object(bench.sqlite3, 'connect', side_effect=tracked):
            bench.runner(args)
        self.assertFalse((workdir/'active.sqlite').exists())
        self.assertEqual(bench.load(args.report)['completed'], 1)
        self.assertGreaterEqual(len(connections), 7)
        for db in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')

    def test_changed_tool_cannot_publish_or_initialize_workers(self):
        with patch.object(bench, 'file_hash', return_value='changed'):
            with self.assertRaisesRegex(ValueError, 'tool changed'):
                bench.assert_tool()
            with self.assertRaisesRegex(ValueError, 'tool changed'):
                bench.observed_initialize(None, None)


if __name__ == '__main__':
    unittest.main()
