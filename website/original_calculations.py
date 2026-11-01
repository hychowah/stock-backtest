
# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))

from backtest import screening
"""Original execution adapter; jobs and user records belong to callers.

Own financial admission, ordinary worker/database lifetime and full results.
Publish only after workers and connections close. Queue waiting repeats only
admission, never calculation. Optional numerical dependencies are not imported.
"""
from contextlib import contextmanager
from datetime import date
import backtest_control
import cache_access
import robustness
import schedules
from backtest import calendar_requests as calendar_requests
from calculation_contract import Control, Busy, Unavailable


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
