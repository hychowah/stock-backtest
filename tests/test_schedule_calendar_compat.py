"""Exact old monthly evidence retained as compact, content-bound expectations."""
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.inputs import daily
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT)]
from backtest.financial import rules
from backtest.inputs import market, fmp_download, cache_assets
from backtest.engines.reference import legacy
fmp_download.KEY_PATH = ROOT/'tmp/cb08/nonexistent-key'
from backtest.engines.original import schedules as s
from backtest.engines.original import robustness as r


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class MonthlyCompatibilityTests(unittest.TestCase):
    def test_all_frozen_periods_full_configurations_and_samples(self):
        fixture = json.loads((ROOT/'tests/fixtures/schedule-calendar-legacy-v1.json').read_text())
        specification = fixture['sessions']
        first, last = date.fromisoformat(specification['first']), date.fromisoformat(specification['last'])
        sessions = [first+timedelta(days=n) for n in range((last-first).days+1)
                    if (first+timedelta(days=n)).weekday() in specification['weekdays']
                    and str(first+timedelta(days=n)) not in specification['holidays']]
        self.assertEqual(digest([str(d) for d in sessions]),specification['sha256'])
        db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
        self.addCleanup(db.close); db.executescript(daily.SCHEMA)
        db.executemany('INSERT INTO sessions VALUES(?,100)',[(str(d),) for d in sessions])
        examples = {(e['start'],e['months'],e['seed']):e for e in fixture['examples']}
        self.assertEqual(len(fixture['cases']),60)
        for case in fixture['cases']:
            with self.subTest(start=case['start'],months=case['months'],seed=case['seed']):
                periods = [[str(a),str(b)] for a,b in s.schedule(case['start'],fixture['end'],case['months'],sessions)]
                configuration = r.plan(db,start=case['start'],end=fixture['end'],months=case['months'],
                                       trials=fixture['trials'],seed=case['seed'])
                self.assertEqual(digest(periods),case['periods_sha256'])
                self.assertEqual(digest(configuration),case['configuration_sha256'])
                self.assertEqual(digest(configuration['samples']),case['samples_sha256'])
                example = examples.get((case['start'],case['months'],case['seed']))
                if example:
                    self.assertEqual(periods,example['periods'])
                    self.assertEqual(configuration['samples'][0],example['first_trial'])
        first = fixture['cases'][0]
        arguments = dict(start=first['start'],end=fixture['end'],seed=42)
        self.assertEqual(r.plan(db,**arguments),r.plan(db,months=12,**arguments))
        for months in [None,True,12.,'12',2,23]:
            with self.assertRaises(ValueError): r.plan(db,months=months,**arguments)
            with self.assertRaises(ValueError): s.dated_periods([str(sessions[0])],first['start'],fixture['end'],months,sessions)
        for extra in [dict(interval={'unit':'week','count':1}),dict(version=1)]:
            # These are not legacy planner arguments. Keep its rejection path.
            with self.assertRaises((ValueError,TypeError)): r.plan(db,**arguments,**extra)


if __name__ == '__main__':
    unittest.main()
