"""Prepared daily storage: the book store; connections and transactions belong to callers.

A daily connection attaches the research database read-only as the schema
'research'. Books, sessions and company names are read from there (facts and
book_store); the daily cache keeps only the books and what its kept-book check
compares.
"""
from contextlib import closing
from datetime import date
import hashlib
from pathlib import Path
import json
import sqlite3
import time

from backtest.inputs import research as r
from backtest.runtime import cache_access as cache_access
from backtest.financial import books as financial_books
from backtest.runtime import backtest_control as backtest_control
from backtest.runtime import diagnostics
from backtest import calendar as schedule_calendar
from backtest import portfolio_results as portfolio_results
from backtest.inputs import market
from backtest.inputs import facts
from backtest.inputs import book_store
from backtest.financial import rules

DATABASE = r.ROOT/'data'/'schedules.sqlite'
VERSION = 9
# The book store (book_store.SCHEMA) holds the latest and dated books. The
# daily price, session and Treasury rows and the copied 10-year yields are
# read only by the kept-book check of a refresh (_prices, _dated_change).
SCHEMA = '''
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE prices(symbol TEXT, day TEXT, adjusted REAL NOT NULL, PRIMARY KEY(symbol,day)) WITHOUT ROWID;
CREATE TABLE sessions(day TEXT PRIMARY KEY, price REAL) WITHOUT ROWID;
CREATE TABLE treasuries(day TEXT PRIMARY KEY, yield_value REAL) WITHOUT ROWID;
CREATE TABLE treasury10 (day TEXT PRIMARY KEY, yield_percent REAL NOT NULL) WITHOUT ROWID;
''' + book_store.SCHEMA


# The research tables whose rows every dated book reads; a change drops every book.
BOOK_INPUTS = ('companies','statements','financial_inputs')
PRICE_SOURCES = (Path(__file__),Path(r.__file__),Path(facts.__file__),Path(rules.__file__),Path(market.__file__))


def _engine_sources():
    return [Path(__file__),Path(__file__).parents[1]/'engines'/'original'/'schedules.py',
            Path(__file__).parents[1]/'engines'/'original'/'book_batch.py',
            Path(schedule_calendar.__file__),Path(portfolio_results.__file__)]


def fingerprint(source=None, *, accepted=False):
    # Daily prices bind to the validated research price inventory. Changed
    # prepared inputs refresh prices/books. Prepared rows are identified by
    # their recorded metadata, not rescanned. Preparation inspects raw inputs
    # afresh; readers compare the accepted signature.
    prices,prepared=r.prepared_bindings(source or r.DATABASE)
    return dict(version=VERSION, facts_version=facts.VERSION,
                inputs=r.accepted_signature() if accepted else r.signature(),prices=prices,facts=prepared,
                engine={p.relative_to(r.ROOT).as_posix() if p.is_relative_to(r.ROOT) else p.name:[p.stat().st_size,p.stat().st_mtime_ns] for p in _engine_sources()})


def attach(db,source):
    """Attach the research database read-only as the schema 'research'."""
    db.execute('ATTACH DATABASE ? AS research',(Path(source).resolve().as_uri()+'?mode=ro',))


def connect(path=DATABASE,source=None):
    # The returned connection is caller-owned. It attaches the research
    # database that the saved fingerprint binds.
    path=Path(path)
    if not path.exists():
        raise ValueError('Daily cache missing. Run: python3 scripts/schedules.py prepare')
    db=sqlite3.connect(path.resolve().as_uri(),uri=True,timeout=60)
    db.row_factory=sqlite3.Row
    try:
        saved=json.loads(db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()[0])
        if saved!=fingerprint(source, accepted=True):
            raise ValueError('Daily cache changed. Run: python3 scripts/schedules.py prepare')
        attach(db,source or r.DATABASE)
    except Exception:
        db.close();raise
    return db


def _price_rows(payload):
    """Return the (day, adjusted close) rows of one saved company file: its valid values (facts.observe)."""
    rows=payload.get('div') if isinstance(payload,dict) else None
    if not isinstance(rows,list):
        raise ValueError('A saved price file is unreadable. Use the data panel to download it again.')
    return [(day,states['adjClose']['value']) for day,states in sorted(facts.observe(rows,('adjClose',)).items())
            if states['adjClose']['valid']]


def _digest(value):
    return hashlib.sha256(json.dumps(value,separators=(',',':')).encode()).hexdigest()


def _code():
    """Content identities of the code that derives price rows and saved books.

    The fingerprint binds the same files by size and time. Content identity
    keeps saved rows across checkouts that only rewrite timestamps.
    """
    def content(paths):
        return _digest([hashlib.sha256(p.read_bytes()).hexdigest() for p in paths])
    return dict(prices=content(PRICE_SOURCES),books=content(r.calculation_sources()+_engine_sources()))


