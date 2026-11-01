
# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))

from backtest import screening
"""Cached daily prices and reusable dated backtest books. No network access."""
from datetime import date
from pathlib import Path
import argparse
import json
import sqlite3
import time

import research as r
from backtest.financial import metrics as metrics
import cache_access
from backtest.financial import books as financial_books
import backtest_control
from backtest import calendar as schedule_calendar
from backtest import portfolio_results as portfolio_results

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
    sources=[Path(__file__),Path(__file__).with_name('book_batch.py'),
             Path(schedule_calendar.__file__),Path(portfolio_results.__file__)]
    return dict(version=VERSION, inputs=r.signature(),prices=r.prepared_price_binding(source or r.DATABASE),
                engine={p.relative_to(r.ROOT).as_posix() if p.is_relative_to(r.ROOT) else p.name:[p.stat().st_size,p.stat().st_mtime_ns] for p in sources})


def connect(path=DATABASE,source=None):
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
        symbols=[row[0] for row in reference.execute('SELECT DISTINCT symbol FROM statements') if r.run.cache_path_for(row[0]).exists()]
        for i,symbol in enumerate(symbols,1):
            payload=json.loads(r.run.cache_path_for(symbol).read_text())
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
        db.executemany('INSERT INTO sessions VALUES(?,?)',[(str(d),v) for d,v in r.run.load_bars(r.RAW/'spy-div.json','adjClose')])
        db.executemany('INSERT OR REPLACE INTO treasuries VALUES(?,?)',[(row['date'][:10],row['month3']/100) for row in json.loads((r.RAW/'treasury.json').read_text()) if r.run.parse_day(row.get('date')) is not None and r.run.num(row.get('month3')) is not None])
        if inputs!=fingerprint(source):
            raise ValueError('Inputs changed during daily preparation; retry.')
        db.execute('INSERT INTO metadata VALUES(?,?)',('daily_inputs',json.dumps(inputs)))
        db.execute('INSERT INTO metadata VALUES(?,?)',('cached_symbols',json.dumps(symbols)))
        db.commit();db.close();reference.close();temporary.replace(path)
    except BaseException:
        db.close();reference.close();temporary.unlink(missing_ok=True);raise
    print(f'Daily cache {path.stat().st_size/1e6:.1f} MB prepared in {time.perf_counter()-started:.1f}s',flush=True)


def schedule(start, end, months, sessions):
    """Adapt the established monthly interface to the shared pure calendar."""
    configuration=schedule_calendar.legacy_configuration(dict(start=start,end=end,months=months))
    return schedule_calendar.SessionCalendar(sessions).fixed(
        configuration,checkpoint=backtest_control.checkpoint)


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


def compute_period(db,entry,exit_day,books,cached,pool):
    """Calculate a dated pool without writes; workers share this financial path."""
    broad,legacy=books
    statements,ranks=financial_books.candidates(books,entry)
    existing=db.execute('SELECT spy,treasury FROM periods WHERE entry=? AND exit=?',(str(entry),str(exit_day))).fetchone()
    if existing is not None:
        spy_return,treasury=existing
    else:
        spy=dict(db.execute('SELECT day,price FROM sessions WHERE day IN (?,?)',(str(entry),str(exit_day))).fetchall())
        treasury=db.execute('SELECT yield_value FROM treasuries WHERE day<=? ORDER BY day DESC LIMIT 1',(str(entry),)).fetchone()
        treasury=treasury[0] if treasury else 0.
        spy_return=spy[str(exit_day)]/spy[str(entry)]-1
    treasury10=r.ten_year_yield(db,entry)
    snapshots=[];pairs=[];filter_rows=[]
    for symbol,s in statements[pool].items():
        backtest_control.checkpoint()
        if symbol not in cached or (pool=='legacy' and symbol not in ranks):continue
        lookup=lambda day,column,forward,slack:price(db,symbol,day,column,forward=forward,slack=slack)
        row=financial_books.snapshot(s,entry,exit_day,lookup,(entry.year,symbol) in r.revalue.BANKRUPT)
        if row is None:continue
        fiscal,entry_date,end_date,cap,ev,ebitda,yield_value,multiple,ret,status=row
        if not financial_books.eligible(pool,cap,ev):continue
        observation=dict(symbol=symbol,fiscal=fiscal,market_cap=cap,enterprise_value=ev,ev_ebitda=multiple,ebitda_yield=yield_value)
        snapshots.append((symbol,ranks.get(symbol),fiscal,entry_date,end_date,cap,ev,ebitda,yield_value,multiple,yield_value-treasury,ret,status))
        history=[dict(row,fiscal=str(row['fiscal']),known=str(row['known'])) for row in broad[symbol]]
        evaluated=metrics.evaluate(observation,history)
        filter_rows.extend((symbol,key,value) for key,value in metrics.filter_values(observation,evaluated,entry,lookup,{record[0]:json.loads(record[1]) for record in db.execute('SELECT fiscal,values_json FROM financial_inputs WHERE symbol=?',(symbol,))},treasury10).items())
        for metric,(multiple,yield_value) in evaluated.items():
            pairs.append((symbol,metric,multiple,yield_value))
    return dict(entry=str(entry),exit=str(exit_day),pool=pool,
                period=(str(entry),str(exit_day),spy_return,treasury,len(ranks),len(statements['cached'])),
                snapshots=snapshots,metrics=pairs,filters=filter_rows)


