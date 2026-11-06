"""Original execution adapter; jobs and user records belong to callers.

Own financial admission, ordinary worker/database lifetime and full results.
Publish only after workers and connections close. Queue waiting repeats only
admission, never calculation. Optional numerical dependencies are not imported.
"""

from backtest.inputs import daily, facts
from backtest import screening

from contextlib import contextmanager
from backtest.runtime import backtest_control as backtest_control
from backtest.runtime import cache_access as cache_access
from backtest.runtime import diagnostics
from backtest.engines.original import robustness as robustness
from backtest.engines.original import schedules as schedules
from backtest import calendar_requests as calendar_requests
from backtest.application.calculation_contract import Control, Busy, Unavailable, ENGINES, engine_id


class Original(Control):
    """The calculation owner that the website runs.

    `engine` names the only engine this owner runs. A request or record may
    name another engine; preflight refuses it and never runs it as Original.
    Every new result records this producer.
    """
    engine='original'
    calendar_version=1

    @contextmanager
    def _financial(self,admission,progress):
        # Queue waiting repeats admission only, never an execution that began.
        waiting=False
        with diagnostics.stage('admission'):
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

    @diagnostics.operation('backtest.run')
    def calculate(self,mode,options,progress,configuration,*,planned=None,
                  admission='interactive',details=True):
        """Calculate once, with complete random holdings unless summary is requested.

        Interactive admission has the ordinary bounded wait. Queue admission
        waits cancellably through contention. Neither policy retries an engine
        error. Configuration is published before random work, under ownership.
        """
        diagnostics.note(mode=mode,admission=admission,strategy=False)
        self.preflight(options,planned=planned)
        if 'strategy' in options:
            raise ValueError('Captured scalar strategies require the bounded result reader.')
        options={key:value for key,value in options.items() if key!='engine'}
        if admission not in ('interactive','queue'):raise ValueError('Invalid calculation admission policy.')
        with self.lock:
            if self.closed.is_set():raise Busy('The server is stopping. Restart it before running a backtest.')
        with self._financial(admission,progress):
            ready=self.ready()
            self._checkpoint()  # Stop takes precedence over stale deferral.
            if not ready:raise Unavailable('Prepared inputs are unavailable. Rebuild from the data panel.')
            db=daily.connect()
            try:
                db.execute('PRAGMA cache_size=-131072')
                if mode=='random':
                    with diagnostics.stage('plan'):
                        sessions=facts.sessions(db)
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
                    diagnostics.note(trials=len(result['trials']),periods=sum(row['periods'] for row in result['trials']),
                                     execution=result['execution'])
                else:
                    evaluate=schedules.backtest_calendar if 'calendar' in options else schedules.backtest_dates if 'dates' in options else schedules.backtest
                    result=evaluate(db,**options)
                    diagnostics.note(periods=len(result['periods']))
                # Note the pool only after the run has validated and used it.
                diagnostics.note(pool=options.get('pool','legacy'))
                backtest_control.checkpoint()
            finally:db.close()
        result['producer']=dict(engine=self.engine,label=ENGINES[self.engine])
        return result

    def preflight(self, options, *, planned=None):
        """Admit new work before readiness, inputs or planning.

        A request or record that names another engine fails with
        UNSUPPORTED_CAPABILITY at /engine. Then captured strategies and a
        recorded plan are checked. Reading stored records never calls this.
        """
        from backtest.application import strategy_requests
        engine=engine_id(options)
        if engine!=self.engine:
            from backtest.variables.definitions import FormulaError
            raise FormulaError('UNSUPPORTED_CAPABILITY','/engine',
                'The experimental engine is not available. Choose Original to run this test.')
        strategy_requests.check_options(options)
        if planned is not None:strategy_requests.validate_recorded(options,planned)
        return self.engine

    def capabilities(self):
        """Describe what this server runs, for GET /api/backtest-capabilities.

        The engines list names only the engines this server runs, with the
        calendar version each supports. Engine labels stay with the browser.
        """
        return dict(engines=[dict(id=self.engine,calendar=self.calendar_version)])

    def preview(self, capture, roots, *, admission='interactive', engine='original'):
        """Explain explicit Original samples under ordinary input lifetime."""
        from backtest.application import scalar_execution, strategy_requests
        from backtest.inputs import fact_view, operation_inputs
        strategy_requests.preview_engine(engine)
        # check_options restores the capture once (one compile); the preview reuses its checked program.
        projection=scalar_execution.check_preview(strategy_requests.check_options({'strategy':capture}),roots)
        with self._financial(admission,None):
            if not self.ready():raise Unavailable('Prepared inputs are unavailable. Rebuild from the data panel.')
            with operation_inputs.held(checkpoint=self._checkpoint) as inputs:
                with fact_view.View(inputs.db,inputs.require_unchanged,self._checkpoint) as view:
                    value=scalar_execution.evaluate_preview(projection,roots,view,checkpoint=self._checkpoint)
        return dict(value,producer=dict(engine='original',label='Original sample preview'))

    def coverage(self, capture=None, scope=None, *, admission='interactive'):
        """Discover or inspect recorded scopes under ordinary financial ownership."""
        from backtest.application import variable_coverage, strategy_requests
        from backtest.inputs import fact_view, operation_inputs
        # check_options restores the capture once (one compile); inspect reuses its checked program.
        checked=None if capture is None else strategy_requests.check_options({'strategy':capture})
        with self._financial(admission,None):
            if not self.ready():raise Unavailable('Prepared inputs are unavailable. Rebuild from the data panel.')
            with operation_inputs.held(checkpoint=self._checkpoint) as inputs:
                with fact_view.View(inputs.db,inputs.require_unchanged,self._checkpoint) as view:
                    value=(variable_coverage.scopes(inputs.db,view) if checked is None else
                           variable_coverage.inspect(checked,scope,inputs.db,view,checkpoint=self._checkpoint))
        return dict(value,producer=dict(engine='original',label='Original coverage'))

    @diagnostics.operation('backtest.run')
    def calculate_into(self, mode, options, destination, progress, configuration, *, planned=None,
                       admission='interactive', max_bytes=256*1024**2, piece_bytes=1024*1024, record_bytes=8*1024*1024):
        """Stream scalar codec 2; publish only after the ordinary financial owner closes."""
        diagnostics.note(mode=mode,admission=admission,strategy=True)
        import hashlib
        from backtest import scalar_result_evidence
        from backtest.inputs import fact_view, operation_inputs
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
            with operation_inputs.held(checkpoint=self._checkpoint) as inputs:
                db=inputs.db
                # Formulas and books read the typed facts through the daily connection's attached research.
                with fact_view.View(db,inputs.require_unchanged,self._checkpoint) as view:
                    metadata=dict(mode=mode,options=options,configuration=planned,input=view.identity,
                        projection=view.projection,producer=dict(engine='original',label='Original'))
                    def configured(value):
                        metadata['configuration']=value
                        if configuration:configuration(value)
                    # Random plan must be known before the immutable header.
                    if mode=='random' and planned is None:
                        with diagnostics.stage('plan'):
                            sessions=facts.sessions(db)
                            planned=calendar_requests.plan(sessions,financial,checkpoint=self._checkpoint)
                        metadata['configuration']=planned
                    writer=scalar_result_evidence.Writer(destination,trials=trials,metadata=metadata,max_bytes=max_bytes,
                        piece_bytes=piece_bytes,record_bytes=record_bytes,checkpoint=self._checkpoint)
                    summary=scalar_runs.execute(db,mode,financial,writer,view,configured,planned=planned,
                        progress=progress,checkpoint=self._checkpoint)
                    view.validate()
        # Sealing runs after financial handles and ownership have closed.
        with diagnostics.stage('seal'):
            manifest=writer.finish(summary)
            destination.flush();destination.seek(0)
            digest=hashlib.sha256();size=0
            for part in iter(lambda:destination.read(65536),b''):
                self._checkpoint();digest.update(part);size+=len(part)
        diagnostics.note(evidence_bytes=size)
        return dict(manifest=manifest,transfer=dict(bytes=size,sha256=digest.hexdigest()))
