"""Typed prepared facts for formulas and books, and their borrowed view.

Research preparation resolves saved files into these tables in its build
transaction. Annual statements use financial_inputs.resolve_history; saved
stock, Treasury and SPY rows use resolve() below, which parses each file once.

- stock_days: one row per company and saved price day, keyed by date, with the
  observation fields.
- market_days: valid SPY sessions (spy) and saved Treasury days (both yields
  in percent).
- annual_facts: one row per company, statement endpoint and fiscal date, with
  one value and one reason column per annual catalog field.
- company_facts: whether each saved company is currently listed.
- fact_sources: the source file digest and disposition per company and
  endpoint; the empty symbol names the shared Treasury and SPY files.
- latest_admission: latest-root admission and its valuation per company and pool.
- fact_metadata: version, latest date, prepared scopes, policy and content identity.

A field is valid when its value is present; otherwise its reason column names
the provider reason. A saved day or fiscal date always has a value or a reason
for each of its endpoint's fields. Value columns have no declared type, so
SQLite keeps the binary64 bits exactly, including -0.0, which a REAL column
stores as the integer 0. The readers still read the stored latest book from
latest_snapshots, screening_metrics and filter_values (typed-storage P3b
switches them).

One rule gives a day its value: equal admissible values agree, and a
conflicting, non-USD or invalid value gives no value and a reason. books.book
reads the valid values through BookFacts. Today books.book (the latest book of
the daily cache) and the View's derived-context readers call legacy_annual()
and ten_year(); the dated books of the daily cache still read its copied tables.

A View borrows the operation's daily and research connections. The caller's
cache ownership keeps both unchanged while the view is open.
"""
from datetime import date
import functools
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from backtest.financial import books, rules
from backtest.inputs import cache_assets, financial_inputs, market
from backtest.variables import parameters

VERSION = 3
MAX_HISTORY = 16384
STOCK = 'historical-price-eod/dividend-adjusted'
TREASURY = 'treasury-rates'
CALENDAR = 'spy-calendar'
_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _annual_columns():
    """(column, endpoint, field) for every direct annual catalog parameter."""
    result = []
    for item in parameters.catalog(parameters.V3):
        if item['kind'] == 'direct' and item['id'].startswith('annual.'):
            result.append((item['id'].split('.', 1)[1], item['source']['endpoint'], item['source']['field']))
    return tuple(result)


ANNUAL = _annual_columns()
_BY_FIELD = {(endpoint, field): column for column, endpoint, field in ANNUAL}
# The legacy values-only annual fields by endpoint, in financial_inputs order.
_LEGACY = tuple((endpoint, tuple((field, _BY_FIELD[endpoint, field]) for field in fields))
                for endpoint, fields in financial_inputs.ENDPOINTS.items() if fields)

SCHEMA = '''
CREATE TABLE stock_days(symbol TEXT, day TEXT, adjusted, adjusted_reason TEXT, volume, volume_reason TEXT,
 PRIMARY KEY(symbol,day)) WITHOUT ROWID;
CREATE TABLE market_days(day TEXT PRIMARY KEY, spy, month3, month3_reason TEXT, year10, year10_reason TEXT) WITHOUT ROWID;
CREATE TABLE annual_facts(symbol TEXT, endpoint TEXT, fiscal TEXT, ''' + ', '.join(
    column + ', ' + column + '_reason TEXT' for column, _, _ in ANNUAL) + ''',
 PRIMARY KEY(symbol,endpoint,fiscal)) WITHOUT ROWID;
CREATE TABLE company_facts(symbol TEXT PRIMARY KEY, listed INTEGER NOT NULL) WITHOUT ROWID;
CREATE TABLE fact_sources(symbol TEXT, endpoint TEXT, sha256 TEXT, disposition TEXT NOT NULL,
 PRIMARY KEY(symbol,endpoint)) WITHOUT ROWID;
CREATE TABLE latest_admission(symbol TEXT, pool TEXT, admitted INTEGER NOT NULL, reason TEXT,
 candidate_rank INTEGER, fiscal TEXT, known TEXT, market_cap REAL, enterprise_value REAL, ebitda REAL,
 PRIMARY KEY(symbol,pool)) WITHOUT ROWID;
CREATE TABLE fact_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
'''


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


