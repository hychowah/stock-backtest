"""Inspect and fill the local raw cache, then rebuild derived backtest data.

The HTTP adapter owns origin checks. Jobs share the schedule writer lock.
No provider response, credential, request URL or arbitrary exception is exposed.
"""
from calendar import monthrange
from datetime import date, timedelta, datetime, timezone
import json
import sqlite3
import subprocess
import sys
from threading import Event, Lock, Thread
import cache_assets
import cache_access
from cache_assets import read_json, write_json, series

import schedules
import research as r
import run

ROOT=r.ROOT
RAW=r.RAW
COVERAGE=RAW/'download-coverage.json'
KINDS=('universe','financials','prices','spy','treasury')



class Cancelled(Exception):
    pass



def source_problem():
    """Allow the repair panel to open when essential source data is absent."""
    for name in ('universe.json','metrics.jsonl','spy-div.json','treasury.json'):
        path=RAW/name
        if not path.is_file() or not path.stat().st_size:return True
    try:
        if not universe_rows() or financial_records()[1]:return True
        for file,field in [('spy-div.json','adjClose'),('treasury.json','month3')]:
            if not series(read_json(RAW/file,[]),field):return True
    except (ValueError,OSError):return True
    return not (ROOT/'results'/'summary-exits.txt').is_file() or not any((RAW/'px').glob('*.json'))


def options(request):
    if set(request)-{'scope','symbols','start','end','datasets'}:
        raise ValueError('Unknown data option.')
    start=date.fromisoformat(request.get('start','1995-01-01'))
    end=date.fromisoformat(request.get('end',str(run.ASOF)))
    if not date(1990,1,1)<=start<=end<=date.today():
        raise ValueError('Choose dates from 1990 through today, with start before end.')
    scope=request.get('scope','baseline')
    if scope not in ('baseline','cached','financials','symbols'):
        raise ValueError('Choose a valid stock group.')
    symbols=request.get('symbols','')
    if not isinstance(symbols,str):raise ValueError('Enter stock symbols as text.')
    symbols=sorted(set(symbols.upper().replace(',',' ').split()))
    if len(symbols)>200 or any(len(s)>30 or not all(c.isalnum() or c in '.-^' for c in s) for s in symbols):
        raise ValueError('Use up to 200 valid stock symbols.')
    if scope=='symbols' and not symbols:raise ValueError('Enter at least one stock symbol.')
    datasets=request.get('datasets',list(KINDS))
    if not isinstance(datasets,list) or any(k not in KINDS for k in datasets) or not datasets:
        raise ValueError('Choose at least one data type.')
    return dict(start=str(start),end=str(end),scope=scope,symbols=symbols,datasets=datasets)


def financial_records():
    return cache_assets.financial_records(RAW/'metrics.jsonl')


def spans(start,end,monthly=False):
    while start<=end:
        stop=min(end,date(start.year,start.month,monthrange(start.year,start.month)[1]) if monthly else date(start.year,12,31))
        yield str(start),str(stop)
        start=stop+timedelta(days=1)



def universe_rows():
    rows=read_json(RAW/'universe.json',[])
    if not isinstance(rows,list):raise ValueError('The universe cache must contain a list.')
    return {row['symbol']:row for row in rows if isinstance(row,dict) and isinstance(row.get('symbol'),str)}


def target_symbols(o,universe,records):
    if o['scope']=='symbols':
        unknown=set(o['symbols'])-universe.keys()
        if unknown:raise ValueError('Symbols absent from the saved US universe: '+', '.join(sorted(unknown)[:20]))
        return o['symbols']
    if o['scope']=='cached':
        return sorted(s for s in universe if run.cache_path_for(s).exists())
    broad=r.books.statements(records,universe)
    if o['scope']=='financials':return sorted(broad)
    pools=r.books.pools(broad)
    spy=series(read_json(RAW/'spy-div.json',[]),'adjClose')
    sessions=[date.fromisoformat(row['date'][:10]) for row in spy]
    selected=set()
    for year in range(run.FIRST_YEAR,run.LAST_YEAR+1):
        entry=run.session_on_or_after(sessions,date(year,1,1))
        if entry and entry<=run.ASOF:
            _,ranks=r.books.candidates(pools,entry);selected.update(ranks)
    # Include the current saved-session candidate set without changing history.
    if sessions:
        active={s:rows for s,rows in pools[1].items() if universe[s].get('listed') is True}
        _,ranks=r.books.candidates((active,active),sessions[-1]);selected.update(ranks)
    return sorted(selected)


