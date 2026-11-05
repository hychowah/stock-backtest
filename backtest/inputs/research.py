"""Offline January research database and configurable equal-weight backtests."""
from __future__ import annotations

import argparse
from contextlib import closing
from bisect import bisect_left, bisect_right
import csv
import hashlib
from datetime import date, timedelta
import json
import os
import platform
import stat
from pathlib import Path
import sqlite3
import statistics
import time

from backtest.financial import rules
from backtest.inputs import market, cache_assets
from backtest.engines.reference import legacy
from backtest import screening, selection
from backtest.financial import metrics as metrics
from backtest.financial import books as books
from backtest.inputs import financial_inputs as financial_inputs
from backtest.inputs import observation_inputs, dated_observation_inputs
from backtest.runtime import backtest_control
from backtest.runtime import diagnostics
from backtest.runtime import cache_access as cache_access
from backtest.engines.reference import revalue as revalue
from backtest.inputs import baseline as baseline
from backtest.paths import ROOT, RAW, RESULTS

DATABASE = ROOT / 'data' / 'research.sqlite'
SCHEMA_VERSION = 11
SCHEMA = '''
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE companies (symbol TEXT PRIMARY KEY, name TEXT, exchange TEXT, sector TEXT);
CREATE TABLE statements (symbol TEXT, fiscal TEXT, known TEXT, market_cap REAL, enterprise_value REAL, ebitda REAL, ebitda_yield REAL, PRIMARY KEY(symbol,fiscal));
CREATE TABLE financial_inputs (symbol TEXT, fiscal TEXT, values_json TEXT NOT NULL, PRIMARY KEY(symbol,fiscal));
CREATE TABLE treasury10 (day TEXT PRIMARY KEY, yield_percent REAL NOT NULL) WITHOUT ROWID;
CREATE TABLE screening_metrics (mode TEXT, pool TEXT, year INTEGER, symbol TEXT, metric TEXT, multiple REAL NOT NULL, yield_value REAL NOT NULL, PRIMARY KEY(mode,pool,year,symbol,metric));
CREATE TABLE filter_values (mode TEXT, pool TEXT, year INTEGER, symbol TEXT, field TEXT, value REAL NOT NULL, PRIMARY KEY(mode,pool,year,symbol,field));
CREATE TABLE baseline_prices (year INTEGER, symbol TEXT, fiscal_price_date TEXT, valuation_date TEXT, fiscal_price REAL, valuation_price REAL, entry_price REAL, exit_price REAL, PRIMARY KEY(year,symbol));
CREATE TABLE baseline_periods (year INTEGER PRIMARY KEY, spy_entry TEXT, spy_exit TEXT, spy_entry_price REAL, spy_exit_price REAL);
CREATE TABLE periods (year INTEGER PRIMARY KEY, entry TEXT, exit TEXT, spy REAL, treasury REAL, legacy_candidates INTEGER, cached_candidates INTEGER);
CREATE TABLE snapshots (
 pool TEXT, year INTEGER, symbol TEXT, candidate_rank INTEGER,
 fiscal TEXT, entry TEXT, exit TEXT, market_cap REAL, enterprise_value REAL,
 ebitda REAL, ebitda_yield REAL, ev_ebitda REAL, spread REAL,
 return_value REAL, status TEXT, PRIMARY KEY(pool,year,symbol));
CREATE INDEX screen_lookup ON snapshots(pool,year,ebitda_yield DESC);
CREATE TABLE latest_snapshots (
 pool TEXT, symbol TEXT, candidate_rank INTEGER, fiscal TEXT, known TEXT,
 price_date TEXT, price REAL, market_cap REAL, enterprise_value REAL,
 ebitda_yield REAL, ev_ebitda REAL, spread REAL, PRIMARY KEY(pool,symbol));
CREATE INDEX latest_lookup ON latest_snapshots(pool,ebitda_yield DESC);
''' + observation_inputs.SCHEMA


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


def signature():
    """Return the current ordered input signature and report cutoff.

    Every call discovers and inspects inputs afresh. Keys preserve lexical
    paths relative to ROOT; discovery and metadata failures retain their
    existing precedence. No inventory or derived prefix survives the call.
    """
    paths = [RAW/n for n in ['universe.json','metrics.jsonl','spy-div.json','treasury.json']]
    paths += [RAW/'px'] + calculation_sources()
    entries = [(path, path.stat()) for path in paths]
    ledger_path = RAW/'download-coverage.json'
    if ledger_path.exists():
        entries.append((ledger_path, ledger_path.stat()))
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
    return dict(result, historical_through=str(baseline.cutoff((RESULTS/'summary-exits.txt').read_text(encoding='utf-8'))))


def price_sources():
    return {p.name: [info.st_size,info.st_mtime_ns] for p,info in _metadata_entries(RAW/'px', '*.json')}


