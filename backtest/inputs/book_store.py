"""The book store: one row shape, one writer and every read of its tables.

The tables live in the daily cache (schedules.sqlite). A book id names one
entry and exit; the open (latest) book has no exit and is the book at the
research database's latest date. Latest and dated books share one book-id
space. An id is a handle, not a durable name: it names one book only while
the cache keeps that book, and delete() lets SQLite reuse the highest ids
(INTEGER PRIMARY KEY without AUTOINCREMENT). A recorded owner_scope book is
therefore a label, never a lookup key outside the operation or coverage
generation that produced it. book_pools marks each completed pool. A book
records its SPY return and candidates, the number of cached-pool reports of
its entry day (for the latest book, the eligible financials that the latest
screen reports). The book
identity (research.code_identity('books')) binds this module, so an edit to
the schema, the writer or a reader here drops every saved book.

Writers: store() and delete() (daily preparation drops the books that the
change-day rule, books.kept, does not keep). Readers: stored(), record(),
open_book(), completed(), find(), rows(), lanes(), require_scope() and
counts(). A book's rows keep the row shape that results
and the website keep, chosen by the book itself: LATEST for the open book (the
old research latest snapshot) and DATED otherwise (the old daily snapshot).
screening.select is the one SQL consumer outside this module; it takes the
table names (ROWS, METRICS, FILTERS) and columns() from here. A daily
connection attaches the research database as the schema 'research', which
supplies the company names.
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
ROWS, METRICS, FILTERS = TABLES[2:]
# The row shapes that holdings, latest screens and the website keep: column
# names in order; a latest row names its entry day price_date.
DATED = ('pool', 'symbol', 'candidate_rank', 'fiscal', 'entry', 'exit', 'market_cap', 'enterprise_value', 'ebitda',
         'ebitda_yield', 'ev_ebitda', 'spread', 'return_value', 'status')
LATEST = ('pool', 'symbol', 'candidate_rank', 'fiscal', 'known', 'price_date', 'price', 'market_cap',
          'enterprise_value', 'ebitda_yield', 'ev_ebitda', 'spread')


def store(db, book):
    """Write one pool of books.book() in the caller's transaction; return its book id.

    The pool's rows and its book_pools marker commit together; an empty pool is
    complete too. The pools of one entry and exit share one book id. A pool
    that is already complete is not written again. There is at most one open
    book: its entry is research's latest date.
    """
    completed = find(db, book['entry'], book['exit'], book['pool'])
    if completed is not None:
        return completed
    row = db.execute('SELECT book FROM books WHERE entry=? AND exit IS ?', (book['entry'], book['exit'])).fetchone()
    if row is None and book['exit'] is None and db.execute('SELECT 1 FROM books WHERE exit IS NULL').fetchone():
        raise ValueError('The book store already holds an open book.')
    book_id = row[0] if row is not None else db.execute(
        'INSERT INTO books(entry,exit,spy,candidates) VALUES(?,?,?,?)',
        (book['entry'], book['exit'], book['spy'], book['candidates'])).lastrowid
    pool = book['pool']
    db.executemany('INSERT INTO book_rows VALUES(' + ','.join('?' * 17) + ')', ((book_id, pool, *row) for row in book['rows']))
    db.executemany('INSERT INTO book_metrics VALUES(?,?,?,?,?,?)', ((book_id, pool, *row) for row in book['metrics']))
    db.executemany('INSERT INTO book_filters VALUES(?,?,?,?,?)', ((book_id, pool, *row) for row in book['filters']))
    db.execute('INSERT INTO book_pools VALUES(?,?)', (book_id, pool))
    return book_id


def delete(db, books):
    """Delete the given book ids from every table, in the caller's transaction."""
    db.execute('CREATE TEMP TABLE dropped_books(book INTEGER PRIMARY KEY)')
    try:
        db.executemany('INSERT INTO temp.dropped_books VALUES(?)', ((book,) for book in books))
        for table in reversed(TABLES):
            db.execute(f'DELETE FROM main.{table} WHERE book IN (SELECT book FROM temp.dropped_books)')
    finally:
        db.execute('DROP TABLE temp.dropped_books')


def stored(db):
    """[(book, entry, exit)] of every stored book, by book id; exit None is the open book."""
    return [tuple(row) for row in db.execute('SELECT book,entry,exit FROM books ORDER BY book')]


