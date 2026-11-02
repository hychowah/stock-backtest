"""Prepared daily storage; connections and transactions belong to callers."""
from datetime import date
from pathlib import Path
import json
import sqlite3
import time

from backtest.inputs import research as r
from backtest.runtime import cache_access as cache_access
from backtest.financial import books as financial_books
from backtest.runtime import backtest_control as backtest_control
from backtest import calendar as schedule_calendar
from backtest import portfolio_results as portfolio_results
from backtest.inputs import market
from backtest.inputs import observation_inputs
from backtest.financial import rules

DATABASE = r.ROOT/'data'/'schedules.sqlite'
VERSION = 3
POOL_SCHEMA = '''
CREATE TABLE IF NOT EXISTS period_pools(
 period_id INTEGER, pool TEXT CHECK(pool IN ('cached','legacy')),
 PRIMARY KEY(period_id,pool), FOREIGN KEY(period_id) REFERENCES periods(year)
) WITHOUT ROWID;
'''
SCHEMA = r.SCHEMA + '''
CREATE TABLE prices(symbol TEXT, day TEXT, price REAL, adjusted REAL,
 PRIMARY KEY(symbol,day)) WITHOUT ROWID;
CREATE TABLE sessions(day TEXT PRIMARY KEY, price REAL) WITHOUT ROWID;
CREATE TABLE treasuries(day TEXT PRIMARY KEY, yield_value REAL) WITHOUT ROWID;
CREATE UNIQUE INDEX dated_period ON periods(entry,exit);
''' + POOL_SCHEMA


def fingerprint(source=None):
    # Daily prices bind to the validated research price inventory. Changed
    # prepared inputs rebuild prices/books. Normal checks do not scan raw files.
    sources=[Path(__file__),Path(__file__).parents[1]/'engines'/'original'/'schedules.py',
             Path(__file__).parents[1]/'engines'/'original'/'book_batch.py',
             Path(schedule_calendar.__file__),Path(portfolio_results.__file__)]
    return dict(version=VERSION, observation_version=observation_inputs.VERSION,
                inputs=r.signature(),prices=r.prepared_price_binding(source or r.DATABASE),
                observations=r.prepared_observation_binding(source or r.DATABASE),
                engine={p.relative_to(r.ROOT).as_posix() if p.is_relative_to(r.ROOT) else p.name:[p.stat().st_size,p.stat().st_mtime_ns] for p in sources})

def connect(path=DATABASE,source=None):
    # The returned connection is caller-owned.
    path=Path(path)
    if not path.exists():
        raise ValueError('Daily cache missing. Run: python3 scripts/schedules.py prepare')
    db=sqlite3.connect(path,timeout=60)
    db.row_factory=sqlite3.Row
    try:
        saved=json.loads(db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()[0])
        if saved!=fingerprint(source):
            raise ValueError('Daily cache changed. Run: python3 scripts/schedules.py prepare')
    except Exception:
        db.close();raise
    return db

def upgrade_daily_cache(path, inputs):
    """Retain compatible prices and books across preparation-engine upgrades.

    Only this schema/engine change is compatible. Changed research inputs or
    financial calculation code still require the ordinary offline rebuild.
    Schema, completion markers and freshness metadata publish atomically.
    """
    db=sqlite3.connect(path,timeout=60)
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            saved=json.loads(db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()[0])
            if (saved.get('version') not in (1,2) or inputs.get('version')!=VERSION
                    or saved.get('observation_version')!=inputs.get('observation_version')
                    or saved.get('observations')!=inputs.get('observations')
                    or saved.get('inputs')!=inputs.get('inputs')
                    or not isinstance(saved.get('prices'),str)
                    or saved['prices']!=inputs.get('prices')):
                return False
            db.execute(POOL_SCHEMA)
            if saved['version']==1:
                for pool in ('cached','legacy'):
                    db.execute('INSERT INTO period_pools SELECT year,? FROM periods',(pool,))
            db.execute("UPDATE metadata SET value=? WHERE key='daily_inputs'",(json.dumps(inputs),))
        return True
    finally:
        db.close()

