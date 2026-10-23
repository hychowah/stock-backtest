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
import financial_inputs
import cache_assets
import cache_access
from cache_assets import read_json, write_json, series

import schedules
import research as r
import run
import fmp_download
import diagnostics
import baseline

ROOT=r.ROOT
RAW=r.RAW
COVERAGE=RAW/'download-coverage.json'
KINDS=('universe','financials','fundamentals','prices','spy','treasury')



Cancelled=fmp_download.Cancelled



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
        stop=min(end,date(start.year,start.month,monthrange(start.year,start.month)[1]) if monthly else date(min(start.year+9,end.year),12,31))
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


def baseline_audit():
    """Return the last committed revision for the check report and JSON export."""
    try:
        db=r.connect(check=False)
    except (ValueError,OSError,sqlite3.Error):return None
    try:return baseline.Baseline(r.RESULTS,r.DATABASE).audit(db)
    finally:db.close()


def price_warning(name,days):
    dates=', '.join(days[:3])+('…' if len(days)>3 else '')
    noun='price' if len(days)==1 else 'prices'
    return f'{name}: skipped {len(days)} zero or negative adjusted {noun} ({dates}). No usable price was saved for these dates.'


def inspect(o,emit=lambda **kw:None,stop=lambda:None):
    issues=[];warnings=[]
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
        skipped=asset.skipped_dates(ledger)
        if skipped:warnings.append(price_warning(file,skipped))
        assets.append(dict(name=name,state='unrequested dates' if gaps else 'checked range',count=len(rows),first=rows[0]['date'][:10] if rows else None,last=rows[-1]['date'][:10] if rows else None,skipped_dates=skipped))
    fundamental_missing={endpoint:[symbol for symbol in targets if not financial_inputs.completed(RAW,symbol,endpoint,ledger)] for endpoint in financial_inputs.ENDPOINTS}
    assets.append(dict(name='Financial ratio inputs (annual statements)',state='missing inputs' if any(fundamental_missing.values()) else 'checked',count=sum(len(targets)-len(missing) for missing in fundamental_missing.values()),first=None,last=None))
    prices=[];available=0
    for i,symbol in enumerate(targets,1):
        stop();path=run.cache_path_for(symbol)
        asset=cache_assets.SeriesAsset(path,'adjClose',stock=True)
        rows=asset.rows;bad=path.exists() and not asset.valid
        gaps=asset.missing(start,end,ledger)
        available+=bool(rows)
        skipped=asset.skipped_dates(ledger)
        if skipped:warnings.append(price_warning(symbol,skipped))
        prices.append(dict(symbol=symbol,state='invalid' if bad else ('missing' if not path.exists() else 'empty' if not rows else 'unrequested dates' if gaps else 'checked range'),count=len(rows),first=rows[0]['date'][:10] if rows else None,last=rows[-1]['date'][:10] if rows else None,windows=len(gaps),skipped_dates=skipped))
        if i%50==0 or i==len(targets):emit(message=f'Checked stock prices {i}/{len(targets)}',completed=i,total=len(targets))
    return dict(issues=issues,warnings=warnings,checked_at=datetime.now(timezone.utc).isoformat(),options=o,api_key_present=run.KEY_PATH.is_file() and run.KEY_PATH.stat().st_size>0,
                assets=assets,universe=len(universe),financial_symbols=len(records),missing_financials=missing,empty_financials=empty,invalid_financial_lines=invalid,
                target_count=len(targets),price_files=sum(1 for _ in (RAW/'px').glob('*.json')),prices_available=available,prices=prices,derived=derived_status(),baseline=baseline_audit(),
                missing_ratio_inputs=fundamental_missing, unavailable_metrics=[])


def request_json(endpoint,params,stop,client=None):
    if client is not None:return client.request(endpoint,params)
    with fmp_download.Client(stop) as session:return session.request(endpoint,params)


def fill_series(file,field,endpoint,o,ledger,emit,stop,symbol=None):
    specs=[(file,field,endpoint,symbol)]
    with fmp_download.Client(stop,emit) as client:
        download_series(specs,o,ledger,emit,stop,client)


