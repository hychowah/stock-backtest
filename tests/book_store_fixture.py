"""Hand-built book store rows and research facts for selection tests, in private files.

`connection(path=None)` returns a daily-cache connection like `daily.connect()`:
the daily tables and the book store in an in-memory `main`, opened with URI
support, and a private research file (research.SCHEMA and facts.SCHEMA)
attached read-only by `daily.attach` as `research`. Its `research` attribute
is a writable autocommit connection to that file; research rows written there
are visible to the daily connection at once. Without a path the file lives in
a private folder that `close()` removes. Nothing touches the project's data
folder.

`company`, `price` and `session` write one research row each. `book` writes
one book through `book_store.store`, one pool at a time: `rows` maps each pool
to {symbol: columns}, `metrics` to {symbol: {metric: (multiple, yield)}} and
`values` to {symbol: {field: value}}. `record` writes the research identity
and the daily binding that a view reads at entry.

`Company` is the formula tests' company A: a private research file and a
daily cache per view. `state`, `statement` and `source` build its rows.
"""
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

from backtest.financial import rules
from backtest.inputs import book_store, daily, fact_view, facts, financial_inputs, research

ROW = ('candidate_rank', 'fiscal', 'known', 'entry', 'price', 'exit', 'market_cap', 'enterprise_value', 'ebitda',
       'ebitda_yield', 'ev_ebitda', 'spread', 'return_value', 'status')


class _Daily(sqlite3.Connection):
    """A daily connection that owns the writer of its attached research file."""

    def close(self):
        writer, folder = getattr(self, 'research', None), getattr(self, '_folder', None)
        super().close()
        if writer is not None:
            writer.close()
        if folder is not None:
            folder.cleanup()


def connection(path=None):
    folder = None
    if path is None:
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        path = Path(folder.name) / 'research.sqlite'
    writer = sqlite3.connect(path, isolation_level=None)
    # A private fixture file needs no durability.
    writer.execute('PRAGMA journal_mode=MEMORY')
    writer.execute('PRAGMA synchronous=OFF')
    writer.executescript(research.SCHEMA + facts.SCHEMA)
    db = sqlite3.connect(':memory:', uri=True, factory=_Daily)
    db.research, db._folder = writer, folder
    db.row_factory = sqlite3.Row
    db.executescript(daily.SCHEMA)
    daily.attach(db, path)
    return db


def record(research_db, daily_db, latest_date):
    """Write fixture values of the research identity (on research_db) and the daily binding (on daily_db)."""
    research_db.execute("INSERT INTO metadata VALUES('identity',?)", (json.dumps(dict(
        version=research.SCHEMA_VERSION, latest_date=latest_date, code='fixture', content='fixture')),))
    daily_db.execute("INSERT INTO metadata VALUES('daily_inputs',?)", (json.dumps(dict(
        version=daily.VERSION, research='fixture', books='fixture')),))


def company(db, symbol, *, name=None, exchange='NYSE', sector='Energy', listed=True):
    db.research.execute('INSERT INTO companies VALUES(?,?,?,?,?)', (symbol, name or symbol, exchange, sector, int(listed)))


def book(db, entry, exit_day=None, *, spy=None, candidates=0, pools=('legacy', 'cached'), rows=None, metrics=None,
         values=None):
    """Store one book with its pools through book_store.store in its own transaction; return its id."""
    rows, metrics, values = rows or {}, metrics or {}, values or {}
    with db:
        for pool in pools:
            book_id = book_store.store(db, dict(
                entry=entry, exit=exit_day, pool=pool, spy=spy, candidates=candidates,
                rows=[(symbol, *(columns.get(column) for column in ROW)) for symbol, columns in rows.get(pool, {}).items()],
                metrics=[(symbol, metric, *pair) for symbol, found in metrics.get(pool, {}).items()
                         for metric, pair in found.items()],
                filters=[(symbol, field, value) for symbol, found in values.get(pool, {}).items()
                         for field, value in found.items()]))
    return book_id


