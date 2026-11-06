"""Offline research database: companies, reports and typed facts.

It holds no book: the book store of the daily cache (backtest/inputs/book_store.py)
holds the latest and dated books, computed from these facts.

Every preparation is a full build. It writes a temporary file and replaces the
published database atomically; the previous database stays on any failure.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
from datetime import date
import json
import os
import stat
from pathlib import Path
import sqlite3
import time

from backtest.financial import rules
from backtest.inputs import market, cache_assets
from backtest.financial import metrics as metrics
from backtest.financial import books as books
from backtest.inputs import financial_inputs as financial_inputs
from backtest.inputs import facts
from backtest.runtime import backtest_control
from backtest.runtime import diagnostics
from backtest.runtime import cache_access as cache_access
from backtest.paths import ROOT, RAW

DATABASE = ROOT / 'data' / 'research.sqlite'
SCHEMA_VERSION = 17
# The annual rows (statements, and the legacy values-only financial_inputs
# JSON) and the 10-year Treasury yields; the typed facts are facts.SCHEMA.
# The daily cache copies treasury10 for its kept-book check.
SCHEMA = '''
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE statements (symbol TEXT, fiscal TEXT, known TEXT, market_cap REAL, enterprise_value REAL, ebitda REAL, ebitda_yield REAL, PRIMARY KEY(symbol,fiscal));
CREATE TABLE financial_inputs (symbol TEXT, fiscal TEXT, values_json TEXT NOT NULL, PRIMARY KEY(symbol,fiscal));
CREATE TABLE treasury10 (day TEXT PRIMARY KEY, yield_percent REAL NOT NULL) WITHOUT ROWID;
'''


def _metadata_entries(directory, pattern):
    """Return fresh metadata for the same paths selected by the inventory glob.

    Preserve platform matching, link traversal and discovery errors. Results
    are ordered and own no open directory handles. No metadata survives this
    invocation. Only the existing one- and two-level patterns are used.
    """
    paths = sorted(directory.glob(pattern))
    parents = {}
    for path in paths:
        parents.setdefault(str(path.parent), set()).add(path.name)
    discovered = {}
    for parent, names in parents.items():
        try:
            with os.scandir(parent) as entries:
                selected = {str(Path(parent) / entry.name): entry for entry in entries if entry.name in names}
        except OSError:
            # Enumeration is an optimization, not an additional permission
            # requirement. Path.stat retains the original metadata failures.
            selected = {}
        discovered.update(selected)
    # Exact spelling also preserves distinct names in case-sensitive Windows
    # directories. Evaluate metadata in the original sorted-path order.
    return [(path, discovered[str(path)].stat() if str(path) in discovered else path.stat())
            for path in paths]


_accepted = {}


def accepted_signature():
    """Return the raw-input signature that ordinary readers compare against.

    signature() inspects about 36,000 files on the real cache. Readers reuse
    the value taken at startup, by preparation and after each data-panel
    action, so a hand edit to raw/ needs a data-panel check before readers see it.
    """
    key = str(RAW), str(ROOT)
    if key not in _accepted:
        _accepted.clear(); _accepted[key] = signature()
    return _accepted[key]


def forget_signature():
    """Make the next reader inspect raw inputs again."""
    _accepted.clear()


def signature():
    """Return the current ordered input signature.

    Every call discovers and inspects inputs afresh. Keys preserve lexical
    paths relative to ROOT; discovery and metadata failures retain their
    existing precedence. No inventory or derived prefix survives the call.
    raw/download-coverage.json is not an input: no preparation reads it.
    """
    paths = [RAW/n for n in ['universe.json','metrics.jsonl','spy-div.json','treasury.json']]
    paths += [RAW/'px'] + calculation_sources()
    entries = [(path, path.stat()) for path in paths]
    financial = _metadata_entries(RAW/'financial-inputs', '*/*.json')
    result = {p.relative_to(ROOT).as_posix(): ['directory' if stat.S_ISDIR(info.st_mode) else info.st_size,info.st_mtime_ns] for p,info in entries}
    prefixes = {}
    for path, info in financial:
        parent = path.parent
        # Exact spelling keeps case-distinct native directories distinct.
        spelling = str(parent)
        if spelling not in prefixes:
            try:
                relative = parent.relative_to(ROOT).as_posix()
            except ValueError:
                # Preserve the original full-path result or exception.
                key = path.relative_to(ROOT).as_posix()
            else:
                prefixes[spelling] = '' if relative == '.' else relative + '/'
                key = prefixes[spelling] + path.name
        else:
            key = prefixes[spelling] + path.name
        result[key] = ['directory' if stat.S_ISDIR(info.st_mode) else info.st_size,info.st_mtime_ns]
    return result


def price_sources():
    return {p.name: [info.st_size,info.st_mtime_ns] for p,info in _metadata_entries(RAW/'px', '*.json')}


def calculation_sources():
    """Source files whose content computes prepared rows or books.

    The list names only that code: never the reference engine or the
    development check (backtest/engines/reference), and never code that only
    reads or selects stored rows. The research signature and the daily cache's
    book identity bind these files, so an edit elsewhere neither rebuilds
    research nor drops saved books.
    """
    here = Path(__file__)
    return [here, Path(metrics.__file__), Path(books.__file__), Path(rules.__file__), Path(cache_assets.__file__), Path(market.__file__),
            Path(financial_inputs.__file__), Path(financial_inputs.parameters.__file__), Path(facts.__file__)]


def _replace(source, destination):
    """Replace atomically; retry Windows sharing/access locks for under 2s."""
    for attempt in range(len(cache_assets.PUBLISH_RETRY_DELAYS)+1):
        try:
            source.replace(destination);return
        except PermissionError as error:
            if getattr(error,'winerror',None) not in (5,32,33) or attempt==len(cache_assets.PUBLISH_RETRY_DELAYS):raise
            time.sleep(cache_assets.PUBLISH_RETRY_DELAYS[attempt])


def prepared_price_binding(path=DATABASE):
    """Identify the price inventory accepted by committed research metadata.

    Read no raw price files. Preparation owns inventory validation; ordinary
    daily-cache checks bind to that validated prerequisite without rescanning it.
    """
    with closing(connect(path)) as db:
        return _price_binding(db)


def prepared_bindings(path=DATABASE):
    """Return the price and typed-facts bindings from one connection.

    The caller compares signature() itself, so this connection skips it. The
    facts binding is the metadata, including the content identity that
    preparation recorded; the app is the only writer and holds the cache lock.
    """
    with closing(connect(path, check=False)) as db:
        return _price_binding(db), facts.require(db)


def _price_binding(db):
    row=db.execute("SELECT value FROM metadata WHERE key='prices'").fetchone()
    inventory=json.loads(row[0]) if row else None
    if (not isinstance(inventory,dict) or any(
            not isinstance(name,str) or Path(name).name!=name or not name.endswith('.json')
            or not isinstance(stamp,list) or len(stamp)!=2
            or any(type(value) is not int or value<0 for value in stamp)
            for name,stamp in inventory.items())):
        raise ValueError('Prepared price inventory is invalid. Run research.py prepare')
    return hashlib.sha256(json.dumps(inventory,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def connect(path=DATABASE, check=True, full_prices=False):
    path=Path(path)
    if not path.exists():
        raise ValueError('Prepared database missing. Run: python3 scripts/research.py prepare')
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    try:
        meta={r['key']:json.loads(r['value']) for r in db.execute("SELECT * FROM metadata WHERE key IN ('version','inputs','prices')")}
        if meta.get('version') != SCHEMA_VERSION:
            raise ValueError('Database version changed; run research.py prepare')
        if check and (meta.get('inputs')!=accepted_signature() or (full_prices and meta.get('prices')!=price_sources())):
            raise ValueError('Cached inputs changed. Run: python3 scripts/research.py prepare')
    except Exception:
        db.close()
        raise
    return db


def _readable(resolution, name):
    """Return one resolved price or yield file; an unreadable saved file stops preparation."""
    if resolution['source']['disposition']=='unreadable':
        raise ValueError(f'Saved file raw/{name} is unreadable. Use the data panel to download it again.')
    return resolution


@cache_access.exclusive
@diagnostics.operation('prepare.research')
def prepare(path=DATABASE, force=False):
    """Build the research database from saved files; never download.

    Every build is a full build. A current database is kept unless force is set.
    """
    started=time.perf_counter()
    diagnostics.note(force=force)
    path=Path(path)
    # Preparation is a data action: its readers inspect raw inputs afresh.
    forget_signature()
    if path.exists() and not force:
        try:
            db=connect(path,full_prices=True)
        except ValueError:
            pass
        else:
            db.close()
            print(f'Database already current ({time.perf_counter()-started:.2f}s); no JSON prices parsed.')
            diagnostics.note(outcome='current');return
    inputs, sources=signature(),price_sources()
    universe={r['symbol']:r for r in json.loads((RAW/'universe.json').read_text())}
    # Each saved file is parsed once, into its typed facts.
    market_facts=facts.shared(RAW,backtest_control.checkpoint)
    for name,endpoint in (('spy-div.json',facts.CALENDAR),('treasury.json',facts.TREASURY)):
        _readable(market_facts[endpoint],name)
    valid={field:{day:states[field]['value'] for day,states in market_facts[endpoint]['dated'].items() if states[field]['valid']}
           for endpoint,field in ((facts.CALENDAR,'adjClose'),(facts.TREASURY,'year10'))}
    records,invalid=cache_assets.financial_records(RAW/'metrics.jsonl')
    if invalid:raise ValueError('Annual financial cache contains invalid records. Use the data panel to repair annual financials.')
    broad=books.statements(records,universe)
    financials=[(symbol,str(row['fiscal']),str(row['known']),row['market_cap'],row['enterprise'],row['ebitda'],row['yield'])
                for symbol,rows in broad.items() for row in rows]
    latest_day=date.fromisoformat(max(valid['adjClose']))
    diagnostics.lap('inputs')
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.building')
    if temporary.exists():
        temporary.unlink()
    db=sqlite3.connect(temporary.resolve().as_uri(),uri=True)
    db.row_factory=sqlite3.Row
    try:
        db.executescript(SCHEMA+facts.SCHEMA)
        units={}
        db.executemany('INSERT INTO treasury10 VALUES(?,?)',sorted(valid['year10'].items()))
        facts.store_companies(db,universe)
        db.executemany('INSERT OR REPLACE INTO statements VALUES(?,?,?,?,?,?,?)',financials)
        cached={s for s in broad if market.cache_path_for(s).name in sources}
        for number,symbol in enumerate(sorted(broad),1):
            backtest_control.checkpoint()
            # One parse of the price file gives its typed facts.
            stock=_readable(facts.stock(RAW,symbol,backtest_control.checkpoint),'px/'+market.cache_path_for(symbol).name)
            facts.store_stock(db,symbol,stock)
            resolved=financial_inputs.resolve_history(RAW,symbol)
            facts.store_annual(db,symbol,resolved)
            if number%200==0 or number==len(broad):
                print(f'Prepared {number}/{len(broad)} companies',flush=True)
            # The facts identity binds each price file's bytes.
            if symbol in cached:
                units[symbol]=stock['source']['sha256']
            db.executemany('INSERT INTO financial_inputs VALUES(?,?,?)',[(symbol,fiscal,json.dumps(values)) for fiscal,values in resolved['values'].items()])
        diagnostics.lap('companies')
        diagnostics.note(companies=len(cached))
        facts.store_market(db,market_facts)
        diagnostics.lap('dated_facts')
        scopes=[dict(mode='latest',pool=pool,context_date=str(latest_day),book=0) for pool in ('legacy','cached')]
        # Rows follow from the raw signature and each price file's bytes.
        facts.finish(db,latest_day,scopes=scopes,inputs=dict(signature=inputs,prices=units))
        diagnostics.lap('facts_finish')
        for key,value in dict(version=SCHEMA_VERSION,inputs=inputs,prices=sources).items():
            db.execute('INSERT INTO metadata VALUES(?,?)',(key,json.dumps(value)))
        # Reject changing inputs and keep an existing database intact on failure.
        if inputs!=signature() or sources!=price_sources():
            raise ValueError('Inputs changed during preparation; retry.')
        db.commit()
        diagnostics.lap('commit')
        db.close()
        _replace(temporary,path)
        diagnostics.lap('publication')
    except BaseException:
        db.close()
        temporary.unlink(missing_ok=True)
        raise
    diagnostics.note(outcome='prepared',database_bytes=path.stat().st_size)
    print(f'Prepared {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: {path.stat().st_size/1e6:.1f} MB in {time.perf_counter()-started:.2f}s')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=DATABASE)
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('prepare',help='Prepare the research database from saved JSON; never downloads')
    p.add_argument('--force',action='store_true')
    commands.add_parser('status',help='Show database size and latest price coverage')
    args=parser.parse_args()
    if args.command=='prepare':
        prepare(args.database,args.force);return
    # The latest book lives in the book store of the daily cache, which binds this database.
    from backtest.inputs import book_store, daily
    connect(args.database).close()
    with closing(daily.connect(daily.DATABASE,args.database)) as db:
        book,asof=book_store.latest(db)
        candidates=db.execute('SELECT candidates FROM books WHERE book=?',(book,)).fetchone()[0]
        counts=dict(db.execute('SELECT pool,COUNT(*) FROM book_rows WHERE book=? GROUP BY pool',(book,)).fetchall())
    print(f'Database: {args.database.stat().st_size/1e6:.1f} MB')
    print(f"Latest session {asof}: {candidates} active names with eligible financials; "
          f"{counts.get('cached',0)} valued with cached prices, {counts.get('legacy',0)} in the original candidate set.")


if __name__=='__main__':
    try:
        main()
    except (ValueError,sqlite3.Error) as error:
        raise SystemExit(str(error))
