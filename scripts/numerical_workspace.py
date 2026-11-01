
# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))

from backtest import screening
"""Compiler-free request workspace and private complete-book SQL staging."""
from datetime import date
import sqlite3

from numerical_matrix import retained_size
from numerical_policy import require_supported


class RequestWorkspace:
    """Own SQL request validation without a numerical provider or compilation.

    The caller owns the input attachment and closes this workspace first.
    Planning, calendar validation and selection use the same SQL as portfolios.
    """
    def __init__(self, inputs, *, result_workspace_bytes=None):
        self.result_workspace_bytes = result_workspace_bytes
        self.peak_result_graph_bytes = 0
        self.inputs, self.s, self.closed = inputs, inputs.s, False
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        try:
            self._validate_inputs()
            self.db.executescript(self.s.SCHEMA)
            self.db.executemany('INSERT INTO companies VALUES(?,?,?,?)', inputs.companies)
            self.db.executemany('INSERT INTO sessions VALUES(?,?)', inputs.sessions.items())
            self.db.commit()
        except BaseException:
            self.close()
            raise

    def _validate_inputs(self):
        if self.closed or self.inputs.closed:
            raise ValueError('Numerical workspace or input attachment is closed.')
        validate = getattr(self.inputs, 'validate', None)
        if validate is not None: validate()

    def _calendar(self):
        return self.s.schedule_calendar.SessionCalendar(
            [date.fromisoformat(day) for day in sorted(self.inputs.sessions)])

    def validate_selection(self, options):
        try:
            screening.validate_selection(**options)
        except TypeError as error:
            raise ValueError('Unknown screening option.') from error
        require_supported(options)

    def admit_eager_result(self,period_count,options):
        """Keep the existing conservative eager estimate before provider work."""
        if self.result_workspace_bytes is not None:
            count=min(len(self.inputs.symbols),options.get('rank_to',50)-options.get('rank_from',1)+1)
            if period_count*(16384+4096*count)>self.result_workspace_bytes:
                raise ValueError('Complete result exceeds the runtime result workspace bound.')

    def result_collector(self,period_count,options):
        """Collect incremental trial evidence within the existing eager budget.

        The caller chooses eager retention. Streaming evaluation does not use
        this collector. Its accounting includes cumulative detached periods and
        the final graph; this does not raise or replace the owner's byte budget.
        """
        self.admit_eager_result(period_count,options)
        return _ResultCollector(self)

    def close(self):
        if not self.closed:
            self.db.close()
            self.closed = True

DERIVED = ('period_pools', 'filter_values', 'screening_metrics', 'snapshots',
           'latest_snapshots', 'baseline_prices', 'baseline_periods', 'periods')


def stage_book(db, book, pool, *, ranking_metric=None, staged_rows=None):
    """Replace one complete book. Optionally stage only the requested pair.

    This retains the historical runner's staging behavior. The caller owns the
    private database and its transaction. No application cache is discovered.
    """
    for table in DERIVED:
        db.execute('DELETE FROM ' + table)
    db.execute('INSERT INTO periods VALUES(?,?,?,?,?,?,?)', (1, *book['period']))
    snapshots = db.executemany('INSERT INTO snapshots VALUES(' + ','.join('?' * 15) + ')',
                               ((pool, 1, *row) for row in book['snapshots']))
    metrics = db.executemany('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',
        (('historical', pool, 1, symbol, metric, multiple, score)
         for symbol, metric, multiple, score in book['metrics']
         if ranking_metric is None or metric == ranking_metric))
    filters = db.executemany('INSERT INTO filter_values VALUES(?,?,?,?,?,?)',
                             (('historical', pool, 1, *row) for row in book['filters']))
    if staged_rows is not None:
        for name, cursor in (('snapshots', snapshots), ('screening_metrics', metrics),
                             ('filter_values', filters)):
            staged_rows[name] += cursor.rowcount
    return 1


class _ResultCollector:
    def __init__(self,portfolio):
        self.portfolio=portfolio
        self.periods=[]
        self.retained=0

    def _check(self,size):
        portfolio=self.portfolio
        portfolio.peak_result_graph_bytes=max(portfolio.peak_result_graph_bytes,size)
        if portfolio.result_workspace_bytes is not None and size>portfolio.result_workspace_bytes:
            raise ValueError('Complete result exceeds the runtime result workspace bound.')

    def period(self,period):
        self.retained+=retained_size(period)+4096
        self._check(self.retained)
        self.periods.append(period)

    def finish(self,summary):
        result=dict(periods=self.periods,**summary)
        self._check(retained_size(result))
        return result

