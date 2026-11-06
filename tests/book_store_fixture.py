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
"""
import json
from pathlib import Path
import sqlite3
import tempfile

from backtest.inputs import book_store, daily, facts, research

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
