"""Update policy and a small atomic progress record under existing cache ownership.

Only the cache owner publishes status and inputs. A foreign busy cache does not
identify an update: its saved running status remains unconfirmed until free.
"""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import json
import signal
from threading import Event, get_ident
import time

from backtest.inputs import cache_assets, daily, financial_inputs, fmp_download, market
from backtest.engines.original import book_batch
from backtest.runtime import backtest_control, cache_access, diagnostics
from website.server import data_manager as data

STAGES=('checking','annual','statements','prices','research','daily','website','sheets','verify')
LABELS=('Checking what needs updating','Updating company reports','Updating company reports',
        'Updating prices','Preparing for backtests','Preparing for backtests',
        'Preparing for backtests','Preparing backtest dates','Checking that backtests are ready')
_active=None


def status_path():
    return data.ROOT/'data/data-refresh.json'


def read_status():
    try:return cache_assets.read_json(status_path(),{})
    except (OSError,ValueError):return dict(outcome='failed',error='Update status could not be read.')


def report_policy(saved):
    """Managed checks use Hong Kong dates; missing history is due."""
    today=datetime.now(timezone(timedelta(hours=8))).date()
    last=saved.get('last_report_check');full=saved.get('last_full_sweep')
    due=(today.weekday()==5 and last!=str(today)) or last is None or (today-date.fromisoformat(last)).days>7
    sweep=full is None or (today-date.fromisoformat(full)).days>90
    return dict(today=today,due=due,sweep=sweep)


def report_symbols(universe,pending,*,sweep):
    return sorted(symbol for symbol,row in universe.items() if sweep or row.get('listed') or symbol in pending)


def timing_scope(scope):
    return dict(scope,end=None) if isinstance(scope,dict) else scope


def status():
    """Read without resuming work or claiming a foreign cache owner's identity."""
    if _active is not None and _active.root==data.ROOT:return _active.view()
    state=read_status()
    state.update(running=False,unconfirmed=False)
    if state.get('outcome') in ('running','incomplete'):
        try:
            if cache_access.workspace.path.exists():
                with cache_access.workspace.observe():state=read_status()
        except (cache_access.Contention,ValueError,OSError):
            state.update(outcome='unconfirmed',unconfirmed=True,stage='Update status unconfirmed. Another operation is using the saved data.')
        else:
            if state.get('outcome') in ('running','incomplete'):
                state.update(outcome='interrupted',stage='Update interrupted')
    state['running']=False
    state['can_continue']=not state.get('unconfirmed') and state.get('outcome') in ('interrupted','cancelled','partial','failed')
    return state


