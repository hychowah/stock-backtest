"""Offline research database: companies, reports, typed facts and the latest book.

Every preparation is a full build. It writes a temporary file and replaces the
published database atomically; the previous database stays on any failure.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from bisect import bisect_left, bisect_right
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
SCHEMA_VERSION = 14
# Tables that research and the daily cache both create. Daily copies the first
# five; latest and dated books share screening_metrics and filter_values.
SHARED_SCHEMA = '''
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE companies (symbol TEXT PRIMARY KEY, name TEXT, exchange TEXT, sector TEXT);
CREATE TABLE statements (symbol TEXT, fiscal TEXT, known TEXT, market_cap REAL, enterprise_value REAL, ebitda REAL, ebitda_yield REAL, PRIMARY KEY(symbol,fiscal));
CREATE TABLE financial_inputs (symbol TEXT, fiscal TEXT, values_json TEXT NOT NULL, PRIMARY KEY(symbol,fiscal));
CREATE TABLE treasury10 (day TEXT PRIMARY KEY, yield_percent REAL NOT NULL) WITHOUT ROWID;
CREATE TABLE screening_metrics (mode TEXT, pool TEXT, year INTEGER, symbol TEXT, metric TEXT, multiple REAL NOT NULL, yield_value REAL NOT NULL, PRIMARY KEY(mode,pool,year,symbol,metric));
CREATE TABLE filter_values (mode TEXT, pool TEXT, year INTEGER, symbol TEXT, field TEXT, value REAL NOT NULL, PRIMARY KEY(mode,pool,year,symbol,field));
'''
SCHEMA = SHARED_SCHEMA + '''
CREATE TABLE latest_snapshots (
 pool TEXT, symbol TEXT, candidate_rank INTEGER, fiscal TEXT, known TEXT,
 price_date TEXT, price REAL, market_cap REAL, enterprise_value REAL,
 ebitda_yield REAL, ev_ebitda REAL, spread REAL, PRIMARY KEY(pool,symbol));
CREATE INDEX latest_lookup ON latest_snapshots(pool,ebitda_yield DESC);
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


def bars(payload, key):
    result=[]
    for row in payload:
        value=rules.num(row.get(key))
        try:
            day=date.fromisoformat(str(row.get('date',''))[:10])
        except ValueError:
            continue
        if value is not None and value>0:
            result.append((day,value))
    return sorted(result)


def before(series, day, slack):
    i=bisect_right(series,(day,float('inf')))-1
    return series[i] if i>=0 and (day-series[i][0]).days<=slack else None


def after(series, day, slack):
    i=bisect_left(series,(day,0))
    return series[i] if i<len(series) and (series[i][0]-day).days<=slack else None


def ten_year_yield(db, day):
    """Latest saved 10-year Treasury yield on or before the screen date (%)."""
    row=db.execute('SELECT yield_percent FROM treasury10 WHERE day<=? ORDER BY day DESC LIMIT 1',(str(day),)).fetchone()
    return row[0] if row else None


def latest_snapshot(statement, day, light, div):
    """Value at this exact session; never carry a stopped stock's old price."""
    if statement['known'] >= day or day-statement['fiscal'] > rules.MAX_AGE:
        return None
    adjusted=before(div,day,0)
    fiscal_px=before(light or div,statement['fiscal'],7)
    current_px=before(light or div,day,0)
    if adjusted is None or fiscal_px is None or current_px is None:
        return None
    cap=statement['market_cap']*(current_px[1]/fiscal_px[1])
    ev=cap+(statement['enterprise']-statement['market_cap'])
    ebitda=statement['yield']*statement['enterprise']
    if cap<=0 or ev<=0 or ebitda<=0:
        return None
    return [str(statement['fiscal']),str(statement['known']),str(adjusted[0]),adjusted[1],cap,ev,ebitda/ev,ev/ebitda]