def store_period(db,book):
    """Save a complete calculated pool inside the caller's transaction."""
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


def prepare_period(db,entry,exit_day,books,cached,pool='legacy'):
    completed=prepared_period(db,entry,exit_day,pool)
    if completed is not None:return completed
    return store_period(db,compute_period(db,entry,exit_day,books,cached,pool))


def backtest(db, *, start, end, months=12, **options):
    """Regular schedules and random-date batches share one book evaluator."""
    sessions=[date.fromisoformat(row[0]) for row in db.execute('SELECT day FROM sessions ORDER BY day')]
    periods=schedule(start,end,months,sessions)
    return backtest_periods(db,periods,months=months,**options)


def backtest_calendar(db, **request):
    """Evaluate a version-1 calendar with the ordinary complete-book policy.

    Requested calendar metadata remains separate from resolved trading sessions.
    Explicit dates preserve the common cash window used by random trials.
    """
    from backtest import calendar_requests as calendar_requests
    sessions=[date.fromisoformat(row[0]) for row in db.execute('SELECT day FROM sessions ORDER BY day')]
    periods,first,options,metadata=calendar_requests.periods(
        sessions,request,checkpoint=backtest_control.checkpoint)
    return _backtest_periods(db,periods,common_start=first,frequency=metadata,**options)


def dated_periods(dates,start,end,months,sessions):
    """Keep legacy month validation; explicit trades need no nominal schedule."""
    schedule_calendar.legacy_configuration(dict(start=start,end=end,months=months))
    return schedule_calendar.SessionCalendar(sessions).explicit(
        dates,start,end,checkpoint=backtest_control.checkpoint)


def backtest_dates(db, *, dates, start, end, months=12, **options):
    """Evaluate explicit trades, holding cash before the first trade for both sides."""
    sessions=[date.fromisoformat(row[0]) for row in db.execute('SELECT day FROM sessions ORDER BY day')]
    first,final,periods=dated_periods(dates,start,end,months,sessions)
    return _backtest_periods(db,periods,months=months,common_start=first,**options)


def backtest_periods(db, periods, *, months, **options):
    return _backtest_periods(db,periods,months=months,**options)


def _backtest_periods(db, periods, *, months=None, common_start=None, frequency=None, **options):
    """Prepare missing books atomically and apply the shared SQL screener."""
    backtest_control.checkpoint()
    started=time.perf_counter()
    periods=portfolio_results.validate_periods(periods,common_start)
    allowed={'rank_from','rank_to','pool','metric','min_cap','max_cap','min_ev','min_yield','max_multiple','sector','exchange','filters','selection_order'}
    if set(options)-allowed:raise ValueError('Unknown screening option.')
    screening.validate_selection(**options)
    pool=options.get('pool','legacy')
    missing=any(prepared_period(db,a,b,pool) is None for a,b in periods)
    books=histories(db) if missing else None
    cached=cached_symbols(db) if missing else set()
    def select_period(entry,exit_day):
        period_id=prepare_period(db,entry,exit_day,books,cached,pool)
        stocks=screening.select(db,period=(period_id,period_id),**options)
        spy=db.execute('SELECT spy FROM periods WHERE year=?',(period_id,)).fetchone()[0]
        return dict(entry=str(entry),exit=str(exit_day),holdings=stocks,spy=spy)
    with db:
        result=portfolio_results.evaluate(periods,select_period,common_start=common_start,
                                          checkpoint=backtest_control.checkpoint)
    result.update(frequency if frequency is not None else dict(months=months),options=options,seconds=time.perf_counter()-started)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare'])
    parser.parse_args()
    prepare()
