"""Refresh saved inputs, then use ordinary preparation before admitting work.

The data job or native startup owns the cache for this entire operation. Fetch
workers return responses; the owner alone publishes assets and refresh status.
"""
from datetime import date, datetime, timedelta, timezone
import signal
from threading import Event

from backtest.inputs import cache_assets, financial_inputs, fmp_download, market
from backtest.runtime import backtest_control, diagnostics
from website.server import data_manager as data


def status_path():
    return data.ROOT/'data'/'data-refresh.json'


def status():
    try:return cache_assets.read_json(status_path(),{})
    except (OSError,ValueError):
        return dict(outcome='failed',error='Refresh status could not be read.')


def save(state):
    cache_assets.write_json(status_path(),state)


def request(endpoint,params,stop,client):
    """A provider failure belongs to this asset; cancellation still stops work."""
    try:return data.request_json(endpoint,params,stop,client)
    except FileNotFoundError:raise
    except (OSError,ValueError) as error:
        diagnostics.failure('refresh.request_failed',error,endpoint=endpoint,symbol=params.get('symbol'))
        return None


def failed(state,asset,error=None):
    state['failed_assets']+=1
    if error is None:diagnostics.event('refresh.asset_failed',asset=asset)
    else:diagnostics.failure('refresh.asset_failed',error,asset=asset)


def refresh_series(specs,end,ledger,emit,stop,client,state):
    """Resume known gaps and refresh recent dates; publish one history at a time."""
    def tasks():
        for file,field,symbol in specs:
            stop()
            asset=cache_assets.SeriesAsset(market.cache_path_for(symbol) if symbol else data.RAW/file,
                                          field,stock=bool(symbol))
            if asset.path.exists() and not asset.valid:
                failed(state,asset.key);continue
            checked=asset.checked(ledger)
            first=min([asset.rows[0]['date'][:10]]+[a for a,_ in checked]) if asset.rows else '1995-01-01'
            ranges=[[str(a),str(b)] for a,b in asset.missing(date.fromisoformat(first),end,ledger)]
            recent=(max(asset.rows[0]['date'][:10],str(date.fromisoformat(asset.rows[-1]['date'][:10])-timedelta(days=7)))
                    if asset.rows else str(max(date(1995,1,1),end-timedelta(days=7))))
            if recent<=str(end):ranges.append([recent,str(end)])
            yield asset,cache_assets.coalesce_windows(ranges),field,symbol
    def windows(ranges,field,symbol):
        result=[]
        for start,end_day in ranges:
            for first,last in data.spans(date.fromisoformat(start),date.fromisoformat(end_day),monthly=field=='month3'):
                stop();params={'from':first,'to':last}
                if field=='adjClose':params['symbol']=symbol or 'SPY'
                endpoint='treasury-rates' if field=='month3' else 'historical-price-eod/dividend-adjusted'
                rows=request(endpoint,params,stop,client)
                if rows is None:return None
                result.append((first,last,rows))
        return result
    for task,batches in client.map(tasks(),lambda task:windows(task[1],task[2],task[3])):
        stop();asset,_,field,symbol=task
        if batches is None:
            failed(state,asset.key);continue
        try:
            admitted=[(first,last,*asset.validate(batch,first,last)) for first,last,batch in batches]
            current={row['date'][:10]:data.rules.num(row[field]) for _,_,rows,_ in admitted for row in rows}
            old={row['date'][:10]:data.rules.num(row[field]) for row in asset.rows}
            overlap=current.keys() & old.keys()
            if field=='adjClose' and old and current:
                if not overlap:raise ValueError('Price refresh has no saved overlap.')
                if any(current[day]!=old[day] for day in overlap):
                    emit(message='Refreshing the complete adjusted history for '+(symbol or 'SPY')+'…')
                    batches=windows([[min('1995-01-01',asset.rows[0]['date'][:10]),str(end)]],field,symbol)
                    if batches is None:
                        failed(state,asset.key);continue
                    admitted=[(first,last,*asset.validate(batch,first,last)) for first,last,batch in batches]
                    replacement={row['date'][:10]:data.rules.num(row[field]) for _,_,rows,_ in admitted for row in rows}
                    if not (old.keys() | current.keys()) <= replacement.keys():
                        raise ValueError('Adjusted history is incomplete.')
                    if any(replacement[day]!=value for day,value in current.items()):
                        raise ValueError('Adjusted history changed during refresh.')
        except ValueError as error:
            failed(state,asset.key,error);continue
        # Publication errors stop the job. Do not keep writing after an I/O failure.
        asset.refresh(admitted,ledger,data.COVERAGE)
        emit(message='Refreshed '+(symbol or asset.path.name)+' through '+str(end)+'.')


