"""Offline research database: companies, reports, typed facts and the one research record.

It holds no book: the book store of the daily cache (backtest/inputs/book_store.py)
holds the latest and dated books, computed from these facts.

Compatible preparation reconciles changed typed rows in one transaction.
Cold, schema and fact-code builds use a temporary file and atomic replacement.
Either path preserves the previous committed data on failure. Both fold the
derived valuation sums last, in the same transaction (facts.store_valuations).

The metadata table is the one research record: the schema version, the
accepted raw-file signature (inputs) with each price file's stamps (prices),
the identity: version, latest date, the content identity of the fact-row code
(code) and the content identity of the facts (content), plus pending fact changes
and their base identity (changes). Readers compare
the stamps and the code (identity()).
Both identities are content digests, so a rewrite with equal bytes keeps them.
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
SCHEMA_VERSION = 21
# The annual statements; the typed facts are facts.SCHEMA.
SCHEMA = '''
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE statements (symbol TEXT, fiscal TEXT, known TEXT, market_cap REAL, enterprise_value REAL, ebitda REAL, ebitda_yield REAL, PRIMARY KEY(symbol,fiscal));
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
    foreign_present=any(market.universe_path(RAW,code).exists() for code in ('hk','jp'))
    entries = [(path, path.stat()) for path in paths if path.exists() or not foreign_present]
    optional=[market.universe_path(RAW,code) for code in ('hk','jp')]+[market.calendar_path(RAW,code) for code in ('hk','jp')]
    optional += [RAW/'markets',RAW/'fx',RAW/'px-full']
    entries += [(path,path.stat()) for path in optional if path.exists()]
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
    for folder in (RAW/'fx',RAW/'px-full'):
        if folder.exists():
            for path,info in _metadata_entries(folder,'*.json'):
                result[path.relative_to(ROOT).as_posix()]=['directory' if stat.S_ISDIR(info.st_mode) else info.st_size,info.st_mtime_ns]
    return result


def price_sources():
    return {p.name: [info.st_size,info.st_mtime_ns] for p,info in _metadata_entries(RAW/'px', '*.json')}


def code_sources(role):
    """The source files whose content forms one identity: the one rule of code roles.

    Each identity binds only the files that hold its role's code, by content
    (sha256), so a rewrite with equal bytes keeps it.
    - 'facts', the research identity: the fact-row code that parses saved
      files into research rows and folds the valuation sums. research.prepare;
      facts.resolve, observe, the store_* writers, refold and the BookFacts
      reads of the fold; books.statements, affected_entries and
      valuation_days; financial_inputs with its parameter catalog; the parsing
      parts of cache_assets; market and rules.
    - 'books', the book identity that the daily binding names: the code that
      computes and stores books. books.py, metrics.py, rules.py,
      facts.BookFacts and book_store (its schema, writer and readers).
      code_identity also names the legacy annual field list that
      BookFacts.legacy_annual reads (facts.LEGACY): fact-row code defines it.
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
    """The content identity of one code role: the digest of its files' names and sha256s (code_sources).

    The book identity also digests facts.LEGACY, so an edit to the legacy field
    list in financial_inputs or the catalog drops every book.
    """
    digests = [[path.name, hashlib.sha256(path.read_bytes()).hexdigest()] for path in code_sources(role)]
    if role == 'books':
        digests.append(['facts.LEGACY', facts.LEGACY])
    return hashlib.sha256(json.dumps(digests, separators=(',', ':')).encode()).hexdigest()


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


def _saved_metadata(path):
    if not path.exists():return {}
    # A writable read lets SQLite recover an interrupted in-place transaction.
    with closing(sqlite3.connect(path,timeout=60)) as db:
        try:return {key:json.loads(value) for key,value in db.execute("SELECT key,value FROM metadata WHERE key IN ('version','identity','changes')")}
        except ValueError:return {}


