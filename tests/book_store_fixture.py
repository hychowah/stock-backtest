"""Hand-built book store rows and research facts for selection tests, on one private connection.

`connection(path=None)` returns a daily-cache connection like `daily.connect()`:
the book store and the daily tables in an in-memory `main`, and the research
tables and typed facts in an attached schema named `research`. With a path, that
schema is a writable research file which a second connection (a view's research
connection) can read after a commit; otherwise it is in memory. Nothing touches
the project's data folder. `company`, `book`, `row`, `metric`, `value`, `price`
and `session` insert one row each.
"""
import sqlite3

from backtest.inputs import daily, facts, research

ROW = ('candidate_rank', 'fiscal', 'known', 'entry', 'price', 'exit', 'market_cap', 'enterprise_value', 'ebitda',
       'ebitda_yield', 'ev_ebitda', 'spread', 'return_value', 'status')


def connection(path=None):
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript(daily.SCHEMA)
    db.execute('ATTACH DATABASE ? AS research', (':memory:' if path is None else str(path),))
    # A private fixture file needs no durability.
    db.execute('PRAGMA research.synchronous=OFF')
    db.executescript((research.SCHEMA + facts.SCHEMA).replace('CREATE TABLE ', 'CREATE TABLE research.'))
    return db


def company(db, symbol, *, name=None, exchange='NYSE', sector='Energy', listed=True):
    db.execute('INSERT INTO research.companies VALUES(?,?,?,?,?)', (symbol, name or symbol, exchange, sector, int(listed)))


def book(db, entry, exit_day=None, *, spy=None, candidates=0, pools=('legacy', 'cached')):
    """Insert one complete book with its pools; return its id."""
    book_id = db.execute('INSERT INTO books(entry,exit,spy,candidates) VALUES(?,?,?,?)',
                         (entry, exit_day, spy, candidates)).lastrowid
    db.executemany('INSERT INTO book_pools VALUES(?,?)', [(book_id, pool) for pool in pools])
    return book_id


def row(db, book_id, pool, symbol, **values):
    """Insert one book row; omitted columns are NULL."""
    db.execute('INSERT INTO book_rows VALUES(' + ','.join('?' * 17) + ')',
               (book_id, pool, symbol, *(values.get(column) for column in ROW)))


def metric(db, book_id, pool, symbol, name, multiple, yield_value):
    db.execute('INSERT INTO book_metrics VALUES(?,?,?,?,?,?)', (book_id, pool, symbol, name, multiple, yield_value))


def value(db, book_id, pool, symbol, field, number):
    db.execute('INSERT INTO book_filters VALUES(?,?,?,?,?)', (book_id, pool, symbol, field, number))


def price(db, symbol, day, adjusted):
    """One valid adjusted close; the company's price file counts as saved."""
    db.execute('INSERT INTO research.stock_days VALUES(?,?,?,?,?,?)', (symbol, day, adjusted, None, None, 'MISSING_INPUT'))
    db.execute('INSERT OR IGNORE INTO research.fact_sources VALUES(?,?,?,?)', (symbol, facts.STOCK, 'fixture', 'valid'))


def session(db, day, spy, month3=None, year10=None):
    """One valid SPY session with optional Treasury yields in percent."""
    db.execute('INSERT INTO research.market_days VALUES(?,?,?,?,?,?)',
               (day, spy, month3, None if month3 is not None else 'MISSING_INPUT',
                year10, None if year10 is not None else 'MISSING_INPUT'))