def derived_status():
    result=[]
    for name,path,open_db in [('January and latest database',r.DATABASE,r.connect),('Custom-date database',schedules.DATABASE,schedules.connect)]:
        state='missing'
        if path.exists():
            try:
                db=open_db();db.close();state='current'
            except (ValueError,OSError,sqlite3.Error):state='needs rebuild'
        result.append(dict(name=name,state=state,bytes=path.stat().st_size if path.exists() else 0))
    reference=ROOT/'results'/'summary-exits.txt'
    result.append(dict(name='Canonical January reference report',state='saved' if reference.exists() else 'missing — restore from backup',bytes=reference.stat().st_size if reference.exists() else 0))
    from build_state import current_build
    try:current=current_build()
    except OSError:current=False
    result.append(dict(name='Website build',state='current' if current else 'needs rebuild',bytes=0))
    return result


def inspect(o,emit=lambda **kw:None,stop=lambda:None):
    issues=[]
    try:universe=universe_rows()
    except (ValueError,TypeError):universe={};issues.append('US stock universe is invalid. Select universe for repair.')
    records,invalid=financial_records()
    try:targets=target_symbols(o,universe,records)
    except json.JSONDecodeError:targets=[];issues.append('SPY JSON is invalid. Select SPY for repair.')
    ledger=read_json(COVERAGE,{})
    start,end=map(date.fromisoformat,(o['start'],o['end']))
    missing=[s for s in universe if s not in records]
    empty=[s for s,record in records.items() if not record['rows']]
    fiscal_dates=sorted(str(row['date'])[:10] for record in records.values() for row in record['rows'] if isinstance(row,dict) and run.parse_day(row.get('date')))
    assets=[dict(name='US stock universe',state='saved' if universe else 'missing',count=len(universe),first=None,last=None),
            dict(name='Annual financials',state='invalid lines' if invalid else ('partial' if missing else 'saved'),count=sum(len(record['rows']) for record in records.values()),first=fiscal_dates[0] if fiscal_dates else None,last=fiscal_dates[-1] if fiscal_dates else None)]
    for name,file,field in [('SPY total-return prices','spy-div.json','adjClose'),('3-month Treasury yield','treasury.json','month3')]:
        asset=cache_assets.SeriesAsset(RAW/file,field)
        rows=asset.rows
        if asset.path.exists() and not asset.valid:issues.append(file+' is invalid. Select this data type for repair.')
        gaps=asset.missing(start,end,ledger)
        assets.append(dict(name=name,state='unrequested dates' if gaps else 'checked range',count=len(rows),first=rows[0]['date'][:10] if rows else None,last=rows[-1]['date'][:10] if rows else None))
    prices=[];available=0
    for i,symbol in enumerate(targets,1):
        stop();path=run.cache_path_for(symbol)
        asset=cache_assets.SeriesAsset(path,'adjClose',stock=True)
        rows=asset.rows;bad=path.exists() and not asset.valid
        gaps=asset.missing(start,end,ledger)
        available+=bool(rows)
        prices.append(dict(symbol=symbol,state='invalid' if bad else ('missing' if not path.exists() else 'empty' if not rows else 'unrequested dates' if gaps else 'checked range'),count=len(rows),first=rows[0]['date'][:10] if rows else None,last=rows[-1]['date'][:10] if rows else None,windows=len(gaps)))
        if i%50==0 or i==len(targets):emit(message=f'Checked stock prices {i}/{len(targets)}',completed=i,total=len(targets))
    return dict(issues=issues,checked_at=datetime.now(timezone.utc).isoformat(),options=o,api_key_present=run.KEY_PATH.is_file() and run.KEY_PATH.stat().st_size>0,
                assets=assets,universe=len(universe),financial_symbols=len(records),missing_financials=missing,empty_financials=empty,invalid_financial_lines=invalid,
                target_count=len(targets),price_files=sum(1 for _ in (RAW/'px').glob('*.json')),prices_available=available,prices=prices,derived=derived_status(),
                unavailable_metrics=['P/E: saved cache lacks earnings','P/B: saved cache lacks book values'])


