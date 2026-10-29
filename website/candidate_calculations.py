"""Candidate lifetime, hidden behind the shared application calculation entry."""
from contextlib import contextmanager
from threading import Lock
import time

import backtest_control
import backtest_jobs
import cache_access
from numerical_runtime import ClosureError


class Candidate(backtest_jobs.Calculations):
    """Serialize execution and parent operations; retain uncertain child owners.

    Callers never prehold financial ownership. Status is advisory; the child
    checks preparation freshness before result or checkpoint reuse.
    """
    def __init__(self, preparation):
        super().__init__()
        self.preparation = preparation
        self.runtime = None
        self.operation = Lock()
        self.ready = lambda: self.status().get('state') == 'current'

    @contextmanager
    def _operation(self, admission='interactive', cancelled=lambda: False):
        deadline = time.monotonic() + 30
        while True:
            self._checkpoint()
            if cancelled(): raise backtest_control.Cancelled()
            if self.operation.acquire(timeout=.05): break
            if admission != 'queue' and time.monotonic() >= deadline:
                raise cache_access.Contention('Another candidate operation is active. Retry after it finishes.')
        try:
            self._checkpoint()
            yield
        finally: self.operation.release()

    def retire(self):
        """After application joins, prove retirement before source release."""
        with self.operation: self._retire()

    def _retire(self):
        if self.runtime is not None:
            while True:
                try:
                    self.runtime.close()
                    break
                except ClosureError: time.sleep(.25)
            self.runtime = None

    @contextmanager
    def parent_operation(self, cancelled=lambda: False):
        """Start after child closure; remain exclusive through parent DB closure."""
        with self._operation(cancelled=cancelled):
            self._retire()
            yield

    def status(self):
        if not self.operation.acquire(blocking=False):
            return dict(state='unavailable', busy=True, category='preparation failed')
        try:
            if self.runtime is None: return self.preparation.status()
            if self.runtime.state != 'ready':
                return dict(state='unavailable', category='closure unconfirmed')
            try: return self.runtime.inspect()
            except Exception:
                return dict(state='unavailable', category='preparation failed')
        finally: self.operation.release()

    calendar_version=1

    def calculate(self, mode, options, progress, configuration, *, planned=None,
                  admission='interactive', details=True):
        if admission not in ('interactive','queue'): raise ValueError('Invalid calculation admission policy.')
        with self._operation(admission):
            try:
                waiting = False
                deadline = time.monotonic() + 30
                while True:
                    self._checkpoint()
                    if self.runtime is not None and self.runtime.state != 'ready': self._retire()
                    if self.runtime is None:
                        status = self.preparation.status()
                        if status.get('state') != 'current' and not status.get('busy'):
                            raise backtest_jobs.Unavailable('Candidate preparation is unavailable. Rebuild from the data panel.')
                        self.runtime = self.preparation._runtime()
                        self.runtime.configuration['preparation_status'] = True
                        try: self.runtime.start(cancelled=self.closed.is_set)
                        except cache_access.Contention:
                            self._retire()
                            if admission != 'queue' and time.monotonic() >= deadline: raise
                            if not waiting and progress:
                                progress(dict(type='waiting',message='Waiting for another backtest or data operation.'))
                            waiting = True
                            self.closed.wait(.1)
                            continue
                    break
                if waiting and progress: progress(None)
                result = self.runtime.calculate(mode, options, progress, configuration,
                    planned=planned, cancelled=self.closed.is_set)
                if not details: result.pop('trial_results', None)
                self._checkpoint()
                return result
            except ClosureError as error:
                self._retire()
                # A runtime cannot publish its primary outcome before proof.
                # Once retirement succeeds, restore that outcome for jobs/queue.
                if error.primary_error is not None: raise error.primary_error
                raise
            except BaseException:
                self._retire()
                raise