# Resolving saved dated files.

def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, float, int)):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, OverflowError):
        return None


def row_day(row):
    """Return the saved day under which one dated row is resolved, or None."""
    value = row.get('date') if isinstance(row, dict) else None
    try:
        return str(date.fromisoformat(value[:10])) if isinstance(value, str) else None
    except ValueError:
        return None


def observe(rows, fields, checkpoint=lambda: None):
    """{day: {field: state}} of saved dated rows: the one value rule of a day.

    Equal admissible values agree; different ones are CONFLICTING_INPUT. An
    explicit foreign currency disqualifies only a price, never volume. A
    price must be positive, a volume non-negative; all signed rates are valid.
    """
    grouped = {}
    for row in rows:
        day = row_day(row)
        if day is not None:
            grouped.setdefault(day, []).append(row)
    dated = {}
    for day, variants in grouped.items():
        checkpoint()
        states = {}
        for field in fields:
            candidates, invalid, foreign = set(), False, False
            for row in variants:
                value = _number(row.get(field))
                incompatible = field == 'adjClose' and any(
                    currency not in (None, '', 'USD') for currency in (row.get('currency'), row.get('reportedCurrency')))
                acceptable = (value is not None and (value > 0 if field == 'adjClose'
                              else value >= 0 if field == 'volume' else True))
                if acceptable and not incompatible:
                    candidates.add(value)
                foreign |= incompatible and value is not None
                invalid |= row.get(field) not in (None, '') and not acceptable
            reason = (None if len(candidates) == 1 else 'CONFLICTING_INPUT' if len(candidates) > 1
                      else 'NON_USD_INPUT' if foreign else 'INVALID_INPUT' if invalid else 'MISSING_INPUT')
            states[field] = dict(value=next(iter(candidates)) if reason is None else None,
                                 valid=reason is None, reason=reason)
        dated[day] = states
    return dated


def resolve(path, endpoint, *, stock=False, checkpoint=lambda: None):
    """Return the source and the field states of each saved day of one file.

    The file is read and parsed once. A stock file is a mapping whose 'div'
    rows are dated; any other content is unreadable. Currency-free stock routes
    use the admitted USD-company/share basis. The source is always complete.
    """
    source = dict(endpoint=endpoint, sha256=None, disposition='missing')
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return dict(source=source, dated={})
    checkpoint()
    source.update(sha256=hashlib.sha256(content).hexdigest(), disposition='unreadable')
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return dict(source=source, dated={})
    rows = (payload.get('div') if isinstance(payload, dict) else None) if stock else payload
    if endpoint == CALENDAR and isinstance(rows, dict):
        # Match the retained SPY reader. Wrapper metadata is not a receipt.
        rows = rows.get('historical') or rows.get('data') or []
    if not isinstance(rows, list):
        return dict(source=source, dated={})
    if len(rows) > MAX_HISTORY:
        raise ValueError('Prepared observation history exceeds its bound.')
    try:
        valid = cache_assets.valid_series(payload, 'month3' if endpoint == TREASURY else 'adjClose', stock=stock)
    except (ValueError, TypeError, OverflowError):
        valid = False
    source['disposition'] = 'valid' if valid else 'salvaged'
    fields = ('month3', 'year10') if endpoint == TREASURY else ('adjClose', 'volume') if stock else ('adjClose',)
    return dict(source=source, dated=observe(rows, fields, checkpoint))


def stock(raw, symbol, checkpoint=lambda: None):
    return resolve(raw / 'px' / market.cache_path_for(symbol).name, STOCK, stock=True, checkpoint=checkpoint)


def shared(raw, checkpoint=lambda: None):
    return {endpoint: resolve(raw / name, endpoint, checkpoint=checkpoint)
            for endpoint, name in ((TREASURY, 'treasury.json'), (CALENDAR, 'spy-div.json'))}