def request_json(endpoint,params,stop):
    stop()
    status,payload=run.get_json(endpoint,params,paced=False)
    stop()
    if status!=200 or not isinstance(payload,list):
        raise ValueError(f'Data provider request failed (status {status}). Saved files were kept. Check your key, subscription or connection, then retry.')
    return payload


def fill_series(file,field,endpoint,o,ledger,emit,stop,symbol=None):
    path=run.cache_path_for(symbol) if symbol else RAW/file
    asset=cache_assets.SeriesAsset(path,field,stock=bool(symbol))
    asset.repair(ledger,COVERAGE)
    gaps=asset.missing(date.fromisoformat(o['start']),date.fromisoformat(o['end']),ledger)
    for start,end in gaps:
        for a,b in spans(start,end,monthly=field=='month3'):
            stop();emit(message=f'Downloading {symbol or file}: {a} to {b}')
            params={'from':a,'to':b}
            if symbol or field=='adjClose':params['symbol']=symbol or 'SPY'
            batch=request_json(endpoint,params,stop)
            asset.publish(batch,a,b,ledger,COVERAGE)


def download(o,emit,stop):
    selected=o['datasets'];ledger=read_json(COVERAGE,{})
    # A no-op download must not require a key. It is read only at a request.
    try:universe=universe_rows()
    except (ValueError,TypeError):universe={}
    if 'universe' in selected and not universe:
        emit(message='Downloading US stock universe')
        universe={}
        # Reuse stock eligibility rules; fail on provider errors before publishing.
        for exchange in ('NYSE','NASDAQ','AMEX'):
            for page in range(30):
                rows=request_json('company-screener',dict(exchange=exchange,isEtf='false',isFund='false',isActivelyTrading='true',limit=1000,page=page),stop)
                for row in rows:
                    symbol=str(row.get('symbol') or '');name=str(row.get('companyName') or '')
                    ex=str(row.get('exchangeShortName') or row.get('exchange') or exchange)
                    if run.common_stock(symbol,name) and run.us_exchange(ex) and not row.get('isEtf') and not row.get('isFund'):
                        universe[symbol]=dict(symbol=symbol,exchange=ex,sector=row.get('sector') or '',name=name,listed=True)
                if len(rows)<1000:break
            else:raise ValueError('US stock universe exceeded the page limit. No partial universe was saved.')
        for page in range(1000):
            rows=request_json('delisted-companies',dict(page=page,limit=100),stop)
            for row in rows:
                symbol=str(row.get('symbol') or '');name=str(row.get('companyName') or '');ex=str(row.get('exchange') or '')
                if run.common_stock(symbol,name) and run.us_exchange(ex):
                    universe.setdefault(symbol,dict(symbol=symbol,exchange=ex,sector='',name=name,listed=False))
            if len(rows)<100:break
        else:raise ValueError('Delisted list exceeded the page limit. No partial universe was saved.')
        if not universe:raise ValueError('No US stock universe was returned. Saved files were kept.')
        path=RAW/'universe.json'
        if path.exists():
            backup=RAW/'archive'/'universe.json.before-data-repair'
            if not backup.exists():backup.parent.mkdir(parents=True,exist_ok=True);backup.write_bytes(path.read_bytes())
        write_json(path,list(universe.values()))
    records,invalid=financial_records()
    if invalid and 'financials' in selected:
        path=RAW/'metrics.jsonl';backup=RAW/'archive'/'metrics.jsonl.before-data-repair'
        if not backup.exists():backup.parent.mkdir(parents=True,exist_ok=True);backup.write_bytes(path.read_bytes())
        temporary=path.with_name(path.name+'.download')
        temporary.write_text(''.join(json.dumps(row)+'\n' for row in records.values()),encoding='utf-8')
        temporary.replace(path)
        emit(message='Invalid financial lines preserved in raw/archive. Filling missing symbol records…')
    if 'financials' in selected:
        wanted=o['symbols'] if o['scope']=='symbols' else sorted(universe)
        if not universe:raise ValueError('Download the US stock universe first.')
        unknown=set(wanted)-universe.keys()
        if unknown:raise ValueError('A requested symbol is absent from the saved US universe.')
        pending=[s for s in wanted if s not in records]
        for i,symbol in enumerate(pending,1):
            emit(message=f'Downloading annual financials {i}/{len(pending)}: {symbol}',completed=i-1,total=len(pending))
            rows=request_json('key-metrics',dict(symbol=symbol,period='annual',limit=40),stop)
            record=run.slim_metrics(symbol,rows)
            path=RAW/'metrics.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
            # A valid final JSONL record need not end with a newline.
            needs_newline=path.exists() and path.stat().st_size>0
            if needs_newline:
                with path.open('rb') as handle:handle.seek(-1,2);needs_newline=handle.read(1)!=b'\n'
            with path.open('a',encoding='utf-8') as handle:handle.write(('\n' if needs_newline else '')+json.dumps(record)+'\n')
            records[symbol]=record
            emit(completed=i,total=len(pending))
    if 'spy' in selected:fill_series('spy-div.json','adjClose','historical-price-eod/dividend-adjusted',o,ledger,emit,stop)
    if 'treasury' in selected:fill_series('treasury.json','month3','treasury-rates',o,ledger,emit,stop)
    if 'prices' in selected:
        if not universe or not records:raise ValueError('Download the universe and annual financials before stock prices.')
        if o['scope']=='baseline' and not series(read_json(RAW/'spy-div.json',[]),'adjClose'):
            raise ValueError('Download SPY prices before the original candidate set.')
        targets=target_symbols(o,universe,records)
        for i,symbol in enumerate(targets,1):
            emit(message=f'Checking stock {i}/{len(targets)}: {symbol}',completed=i-1,total=len(targets))
            fill_series(None,'adjClose','historical-price-eod/dividend-adjusted',o,ledger,emit,stop,symbol=symbol)
            emit(completed=i,total=len(targets))
    return inspect(o,emit,stop)