class Progress:
    """Save stage checkpoints and active seconds; estimate from one prior success.

    Its caller already owns the financial cache. There is no separate owner,
    per-asset completion store, or timing model. Receipts remain asset evidence.
    """
    def __init__(self,saved,scope=None,*,resume=False):
        self.root=data.ROOT;self.owner=get_ident();self.finished=False
        if resume:scope=saved.get('scope')
        if resume:self.state=dict(saved)
        else:self.state={key:saved[key] for key in ('pending_symbols','pending_markets','last_success','latest_session','last_timing','last_report_check','last_full_sweep') if key in saved}
        now=datetime.now(timezone.utc)
        if not resume:
            self.state.update(started_at=now.isoformat(),elapsed_seconds=0,completed_stages=[],stage_durations={},work={})
        self.state.setdefault('started_at',now.isoformat())
        self.state.setdefault('target_date',str((now-timedelta(hours=22)).date()))
        for key,default in (('elapsed_seconds',0),('completed_stages',[]),('stage_durations',{}),('work',{})):
            self.state.setdefault(key,default)
        self.state.update(scope=scope,outcome='running',finished_at=None,error=None,failed_assets=0,ready=False)
        self.last_tick=self.last_save=time.monotonic();self.save()

    def tick(self):
        now=time.monotonic();seconds=max(0,now-self.last_tick);self.last_tick=now
        self.state['elapsed_seconds']+=seconds
        kind=self.state.get('kind')
        if kind:self.state['stage_durations'][kind]=self.state['stage_durations'].get(kind,0)+seconds

    def save(self):
        self.tick()
        view=self.view()
        for key in ('percent','estimated_remaining_seconds'):self.state[key]=view[key]
        cache_assets.write_json(status_path(),self.state)
        self.last_save=time.monotonic()

    def checkpoint(self):
        if get_ident()==self.owner and time.monotonic()-self.last_save>=1:self.save()

    def emit(self,**values):
        if 'kind' not in values:return
        self.tick();kind=values['kind'];changed=kind!=self.state.get('kind')
        if changed:
            self.state['completed_stages']=self.state['completed_stages'][:STAGES.index(kind)]
            self.state['kind']=kind;self.state['stage']=LABELS[STAGES.index(kind)]
        self.state['work'][kind]=dict(completed=values.get('completed',0),total=values.get('total'))
        if values.get('skipped'):self.state['work'][kind]['skipped']=True
        if changed or time.monotonic()-self.last_save>=1:self.save()

    def done(self,kind,success=True):
        if success and len(self.state['completed_stages'])==STAGES.index(kind):
            self.state['completed_stages'].append(kind)
        self.save()

    def view(self):
        state=json.loads(json.dumps(self.state))
        if not self.finished:
            seconds=max(0,time.monotonic()-self.last_tick)
            state['elapsed_seconds']+=seconds
            if state.get('kind'):
                kind=state['kind'];state['stage_durations'][kind]=state['stage_durations'].get(kind,0)+seconds
        state.update(running=not self.finished,unconfirmed=False,can_continue=self.finished and state['outcome']!='complete',percent=None,estimated_remaining_seconds=None)
        previous=state.get('last_timing',{})
        durations={kind:0 if state['work'].get(kind,{}).get('skipped') else seconds
                   for kind,seconds in previous.get('durations',{}).items()}
        if state.get('kind') and timing_scope(previous.get('scope'))==timing_scope(state['scope']) and all(kind in durations for kind in STAGES):
            index=STAGES.index(state['kind']);counts=state['work'].get(state['kind'],{})
            total=counts.get('total');fraction=min(1,counts.get('completed',0)/total) if total else 0
            whole=sum(durations.values())
            if whole>0:
                state['percent']=min(99,int(100*(sum(durations[k] for k in STAGES[:index])+durations[state['kind']]*fraction)/whole))
                remaining=durations[state['kind']]*(1-fraction)
                if fraction>0:remaining=max(remaining,state['stage_durations'].get(state['kind'],0)*(1-fraction)/fraction)
                state['estimated_remaining_seconds']=remaining+sum(durations[k] for k in STAGES[index+1:])
        if state['outcome']=='complete':state['percent']=100
        if self.finished:state['estimated_remaining_seconds']=None
        return state

    def finish(self,outcome,*,error=None,ready=False):
        self.tick()
        self.state.update(outcome=outcome,error=error,ready=ready,finished_at=datetime.now(timezone.utc).isoformat())
        self.state['stage']={'complete':'Ready for backtests','partial':'Some data could not be updated','failed':'Update needs attention','cancelled':'Update stopped'}[outcome]
        if outcome=='complete':
            self.state['last_success']=self.state['finished_at']
            previous=self.state.get('last_timing',{})
            measured=previous.get('durations',{}) if timing_scope(previous.get('scope'))==timing_scope(self.state['scope']) else {}
            durations={kind:measured.get(kind,0) if self.state['work'].get(kind,{}).get('skipped') else seconds
                       for kind,seconds in self.state['stage_durations'].items()}
            self.state['last_timing']=dict(scope=self.state['scope'],durations=durations)
        self.save();self.finished=True


