"""Cached daily prices and reusable dated backtest books. No network access."""
from bisect import bisect_left, bisect_right
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path
import argparse
import json
import sqlite3
import time

import research as r
import metrics
import books as financial_books

DATABASE = r.ROOT/'data'/'schedules.sqlite'
VERSION = 2
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


def fingerprint():
    # Preparation already validated every raw price file. Normal requests inspect
    # only the compact research signature, not thousands of raw files.
    return dict(version=VERSION, inputs=r.signature(), engine=[Path(__file__).stat().st_size,Path(__file__).stat().st_mtime_ns])


def connect(path=DATABASE):
    path=Path(path)
    if not path.exists():
        raise ValueError('Daily cache missing. Run: python3 scripts/schedules.py prepare')
    db=sqlite3.connect(path,timeout=60)
    db.row_factory=sqlite3.Row
    try:
        saved=json.loads(db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()[0])
        if saved!=fingerprint():
            raise ValueError('Daily cache changed. Run: python3 scripts/schedules.py prepare')
    except Exception:
        db.close();raise
    return db


def upgrade_daily_cache(path, inputs):
    """Version 1 prepared both pools; retain its prices and completed books.

    Only this schema/engine change is compatible. Changed research inputs or
    financial calculation code still require the ordinary offline rebuild.
    Schema, completion markers and freshness metadata publish atomically.
    """
    db=sqlite3.connect(path,timeout=60)
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            saved=json.loads(db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()[0])
            if saved.get('version')!=1 or inputs.get('version')!=2 or saved.get('inputs')!=inputs.get('inputs'):
                return False
            db.execute(POOL_SCHEMA)
            for pool in ('cached','legacy'):
                db.execute('INSERT INTO period_pools SELECT year,? FROM periods',(pool,))
            db.execute("UPDATE metadata SET value=? WHERE key='daily_inputs'",(json.dumps(inputs),))
        return True
    finally:
        db.close()


def prepare(path=DATABASE, source=r.DATABASE):
    """Parse raw prices once; keep the previous cache if publication fails."""
    started=time.perf_counter()
    inputs=fingerprint()
    path=Path(path)
    # The public daily-cache command owns its prerequisite too. Users never
    # need to discover and run the dependency chain themselves.
    r.prepare(source)
    reference=r.connect(source,full_prices=True)
    if path.exists():
        try:
            db=connect(path)
        except ValueError:
            if upgrade_daily_cache(path,inputs):
                reference.close()
                print('Daily cache upgraded; existing prices and both completed pools retained.');return
        else:
            db.close();reference.close();print('Daily cache already current; no prices parsed.');return
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.building')
    temporary.unlink(missing_ok=True)
    db=sqlite3.connect(temporary)
    try:
        db.executescript(SCHEMA)
        for table in ('companies','statements'):
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
        if inputs!=fingerprint():
            raise ValueError('Inputs changed during daily preparation; retry.')
        db.execute('INSERT INTO metadata VALUES(?,?)',('daily_inputs',json.dumps(inputs)))
        db.execute('INSERT INTO metadata VALUES(?,?)',('cached_symbols',json.dumps(symbols)))
        db.commit();db.close();reference.close();temporary.replace(path)
    except BaseException:
        db.close();reference.close();temporary.unlink(missing_ok=True);raise
    print(f'Daily cache {path.stat().st_size/1e6:.1f} MB prepared in {time.perf_counter()-started:.1f}s',flush=True)


def schedule(start, end, months, sessions):
    """Anchor every target to the original day; holidays roll forward.

    Clamp invalid month days (31 April, leap anniversaries) without drifting the
    next target. End is an inclusive mark date, rolled back to an available session.
    """
    start,end=date.fromisoformat(start),date.fromisoformat(end)
    if not sessions:raise ValueError('The daily cache has no trading sessions.')
    if months not in (1,3,6,12,24) or type(months) is not int:
        raise ValueError('Rebalance interval must be 1, 3, 6, 12 or 24 months.')
    if start<date(1996,1,1) or start>=end or end>sessions[-1]:
        raise ValueError(f'Choose increasing dates from 1996-01-01 through {sessions[-1]}.')
    final=sessions[bisect_right(sessions,end)-1]
    boundaries=[]
    offset=0
    while True:
        absolute=start.year*12+start.month-1+offset
        year,month=divmod(absolute,12);month+=1
        target=date(year,month,min(start.day,monthrange(year,month)[1]))
        if target>=final:
            break
        index=bisect_left(sessions,target)
        actual=sessions[index]
        if actual<final and (not boundaries or boundaries[-1]!=actual):
            boundaries.append(actual)
        offset+=months
    if not boundaries:
        raise ValueError('No complete trading interval in the selected dates.')
    return list(zip(boundaries,boundaries[1:]+[final]))


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


