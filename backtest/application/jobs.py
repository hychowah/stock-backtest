"""Server-owned website runs. Only an explicit stop cancels calculation.

One run per server can own the existing engine adapter. Completed results stay
available for 24 hours (up to four runs), or until the server exits. Run IDs are
unguessable browser-generated capabilities, also used to make retries idempotent.
"""
from copy import deepcopy
from contextlib import contextmanager
import json
import re
from threading import Event, RLock, Thread
import time

from backtest.runtime import backtest_control as backtest_control
from backtest.runtime import diagnostics as diagnostics
from backtest.application import temporary_evidence as job_evidence
from backtest.application import evidence_transfer
from backtest.application import durable_evidence as durable_evidence
from backtest.application import strategy_requests
class Missing(ValueError):
    pass


from backtest.application.calculation_contract import Busy, engine_id
from backtest.application.original_calculations import Original

class Jobs:
    def __init__(self,calculations=None,*,evidence_root=None,evidence_bytes=1024**3):
        self.lock=RLock()
        self.runs={}
        self.closing=False
        self.calculations=calculations if calculations is not None else Original()
        self.evidence=job_evidence.Workspace(evidence_root,max_bytes=evidence_bytes)

    @property
    def ready(self):return self.calculations.ready

    @ready.setter
    def ready(self,value):self.calculations.ready=value

    def start(self,identifier,mode,options,*,planned=None):
        return self._start(identifier,mode,options,planned=planned)

    def accepted(self,identifier):
        """A retry reconciles accepted intent without fresh calculation admission."""
        try:self.snapshot(identifier,include_result=False)
        except Missing:return False
        return True

    def start_evidence(self,identifier,mode,options,*,planned=None,max_bytes=256*1024**2,
                       piece_bytes=1024*1024,record_bytes=8*1024*1024):
        """Explicit temporary evidence job. No HTTP or browser route selects it."""
        return self._start(identifier,mode,options,planned=planned,
            limits=dict(max_bytes=max_bytes,piece_bytes=piece_bytes,record_bytes=record_bytes))

    def _drop(self,identifier):
        run=self.runs.pop(identifier)
        if run.get('_evidence') is not None:self.evidence.discard(run['_evidence'])

    def _start(self,identifier,mode,options,*,planned=None,limits=None):
        if not re.fullmatch(r'[a-f0-9]{32}',identifier):
            raise ValueError('Invalid backtest run ID.')
        strategy_requests.require_mode(mode)
        scalar=isinstance(options,dict) and 'strategy' in options
        options=strategy_requests.canonical_options(options)
        accepted=scalar and self.accepted(identifier)
        if not accepted:
            # Refuse an engine this owner does not run before any strategy check.
            self.calculations.preflight(options,planned=planned)
            strategy_requests.check_request(dict(id=identifier,mode=mode,options=options,planned=planned))
        if scalar and limits is None:
            limits=dict(max_bytes=256*1024**2,piece_bytes=1024*1024,record_bytes=8*1024*1024)
        if mode not in (strategy_requests.SCALAR_MODES if scalar else ('custom','random')) or not isinstance(options,dict):
            raise ValueError('Expected backtest mode and options.')
        json.dumps(options,allow_nan=False)
        if limits is None:json.dumps(planned,allow_nan=False)
        if planned is not None and (mode!='random' or not isinstance(planned,dict)):
            raise ValueError('A recorded plan requires random mode.')
        with self.lock:
            if self.closing:raise Busy('The server is stopping. Restart it before running a backtest.')
            existing=self.runs.get(identifier)
            if existing:
                reference=existing.get('_plan_identity')
                candidate=None
                if limits is not None:
                    candidate=evidence_transfer.plan_identity(planned) if planned is not None else None
                if (existing['mode']!=mode or existing['options']!=options
                        or bool(existing.get('_evidence'))!=(limits is not None)
                        or (reference!=candidate if limits is not None else existing.get('planned')!=planned)):
                    raise ValueError('This run ID already has different settings.')
                return self.snapshot(identifier)
            if any(run['state'] in ('running','stopping') for run in self.runs.values()):
                raise Busy('Another backtest is running on this server. Let it finish or stop it from its original browser.')
            now=time.time()
            entry=self.evidence.reserve(planned=planned,**limits) if limits is not None else None
            for key in list(self.runs):
                if now-self.runs[key].get('finished',now)>86400:self._drop(key)
            while len(self.runs)>=4:self._drop(next(iter(self.runs)))
            run=dict(id=identifier,mode=mode,options=deepcopy(options),state='running',started=now,
                     progress=None,configuration=None,result=None,error=None,stop=Event(),planned=deepcopy(planned) if entry is None else None)
            run['engine']=engine_id(options)
            if entry is not None:
                run.update(_evidence=entry,_plan_identity=entry['reference']['sha256'] if entry['reference'] else None,evidence=None)
            self.runs[identifier]=run
            thread=Thread(target=self._run,args=(run,),name='backtest-'+identifier[:8],daemon=False)
            run['thread']=thread
            try:thread.start()
            except BaseException:
                self._drop(identifier)
                raise
            return self.snapshot(identifier)

    def snapshot(self,identifier,*,include_result=True):
        with self.lock:
            run=self.runs.get(identifier)
            if run and time.time()-run.get('finished',time.time())>86400:
                self._drop(identifier)
            if identifier not in self.runs:
                raise Missing('This run is no longer available. The server may have restarted or the result expired. Run the backtest again.')
            return {key:value for key,value in self.runs[identifier].items()
                    if key not in ('stop','thread') and not key.startswith('_') and (include_result or key!='result')}

    @contextmanager
    def open_evidence(self,identifier):
        """Pin immutable complete evidence independently of calculation resources."""
        with self.lock:
            self.snapshot(identifier)
            run=self.runs[identifier]
            if run['state']!='complete' or run.get('_evidence') is None:raise Missing('Complete evidence is unavailable.')
            entry=run['_evidence'];pin=self.evidence.pin(entry);stream=pin.__enter__()
        try:yield self.evidence.read(entry,stream)
        finally:pin.__exit__(None,None,None)

    @contextmanager
    def display_evidence(self,identifier,display):
        """Acquire original job evidence for a display, independently of expiry."""
        with self.lock:
            self.snapshot(identifier)
            run=self.runs[identifier]
            if run['state']!='complete' or run.get('_evidence') is None:raise Missing('Complete evidence is unavailable.')
            entry=run['_evidence'];pin=self.evidence.pin(entry);stream=pin.__enter__()
        try:
            reader=self.evidence.read(entry,stream)
            scalar=reader.format_version==2
            metadata=dict(version=4 if scalar else 3,kind=run['mode'],settings=dict(mode=run['mode'],**deepcopy(run['options'])),
                result=reader.manifest['summary'],catalog=dict(metrics={},filters={}) if scalar else display.get('catalog'),
                presentation=dict(kind='scalar') if scalar else display.get('presentation'),captured_at=display.get('captured_at'))
            durable_evidence.encode(metadata,durable_evidence.MAX_METADATA_BYTES)
            durable_evidence.validate_metadata(metadata,reader)
            class Opened:
                def __init__(opened):opened.reader=reader;opened.metadata=metadata
                def open_reader(opened):return self.evidence.fork_pinned(entry,reader)
                def close(opened):pass  # The enclosing source context owns the pin.
            yield Opened()
        finally:pin.__exit__(None,None,None)

    def cancel(self,identifier):
        with self.lock:
            self.snapshot(identifier)
            run=self.runs[identifier]
            if run['state']=='running':
                run['state']='stopping'
                run['stop'].set()
            return self.snapshot(identifier)

    def _run(self,run):
        def progress(event):
            with self.lock:run['progress']=deepcopy(event)
        def configuration(value):
            with self.lock:run['configuration']=value
        try:
            with backtest_control.cancel_when(run['stop'].is_set):
                entry=run.get('_evidence')
                if entry is not None:
                    with self.evidence.destination(entry) as destination:
                        completion=self.calculations.calculate_into(run['mode'],run['options'],destination,progress,configuration,
                            planned=self.evidence.plan(entry),**entry['limits'])
                    backtest_control.checkpoint()
                    descriptor=self.evidence.publish(entry,completion)
                    result=None
                else:
                    result=self.calculations.calculate(run['mode'],run['options'],progress,configuration,
                        **({'planned':run['planned']} if run.get('planned') is not None else {}))
            # Publish only after worker cleanup, database closure and cache release.
            with self.lock:
                if entry is not None and run['stop'].is_set():raise backtest_control.Cancelled()
                run['result']=result
                run['state']='complete'
                if entry is not None:run['evidence']=descriptor
        except backtest_control.Cancelled:
            with self.lock:run['state']='cancelled'
        except Exception as error:
            diagnostics.failure('backtest_job.failed',error,mode=run['mode'])
            with self.lock:
                run['state']='failed'
                run['error']=str(error) if isinstance(error,(ValueError,TypeError)) else 'Backtest failed. Check the server development log.'
                if 'strategy' in run['options']:
                    run.update(strategy_requests.failure_details(error) or {})
        finally:
            if run.get('_evidence') is not None and run['state']!='complete':self.evidence.discard(run['_evidence'])
            with self.lock:run['finished']=time.time()

    def request_stop(self):
        """Close admission and signal all accepted work before owners drain."""
        with self.lock:
            self.closing=True
            for run in self.runs.values():
                run['stop'].set()

    def close(self):
        self.request_stop()
        with self.lock:threads=[run['thread'] for run in self.runs.values()]
        for thread in threads:thread.join()
        self.evidence.close()