def calculation_sources():
    """Source files whose content establishes prepared rows and their check.

    Download transport and the daily cache do not compute research rows, so
    editing them does not force a research rebuild.
    """
    here = Path(__file__)
    return [Path(baseline.__file__), here, Path(metrics.__file__), Path(books.__file__), Path(rules.__file__), Path(screening.__file__), Path(selection.__file__), Path(cache_assets.__file__), Path(market.__file__), Path(legacy.__file__), Path(revalue.__file__),
            Path(financial_inputs.__file__), Path(observation_inputs.__file__),
            Path(financial_inputs.parameters.__file__), Path(dated_observation_inputs.__file__), Path(observation_inputs.measure_observations.__file__)]


# Historical forward price lookups start at a January entry and reach at most
# books.FORWARD_REACH; exit lookups read backward from a day on or before the
# report cutoff. REUSE_MARGIN is a wider margin: rows after the later of the
# cutoff and the last entry + REUSE_MARGIN can change only latest and dated units.
REUSE_MARGIN = timedelta(days=31)


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows_digest(rows):
    return hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest()


def _beyond(row, horizon):
    """True only when both saved-date readers place the row after the horizon."""
    if not isinstance(row,dict):
        return False
    value=row.get('date')
    try:
        iso=date.fromisoformat(str(value)[:10])
    except ValueError:
        return False
    if iso<=horizon:
        return False
    day=rules.parse_day(value)
    return day is not None and day>horizon


def _bounded_digest(payload, horizon, key=None):
    """Digest the saved rows that a historical calculation can read.

    Drop rows dated after the horizon from the row list, or only from
    payload[key]. Keep everything else bound, including undated rows and the
    complete light series, whose presence selects the valuation scale. Saved
    key order is kept: a reordered file only costs a recalculation.
    """
    if key is None:
        value=[row for row in payload if not _beyond(row,horizon)] if isinstance(payload,list) else payload
    elif isinstance(payload,dict) and isinstance(payload.get(key),list):
        value=dict(payload,**{key:[row for row in payload[key] if not _beyond(row,horizon)]})
    else:
        value=payload
    return _rows_digest(value)


def _reuse_scope(through, horizon, treasury_rows):
    """Identify every shared input of historical rows and of the reference check.

    The interpreter and SQLite versions are bound too: date parsing and the
    order of unsorted queries may change with either of them.
    """
    return _digest(dict(
        version=SCHEMA_VERSION, observations=observation_inputs.VERSION, through=str(through),
        runtime=[platform.python_implementation(),platform.python_version(),sqlite3.sqlite_version],
        code=[_file_digest(path) for path in calculation_sources()],
        universe=_file_digest(RAW/'universe.json'), metrics=_file_digest(RAW/'metrics.jsonl'),
        financial={path.relative_to(RAW).as_posix():[info.st_size,info.st_mtime_ns]
                   for path,info in _metadata_entries(RAW/'financial-inputs','*/*.json')},
        spy=_bounded_digest(json.loads((RAW/'spy-div.json').read_text()),horizon),
        treasury=_bounded_digest(treasury_rows,horizon)))


