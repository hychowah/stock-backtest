"""The book store: one row shape, one writer and the readers of latest and dated books.

The tables live in the daily cache (schedules.sqlite). A book id names one
entry and exit; the open (latest) book has no exit and is the book at the
research database's latest date. Latest and dated books share one book-id
space. book_pools marks each completed pool. A book records its SPY return and
candidates, the number of cached-pool reports of its entry day (for the latest
book, the eligible financials that the latest screen reports). daily.VERSION
covers this schema and writer.

Readers select a book's rows in the row shape that results and the website
keep (DATED and LATEST below): a dated row is the old daily snapshot, a latest
row the old research latest snapshot. A daily connection attaches the research
database as the schema 'research', which supplies the company names.
"""

SCHEMA = '''
CREATE TABLE books(book INTEGER PRIMARY KEY, entry TEXT NOT NULL, exit TEXT, spy REAL, candidates INTEGER NOT NULL);
CREATE UNIQUE INDEX book_dates ON books(entry,exit);
CREATE TABLE book_pools(book INTEGER REFERENCES books(book), pool TEXT CHECK(pool IN ('cached','legacy')),
 PRIMARY KEY(book,pool)) WITHOUT ROWID;
CREATE TABLE book_rows(book INTEGER, pool TEXT, symbol TEXT, candidate_rank INTEGER, fiscal TEXT, known TEXT,
 entry TEXT, price REAL, exit TEXT, market_cap REAL, enterprise_value REAL, ebitda REAL, ebitda_yield REAL,
 ev_ebitda REAL, spread REAL, return_value REAL, status TEXT, PRIMARY KEY(book,pool,symbol)) WITHOUT ROWID;
CREATE TABLE book_metrics(book INTEGER, pool TEXT, symbol TEXT, metric TEXT, multiple REAL NOT NULL,
 yield_value REAL NOT NULL, PRIMARY KEY(book,pool,symbol,metric)) WITHOUT ROWID;
CREATE TABLE book_filters(book INTEGER, pool TEXT, symbol TEXT, field TEXT, value REAL NOT NULL,
 PRIMARY KEY(book,pool,symbol,field)) WITHOUT ROWID;
'''
TABLES = ('books', 'book_pools', 'book_rows', 'book_metrics', 'book_filters')
# The row shapes that holdings, latest screens and the website keep.
DATED = ('pool', 'symbol', 'candidate_rank', 'fiscal', 'entry', 'exit', 'market_cap', 'enterprise_value', 'ebitda',
         'ebitda_yield', 'ev_ebitda', 'spread', 'return_value', 'status')
LATEST = ('pool', 'symbol', 'candidate_rank', 'fiscal', 'known', 'entry AS price_date', 'price', 'market_cap',
          'enterprise_value', 'ebitda_yield', 'ev_ebitda', 'spread')


def store(db, book):
    """Write one pool of books.book() in the caller's transaction; return its book id.

    The pool's rows and its book_pools marker commit together; an empty pool is
    complete too. The pools of one entry and exit share one book id. A pool
    that is already complete is not written again.
    """
    completed = find(db, book['entry'], book['exit'], book['pool'])
    if completed is not None:
        return completed
    row = db.execute('SELECT book FROM books WHERE entry=? AND exit IS ?', (book['entry'], book['exit'])).fetchone()
    book_id = row[0] if row is not None else db.execute(
        'INSERT INTO books(entry,exit,spy,candidates) VALUES(?,?,?,?)',
        (book['entry'], book['exit'], book['spy'], book['candidates'])).lastrowid
    pool = book['pool']
    db.executemany('INSERT INTO book_rows VALUES(' + ','.join('?' * 17) + ')', ((book_id, pool, *row) for row in book['rows']))
    db.executemany('INSERT INTO book_metrics VALUES(?,?,?,?,?,?)', ((book_id, pool, *row) for row in book['metrics']))
    db.executemany('INSERT INTO book_filters VALUES(?,?,?,?,?)', ((book_id, pool, *row) for row in book['filters']))
    db.execute('INSERT INTO book_pools VALUES(?,?)', (book_id, pool))
    return book_id


def find(db, entry, exit_day, pool):
    """The book id of a completed pool, or None; exit_day None names the latest book."""
    row = db.execute('SELECT b.book FROM books b JOIN book_pools p ON p.book=b.book WHERE b.entry=? AND b.exit IS ? AND p.pool=?',
                     (str(entry), None if exit_day is None else str(exit_day), pool)).fetchone()
    return None if row is None else row[0]


def latest(db):
    """(book id, entry day) of the latest book that daily preparation wrote."""
    row = db.execute('SELECT book,entry FROM books WHERE exit IS NULL').fetchone()
    if row is None:
        raise ValueError('The latest book is missing. Run: python3 scripts/schedules.py prepare')
    return row[0], row[1]


def projection(open_book, alias='s'):
    """The SQL column list of a book's rows in the kept row shape (LATEST or DATED)."""
    return ','.join(alias + '.' + column for column in (LATEST if open_book else DATED))