def price(db, symbol, day, adjusted):
    """One valid adjusted close; the company's price file counts as saved."""
    db.research.execute('INSERT INTO stock_days VALUES(?,?,?,?,?,?)', (symbol, day, adjusted, None, None, 'MISSING_INPUT'))
    db.research.execute('INSERT OR IGNORE INTO fact_sources VALUES(?,?,?,?)', (symbol, facts.STOCK, 'fixture', 'valid'))


def session(db, day, spy, month3=None, year10=None):
    """One valid SPY session with optional Treasury yields in percent."""
    db.research.execute('INSERT INTO market_days VALUES(?,?,?,?,?,?)',
                        (day, spy, month3, None if month3 is not None else 'MISSING_INPUT',
                         year10, None if year10 is not None else 'MISSING_INPUT'))


def state(value, reason=None):
    """A resolved field state: its value, or None with the reason."""
    return dict(value=value, valid=reason is None, reason=reason)


def statement(fiscal, *, earnings_yield=.3, market_cap=150e6, enterprise=180e6, ebitda=None):
    """One statements row: known rules.LAG days after fiscal; EBITDA is enterprise × yield unless given."""
    day = date.fromisoformat(fiscal)
    return dict(fiscal=fiscal, known=str(day + rules.LAG), market_cap=market_cap, enterprise_value=enterprise,
                ebitda=enterprise * earnings_yield if ebitda is None else ebitda, ebitda_yield=earnings_yield)


def source(endpoint):
    """The valid source of one endpoint; its digest is the SHA-256 of the endpoint name."""
    return dict(endpoint=endpoint, sha256=hashlib.sha256(endpoint.encode()).hexdigest(), disposition='valid')