def request(endpoint,params,stop,client):
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
    """Refresh recent dates and known missing windows; retain complete histories."""
    def tasks():
        for file,field,endpoint,symbol in specs:
            stop()
            path=data.RAW/file if file else market.cache_path_for(symbol)
            asset=cache_assets.SeriesAsset(path,field,stock=bool(symbol and file is None),key=path.relative_to(data.RAW).as_posix())
            checked=asset.checked(ledger)
            first=min([asset.rows[0]['date'][:10]]+[a for a,_ in checked]) if asset.rows else '1995-01-01'
            if state['scope']:first=min(first,state['scope']['start'])
            ranges=[[str(a),str(b)] for a,b in asset.missing(date.fromisoformat(first),end,ledger)]
            recent=(max(asset.rows[0]['date'][:10],str(date.fromisoformat(asset.rows[-1]['date'][:10])-timedelta(days=7)))
                    if asset.rows else str(max(date(1995,1,1),end-timedelta(days=7))))
            if recent<=str(end):ranges.append([recent,str(end)])
            yield asset,cache_assets.coalesce_windows(ranges),field,symbol,endpoint
    def windows(ranges,field,symbol,endpoint):
        result=[]
        for start,end_day in ranges:
            for first,last in data.spans(date.fromisoformat(start),date.fromisoformat(end_day),monthly=field=='month3'):
                stop();params={'from':first,'to':last}
                if symbol or field=='adjClose':params['symbol']=symbol or 'SPY'
                rows=request(endpoint,params,stop,client)
                if rows is None:return None
                result.append((first,last,rows))
        return result
    emit(kind='prices',completed=0,total=len(specs))
    for number,(task,batches) in enumerate(client.map(tasks(),lambda task:windows(task[1],task[2],task[3],task[4])),1):
        stop();asset,_,field,symbol,endpoint=task
        if batches is None:failed(state,asset.key)
        else:
            try:
                admitted=[(first,last,*asset.validate(batch,first,last)) for first,last,batch in batches]
                current={row['date'][:10]:data.rules.num(row[field]) for _,_,rows,_ in admitted for row in rows}
                old={row['date'][:10]:data.rules.num(row[field]) for row in asset.rows}
                if field=='adjClose' and old and current:
                    overlap=current.keys() & old.keys()
                    if not overlap:raise ValueError('Price update has no saved overlap.')
                    if any(current[day]!=old[day] for day in overlap):
                        emit(message='Updating the complete adjusted history for '+(symbol or 'SPY')+'.')
                        batches=windows([[min('1995-01-01',asset.rows[0]['date'][:10]),str(end)]],field,symbol,endpoint)
                        if batches is None:failed(state,asset.key);continue
                        admitted=[(first,last,*asset.validate(batch,first,last)) for first,last,batch in batches]
                        replacement={row['date'][:10]:data.rules.num(row[field]) for _,_,rows,_ in admitted for row in rows}
                        if not (old.keys() | current.keys()) <= replacement.keys():raise ValueError('Adjusted history is incomplete.')
                        if any(replacement[day]!=value for day,value in current.items()):raise ValueError('Adjusted history changed during update.')
            except ValueError as error:failed(state,asset.key,error)
            else:
                asset.refresh(admitted,ledger,data.COVERAGE)
                emit(message='Updated '+(symbol or asset.path.name)+' through '+str(end)+'.')
        emit(kind='prices',completed=number,total=len(specs))


