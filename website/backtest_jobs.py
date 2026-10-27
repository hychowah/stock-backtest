"""Server-owned website runs. Only an explicit stop cancels calculation.

One run per server can own the existing engine adapter. Completed results stay
available for 24 hours (up to four runs), or until the server exits. Run IDs are
unguessable browser-generated capabilities, also used to make retries idempotent.
"""
from copy import deepcopy
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


def calculate(mode,options,progress,configuration,*,planned=None):
    """Run one website test under cache ownership; return after engine cleanup."""
    with cache_access.daily() as db:
        backtest_control.checkpoint()
        db.execute('PRAGMA cache_size=-131072')
        if mode=='random':
            if planned is None:planned=robustness.plan(db,**options)
            configuration(planned)
            details=[]
            result=robustness.run(db,planned,progress=progress,capture=lambda number,trial:details.append(trial))
            result['trial_results']=details
        else:
            evaluate=schedules.backtest_dates if 'dates' in options else schedules.backtest
            result=evaluate(db,**options)
        backtest_control.checkpoint()
    return result


class Jobs:
    def __init__(self):
        self.lock=RLock()
        self.runs={}
        self.closing=False

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
                result=calculate(run['mode'],run['options'],progress,configuration)
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