class Jobs:
    def __init__(self):
        self.lock=Lock();self.cancel=Event()
        self.thread=None;self.report=None;self.rebuilt=False
        self.state=dict(running=False,action=None,message='Check the saved data to see coverage.',completed=0,total=0,error=None)

    def snapshot(self):
        with self.lock:return dict(job=dict(self.state),report=self.report)

    def emit(self,**values):
        with self.lock:self.state.update(values)

    def stop(self):
        if self.cancel.is_set():raise Cancelled()

    def start(self,action,request):
        if action not in ('check','download','rebuild'):raise ValueError('Choose check, download or rebuild.')
        o=options(request)
        with self.lock:
            if self.state['running']:raise ValueError('A data job is already running. Wait for it or cancel it.')
            self.cancel.clear();self.state=dict(running=True,action=action,message='Waiting for the current backtest to finish…',completed=0,total=0,error=None)
            self.thread=Thread(target=self.work,args=(action,o),daemon=False)
            self.thread.start()
        return self.snapshot()

    def work(self,action,o):
        try:
            # Audit and replacement share the same lock as custom backtests.
            with cache_access.access():
                self.stop()
                if action=='rebuild':
                    self.emit(message='Preparing January and custom-date databases…')
                    schedules.prepare();self.stop()
                    self.emit(message='Rebuilding the website…')
                    subprocess.run([sys.executable,'-X','utf8',str(ROOT/'website'/'build.py')],cwd=ROOT,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    self.rebuilt=True
                    report=inspect(o,self.emit,self.stop)
                elif action=='download':report=download(o,self.emit,self.stop)
                else:report=inspect(o,self.emit,self.stop)
                with self.lock:self.report=report
                self.emit(message='Rebuild complete. Open the strategy page to load the new data.' if action=='rebuild' else 'Download complete. Rebuild prepared data to use new files.' if action=='download' else 'Data check complete.')
        except Cancelled:self.emit(message='Cancelled. Completed downloads were kept. Retry to continue.')
        except (ValueError,FileNotFoundError) as error:
            # Only our validation errors are suitable for the UI. Provider URLs
            # and subprocess traces must never reach a status response.
            if isinstance(error,json.JSONDecodeError):message='A saved JSON file is invalid. Restore it from backup or repair that data type.'
            elif isinstance(error,FileNotFoundError):message='A required saved file or API key is missing. Check the data list and key setup.'
            else:message=str(error)
            self.emit(error=message,message='Data job failed. Existing completed files were kept.')
        except Exception:self.emit(error='Data operation failed. Check file access, provider access and available disk space, then retry.',message='Data job failed. Existing completed files were kept.')
        finally:self.emit(running=False)

    def cancel_job(self):
        self.cancel.set()
        self.emit(message='Cancellation requested. Waiting for the active request or preparation step to finish…')
        return self.snapshot()

    def close(self):
        self.cancel.set()
        if self.thread:self.thread.join()
