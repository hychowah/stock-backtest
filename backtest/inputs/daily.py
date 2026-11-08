"""Prepared daily storage: the book store; connections and transactions belong to callers.

A daily connection attaches the research database read-only as the schema
'research'. Facts, sessions and company names are read from there (facts and
book_store); the daily cache holds only the book store and its binding.

The daily binding (metadata 'daily_inputs') names what the books were computed
from: this cache's VERSION, the research content identity and the book
identity (research.code_identity('books')). binding() is its one reader;
connect() admits a cache whose binding equals the current one.
"""
from contextlib import closing
from datetime import date
from pathlib import Path
import json
import sqlite3
import time

from backtest.inputs import research as r
from backtest.runtime import cache_access as cache_access
from backtest.financial import books as financial_books
from backtest.runtime import backtest_control as backtest_control
from backtest.runtime import diagnostics
from backtest.inputs import facts
from backtest.inputs import book_store

DATABASE = r.ROOT/'data'/'schedules.sqlite'
VERSION = 12
SCHEMA = '''
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
''' + book_store.SCHEMA


def binding(db):
    """The saved daily binding of a daily connection (JSON text), or None."""
    row=db.execute("SELECT value FROM main.metadata WHERE key='daily_inputs'").fetchone()
    return None if row is None else row[0]


def current(db):
    """The daily binding of the current research record (attached as 'research') and book code."""
    return dict(version=VERSION,research=r.identity(db,'research')['content'],books=r.code_identity('books'))


def attach(db,source):
    """Attach the research database read-only as the schema 'research'."""
    db.execute('ATTACH DATABASE ? AS research',(Path(source).resolve().as_uri()+'?mode=ro',))


def connect(path=DATABASE,source=None):
    """A caller-owned daily connection with research attached, admitted once by its binding."""
    path,source=Path(path),Path(source or r.DATABASE)
    if not path.exists():
        raise ValueError('Daily cache missing. Run: python3 scripts/schedules.py prepare')
    if not source.exists():
        raise ValueError('Prepared database missing. Run: python3 scripts/research.py prepare')
    db=_open(path,source)
    db.row_factory=sqlite3.Row
    try:
        saved=binding(db)
        if saved is None or json.loads(saved)!=current(db):
            raise ValueError('Daily cache changed. Run: python3 scripts/schedules.py prepare')
    except Exception:
        db.close();raise
    return db


def _saved(path):
    """The saved binding of an existing cache, or None for a file that holds none.

    None means an old or foreign file: not a database, a damaged one, or one
    without a metadata table or a binding. Every other error, such as a
    locked database or an I/O failure, propagates and leaves the file alone.
    Read-write, like connect(): a book write interrupted by a crash leaves a
    hot journal that only a writable connection rolls back.
    """
    if not path.exists():
        return None
    try:
        with closing(sqlite3.connect(path,timeout=60)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone() is None:
                return None
            saved=binding(db)
    except sqlite3.DatabaseError as error:
        if getattr(error,'sqlite_errorcode',0)&0xff not in (sqlite3.SQLITE_NOTADB,sqlite3.SQLITE_CORRUPT):
            raise
        return None
    try:
        value=json.loads(saved) if saved is not None else None
    except ValueError:
        return None
    return value if isinstance(value,dict) else None


def _open(path,source):
    """A read-write connection to the cache at path with research attached; no binding check."""
    db=sqlite3.connect(path.resolve().as_uri(),uri=True,timeout=60)
    try:
        attach(db,source)
    except BaseException:
        db.close();raise
    return db


def _empty(path):
    """Replace the cache at path with an empty one of this VERSION: no binding, no book.

    The schema commits in one transaction, so an interruption leaves an empty
    file or this empty cache, never part of a schema.
    """
    # _saved has rolled back any hot journal; a stale journal must not meet the new file.
    # Versions before 11 built the cache in a temporary file; an interrupted build left it.
    for name in (path,path.with_name(path.name+'-journal'),path.with_name(path.name+'.building')):
        name.unlink(missing_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.executescript('BEGIN;'+SCHEMA+'COMMIT;')


@diagnostics.operation('prepare.daily')
@cache_access.exclusive
def prepare(path=DATABASE, source=r.DATABASE, *, progress=lambda **kw:None):
    """Prepare latest sheets; changed content or book code drops every cached sheet.

    Unchanged identities retain historical sheets. A changed binding replaces
    the disposable cache with an empty version-12 file, avoiding a journal as
    large as the old store. Failure after reset leaves an unbound cache.
    Research retains its separate atomic replacement and failure guarantees.
    """
    started=time.perf_counter()
    diagnostics.lap('admission')
    path=Path(path)
    # The public daily-cache command owns its prerequisite too. Users never
    # need to discover and run the dependency chain themselves.
    r.prepare(source,progress=progress)
    progress(kind='daily',completed=0,total=2)
    diagnostics.lap('research')
    # research.prepare has just inspected the raw files.
    raw=r.accepted_signature()
    path.parent.mkdir(parents=True,exist_ok=True)
    previous=_saved(path)
    if previous is None or previous.get('version')!=VERSION or previous.get('books')!=r.code_identity('books'):
        _empty(path)
        previous=None
    with closing(_open(path,source)) as db:
        latest=date.fromisoformat(r.identity(db,'research',prices=True)['latest_date'])
        inputs=current(db)
        if previous==inputs:
            progress(kind='daily',completed=2,total=2,reused=True)
            print('Daily cache already current; no sheet changed.')
            diagnostics.note(outcome='current');return
        stored=book_store.stored(db) if previous and previous.get('version')==VERSION else []
    diagnostics.note(books_previous=len(stored),books_kept=0)
    # All retained values must belong to this exact research/book generation.
    if previous is not None:_empty(path)
    db=_open(path,source)
    try:
        db.execute('BEGIN IMMEDIATE')
        db.execute("INSERT OR REPLACE INTO metadata VALUES('daily_inputs',?)",(json.dumps(inputs),))
        # Latest keeps its own listed/exact-session admission in both pools.
        book_facts=facts.BookFacts(db)
        for number,pool in enumerate(('legacy','cached'),1):
            book_store.store(db,financial_books.book(latest,pool,book_facts,backtest_control.checkpoint,latest=True))
            progress(kind='daily',completed=number,total=2)
        diagnostics.lap('latest_book')
        if inputs!=current(db) or raw!=r.signature():
            raise ValueError('Inputs changed during daily preparation; retry.')
        db.commit()
    except BaseException:
        db.rollback();raise
    finally:
        db.close()
    action='refreshed' if previous is not None else 'prepared'
    diagnostics.lap('commit')
    diagnostics.note(outcome=action,database_bytes=path.stat().st_size)
    print(f'Daily cache {path.stat().st_size/1e6:.1f} MB {action} in {time.perf_counter()-started:.1f}s',flush=True)
