"""Evidence-bearing prepared inputs for dated financial observations.

Preparation owns these facts. A read view borrows an admitted attachment and
expires with it; detached company records retain no database or array handles.
This module chooses no financial report and evaluates no variable or formula.
"""
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from backtest.financial import books, rules
from backtest.inputs import financial_inputs

VERSION = 1
FIELDS = ('revenue', 'operatingIncome')
TABLES = ('observation_sources', 'observation_annual', 'observation_latest', 'observation_metadata')
SCHEMA = '''
CREATE TABLE observation_sources(symbol TEXT,endpoint TEXT,evidence_json TEXT NOT NULL,
 PRIMARY KEY(symbol,endpoint)) WITHOUT ROWID;
CREATE TABLE observation_annual(symbol TEXT,endpoint TEXT,fiscal TEXT,evidence_json TEXT NOT NULL,
 PRIMARY KEY(symbol,endpoint,fiscal)) WITHOUT ROWID;
CREATE TABLE observation_latest(symbol TEXT,pool TEXT,admitted INTEGER NOT NULL,
 evidence_json TEXT NOT NULL,PRIMARY KEY(symbol,pool)) WITHOUT ROWID;
CREATE TABLE observation_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL) WITHOUT ROWID;
'''


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def policy_binding():
    """Bind the preparation and financial source that establishes these facts."""
    paths = (Path(__file__), Path(financial_inputs.__file__), Path(books.__file__),
             Path(rules.__file__), Path(__file__).with_name('research.py'),
             Path(__file__).with_name('daily.py'))
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def store_annual(db, symbol, resolution):
    """Keep all income dates; an unavailable newer member must remain visible."""
    db.executemany('INSERT INTO observation_sources VALUES(?,?,?)',
        ((symbol, endpoint, encoded(source)) for endpoint, source in resolution['sources'].items()))
    db.executemany('INSERT INTO observation_annual VALUES(?,?,?,?)',
        ((symbol, 'income-statement', fiscal, encoded({field: states[field] for field in FIELDS}))
         for fiscal, states in resolution['annual'].get('income-statement', {}).items()))


def store_latest(db, symbol, pool, evidence):
    """Record root admission, including denials, without implying past listing.

    An admitted latest root needs the existing candidate policy and an exact
    latest-SPY-session adjusted price. Earlier contexts cannot change this root.
    """
    db.execute('INSERT INTO observation_latest VALUES(?,?,?,?)',
               (symbol, pool, int(evidence['admitted']), encoded(evidence)))


def content_identity(db, checkpoint=lambda: None):
    digest = hashlib.sha256()
    for table, order in (('observation_sources', 'symbol,endpoint'),
                         ('observation_annual', 'symbol,endpoint,fiscal'),
                         ('observation_latest', 'symbol,pool')):
        digest.update((table + '\n').encode())
        for row in db.execute(f'SELECT * FROM {table} ORDER BY {order}'):
            checkpoint()
            digest.update((encoded(tuple(row)) + '\n').encode())
    return digest.hexdigest()


def finish(db, latest_date, checkpoint=lambda: None):
    metadata = dict(version=VERSION, latest_date=str(latest_date),
                    policy=policy_binding(), content=content_identity(db, checkpoint))
    db.executemany('INSERT INTO observation_metadata VALUES(?,?)',
                   ((key, encoded(value)) for key, value in metadata.items()))
    return metadata


def require(db, *, expected=None, verify_content=False, checkpoint=lambda: None):
    """Reject absent, incompatible or stale projections before observation work."""
    try:
        metadata = {row[0]: json.loads(row[1]) for row in db.execute('SELECT * FROM observation_metadata')}
        for table in TABLES[:-1]:
            db.execute(f'SELECT * FROM {table} LIMIT 0').close()
        if (set(metadata) != {'version', 'latest_date', 'policy', 'content'}
                or type(metadata['version']) is not int or metadata['version'] != VERSION
                or str(date.fromisoformat(metadata['latest_date'])) != metadata['latest_date']
                or metadata['policy'] != policy_binding()
                or not isinstance(metadata['content'], str) or len(metadata['content']) != 64
                or any(c not in '0123456789abcdef' for c in metadata['content'])
                or expected is not None and metadata != expected):
            raise ValueError()
        if verify_content and content_identity(db, checkpoint) != metadata['content']:
            raise ValueError()
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        raise ValueError('Observation inputs are missing, incompatible or stale. Retry offline preparation.') from None
    return metadata