def prepare_period(db,entry,exit_day,books,cached,pool='legacy'):
    completed=prepared_period(db,entry,exit_day,pool)
    if completed is not None:return completed
    broad,legacy=books
    statements,ranks=financial_books.candidates(books,entry)
    existing=db.execute('SELECT year,treasury FROM periods WHERE entry=? AND exit=?',(str(entry),str(exit_day))).fetchone()
    if existing is not None:
        period_id,treasury=existing
    else:
        spy=dict(db.execute('SELECT day,price FROM sessions WHERE day IN (?,?)',(str(entry),str(exit_day))).fetchall())
        treasury=db.execute('SELECT yield_value FROM treasuries WHERE day<=? ORDER BY day DESC LIMIT 1',(str(entry),)).fetchone()
        treasury=treasury[0] if treasury else 0.
        cursor=db.execute('INSERT INTO periods(entry,exit,spy,treasury,legacy_candidates,cached_candidates) VALUES(?,?,?,?,?,?)',(str(entry),str(exit_day),spy[str(exit_day)]/spy[str(entry)]-1,treasury,len(ranks),len(statements['cached'])))
        period_id=cursor.lastrowid
    for symbol,s in statements[pool].items():
        if symbol not in cached or (pool=='legacy' and symbol not in ranks):continue
        lookup=lambda day,column,forward,slack:price(db,symbol,day,column,forward=forward,slack=slack)
        row=financial_books.snapshot(s,entry,exit_day,lookup,(entry.year,symbol) in r.revalue.BANKRUPT)
        if row is None:continue
        fiscal,entry_date,end_date,cap,ev,ebitda,yield_value,multiple,ret,status=row
        if not financial_books.eligible(pool,cap,ev):continue
        observation=dict(symbol=symbol,fiscal=fiscal,enterprise_value=ev,ev_ebitda=multiple,ebitda_yield=yield_value)
        db.execute('INSERT INTO snapshots VALUES('+','.join('?'*15)+')',(pool,period_id,symbol,ranks.get(symbol),fiscal,entry_date,end_date,cap,ev,ebitda,yield_value,multiple,yield_value-treasury,ret,status))
        history=[dict(row,fiscal=str(row['fiscal']),known=str(row['known'])) for row in broad[symbol]]
        for metric,(multiple,yield_value) in metrics.evaluate(observation,history).items():
            db.execute('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',('historical',pool,period_id,symbol,metric,multiple,yield_value))
    # Empty pools are completed too. The caller commits this marker with all
    # snapshots/metrics, so an interrupted pool switch can safely be retried.
    db.execute('INSERT INTO period_pools VALUES(?,?)',(period_id,pool))
    return period_id


def backtest(db, *, start, end, months=12, **options):
    """Regular schedules and random-date batches share one book evaluator."""
    sessions=[date.fromisoformat(row[0]) for row in db.execute('SELECT day FROM sessions ORDER BY day')]
    periods=schedule(start,end,months,sessions)
    return backtest_periods(db,periods,months=months,**options)


def backtest_dates(db, *, dates, start, end, months=12, **options):
    """Evaluate sampled dates, including zero-return cash before the first trade.

    Both the portfolio and paired SPY hold cash over that initial interval. All
    trials therefore use the same elapsed window for CAGR. Dates must be real
    cached sessions and strictly increasing; every trial uses ordinary books.
    """
    sessions=[date.fromisoformat(row[0]) for row in db.execute('SELECT day FROM sessions ORDER BY day')]
    window=schedule(start,end,months,sessions)
    first,final=window[0][0],window[-1][1]
    trades=[date.fromisoformat(day) for day in dates]
    available=set(sessions)
    if not trades or trades!=sorted(set(trades)) or any(day not in available or not first<=day<final for day in trades):
        raise ValueError('Sampled trades must be increasing cached sessions inside the backtest window.')
    periods=list(zip(trades,trades[1:]+[final]))
    result=backtest_periods(db,periods,months=months,**options)
    result['first_trade']=result['start']
    result['start']=str(first)
    result['cash_days']=(trades[0]-first).days
    duration=(final-first).days/365.25
    result['cagr']=result['growth']**(1/duration)-1 if result['growth'] is not None else None
    result['spy_cagr']=result['spy_growth']**(1/duration)-1
    return result


def backtest_periods(db, periods, *, months, **options):
    """Prepare missing books atomically and apply the shared SQL screener."""
    started=time.perf_counter()
    allowed={'rank_from','rank_to','pool','metric','min_cap','max_cap','min_ev','min_yield','max_multiple','sector','exchange'}
    if set(options)-allowed:raise ValueError('Unknown screening option.')
    r._select(db,period=(-1,-1),**options)
    pool=options.get('pool','legacy')
    missing=any(prepared_period(db,a,b,pool) is None for a,b in periods)
    books=histories(db) if missing else None
    saved=db.execute("SELECT value FROM metadata WHERE key='cached_symbols'").fetchone() if missing else None
    cached=set(json.loads(saved[0])) if saved else {row[0] for row in db.execute('SELECT DISTINCT symbol FROM prices')} if missing else set()
    results=[]
    with db:
        for entry,exit_day in periods:
            period_id=prepare_period(db,entry,exit_day,books,cached,pool)
            stocks=r._select(db,period=(period_id,period_id),**options)
            for stock in stocks:
                stock.pop('year')
                stock['weight']=1/len(stocks)
                stock['contribution_pp']=stock['return_value']/len(stocks)*100
            spy=db.execute('SELECT spy FROM periods WHERE year=?',(period_id,)).fetchone()[0]
            results.append(dict(entry=str(entry),exit=str(exit_day),holdings=stocks,names=len(stocks),portfolio=sum(h['return_value'] for h in stocks)/len(stocks) if stocks else None,spy=spy,is_final_period=exit_day==periods[-1][1]))
    growth=spy_growth=1.
    for period in results:
        if growth is not None:growth=growth*(1+period['portfolio']) if period['portfolio'] is not None else None
        spy_growth*=1+period['spy']
    duration=(periods[-1][1]-periods[0][0]).days/365.25
    return dict(periods=results,start=str(periods[0][0]),end=str(periods[-1][1]),months=months,options=options,growth=growth,spy_growth=spy_growth,cagr=growth**(1/duration)-1 if growth is not None else None,spy_cagr=spy_growth**(1/duration)-1,seconds=time.perf_counter()-started,coverage='Cached-price companies only; additional early exits have not received the original manual review. Stopped proceeds stay in cash until the next rebalance. Equal weights reset each period; no transaction costs.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare'])
    parser.parse_args()
    prepare()