# Writing, inside research preparation's build transaction.

def _pair(state):
    """Return (value, reason) of one resolved field state."""
    return (state['value'], None) if state['valid'] else (None, state['reason'])


def _source(db, symbol, source):
    db.execute('INSERT INTO fact_sources VALUES(?,?,?,?)',
               (symbol, source['endpoint'], source['sha256'], source['disposition']))


def store_annual(db, symbol, resolution):
    """Write every resolved endpoint and fiscal date, including unavailable fields."""
    for endpoint, source in resolution['sources'].items():
        _source(db, symbol, source)
    rows = []
    for endpoint, dates in resolution['annual'].items():
        for fiscal, states in dates.items():
            values = {_BY_FIELD[endpoint, field]: _pair(state) for field, state in states.items()}
            row = [symbol, endpoint, fiscal]
            for column, _, _ in ANNUAL:
                row.extend(values.get(column, (None, None)))
            rows.append(row)
    if rows:
        db.executemany('INSERT INTO annual_facts VALUES(' + ','.join('?' * len(rows[0])) + ')', rows)


def store_stock(db, symbol, resolution):
    """Write the saved days of one price file."""
    _source(db, symbol, resolution['source'])
    dated = resolution['dated']
    db.executemany('INSERT INTO stock_days VALUES(?,?,?,?,?,?)', (
        (symbol, day, *_pair(dated[day]['adjClose']), *_pair(dated[day]['volume'])) for day in sorted(dated)))


def store_market(db, resolutions):
    """Write the shared Treasury and SPY calendar days and their sources."""
    treasury, calendar = resolutions[TREASURY], resolutions[CALENDAR]
    for resolution in (treasury, calendar):
        _source(db, '', resolution['source'])
    days = {}
    for day, states in calendar['dated'].items():
        if states['adjClose']['valid']:
            days[day] = [states['adjClose']['value'], None, None, None, None]
    for day, states in treasury['dated'].items():
        row = days.setdefault(day, [None, None, None, None, None])
        row[1:] = [*_pair(states['month3']), *_pair(states['year10'])]
    db.executemany('INSERT INTO market_days VALUES(?,?,?,?,?,?)', ((day, *days[day]) for day in sorted(days)))


def store_companies(db, universe):
    """Write whether each saved company is currently listed (universe 'listed' is True)."""
    db.executemany('INSERT INTO company_facts VALUES(?,?)',
                   ((symbol, int(company.get('listed') is True)) for symbol, company in universe.items()))


def store_latest(db, symbol, pool, evidence):
    """Record latest-root admission, including denials and their reasons."""
    statement, valuation = evidence['statement'] or {}, evidence['valuation'] or {}
    db.execute('INSERT INTO latest_admission VALUES(?,?,?,?,?,?,?,?,?,?)',
               (symbol, pool, int(evidence['admitted']), evidence['reason'], evidence['candidate_rank'],
                statement.get('fiscal'), statement.get('known'), valuation.get('market_cap'),
                valuation.get('enterprise_value'), valuation.get('ebitda')))


# Book facts: what books.book and the derived-context readers read.

def legacy_annual(db, symbol, checkpoint=lambda: None):
    """{fiscal: {field: value}} of the valid legacy annual values of one company.

    The fields are financial_inputs.ENDPOINTS, in its endpoint and field order;
    a fiscal date without a valid value is left out. This equals the
    values-only projection of financial_inputs.resolve_history bit for bit.
    """
    columns = [column for _, fields in _LEGACY for _, column in fields]
    found = {}
    for endpoint, fiscal, *values in db.execute(
            f'SELECT endpoint,fiscal,{",".join(columns)} FROM annual_facts WHERE symbol=? AND endpoint IN '
            f'({",".join("?" * len(_LEGACY))}) ORDER BY fiscal', (symbol, *(endpoint for endpoint, _ in _LEGACY))):
        checkpoint()
        found.setdefault(fiscal, {})[endpoint] = dict(zip(columns, values))
    result = {}
    for fiscal, rows in found.items():
        values = {field: row[column] for endpoint, fields in _LEGACY if (row := rows.get(endpoint))
                  for field, column in fields if row[column] is not None}
        if values:
            result[fiscal] = values
    return result