@cache_access.exclusive
@diagnostics.operation('prepare.research')
def prepare(path=DATABASE, force=False):
    """Build the research database from saved files; never download.

    Every build is a full build. A current database is kept unless force is set.
    """
    started=time.perf_counter()
    diagnostics.note(force=force)
    path=Path(path)
    # The removed January report publication left this journal; nothing reads it.
    path.with_name(path.name+'.publication.json').unlink(missing_ok=True)
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
    all_spy=market.load_bars(RAW/'spy-div.json','adjClose')
    yields=[]
    treasury_rows=json.loads((RAW/'treasury.json').read_text())
    for r in treasury_rows:
        day,value=rules.parse_day(r.get('date')),rules.num(r.get('month3'))
        if day is not None and value is not None:
            yields.append((day,value/100))
    yields.sort()
    records,invalid=cache_assets.financial_records(RAW/'metrics.jsonl')
    if invalid:raise ValueError('Annual financial cache contains invalid records. Use the data panel to repair annual financials.')
    broad=books.statements(records,universe)
    financials=[(symbol,str(row['fiscal']),str(row['known']),row['market_cap'],row['enterprise'],row['ebitda'],row['yield'])
                for symbol,rows in broad.items() for row in rows]
    broad,book=books.pools(broad)
    latest_day=all_spy[-1][0]
    active={s for s,r in universe.items() if r.get('listed') is True}
    latest_statements,latest_ranks=books.candidates(tuple({s:rows for s,rows in pool.items() if s in active} for pool in (broad,book)),latest_day)
    latest_meta=dict(asof=str(latest_day),active_universe=len(active),eligible_financials=len(latest_statements['cached']),legacy_candidates=len(latest_ranks))
    latest_treasury=market.asof_yield(yields,latest_day)
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
        db.executemany('INSERT OR REPLACE INTO treasury10 VALUES(?,?)',
                       [(str(day),value) for row in treasury_rows
                        if (day:=rules.parse_day(row.get('date'))) is not None
                        and (value:=rules.num(row.get('year10'))) is not None])
        latest_treasury10=ten_year_yield(db,latest_day)
        db.executemany('INSERT INTO companies VALUES(?,?,?,?)',[(s,r.get('name') or 'Unavailable',r.get('exchange') or 'Unavailable',r.get('sector') or 'Unavailable') for s,r in universe.items()])
        db.executemany('INSERT OR REPLACE INTO statements VALUES(?,?,?,?,?,?,?)',financials)
        # Denials are first-class preparation facts: every company and pool has
        # a latest-root decision, with its reason.
        latest_admission={}
        for symbol,company in universe.items():
            for pool in ('cached','legacy'):
                statement=latest_statements[pool].get(symbol)
                latest_admission[(symbol,pool)]=dict(candidate_rank=latest_ranks.get(symbol),
                    admitted=False,reason='MISSING_PRICE' if statement is not None else 'NO_ELIGIBLE_REPORT',
                    statement=None if statement is None else {key:str(statement[key]) for key in ('fiscal','known')},
                    valuation=None)
                if company.get('listed') is not True:
                    latest_admission[(symbol,pool)]['reason']='NOT_LISTED'
        cached_symbols=sorted(s for s in broad if market.cache_path_for(s).name in sources)
        for number,symbol in enumerate(cached_symbols,1):
            # The facts identity binds each price file's bytes. An unlisted
            # company has no latest root, so its prices are not parsed here.
            content=market.cache_path_for(symbol).read_bytes()
            units[symbol]=hashlib.sha256(content).hexdigest()
            div=None
            if symbol in active:
                payload=json.loads(content)
                light=[]
                for r in payload.get('light') or []:
                    value=r.get('price') if r.get('price') is not None else r.get('close')
                    light.extend(bars([dict(date=r.get('date'),value=value)],'value'))
                light.sort()
                div=bars(payload.get('div') or [],'adjClose')
                for pool in ['legacy','cached']:
                    statement=latest_statements[pool].get(symbol)
                    candidate=latest_ranks.get(symbol)
                    if statement is None or (pool=='legacy' and candidate is None):
                        continue
                    row=latest_snapshot(statement,latest_day,light,div)
                    evidence=latest_admission[(symbol,pool)]
                    adjusted=before(div,latest_day,0)
                    fiscal_px=before(light or div,statement['fiscal'],7)
                    current_px=before(light or div,latest_day,0)
                    if row is None:
                        if adjusted is not None and fiscal_px is not None and current_px is not None:
                            evidence['reason']='NONPOSITIVE_VALUATION'
                        continue
                    evidence['valuation']=dict(market_cap=row[4],enterprise_value=row[5],
                        ebitda=statement['yield']*statement['enterprise'])
                    if pool=='legacy' and (row[4]<rules.MIN_MARKET_CAP or row[5]<rules.MIN_EV):
                        evidence['reason']='POOL_INELIGIBLE';continue
                    evidence.update(admitted=True,reason=None)
                    db.execute('INSERT INTO latest_snapshots VALUES('+','.join('?'*12)+')',[pool,symbol,candidate]+row+[row[6]-(latest_treasury or 0.)])
            resolved=financial_inputs.resolve_history(RAW,symbol)
            financial_history=resolved['values']
            facts.store_annual(db,symbol,resolved)
            db.executemany('INSERT INTO financial_inputs VALUES(?,?,?)',[(symbol,fiscal,json.dumps(values)) for fiscal,values in financial_history.items()])
            history=[dict(fiscal=str(row['fiscal']),ebitda=row['ebitda']) for row in broad[symbol]]
            def lookup(day,column,forward,slack):
                return (after if forward else before)(div,day,slack)
            for saved in db.execute('SELECT * FROM latest_snapshots WHERE symbol=?',(symbol,)).fetchall():
                observation=dict(saved)
                pairs=metrics.evaluate(observation,history)
                values=metrics.filter_values(observation,pairs,date.fromisoformat(saved['price_date']),lookup,financial_history,latest_treasury10)
                db.executemany('INSERT INTO filter_values VALUES(?,?,?,?,?,?)',
                    [('latest',saved['pool'],0,symbol,key,value) for key,value in values.items()])
            if number%200==0 or number==len(cached_symbols):
                print(f'Prepared {number}/{len(cached_symbols)} cached companies',flush=True)
        diagnostics.lap('companies')
        diagnostics.note(companies=len(cached_symbols))
        for symbol in sorted(set(broad)-set(cached_symbols)):
            facts.store_annual(db,symbol,financial_inputs.resolve_history(RAW,symbol))
        for (symbol,pool),evidence in latest_admission.items():
            facts.store_latest(db,symbol,pool,evidence)
        for symbol in sorted(broad):
            backtest_control.checkpoint()
            facts.store_stock(db,symbol,facts.stock(RAW,symbol,backtest_control.checkpoint))
        facts.store_market(db,facts.shared(RAW,backtest_control.checkpoint))
        diagnostics.lap('dated_facts')
        prepare_metrics(db)
        diagnostics.lap('metrics')
        scopes=[dict(mode='latest',pool=pool,context_date=str(latest_day),book=0) for pool in ('legacy','cached')]
        # Rows follow from the raw signature and each price file's bytes.
        facts.finish(db,latest_day,scopes=scopes,inputs=dict(signature=inputs,prices=units))
        diagnostics.lap('facts_finish')
        for key,value in dict(version=SCHEMA_VERSION,inputs=inputs,prices=sources,latest=latest_meta).items():
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