def _book_inputs(reference,db):
    """Copy the 10-year yields for the kept-book check; return the identity of the undated book inputs."""
    db.execute('INSERT INTO main.treasury10 SELECT * FROM research.treasury10')
    digest=hashlib.sha256()
    for table in BOOK_INPUTS:
        digest.update(table.encode()+b'\n')
        for row in reference.execute('SELECT * FROM '+table):
            backtest_control.checkpoint()
            digest.update(json.dumps(list(row),separators=(',',':')).encode()+b'\n')
    return digest.hexdigest()


def _previous(path):
    """Return the saved inputs and refresh evidence of an existing cache.

    Old rows are read only when the saved code identities equal the current
    ones. Those bind this module, so its schema and evidence form match too.
    """
    # Read-write, like connect(): a book write interrupted by a crash leaves a
    # hot journal that only a writable connection rolls back.
    with closing(sqlite3.connect(path,timeout=60)) as db:
        saved=dict(db.execute("SELECT key,value FROM metadata WHERE key IN ('daily_inputs','refresh')"))
    try:
        current=json.loads(saved['daily_inputs']) if 'daily_inputs' in saved else None
        evidence=json.loads(saved['refresh']) if 'refresh' in saved else None
    except ValueError:
        return None,None
    return current,(evidence if isinstance(evidence,dict) and evidence.get('version')==VERSION else None)


def _first_difference(old,new):
    """Return the first day whose dated row differs, or None when both match."""
    for a,b in zip(old,new):
        if a!=b:return min(a[0],b[0])
    if len(old)!=len(new):
        return (old if len(old)>len(new) else new)[min(len(old),len(new))][0]
    return None


def _prices(db,symbols,saved,code):
    """Store company prices; return their evidence and the first changed days.

    With an attached previous cache, equal file bytes copy the stored rows
    without parsing. Bytes, not stamps, decide: downloads rewrite checked files
    with equal bytes, and a copy can keep old stamps. A saved digest of the
    stored rows proves a pure append without reading them back; otherwise the
    rows are compared.
    """
    previous=saved['prices'] if saved else {}
    same_code=saved is not None and saved['code']['prices']==code['prices']
    units={};earliest=[]
    for i,symbol in enumerate(symbols,1):
        backtest_control.checkpoint()
        # Parse the hashed bytes themselves: no later check sees an in-place
        # rewrite of one price file.
        data=market.cache_path_for(symbol).read_bytes()
        content=hashlib.sha256(data).hexdigest()
        old=previous.get(symbol)
        if same_code and old is not None and old['content']==content:
            db.execute('INSERT INTO prices SELECT * FROM old.prices WHERE symbol=?',(symbol,))
            units[symbol]=old
            diagnostics.count('prices_copied')
        else:
            diagnostics.count('prices_parsed')
            rows=_price_rows(json.loads(data))
            db.executemany('INSERT INTO prices VALUES(?,?,?)',[(symbol,*row) for row in rows])
            units[symbol]=dict(content=content,last=rows[-1][0] if rows else None,digest=_digest(rows))
            if same_code:
                if old is not None and _digest([row for row in rows if old['last'] is not None and row[0]<=old['last']])==old['digest']:
                    later=[row for row in rows if old['last'] is None or row[0]>old['last']]
                    changed=later[0][0] if later else None
                else:
                    changed=_first_difference([tuple(row) for row in db.execute('SELECT day,adjusted FROM old.prices WHERE symbol=? ORDER BY day',(symbol,))],rows)
                if changed is not None:earliest.append(changed)
        if i%200==0 or i==len(symbols):
            print(f'Prepared daily prices {i}/{len(symbols)}',flush=True)
    # A removed company changes the cached set, which drops every book.
    return units,earliest


def _dated_change(db,table):
    """First day where a small dated table differs from the previous cache."""
    rows=lambda schema:[tuple(row) for row in db.execute(f'SELECT * FROM {schema}.{table} ORDER BY day')]
    return _first_difference(rows('old'),rows('main'))