class _PriorUnits:
    """Company units of the published database that a new build may copy.

    The prior database is attached read-only only when its reuse scope equals
    the current scope. Copied rows keep their original order, so the new
    database equals a full rebuild row for row. Callers end the transaction
    before finish() detaches the prior database.
    """
    SPANS = ('snapshots','baseline_prices','filter_values')

    @classmethod
    def open(cls, db, path, owner, scope):
        if not path.exists():
            return None
        location=path.resolve().as_uri()+'?mode=ro'
        try:
            with closing(sqlite3.connect(location,uri=True)) as prior:
                owner.check_ready(prior)
                meta={key:json.loads(value) for key,value in prior.execute(
                    "SELECT key,value FROM metadata WHERE key IN ('reuse','baseline_result')")}
        except (sqlite3.Error,ValueError,OSError):
            return None
        # The scope binds this source and schema, so an equal scope means this
        # code wrote the units in their current form.
        reuse=meta.get('reuse')
        if not isinstance(reuse,dict) or reuse.get('scope')!=scope:
            return None
        db.execute('ATTACH DATABASE ? AS prior',(location,))
        return cls(db,reuse['symbols'],meta.get('baseline_result'))

    def __init__(self, db, units, baseline_result):
        self.db,self.units,self.baseline=db,units,baseline_result
        self.spans={}
        for table in self.SPANS:
            for symbol,low,high,count in db.execute(f'SELECT symbol,min(rowid),max(rowid),count(*) FROM prior.{table} GROUP BY symbol'):
                self.spans.setdefault(symbol,{})[table]=(low,high) if high-low+1==count else None
        self.history,self.sources,self.dated=set(),set(),set()

    def copy_history(self, symbol, digest):
        """Copy one company's historical rows when its readable prices are equal."""
        spans=self.spans.get(symbol,{})
        unit=self.units.get(symbol)
        if unit is None or unit['history']!=digest or None in spans.values():
            return False
        for table,span in spans.items():
            # The unary + keeps SQLite on the rowid range; a mode index would
            # scan every historical row of every company for each company.
            self.db.execute(f'INSERT INTO {table} SELECT * FROM prior.{table} WHERE rowid BETWEEN ? AND ?'
                            +(" AND +mode='historical'" if table=='filter_values' else '')+' ORDER BY rowid',span)
        self.history.add(symbol)
        return True

    def prepended(self, symbol, rows):
        """Return how many rows a download added before the unchanged saved rows.

        SeriesAsset saves rows newest first, so a daily download moves every
        earlier row by the same number of places. Return None for any other change.
        """
        known=self.units.get(symbol)
        known=known['rows'] if known is not None else None
        if not isinstance(rows,list) or known is None or not len(rows)>known[0]:
            return None
        offset=len(rows)-known[0]
        return offset if _rows_digest(rows[offset:])==known[1] else None

    def shifted(self, symbol, offset, days):
        """Return the prior day evidence of moved rows, except days the new rows touch.

        Return None when any stored day cannot be moved exactly.
        """
        moved=[]
        for row in self.db.execute('SELECT * FROM prior.observation_dated WHERE symbol=? AND endpoint=?',
                                   (symbol,dated_observation_inputs.STOCK)):
            if row[2] in days:
                continue
            document=dated_observation_inputs.shifted(row[3],offset)
            if document is None:
                return None
            moved.append(observation_inputs._prepared_record((row[0],row[1],row[2],document)))
        return moved

    def copy_dated(self, symbol, unit):
        """Batch the dated rows of equal bytes; return whether the source row is copied too.

        Dated rows depend only on the file bytes. The source row also holds the
        coverage receipt, so it is copied only when that receipt is unchanged.
        Return None when the caller must resolve the file completely.
        """
        known=self.units.get(symbol)
        if known is None or known['content']!=unit['content']:
            return None
        self.dated.add(symbol)
        if known['receipt']!=unit['receipt']:
            return False
        self.sources.add(symbol)
        return True

    def finish(self):
        """Copy batched observation units, commit and release the prior database."""
        self.db.execute('CREATE TEMP TABLE reused(kind TEXT,symbol TEXT,PRIMARY KEY(kind,symbol)) WITHOUT ROWID')
        self.db.executemany('INSERT INTO temp.reused VALUES(?,?)',[(kind,s) for kind,symbols in
            (('history',self.history),('source',self.sources),('dated',self.dated)) for s in symbols])
        self.db.execute("""INSERT INTO observation_measure_contexts SELECT * FROM prior.observation_measure_contexts
                           WHERE mode='historical' AND symbol IN (SELECT symbol FROM temp.reused WHERE kind='history')""")
        for table,kind in (('observation_sources','source'),('observation_dated','dated')):
            self.db.execute(f"""INSERT INTO {table} SELECT * FROM prior.{table}
                                WHERE endpoint=? AND symbol IN (SELECT symbol FROM temp.reused WHERE kind=?)""",
                            (dated_observation_inputs.STOCK,kind))
        self.db.commit()
        self.db.execute('DROP TABLE temp.reused')
        self.db.execute('DETACH DATABASE prior')


def prepared_price_binding(path=DATABASE):
    """Identify the price inventory accepted by committed research metadata.

    Read no raw price files. Preparation owns inventory validation; ordinary
    daily-cache checks bind to that validated prerequisite without rescanning it.
    """
    with closing(connect(path)) as db:
        return _price_binding(db)


def prepared_bindings(path=DATABASE):
    """Return the price and observation bindings from one connection.

    The caller compares signature() itself, so this connection skips it. The
    observation binding is the metadata, including the content identity that
    preparation recorded; the app is the only writer and holds the cache lock.
    """
    with closing(connect(path, check=False)) as db:
        return _price_binding(db), observation_inputs.require(db)


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
        baseline.Baseline(RESULTS,path).check_ready(db)
        meta={r['key']:json.loads(r['value']) for r in db.execute("SELECT * FROM metadata WHERE key IN ('version','inputs','prices')")}
        if meta.get('version') != SCHEMA_VERSION:
            raise ValueError('Database version changed; run research.py prepare')
        if check and (meta.get('inputs')!=signature() or (full_prices and meta.get('prices')!=price_sources())):
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


