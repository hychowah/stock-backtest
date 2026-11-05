"""Typed prepared facts for custom-variable formulas.

Research preparation writes these tables in its build transaction, from the
same resolutions that give the observation meaning:
financial_inputs.resolve_history for annual statements and
dated_observation_inputs.resolve for saved stock, Treasury and SPY rows.

- stock_days: one row per company and saved price day, keyed by date.
- market_days: valid SPY sessions (spy) and saved Treasury days.
- annual_facts: one row per company, statement endpoint and fiscal date, with
  one value and one reason column per annual catalog field.
- fact_sources: the source file digest and disposition per company and
  endpoint; the empty symbol names the shared Treasury and SPY files.
- latest_admission: latest-root admission and its valuation per company and pool.

A field is valid when its value is present; otherwise its reason column names
the provider reason. A saved day or fiscal date always has a value or a reason
for each of its endpoint's fields. Value columns have no declared type, so
SQLite keeps the binary64 bits exactly, including -0.0, which a REAL column
stores as the integer 0. Prepared owner lanes are the stored January and latest
books (snapshots, screening_metrics, filter_values); they are read in place.

Readers borrow the caller's connection to the research database. The caller's
cache ownership keeps the rows unchanged while it reads.
"""
from datetime import date

from backtest.financial import books
from backtest.inputs import dated_observation_inputs as dated
from backtest.variables import parameters

MAX_HISTORY = 16384


def _annual_columns():
    """(column, endpoint, field) for every direct annual catalog parameter."""
    result = []
    for item in parameters.catalog(parameters.V3):
        if item['kind'] == 'direct' and item['id'].startswith('annual.'):
            result.append((item['id'].split('.', 1)[1], item['source']['endpoint'], item['source']['field']))
    return tuple(result)


ANNUAL = _annual_columns()
_BY_FIELD = {(endpoint, field): column for column, endpoint, field in ANNUAL}
STOCK_FIELDS = (('adjusted', 'adjClose'), ('volume', 'volume'))
TREASURY_FIELDS = (('month3', 'month3'), ('year10', 'year10'))

SCHEMA = '''
CREATE TABLE stock_days(symbol TEXT, day TEXT, adjusted, adjusted_reason TEXT, volume, volume_reason TEXT,
 PRIMARY KEY(symbol,day)) WITHOUT ROWID;
CREATE TABLE market_days(day TEXT PRIMARY KEY, spy, month3, month3_reason TEXT, year10, year10_reason TEXT) WITHOUT ROWID;
CREATE TABLE annual_facts(symbol TEXT, endpoint TEXT, fiscal TEXT, ''' + ', '.join(
    column + ', ' + column + '_reason TEXT' for column, _, _ in ANNUAL) + ''',
 PRIMARY KEY(symbol,endpoint,fiscal)) WITHOUT ROWID;
CREATE TABLE fact_sources(symbol TEXT, endpoint TEXT, sha256 TEXT, disposition TEXT NOT NULL,
 PRIMARY KEY(symbol,endpoint)) WITHOUT ROWID;
CREATE TABLE latest_admission(symbol TEXT, pool TEXT, admitted INTEGER NOT NULL, reason TEXT,
 candidate_rank INTEGER, fiscal TEXT, known TEXT, market_cap REAL, enterprise_value REAL, ebitda REAL,
 PRIMARY KEY(symbol,pool)) WITHOUT ROWID;
'''
TABLES = ('stock_days', 'market_days', 'annual_facts', 'fact_sources', 'latest_admission')


def _pair(state):
    """Return (value, reason) of one resolved field state."""
    return (state['value'], None) if state['valid'] else (None, state['reason'])


def _states(**pairs):
    """Field states from (value, reason) pairs; a field with neither has no state."""
    return {field: dict(value=value, valid=reason is None, reason=reason)
            for field, (value, reason) in pairs.items() if value is not None or reason is not None}


def _source(db, symbol, source):
    db.execute('INSERT INTO fact_sources VALUES(?,?,?,?)',
               (symbol, source['endpoint'], source['sha256'], source['disposition']))


# Writing, inside research preparation's build transaction.

