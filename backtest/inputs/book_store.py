"""Compact entry sheets in the daily cache; one owner for their schema and reads.

Historical sheets share an entry across every exit. Latest uses a separate
header because its listed/exact-session admission differs. Pool completion
commits with the rows, including empty pools. A book id is an operation-local
handle; saved owner_scope labels never look up a future cache generation.
Stored owner numbers retain REAL rounding and zero normalization. Typed
research facts and formula outputs keep their existing signed-zero semantics.
"""
from backtest.financial import metrics as catalog

METRICS = {key: (f'm_{key}_multiple', f'm_{key}_yield') for key in catalog.METRICS}
FILTERS = {key: f'f_{key}' for key in catalog.FILTERS}
LANES = tuple(column for pair in METRICS.values() for column in pair) + tuple(FILTERS.values())
SCHEMA = """
CREATE TABLE books(book INTEGER PRIMARY KEY, entry TEXT NOT NULL, latest INTEGER NOT NULL CHECK(latest IN (0,1)),
 candidates INTEGER NOT NULL, market TEXT NOT NULL DEFAULT 'us', UNIQUE(market,entry,latest));
CREATE TABLE book_pools(book INTEGER REFERENCES books(book), pool TEXT CHECK(pool IN ('cached','legacy')),
 PRIMARY KEY(book,pool)) WITHOUT ROWID;
CREATE TABLE book_rows(book INTEGER, pool TEXT, symbol TEXT, candidate_rank INTEGER, fiscal TEXT, known TEXT,
 entry TEXT, price REAL, market_cap REAL, enterprise_value REAL, ebitda REAL, ebitda_yield REAL,
 ev_ebitda REAL, spread REAL,""" + ','.join(column + ' REAL' for column in LANES) + """,
 PRIMARY KEY(book,pool,symbol)) WITHOUT ROWID;
"""
TABLES = ('books', 'book_pools', 'book_rows')
ROWS = TABLES[2]
DATED = ('pool', 'symbol', 'candidate_rank', 'fiscal', 'entry', 'price', 'market_cap', 'enterprise_value', 'ebitda',
         'ebitda_yield', 'ev_ebitda', 'spread')
LATEST = ('pool', 'symbol', 'candidate_rank', 'fiscal', 'known', 'price_date', 'price', 'market_cap',
          'enterprise_value', 'ebitda_yield', 'ev_ebitda', 'spread')


def store(db, book, *, symbols=None):
    """Write a complete sheet or replace its dirty symbols; return its handle."""
    market=book.get('market','us')
    row = db.execute('SELECT book FROM books WHERE entry=? AND latest=? AND market=?', (book['entry'], book['latest'],market)).fetchone()
    book_id = row[0] if row is not None else db.execute(
        'INSERT INTO books(entry,latest,candidates,market) VALUES(?,?,?,?)',
        (book['entry'], book['latest'], book['candidates'],market)).lastrowid
    pool = book['pool']
    if symbols is not None:
        db.executemany('DELETE FROM book_rows WHERE book=? AND pool=? AND symbol=?',
                       ((book_id,pool,symbol) for symbol in symbols))
        db.execute('UPDATE books SET candidates=? WHERE book=?',(book['candidates'],book_id))
    values = {row[0]: {} for row in book['rows']}
    for symbol, metric, multiple, value in book['metrics']:
        a, b = METRICS[metric]
        values[symbol].update({a: multiple, b: value})
    for symbol, field, value in book['filters']:
        values[symbol][FILTERS[field]] = value
    db.executemany('INSERT INTO book_rows VALUES(' + ','.join('?' * (14 + len(LANES))) + ')',
        ((book_id, pool, *row, *(values[row[0]].get(column) for column in LANES)) for row in book['rows']))
    if symbols is None:db.execute('INSERT INTO book_pools VALUES(?,?)', (book_id, pool))
    return book_id


def refresh_ranks(db, book, pool, ranks):
    """Refresh whole-pool tie metadata without repeating price calculations."""
    previous=dict(db.execute('SELECT symbol,candidate_rank FROM book_rows WHERE book=? AND pool=? AND candidate_rank IS NOT NULL',(book,pool)))
    db.executemany('UPDATE book_rows SET candidate_rank=? WHERE book=? AND pool=? AND symbol=?',
                   ((ranks.get(symbol),book,pool,symbol) for symbol in previous.keys()|ranks.keys()
                    if previous.get(symbol)!=ranks.get(symbol)))


def remove(db, book, pool=None):
    """Remove one complete pool or header; all its derived rows share the transaction."""
    where='book=?'+(' AND pool=?' if pool is not None else '')
    args=(book,pool) if pool is not None else (book,)
    db.execute('DELETE FROM book_rows WHERE '+where,args)
    db.execute('DELETE FROM book_pools WHERE '+where,args)
    db.execute('DELETE FROM books WHERE book=? AND NOT EXISTS (SELECT 1 FROM book_pools WHERE book=?)',(book,book))


def stored(db, market='us'):
    """[(book, entry, latest)] of stored headers, by handle."""
    return [tuple(row) for row in db.execute('SELECT book,entry,latest FROM books WHERE market=? ORDER BY book',(market,))]