def snapshot(statement, entry_day, exit_day, light, div, bankruptcy, lookup_evidence=None):
    def lookup(day,column,forward,slack):
        series=(light or div) if column=='price' else div
        result=(after if forward else before)(series,day,slack)
        if lookup_evidence is not None:
            lookup_evidence.append(dict(requested_date=str(day),column=column,forward=forward,slack=slack,
                observation=[str(result[0]),result[1]] if result else None))
        return result
    return books.snapshot(statement,entry_day,exit_day,lookup,bankruptcy)


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
    started=time.perf_counter()
    diagnostics.note(force=force)
    path=Path(path)
    owner=baseline.Baseline(RESULTS,path)
    owner.recover()
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
    try:
        ledger=cache_assets.read_json(RAW/'download-coverage.json',{})
    except (ValueError, UnicodeDecodeError):
        ledger={}
    if not isinstance(ledger,dict):ledger={}
    universe={r['symbol']:r for r in json.loads((RAW/'universe.json').read_text())}
    # Reuse the current selection semantics, including the 250-name pre-price buffer.
    book={}
    all_spy=market.load_bars(RAW/'spy-div.json','adjClose')
    historical_end=owner.through()
    spy=[row for row in all_spy if row[0]<=historical_end]
    sessions=[d for d,_ in spy]
    yields=[]
    treasury_rows=json.loads((RAW/'treasury.json').read_text())
    for r in treasury_rows:
        day,value=rules.parse_day(r.get('date')),rules.num(r.get('month3'))
        if day is not None and value is not None:
            yields.append((day,value/100))
    yields.sort()
    legacy={}
    ranks={}
    records,invalid=cache_assets.financial_records(RAW/'metrics.jsonl')
    if invalid:raise ValueError('Annual financial cache contains invalid records. Use the data panel to repair annual financials.')
    broad=books.statements(records,universe)
    financials=[(symbol,str(row['fiscal']),str(row['known']),row['market_cap'],row['enterprise'],row['ebitda'],row['yield'])
                for symbol,rows in broad.items() for row in rows]
    broad,book=books.pools(broad)
    for year in range(rules.FIRST_YEAR,rules.LAST_YEAR+1):
        entry=market.session_on_or_after(sessions,date(year,1,1))
        if entry is not None and entry<=rules.ASOF and market.asof_yield(yields,entry) is not None:
            _,ranks[year]=books.candidates((broad,book),entry)
            legacy[year]=ranks[year]
    periods={}
    for year in legacy:
        entry=market.session_on_or_after(sessions,date(year,1,1))
        end=market.session_on_or_after(sessions,date(year+1,1,1)) if year<rules.LAST_YEAR else sessions[-1]
        a,b=after(spy,entry,4),before(spy,end,4)
        periods[year]=(entry,end,books.benchmark_return(a[1],b[1]),market.asof_yield(yields,entry))
    horizon=max([historical_end]+[entry+REUSE_MARGIN for entry,*_ in periods.values()])
    scope=_reuse_scope(historical_end,horizon,treasury_rows)
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
        db.executescript(SCHEMA)
        # A company unit whose inputs are unchanged is copied from the published,
        # verified database. A forced preparation always recalculates.
        prior=None if force else _PriorUnits.open(db,path,owner,scope)
        units,rebuilt,shifts={},set(),{}
        db.executemany('INSERT OR REPLACE INTO treasury10 VALUES(?,?)',
                       [(str(day),value) for row in treasury_rows
                        if (day:=rules.parse_day(row.get('date'))) is not None
                        and (value:=rules.num(row.get('year10'))) is not None])
        treasury10_by_day={day:ten_year_yield(db,day) for day in {latest_day}|{p[0] for p in periods.values()}}
        db.executemany('INSERT INTO companies VALUES(?,?,?,?)',[(s,r.get('name') or 'Unavailable',r.get('exchange') or 'Unavailable',r.get('sector') or 'Unavailable') for s,r in universe.items()])
        db.executemany('INSERT OR REPLACE INTO statements VALUES(?,?,?,?,?,?,?)',financials)
        # Denials are first-class preparation facts. They cannot be mistaken for
        # an old projection that never established latest-root admission.
        latest_admission={}
        for symbol,company in universe.items():
            for pool in ('cached','legacy'):
                statement=latest_statements[pool].get(symbol)
                candidate=latest_ranks.get(symbol)
                latest_admission[(symbol,pool)]=dict(root_date=str(latest_day),
                    listed=company.get('listed') is True,candidate_rank=candidate,
                    candidate=statement is not None and (pool!='legacy' or candidate is not None),
                    admitted=False,reason='MISSING_PRICE' if statement is not None else 'NO_ELIGIBLE_REPORT',
                    statement=None if statement is None else {key:str(value) if isinstance(value,date) else value for key,value in statement.items()},
                    adjusted_price=None,fiscal_price=None,valuation_price=None,valuation=None)
                if company.get('listed') is not True:
                    latest_admission[(symbol,pool)]['reason']='NOT_LISTED'
        for year,(entry,end,spy_return,treasury) in periods.items():
            count=sum(rules.latest_statement(rs,entry) is not None for rs in broad.values())
            db.execute('INSERT INTO periods VALUES(?,?,?,?,?,?,?)',(year,str(entry),str(end),spy_return,treasury,len(legacy[year]),count))
            a,b=after(spy,entry,4),before(spy,end,4)
            db.execute('INSERT INTO baseline_periods VALUES(?,?,?,?,?)',(year,str(a[0]),str(b[0]),a[1],b[1]))
        cached_symbols=sorted(s for s in broad if market.cache_path_for(s).name in sources)
        total=reused=0
        for number,symbol in enumerate(cached_symbols,1):
            valuation_evidence={}
            location=market.cache_path_for(symbol);name=location.name
            # File bytes, never the file stamp, decide reuse: downloads rewrite
            # checked files with equal bytes, and a copy can keep old stamps.
            # Equal bytes of an unlisted company are not parsed: it has no
            # latest root.
            content=_file_digest(location)
            unchanged=prior is not None and symbol in prior.units and prior.units[symbol]['content']==content
            payload=None if unchanged and symbol not in active else json.loads(location.read_text())
            rows=payload.get('div') if isinstance(payload,dict) else None
            unit=units[symbol]=dict(content=content,
                history=prior.units[symbol]['history'] if unchanged else _bounded_digest(payload,horizon,'div'),
                receipt=_digest(ledger.get('px/'+name)),
                rows=prior.units[symbol]['rows'] if unchanged else [len(rows),_rows_digest(rows)] if isinstance(rows,list) else None)
            offset=None if unchanged or prior is None else prior.prepended(symbol,rows)
            if offset is not None:
                shifts[symbol]=offset,{day for row in rows[:offset] if (day:=dated_observation_inputs.row_day(row)) is not None}
            if prior is not None and prior.copy_history(symbol,unit['history']):
                reused+=1
            else:
                rebuilt.add(symbol)
                if payload is None:
                    payload=json.loads(location.read_text())
            light=div=None
            if payload is not None:
                light=[]
                for r in payload.get('light') or []:
                    value=r.get('price') if r.get('price') is not None else r.get('close')
                    light.extend(bars([dict(date=r.get('date'),value=value)],'value'))
                light.sort()
                div=bars(payload.get('div') or [],'adjClose')
            inserts=[]
            for year,(entry,end,_,treasury) in (periods.items() if symbol in rebuilt else ()):
                for pool,statements in [('legacy',book.get(symbol,[])),('cached',broad[symbol])]:
                    candidate=ranks[year].get(symbol)
                    if pool=='legacy' and candidate is None:
                        continue
                    statement=rules.latest_statement(statements,entry)
                    if statement is None:
                        continue
                    valuation_lookups=[]
                    row=snapshot(statement,entry,end,light,div,(year,symbol) in rules.BANKRUPT,valuation_lookups)
                    if row is None:
                        continue
                    fiscal,entry_date,exit_date,cap,ev,ebitda,earnings_yield,multiple,ret,status=row
                    # Original rescale rejects buy-date caps before ranking.
                    if not books.eligible(pool,cap,ev):
                        continue
                    valuation_evidence[('historical',pool,str(entry),symbol)]=dict(lookups=valuation_lookups, statement={key:str(value) if isinstance(value,date) else value for key,value in statement.items()})
                    inserts.append((pool,year,symbol,candidate,fiscal,entry_date,exit_date,cap,ev,ebitda,earnings_yield,multiple,earnings_yield-treasury,ret,status))
                    if pool=='legacy':
                        fiscal_px=before(light or div,statement['fiscal'],7)
                        valuation_px=after(light or div,entry,4)
                        entry_px=after(div,date.fromisoformat(entry_date),0)
                        exit_px=before(div,date.fromisoformat(exit_date),0)
                        db.execute('INSERT INTO baseline_prices VALUES(?,?,?,?,?,?,?,?)',(year,symbol,str(fiscal_px[0]),str(valuation_px[0]),fiscal_px[1],valuation_px[1],entry_px[1],exit_px[1]))
            db.executemany('INSERT INTO snapshots VALUES('+','.join('?'*15)+')',inserts)
            total+=len(inserts)
            if symbol in active:
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
                    evidence.update(adjusted_price=None if adjusted is None else [str(adjusted[0]),adjusted[1]],
                        fiscal_price=None if fiscal_px is None else [str(fiscal_px[0]),fiscal_px[1]],
                        valuation_price=None if current_px is None else [str(current_px[0]),current_px[1]])
                    if row is None:
                        if adjusted is not None and fiscal_px is not None and current_px is not None:
                            evidence['reason']='NONPOSITIVE_VALUATION'
                        continue
                    evidence['valuation']=dict(market_cap=row[4],enterprise_value=row[5],
                        ebitda=statement['yield']*statement['enterprise'])
                    if pool=='legacy' and (row[4]<rules.MIN_MARKET_CAP or row[5]<rules.MIN_EV):
                        evidence['reason']='POOL_INELIGIBLE';continue
                    evidence.update(admitted=True,reason=None)
                    valuation_evidence[('latest',pool,str(latest_day),symbol)]=dict(lookups=[dict(requested_date=str(statement['fiscal']),column='price',forward=False,slack=7,observation=evidence['fiscal_price']),dict(requested_date=str(latest_day),column='price',forward=False,slack=0,observation=evidence['valuation_price']),dict(requested_date=str(latest_day),column='adjusted',forward=False,slack=0,observation=evidence['adjusted_price'])],statement=evidence['statement'])
                    db.execute('INSERT INTO latest_snapshots VALUES('+','.join('?'*12)+')',[pool,symbol,candidate]+row+[row[6]-(latest_treasury or 0.)])
            resolved=financial_inputs.resolve_history(RAW,symbol)
            financial_history=resolved['values']
            observation_inputs.store_annual(db,symbol,resolved)
            db.executemany('INSERT INTO financial_inputs VALUES(?,?,?)',[(symbol,fiscal,json.dumps(values)) for fiscal,values in financial_history.items()])
            history=[dict(fiscal=str(row['fiscal']),ebitda=row['ebitda']) for row in broad[symbol]]
            lookup_calls=[]
            def lookup(day,column,forward,slack):
                result=(after if forward else before)(div,day,slack)
                lookup_calls.append(dict(requested_date=str(day),column=column,forward=forward,slack=slack,observation=[str(result[0]),result[1]] if result else None))
                return result
            for mode,table,day_key in [('historical','snapshots','entry'),('latest','latest_snapshots','price_date')]:
                if mode=='historical' and symbol not in rebuilt:
                    continue
                for saved in db.execute('SELECT * FROM '+table+' WHERE symbol=?',(symbol,)).fetchall():
                    observation=dict(saved)
                    pairs=metrics.evaluate(observation,history)
                    screen_day=date.fromisoformat(saved[day_key])
                    treasury_day=periods[saved['year']][0] if mode=='historical' else latest_day
                    lookup_calls.clear()
                    values=metrics.filter_values(observation,pairs,screen_day,lookup,financial_history,treasury10_by_day[treasury_day])
                    scope_day=str(periods[saved['year']][0]) if mode=='historical' else str(latest_day)
                    treasury_row=db.execute('SELECT day,yield_percent FROM treasury10 WHERE day<=? ORDER BY day DESC LIMIT 1',(str(treasury_day),)).fetchone()
                    measure_evidence=dict(screen_date=str(screen_day), treasury_requested_date=str(treasury_day), treasury_selected=[treasury_row[0],treasury_row[1]] if treasury_row else None, lookups=list(lookup_calls), valuation=valuation_evidence[(mode,saved['pool'],scope_day,symbol)])
                    db.execute('INSERT INTO observation_measure_contexts VALUES(?,?,?,?,?)',
                        observation_inputs._prepared_record((mode,saved['pool'],scope_day,symbol,observation_inputs.encoded(observation_inputs.measure_observations.detached(measure_evidence)))))
                    db.executemany('INSERT INTO filter_values VALUES(?,?,?,?,?,?)',
                        [(mode,saved['pool'],observation.get('year',0),symbol,key,value) for key,value in values.items()])
            if number%200==0 or number==len(cached_symbols):
                print(f'Prepared {number}/{len(cached_symbols)} cached companies; {total:,} new January snapshots; {reused:,} companies reused',flush=True)
        diagnostics.lap('companies')
        diagnostics.note(companies=len(cached_symbols),companies_reused=reused,companies_rebuilt=len(rebuilt),snapshots_new=total)
        for symbol in sorted(set(broad)-set(cached_symbols)):
            observation_inputs.store_annual(db,symbol,financial_inputs.resolve_history(RAW,symbol))
        for (symbol,pool),evidence in latest_admission.items():
            observation_inputs.store_latest(db,symbol,pool,evidence)
        for symbol in sorted(broad):
            backtest_control.checkpoint()
            copied=prior.copy_dated(symbol,units[symbol]) if symbol in units and prior is not None else None
            if copied:
                continue
            # Equal bytes keep every day; prepended rows touch only their own days.
            shift=shifts.get(symbol) if copied is None else None
            moved=prior.shifted(symbol,*shift) if shift else None
            days=() if copied is False else shift[1] if moved is not None else None
            resolution=dated_observation_inputs.stock(RAW,symbol,ledger,backtest_control.checkpoint,days=days)
            if days is not None and resolution['source']['sha256']!=units[symbol]['content']:
                raise ValueError('Dated observation source changed during preparation.')
            observation_inputs.store_dated(db,symbol,dated_observation_inputs.STOCK,resolution,backtest_control.checkpoint)
            if moved:
                db.executemany('INSERT INTO observation_dated VALUES(?,?,?,?)',moved)
        for endpoint,resolution in dated_observation_inputs.shared(RAW,ledger,backtest_control.checkpoint).items():
            observation_inputs.store_dated(db,'',endpoint,resolution,backtest_control.checkpoint)
        diagnostics.lap('observations')
        prepare_metrics(db)
        diagnostics.lap('metrics')
        scopes=[dict(mode='historical',pool=pool,context_date=str(period[0]),book=year)
                for year,period in periods.items() for pool in ('legacy','cached')]
        scopes += [dict(mode='latest',pool=pool,context_date=str(latest_day),book=0)
                   for pool in ('legacy','cached')]
        for mode,pool,scope_day,symbol,document in db.execute('SELECT * FROM observation_measure_contexts'):
            backtest_control.checkpoint()
            evidence=json.loads(document)
            year=next(scope['book'] for scope in scopes if scope['mode']==mode and scope['pool']==pool and scope['context_date']==scope_day)
            table='snapshots' if mode=='historical' else 'latest_snapshots'
            saved=db.execute('SELECT * FROM '+table+' WHERE pool=? AND symbol=?'+(' AND year=?' if mode=='historical' else ''),
                (pool,symbol,year) if mode=='historical' else (pool,symbol)).fetchone()
            evidence['snapshot']=dict(saved)
            evidence['metrics']={row['metric']:[row['multiple'],row['yield_value']] for row in db.execute(
                'SELECT metric,multiple,yield_value FROM screening_metrics WHERE mode=? AND pool=? AND year=? AND symbol=?',(mode,pool,year,symbol))}
            evidence['filters']={row['field']:row['value'] for row in db.execute(
                'SELECT field,value FROM filter_values WHERE mode=? AND pool=? AND year=? AND symbol=?',(mode,pool,year,symbol))}
            record=observation_inputs._prepared_record((mode,pool,scope_day,symbol,observation_inputs.encoded(observation_inputs.measure_observations.detached(evidence))))
            db.execute('UPDATE observation_measure_contexts SET evidence_json=? WHERE mode=? AND pool=? AND context_date=? AND symbol=?',
                (record[4],mode,pool,scope_day,symbol))
        diagnostics.lap('measure_contexts')
        if prior is not None:
            prior.finish()
        # Rows follow from the raw signature, each price file's bytes and the
        # reuse scope (code, universe, metrics, financial inputs, SPY, Treasury).
        observation_inputs.finish(db,latest_day,scopes=scopes,inputs=dict(signature=inputs,
            scope=scope,prices={symbol:unit['content'] for symbol,unit in units.items()}))
        diagnostics.lap('observation_finish')
        for key,value in dict(version=SCHEMA_VERSION,inputs=inputs,prices=sources,latest=latest_meta,historical_through=str(historical_end),
                              reuse=dict(scope=scope,symbols=units)).items():
            db.execute('INSERT INTO metadata VALUES(?,?)',(key,json.dumps(value)))
        # Reject changing inputs and keep an existing database intact on failure.
        if inputs!=signature() or sources!=price_sources():
            raise ValueError('Inputs changed during preparation; retry.')
        db.commit()
        diagnostics.lap('commit')
        # The independent engine already agreed on these exact historical
        # inputs when every company unit was copied and the copied baseline is
        # the published one. Any recalculated or removed unit is checked again.
        result=prepared_baseline(db) if prior is not None and not rebuilt and prior.units.keys()==units.keys() else None
        if result is not None and json.loads(json.dumps(result))==prior.baseline:
            print('Historical inputs unchanged; the verified January baseline was reused.',flush=True)
            diagnostics.note(verification='reused')
        else:
            diagnostics.note(verification='independent')
            result=verify_reference(db)
        diagnostics.lap('verification')
        diagnostics.note(verified_years=len(result['years']),verified_holdings=sum(len(year['holdings']) for year in result['years']))
        if inputs!=signature() or sources!=price_sources():
            raise ValueError('Inputs changed during baseline verification; retry.')
        db.close()
        owner.publish(temporary,result)
        diagnostics.lap('publication')
    except BaseException:
        db.close()
        temporary.unlink(missing_ok=True)
        raise
    diagnostics.note(outcome='prepared',database_bytes=path.stat().st_size)
    print(f'Prepared {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: {path.stat().st_size/1e6:.1f} MB in {time.perf_counter()-started:.2f}s')