def store_annual(db, symbol, resolution):
    """Write every resolved endpoint and fiscal date, including unavailable fields."""
    for endpoint, source in resolution['sources'].items():
        _source(db, symbol, source)
    rows = []
    for endpoint, dates in resolution['annual'].items():
        for fiscal, states in dates.items():
            values = {}
            for field, state in states.items():
                values[_BY_FIELD[endpoint, field]] = _pair(state)
            row = [symbol, endpoint, fiscal]
            for column, _, _ in ANNUAL:
                row.extend(values.get(column, (None, None)))
            rows.append(row)
    if rows:
        db.executemany('INSERT INTO annual_facts VALUES(' + ','.join('?' * len(rows[0])) + ')', rows)


def store_stock(db, symbol, resolution):
    """Write the saved days of one price file; resolution may cover only some days."""
    _source(db, symbol, resolution['source'])
    db.executemany('INSERT INTO stock_days VALUES(?,?,?,?,?,?)',
                   ((symbol, day, *_pair(states['adjClose']), *_pair(states['volume']))
                    for day, states in resolution['dated'].items()))


def copy_stock(db, schema, symbol, *, source, days=None):
    """Copy one company's stock days from an attached prior build.

    days excludes the days a caller writes from new rows; None copies every day.
    source also copies the price file's source row (equal file bytes).
    """
    if days:
        db.execute('CREATE TEMP TABLE IF NOT EXISTS new_days(day TEXT PRIMARY KEY) WITHOUT ROWID')
        db.execute('DELETE FROM temp.new_days')
        db.executemany('INSERT INTO temp.new_days VALUES(?)', ((day,) for day in days))
        db.execute(f'INSERT INTO stock_days SELECT * FROM {schema}.stock_days WHERE symbol=? '
                   'AND day NOT IN (SELECT day FROM temp.new_days)', (symbol,))
    else:
        db.execute(f'INSERT INTO stock_days SELECT * FROM {schema}.stock_days WHERE symbol=?', (symbol,))
    if source:
        db.execute(f'INSERT INTO fact_sources SELECT * FROM {schema}.fact_sources WHERE symbol=? AND endpoint=?',
                   (symbol, dated.STOCK))


def store_market(db, resolutions):
    """Write the shared Treasury and SPY calendar days and their sources."""
    treasury, calendar = resolutions[dated.TREASURY], resolutions[dated.CALENDAR]
    for resolution in (treasury, calendar):
        _source(db, '', resolution['source'])
    days = {}
    for day, states in calendar['dated'].items():
        if states['adjClose']['valid']:
            days[day] = [states['adjClose']['value'], None, None, None, None]
    for day, states in treasury['dated'].items():
        row = days.setdefault(day, [None, None, None, None, None])
        row[1:] = [*_pair(states['month3']), *_pair(states['year10'])]
    db.executemany('INSERT INTO market_days VALUES(?,?,?,?,?,?)', ((day, *row) for day, row in sorted(days.items())))


def store_latest(db, symbol, pool, evidence):
    """Record latest-root admission, including denials and their reasons."""
    statement, valuation = evidence['statement'] or {}, evidence['valuation'] or {}
    db.execute('INSERT INTO latest_admission VALUES(?,?,?,?,?,?,?,?,?,?)',
               (symbol, pool, int(evidence['admitted']), evidence['reason'], evidence['candidate_rank'],
                statement.get('fiscal'), statement.get('known'), valuation.get('market_cap'),
                valuation.get('enterprise_value'), valuation.get('ebitda')))


# Reading, on a borrowed research connection.

def reports(db, symbol, pool):
    """Return the company's accepted reports in fiscal order for one pool."""
    rows = []
    for record in db.execute('SELECT fiscal,known,market_cap,enterprise_value,ebitda,ebitda_yield FROM statements '
                             'WHERE symbol=? ORDER BY fiscal LIMIT ?', (symbol, MAX_HISTORY + 1)):
        fiscal, known, cap, ev, ebitda, earnings_yield = record
        rows.append(dict(fiscal=fiscal, known=known, market_cap=cap, enterprise_value=ev, ebitda=ebitda,
                         ebitda_yield=earnings_yield, enterprise=ev, **{'yield': earnings_yield}))
    if len(rows) > MAX_HISTORY:
        raise ValueError('Prepared observation history exceeds its bound.')
    return books.pools({symbol: rows})[1].get(symbol, []) if pool == 'legacy' else rows


