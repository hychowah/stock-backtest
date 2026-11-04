"""Synthetic daily database and exact comparison helpers.

The fixture writes a small `daily.SCHEMA` database with five companies, adjusted
and raw prices, sessions, statements, financial inputs and Treasury yields. It
uses only the standard library. Live observation tests borrow its database.
Frozen numerical engine tests compare their books with the original schedules
engine through `compare`.
"""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))

from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest

from backtest.inputs import daily
from backtest.engines.original import schedules as s

OPTIONS = dict(rank_from=1, rank_to=50, metric='ev_ebitda', min_cap=100e6,
               max_cap=None, min_ev=50e6, min_yield=0., max_multiple=None,
               sector=None, exchange=None, filters=[])
PROFILES = dict(F0=[], F1=[dict(field='pb', op='lt', value=3.),
                         dict(field='roe', op='gt', value=10.)],
                F2=[dict(field='return_1y', op='gt', value=0.),
                    dict(field='return_3y', op='gt', value=0.)])


def options(pool, profile):
    """Return the default top-50 options with one filter profile (F0, F1 or F2)."""
    return dict(OPTIONS, pool=pool, filters=PROFILES[profile])


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def compare(left, right):
    """Compare ordered evidence; categorical values and missingness are exact.

    Numeric fields use fixed 1e-12 relative/absolute tolerances. Integer
    identities remain exact. Return maximum absolute and relative differences,
    and whether the canonical encodings are identical.
    """
    maximum_absolute = maximum_relative = 0.

    def walk(a, b, path):
        nonlocal maximum_absolute, maximum_relative
        if type(a) is not type(b):
            raise ValueError('Evidence type differs at ' + path)
        if type(a) is float:
            if not math.isfinite(a) or not math.isfinite(b):
                raise ValueError('Nonfinite evidence at ' + path)
            absolute = abs(a - b)
            relative = absolute / max(abs(a), abs(b)) if a or b else 0.
            maximum_absolute = max(maximum_absolute, absolute)
            maximum_relative = max(maximum_relative, relative)
            if not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError('Numeric evidence differs at ' + path)
        elif isinstance(a, dict):
            if a.keys() != b.keys():
                raise ValueError('Evidence fields differ at ' + path)
            for key in a:
                walk(a[key], b[key], path + '.' + key)
        elif isinstance(a, list):
            if len(a) != len(b):
                raise ValueError('Evidence lengths differ at ' + path)
            for index, (x, y) in enumerate(zip(a, b)):
                walk(x, y, path + '[' + str(index) + ']')
        elif a != b:
            raise ValueError('Evidence differs at ' + path)

    walk(left, right, '$')
    return dict(maximum_absolute=maximum_absolute, maximum_relative=maximum_relative,
                exact=digest(left) == digest(right))


class SyntheticDailyFixture(unittest.TestCase):
    """Own one disposable synthetic daily database.

    Tests reuse `setUp` directly, or create an instance and call `setUp()` to
    borrow `db`, `reader`, `path` and `root`. Cleanups run with the owner.
    """
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.path = self.root / 'daily.sqlite'
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript(daily.SCHEMA)
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

    def base_inputs(self):
        return {table: [tuple(row) for row in self.db.execute('SELECT * FROM ' + table)]
                for table in ('companies', 'statements', 'financial_inputs',
                              'prices', 'sessions', 'treasuries')}