def prepare_metrics(db):
    """Publish ready-to-rank latest values for each pool and company.

    The selected fiscal report bounds history; its availability and screening
    eligibility were established when preparing the observation. Latest rows
    use year 0. Dated books store their own values (engines/original/schedules.py).
    """
    metrics.validate_catalog()
    histories={}
    for row in db.execute('SELECT * FROM statements ORDER BY symbol,fiscal'):
        histories.setdefault(row['symbol'],[]).append(dict(row))
    db.execute('DELETE FROM screening_metrics')
    values=[]
    for row in db.execute('SELECT * FROM latest_snapshots'):
        observation=dict(row)
        for metric,pair in metrics.evaluate(observation,histories.get(row['symbol'],[])).items():
            values.append(('latest',row['pool'],observation.get('year',0),row['symbol'],metric,*pair))
    db.executemany('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',values)


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
    with closing(connect(args.database)) as db:
        latest=json.loads(db.execute("SELECT value FROM metadata WHERE key='latest'").fetchone()[0])
        counts=dict(db.execute('SELECT pool,COUNT(*) FROM latest_snapshots GROUP BY pool').fetchall())
    print(f'Database: {args.database.stat().st_size/1e6:.1f} MB')
    print(f"Latest session {latest['asof']}: {latest['eligible_financials']} active names with eligible financials; "
          f"{counts.get('cached',0)} valued with cached prices, {counts.get('legacy',0)} in the original candidate set.")


if __name__=='__main__':
    try:
        main()
    except (ValueError,sqlite3.Error) as error:
        raise SystemExit(str(error))
