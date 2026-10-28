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

import backtest_control
import cache_access
import diagnostics
import robustness
import schedules


class Missing(ValueError):
    pass


class Busy(ValueError):
    pass


class Unavailable(ValueError):
    """No calculation began because admitted inputs are not ready."""


class Calculations:
    """Own input admission and engine cleanup for every application caller.

    Callers must not prehold financial ownership. Results become publishable
    only after engine cleanup. Readiness is checked against the admitted input
    snapshot; earlier status responses are advisory. This owner selects only
    the ordinary engine. It owns neither user records nor job lifetimes.
    """
    def __init__(self):
        self.ready=lambda:True
        self.lock=RLock()
        self.closed=Event()

    def close(self):
        """Close admission; existing job and HTTP owners drain accepted calls."""
        with self.lock:self.closed.set()

    def _checkpoint(self):
        backtest_control.checkpoint()
        if self.closed.is_set():raise backtest_control.Cancelled()

    @contextmanager
    def _financial(self,admission,progress):
        # Queue waiting repeats admission only, never an execution that began.
        waiting=False
        while True:
            self._checkpoint()
            ownership=cache_access.access(timeout=.25 if admission=='queue' else 30)
            try:ownership.__enter__()
            except cache_access.Contention:
                if admission!='queue':raise
                if not waiting:
                    if progress:progress(dict(type='waiting',message='Waiting for another backtest or data operation.'))
                    waiting=True
                self.closed.wait(.1)
                continue
            break
        try:
            self._checkpoint()
            if waiting and progress:progress(None)
            yield
        finally:ownership.__exit__(None,None,None)

    def calculate(self,mode,options,progress,configuration,*,planned=None,
                  admission='interactive',details=True):
        """Calculate once, with complete random holdings unless summary is requested.

        Interactive admission has the ordinary bounded wait. Queue admission
        waits cancellably through contention. Neither policy retries an engine
        error. Configuration is published before random work, under ownership.
        """
        if admission not in ('interactive','queue'):raise ValueError('Invalid calculation admission policy.')
        with self.lock:
            if self.closed.is_set():raise Busy('The server is stopping. Restart it before running a backtest.')
        with self._financial(admission,progress):
            ready=self.ready()
            self._checkpoint()  # Stop takes precedence over stale deferral.
            if not ready:raise Unavailable('Candidate preparation is unavailable. Rebuild from the data panel.')
            db=schedules.connect()
            try:
                db.execute('PRAGMA cache_size=-131072')
                if mode=='random':
                    if planned is None:planned=robustness.plan(db,**options)
                    if configuration:configuration(planned)
                    captured=[]
                    result=robustness.run(db,planned,progress=progress,
                        capture=(lambda number,trial:captured.append(trial)) if details else None)
                    if details:result['trial_results']=captured
                else:
                    evaluate=schedules.backtest_dates if 'dates' in options else schedules.backtest
                    result=evaluate(db,**options)
                backtest_control.checkpoint()
            finally:db.close()
        return result


def calculate(mode,options,progress,configuration,*,planned=None,owner=None,
              admission='interactive',details=True):
    """Shared application entry; standalone callers retain ordinary execution."""
    return (owner if owner is not None else Calculations()).calculate(
        mode,options,progress,configuration,planned=planned,admission=admission,details=details)


class Jobs:
    def __init__(self,calculations=None):
        self.lock=RLock()
        self.runs={}
        self.closing=False
        self.calculations=calculations if calculations is not None else Calculations()

    @property
    def ready(self):return self.calculations.ready

    @ready.setter
    def ready(self,value):self.calculations.ready=value

    def start(self,identifier,mode,options):
        if not re.fullmatch(r'[a-f0-9]{32}',identifier):
            raise ValueError('Invalid backtest run ID.')
        if mode not in ('custom','random') or not isinstance(options,dict):
            raise ValueError('Expected backtest mode and options.')
        json.dumps(options,allow_nan=False)
        with self.lock:
            if self.closing:raise Busy('The server is stopping. Restart it before running a backtest.')
            existing=self.runs.get(identifier)
            if existing:
                if existing['mode']!=mode or existing['options']!=options:
                    raise ValueError('This run ID already has different settings.')
                return self.snapshot(identifier)
            if any(run['state'] in ('running','stopping') for run in self.runs.values()):
                raise Busy('Another backtest is running on this server. Let it finish or stop it from its original browser.')
            now=time.time()
            for key in list(self.runs):
                if now-self.runs[key].get('finished',now)>86400:del self.runs[key]
            while len(self.runs)>=4:del self.runs[next(iter(self.runs))]
            run=dict(id=identifier,mode=mode,options=deepcopy(options),state='running',started=now,
                     progress=None,configuration=None,result=None,error=None,stop=Event())
            self.runs[identifier]=run
            thread=Thread(target=self._run,args=(run,),name='backtest-'+identifier[:8],daemon=False)
            run['thread']=thread
            thread.start()
            return self.snapshot(identifier)

    def snapshot(self,identifier,*,include_result=True):
        with self.lock:
            run=self.runs.get(identifier)
            if run and time.time()-run.get('finished',time.time())>86400:
                del self.runs[identifier]
            if identifier not in self.runs:
                raise Missing('This run is no longer available. The server may have restarted or the result expired. Run the backtest again.')
            return {key:value for key,value in self.runs[identifier].items()
                    if key not in ('stop','thread') and (include_result or key!='result')}

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
                result=calculate(run['mode'],run['options'],progress,configuration,owner=self.calculations)
            # Publish only after worker cleanup, database closure and cache release.
            with self.lock:
                run['result']=result
                run['state']='complete'
        except backtest_control.Cancelled:
            with self.lock:run['state']='cancelled'
        except Exception as error:
            diagnostics.failure('backtest_job.failed',error,mode=run['mode'])
            with self.lock:
                run['state']='failed'
                run['error']=str(error) if isinstance(error,(ValueError,TypeError)) else 'Backtest failed. Check the server development log.'
        finally:
            with self.lock:run['finished']=time.time()

    def close(self):
        with self.lock:
            self.closing=True
            threads=[]
            for run in self.runs.values():
                run['stop'].set()
                threads.append(run['thread'])
        for thread in threads:thread.join()
