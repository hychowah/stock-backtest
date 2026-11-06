"""Offline research database: companies, reports, typed facts and the one research record.

It holds no book: the book store of the daily cache (backtest/inputs/book_store.py)
holds the latest and dated books, computed from these facts.

Every preparation is a full build. It writes a temporary file and replaces the
published database atomically; the previous database stays on any failure.

The metadata table is the one research record: the schema version, the
accepted raw-file signature (inputs) with each price file's stamps (prices),
and the identity: version, latest date, the content identity of the fact-row
code (code) and the content identity of the facts (content). Readers compare
the stamps and the code (identity()). Both identities are content digests, so
a rewrite with equal bytes keeps them.
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
from backtest.inputs import book_store, facts
from backtest.runtime import backtest_control
from backtest.runtime import diagnostics
from backtest.runtime import cache_access as cache_access
from backtest.paths import ROOT, RAW

DATABASE = ROOT / 'data' / 'research.sqlite'
SCHEMA_VERSION = 18
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
    raw/download-coverage.json is not an input: no preparation reads it. Code
    is not in the signature: identity() compares the fact-row code by content.
    """
    paths = [RAW/n for n in ['universe.json','metrics.jsonl','spy-div.json','treasury.json']] + [RAW/'px']
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


def code_sources(role):
    """The source files whose content forms one identity: the one rule of code roles.

    Each identity binds only the files that hold its role's code, by content
    (sha256), so a rewrite with equal bytes keeps it.
    - 'facts', the research identity: the fact-row code that parses saved
      files into research rows. research.prepare; facts.resolve, observe and
      the store_* writers; books.statements; financial_inputs with its
      parameter catalog; the parsing parts of cache_assets; market and rules.
    - 'books', the book identity that the daily binding names: the code that
      computes and stores books. books.py, metrics.py, rules.py,
      facts.BookFacts and book_store (its schema, writer and readers).
    A file that holds code of both roles is in both lists. Readers bind no
    identity: fact_view (View and its recorder), schedules, book_batch,
    calendar, portfolio_results, screening, scalar_execution, the CLI and
    connection code (daily.py among them). An edit to a reader neither
    rebuilds research nor drops a book. The reference engine and the
    development check (backtest/engines/reference) are never bound.
    """
    if role == 'facts':
        return [Path(__file__)] + [Path(module.__file__) for module in (
            facts, books, rules, financial_inputs, financial_inputs.parameters, cache_assets, market)]
    if role == 'books':
        return [Path(module.__file__) for module in (books, metrics, rules, facts, book_store)]
    raise ValueError('Unknown code role.')


def code_identity(role):
    """The content identity of one code role: the digest of its files' names and sha256s (code_sources)."""
    digests = [[path.name, hashlib.sha256(path.read_bytes()).hexdigest()] for path in code_sources(role)]
    return hashlib.sha256(json.dumps(digests, separators=(',', ':')).encode()).hexdigest()


def _replace(source, destination):
    """Replace atomically; retry Windows sharing/access locks for under 2s."""
    for attempt in range(len(cache_assets.PUBLISH_RETRY_DELAYS)+1):
        try:
            source.replace(destination);return
        except PermissionError as error:
            if getattr(error,'winerror',None) not in (5,32,33) or attempt==len(cache_assets.PUBLISH_RETRY_DELAYS):raise
            time.sleep(cache_assets.PUBLISH_RETRY_DELAYS[attempt])


def identity(db, schema='main', *, prices=False):
    """The identity of one research record, after the readers' freshness check.

    schema is 'main' on a research connection and 'research' on a daily
    connection that attaches it. The record must have this schema version,
    the accepted raw-file signature, the current fact-row code and, when
    prices is set, each saved price file's current stamps. A stale record
    raises ValueError.
    """
    keys = ('version', 'inputs', 'identity') + (('prices',) if prices else ())
    meta = {key: json.loads(value) for key, value in db.execute(
        f'SELECT key,value FROM {schema}.metadata WHERE key IN ({",".join("?" * len(keys))})', keys)}
    if meta.get('version') != SCHEMA_VERSION:
        raise ValueError('Database version changed; run research.py prepare')
    if (meta.get('inputs') != accepted_signature() or (prices and meta.get('prices') != price_sources())
            or not isinstance(meta.get('identity'), dict) or meta['identity'].get('code') != code_identity('facts')):
        raise ValueError('Cached inputs changed. Run: python3 scripts/research.py prepare')
    return meta['identity']


def connect(path=DATABASE, full_prices=False):
    """Open a read-only research connection whose record passes identity()."""
    path=Path(path)
    if not path.exists():
        raise ValueError('Prepared database missing. Run: python3 scripts/research.py prepare')
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    try:
        identity(db,prices=full_prices)
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
    code=code_identity('facts')
    content=(RAW/'universe.json').read_bytes()
    # The facts' content identity: the code and the bytes of every saved file read.
    raw=dict(universe=hashlib.sha256(content).hexdigest(),
             metrics=hashlib.sha256((RAW/'metrics.jsonl').read_bytes()).hexdigest())
    universe={r['symbol']:r for r in json.loads(content)}
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
            db.executemany('INSERT INTO financial_inputs VALUES(?,?,?)',[(symbol,fiscal,json.dumps(values)) for fiscal,values in resolved['values'].items()])
        diagnostics.lap('companies')
        diagnostics.note(companies=len(cached))
        facts.store_market(db,market_facts)
        diagnostics.lap('dated_facts')
        # fact_sources holds the digest of every price, annual, SPY and Treasury file read.
        digest=hashlib.sha256()
        for row in db.execute('SELECT symbol,endpoint,sha256,disposition FROM fact_sources ORDER BY symbol,endpoint'):
            digest.update(json.dumps(list(row),separators=(',',':')).encode()+b'\n')
        raw['sources']=digest.hexdigest()
        record=dict(version=SCHEMA_VERSION,latest_date=str(latest_day),code=code)
        record['content']=hashlib.sha256(facts.encoded(dict(record,raw=raw)).encode()).hexdigest()
        diagnostics.lap('identity')
        for key,value in dict(version=SCHEMA_VERSION,inputs=inputs,prices=sources,identity=record).items():
            db.execute('INSERT INTO metadata VALUES(?,?)',(key,json.dumps(value)))
        # Reject changing inputs and keep an existing database intact on failure.
        if inputs!=signature() or sources!=price_sources() or code!=code_identity('facts'):
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
    from backtest.inputs import daily
    connect(args.database).close()
    with closing(daily.connect(daily.DATABASE,args.database)) as db:
        book=book_store.open_book(db);latest=book_store.record(db,book)
        counts={pool:sum(1 for _ in book_store.rows(db,book,pool)) for pool in ('legacy','cached')}
    print(f'Database: {args.database.stat().st_size/1e6:.1f} MB')
    print(f"Latest session {latest['entry']}: {latest['candidates']} active names with eligible financials; "
          f"{counts.get('cached',0)} valued with cached prices, {counts.get('legacy',0)} in the original candidate set.")


if __name__=='__main__':
    try:
        main()
    except (ValueError,sqlite3.Error) as error:
        raise SystemExit(str(error))
