"""Synthetic financial parity and durable evidence for the shared prototype."""
from datetime import date, timedelta
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get('BACKTEST_BASELINE_RUNTIME', ROOT))
if '--runtime' in sys.argv:
    index = sys.argv.index('--runtime')
    RUNTIME = Path(sys.argv[index + 1]).resolve()
    del sys.argv[index:index + 2]
sys.path.insert(0, str(ROOT / 'tools'))
import bench_baseline as baseline
baseline.bootstrap(RUNTIME)
import bench_methods as methods
from bench_methods_arrays import open_prices

s, robust = baseline.s, baseline.robust


class SharedMethodsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.path = self.root / 'daily.sqlite'
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript(s.SCHEMA)
        companies = {
            'A': (150e6, 180e6, 60e6),
            'B': (200e6, 250e6, 50e6),
            'C': (170e6, 220e6, 30e6),
            'SMALL': (50e6, 70e6, 25e6),
            'STOP': (130e6, 160e6, 45e6),
        }
        for symbol, (cap, ev, ebitda) in companies.items():
            self.db.execute('INSERT INTO companies VALUES(?,?,?,?)',
                            (symbol, symbol, 'NYSE', 'Energy'))
            for year in range(2011, 2017):
                fiscal = date(year, 6, 30)
                self.db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',
                                (symbol, str(fiscal), str(fiscal + timedelta(days=90)),
                                 cap, ev, ebitda, ebitda / ev))
                # B has no financial ratios. C has newer data but no inputs for
                # the selected 2014 report; later data must not fill that hole.
                if symbol != 'B' and not (symbol == 'C' and year == 2014):
                    values = dict(totalStockholdersEquity=100e6, netIncome=30e6,
                                  freeCashFlow=20e6, epsDiluted=year - 2010.)
                    self.db.execute('INSERT INTO financial_inputs VALUES(?,?,?)',
                                    (symbol, str(fiscal), json.dumps(values)))
        day = date(2011, 1, 1)
        index = 0
        while day <= date(2016, 12, 30):
            if day.weekday() < 5:
                value = 10 + index * .001
                if day >= date(2015, 1, 1):
                    self.db.execute('INSERT INTO sessions VALUES(?,?)',
                                    (str(day), 100 + index * .02))
                for symbol in companies:
                    if symbol == 'STOP' and day > date(2016, 5, 31):
                        continue
                    # Raw entry on this day must resolve adjusted entry later.
                    adjusted = None if symbol == 'A' and day == date(2015, 1, 2) else value
                    self.db.execute('INSERT INTO prices VALUES(?,?,?,?)',
                                    (symbol, str(day), value, adjusted))
                index += 1
            day += timedelta(days=1)
        self.db.executemany('INSERT INTO treasuries VALUES(?,?)',
                            [('2014-12-31', .1), ('2015-07-01', .2),
                             ('2016-07-01', .3)])
        self.db.commit()
        self.reader = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
        self.reader.row_factory = sqlite3.Row
        self.addCleanup(self.reader.close)
        self.model = methods.Model(self.reader, s)
        self.addCleanup(self.model.close)
        self.resolver = open_prices(self.reader)
        self.addCleanup(self.resolver.close)

    def configuration(self, pool='legacy', profile='F0', **overrides):
        options = dict(baseline.options(pool, profile), min_cap=0., min_ev=0.)
        options.update(overrides)
        return robust.plan(self.db, start='2015-01-01', end='2016-12-30',
                           months=12, trials=3, seed=42, **options)

    def reference(self, configuration):
        evidence, rows = [], []
        began = time.perf_counter()
        for number, dates in enumerate(configuration['samples'], 1):
            result = s.backtest_dates(
                self.db, dates=dates, start=configuration['start'],
                end=configuration['end'], months=configuration['months'],
                **configuration['options'])
            evidence.append(methods.clean(result))
            rows.append(robust.summarize(result, number, dates))
        summary = methods.clean(robust.summarize_trials(configuration, rows, began))
        return evidence, summary

    def base_inputs(self):
        return {table: [tuple(row) for row in self.db.execute('SELECT * FROM ' + table)]
                for table in ('companies', 'statements', 'financial_inputs',
                              'prices', 'sessions', 'treasuries')}

    def test_both_pools_profiles_and_metrics_match_complete_reference(self):
        inputs = self.base_inputs()
        for pool in ('legacy', 'cached'):
            for profile in ('F0', 'F1', 'F2'):
                for metric in s.metrics.METRICS:
                    with self.subTest(pool=pool, profile=profile, metric=metric):
                        configuration = self.configuration(pool, profile, metric=metric)
                        reference, summary = self.reference(configuration)
                        store = self.root / f'{pool}-{profile}-{metric}.sqlite'
                        freshness = Mock()
                        visible = []

                        def progress(event):
                            saved = methods.replay(store)
                            self.assertEqual(len(saved), event['completed'])
                            self.assertTrue(baseline.compare(reference[:len(saved)], saved)['exact'])
                            visible.append(event['completed'])

                        measurement, evidence = methods.run_request(
                            self.model, self.resolver, configuration, store,
                            freshness=freshness, progress=progress)
                        freshness.assert_called_once_with()
                        self.assertEqual(visible, [1, 2, 3])
                        self.assertTrue(baseline.compare(reference, evidence)['exact'])
                        self.assertTrue(baseline.compare(summary, measurement['summary'])['exact'])
                        self.assertTrue(baseline.compare(evidence, methods.replay(store))['exact'])
                        self.assertEqual(measurement['committed_trials'], 3)
                        self.assertEqual(measurement['response_bytes'], measurement['received_bytes'])
                        self.assertEqual(self.model.db.execute('SELECT COUNT(*) FROM periods').fetchone()[0], 1)
                        self.assertEqual(self.model.db.execute('SELECT COUNT(*) FROM prices').fetchone()[0], 0)
                        self.assertEqual(self.model.db.execute('SELECT COUNT(*) FROM statements').fetchone()[0], 0)
                        self.assertLessEqual(self.model.db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0], 5)
                        self.assertEqual(self.model.db.execute('SELECT COUNT(*) FROM snapshots WHERE year!=1').fetchone()[0], 0)
                        holdings = [holding for trial in evidence for period in trial['periods']
                                    for holding in period['holdings']]
                        self.assertTrue(holdings)
                        symbols = {holding['symbol'] for holding in holdings}
                        self.assertEqual('SMALL' in symbols, pool == 'cached')
                        if profile == 'F1':
                            self.assertNotIn('B', symbols)
                            self.assertFalse(any(h['symbol'] == 'C' and h['fiscal'] == '2014-06-30'
                                                 for h in holdings))
                        if profile == 'F0':
                            self.assertIn('B', symbols)
                            self.assertTrue(any(h['status'] == 'Last available price' for h in holdings))
                        for holding in holdings:
                            for field in ('rank', 'fiscal', 'entry', 'exit', 'return_value',
                                          'status', 'weight', 'contribution_pp'):
                                self.assertIn(field, holding)
        self.assertEqual(self.base_inputs(), inputs)

    def test_raw_and_adjusted_entry_dates_match_shared_policy(self):
        configuration = self.configuration()
        configuration['samples'] = [['2015-01-02', '2016-01-04']] * 3
        reference, summary = self.reference(configuration)
        # Only the draw is fixed. Both evaluators use the same ordinary plan.
        with patch.object(robust, 'plan', return_value=configuration):
            measurement, evidence = methods.run_request(
                self.model, self.resolver, configuration, self.root / 'different-entry.sqlite')
        self.assertTrue(baseline.compare(reference, evidence)['exact'])
        self.assertTrue(baseline.compare(summary, measurement['summary'])['exact'])
        holding = next(h for h in evidence[0]['periods'][0]['holdings'] if h['symbol'] == 'A')
        self.assertEqual(holding['entry'], '2015-01-05')
        self.assertEqual(holding['fiscal'], '2014-06-30')

    def test_empty_trials_remain_visible_and_excluded_from_distributions(self):
        configuration = self.configuration(sector='__NO_MATCH__')
        reference, summary = self.reference(configuration)
        measurement, evidence = methods.run_request(
            self.model, self.resolver, configuration, self.root / 'empty.sqlite')
        self.assertTrue(baseline.compare(reference, evidence)['exact'])
        self.assertTrue(baseline.compare(summary, measurement['summary'])['exact'])
        self.assertEqual(measurement['summary']['valid'], 0)
        self.assertEqual(measurement['summary']['incomplete'], 3)
        self.assertEqual(measurement['summary']['distributions']['spy_cagr']['n'], 0)
        self.assertTrue(all(trial['growth'] is None for trial in evidence))

    def test_annual_average_cache_calls_original_and_retains_missingness(self):
        history = self.model.histories['A']
        original = Mock(wraps=self.model.original_average)
        self.model.original_average = original
        expected = s.metrics.annual_average(history, '2014-06-30', 3)
        self.assertEqual(self.model.annual_average(history, '2014-06-30', 3), expected)
        self.assertEqual(self.model.annual_average(history, '2014-06-30', 3), expected)
        original.assert_called_once_with(history, '2014-06-30', 3)
        self.assertIsNone(self.model.annual_average(history, '2011-06-30', 3))
        self.assertIsNone(self.model.annual_average(history, '2011-06-30', 3))
        self.assertEqual(original.call_count, 2)

    def test_mid_trial_failure_exposes_only_previously_committed_trial(self):
        configuration = self.configuration()
        reference, _ = self.reference(configuration)
        store = self.root / 'interrupted.sqlite'
        ordinary_prepare = self.model.prepare
        calls = 0

        def interrupted_prepare(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise RuntimeError('Synthetic interruption in second trial.')
            return ordinary_prepare(*args, **kwargs)

        with patch.object(self.model, 'prepare', side_effect=interrupted_prepare):
            with self.assertRaisesRegex(RuntimeError, 'Synthetic interruption'):
                methods.run_request(self.model, self.resolver, configuration, store)
        self.assertEqual(calls, 4)
        self.assertTrue(baseline.compare(reference[:1], methods.replay(store))['exact'])
        with closing(sqlite3.connect(store)) as db:
            self.assertEqual(db.execute('SELECT number FROM trials').fetchall(), [(1,)])
        # A fresh retry reproduces all holdings. The interrupted store remains
        # reviewable and cannot accidentally be replaced by a fresh request.
        with self.assertRaisesRegex(ValueError, 'new result store'):
            methods.run_request(self.model, self.resolver, configuration, store)
        _, retry = methods.run_request(self.model, self.resolver, configuration,
                                      self.root / 'retry.sqlite')
        self.assertTrue(baseline.compare(reference, retry)['exact'])
        self.assertTrue(baseline.compare(reference[:1], methods.replay(store))['exact'])

    def test_failed_publication_preserves_completed_trial(self):
        configuration = self.configuration()
        reference, _ = self.reference(configuration)
        store = self.root / 'failed-publication.sqlite'

        def fail_second_publication(event):
            if event['completed'] == 1:
                with closing(sqlite3.connect(store)) as db:
                    with db:
                        db.execute('CREATE TRIGGER fail_second BEFORE INSERT ON trials '
                                   'WHEN NEW.number=2 BEGIN '
                                   "SELECT RAISE(ABORT,'Synthetic publication failure'); END")

        with self.assertRaisesRegex(sqlite3.IntegrityError, 'Synthetic publication failure'):
            methods.run_request(self.model, self.resolver, configuration, store,
                                progress=fail_second_publication)
        self.assertTrue(baseline.compare(reference[:1], methods.replay(store))['exact'])

    def test_request_budget_expiry_leaves_only_committed_rows(self):
        configuration = self.configuration()
        reference, _ = self.reference(configuration)
        store = self.root / 'budget-expired.sqlite'
        with self.assertRaisesRegex(TimeoutError, 'time budget'):
            methods.run_request(self.model, self.resolver, configuration, store,
                                budget_seconds=0)
        self.assertEqual(methods.replay(store), [])
        with closing(sqlite3.connect(store)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM trials').fetchone()[0], 0)
        _, retry = methods.run_request(self.model, self.resolver, configuration,
                                      self.root / 'budget-retry.sqlite')
        self.assertTrue(baseline.compare(reference, retry)['exact'])
        self.assertEqual(methods.replay(store), [])


if __name__ == '__main__':
    unittest.main()
