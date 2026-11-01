from backtest import calendar as schedule_calendar, portfolio_results, screening
from backtest.runtime import backtest_control

from backtest import screening
"""Offline complete-book portfolio diagnostic. No runtime discovery or routing.

The caller owns source before import/cache access, validates and holds its input
attachment, and closes the borrowed provider before that attachment. This adapter
owns only its private SQL workspace. It never opens an application database.
"""
from datetime import date
import math
import sqlite3
import time

from backtest import calendar_requests as numerical_calendar
from backtest import portfolio_results as portfolio_results
from backtest.engines.numerical.workspace import RequestWorkspace, stage_book
from backtest.engines.numerical.matrix import retained_size


class NumericalPortfolio(RequestWorkspace):
    """Compose an explicitly supplied complete-book provider with existing SQL.

    inputs can be an already validated AttachedInputs or fictional NumericInputs.
    provider is the accepted complete-book evaluator for exactly those inputs.
    Work stays bounded to one complete candidate book at a time. No factors are
    ranked before period-specific entry/exit eligibility has been applied.
    """
    def __init__(self, inputs, provider, *, result_workspace_bytes=None):
        self.inputs, self.provider = inputs, provider
        self.result_workspace_bytes = result_workspace_bytes
        self.peak_result_graph_bytes = 0
        super().__init__(inputs, result_workspace_bytes=result_workspace_bytes)

    def _validate_inputs(self):
        super()._validate_inputs()
        if self.provider.inputs is not self.inputs:
            raise ValueError('Complete-book provider belongs to different inputs.')

    def backtest(self, *, start, end, months=12, **options):
        self._validate_inputs()
        configuration = schedule_calendar.legacy_configuration(
            dict(start=start, end=end, months=months))
        periods = self._calendar().fixed(configuration, checkpoint=backtest_control.checkpoint)
        return self.backtest_periods(periods, months=months, **options)

    def backtest_dates(self, *, dates, start, end, months=12, **options):
        self._validate_inputs()
        schedule_calendar.legacy_configuration(dict(start=start, end=end, months=months))
        first, final, periods = self._calendar().explicit(
            dates, start, end, checkpoint=backtest_control.checkpoint)
        return self.backtest_periods(periods, months=months, common_start=first, **options)

    def backtest_calendar(self, **request):
        pairs,first,options,metadata=numerical_calendar.periods(
            self._calendar().sessions,request,checkpoint=backtest_control.checkpoint)
        return self._evaluate_periods(pairs,metadata,common_start=first,**options)

    def backtest_periods(self, periods, *, months=12, common_start=None, **options):
        return self._evaluate_periods(periods,dict(months=months),common_start=common_start,**options)

    def backtest_dates_into(self, emit_period, *, dates, start, end, months=12, **options):
        """Emit detached complete periods synchronously; return scalar metadata.

        No previous period is retained. The caller owns output publication and
        lifetime. This explicit operation does not alter eager admission.
        """
        if not callable(emit_period):raise ValueError('Choose a callable period sink.')
        self._validate_inputs()
        schedule_calendar.legacy_configuration(dict(start=start,end=end,months=months))
        first,_,periods = self._calendar().explicit(
            dates,start,end,checkpoint=backtest_control.checkpoint)
        return self._reduce_periods(periods,dict(months=months),emit_period,common_start=first,**options)

    def backtest_calendar_into(self, emit_period, **request):
        if not callable(emit_period):raise ValueError('Choose a callable period sink.')
        self._validate_inputs()
        pairs,first,options,metadata=numerical_calendar.periods(
            self._calendar().sessions,request,checkpoint=backtest_control.checkpoint)
        return self._reduce_periods(pairs,metadata,emit_period,common_start=first,**options)

    def _evaluate_periods(self, periods, metadata, *, common_start=None, **options):
        return self._reduce_periods(periods,metadata,None,common_start=common_start,**options)

    def _reduce_periods(self, periods, metadata, emit_period, /, *, common_start=None, **options):
        started = time.perf_counter()
        periods = portfolio_results.validate_periods(periods, common_start)
        self._validate_inputs()
        # This unchanged selector validates options before any provider work or
        # SQL writes, including unknown keyword arguments and strict filters.
        self.validate_selection(options)
        if emit_period is None:self.admit_eager_result(len(periods),options)
        retained = 0
        self.provider.begin(dict(options=options))
        pool = options.get('pool', 'legacy')

        def select_period(entry, exit_day):
            nonlocal retained
            backtest_control.checkpoint()
            requested = (str(entry), str(exit_day), pool)
            response = self.provider.evaluate([requested])
            if not isinstance(response, list) or len(response) != 1:
                raise ValueError('Complete-book provider changed the result count.')
            book = response[0]
            self._check_book(book, requested)
            try:
                period_id = stage_book(self.db, book, pool)
            except (sqlite3.Error, TypeError, ValueError, KeyError) as error:
                raise ValueError('Complete-book SQL staging contract differs.') from error
            backtest_control.checkpoint()
            holdings = screening.select(self.db, period=(period_id, period_id), **options)
            selected = dict(entry=requested[0], exit=requested[1], holdings=holdings, spy=book['period'][2])
            retained = (retained if emit_period is None else 0)+retained_size(selected)+4096
            self.peak_result_graph_bytes = max(self.peak_result_graph_bytes,retained)
            if self.result_workspace_bytes is not None and retained > self.result_workspace_bytes:
                raise ValueError('Complete result exceeds the runtime result workspace bound.')
            return selected

        with self.db:
            if emit_period is None:
                result = portfolio_results.evaluate(periods, select_period, common_start=common_start,
                    checkpoint=backtest_control.checkpoint)
            else:
                result = portfolio_results.evaluate_into(periods, select_period, emit_period,
                    common_start=common_start,checkpoint=backtest_control.checkpoint)
        result.update(metadata, options=options, seconds=time.perf_counter()-started)
        size = retained_size(result)
        self.peak_result_graph_bytes = max(self.peak_result_graph_bytes,size)
        if self.result_workspace_bytes is not None and size > self.result_workspace_bytes:
            raise ValueError('Complete result exceeds the runtime result workspace bound.')
        return dict(contract_version=portfolio_results.CONTRACT_VERSION, result=result)

    def _check_book(self, book, requested):
        if (not isinstance(book, dict) or not {'entry', 'exit', 'pool', 'period',
                'snapshots', 'metrics', 'filters'}.issubset(book)
                or (book['entry'], book['exit'], book['pool']) != requested
                or not isinstance(book['period'], (tuple, list)) or len(book['period']) != 6
                or tuple(book['period'][:2]) != requested[:2]):
            raise ValueError('Complete-book provider changed a requested book identity.')
        if any(not isinstance(book[key], list) for key in ('snapshots', 'metrics', 'filters')):
            raise ValueError('Complete-book provider returned malformed rows.')
        if (any(type(value) not in (int, float) or not math.isfinite(value)
                for value in book['period'][2:4]) or book['period'][2] < -1
                or any(type(value) is not int or value < 0 for value in book['period'][4:])):
            raise ValueError('Complete-book provider returned malformed period values.')
        bound = self.provider.limits.get('max_candidate_rows', 250000)
        if len(book['snapshots']) > bound:
            raise ValueError('Complete book exceeds the existing candidate row bound.')
        for key, width in (('snapshots', 13), ('metrics', 4), ('filters', 3)):
            if any(not isinstance(row, (tuple, list)) or len(row) != width for row in book[key]):
                raise ValueError('Complete-book provider changed a row schema.')
        symbols = {row[0] for row in book['snapshots']}
        if len(symbols) != len(book['snapshots']):
            raise ValueError('Complete-book provider returned duplicate holdings.')
        for row in book['snapshots']:
            if (not isinstance(row[0], str) or not row[0]
                    or row[1] is not None and (type(row[1]) is not int or row[1] < 1)
                    or any(type(value) not in (int, float) or not math.isfinite(value) for value in row[5:12])
                    or row[11] < -1 or row[12] not in portfolio_results.STATUSES):
                raise ValueError('Complete-book provider returned malformed snapshot values.')
            try:
                fiscal, buy, sell = (date.fromisoformat(value) for value in row[2:5])
                entry, exit_day = (date.fromisoformat(value) for value in requested[:2])
            except (ValueError, TypeError):
                raise ValueError('Complete-book provider returned malformed snapshot dates.') from None
            if (tuple(map(str, (fiscal, buy, sell))) != tuple(row[2:5])
                    or not entry <= buy < exit_day or not buy <= sell <= exit_day):
                raise ValueError('Complete-book provider changed actual entry/exit eligibility.')
        if any(row[0] not in symbols for key in ('metrics', 'filters') for row in book[key]):
            raise ValueError('Complete-book provider returned orphan financial rows.')
        for key in ('metrics', 'filters'):
            if any(not isinstance(row[1], str) or
                   any(type(value) not in (int, float) or not math.isfinite(value) for value in row[2:])
                   for row in book[key]):
                raise ValueError('Complete-book provider returned malformed financial values.')

    def close(self):
        if not self.closed:
            self.db.close()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()