def download_series(specs,o,ledger,emit,stop,client):
    """Plan lazily within the client's submission bound; publish on this thread.

    The original saved span plus individual completed windows defines coverage.
    Out-of-order results cannot hide unfinished windows inside an expanded span.
    Only the writer owns asset objects and the completion ledger.
    """
    saved=0;finished=0;total=len(specs)
    def progress():
        emit(message=f'Saved {saved} price/yield windows; {finished}/{total} histories complete · up to {client.workers} parallel requests.',
             completed=finished,total=total,workers=client.workers,requests_saved=saved)
    def tasks():
        nonlocal finished
        for file,field,endpoint,symbol in specs:
            stop()
            path=run.cache_path_for(symbol) if symbol else RAW/file
            asset=cache_assets.SeriesAsset(path,field,stock=bool(symbol))
            asset.repair(ledger,COVERAGE)
            windows=[window for a,b in asset.missing(date.fromisoformat(o['start']),date.fromisoformat(o['end']),ledger)
                     for window in spans(a,b,monthly=field=='month3')]
            owner=dict(asset=asset,left=len(windows))
            if not windows:
                finished+=1
                if finished%50==0 or finished==total:progress()
            for a,b in windows:
                params={'from':a,'to':b}
                if symbol or field=='adjClose':params['symbol']=symbol or 'SPY'
                yield owner,a,b,endpoint,params
    for task,batch in client.map(tasks(),lambda task:request_json(task[3],task[4],stop,client)):
        stop();owner,a,b,_,_=task
        try:skipped=owner['asset'].publish(batch,a,b,ledger,COVERAGE)
        except Exception as error:
            diagnostics.failure('download.publish_failed',error,asset=owner['asset'].key,start=a,end=b)
            raise
        diagnostics.event('download.saved',asset=owner['asset'].key,start=a,end=b,rows=len(batch),skipped=len(skipped))
        if skipped:emit(warning=price_warning(owner['asset'].key,skipped))
        saved+=1;owner['left']-=1
        if not owner['left']:finished+=1
        progress()


def download(o,emit,stop):
    with fmp_download.Client(stop,emit) as client:
        return _download(o,emit,stop,client)


def _download(o,emit,stop,client):
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
                rows=request_json('company-screener',dict(exchange=exchange,isEtf='false',isFund='false',isActivelyTrading='true',limit=1000,page=page),stop,client)
                for row in rows:
                    symbol=str(row.get('symbol') or '');name=str(row.get('companyName') or '')
                    ex=str(row.get('exchangeShortName') or row.get('exchange') or exchange)
                    if run.common_stock(symbol,name) and run.us_exchange(ex) and not row.get('isEtf') and not row.get('isFund'):
                        universe[symbol]=dict(symbol=symbol,exchange=ex,sector=row.get('sector') or '',name=name,listed=True)
                if len(rows)<1000:break
            else:raise ValueError('US stock universe exceeded the page limit. No partial universe was saved.')
        for page in range(1000):
            rows=request_json('delisted-companies',dict(page=page,limit=100),stop,client)
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
        for completed,(symbol,rows) in enumerate(client.map(pending,lambda symbol:request_json('key-metrics',dict(symbol=symbol,period='annual',limit=40),stop,client)),1):
            stop()
            record=run.financial_record(symbol,rows)
            path=RAW/'metrics.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
            # A valid final JSONL record need not end with a newline.
            needs_newline=path.exists() and path.stat().st_size>0
            if needs_newline:
                with path.open('rb') as handle:handle.seek(-1,2);needs_newline=handle.read(1)!=b'\n'
            with path.open('a',encoding='utf-8') as handle:handle.write(('\n' if needs_newline else '')+json.dumps(record)+'\n')
            records[symbol]=record
            emit(message=f'Saved annual financials {completed}/{len(pending)} · up to {client.workers} parallel requests.',completed=completed,total=len(pending),workers=client.workers)
    if 'fundamentals' in selected:
        if not universe:raise ValueError('Download the US stock universe first.')
        targets=target_symbols(o,universe,records)
        # Reuse full key-metric responses already saved by the financial downloader.
        for symbol in targets:
            record=records.get(symbol,{})
            if record.get('full_response') is True and not financial_inputs.completed(RAW,symbol,'key-metrics',ledger):
                financial_inputs.publish(RAW,symbol,'key-metrics',record['rows'],ledger,COVERAGE)
        pending=[(symbol,endpoint) for symbol in targets for endpoint in financial_inputs.ENDPOINTS if not financial_inputs.completed(RAW,symbol,endpoint,ledger)]
        for completed,(task,rows) in enumerate(client.map(pending,lambda task:request_json(task[1],dict(symbol=task[0],period='annual',limit=40),stop,client)),1):
            stop();symbol,endpoint=task
            financial_inputs.publish(RAW,symbol,endpoint,rows,ledger,COVERAGE)
            emit(message=f'Saved financial ratio inputs {completed}/{len(pending)}.',completed=completed,total=len(pending),workers=client.workers)
    market=[]
    if 'spy' in selected:market.append(('spy-div.json','adjClose','historical-price-eod/dividend-adjusted',None))
    if 'treasury' in selected:market.append(('treasury.json','month3','treasury-rates',None))
    if market:download_series(market,o,ledger,emit,stop,client)
    if 'prices' in selected:
        if not universe or not records:raise ValueError('Download the universe and annual financials before stock prices.')
        if o['scope']=='baseline' and not series(read_json(RAW/'spy-div.json',[]),'adjClose'):
            raise ValueError('Download SPY prices before the original candidate set.')
        targets=target_symbols(o,universe,records)
        download_series([(None,'adjClose','historical-price-eod/dividend-adjusted',symbol) for symbol in targets],o,ledger,emit,stop,client)
    return inspect(o,emit,stop)