def record(db, book):
    """Entry policy and candidate count for a stored header, or None."""
    row = db.execute('SELECT entry,latest,candidates,market FROM books WHERE book=?', (book,)).fetchone()
    return None if row is None else dict(zip(('entry', 'latest', 'candidates','market'), row))


def open_book(db, market='us'):
    """Require the one latest header; its pools keep the existing shared handle."""
    found = db.execute('SELECT book FROM books WHERE latest=1 AND market=? LIMIT 2',(market,)).fetchall()
    if not found:
        raise ValueError('The latest book is missing. Run: python3 scripts/schedules.py prepare')
    if len(found) > 1:
        raise ValueError('The book store holds more than one open book. Run: python3 scripts/schedules.py prepare')
    return found[0][0]


def completed(db, pool, market='us'):
    """[(book, entry, latest)] of complete pool sheets, including empty sheets."""
    return [tuple(row) for row in db.execute(
        'SELECT b.book,b.entry,b.latest FROM books b JOIN book_pools p ON p.book=b.book WHERE p.pool=? AND b.market=? ORDER BY b.book', (pool,market))]


def find(db, entry, pool, *, latest=False, market='us'):
    """The complete entry/pool handle under historical or latest policy, or None."""
    row = db.execute('SELECT b.book FROM books b JOIN book_pools p ON p.book=b.book WHERE b.entry=? AND b.latest=? AND p.pool=? AND b.market=?',
                     (str(entry), latest, pool, market)).fetchone()
    return None if row is None else row[0]


def require_scope(db, book, pool, day, open_book,market='us'):
    """Check a prepared scope's entry, policy and pool completion once."""
    found = record(db, book) if type(book) is int else None
    if (found is None or found['entry'] != str(day) or bool(found['latest']) != open_book
            or find(db, day, pool, latest=open_book,market=market) != book):
        raise ValueError('The prepared scope is not a complete stored book.')


def columns(db, book):
    """The stored entry columns (alias s), with latest price_date projection."""
    found = record(db, book)
    if found is None:
        raise ValueError('The book is not stored.')
    return ','.join('s.entry AS price_date' if name == 'price_date' else 's.' + name
                    for name in (LATEST if found['latest'] else DATED))


def rows(db, book, pool, symbols=None):
    """Bounded full entry rows; dated returns are added only after selection."""
    named = '' if symbols is None else f' AND s.symbol IN ({",".join("?" * len(symbols))})'
    cursor = db.execute(f'SELECT {columns(db, book)},c.name,c.sector,c.exchange,c.symbol AS _company '
                        f'FROM book_rows s LEFT JOIN research.companies c USING(symbol) WHERE s.book=? AND s.pool=?{named} '
                        'ORDER BY s.symbol', (book, pool, *(symbols or ())))
    names = [item[0] for item in cursor.description]
    for row in cursor:
        detached = dict(zip(names, row))
        if detached.pop('_company') is None:
            raise ValueError('A stored book row has no saved company.')
        yield detached


def scope(db, book, pool, limit, exit_day=None):
    """Selection rows, restricted to actual entries before exit, before the ceiling."""
    window = '' if exit_day is None else ' AND s.entry<?'
    found = db.execute('SELECT c.symbol,s.candidate_rank,s.fiscal,s.known,s.market_cap,s.enterprise_value,s.ebitda,'
                       'c.sector,c.exchange FROM book_rows s LEFT JOIN research.companies c USING(symbol) '
                       'WHERE s.book=? AND s.pool=?' + window + ' ORDER BY s.symbol LIMIT ?',
                       (book, pool, *((str(exit_day),) if exit_day is not None else ()), limit)).fetchall()
    if any(row[0] is None for row in found):
        raise ValueError('A stored book row has no saved company.')
    return found


def lanes(db, book, pool, metrics=None, fields=None):
    """Read requested stored owner lanes once; NULL remains absent, never recalculated."""
    metrics = tuple(METRICS) if metrics is None else tuple(sorted(set(metrics)))
    fields = tuple(FILTERS) if fields is None else tuple(sorted(set(fields)))
    pairs, values = {metric: ({}, {}) for metric in metrics}, {field: {} for field in fields}
    names = [column for metric in metrics for column in METRICS[metric]] + [FILTERS[field] for field in fields]
    if names:
        for row in db.execute('SELECT symbol,' + ','.join(names) + ' FROM book_rows WHERE book=? AND pool=? ORDER BY symbol', (book, pool)):
            symbol, *numbers = row
            for i, metric in enumerate(metrics):
                multiple, value = numbers[2*i:2*i+2]
                if multiple is not None and value is not None:
                    pairs[metric][0][symbol], pairs[metric][1][symbol] = multiple, value
            for field, value in zip(fields, numbers[2*len(metrics):]):
                if value is not None:
                    values[field][symbol] = value
    return dict(sorted(pairs.items())), dict(sorted(values.items()))


def market_caps(db, book, pool):
    """Stored entry caps for owner contexts; no fallback."""
    return dict(db.execute('SELECT symbol,market_cap FROM book_rows WHERE book=? AND pool=?', (book, pool)))


def counts(db):
    """Header, pool-completion and compact-row counts."""
    return {table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in TABLES}
