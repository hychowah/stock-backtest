"""One application calculation capability with an immutable submitted choice.

Engine metadata never enters financial plans. Producer metadata describes only
new completed results; request defaults cannot establish old result provenance.
"""

from contextlib import contextmanager

from backtest.application import calculation_contract as calculation_contract
from backtest import calendar_requests as calendar_requests
from backtest.application.original_calculations import Original


class Selectable:
    calendar_version=None  # Legacy clients still see Original's calendar.

    def __init__(self,preparation):
        from backtest.application.candidate_calculations import Candidate
        self.preparation=preparation
        self.original=Original()
        self.closed=self.original.closed
        self.experimental=Candidate(preparation)
        self.ready=lambda:True
        self.original.ready=lambda:self.ready()

    def preflight(self,options,*,planned=None):
        """Validate the pinned engine's policy without changing financial settings."""
        engine=calculation_contract.engine_id(options)
        from backtest.application import strategy_requests
        strategy_requests.check_options(options)
        if planned is not None:
            strategy_requests.validate_recorded({key:value for key,value in options.items() if key!='engine'},planned)
        if engine=='experimental':
            from backtest.engines.numerical.policy import require_supported
            require_supported(options)
            if planned is not None:require_supported(planned.get('options',{}))
        return engine

    def status(self):
        from backtest.application.preparation import dependencies, PreparationError, DEFAULT_PROFILE
        profile=getattr(self.preparation,'profile',DEFAULT_PROFILE)
        if not isinstance(profile,str):profile=DEFAULT_PROFILE
        try:dependencies(profile)
        except PreparationError as error:return dict(state='unavailable',category=error.category)
        return self.experimental.status()

    def ready_for(self,options,*,advisory=False):
        if calculation_contract.engine_id(options)=='original':return self.ready()
        status=self.status()
        return status.get('state')=='current' or advisory and status.get('busy') is True

    def queue_engines(self):
        """Read readiness outside queue transactions. Keep waiting records intact."""
        return {'original','experimental'} if self.ready_for({'engine':'experimental'}) else {'original'}

    def capabilities(self):
        return dict(calendar=None,shared_views=['latest','january'],engines=[dict(id=key,label=label,calendar=1,operations=['custom','random'],
            status=self.status() if key=='experimental' else dict(state='current'))
            for key,label in calculation_contract.ENGINES.items()])

    def calculate(self,mode,options,progress,configuration,*,planned=None,admission='interactive',details=True):
        if self.closed.is_set():raise calculation_contract.Busy('The server is stopping. Restart it before running a backtest.')
        engine=self.preflight(options,planned=planned)
        financial={key:value for key,value in options.items() if key!='engine'}
        if engine=='experimental':
            if not self.ready_for(options,advisory=True):
                raise calculation_contract.Unavailable('Experimental preparation is unavailable. Use Prepare experimental engine in Manage backtest data. Original remains available.')
            result=self.experimental.calculate(mode,financial,progress,configuration,planned=planned,admission=admission,details=details)
        else:
            # Also waits for a retained uncertain child before parent access.
            with self.experimental.parent_operation(admission=admission):
                result=self.original.calculate(mode,financial,progress,configuration,planned=planned,admission=admission,details=details)
        result['producer']=dict(engine=engine,label=calculation_contract.ENGINES[engine])
        return result

    @contextmanager
    def parent_operation(self,cancelled=lambda:False):
        with self.experimental.parent_operation(cancelled=cancelled):yield

    def close(self):
        self.original.close();self.experimental.close()

    def retire(self):self.experimental.retire()

    def calculate_into(self,mode,options,destination,progress,configuration,*,planned=None,admission='interactive',**limits):
        self.preflight(options,planned=planned)
        if self.closed.is_set():raise calculation_contract.Busy('The server is stopping.')
        financial={key:value for key,value in options.items() if key!='engine'}
        with self.experimental.parent_operation(admission=admission):
            return self.original.calculate_into(mode,options,destination,progress,configuration,
                planned=planned,admission=admission,**limits)

    def preview(self,capture,roots):
        from backtest.application import strategy_requests
        strategy_requests.check_options({'strategy':capture})
        with self.experimental.parent_operation():
            return self.original.preview(capture,roots)