def compare_results(reference, observed):
    """Inspect complete ordered payloads; exclude only root runtime seconds.

    Structural/category failures and numeric differences have separate paths.
    Tolerance is the existing fixed 1e-12 relative/absolute rule. Arrays are never
    sorted, fields never projected, and integer identities remain exact.
    """
    structural, numeric = [], []
    maximum_absolute = maximum_relative = 0.

    def walk(a, b, path):
        nonlocal maximum_absolute, maximum_relative
        if type(a) is not type(b):
            structural.append(dict(path=path, reason='type'))
        elif type(a) is float:
            if not math.isfinite(a) or not math.isfinite(b):
                numeric.append(dict(path=path, reason='nonfinite'))
                return
            absolute = abs(a-b)
            relative = absolute/max(abs(a), abs(b)) if a or b else 0.
            maximum_absolute, maximum_relative = max(maximum_absolute, absolute), max(maximum_relative, relative)
            if not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12):
                numeric.append(dict(path=path, absolute=absolute, relative=relative))
        elif isinstance(a, dict):
            left, right = set(a), set(b)
            if path == '$': left.discard('seconds'); right.discard('seconds')
            if left != right: structural.append(dict(path=path, reason='keys'))
            for key in a:
                if key in left & right: walk(a[key], b[key], path+'.'+key)
        elif isinstance(a, list):
            if len(a) != len(b): structural.append(dict(path=path, reason='length'))
            for index, (x, y) in enumerate(zip(a, b)):
                walk(x, y, path+'['+str(index)+']')
        elif a != b:
            structural.append(dict(path=path, reason='value'))

    walk(reference, observed, '$')
    return dict(exact=not structural and not numeric, structural=structural, numeric=numeric,
                maximum_absolute=maximum_absolute, maximum_relative=maximum_relative)