class Company:
    """Company A in a private research file, and an in-memory daily cache that attaches it.

    Set the attributes, then call view(): it rewrites the research rows,
    opens a new daily cache and borrows a fact_view.View. Earlier views stay
    open until close(), which also removes the folder.
    - reports: statements rows (statement()); by default 30 June 2012-2014.
    - annual: endpoint, fiscal date and field to a resolved state; financials:
      legacy values by fiscal date, written as annual states over annual.
    - Prices of A are 10 at every report fiscal date, the root date and the
      latest date; with fill, on every calendar day from 7 days before the
      first of these dates to 7 days after the last. prices overrides days
      (None removes one); stock overrides whole stock-day states.
    - spy adds saved SPY sessions to the root and latest dates; treasury maps
      a day to its Treasury states (month3, year10).
    - books maps a pool to its stored latest book row (market_cap, metrics,
      filters); a pool without one is stored empty. population adds that many
      companies Z000... with a higher report yield; Z000-Z009 have no saved
      prices.
    - listed: whether A is listed; stale fails the view's freshness callback.
    """

    def __init__(self):
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = Path(self.folder.name) / 'research.sqlite'
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA synchronous=OFF')  # A private fixture file needs no durability.
        self.db.executescript(research.SCHEMA + facts.SCHEMA)
        self.daily = []
        self.root_date, self.latest_date = '2015-01-02', '2015-01-05'
        self.reports = [statement(f'{year}-06-30') for year in (2012, 2013, 2014)]
        self.annual = {'income-statement': {f'{year}-06-30': dict(revenue=state(100.), operatingIncome=state(income))
                                            for year, income in ((2012, -10.), (2013, 0.), (2014, 20.))}}
        self.financials, self.books = {}, {}
        self.fill, self.prices, self.stock = False, {}, {}
        self.spy, self.treasury = [], {}
        self.population, self.listed, self.stale = 0, True, False

    def close(self):
        for db in (*self.daily, self.db):
            db.close()
        self.daily = []
        self.folder.cleanup()

    def freshness(self):
        if self.stale:
            raise ValueError('Fixture inputs are stale.')

    def _prices(self):
        days = [date.fromisoformat(day) for day in (*(row['fiscal'] for row in self.reports), self.root_date, self.latest_date)]
        if self.fill:
            first, last = min(days) - timedelta(days=7), max(days) + timedelta(days=7)
            days = [first + timedelta(days=offset) for offset in range((last - first).days + 1)]
        prices = {str(day): 10. for day in days}
        prices.update(self.prices)
        return {day: price for day, price in prices.items() if price is not None}

    def view(self):
        db = self.db
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            db.execute('DELETE FROM ' + table)
        db.execute('INSERT INTO companies VALUES(?,?,?,?,?)', ('A', 'A', 'NYSE', 'Technology', int(self.listed)))
        db.executemany('INSERT INTO statements VALUES(?,?,?,?,?,?,?)', [
            ('A', row['fiscal'], row['known'], row['market_cap'], row['enterprise_value'], row['ebitda'],
             row['ebitda_yield']) for row in self.reports])
        # One value rule: valuation and market inputs read the same stock days.
        stock = {day: dict(adjClose=state(price), volume=state(None, 'MISSING_INPUT'))
                 for day, price in sorted(self._prices().items())}
        stock.update(self.stock)
        facts.store_stock(db, 'A', dict(source=source(facts.STOCK), dated=stock))
        annual = {endpoint: {fiscal: dict(fields) for fiscal, fields in dates.items()} for endpoint, dates in self.annual.items()}
        for fiscal, values in self.financials.items():
            for name, value in values.items():
                endpoint = next(endpoint for endpoint, names in financial_inputs.ENDPOINTS.items() if name in names)
                annual.setdefault(endpoint, {}).setdefault(fiscal, {})[name] = state(value)
        facts.store_annual(db, 'A', dict(annual=annual, sources={endpoint: source(endpoint) for endpoint in annual}))
        for index in range(self.population):
            symbol = f'Z{index:03d}'
            db.execute('INSERT INTO companies VALUES(?,?,?,?,?)', (symbol, symbol, 'NYSE', 'Energy', 1))
            db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',
                       (symbol, '2014-06-30', '2014-09-28', 150e6, 180e6, 162e6, .9))
            if index >= 10:
                facts.store_stock(db, symbol, dict(source=source(facts.STOCK), dated={
                    day: dict(adjClose=state(10.), volume=state(None, 'MISSING_INPUT')) for day in ('2014-06-30', '2015-01-02')}))
        # Admission needs saved SPY sessions at the root and latest dates.
        sessions = sorted({*self.spy, self.root_date, self.latest_date})
        facts.store_market(db, {facts.TREASURY: dict(source=source(facts.TREASURY), dated=self.treasury),
                                facts.CALENDAR: dict(source=source(facts.CALENDAR),
                                                     dated={day: dict(adjClose=state(100.)) for day in sessions})})
        cache = sqlite3.connect(':memory:', uri=True)
        cache.row_factory = sqlite3.Row
        self.daily.append(cache)
        cache.executescript(daily.SCHEMA)
        record(db, cache, self.latest_date)
        db.commit()
        daily.attach(cache, self.path)
        last = self.reports[-1]
        for pool in ('legacy', 'cached'):
            row = self.books.get(pool)
            book_store.store(cache, dict(entry=self.latest_date, exit=None, pool=pool, spy=None, candidates=1,
                rows=[] if row is None else [('A', 1, last['fiscal'], last['known'], self.latest_date, 10., None,
                                               row['market_cap'], 190e6, 54e6, .3, 3., .28, None, None)],
                metrics=[] if row is None else [('A', metric, *pair) for metric, pair in row['metrics'].items()],
                filters=[] if row is None else [('A', name, value) for name, value in row['filters'].items()]))
        cache.commit()
        return fact_view.View(cache, self.freshness, lambda: None)