class Jobs:
    def __init__(self):
        self.lock=Lock();self.cancel=Event()
        self.thread=None;self.report=None;self.rebuilt=False
        self.state=dict(running=False,action=None,message='Check the saved data to see coverage.',completed=0,total=0,error=None,warning='')

    def snapshot(self):
        path=diagnostics.log_path()
        with self.lock:return dict(job=dict(self.state),report=self.report,log_file=diagnostics.relative_path(path) if path else None)

    def emit(self,**values):
        with self.lock:self.state.update(values)

    def stop(self):
        if self.cancel.is_set():raise Cancelled()

    def start(self,action,request):
        if action not in ('check','download','rebuild'):raise ValueError('Choose check, download or rebuild.')
        o=options(request)
        with self.lock:
            if self.state['running']:raise ValueError('A data job is already running. Wait for it or cancel it.')
            self.cancel.clear();self.state=dict(running=True,action=action,message='Waiting for the current backtest to finish…',completed=0,total=0,error=None,warning='')
            self.thread=Thread(target=self.work,args=(action,o),daemon=False)
            self.thread.start()
        return self.snapshot()

    def work(self,action,o):
        diagnostics.event('data.started',action=action,scope=o['scope'],start=o['start'],end=o['end'],datasets=o['datasets'],symbol_count=len(o['symbols']))
        try:
            # Audit and replacement share the same lock as custom backtests.
            with cache_access.access():
                self.stop()
                if action=='rebuild':
                    self.emit(message='Preparing January and custom-date databases…')
                    schedules.prepare();self.stop()
                    self.emit(message='Rebuilding the website…')
                    subprocess.run([sys.executable,'-X','utf8',str(ROOT/'website'/'build.py'),'--cache-owned'],cwd=ROOT,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    self.rebuilt=True
                    report=inspect(o,self.emit,self.stop)
                elif action=='download':report=download(o,self.emit,self.stop)
                else:report=inspect(o,self.emit,self.stop)
                with self.lock:self.report=report
                self.emit(warning=' '.join(report.get('warnings',[])))
                self.emit(message='Rebuild complete. Open the strategy page to load the new data.' if action=='rebuild' else 'Download complete. Rebuild prepared data to use new files.' if action=='download' else 'Data check complete.')
                diagnostics.event('data.completed',action=action)
        except Cancelled:
            diagnostics.event('data.cancelled',action=action)
            self.emit(message='Cancelled. Completed downloads were kept. Retry to continue.')
        except (ValueError,FileNotFoundError) as error:
            diagnostics.failure('data.failed',error,action=action)
            # Only our validation errors are suitable for the UI. Provider URLs
            # and subprocess traces must never reach a status response.
            if isinstance(error,json.JSONDecodeError):message='A saved JSON file is invalid. Restore it from backup or repair that data type.'
            elif isinstance(error,FileNotFoundError):message='A required saved file or API key is missing. Check the data list and key setup.'
            else:message=str(error)
            self.emit(error=message,message='Data job failed. Existing completed files were kept.')
        except Exception as error:
            diagnostics.failure('data.failed',error,action=action)
            self.emit(error='Data operation failed. Check the development log below for details, then retry.',message='Data job failed. Existing completed files were kept.')
        finally:self.emit(running=False)

    def cancel_job(self):
        self.cancel.set()
        self.emit(message='Cancellation requested. Waiting for the active request or preparation step to finish…')
        return self.snapshot()

    def close(self):
        self.cancel.set()
        if self.thread:self.thread.join()