def record(db, book):
    """dict(entry, exit, spy, candidates) of a stored book, or None; exit None is the open book."""
    row = db.execute('SELECT entry,exit,spy,candidates FROM books WHERE book=?', (book,)).fetchone()
    return None if row is None else dict(zip(('entry', 'exit', 'spy', 'candidates'), row))


def open_book(db):
    """The id of the open (latest) book that daily preparation wrote: the one book without an exit."""
    found = db.execute('SELECT book FROM books WHERE exit IS NULL LIMIT 2').fetchall()
    if not found:
        raise ValueError('The latest book is missing. Run: python3 scripts/schedules.py prepare')
    if len(found) > 1:
        raise ValueError('The book store holds more than one open book. Run: python3 scripts/schedules.py prepare')
    return found[0][0]


def completed(db, pool):
    """[(book, entry, exit)] of every stored book whose pool is complete, by book id; exit None is the open book."""
    return [tuple(row) for row in db.execute(
        'SELECT b.book,b.entry,b.exit FROM books b JOIN book_pools p ON p.book=b.book WHERE p.pool=? ORDER BY b.book', (pool,))]


def find(db, entry, exit_day, pool):
    """The book id of a completed pool, or None; exit_day None names the open book."""
    row = db.execute('SELECT b.book FROM books b JOIN book_pools p ON p.book=b.book WHERE b.entry=? AND b.exit IS ? AND p.pool=?',
                     (str(entry), None if exit_day is None else str(exit_day), pool)).fetchone()
    return None if row is None else row[0]


def require_scope(db, book, pool, day, open_book):
    """The one check of a prepared scope: book's pool is complete, entered on day, and is the open book when open_book.

    Raise ValueError otherwise.
    """
    found = record(db, book) if type(book) is int else None
    if (found is None or found['entry'] != str(day) or (found['exit'] is None) != open_book
            or find(db, found['entry'], found['exit'], pool) != book):
        raise ValueError('The prepared scope is not a complete stored book.')


def columns(db, book):
    """The SQL column list of a stored book's rows (alias s) in its row shape: LATEST for the open book, DATED otherwise."""
    found = record(db, book)
    if found is None:
        raise ValueError('The book is not stored.')
    return ','.join('s.entry AS price_date' if name == 'price_date' else 's.' + name
                    for name in (LATEST if found['exit'] is None else DATED))


def rows(db, book, pool):
    """Yield the rows of one book pool in symbol order: dicts in the book's row shape plus name, sector and exchange.

    A caller may stop early, which bounds the read. A row whose company is not
    a saved research company fails.
    """
    cursor = db.execute(f'SELECT {columns(db, book)},c.name,c.sector,c.exchange,c.symbol AS _company '
                        'FROM book_rows s LEFT JOIN research.companies c USING(symbol) WHERE s.book=? AND s.pool=? '
                        'ORDER BY s.symbol', (book, pool))
    names = [item[0] for item in cursor.description]
    for row in cursor:
        detached = dict(zip(names, row))
        if detached.pop('_company') is None:
            raise ValueError('A stored book row has no saved company.')
        yield detached


def lanes(db, book, pool, metrics=None, fields=None):
    """The stored ranking pairs and filter values of one book pool: one read per table.

    Return (pairs, values): pairs {symbol: {metric: (multiple, yield)}} and
    values {symbol: {field: value}}. metrics and fields name what to read;
    None reads every metric or field, and an empty sequence reads nothing.
    """
    pairs, values = {}, {}
    if metrics is None or metrics:
        for symbol, metric, multiple, value in _read(db, METRICS, 'metric', 'multiple,yield_value', book, pool, metrics):
            pairs.setdefault(symbol, {})[metric] = multiple, value
    if fields is None or fields:
        for symbol, field, value in _read(db, FILTERS, 'field', 'value', book, pool, fields):
            values.setdefault(symbol, {})[field] = value
    return pairs, values


def _read(db, table, key, columns, book, pool, names):
    """The (symbol, key, columns) rows of one book pool, of the named keys (None: every key)."""
    names = () if names is None else tuple(sorted(set(names)))
    condition = f' AND {key} IN ({",".join("?" * len(names))})' if names else ''
    return db.execute(f'SELECT symbol,{key},{columns} FROM {table} WHERE book=? AND pool=?{condition}', (book, pool, *names))


def counts(db):
    """{table: rows} of the books, completed pools and book rows."""
    return {table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in TABLES[:3]}