def ten_year(db, day):
    """(day, percent) of the latest valid 10-year Treasury value on or before day, or None."""
    row = db.execute('SELECT day,year10 FROM market_days WHERE day<=? AND year10 IS NOT NULL '
                     'ORDER BY day DESC LIMIT 1', (str(day),)).fetchone()
    return None if row is None else (row[0], row[1])


class BookFacts:
    """The facts port of books.Screen and books.book over a research connection.

    reports() is (broad, legacy) as books.pools gives it; cached() holds the
    companies with a saved price file; companies() maps each saved company to
    whether it is listed. price() reads the valid adjusted closes, spy() a
    valid SPY session, treasury() and ten_year() the valid yields. Each input
    is read once per instance; the caller keeps the connection unchanged while
    it is used.
    """

    def __init__(self, db):
        self.db = db
        self._annual, self._reports, self._cached, self._companies = {}, None, None, None

    def reports(self):
        if self._reports is None:
            from backtest.inputs import daily
            self._reports = daily.histories(self.db)
        return self._reports

    def cached(self):
        if self._cached is None:
            self._cached = {row[0] for row in self.db.execute(
                "SELECT symbol FROM fact_sources WHERE endpoint=? AND disposition!='missing'", (STOCK,))}
        return self._cached

    def companies(self):
        if self._companies is None:
            self._companies = {symbol: bool(listed) for symbol, listed in self.db.execute(
                'SELECT symbol,listed FROM company_facts')}
        return self._companies

    def price(self, symbol, day, forward=False, slack=None):
        """(day, adjusted close) nearest on or before (on or after, if forward) day within slack days, or None."""
        operator, order = ('>=', 'ASC') if forward else ('<=', 'DESC')
        row = self.db.execute(f'SELECT day,adjusted FROM stock_days WHERE symbol=? AND day{operator}? '
                              f'AND adjusted IS NOT NULL ORDER BY day {order} LIMIT 1', (symbol, str(day))).fetchone()
        if row is None:
            return None
        result = (date.fromisoformat(row[0]), row[1])
        return result if slack is None or abs((result[0] - day).days) <= slack else None

    def spy(self, day):
        row = self.db.execute('SELECT spy FROM market_days WHERE day=? AND spy IS NOT NULL', (str(day),)).fetchone()
        return None if row is None else row[0]

    def treasury(self, day):
        """The latest valid 3-month Treasury yield on or before day, as a fraction, or None."""
        row = self.db.execute('SELECT month3 FROM market_days WHERE day<=? AND month3 IS NOT NULL '
                              'ORDER BY day DESC LIMIT 1', (str(day),)).fetchone()
        return None if row is None else row[0] / 100

    def ten_year(self, day):
        row = ten_year(self.db, day)
        return None if row is None else row[1]

    def legacy_annual(self, symbol):
        if symbol not in self._annual:
            self._annual[symbol] = legacy_annual(self.db, symbol)
        return self._annual[symbol]


# Projection metadata.

def policy_binding():
    """Bind the preparation and financial source that establishes these facts."""
    return dict(_policy_binding())


@functools.cache
def _policy_binding():
    # The research signature binds the same list, so an edit that rejects
    # these facts also makes research.prepare rebuild them. Hashed once per
    # process: deployment restarts the server on source change.
    from backtest.inputs import research
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in research.calculation_sources()}