def annual(db, symbol, endpoint, fields):
    """Return {fiscal: {field: state}} for every fiscal date of one endpoint.

    fields are source field names of that endpoint. Dates with no requested
    field are still returned: income-statement dates form the fiscal spine.
    """
    columns = [_BY_FIELD[endpoint, field] for field in fields]
    projection = ''.join(f',{column},{column}_reason' for column in columns)
    result = {}
    for row in db.execute(f'SELECT fiscal{projection} FROM annual_facts WHERE symbol=? AND endpoint=? '
                          'ORDER BY fiscal LIMIT ?', (symbol, endpoint, MAX_HISTORY + 1)):
        if len(result) == MAX_HISTORY:
            raise ValueError('Prepared observation history exceeds its bound.')
        result[row[0]] = _states(**{field: row[1 + 2 * i:3 + 2 * i] for i, field in enumerate(fields)})
    return result


def session(db, day, slack):
    """Return the latest valid SPY session on or before day within slack days, or None."""
    row = db.execute('SELECT day FROM market_days WHERE day<=? AND spy IS NOT NULL ORDER BY day DESC LIMIT 1',
                     (str(day),)).fetchone()
    if row is None:
        return None
    return row[0] if (day - date.fromisoformat(row[0])).days <= slack else None


def stock_day(db, symbol, day):
    """Return {'adjClose': state, 'volume': state} at one exact saved day, or None."""
    row = db.execute('SELECT adjusted,adjusted_reason,volume,volume_reason FROM stock_days WHERE symbol=? AND day=?',
                     (symbol, str(day))).fetchone()
    return None if row is None else _states(adjClose=row[0:2], volume=row[2:4])


def treasury(db, day):
    """Return (day, {'month3': state, 'year10': state}) of the latest saved Treasury day on or before day."""
    row = db.execute('SELECT day,month3,month3_reason,year10,year10_reason FROM market_days WHERE day<=? '
                     'AND (month3 IS NOT NULL OR month3_reason IS NOT NULL) ORDER BY day DESC LIMIT 1',
                     (str(day),)).fetchone()
    return None if row is None else (row[0], _states(month3=row[1:3], year10=row[3:5]))


def source(db, symbol, endpoint):
    """Return {endpoint, sha256, disposition} of one source file, or None."""
    row = db.execute('SELECT sha256,disposition FROM fact_sources WHERE symbol=? AND endpoint=?',
                     (symbol, endpoint)).fetchone()
    return None if row is None else dict(endpoint=endpoint, sha256=row[0], disposition=row[1])


def latest_admission(db, symbol, pool):
    """Return the prepared latest-root decision fields, or None for an unknown company."""
    row = db.execute('SELECT admitted,reason,candidate_rank,fiscal,known,market_cap,enterprise_value,ebitda '
                     'FROM latest_admission WHERE symbol=? AND pool=?', (symbol, pool)).fetchone()
    if row is None:
        return None
    admitted, reason, rank, fiscal, known, cap, ev, ebitda = row
    return dict(admitted=bool(admitted), reason=reason, candidate_rank=rank,
                statement=None if fiscal is None else dict(fiscal=fiscal, known=known),
                valuation=None if cap is None else dict(market_cap=cap, enterprise_value=ev, ebitda=ebitda))


def prepared_lanes(db, mode, pool, book, symbol):
    """Return one stored January or latest book row's owner values, or None when absent.

    The shape is the prepared measure context's: snapshot market cap, metric
    pairs and filter values. Latest books use year 0 in the metric tables.
    """
    if mode == 'latest':
        row = db.execute('SELECT market_cap FROM latest_snapshots WHERE pool=? AND symbol=?', (pool, symbol)).fetchone()
        year = 0
    else:
        row = db.execute('SELECT market_cap FROM snapshots WHERE pool=? AND year=? AND symbol=?',
                         (pool, book, symbol)).fetchone()
        year = book
    if row is None:
        return None
    key = (mode, pool, year, symbol)
    metrics = {metric: [multiple, value] for metric, multiple, value in db.execute(
        'SELECT metric,multiple,yield_value FROM screening_metrics WHERE mode=? AND pool=? AND year=? AND symbol=?', key)}
    filters = dict(db.execute('SELECT field,value FROM filter_values WHERE mode=? AND pool=? AND year=? AND symbol=?', key))
    return dict(snapshot=dict(market_cap=row[0]), metrics=metrics, filters=filters)