def copy(source, destination, checkpoint=lambda: None, *, max_record_bytes=None):
    """Copy facts unchanged inside the caller's existing publication transaction."""
    metadata = require(source, verify_content=True, checkpoint=checkpoint)
    for table in TABLES:
        for row in source.execute('SELECT * FROM ' + table):
            checkpoint()
            if max_record_bytes is not None and sum(
                    len(value.encode('utf-8')) if isinstance(value, str) else 8
                    for value in row) > max_record_bytes:
                raise ValueError('Prepared observation record exceeds its byte bound.')
            destination.execute('INSERT INTO ' + table + ' VALUES(' + ','.join('?' * len(row)) + ')', tuple(row))
    require(destination, expected=metadata, verify_content=True, checkpoint=checkpoint)
    return metadata


class ReadView:
    """Borrow one admitted generation; close the view before its attachment.

    No connection, mapping or lease is owned here. validate() invokes the existing
    attachment freshness owner. company() returns complete detached source facts;
    consumers cannot replace a missing field by choosing another report.
    """
    def __init__(self, identity, db, validate, reports, lookup, *, expected,
                 max_history, max_record_bytes):
        self.identity = identity
        self._db, self._validate, self._reports, self._lookup = db, validate, reports, lookup
        self._expected = json.loads(encoded(expected))
        self.max_history, self.max_record_bytes = max_history, max_record_bytes
        self.closed = False
        self.validate()

    @property
    def projection(self):
        return json.loads(encoded(self._expected))

    def validate(self):
        if self.closed:
            raise ValueError('Observation input view is closed.')
        self._validate()
        require(self._db, expected=self._expected)

    def _json(self, text):
        if len(text.encode('utf-8')) > self.max_record_bytes:
            raise ValueError('Prepared observation record exceeds its byte bound.')
        return json.loads(text)

    def company(self, symbol, pool):
        if self.closed:
            raise ValueError('Observation input view is closed.')
        if pool not in ('cached', 'legacy') or not isinstance(symbol, str):
            raise ValueError('Invalid observation company or pool.')
        reports = self._reports(symbol, pool)
        if len(reports) > self.max_history:
            raise ValueError('Prepared observation history exceeds its bound.')
        annual = {}
        cursor = self._db.execute('SELECT fiscal,evidence_json FROM observation_annual '
                                 'WHERE symbol=? AND endpoint=? ORDER BY fiscal LIMIT ?',
                                 (symbol, 'income-statement', self.max_history + 1))
        for fiscal, evidence in cursor:
            if len(annual) == self.max_history:
                raise ValueError('Prepared observation history exceeds its bound.')
            annual[fiscal] = self._json(evidence)
        sources = {row[0]: self._json(row[1]) for row in self._db.execute(
            'SELECT endpoint,evidence_json FROM observation_sources WHERE symbol=? ORDER BY endpoint', (symbol,))}
        latest = self._db.execute('SELECT evidence_json FROM observation_latest WHERE symbol=? AND pool=?',
                                  (symbol, pool)).fetchone()
        return dict(symbol=symbol, pool=pool, reports=reports, annual=annual, sources=sources,
                    latest=self._json(latest[0]) if latest else None)

    def lookup(self, symbol, day, column, forward=False, slack=None):
        if self.closed:
            raise ValueError('Observation input view is closed.')
        if (column not in ('price', 'adjusted') or not isinstance(day, date)
                or type(forward) is not bool
                or slack is not None and (type(slack) is not int or slack < 0)):
            raise ValueError('Invalid observation price lookup.')
        value = self._lookup(symbol, day, column, forward, slack)
        if value is not None and (not math.isfinite(value[1]) or value[1] <= 0):
            raise ValueError('Prepared observation price is invalid.')
        return value

    def close(self):
        self.closed = True
        self._db = self._reports = self._lookup = self._validate = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