def download(state,end,emit,stop,client):
    state['failed_assets']=0
    old=data.universe_rows()
    emit(message='Refreshing US listings…')
    current=data.fetch_universe(stop,client)
    pending=set(state.get('pending_symbols',[]))|set(current).difference(old)
    state['pending_symbols']=sorted(pending)
    # Intent precedes universe publication: interruption cannot lose a new name.
    save(state)
    universe={symbol:{**row,'listed':False} for symbol,row in old.items()}
    for symbol,row in current.items():
        previous=universe.get(symbol,{})
        universe[symbol]={**previous,**row,'sector':row.get('sector') or previous.get('sector','')}
    if universe!=old:cache_assets.write_json(data.RAW/'universe.json',list(universe.values()))
    records,invalid=data.financial_records()
    if invalid:raise ValueError('Repair invalid annual financial records before refreshing data.')
    target_set=set(data.target_symbols(dict(scope='cached'),universe,records))|pending
    ledger=cache_assets.read_json(data.COVERAGE,{})
    for symbol,rows in client.map(sorted(universe),lambda symbol:request(
            'key-metrics',dict(symbol=symbol,period='annual',limit=40),stop,client)):
        stop()
        if rows is None:
            failed(state,'key-metrics/'+symbol);continue
        try:rows=financial_inputs.publish(data.RAW,symbol,'key-metrics',rows,ledger,data.COVERAGE)
        except ValueError as error:
            failed(state,'key-metrics/'+symbol,error);continue
        previous=records.get(symbol,dict(rows=[]))
        saved=previous.get('rows',[]);dates={data.rules.parse_day(row.get('date')) for row in saved}
        # Existing valuation reports keep their values. New fiscal dates enter
        # the same policy. Complete provider variants also stay in raw inputs.
        merged=saved+[row for row in rows if data.rules.parse_day(row.get('date')) not in dates]
        if symbol not in records or merged!=saved:
            record=cache_assets.financial_record(symbol,merged)
            if saved and not previous.get('full_response'):record['full_response']=False
            if (symbol not in target_set and not data.r.books.statements({symbol:previous},universe)
                    and data.r.books.statements({symbol:record},universe)):
                pending.add(symbol);target_set.add(symbol)
                state['pending_symbols']=sorted(pending);save(state)
            data.append_financial(record);records[symbol]=record
        emit(message='Checked annual reports for '+symbol+'.')
    targets=sorted(target_set)
    requests=((symbol,endpoint) for symbol in targets for endpoint in financial_inputs.ENDPOINTS
              if endpoint!='key-metrics')
    for task,rows in client.map(requests,lambda task:request(
            task[1],dict(symbol=task[0],period='annual',limit=40),stop,client)):
        stop();symbol,endpoint=task
        if rows is None:
            failed(state,endpoint+'/'+symbol);continue
        try:financial_inputs.publish(data.RAW,symbol,endpoint,rows,ledger,data.COVERAGE)
        except ValueError as error:
            failed(state,endpoint+'/'+symbol,error);continue
        emit(message='Refreshed '+endpoint+' for '+symbol+'.')
    specs=[('spy-div.json','adjClose',None),('treasury.json','month3',None)]
    specs.extend((None,'adjClose',symbol) for symbol in targets)
    refresh_series(specs,end,ledger,emit,stop,client,state)
    for symbol in pending:
        price=cache_assets.SeriesAsset(market.cache_path_for(symbol),'adjClose',stock=True)
        if price.rows and records.get(symbol,{}).get('rows') and all(
                financial_inputs.read(data.RAW,symbol,endpoint)[0] for endpoint in financial_inputs.ENDPOINTS):
            state['pending_symbols'].remove(symbol)
    save(state)


@diagnostics.operation('data.refresh')
def run(emit=lambda **kw:None,stop=lambda:None):
    """Called only under cache ownership, manually or before native startup."""
    state=cache_assets.read_json(status_path(),{})
    state.update(started_at=datetime.now(timezone.utc).isoformat(),finished_at=None,
                 outcome='incomplete',error=None,failed_assets=0)
    save(state)
    try:
        try:
            # 22:00 UTC is after the US close in both seasons. Do not request
            # an unfinished US session when the manual action runs earlier.
            end=(datetime.now(timezone.utc)-timedelta(hours=22)).date()
            with fmp_download.Client(stop,emit) as client:download(state,end,emit,stop,client)
            if state['failed_assets']:
                state['error']=f"{state['failed_assets']} data assets could not be refreshed. Completed downloads were kept; retry Refresh data."
        except (fmp_download.Cancelled,backtest_control.Cancelled,KeyboardInterrupt):raise
        except Exception as error:
            diagnostics.failure('refresh.download_failed',error)
            state['error']='Data refresh was incomplete. Completed downloads were kept; retry Refresh data.'
        stop()
        data.rebuild(emit,stop)
        spy=cache_assets.SeriesAsset(data.RAW/'spy-div.json','adjClose')
        state.update(outcome='partial' if state['error'] else 'complete',
                     latest_session=spy.rows[-1]['date'][:10] if spy.rows else None)
        if not state['error']:state['last_success']=datetime.now(timezone.utc).isoformat()
    except (fmp_download.Cancelled,backtest_control.Cancelled,KeyboardInterrupt):
        state.update(outcome='cancelled',error='Refresh stopped. Completed downloads were kept.')
        raise
    except Exception as error:
        diagnostics.failure('refresh.prepare_failed',error)
        state.update(outcome='failed',error='Prepared data could not be rebuilt. Retry preparation before calculating.')
        raise
    finally:
        data.r.forget_signature()
        state['finished_at']=datetime.now(timezone.utc).isoformat();save(state)
    emit(error=state['error'],message='Refresh incomplete. Prepared saved inputs are ready.' if state['error'] else 'Refresh complete. Open the strategy page to load the new data.')
    return state


def startup(emit):
    """Translate startup interrupts into cancellation, retaining worker ownership.

    Unlike an HTTP data job, this runs on the main thread. A second Ctrl+C
    must not interrupt its worker joins or release source/cache ownership early.
    """
    cancelled=Event()
    previous=signal.signal(signal.SIGINT,lambda *_:cancelled.set())
    def stop():
        if cancelled.is_set():raise fmp_download.Cancelled()
    try:
        with backtest_control.cancel_when(cancelled.is_set):return run(emit,stop)
    except (fmp_download.Cancelled,backtest_control.Cancelled):
        raise KeyboardInterrupt() from None
    finally:signal.signal(signal.SIGINT,previous)