def finish(db, latest_date, *, inputs, scopes):
    """Record the projection metadata in the caller's transaction.

    The content identity hashes what determines the rows (the caller's input
    identity, the scopes and this policy), not the rows themselves, so an
    incremental build and a full rebuild of the same inputs record the same
    identity.
    """
    scopes = list(scopes)
    policy = policy_binding()
    content = hashlib.sha256(encoded(dict(version=VERSION, inputs=inputs, scopes=scopes, policy=policy)).encode()).hexdigest()
    metadata = dict(version=VERSION, latest_date=str(latest_date), scopes=scopes, policy=policy, content=content)
    db.executemany('INSERT INTO fact_metadata VALUES(?,?)', ((key, encoded(value)) for key, value in metadata.items()))
    return require(db, expected=metadata)


def require(db, *, expected=None):
    """Reject absent, incompatible or stale facts before formula work."""
    try:
        metadata = {row[0]: json.loads(row[1]) for row in db.execute('SELECT key,value FROM fact_metadata')}
        if (set(metadata) != {'version', 'latest_date', 'scopes', 'policy', 'content'}
                or type(metadata['version']) is not int or metadata['version'] != VERSION
                or str(date.fromisoformat(metadata['latest_date'])) != metadata['latest_date']
                or not isinstance(metadata['scopes'], list)
                or metadata['policy'] != policy_binding()
                or not isinstance(metadata['content'], str) or len(metadata['content']) != 64
                or expected is not None and metadata != expected):
            raise ValueError()
        keys = set()
        for scope in metadata['scopes']:
            if (type(scope) is not dict or set(scope) != {'mode', 'pool', 'context_date', 'book'}
                    or scope['mode'] != 'latest' or scope['pool'] not in ('legacy', 'cached')
                    or type(scope['book']) is not int
                    or str(date.fromisoformat(scope['context_date'])) != scope['context_date']):
                raise ValueError()
            key = scope['mode'], scope['pool'], scope['context_date']
            if key in keys or scope['mode'] == 'latest' and (scope['context_date'] != metadata['latest_date']
                                                              or scope['book'] != 0):
                raise ValueError()
            keys.add(key)
        if any(('latest', pool, metadata['latest_date']) not in keys for pool in ('legacy', 'cached')):
            raise ValueError()
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        raise ValueError('Prepared facts are missing, incompatible or stale. Retry offline preparation.') from None
    return metadata


# Reading.

def _states(**pairs):
    """Field states from (value, reason) pairs; a field with neither has no state."""
    return {field: dict(value=value, valid=reason is None, reason=reason)
            for field, (value, reason) in pairs.items() if value is not None or reason is not None}