def prepare_metrics(db):
    """Publish ready-to-rank values for each mode, pool, date and company.

    The selected fiscal report bounds history; its availability and screening
    eligibility were established when preparing the observation. Latest uses
    year 0, while historical observations use their January book year.
    """
    metrics.validate_catalog()
    histories={}
    for row in db.execute('SELECT * FROM statements ORDER BY symbol,fiscal'):
        histories.setdefault(row['symbol'],[]).append(dict(row))
    db.execute('DELETE FROM screening_metrics')
    for mode,table in [('historical','snapshots'),('latest','latest_snapshots')]:
        values=[]
        for row in db.execute('SELECT * FROM '+table):
            observation=dict(row)
            for metric,pair in metrics.evaluate(observation,histories.get(row['symbol'],[])).items():
                values.append((mode,row['pool'],observation.get('year',0),row['symbol'],metric,*pair))
        db.executemany('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',values)


def aggregate(rows):
    groups={}
    for r in rows:
        groups.setdefault(r['year'],[]).append(r)
    return {year:dict(holdings=stocks,median_market_cap=statistics.median(r['market_cap'] for r in stocks),median_yield=statistics.median(r['metric_yield'] for r in stocks),median_multiple=statistics.median(r['metric_multiple'] for r in stocks),portfolio=statistics.mean(r['return_value'] for r in stocks)) for year,stocks in groups.items()}


