"""Original execution adapter; jobs and user records belong to callers.

Own financial admission, ordinary worker/database lifetime and full results.
Publish only after workers and connections close. Queue waiting repeats only
admission, never calculation. Optional numerical dependencies are not imported.
"""

from backtest.inputs import daily
from backtest import screening

from contextlib import contextmanager
from datetime import date
from backtest.runtime import backtest_control as backtest_control
from backtest.runtime import cache_access as cache_access
from backtest.engines.original import robustness as robustness
from backtest.engines.original import schedules as schedules
from backtest import calendar_requests as calendar_requests
from backtest.application.calculation_contract import Control, Busy, Unavailable


class Original(Control):
    calendar_version=1

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
        if 'strategy' in options:
            from backtest.application import strategy_requests
            strategy_requests.check_options(options)
            raise ValueError('Captured scalar strategies require the bounded result reader.')
        if admission not in ('interactive','queue'):raise ValueError('Invalid calculation admission policy.')
        with self.lock:
            if self.closed.is_set():raise Busy('The server is stopping. Restart it before running a backtest.')
        with self._financial(admission,progress):
            ready=self.ready()
            self._checkpoint()  # Stop takes precedence over stale deferral.
            if not ready:raise Unavailable('Candidate preparation is unavailable. Rebuild from the data panel.')
            db=daily.connect()
            try:
                db.execute('PRAGMA cache_size=-131072')
                if mode=='random':
                    sessions=[date.fromisoformat(row[0]) for row in db.execute('SELECT day FROM sessions ORDER BY day')]
                    if planned is None:
                        planned=calendar_requests.plan(sessions,options,checkpoint=self._checkpoint) if 'calendar' in options else robustness.plan(db,**options)
                    else:
                        calendar_requests.validate_submitted(options,planned)
                        planned=calendar_requests.validate_plan(sessions,planned,checkpoint=self._checkpoint)
                    screening.validate_selection(**planned['options'])
                    if configuration:configuration(planned)
                    captured=[]
                    result=robustness.run(db,planned,progress=progress,
                        capture=(lambda number,trial:captured.append(trial)) if details else None)
                    if details:result['trial_results']=captured
                else:
                    evaluate=schedules.backtest_calendar if 'calendar' in options else schedules.backtest_dates if 'dates' in options else schedules.backtest
                    result=evaluate(db,**options)
                backtest_control.checkpoint()
            finally:db.close()
        return result

    def preflight(self, options, *, planned=None):
        from backtest.application import strategy_requests
        if isinstance(options,dict) and 'strategy' in options and options.get('engine','original')!='original':
            from backtest.variables.definitions import FormulaError
            raise FormulaError('UNSUPPORTED_CAPABILITY','/engine',
                'Original cannot execute a strategy pinned to another engine.')
        strategy_requests.check_options(options)
        if planned is not None:strategy_requests.validate_recorded(options,planned)
        return 'original'

    def ready_for(self, options, *, advisory=False):
        self.preflight(options)
        return self.ready()

    def preview(self, capture, roots, *, admission='interactive', engine='original'):
        """Explicit Original reference samples under ordinary input lifetime."""
        from backtest.application import scalar_execution, strategy_requests
        from backtest.inputs import sqlite_observations
        options={'strategy':capture}
        strategy_requests.preview_engine(engine)
        strategy_requests.check_options(options)
        plans=scalar_execution.plan_preview(strategy_requests.from_wire(capture),roots)
        with self._financial(admission,None):
            if not self.ready():raise Unavailable('Prepared inputs are unavailable. Rebuild from the data panel.')
            db=daily.connect()
            try:
                accepted=daily.fingerprint()
                def fresh():
                    self._checkpoint()
                    if daily.fingerprint()!=accepted:raise ValueError('Scalar inputs changed during execution.')
                with sqlite_observations.prepared_view(db,fresh,checkpoint=self._checkpoint) as view:
                    value=scalar_execution.evaluate_preview(plans,roots,view,checkpoint=self._checkpoint)
                    fresh()
            finally:db.close()
        return dict(value,producer=dict(engine='original',label='Original reference sample preview'))

    def coverage(self, capture=None, scope=None, *, admission='interactive'):
        """Discover or inspect recorded scopes under ordinary financial ownership."""
        from backtest.application import variable_coverage, strategy_requests
        from backtest.inputs import research, sqlite_observations
        if capture is not None:
            strategy_requests.check_options({'strategy':capture})
            capture=strategy_requests.from_wire(capture)
        with self._financial(admission,None):
            if not self.ready():raise Unavailable('Prepared inputs are unavailable. Rebuild from the data panel.')
            db=daily.connect();source=None
            try:
                accepted=daily.fingerprint()
                def fresh():
                    self._checkpoint()
                    if daily.fingerprint()!=accepted:raise ValueError('Scalar inputs changed during inspection.')
                source=research.connect()
                with sqlite_observations.prepared_view(db,fresh,checkpoint=self._checkpoint) as view:
                    value=(variable_coverage.scopes(source,view) if capture is None else
                           variable_coverage.inspect(capture,scope,source,view,checkpoint=self._checkpoint))
                    fresh()
            finally:
                if source is not None:source.close()
                db.close()
        return dict(value,producer=dict(engine='original',label='Original reference coverage'))

    def calculate_into(self, mode, options, destination, progress, configuration, *, planned=None,
                       admission='interactive', max_bytes=256*1024**2, piece_bytes=1024*1024, record_bytes=8*1024*1024):
        """Stream scalar codec 2; publish only after the ordinary financial owner closes."""
        import hashlib
        from backtest import scalar_result_evidence
        from backtest.inputs import research, sqlite_observations
        from backtest.application import strategy_requests, scalar_runs
        self.preflight(options,planned=planned)
        options=strategy_requests.execution_options(mode,options,planned=planned,checkpoint=self._checkpoint)
        if admission not in ('interactive','queue'):raise ValueError('Invalid calculation admission policy.')
        if not 0<max_bytes<=256*1024**2:raise ValueError('Invalid scalar evidence byte ceiling.')
        financial={key:value for key,value in options.items() if key!='engine'}
        trials=0 if mode=='latest' else (planned['requested'] if planned is not None else options.get('trials',24)) if mode=='random' else 1
        writer=None
        with self._financial(admission,progress):
            if not self.ready():raise Unavailable('Prepared inputs are unavailable. Rebuild from the data panel.')
            db=daily.connect();source=None
            try:
                accepted=daily.fingerprint()
                def fresh():
                    self._checkpoint()
                    if daily.fingerprint()!=accepted:raise ValueError('Scalar inputs changed during execution.')
                if mode in ('latest','january'):source=research.connect()
                with sqlite_observations.prepared_view(db,fresh,checkpoint=self._checkpoint) as view:
                    metadata=dict(mode=mode,options=options,configuration=planned,input=view.identity,
                        projection=view.projection,producer=dict(engine='original',label='Original'))
                    def configured(value):
                        metadata['configuration']=value
                        if configuration:configuration(value)
                    # Random plan must be known before the immutable header.
                    if mode=='random' and planned is None:
                        sessions=[date.fromisoformat(row[0]) for row in db.execute('SELECT day FROM sessions ORDER BY day')]
                        planned=calendar_requests.plan(sessions,financial,checkpoint=self._checkpoint)
                        metadata['configuration']=planned
                    writer=scalar_result_evidence.Writer(destination,trials=trials,metadata=metadata,max_bytes=max_bytes,
                        piece_bytes=piece_bytes,record_bytes=record_bytes,checkpoint=self._checkpoint)
                    summary=scalar_runs.execute(db,source,mode,financial,writer,view,configured,planned=planned,
                        progress=progress,checkpoint=self._checkpoint)
                    view.validate();fresh()
            finally:
                if source is not None:source.close()
                db.close()
        # Sealing runs after financial handles and ownership have closed.
        manifest=writer.finish(summary)
        destination.flush();destination.seek(0)
        digest=hashlib.sha256();size=0
        for part in iter(lambda:destination.read(65536),b''):
            self._checkpoint();digest.update(part);size+=len(part)
        return dict(manifest=manifest,transfer=dict(bytes=size,sha256=digest.hexdigest()))
