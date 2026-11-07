"""Typed prepared facts: the tables that research preparation writes and the book facts port.

Research preparation resolves saved files into these tables in its build
transaction. Annual statements use financial_inputs.resolve_history; saved
stock, Treasury and SPY rows use resolve() below, which parses each file once.

- stock_days: one row per company and saved price day, keyed by date, with the
  observation fields.
- market_days: valid SPY sessions (spy) and saved Treasury days (both yields
  in percent).
- annual_facts: one row per company, statement endpoint and fiscal date, with
  one value and one reason column per annual catalog field.
- companies: each saved company with its name, exchange, sector and whether
  it is listed now.
- fact_sources: the source file digest and disposition per company and
  endpoint; the empty symbol names the shared Treasury and SPY files.

The research record (research.py) names the facts' version and content
identity. A field is valid when its value is present; otherwise its reason
column names the provider reason. A saved day or fiscal date always has a
value or a reason for each of its endpoint's fields. Value columns have no
declared type, so SQLite keeps the binary64 bits exactly, including -0.0,
which a REAL column stores as the integer 0.

One rule gives a day its value: equal admissible values agree, and a
conflicting, non-USD or invalid value gives no value and a reason. A stock
series with an isolated price spike keeps no close (stock()). Books
(books.book) and admission (books.Screen) read the valid values through
BookFacts. Every reader reads the facts through the 'research' schema that a
daily connection attaches (daily.attach). The book store of the daily cache
(backtest/inputs/book_store.py) holds the latest and dated books; the formula
view (backtest/inputs/fact_view.py) reads the facts for formulas.
"""
from datetime import date
import hashlib
import json
import math

from backtest.financial import books
from backtest.inputs import cache_assets, financial_inputs, market
from backtest.variables import parameters

MAX_HISTORY = 16384
STOCK = 'historical-price-eod/dividend-adjusted'
TREASURY = 'treasury-rates'
CALENDAR = 'spy-calendar'
# The isolated price spike of stock() and the reason it gives every close.
SPIKE = 8
INCONSISTENT_SERIES = 'INCONSISTENT_SERIES'


def _annual_columns():
    """(column, endpoint, field) for every direct annual catalog parameter."""
    result = []
    for item in parameters.catalog(parameters.V3):
        if item['kind'] == 'direct' and item['id'].startswith('annual.'):
            result.append((item['id'].split('.', 1)[1], item['source']['endpoint'], item['source']['field']))
    return tuple(result)


ANNUAL = _annual_columns()
# The annual_facts column of each (endpoint, field).
COLUMNS = {(endpoint, field): column for column, endpoint, field in ANNUAL}
# The legacy values-only annual fields by endpoint, in financial_inputs order:
# what BookFacts.legacy_annual reads. financial_inputs and the catalog are fact-row
# code, so the book identity names this list itself (research.code_identity).
LEGACY = tuple((endpoint, tuple((field, COLUMNS[endpoint, field]) for field in fields))
               for endpoint, fields in financial_inputs.ENDPOINTS.items() if fields)