def prepared_baseline(db):
    """Export the SQL engine's priced January result for independent comparison."""
    years=[]
    for year,group in aggregate(screening.historical(db)).items():
        period=dict(db.execute('SELECT * FROM periods JOIN baseline_periods USING(year) WHERE year=?',(year,)).fetchone())
        holdings=[]
        for stock in group['holdings']:
            prices=dict(db.execute('SELECT * FROM baseline_prices WHERE year=? AND symbol=?',(year,stock['symbol'])).fetchone())
            holdings.append({key:(prices[key] if key in baseline.PRICE_FIELDS else stock[key]) for key in baseline.HOLDING_FIELDS})
        years.append(dict(year=year,entry=period['entry'],exit=period['exit'],spy_entry=period['spy_entry'],spy_exit=period['spy_exit'],
                          spy_entry_price=period['spy_entry_price'],spy_exit_price=period['spy_exit_price'],
                          spy=period['spy'],portfolio=group['portfolio'],holdings=holdings))
    through=json.loads(db.execute("SELECT value FROM metadata WHERE key='historical_through'").fetchone()[0])
    return dict(through=through,years=years)


def verify_reference(db):
    result=prepared_baseline(db)
    independent=revalue.calculate(date.fromisoformat(result['through']))
    baseline.agree(result,independent)
    print(f'Verified {len(result["years"])} January books, holdings, prices and returns with the independent engine.',flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=DATABASE)
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('prepare',help='Prepare January snapshots from saved JSON; never downloads')
    p.add_argument('--force',action='store_true')
    p=commands.add_parser('screen',help='Run a fast parameterized January backtest')
    p.add_argument('--first',type=int,default=1996);p.add_argument('--last',type=int,default=2026)
    p.add_argument('--rank-from',type=int,default=1);p.add_argument('--rank-to',type=int,default=50)
    p.add_argument('--top',type=int,help='Shortcut for ranks 1 through N')
    p.add_argument('--selection-order',choices=['filter_first','rank_first'],default='filter_first')
    p.add_argument('--metric',choices=list(metrics.METRICS),default=metrics.DEFAULT_METRIC)
    p.add_argument('--pool',choices=['legacy','cached'],default='legacy')
    p.add_argument('--min-cap',type=float,default=100e6);p.add_argument('--max-cap',type=float)
    p.add_argument('--min-ev',type=float,default=50e6);p.add_argument('--min-yield',type=float,default=0.)
    p.add_argument('--max-multiple',type=float);p.add_argument('--sector');p.add_argument('--exchange')
    p.add_argument('--output',type=Path,help='Optional JSON result path; the current report is never overwritten')
    commands.add_parser('status',help='Show database size and price-coverage limits')
    args=parser.parse_args()
    if args.command=='prepare':
        prepare(args.database,args.force);return
    started=time.perf_counter()
    with connect(args.database) as db:
        if args.command=='status':
            print(f'Database: {args.database.stat().st_size/1e6:.1f} MB')
            print('year,eligible_financials,price_valued_cached,legacy_price_valued')
            for p in db.execute('SELECT * FROM periods ORDER BY year'):
                counts={row[0]:row[1] for row in db.execute('SELECT pool,COUNT(*) FROM snapshots WHERE year=? GROUP BY pool',(p['year'],))}
                print(f"{p['year']},{p['cached_candidates']},{counts.get('cached',0)},{counts.get('legacy',0)}")
            return
        options={k:getattr(args,k) for k in ['first','last','rank_from','rank_to','pool','metric','min_cap','max_cap','min_ev','min_yield','max_multiple','sector','exchange','selection_order']}
        if args.top is not None:
            options.update(rank_from=1,rank_to=args.top)
        rows=screening.historical(db,**options)
        grouped=aggregate(rows)
        periods={r['year']:dict(r) for r in db.execute('SELECT * FROM periods')}
        print('year,names,strategy,spy,median_market_cap,last_price_exits')
        wealth=spy_wealth=1.
        for year in range(args.first,args.last+1):
            if year not in periods:
                continue
            g=grouped.get(year)
            if not g:
                print(f'{year},0,NA,NA,NA,0');continue
            wealth*=1+g['portfolio'];spy_wealth*=1+periods[year]['spy']
            stops=sum(r['status']=='Last available price' for r in g['holdings'])
            print(f"{year},{len(g['holdings'])},{g['portfolio']:.4%},{periods[year]['spy']:.4%},{g['median_market_cap']:.0f},{stops}")
        requested=options['rank_to']-options['rank_from']+1
        incomplete=[y for y in periods if args.first<=y<=args.last and len(grouped.get(y,{}).get('holdings',[]))!=requested]
        print(f'Growth of $1 over populated books: strategy ${wealth:.4f}; SPY ${spy_wealth:.4f}')
        print(f'Query and validation time: {time.perf_counter()-started:.3f}s')
        print('Coverage: '+('original 250-candidate buffer; report-compatible selection.' if args.pool=='legacy' else 'cached-price companies only; not the full universe. Sector/exchange are cached metadata, not historical classifications.'))
        if incomplete:
            print('Insufficient matching names in: '+', '.join(map(str,incomplete)))
        print('Early exits outside the original top 50 have not received the prior manual bankruptcy review.')
        if args.output:
            if args.output.resolve()==(RESULTS/'summary-exits.txt').resolve():
                raise ValueError('Choose a separate experiment output; the reference report is preserved.')
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(dict(parameters=options,years=grouped,periods=periods,incomplete_years=incomplete),indent=2))


if __name__=='__main__':
    try:
        main()
    except (ValueError,sqlite3.Error) as error:
        raise SystemExit(str(error))