@cache_access.exclusive
@diagnostics.operation('prepare.research')
def prepare(path=DATABASE, force=False, *, progress=lambda **kw:None):
    """Reconcile saved facts atomically; force also checks unchanged inputs."""
    if (RAW/'metrics.jsonl').exists():cache_assets.trim_financial_tail(RAW/'metrics.jsonl')
    started=time.perf_counter()
    progress(kind='research',completed=0,total=None)
    diagnostics.note(force=force)
    path=Path(path)
    prior=_saved_metadata(path)
    # Preparation is a data action: its readers inspect raw inputs afresh.
    forget_signature()
    if path.exists() and not force:
        try:
            db=connect(path,full_prices=True)
        except ValueError:
            pass
        else:
            db.close()
            progress(kind='research',completed=1,total=1,reused=True)
            print(f'Database already current ({time.perf_counter()-started:.2f}s); only file metadata was checked.')
            diagnostics.note(outcome='current');return
    inputs, sources=signature(),price_sources()
    code=code_identity('facts')
    previous=prior.get('identity',{})
    cold=prior.get('version')!=SCHEMA_VERSION or not isinstance(previous,dict) or previous.get('code')!=code
    foreign_universes={};foreign_digests={}
    for market_id in ('hk','jp'):
        inventory=market.universe_path(RAW,market_id)
        if inventory.exists():
            saved=inventory.read_bytes()
            foreign_digests[market_id]=hashlib.sha256(saved).hexdigest()
            foreign_universes[market_id]={row['symbol']:{**row,'market':market_id} for row in json.loads(saved)}
    content=(RAW/'universe.json').read_bytes() if (RAW/'universe.json').exists() else b'[]'
    # The facts' content identity: the code and the bytes of every saved file read.
    raw=dict(universe=hashlib.sha256(content).hexdigest(),
             metrics=hashlib.sha256((RAW/'metrics.jsonl').read_bytes() if (RAW/'metrics.jsonl').exists() else b'').hexdigest())
    raw['foreign_universes']=foreign_digests
    universe={r['symbol']:r for r in json.loads(content)}
    us_universe=universe.copy()
    for group in foreign_universes.values():universe.update(group)
    records,invalid=cache_assets.financial_records(RAW/'metrics.jsonl')
    if invalid:raise ValueError('Annual financial cache contains invalid records. Use the data panel to repair annual financials.')
    broad=books.statements(records,us_universe)
    company_count=len(broad)+sum(len(group) for group in foreign_universes.values())
    progress(kind='research',completed=0,total=company_count+1)
    financials=[(symbol,str(row['fiscal']),str(row['known']),row['market_cap'],row['enterprise'],row['ebitda'],row['yield'])
                for symbol,rows in broad.items() for row in rows]
    diagnostics.lap('inputs')
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.building')
    temporary.unlink(missing_ok=True)
    db=sqlite3.connect(':memory:',uri=True)
    db.row_factory=sqlite3.Row
    try:
        if cold:
            with closing(sqlite3.connect(temporary)) as fresh:fresh.executescript(SCHEMA+facts.SCHEMA)
        # The build attaches its file as 'research', the schema that the facts
        # port reads, so the valuation fold reads this transaction's facts.
        # main stays empty, so unqualified table names resolve to research.
        db.execute('ATTACH DATABASE ? AS research',((temporary if cold else path).resolve().as_uri(),))
        db.execute('BEGIN IMMEDIATE')
        changes=dict(base=None if cold else previous['content'],companies={},prices={},
                     annual={},reports={},statements=False,sessions={},treasury=None,fx={})
        def note(kind,owner,day):
            current=changes[kind].get(owner)
            if current is None or day<current:changes[kind][owner]=day
        old_markets={row[0]:tuple(row) for row in db.execute('SELECT * FROM company_markets')}
        old_sources={(row[0],row[1]):tuple(row) for row in db.execute('SELECT * FROM fact_sources')}
        seen_sources=set()
        def source_bytes(file,symbol,endpoint,*,decode=False):
            seen_sources.add((symbol,endpoint))
            try:content=file.read_bytes()
            except FileNotFoundError:content=None
            sha=None if content is None else hashlib.sha256(content).hexdigest()
            old=old_sources.get((symbol,endpoint))
            return force or decode or old is None or old[2]!=sha,content
        company_changes,market_changes=facts.store_companies(db,universe)
        new_markets={row[0]:tuple(row) for row in db.execute('SELECT * FROM company_markets')}
        def company_changed(symbol):
            changes['companies'][symbol]=[old_markets.get(symbol,(None,None))[1],new_markets.get(symbol,(None,None))[1]]
        for before,after in company_changes:
            if before is None or after is None:company_changed((after or before)[0])
        for before,after in market_changes:company_changed((after or before)[0])

        # Stable legacy ties follow source insertion order, as in a cold build.
        old_statements=[tuple(row) for row in db.execute('SELECT * FROM statements ORDER BY rowid')]
        db.execute('DELETE FROM statements')
        db.executemany('INSERT OR REPLACE INTO statements VALUES(?,?,?,?,?,?,?)',financials)
        new_statements=[tuple(row) for row in db.execute('SELECT * FROM statements ORDER BY rowid')]
        changes['statements']=len(old_statements)!=len(new_statements) or any(
            not facts.same_row(old,new) for old,new in zip(old_statements,new_statements))
        old_reports={(row[0],row[1]):row for row in old_statements}
        for row in new_statements:
            old=old_reports.pop(row[:2],None)
            if old is None or not facts.same_row(old,row):
                note('reports',row[0],min(item[2] for item in (old,row) if item is not None))
        for row in old_reports.values():note('reports',row[0],row[2])
        contents={}
        for market_id in foreign_universes:
            # Completion depends on the clock as well as the small calendar file.
            endpoint='calendar:'+market_id
            _,content=source_bytes(market.calendar_path(RAW,market_id),'',endpoint)
            contents[endpoint]=content
        currencies=set()
        for file in sorted((RAW/'fx').glob('USD???.json')):
            currencies.add(file.stem[3:]);endpoint='fx:'+file.stem[3:]
            changed,content=source_bytes(file,'',endpoint)
            if changed:contents[endpoint]=content
        foreign=facts.store_foreign_market(db,RAW,foreign_universes,backtest_control.checkpoint,contents=contents)
        for kind in ('sessions','fx'):
            for owner,rows in foreign[kind].items():
                for before,after in rows:note(kind,owner,(after or before)[1])
        for table,column,wanted,kind in [('local_sessions','market',foreign_universes,'sessions'),('fx_days','currency',currencies,'fx')]:
            for (owner,) in db.execute(f'SELECT DISTINCT {column} FROM {table}').fetchall():
                if owner not in wanted:
                    for before,_ in facts.reconcile(db,table,(column,'day'),[],**{column:owner}):note(kind,owner,before[1])
        cached={s for s in broad if market.cache_path_for(s).name in sources}
        spiked=[]
        companies=[(symbol,'us','USD') for symbol in sorted(broad)]
        companies += [(symbol,market_id,company.get('currency') or market.MARKETS[market_id]['currency'])
                      for market_id,group in foreign_universes.items() for symbol,company in sorted(group.items())]
        annual_endpoints=[endpoint for endpoint,fields in financial_inputs.ENDPOINTS.items()
                          if fields or financial_inputs.observation_fields().get(endpoint)]
        for number,(symbol,market_id,currency) in enumerate(companies,1):
            backtest_control.checkpoint()
            context_changed=old_markets.get(symbol)!=new_markets[symbol]
            changed,content=source_bytes(RAW/'px'/market.cache_path_for(symbol).name,symbol,facts.STOCK,decode=context_changed)
            if changed:
                stock=_readable(facts.stock(RAW,symbol,backtest_control.checkpoint,currency=currency,content=content),'px/'+market.cache_path_for(symbol).name)
                rows=facts.store_stock(db,symbol,stock)
                for before,after in rows:
                    if before is None or after is None or not facts.same_row(before[2:4],after[2:4]):note('prices',symbol,(after or before)[1])
                old=old_sources.get((symbol,facts.STOCK))
                if (old is None or old[3]=='missing')!=(stock['source']['disposition']=='missing'):company_changed(symbol)
                if market_id=='us' and any(states['adjClose']['reason']==facts.INCONSISTENT_SERIES for states in stock['dated'].values()):spiked.append(symbol)
            elif market_id=='us':
                row=db.execute('SELECT adjusted_reason FROM stock_days WHERE symbol=? AND (adjusted IS NOT NULL OR adjusted_reason=?) ORDER BY day LIMIT 1',
                               (symbol,facts.INCONSISTENT_SERIES)).fetchone()
                if row is not None and row[0]==facts.INCONSISTENT_SERIES:spiked.append(symbol)
            if market_id!='us':
                changed,content=source_bytes(market.native_path(RAW,symbol),symbol,'native-price',decode=context_changed)
                if changed:
                    facts.store_native(db,RAW,symbol,backtest_control.checkpoint,content=content)
            annual={}
            for endpoint in annual_endpoints:
                changed,content=source_bytes(financial_inputs.asset_path(RAW,symbol,endpoint),symbol,endpoint,decode=context_changed)
                if changed:annual[endpoint]=content
            if annual:
                old_known={(row[0],row[1]):row[2] for row in db.execute('SELECT endpoint,fiscal,known FROM annual_metadata WHERE symbol=?',(symbol,))}
                resolved=financial_inputs.resolve_history(RAW,symbol,market_id,contents=annual)
                changed=facts.store_annual(db,symbol,resolved)
                new_known={(row[0],row[1]):row[2] for row in db.execute('SELECT endpoint,fiscal,known FROM annual_metadata WHERE symbol=?',(symbol,))}
                for before,after in (*changed['rows'],*changed['metadata']):
                    key=(after or before)[1:3]
                    for known in (old_known.get(key),new_known.get(key)):
                        if known is not None:note('annual',symbol,known)
            progress(kind='research',completed=number,total=len(companies)+1)
            if number%200==0 or number==len(companies):
                print(f'Prepared {number}/{len(companies)} companies',flush=True)
        active={symbol for symbol,_,_ in companies}
        for symbol in {symbol for symbol,_ in old_sources if symbol} - active:
            backtest_control.checkpoint()
            company_changed(symbol)
            for table,keys in [('stock_days',('symbol','day')),('stock_native',('symbol','day')),
                               ('annual_facts',('symbol','endpoint','fiscal')),('annual_metadata',('symbol','endpoint','fiscal'))]:
                facts.reconcile(db,table,keys,[],symbol=symbol)
        for before,after in facts.store_foreign_reports(db,backtest_control.checkpoint):
            note('reports',(after or before)[0],min(row[2] for row in (before,after) if row is not None))
        diagnostics.lap('companies')
        if spiked:
            print(f'Left out {len(spiked)} price series with an isolated price spike: {", ".join(spiked)}',flush=True)
        diagnostics.note(companies=len(cached),spiked_series=len(spiked))
        market_facts={}
        for name,endpoint in (('spy-div.json',facts.CALENDAR),('treasury.json',facts.TREASURY)):
            changed,content=source_bytes(RAW/name,'',endpoint)
            if changed:market_facts[endpoint]=_readable(facts.resolve(RAW/name,endpoint,checkpoint=backtest_control.checkpoint,content=content),name)
        for before,after in facts.store_market(db,market_facts):
            day=(after or before)[0]
            if before is None or after is None or not facts.same_row(before[2:],after[2:]):
                # A SPY-only day carries no Treasury observation.
                if any(row is not None and any(v is not None for v in row[2:]) for row in (before,after)):
                    changes['treasury']=min(changes['treasury'] or day,day)
        for key in old_sources.keys()-seen_sources:
            db.execute('DELETE FROM fact_sources WHERE symbol=? AND endpoint=?',key)
        latest_day=db.execute('SELECT MAX(day) FROM market_days WHERE spy IS NOT NULL').fetchone()[0]
        if latest_day is None:raise ValueError('Saved SPY calendar has no usable sessions.')
        latest_dates={'us':latest_day}
        for market_id in foreign_universes:
            last=db.execute('SELECT MAX(day) FROM local_sessions WHERE market=?',(market_id,)).fetchone()[0]
            if last is not None:latest_dates[market_id]=last
        diagnostics.lap('dated_facts')
        facts.store_valuations(db,None if cold else changes,backtest_control.checkpoint)
        diagnostics.lap('valuations')
        # fact_sources holds the digest of every price, annual, SPY and Treasury file read.
        digest=hashlib.sha256()
        for row in db.execute('SELECT symbol,endpoint,sha256,disposition FROM fact_sources ORDER BY symbol,endpoint'):
            digest.update(json.dumps(list(row),separators=(',',':')).encode()+b'\n')
        raw['sources']=digest.hexdigest()
        record=dict(version=SCHEMA_VERSION,latest_date=str(latest_day),code=code)
        if foreign_universes:record['latest_dates']=latest_dates
        record['content']=hashlib.sha256(facts.encoded(dict(record,raw=raw)).encode()).hexdigest()
        diagnostics.lap('identity')
        if not cold and record['content']==previous['content']:changes=prior.get('changes',changes)
        for key,value in dict(version=SCHEMA_VERSION,inputs=inputs,prices=sources,identity=record,changes=changes).items():
            db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',(key,json.dumps(value)))
        # Reject changing inputs and keep an existing database intact on failure.
        if inputs!=signature() or sources!=price_sources() or code!=code_identity('facts'):
            raise ValueError('Inputs changed during preparation; retry.')
        db.commit()
        diagnostics.lap('commit')
        db.close()
        db=None
        if cold:cache_assets.replace(temporary,path)
        diagnostics.lap('publication')
    except BaseException:
        if db is not None:
            db.rollback()
            db.close()
        if cold:temporary.unlink(missing_ok=True)
        raise
    diagnostics.note(outcome='prepared',database_bytes=path.stat().st_size)
    progress(kind='research',completed=company_count+1,total=company_count+1)
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
