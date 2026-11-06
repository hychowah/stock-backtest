"""The book store: one row shape and one writer for latest and dated books.

The tables live in the daily cache (schedules.sqlite). A book id names one
entry and exit; the open (latest) book has no exit and is the book at the
research database's latest date. book_pools marks each completed pool. A book
records its SPY return and candidates, the number of cached-pool reports of
its entry day (for the latest book, the eligible financials that the latest
screen reports). daily.VERSION covers this schema and writer.

Today the daily cache writes only the latest book here; the readers still read
latest_snapshots in research and the dated periods and snapshots of the daily
cache (typed-storage P3b switches them and adds the reader here).
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


def store(db, book):
    """Write one pool of books.book() in the caller's transaction; return its book id.

    The pool's rows and its book_pools marker commit together; an empty pool is
    complete too. The pools of one entry and exit share one book id.
    """
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