class View:
    """Borrowed daily cache and research facts of one operation; close it before either connection.

    The daily cache supplies reports, prices and saved sessions; research
    supplies the typed facts, the legacy annual values, the 10-year yield and
    the stored latest book.
    Each company, day and source is read once per view: neither
    database can change while it is open. validate() is the operation's
    boundary check: the freshness callback, the admitted daily identity and
    the facts metadata.
    """

    def __init__(self, db, research, freshness, checkpoint):
        from backtest.inputs import daily
        freshness()
        self._db, self.db, self._freshness, self._checkpoint = db, research, freshness, checkpoint
        self._expected = require(research)
        row = db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()
        if row is None:
            raise ValueError('Admitted daily input identity is missing.')
        self._admitted = row[0]
        binding = json.loads(self._admitted)
        self.identity = 'sqlite:' + hashlib.sha256(encoded(dict(inputs=binding, adapter=_LOADED)).encode()).hexdigest()
        self._cached = daily.cached_symbols(db)
        broad, legacy = daily.histories(db)
        if any(len(rows) > MAX_HISTORY for rows in broad.values()):
            raise ValueError('Prepared observation history exceeds its bound.')
        self._pools = dict(cached=broad, legacy=legacy)
        self._bounds = dict(latest_date=self._expected['latest_date'], population=len(broad))
        self._candidates, self._reports, self._companies = {}, {}, {}
        self._sessions, self._stock, self._treasury, self._sources = {}, {}, {}, {}
        self.closed = False

    @property
    def projection(self):
        """The admitted facts metadata (scopes, latest date, content identity); callers do not change it."""
        return self._expected

    @property
    def bounds(self):
        return dict(self._bounds)

    def validate(self):
        if self.closed:
            raise ValueError('Observation input view is closed.')
        self._checkpoint()
        self._freshness()
        current = self._db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()
        if current is None or current[0] != self._admitted:
            raise ValueError('Admitted daily input identity changed.')
        require(self.db, expected=self._expected)

    def _open(self):
        if self.closed:
            raise ValueError('Observation input view is closed.')

    def close(self):
        self.closed = True
        self._db = self.db = self._freshness = None

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()

    # Admission and valuation, by the existing financial policy.

    def candidates(self, day, checkpoint=lambda: None):
        """Return (statements by pool, legacy ranks) at one screen date."""
        self._open()
        if day not in self._candidates:
            checkpoint()
            self._candidates[day] = books.candidates((self._pools['cached'], self._pools['legacy']), date.fromisoformat(day))
        return self._candidates[day]

    def is_cached(self, symbol):
        self._open()
        return symbol in self._cached

    def reports(self, symbol, pool):
        self._open()
        key = symbol, pool
        if key not in self._reports:
            self._reports[key] = [dict(row, fiscal=str(row['fiscal']), known=str(row['known']))
                                  for row in self._pools[pool].get(symbol, [])]
        return self._reports[key]

    def admit(self, roots, checkpoint=lambda: None):
        """Admission decisions in root order.

        Historical roots, on a saved SPY session from rules.FIRST_DAY, use the
        complete-population candidates of their date: the legacy buffer precedes
        cached-price membership, so asking for fewer companies cannot promote
        one. Latest roots read the typed latest admission. Earlier contexts
        reuse these decisions.
        """
        self._open()
        self.validate()
        decisions = []
        for index, root in enumerate(roots):
            checkpoint()
            decision = dict(root='r' + str(index), symbol=root['symbol'], pool=root['pool'], mode=root['mode'],
                            date=root['date'], admitted=False, reason=None, candidate_rank=None,
                            statement=None, valuation=None)
            symbol, pool, day = root['symbol'], root['pool'], date.fromisoformat(root['date'])
            if root['mode'] == 'latest':
                if root['date'] != self._bounds['latest_date']:
                    raise ValueError('Latest observation root does not match prepared admission.')
                row = self.db.execute('SELECT admitted,reason,candidate_rank,fiscal,known,market_cap,enterprise_value,ebitda '
                                      'FROM latest_admission WHERE symbol=? AND pool=?', (symbol, pool)).fetchone()
                if row is None:
                    if self.db.execute('SELECT 1 FROM companies WHERE symbol=?', (symbol,)).fetchone():
                        raise ValueError('Prepared latest-root admission is missing.')
                    decision['reason'] = 'UNKNOWN_COMPANY'
                else:
                    admitted, reason, rank, fiscal, known, cap, ev, ebitda = row
                    decision.update(admitted=bool(admitted), reason=reason, candidate_rank=rank,
                                    statement=None if fiscal is None else dict(fiscal=fiscal, known=known),
                                    valuation=None if cap is None else dict(market_cap=cap, enterprise_value=ev, ebitda=ebitda))
            else:
                if (root['mode'] != 'historical' or day < rules.FIRST_DAY
                        or self._db.execute('SELECT 1 FROM sessions WHERE day=?', (str(day),)).fetchone() is None):
                    raise ValueError('Historical observation root is outside saved screen dates.')
                selected, ranks = self.candidates(root['date'], checkpoint)
                statement, rank = selected[pool].get(symbol), ranks.get(symbol)
                decision['candidate_rank'] = rank
                decision['statement'] = None if statement is None else _detached(statement)
                if statement is None:
                    decision['reason'] = 'NO_ELIGIBLE_REPORT'
                elif pool == 'legacy' and rank is None:
                    decision['reason'] = 'OUTSIDE_LEGACY_BUFFER'
                elif not self.is_cached(symbol):
                    decision['reason'] = 'MISSING_CACHED_PRICES'
                else:
                    valuation, evidence = self.entry(symbol, statement, day)
                    decision['admission_evidence'] = evidence
                    if valuation is None:
                        decision['reason'] = evidence['reason']
                    elif not books.eligible(pool, valuation['market_cap'], valuation['enterprise_value']):
                        decision['reason'] = 'INELIGIBLE_VALUATION'
                    else:
                        decision.update(admitted=True, valuation=valuation)
            decisions.append(decision)
        self.validate()
        return decisions

    def entry(self, symbol, statement, day):
        """Observe the authoritative entry valuation and its actual lookups."""
        self._open()
        calls = []

        def lookup(when, forward, slack):
            result = self.lookup(symbol, when, forward, slack)
            # 'price' is the stored explanation label of a valuation lookup.
            calls.append(dict(requested_date=str(when), column='price', forward=forward, slack=slack,
                              observation=[str(result[0]), result[1]] if result else None))
            return result
        reason, value = books.admit(statement, day, lookup, books.ENTRY_SLACK)
        evidence = dict(lookup_policy='existing-entry-valuation', lookups=calls, statement=_detached(statement),
                        reason=reason)
        if value is None:
            return None, evidence
        fiscal, entry, cap, ev, ebitda = value
        return dict(market_cap=cap, enterprise_value=ev, ebitda=ebitda,
                    fiscal_price=[str(fiscal[0]), fiscal[1]], valuation_price=[str(entry[0]), entry[1]]), evidence

    def lookup(self, symbol, day, forward=False, slack=None):
        self._open()
        from backtest.inputs import daily
        if not isinstance(day, date):
            raise ValueError('Invalid observation price lookup.')
        value = daily.price(self._db, symbol, day, forward, slack)
        if value is not None and (not math.isfinite(value[1]) or value[1] <= 0):
            raise ValueError('Prepared observation price is invalid.')
        return value

    def broad_reports(self, symbol, checkpoint=lambda: None, *, budget=None):
        self._open()
        checkpoint()
        reports = self.reports(symbol, 'cached')
        if budget is not None and len(encoded(reports).encode('utf-8')) > budget:
            raise ValueError('Observation report history exceeds its byte bound.')
        return reports

    def legacy_financial_history(self, symbol, checkpoint=lambda: None, *, budget=None):
        """legacy_annual() of one company; the byte bound counts each date's JSON text."""
        self._open()
        result = legacy_annual(self.db, symbol, checkpoint)
        if len(result) > MAX_HISTORY:
            raise ValueError('Prepared observation history exceeds its bound.')
        size = 0
        for fiscal, values in result.items():
            checkpoint()
            size += len(symbol) + len(fiscal) + len(json.dumps(values))
            if budget is not None and size > budget:
                raise ValueError('Observation financial history exceeds its byte bound.')
        return result

    def legacy_treasury(self, day, checkpoint=lambda: None):
        self._open()
        checkpoint()
        row = ten_year(self.db, day)
        return dict(day=row[0], value=row[1]) if row else None

    # Typed facts.

    def company(self, symbol, pool, requirements):
        """Return company facts: reports, the requested annual states and their sources.

        Income-statement dates always form the fiscal spine when any annual field
        is required.
        """
        self._open()
        key = symbol, pool
        cached = self._companies.get(key)
        if cached is None:
            cached = self._companies[key] = dict(reports=self.reports(symbol, pool), annual={}, sources={}, loaded={})
        annual, loaded, sources = cached['annual'], cached['loaded'], cached['sources']
        wanted = dict(requirements)
        if wanted:
            wanted.setdefault('income-statement', set())
        for endpoint, fields in wanted.items():
            missing = sorted(set(fields) - loaded.get(endpoint, set()))
            if endpoint in loaded and not missing:
                continue
            states = annual.setdefault(endpoint, {})
            columns = [_BY_FIELD[endpoint, field] for field in missing]
            projection = ''.join(f',{column},{column}_reason' for column in columns)
            count = 0
            for row in self.db.execute(f'SELECT fiscal{projection} FROM annual_facts WHERE symbol=? AND endpoint=? '
                                       'ORDER BY fiscal LIMIT ?', (symbol, endpoint, MAX_HISTORY + 1)):
                count += 1
                if count > MAX_HISTORY:
                    raise ValueError('Prepared observation history exceeds its bound.')
                states.setdefault(row[0], {}).update(
                    _states(**{field: row[1 + 2 * i:3 + 2 * i] for i, field in enumerate(missing)}))
            loaded.setdefault(endpoint, set()).update(missing)
            if endpoint not in sources:
                sources[endpoint] = self.source(symbol, endpoint)
        return cached

    def session(self, day):
        """The latest valid SPY session on or before day within seven days, or None."""
        self._open()
        if day not in self._sessions:
            row = self.db.execute('SELECT day FROM market_days WHERE day<=? AND spy IS NOT NULL ORDER BY day DESC LIMIT 1',
                                  (str(day),)).fetchone()
            self._sessions[day] = row[0] if row is not None and (day - date.fromisoformat(row[0])).days <= 7 else None
        return self._sessions[day]

    def stock(self, symbol, day):
        """{'adjClose': state, 'volume': state} at one exact saved day, or None."""
        self._open()
        key = symbol, day
        if key not in self._stock:
            row = self.db.execute('SELECT adjusted,adjusted_reason,volume,volume_reason FROM stock_days '
                                  'WHERE symbol=? AND day=?', (symbol, str(day))).fetchone()
            self._stock[key] = None if row is None else _states(adjClose=row[0:2], volume=row[2:4])
        return self._stock[key]

    def treasury(self, day):
        """(day, {'month3': state, 'year10': state}) of the latest saved Treasury day on or before day."""
        self._open()
        if day not in self._treasury:
            row = self.db.execute('SELECT day,month3,month3_reason,year10,year10_reason FROM market_days WHERE day<=? '
                                  'AND (month3 IS NOT NULL OR month3_reason IS NOT NULL) ORDER BY day DESC LIMIT 1',
                                  (str(day),)).fetchone()
            self._treasury[day] = None if row is None else (row[0], _states(month3=row[1:3], year10=row[3:5]))
        return self._treasury[day]

    def source(self, symbol, endpoint):
        """{endpoint, sha256, disposition} of one source file, as explanations keep them."""
        self._open()
        key = symbol, endpoint
        if key not in self._sources:
            row = self.db.execute('SELECT sha256,disposition FROM fact_sources WHERE symbol=? AND endpoint=?',
                                  (symbol, endpoint)).fetchone()
            self._sources[key] = None if row is None else dict(endpoint=endpoint, sha256=row[0], disposition=row[1])
        return self._sources[key]

    def prepared(self, decision):
        """Owner values of the stored latest book row of a latest root.

        A missing row is unavailable; it never falls back to a recalculation.
        """
        self._open()
        pool, symbol = decision['pool'], decision['symbol']
        if decision['mode'] != 'latest':
            raise ValueError('Only a latest root has a stored owner book.')
        row = self.db.execute('SELECT market_cap FROM latest_snapshots WHERE pool=? AND symbol=?', (pool, symbol)).fetchone()
        if row is None:
            return dict(reason='PREPARED_MEASURE_CONTEXT_UNAVAILABLE', evidence=None)
        key = ('latest', pool, 0, symbol)
        metrics = {metric: [multiple, value] for metric, multiple, value in self.db.execute(
            'SELECT metric,multiple,yield_value FROM screening_metrics WHERE mode=? AND pool=? AND year=? AND symbol=?', key)}
        filters = {field: value for field, value in self.db.execute(
            'SELECT field,value FROM filter_values WHERE mode=? AND pool=? AND year=? AND symbol=?', key)}
        return dict(reason=None, evidence=dict(snapshot=dict(market_cap=row[0]), metrics=metrics, filters=filters))


def _detached(statement):
    return {key: str(value) if isinstance(value, date) else value for key, value in statement.items()}
