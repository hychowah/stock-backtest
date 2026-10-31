"""One application calculation capability with an immutable submitted choice.

Engine metadata never enters financial plans. Producer metadata describes only
new completed results; request defaults cannot establish old result provenance.
"""
from contextlib import contextmanager

import backtest_jobs


class Selectable:
    calendar_version=None  # Legacy clients still see Original's calendar.

    def __init__(self,preparation):
        from candidate_calculations import Candidate
        self.preparation=preparation
        self.original=backtest_jobs.Calculations()
        self.closed=self.original.closed
        self.experimental=Candidate(preparation)
        self.ready=lambda:True
        self.original.ready=lambda:self.ready()

    def preflight(self,options,*,planned=None):
        """Validate the pinned engine's policy without changing financial settings."""
        engine=backtest_jobs.engine_id(options)
        if planned is not None and not isinstance(planned,dict):raise ValueError('Expected a recorded random plan.')
        if engine=='original':
            if 'calendar' in options or planned is not None and 'calendar' in planned:
                raise ValueError('Original supports the monthly frequency presets. Custom week/month calendars require New engine — experimental.')
            if planned is not None:
                if not isinstance(planned.get('options'),dict) or any(key not in planned for key in ('start','end','months','requested','seed')):
                    raise ValueError('Invalid recorded random plan.')
                submitted={'selection_order':'filter_first',**planned['options'],
                    **{key:planned[key] for key in ('start','end','months')},'trials':planned['requested'],'seed':planned['seed']}
                if any(key not in submitted or value!=submitted[key] for key,value in
                       {'selection_order':'filter_first',**options}.items() if key!='engine'):
                    raise ValueError('Submitted settings differ from the recorded random plan.')
        else:
            from numerical_policy import require_supported
            require_supported(options)
            if planned is not None:require_supported(planned.get('options',{}))
        return engine

    def status(self):
        from numerical_preparation import dependencies,PreparationError
        try:dependencies()
        except PreparationError as error:return dict(state='unavailable',category=error.category)
        return self.experimental.status()

    def ready_for(self,options,*,advisory=False):
        if backtest_jobs.engine_id(options)=='original':return self.ready()
        status=self.status()
        return status.get('state')=='current' or advisory and status.get('busy') is True

    def queue_engines(self):
        """Read readiness outside queue transactions. Keep waiting records intact."""
        return {'original','experimental'} if self.ready_for({'engine':'experimental'}) else {'original'}

    def capabilities(self):
        return dict(calendar=None,engines=[dict(id=key,label=label,calendar=1 if key=='experimental' else None,
            status=self.status() if key=='experimental' else dict(state='current'))
            for key,label in backtest_jobs.ENGINES.items()])

    def calculate(self,mode,options,progress,configuration,*,planned=None,admission='interactive',details=True):
        if self.closed.is_set():raise backtest_jobs.Busy('The server is stopping. Restart it before running a backtest.')
        engine=self.preflight(options,planned=planned)
        financial={key:value for key,value in options.items() if key!='engine'}
        if engine=='experimental':
            if not self.ready_for(options,advisory=True):
                raise backtest_jobs.Unavailable('Experimental preparation is unavailable. Use Prepare experimental engine in Manage backtest data. Original remains available.')
            result=self.experimental.calculate(mode,financial,progress,configuration,planned=planned,admission=admission,details=details)
        else:
            # Also waits for a retained uncertain child before parent access.
            with self.experimental.parent_operation(admission=admission):
                result=self.original.calculate(mode,financial,progress,configuration,planned=planned,admission=admission,details=details)
        result['producer']=dict(engine=engine,label=backtest_jobs.ENGINES[engine])
        return result

    @contextmanager
    def parent_operation(self,cancelled=lambda:False):
        with self.experimental.parent_operation(cancelled=cancelled):yield

    def close(self):
        self.original.close();self.experimental.close()

    def retire(self):self.experimental.retire()