def download(state,end,emit,stop,client,progress,*,reports=None):
    """Continue keeps a successful stage prefix; unfinished stages are rechecked."""
    try:old=data.universe_rows()
    except (ValueError,TypeError):
        old={}
        path=data.RAW/'universe.json';backup=data.RAW/'archive/universe.json.before-data-repair'
        if path.exists() and not backup.exists():cache_assets.publish_bytes(backup,path.read_bytes())
    if 'checking' not in state['completed_stages'] or not old:
        emit(kind='checking',completed=0,total=1)
        current=data.fetch_universe(stop,client)
        pending=set(state.get('pending_symbols',[]))|set(current).difference(old)
        state['pending_symbols']=sorted(pending);progress.save()
        universe={symbol:{**row,'listed':False} for symbol,row in old.items()}
        for symbol,row in current.items():
            previous=universe.get(symbol,{})
            universe[symbol]={**previous,**row,'sector':row.get('sector') or previous.get('sector','')}
        if universe!=old:cache_assets.write_json(data.RAW/'universe.json',list(universe.values()))
        emit(kind='checking',completed=1,total=1);progress.done('checking')
    else:universe=old
    cache_assets.trim_financial_tail(data.RAW/'metrics.jsonl')
    records,invalid=data.financial_records()
    if invalid:raise ValueError('Repair invalid annual financial records before updating data.')
    ledger=cache_assets.read_json(data.COVERAGE,{})
    pending=set(state.get('pending_symbols',[]));scope=state['scope']
    if scope and scope.get('managed'):scope=None
    if scope:
        targets=set(data.target_symbols(scope,universe,records))
        wanted=sorted(targets) if scope['scope']!='financials' else sorted(universe)
    else:
        targets=set(data.target_symbols(dict(scope='cached'),universe,records))|pending
        targets.update(symbol for symbol in universe if 'px/'+market.cache_path_for(symbol).name in ledger)
        wanted=sorted(universe)
    if reports is not None:
        wanted=report_symbols(universe,pending,sweep=reports['sweep'])
    report_failures=state['failed_assets']
    due=reports is None or reports['due']
    if not due:
        for kind in ('annual','statements'):
            if kind not in state['completed_stages']:
                emit(kind=kind,completed=0,total=0,skipped=True);progress.done(kind)
    if due and ('annual' not in state['completed_stages'] or any(symbol not in records or not financial_inputs.completed(data.RAW,symbol,'key-metrics',ledger) for symbol in wanted)):
        emit(kind='annual',completed=0,total=len(wanted));before=state['failed_assets']
        for number,(symbol,rows) in enumerate(client.map(wanted,lambda symbol:request('key-metrics',dict(symbol=symbol,period='annual',limit=40),stop,client)),1):
            stop()
            if rows is None:failed(state,'key-metrics/'+symbol)
            else:
                try:rows=financial_inputs.publish(data.RAW,symbol,'key-metrics',rows,ledger,data.COVERAGE)
                except ValueError as error:failed(state,'key-metrics/'+symbol,error)
                else:
                    previous=records.get(symbol,dict(rows=[]));saved=previous.get('rows',[])
                    dates={data.rules.parse_day(row.get('date')) for row in saved}
                    merged=saved+[row for row in rows if data.rules.parse_day(row.get('date')) not in dates]
                    if symbol not in records or merged!=saved:
                        record=cache_assets.financial_record(symbol,merged)
                        if saved and not previous.get('full_response'):record['full_response']=False
                        if not scope and symbol not in targets and not data.r.books.statements({symbol:previous},universe) and data.r.books.statements({symbol:record},universe):
                            pending.add(symbol);targets.add(symbol)
                            state['pending_symbols']=sorted(pending);progress.save()
                        data.append_financial(record);records[symbol]=record
                    emit(message='Checked annual reports for '+symbol+'.')
            emit(kind='annual',completed=number,total=len(wanted))
        progress.done('annual',state['failed_assets']==before)
    if scope and scope['scope']=='financials':targets=set(data.target_symbols(scope,universe,records))
    targets=sorted(targets)
    report_targets=sorted(set(targets)&set(wanted)) if reports is not None else targets
    total=len(report_targets)*(len(financial_inputs.ENDPOINTS)-1)
    if due and ('statements' not in state['completed_stages'] or any(not financial_inputs.completed(data.RAW,symbol,endpoint,ledger) for symbol in report_targets for endpoint in financial_inputs.ENDPOINTS if endpoint!='key-metrics')):
        requests=((symbol,endpoint) for symbol in report_targets for endpoint in financial_inputs.ENDPOINTS if endpoint!='key-metrics')
        emit(kind='statements',completed=0,total=total);before=state['failed_assets']
        for number,(task,rows) in enumerate(client.map(requests,lambda task:request(task[1],dict(symbol=task[0],period='annual',limit=40),stop,client)),1):
            stop();symbol,endpoint=task
            if rows is None:failed(state,endpoint+'/'+symbol)
            else:
                try:financial_inputs.publish(data.RAW,symbol,endpoint,rows,ledger,data.COVERAGE)
                except ValueError as error:failed(state,endpoint+'/'+symbol,error)
                else:emit(message='Updated '+endpoint+' for '+symbol+'.')
            emit(kind='statements',completed=number,total=total)
        progress.done('statements',state['failed_assets']==before)
    reports_ok=state['failed_assets']==report_failures
    specs=[('spy-div.json','adjClose','historical-price-eod/dividend-adjusted',None),('treasury.json','month3','treasury-rates',None)]+[(None,'adjClose','historical-price-eod/dividend-adjusted',symbol) for symbol in targets]
    valid_prices='prices' in state['completed_stages']
    if valid_prices:
        for file,field,endpoint,symbol in specs:
            asset=cache_assets.SeriesAsset(market.cache_path_for(symbol) if symbol else data.RAW/file,field,stock=bool(symbol))
            if not asset.valid or not asset.evidence(ledger):valid_prices=False;break
    if not valid_prices:
        before=state['failed_assets'];refresh_series(specs,end,ledger,emit,stop,client,state)
        progress.done('prices',state['failed_assets']==before)
    if not scope:
        for symbol in pending:
            price=cache_assets.SeriesAsset(market.cache_path_for(symbol),'adjClose',stock=True)
            if price.rows and records.get(symbol,{}).get('rows') and all(financial_inputs.read(data.RAW,symbol,endpoint)[0] for endpoint in financial_inputs.ENDPOINTS):
                state['pending_symbols'].remove(symbol)
    progress.save()
    return reports_ok