@cache_access.exclusive
def prepare(path=DATABASE, source=r.DATABASE):
    """Parse raw prices once; keep the previous cache if publication fails."""
    started=time.perf_counter()
    path=Path(path)
    # The public daily-cache command owns its prerequisite too. Users never
    # need to discover and run the dependency chain themselves.
    r.prepare(source)
    inputs=fingerprint(source)
    reference=r.connect(source,full_prices=True)
    if path.exists():
        try:
            db=connect(path,source)
        except ValueError:
            if upgrade_daily_cache(path,inputs):
                reference.close()
                print('Daily cache upgraded; existing prices and completed pools retained.');return
        else:
            db.close();reference.close();print('Daily cache already current; no prices parsed.');return
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.building')
    temporary.unlink(missing_ok=True)
    db=sqlite3.connect(temporary)
    try:
        db.executescript(SCHEMA)
        for table in ('companies','statements','financial_inputs','treasury10'):
            rows=reference.execute('SELECT * FROM '+table).fetchall()
            if rows:
                db.executemany('INSERT INTO '+table+' VALUES('+','.join('?'*len(rows[0]))+')',rows)
        observation_inputs.copy(reference,db,backtest_control.checkpoint)
        symbols=[row[0] for row in reference.execute('SELECT DISTINCT symbol FROM statements') if market.cache_path_for(row[0]).exists()]
        for i,symbol in enumerate(symbols,1):
            payload=json.loads(market.cache_path_for(symbol).read_text())
            adjusted=dict(r.bars(payload.get('div') or [],'adjClose'))
            light={}
            for row in payload.get('light') or []:
                value=row.get('price') if row.get('price') is not None else row.get('close')
                light.update(r.bars([dict(date=row.get('date'),value=value)],'value'))
            # Match existing valuation policy: use the entire light series when
            # supplied, otherwise the adjusted series. Never mix their scales.
            valuation=light or adjusted
            db.executemany('INSERT INTO prices VALUES(?,?,?,?)',[(symbol,str(day),valuation.get(day),adjusted.get(day)) for day in sorted(valuation.keys()|adjusted.keys())])
            if i%200==0 or i==len(symbols):
                print(f'Prepared daily prices {i}/{len(symbols)}',flush=True)
        db.executemany('INSERT INTO sessions VALUES(?,?)',[(str(d),v) for d,v in market.load_bars(r.RAW/'spy-div.json','adjClose')])
        db.executemany('INSERT OR REPLACE INTO treasuries VALUES(?,?)',[(row['date'][:10],row['month3']/100) for row in json.loads((r.RAW/'treasury.json').read_text()) if rules.parse_day(row.get('date')) is not None and rules.num(row.get('month3')) is not None])
        if inputs!=fingerprint(source):
            raise ValueError('Inputs changed during daily preparation; retry.')
        db.execute('INSERT INTO metadata VALUES(?,?)',('daily_inputs',json.dumps(inputs)))
        db.execute('INSERT INTO metadata VALUES(?,?)',('cached_symbols',json.dumps(symbols)))
        db.commit();db.close();reference.close();temporary.replace(path)
    except BaseException:
        db.close();reference.close();temporary.unlink(missing_ok=True);raise
    print(f'Daily cache {path.stat().st_size/1e6:.1f} MB prepared in {time.perf_counter()-started:.1f}s',flush=True)

def price(db,symbol,day,column,forward=False,slack=None):
    # column is internal, never request data.
    operator,order=('>=','ASC') if forward else ('<=','DESC')
    row=db.execute(f'SELECT day,{column} FROM prices WHERE symbol=? AND day{operator}? AND {column} IS NOT NULL ORDER BY day {order} LIMIT 1',(symbol,str(day))).fetchone()
    if row is None:
        return None
    result=(date.fromisoformat(row[0]),row[1])
    return result if slack is None or abs((result[0]-day).days)<=slack else None

def histories(db):
    broad,legacy={},{}
    for record in db.execute('SELECT * FROM statements ORDER BY rowid'):
        backtest_control.checkpoint()
        row=dict(record);symbol=row.pop('symbol')
        row.update(fiscal=date.fromisoformat(row['fiscal']),known=date.fromisoformat(row['known']),enterprise=row['enterprise_value'])
        row['yield']=row['ebitda_yield']
        broad.setdefault(symbol,[]).append(row)
    for rows in broad.values():rows.sort(key=lambda s:s['fiscal'])
    return financial_books.pools(broad)

def prepared_period(db,entry,exit_day,pool):
    row=db.execute('''SELECT p.year FROM periods p JOIN period_pools b ON b.period_id=p.year
                      WHERE p.entry=? AND p.exit=? AND b.pool=?''',
                   (str(entry),str(exit_day),pool)).fetchone()
    return row[0] if row is not None else None

def cached_symbols(db):
    row=db.execute("SELECT value FROM metadata WHERE key='cached_symbols'").fetchone()
    return set(json.loads(row[0])) if row else {row[0] for row in db.execute('SELECT DISTINCT symbol FROM prices')}

def store_period(db,book):
    """Save a complete pool in the caller's transaction, including empty pools.

    Rows and completion marker commit together. Daily-price inventory binding
    remains the prerequisite for every read and write.
    """
    pool=book['pool'];entry=book['entry'];exit_day=book['exit']
    completed=prepared_period(db,entry,exit_day,pool)
    if completed is not None:return completed
    row=db.execute('SELECT year FROM periods WHERE entry=? AND exit=?',(entry,exit_day)).fetchone()
    if row is None:
        cursor=db.execute('INSERT INTO periods(entry,exit,spy,treasury,legacy_candidates,cached_candidates) VALUES(?,?,?,?,?,?)',book['period'])
        period_id=cursor.lastrowid
    else:period_id=row[0]
    db.executemany('INSERT INTO snapshots VALUES('+','.join('?'*15)+')',
                   ((pool,period_id,*row) for row in book['snapshots']))
    db.executemany('INSERT INTO filter_values VALUES(?,?,?,?,?,?)',
                   (('historical',pool,period_id,*row) for row in book.get('filters',[])))
    db.executemany('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',
                   (('historical',pool,period_id,*row) for row in book['metrics']))
    # Empty pools are completed too. The caller commits this marker with all
    # snapshots/metrics, so an interrupted pool switch can safely be retried.
    db.execute('INSERT INTO period_pools VALUES(?,?)',(period_id,pool))
    return period_id
