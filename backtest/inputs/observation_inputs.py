"""Evidence-bearing prepared inputs for dated financial observations.

Preparation owns these facts. A read view borrows an admitted attachment and
expires with it; detached company records retain no database or array handles.
Root admission delegates to the existing financial policy. Formula and temporal
observation semantics belong to the provider, not to this storage boundary.
"""
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from backtest.financial import books, rules
from backtest.inputs import financial_inputs
from backtest.variables import parameters

VERSION = 2
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
             Path(__file__).with_name('daily.py'), Path(parameters.__file__))
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def store_annual(db, symbol, resolution):
    """Keep every admitted endpoint/date, including entirely unavailable fields.

    Source and row receipts retain endpoint identity. A consumer must join the
    chosen income fiscal spine exactly, never select a replacement endpoint date.
    """
    db.executemany('INSERT INTO observation_sources VALUES(?,?,?)',
        ((symbol, endpoint, encoded(source)) for endpoint, source in resolution['sources'].items()))
    db.executemany('INSERT INTO observation_annual VALUES(?,?,?,?)',
        ((symbol, endpoint, fiscal, encoded(states))
         for endpoint, dates in resolution['annual'].items() for fiscal, states in dates.items()))


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
                 max_history, max_record_bytes, bounds=None, populations=None,
                 cached=None, session=None):
        self.identity = identity
        self._db, self._validate, self._reports, self._lookup = db, validate, reports, lookup
        self._expected = json.loads(encoded(expected))
        self.max_history, self.max_record_bytes = max_history, max_record_bytes
        self._bounds = bounds
        self._populations, self._cached, self._session = populations, cached, session
        self.closed = False
        self.validate()

    @property
    def projection(self):
        return json.loads(encoded(self._expected))

    @property
    def bounds(self):
        """Detached preflight counts; these reveal no financial observations."""
        if self.closed:
            raise ValueError('Observation input view is closed.')
        if self._bounds is None:
            raise ValueError('Generation has no observation admission capability.')
        return json.loads(encoded(self._bounds))

    def admit(self, roots, budget, checkpoint=lambda: None):
        """Admit roots against the complete original-order population.

        The legacy buffer precedes cached-price membership. Requested subsets
        never form their own buffer. Earlier observation contexts reuse these
        detached decisions; they establish no new root or listing history.
        """
        self.validate()
        bounds = self.bounds
        dates = {root['date'] for root in roots if root['mode'] == 'historical'}
        cost = len(dates) * 2 * (bounds['report_rows'] + bounds['population'])
        if not isinstance(budget, dict) or budget.get('rows', -1) < cost:
            raise ValueError('Observation admission exceeds its inspected-row bound.')
        for root in roots:
            day = date.fromisoformat(root['date'])
            if root['mode'] == 'historical':
                if (not isinstance(bounds['historical_through'], str)
                        or day.year < rules.FIRST_YEAR or str(day) > bounds['historical_through']
                        or not self._session(day)):
                    raise ValueError('Historical observation root is outside saved screen dates.')
            elif root['mode'] != 'latest' or root['date'] != bounds['latest_date']:
                raise ValueError('Latest observation root does not match prepared admission.')
        by_day = {}
        for text in sorted(dates):
            checkpoint()
            by_day[text] = books.candidates(self._populations(checkpoint), date.fromisoformat(text))
        decisions, size = [], 0
        for root in roots:
            checkpoint()
            decision = dict(root=root['id'], symbol=root['symbol'], pool=root['pool'],
                            mode=root['mode'], date=root['date'], admitted=False,
                            reason=None, candidate_rank=None, statement=None, valuation=None)
            symbol, pool = root['symbol'], root['pool']
            if root['mode'] == 'latest':
                row = self._db.execute('SELECT evidence_json FROM observation_latest WHERE symbol=? AND pool=?',
                                       (symbol, pool)).fetchone()
                if row is None:
                    if self._db.execute('SELECT 1 FROM companies WHERE symbol=?', (symbol,)).fetchone():
                        raise ValueError('Prepared latest-root admission is missing.')
                    decision['reason'] = 'UNKNOWN_COMPANY'
                else:
                    evidence = self._json(row[0])
                    if evidence.get('root_date') != root['date']:
                        raise ValueError('Prepared latest-root admission is incompatible.')
                    decision.update(admitted=bool(evidence['admitted']), reason=evidence.get('reason'),
                                    candidate_rank=evidence.get('candidate_rank'),
                                    statement=evidence.get('statement'), valuation=evidence.get('valuation'),
                                    admission_evidence=evidence)
            else:
                selected, ranks = by_day[root['date']]
                statement = selected[pool].get(symbol)
                rank = ranks.get(symbol)
                decision['candidate_rank'] = rank
                decision['statement'] = self._statement(statement) if statement is not None else None
                if statement is None:
                    decision['reason'] = 'NO_ELIGIBLE_REPORT'
                elif pool == 'legacy' and rank is None:
                    decision['reason'] = 'OUTSIDE_LEGACY_BUFFER'
                elif not self._cached(symbol):
                    decision['reason'] = 'MISSING_CACHED_PRICES'
                else:
                    valuation, evidence = self.entry(symbol, statement, date.fromisoformat(root['date']))
                    decision['admission_evidence'] = evidence
                    if valuation is None:
                        decision['reason'] = evidence['reason']
                    elif not books.eligible(pool, valuation['market_cap'], valuation['enterprise_value']):
                        decision['reason'] = 'INELIGIBLE_VALUATION'
                    else:
                        decision.update(admitted=True, valuation=valuation)
            size += len(encoded(decision).encode('utf-8'))
            if size > budget.get('bytes', -1):
                raise ValueError('Observation admission exceeds its byte bound.')
            decisions.append(decision)
        self.validate()
        return decisions

    @staticmethod
    def _statement(statement):
        return {key: str(value) if isinstance(value, date) else value for key, value in statement.items()}

    def entry(self, symbol, statement, day):
        """Observe authoritative entry valuation and its actual lookup evidence."""
        calls = []
        def lookup(when, column, forward, slack):
            result = self.lookup(symbol, when, column, forward, slack)
            calls.append(dict(requested_date=str(when), column=column, forward=forward, slack=slack,
                              observation=[str(result[0]), result[1]] if result else None))
            return result
        value = books.entry_valuation(statement, day, lookup)
        evidence = dict(lookup_policy='existing-entry-valuation', lookups=calls,
                        statement=self._statement(statement),
                        reason=None if value else ('MISSING_PRICE' if any(c['observation'] is None for c in calls)
                                                  else 'NONPOSITIVE_VALUATION'))
        if value is None:
            return None, evidence
        fiscal, entry, cap, ev, ebitda = value
        if not all(math.isfinite(number) for number in (cap, ev, ebitda)):
            return None, dict(evidence, reason='NONFINITE_RESULT')
        return dict(market_cap=cap, enterprise_value=ev, ebitda=ebitda,
                    fiscal_price=[str(fiscal[0]), fiscal[1]], valuation_price=[str(entry[0]), entry[1]]), evidence

    def validate(self):
        if self.closed:
            raise ValueError('Observation input view is closed.')
        self._validate()
        require(self._db, expected=self._expected)

    def _json(self, text):
        if len(text.encode('utf-8')) > self.max_record_bytes:
            raise ValueError('Prepared observation record exceeds its byte bound.')
        return json.loads(text)

    def company(self, symbol, pool, *, budget=None, checkpoint=lambda: None):
        # The observation operation owns whole-generation admission and its
        # final freshness check. A company read inspects only its bounded facts.
        if self.closed:
            raise ValueError('Observation input view is closed.')
        if pool not in ('cached', 'legacy') or not isinstance(symbol, str):
            raise ValueError('Invalid observation company or pool.')
        reports = self._reports(symbol, pool)
        if len(reports) > self.max_history:
            raise ValueError('Prepared observation history exceeds its bound.')
        size = len(encoded(reports).encode('utf-8'))
        def decode(text):
            nonlocal size
            checkpoint()
            size += len(text.encode('utf-8'))
            if budget is not None and size > budget['bytes']:
                raise ValueError('Observation company facts exceed their byte bound.')
            return self._json(text)
        if budget is not None and size > budget['bytes']:
            raise ValueError('Observation company facts exceed their byte bound.')
        endpoints = financial_inputs.observation_fields()
        annual = {endpoint: {} for endpoint in endpoints}
        # Bound total retained rows and each endpoint's full history separately.
        # The provider's max_annual preflight counts all endpoints together.
        cursor = self._db.execute('SELECT endpoint,fiscal,evidence_json FROM observation_annual '
                                 'WHERE symbol=? ORDER BY endpoint,fiscal LIMIT ?',
                                 (symbol, len(endpoints) * self.max_history + 1))
        for endpoint, fiscal, evidence in cursor:
            if endpoint not in annual or len(annual[endpoint]) == self.max_history:
                raise ValueError('Prepared observation history exceeds its bound.')
            annual[endpoint][fiscal] = decode(evidence)
        sources = {}
        for endpoint, evidence in self._db.execute('SELECT endpoint,evidence_json FROM observation_sources '
                'WHERE symbol=? ORDER BY endpoint LIMIT ?', (symbol, len(endpoints) + 1)):
            if endpoint not in endpoints:
                raise ValueError('Prepared observation source endpoint is incompatible.')
            sources[endpoint] = decode(evidence)
        latest = self._db.execute('SELECT evidence_json FROM observation_latest WHERE symbol=? AND pool=?',
                                  (symbol, pool)).fetchone()
        result = dict(symbol=symbol, pool=pool, reports=reports, annual=annual, sources=sources,
                      latest=decode(latest[0]) if latest else None)
        if budget is not None and len(encoded(result).encode('utf-8')) > budget['bytes']:
            raise ValueError('Observation company facts exceed their byte bound.')
        return result

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
        self._populations = self._cached = self._session = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