@diagnostics.operation('data.refresh')
@cache_access.exclusive
def run(emit=lambda **kw:None,stop=lambda:None,*,scope=None,resume=False):
    """The existing cache owner holds publication through cancellation and closure."""
    global _active
    saved=read_status()
    if resume and saved.get('outcome')=='complete':
        return dict(saved,ready=all(row['state']=='current' for row in data.derived_status()),error=saved.get('error'))
    progress=Progress(saved,scope,resume=resume);_active=progress;state=progress.state
    scope=state['scope']
    reports=report_policy(saved) if scope is None or scope.get('managed') else None
    if reports is not None:
        if resume and reports['due'] and reports['sweep']:
            # A completed listed-company check does not prove a full sweep.
            state['completed_stages']=state['completed_stages'][:STAGES.index('annual')]
        for kind in ('annual','statements'):
            if not reports['due']:state['work'][kind]=dict(completed=0,total=0,skipped=True)
            elif state['work'].get(kind,{}).get('skipped'):
                # A previously skipped stage does not prove a report check.
                state['completed_stages']=state['completed_stages'][:STAGES.index(kind)]
                del state['work'][kind]
    def checkpoint():stop();progress.checkpoint()
    def feedback(**values):
        progress.emit(**values);emit(**values)
        if 'kind' in values:diagnostics.work(stage=values['kind'],completed=values.get('completed',0),total=values.get('total'))
    try:
        progress.save()
        with backtest_control.cancel_when(lambda:bool(stop())):
            try:
                end=date.fromisoformat(state['target_date'])
                if state['scope']:end=min(end,date.fromisoformat(state['scope']['end']))
                with fmp_download.Client(checkpoint,feedback) as client:
                    scope=state['scope']
                    reports_ok=True
                    foreign=[code for code in market.MARKETS if code!='us' and market.universe_path(data.RAW,code).exists()]
                    if scope and scope.get('market','us')!='us':
                        reports_ok=data.download_market(dict(scope,end=str(end)),feedback,checkpoint,client,refresh=True,refresh_state=state,reports=reports)
                        for kind in STAGES[:4]:progress.done(kind,state['failed_assets']==0)
                    else:
                        if scope or market.universe_path(data.RAW,'us').exists() or not foreign:
                            reports_ok=download(state,end,feedback,checkpoint,client,progress,reports=reports)
                        if not scope:
                            for code in foreign:
                                selected=data.options(dict(market=code,end=str(end)))
                                reports_ok=data.download_market(selected,feedback,checkpoint,client,refresh=True,refresh_state=state,reports=reports) and reports_ok
                            for kind in STAGES[:4]:progress.done(kind,state['failed_assets']==0)
                if reports is not None and reports['due'] and reports_ok and (state['scope'] is None or 'market' not in state['scope']):
                    state['last_report_check']=str(reports['today'])
                    if reports['sweep']:state['last_full_sweep']=str(reports['today'])
                    progress.save()
                if state['failed_assets']:state['error']=f"{state['failed_assets']} data items could not be updated. Completed work was kept. Continue to try again."
            except (fmp_download.Cancelled,backtest_control.Cancelled,KeyboardInterrupt):raise
            except Exception as error:
                diagnostics.failure('refresh.download_failed',error)
                state['error']='Some data could not be updated. Completed work was kept. Continue to try again.'
            checkpoint();data.rebuild(feedback,checkpoint)
            for kind in ('research','daily','website'):progress.done(kind)
            with closing(daily.connect()) as db:
                book_batch.precompute(db,feedback,checkpoint)
            diagnostics.lap('sheets')
            progress.done('sheets')
            feedback(kind='verify',completed=0,total=1)
            if any(row['state']!='current' for row in data.derived_status()):raise ValueError('Preparation is incomplete.')
            spy=cache_assets.SeriesAsset(data.RAW/'spy-div.json','adjClose')
            state['latest_session']=spy.rows[-1]['date'][:10] if spy.rows else None
            state['latest_dates']={'us':state['latest_session']} if state['latest_session'] else {}
            for code in market.MARKETS:
                if code=='us':continue
                rows=cache_assets.SeriesAsset(market.calendar_path(data.RAW,code),'close').rows
                if rows:state['latest_dates'][code]=rows[-1]['date'][:10]
            feedback(kind='verify',completed=1,total=1);progress.done('verify')
            progress.finish('partial' if state['error'] else 'complete',error=state['error'],ready=True)
    except (fmp_download.Cancelled,backtest_control.Cancelled,KeyboardInterrupt):
        progress.finish('cancelled',error='Update stopped. Completed work was kept.');raise
    except Exception:
        progress.finish('failed',error='Preparation could not finish. Continue to try again.');raise
    finally:
        data.r.forget_signature();_active=None
    emit(error=state['error'],message='Some data could not be updated. Saved inputs are ready.' if state['error'] else 'Data updated. Ready for backtests.')
    return progress.view()


def startup(emit):
    cancelled=Event()
    previous=signal.signal(signal.SIGINT,lambda *_:cancelled.set())
    def stop():
        if cancelled.is_set():raise fmp_download.Cancelled()
    try:
        with backtest_control.cancel_when(cancelled.is_set):return run(emit,stop)
    except (fmp_download.Cancelled,backtest_control.Cancelled):raise KeyboardInterrupt() from None
    finally:signal.signal(signal.SIGINT,previous)
