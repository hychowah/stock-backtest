"""Multi-date lazy temporal joins and source-derived factors in Polars.

The shared policy owns every financial formula and scalar control decision.
This executor owns full report/price histories and lowers that same policy tree
to column expressions. It never calls the old per-book lookup experiment.
"""
from pathlib import Path
import os
import sys
import time

import numpy as np

from bench_candidates import PythonExecutor
from backtest.financial import rules
from bench_candidates_analytical import (
    begin_stats, matrix_columns, polars_expression, price_columns, price_queries,
    report_columns, report_queries, stage_stats,
)


SOURCE_FILES = (Path(__file__).with_name('bench_candidates.py'),
                Path(__file__).with_name('bench_candidates_analytical.py'))


class Executor(PythonExecutor):
    """Borrow immutable buffers and execute bounded multi-date lazy plans."""

    def __init__(self, inputs, policy=None, limits=None):
        super().__init__(inputs, policy, limits)
        began = time.perf_counter()
        self._inputs = inputs
        self._policy = policy or inputs.policy
        self._limits = dict(limits or {})
        self._closed = False
        threads = self._limits.get('threads', 4)
        if type(threads) is not int or not 1 <= threads <= 4:
            raise ValueError('Analytical thread count must be an integer from one to four.')
        if 'polars' not in sys.modules:
            os.environ['POLARS_MAX_THREADS'] = str(threads)
        import polars as pl
        if pl.thread_pool_size() > threads:
            raise RuntimeError('The existing Polars pool exceeds the declared thread limit.')
        self._pl = pl
        self._max_rows = self._limits.get('max_query_rows', 1_000_000)
        if type(self._max_rows) is not int or self._max_rows < 1:
            raise ValueError('Analytical query row limit must be positive.')
        self._reports = {}
        for pool in ('cached', 'legacy'):
            # Equal availability dates choose the last source report. Explicit
            # source position prevents an analytical engine from choosing ties.
            self._reports[pool] = (
                pl.DataFrame(report_columns(inputs, pool)).sort('position')
                .unique(subset=['sid', 'known'], keep='last', maintain_order=True)
                .sort(['sid', 'known'])
            )
        self._price_views = [price_columns(inputs, column) for column in (0, 1)]
        # Sparse input buffers are already ordered by symbol and day. Filtering
        # preserves that order. ASOF checks are disabled only because a grouped
        # history is not globally ordered by its day column.
        self._prices = [pl.DataFrame(view).rename({'day': 'actual'}) for view in self._price_views]
        environment = {name: pl.col(name) for name in self._policy.input_names}
        self._numeric_literals = {}
        self._numeric_expressions = [
            polars_expression(self._policy.expanded(name), environment, pl,
                              self._numeric_literals).alias(name)
            for name in self._policy.output_names
        ]
        # Numeric simplification can reassociate a nested float expression.
        # Keep relational optimizations while preserving the policy's tree.
        self._numeric_optimizations = pl.QueryOptFlags(simplify_expression=False)
        self._setup_stats = stage_stats('polars',
            versions=dict(polars=pl.__version__, numpy=np.__version__),
            load_seconds=time.perf_counter()-began,
            threads=pl.thread_pool_size(),
            expression_simplification=False,
            full_length_constant_columns=True, numeric_padding_rows=0,
            symbol_column_bytes=sum(view['sid'].nbytes for view in self._price_views),
            max_query_rows=self._max_rows,
            memory_accounting='Price days/values borrow immutable NumPy buffers. '
                'Symbol columns and join results are owned. No library memory cap is asserted.')
        self.stats.update(self._setup_stats)

    def begin(self, request):
        super().begin(request)
        self.stats.update(self._setup_stats)
        begin_stats(self.stats)
        self.stats['numeric_padding_rows'] = 0

    def _guard(self):
        if self._closed:
            raise RuntimeError('Polars candidate executor is closed.')
        deadline = getattr(self, 'deadline', None)
        if deadline is not None and time.perf_counter() >= deadline:
            raise TimeoutError('Analytical candidate request exceeded its time budget.')

    def select_reports(self, entry_ordinals):
        """Resolve both full report pools in strict multi-date temporal joins."""
        self._guard()
        pl = self._pl
        queries, books = report_queries(entry_ordinals, len(self._inputs.symbols), self._max_rows)
        self.stats['report_batches'] += 1
        self.stats['report_probe_rows'] += len(queries['query_id'])
        self.stats['max_report_batch_days'] = max(self.stats['max_report_batch_days'], books)
        shape = books, len(self._inputs.symbols)
        if not len(queries['query_id']):
            return np.empty(shape, dtype=np.int32), np.empty(shape, dtype=np.int32)
        query_frame = pl.DataFrame(queries).sort(['sid', 'day'])
        age = int(rules.MAX_AGE.days)
        outputs = []
        for pool in ('cached', 'legacy'):
            frame = (
                query_frame.lazy().join_asof(self._reports[pool].lazy(),
                    left_on='day', right_on='known', by='sid', strategy='backward',
                    allow_exact_matches=False, check_sortedness=False)
                .with_columns(pl.when(pl.col('day')-pl.col('fiscal') <= age)
                    .then(pl.col('report_id')).otherwise(-1).cast(pl.Int32).alias('report_id'))
                .sort('query_id').select('query_id', 'report_id').collect()
            )
            if not np.array_equal(frame['query_id'].to_numpy(), queries['query_id']):
                raise ValueError('Temporal report join changed query identity/order.')
            outputs.append(frame['report_id'].to_numpy().reshape(shape))
        self._guard()
        return tuple(outputs)

    def resolve(self, symbol_ids, days, columns, forwards):
        """Resolve every batch query through grouped forward/backward ASOF."""
        self._guard()
        pl = self._pl
        queries = price_queries(symbol_ids, days, columns, forwards, self._max_rows)
        count = len(queries['query_id'])
        self.stats['price_batches'] += 1
        self.stats['price_queries'] += count
        self.stats['max_price_queries'] = max(self.stats['max_price_queries'], count)
        if not count:
            return np.empty(0, dtype=np.int32), np.empty(0, dtype=np.float64)
        query_frame = pl.DataFrame(queries)
        pieces = []
        for column in (0, 1):
            for forward in (False, True):
                selected = query_frame.filter((pl.col('column') == column) &
                                              (pl.col('forward') == forward))
                if not len(selected):
                    continue
                cohort = selected['sid'].unique()
                # Filter retains sorted per-symbol input order and avoids a
                # large right-hand join for companies absent from this batch.
                history = self._prices[column].lazy().filter(pl.col('sid').is_in(cohort.implode()))
                pieces.append(
                    selected.sort(['sid', 'day']).lazy().join_asof(history,
                        left_on='day', right_on='actual', by='sid',
                        strategy='forward' if forward else 'backward',
                        allow_exact_matches=True, check_sortedness=False)
                    .select('query_id', 'actual', 'value')
                )
        frame = pl.concat(pieces).sort('query_id').collect()
        if not np.array_equal(frame['query_id'].to_numpy(), queries['query_id']):
            raise ValueError('Price ASOF joins changed query identity/order.')
        actual = np.nan_to_num(frame['actual'].to_numpy(), nan=0).astype(np.int32)
        prices = np.asarray(frame['value'].to_numpy(), dtype=np.float64)
        if np.any((actual != 0) & ~np.isfinite(prices)):
            raise ValueError('ASOF resolved a nonfinite attached price.')
        self._guard()
        return actual, prices

    def calculate(self, matrix):
        """Run the attached source-derived arithmetic as one lazy projection."""
        self._guard()
        columns, count = matrix_columns(matrix, self._policy.input_names)
        self.stats['numeric_batches'] += 1
        self.stats['numeric_rows'] += count
        if not count:
            return np.empty((0, len(self._policy.output_names)), dtype=np.float64)
        # Polars' scalar division kernel can multiply by a reciprocal. Full
        # columns force ordinary elementwise division. A one-row projection
        # gets one duplicate work row so it uses that same vector kernel.
        work_count = max(2, count)
        if count == 1:
            columns = {name: np.repeat(values, 2) for name, values in columns.items()}
            self.stats['numeric_padding_rows'] += 1
        columns.update({name: np.full(work_count, value, dtype=np.float64)
                        for name, value in self._numeric_literals.values()})
        frame = self._pl.DataFrame(columns).lazy().select(self._numeric_expressions).collect(
            optimizations=self._numeric_optimizations)
        output = np.asarray(frame.to_numpy(), dtype=np.float64)[:count]
        self._guard()
        return output

    def close(self):
        """Release executor-owned frames, retaining caller-owned input buffers."""
        if getattr(self, '_closed', False):
            return
        self._closed = True
        self._reports.clear()
        self._prices.clear()
        self._price_views.clear()
        self._numeric_expressions.clear()
        super().close()


def attach(inputs, policy=None, limits=None):
    return Executor(inputs, policy, limits)