SCHEMA = '''
CREATE TABLE stock_days(symbol TEXT, day TEXT, adjusted, adjusted_reason TEXT, volume, volume_reason TEXT,
 PRIMARY KEY(symbol,day)) WITHOUT ROWID;
CREATE TABLE market_days(day TEXT PRIMARY KEY, spy, month3, month3_reason TEXT, year10, year10_reason TEXT) WITHOUT ROWID;
CREATE TABLE annual_facts(symbol TEXT, endpoint TEXT, fiscal TEXT, ''' + ', '.join(
    column + ', ' + column + '_reason TEXT' for column, _, _ in ANNUAL) + ''',
 PRIMARY KEY(symbol,endpoint,fiscal)) WITHOUT ROWID;
CREATE TABLE companies(symbol TEXT PRIMARY KEY, name TEXT, exchange TEXT, sector TEXT, listed INTEGER NOT NULL);
CREATE TABLE fact_sources(symbol TEXT, endpoint TEXT, sha256 TEXT, disposition TEXT NOT NULL,
 PRIMARY KEY(symbol,endpoint)) WITHOUT ROWID;
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


def _spiked(closes):
    """Whether one close is at least SPIKE times, or at most 1/SPIKE of, both neighbouring closes."""
    for before, middle, after in zip(closes, closes[1:], closes[2:]):
        up, down = middle / before, middle / after
        if min(up, down) >= SPIKE or max(up, down) <= 1 / SPIKE:
            return True
    return False


def stock(raw, symbol, checkpoint=lambda: None):
    """Resolve one saved price file; a series with an isolated spike keeps no close.

    Such a spike mixes two price scales in one provider series, so no close of
    it is usable: every valid close becomes INCONSISTENT_SERIES and the company
    has no price. Neighbours are the adjacent valid closes in day order.
    """
    resolution = resolve(raw / 'px' / market.cache_path_for(symbol).name, STOCK, stock=True, checkpoint=checkpoint)
    closes = [states['adjClose'] for _, states in sorted(resolution['dated'].items()) if states['adjClose']['valid']]
    if _spiked([state['value'] for state in closes]):
        for state in closes:
            state.update(value=None, valid=False, reason=INCONSISTENT_SERIES)
    return resolution


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
            values = {COLUMNS[endpoint, field]: _pair(state) for field, state in states.items()}
            row = [symbol, endpoint, fiscal]
            for column, _, _ in ANNUAL:
                row.extend(values.get(column, (None, None)))
            rows.append(row)
    if rows:
        db.executemany('INSERT INTO annual_facts VALUES(' + ','.join('?' * len(rows[0])) + ')', rows)


def store_stock(db, symbol, resolution):
    """Write the saved days of one price file; return its stock_days rows without the symbol, by day."""
    _source(db, symbol, resolution['source'])
    dated = resolution['dated']
    rows = [(day, *_pair(dated[day]['adjClose']), *_pair(dated[day]['volume'])) for day in sorted(dated)]
    db.executemany('INSERT INTO stock_days VALUES(?,?,?,?,?,?)', ((symbol, *row) for row in rows))
    return rows


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
    """Write each saved company: its name, exchange and sector, and whether it is listed (universe 'listed' is True)."""
    db.executemany('INSERT INTO companies VALUES(?,?,?,?,?)', (
        (symbol, company.get('name') or 'Unavailable', company.get('exchange') or 'Unavailable',
         company.get('sector') or 'Unavailable', int(company.get('listed') is True)) for symbol, company in universe.items()))


# Book facts: what books.book, books.Screen and the derived-context readers read,
# through the 'research' schema of a daily connection.

def legacy_annual(db, symbol, schema='research'):
    """{fiscal: {field: value}} of the valid legacy annual values of one company.

    The fields are LEGACY (financial_inputs.ENDPOINTS), in its endpoint and
    field order; a fiscal date without a valid value is left out. This equals the
    values-only projection of financial_inputs.resolve_history bit for bit.
    schema names the research facts on db: 'research' on a daily connection;
    research preparation's fact diff reads 'main' and 'old'. The read is
    bounded: more than MAX_HISTORY rows for each legacy endpoint, counted
    together, fail.
    """
    columns = [column for _, fields in LEGACY for _, column in fields]
    bound = MAX_HISTORY * len(LEGACY)
    found, count = {}, 0
    for endpoint, fiscal, *values in db.execute(
            f'SELECT endpoint,fiscal,{",".join(columns)} FROM {schema}.annual_facts WHERE symbol=? AND endpoint IN '
            f'({",".join("?" * len(LEGACY))}) ORDER BY fiscal LIMIT ?', (symbol, *(endpoint for endpoint, _ in LEGACY), bound + 1)):
        count += 1
        if count > bound:
            raise ValueError('Prepared observation history exceeds its bound.')
        found.setdefault(fiscal, {})[endpoint] = dict(zip(columns, values))
    result = {}
    for fiscal, rows in found.items():
        values = {field: row[column] for endpoint, fields in LEGACY if (row := rows.get(endpoint))
                  for field, column in fields if row[column] is not None}
        if values:
            result[fiscal] = values
    return result


def ten_year(db, day):
    """(day, percent) of the latest valid 10-year Treasury value on or before day, or None."""
    row = db.execute('SELECT day,year10 FROM research.market_days WHERE day<=? AND year10 IS NOT NULL '
                     'ORDER BY day DESC LIMIT 1', (str(day),)).fetchone()
    return None if row is None else (row[0], row[1])


def sessions(db):
    """The saved SPY sessions in order."""
    return [date.fromisoformat(row[0]) for row in db.execute(
        'SELECT day FROM research.market_days WHERE spy IS NOT NULL ORDER BY day')]


class BookFacts:
    """The facts port of books.Screen and books.book on a daily connection that attaches research.

    reports() is (broad, legacy) as books.pools gives it; cached() holds the
    companies with a saved price file; companies() maps each saved company to
    whether it is listed. price() reads the valid adjusted closes, spy() a
    valid SPY session, treasury() and ten_year() the valid yields. Each input
    is read once per instance; the caller keeps the connection unchanged while
    it is used. Each read is one kind of the research fact diff (research._Diff,
    books.VISIBLE): reports() and companies() statements, cached() and price()
    prices, spy(), treasury() and ten_year() market, legacy_annual() annual; a
    new read needs a kind, or kept books go stale.
    """

    def __init__(self, db):
        self.db = db
        self._annual, self._reports, self._cached, self._companies = {}, None, None, None

    def reports(self):
        if self._reports is None:
            broad = {}
            for symbol, fiscal, known, cap, ev, ebitda, ebitda_yield in self.db.execute(
                    'SELECT symbol,fiscal,known,market_cap,enterprise_value,ebitda,ebitda_yield '
                    'FROM research.statements ORDER BY rowid'):
                # The names of books.statements, which books and metrics read.
                broad.setdefault(symbol, []).append(dict(
                    fiscal=date.fromisoformat(fiscal), known=date.fromisoformat(known), market_cap=cap,
                    enterprise=ev, ebitda=ebitda, **{'yield': ebitda_yield}))
            for rows in broad.values():
                rows.sort(key=lambda row: row['fiscal'])
            self._reports = books.pools(broad)
        return self._reports

    def cached(self):
        if self._cached is None:
            self._cached = {row[0] for row in self.db.execute(
                "SELECT symbol FROM research.fact_sources WHERE endpoint=? AND disposition!='missing'", (STOCK,))}
        return self._cached

    def companies(self):
        if self._companies is None:
            self._companies = {symbol: bool(listed) for symbol, listed in self.db.execute(
                'SELECT symbol,listed FROM research.companies')}
        return self._companies

    def price(self, symbol, day, forward=False, slack=None):
        """(day, adjusted close) nearest on or before (on or after, if forward) day within slack days, or None."""
        operator, order = ('>=', 'ASC') if forward else ('<=', 'DESC')
        row = self.db.execute(f'SELECT day,adjusted FROM research.stock_days WHERE symbol=? AND day{operator}? '
                              f'AND adjusted IS NOT NULL ORDER BY day {order} LIMIT 1', (symbol, str(day))).fetchone()
        if row is None:
            return None
        result = (date.fromisoformat(row[0]), row[1])
        return result if slack is None or abs((result[0] - day).days) <= slack else None

    def spy(self, day):
        row = self.db.execute('SELECT spy FROM research.market_days WHERE day=? AND spy IS NOT NULL',
                              (str(day),)).fetchone()
        return None if row is None else row[0]

    def treasury(self, day):
        """The latest valid 3-month Treasury yield on or before day, as a fraction, or None."""
        row = self.db.execute('SELECT month3 FROM research.market_days WHERE day<=? AND month3 IS NOT NULL '
                              'ORDER BY day DESC LIMIT 1', (str(day),)).fetchone()
        return None if row is None else row[0] / 100

    def ten_year(self, day):
        row = ten_year(self.db, day)
        return None if row is None else row[1]

    def legacy_annual(self, symbol):
        if symbol not in self._annual:
            self._annual[symbol] = legacy_annual(self.db, symbol)
        return self._annual[symbol]