def _keep_books(db,since):
    """Copy saved dated books that read no input changed on or after since, with their book ids.

    A book reads no price, session or yield after max(exit, entry+FORWARD_REACH).
    None keeps every dated book. The latest book is never kept.
    """
    previous=db.execute('SELECT book,entry,exit FROM old.books WHERE exit IS NOT NULL').fetchall()
    kept=[(book,) for book,entry,exit_day in previous
          if since is None or max(date.fromisoformat(exit_day),date.fromisoformat(entry)+financial_books.FORWARD_REACH)<date.fromisoformat(since)]
    diagnostics.note(books_previous=len(previous),books_kept=len(kept),changed_from=since)
    if not kept:return
    db.execute('CREATE TEMP TABLE kept_books(book INTEGER PRIMARY KEY)')
    db.executemany('INSERT INTO temp.kept_books VALUES(?)',kept)
    for table in book_store.TABLES:
        db.execute(f'INSERT INTO main.{table} SELECT * FROM old.{table} WHERE book IN (SELECT book FROM temp.kept_books)')
    db.execute('DROP TABLE temp.kept_books')


@diagnostics.operation('prepare.daily')
@cache_access.exclusive
def prepare(path=DATABASE, source=r.DATABASE):
    """Parse changed raw prices only; keep the previous cache if publication fails.

    A stale cache with refresh evidence and the current layout supplies its
    unchanged company prices and every saved dated book that cannot read a
    changed input. The latest book is computed afresh. The result matches a
    full build of the same inputs plus those books.
    """
    started=time.perf_counter()
    diagnostics.lap('admission')
    path=Path(path)
    # The public daily-cache command owns its prerequisite too. Users never
    # need to discover and run the dependency chain themselves.
    r.prepare(source)
    diagnostics.lap('research')
    inputs=fingerprint(source)
    reference=r.connect(source,full_prices=True)
    saved=None
    if path.exists():
        # Compare the saved fingerprint with this operation's own. connect()
        # would compute it again and ask no new freshness question.
        current,saved=_previous(path)
        if current==inputs:
            reference.close();print('Daily cache already current; no prices parsed.')
            diagnostics.note(outcome='current');return
    diagnostics.lap('input_check')
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.building')
    temporary.unlink(missing_ok=True)
    # URI support lets the previous cache attach read-only.
    db=sqlite3.connect(temporary.resolve().as_uri(),uri=True)
    try:
        db.executescript(SCHEMA)
        if saved is not None:
            db.execute('ATTACH DATABASE ? AS old',(path.resolve().as_uri()+'?mode=ro',))
        attach(db,source)
        tables=_book_inputs(reference,db)
        diagnostics.lap('copy_research')
        symbols=[row[0] for row in reference.execute('SELECT DISTINCT symbol FROM statements') if market.cache_path_for(row[0]).exists()]
        code=_code()
        units,earliest=_prices(db,symbols,saved,code)
        diagnostics.lap('prices')
        db.executemany('INSERT INTO sessions VALUES(?,?)',[(str(d),v) for d,v in market.load_bars(r.RAW/'spy-div.json','adjClose')])
        db.executemany('INSERT OR REPLACE INTO treasuries VALUES(?,?)',[(row['date'][:10],row['month3']/100) for row in json.loads((r.RAW/'treasury.json').read_text()) if rules.parse_day(row.get('date')) is not None and rules.num(row.get('month3')) is not None])
        diagnostics.lap('market')
        books=_digest(dict(tables=tables,symbols=symbols))
        if saved is not None and code['books']==saved['code']['books'] and books==saved['books']:
            earliest+=[day for table in ('sessions','treasuries','treasury10') if (day:=_dated_change(db,table)) is not None]
            _keep_books(db,min(earliest) if earliest else None)
            diagnostics.lap('keep_books')
        # The latest book: the open book at research's latest date, from its
        # facts. Kept dated books keep their ids; the latest book takes the next.
        book_facts=facts.BookFacts(reference)
        for pool in ('legacy','cached'):
            book_store.store(db,financial_books.book(date.fromisoformat(inputs['facts']['latest_date']),None,pool,
                                                     book_facts,backtest_control.checkpoint))
        diagnostics.lap('latest_book')
        if inputs!=fingerprint(source):
            raise ValueError('Inputs changed during daily preparation; retry.')
        evidence=dict(version=VERSION,code=code,books=books,prices=units)
        for key,value in dict(daily_inputs=inputs,refresh=evidence).items():
            db.execute('INSERT INTO metadata VALUES(?,?)',(key,json.dumps(value)))
        db.commit()
        db.close();reference.close();temporary.replace(path)
    except BaseException:
        db.close();reference.close();temporary.unlink(missing_ok=True);raise
    action='refreshed' if saved is not None else 'prepared'
    diagnostics.lap('publication')
    diagnostics.note(outcome=action,symbols=len(symbols),database_bytes=path.stat().st_size)
    print(f'Daily cache {path.stat().st_size/1e6:.1f} MB {action} in {time.perf_counter()-started:.1f}s',flush=True)
