"""Multi-date report/price joins and source-derived factors in DuckDB.

Financial formulas come only from the attached PolicyProgram. Shared source
control still owns eligibility, exit labels and final SQLite screening. This
executor owns complete temporal histories and joins several requested dates at
once, rather than rerunning the old per-book price adapter.
"""
from pathlib import Path
import shutil
import tempfile
import time

import numpy as np

from bench_candidates import PythonExecutor
from backtest.financial import rules
from bench_candidates_analytical import (
    begin_stats, matrix_columns, price_columns, price_queries, quote,
    report_columns, report_queries, sql_expression, stage_stats, work_root,
)


SOURCE_FILES = (Path(__file__).with_name('bench_candidates.py'),
                Path(__file__).with_name('bench_candidates_analytical.py'))


class Executor(PythonExecutor):
    """Attach immutable histories and evaluate bounded multi-date SQL batches."""

    def __init__(self, inputs, policy=None, limits=None):
        super().__init__(inputs, policy, limits)
        import duckdb
        began = time.perf_counter()
        self._inputs = inputs
        self._policy = policy or inputs.policy
        self._limits = dict(limits or {})
        self._db = None
        self._directory = None
        self._price_views = []
        self._closed = False
        threads = self._limits.get('threads', 4)
        if type(threads) is not int or not 1 <= threads <= 4:
            raise ValueError('Analytical thread count must be an integer from one to four.')
        self._max_rows = self._limits.get('max_query_rows', 1_000_000)
        if type(self._max_rows) is not int or self._max_rows < 1:
            raise ValueError('Analytical query row limit must be positive.')
        memory_limit = self._limits.get('memory_limit', '1GB')
        try:
            self._directory = Path(tempfile.mkdtemp(prefix='duckdb-',
                dir=work_root(inputs, self._limits, 'duckdb')))
            self._db = duckdb.connect(config=dict(threads=threads,
                memory_limit=memory_limit, temp_directory=str(self._directory),
                preserve_insertion_order=False))
            for pool in ('cached', 'legacy'):
                self._db.register('report_chunk', report_columns(inputs, pool))
                try:
                    # Equal known dates preserve the last source row. This is
                    # resolved before ASOF so its tie choice is never implicit.
                    self._db.execute('CREATE TABLE ' + pool + '_reports AS '
                        'SELECT sid,known,fiscal,report_id FROM report_chunk '
                        'QUALIFY ROW_NUMBER() OVER(PARTITION BY sid,known ORDER BY position DESC)=1')
                finally:
                    self._db.unregister('report_chunk')
            for column, name in ((0, 'raw_prices'), (1, 'adjusted_prices')):
                view = price_columns(inputs, column)
                self._price_views.append(view)
                self._db.register(name, view)
            environment = {name: quote(name) for name in self._policy.input_names}
            self._numeric_sql = 'SELECT ' + ','.join(
                sql_expression(self._policy.expanded(name), environment) + ' AS ' + quote(name)
                for name in self._policy.output_names) + ' FROM numeric_inputs ORDER BY "__row_id"'
            self._setup_stats = stage_stats('duckdb',
                versions=dict(duckdb=duckdb.__version__, numpy=np.__version__),
                load_seconds=time.perf_counter()-began,
                threads=threads, memory_limit=memory_limit,
                symbol_column_bytes=sum(view['sid'].nbytes for view in self._price_views),
                temporary_directory=str(self._directory),
                memory_accounting='Price days/values borrow immutable NumPy buffers. '
                    'Symbol columns are owned. DuckDB buffer limit excludes Python/NumPy memory.',
                max_query_rows=self._max_rows)
            self.stats.update(self._setup_stats)
        except BaseException:
            self.close()
            raise

    def begin(self, request):
        super().begin(request)
        self.stats.update(self._setup_stats)
        begin_stats(self.stats)

    def _guard(self):
        if self._closed:
            raise RuntimeError('DuckDB candidate executor is closed.')
        deadline = getattr(self, 'deadline', None)
        if deadline is not None and time.perf_counter() >= deadline:
            raise TimeoutError('Analytical candidate request exceeded its time budget.')

    def select_reports(self, entry_ordinals):
        """Select both complete report pools for every requested entry date."""
        self._guard()
        queries, books = report_queries(entry_ordinals, len(self._inputs.symbols), self._max_rows)
        self.stats['report_batches'] += 1
        self.stats['report_probe_rows'] += len(queries['query_id'])
        self.stats['max_report_batch_days'] = max(self.stats['max_report_batch_days'], books)
        shape = books, len(self._inputs.symbols)
        if not len(queries['query_id']):
            return np.empty(shape, dtype=np.int32), np.empty(shape, dtype=np.int32)
        age = int(rules.MAX_AGE.days)
        answers = []
        self._db.register('report_queries', queries)
        try:
            for pool in ('cached', 'legacy'):
                rows = self._db.execute(
                    'SELECT q.query_id,CASE WHEN q.day-r.fiscal<=? THEN r.report_id ELSE -1 END AS report_id '
                    'FROM report_queries q ASOF LEFT JOIN ' + pool + '_reports r '
                    'ON q.sid=r.sid AND q.day>r.known ORDER BY q.query_id', [age]).fetchnumpy()
                if not np.array_equal(rows['query_id'], queries['query_id']):
                    raise ValueError('Temporal report join changed query identity/order.')
                answers.append(np.asarray(rows['report_id'], dtype=np.int32).reshape(shape))
        finally:
            self._db.unregister('report_queries')
        self._guard()
        return tuple(answers)

    def resolve(self, symbol_ids, days, columns, forwards):
        """Resolve all requested dates in grouped directional ASOF joins."""
        self._guard()
        queries = price_queries(symbol_ids, days, columns, forwards, self._max_rows)
        count = len(queries['query_id'])
        self.stats['price_batches'] += 1
        self.stats['price_queries'] += count
        self.stats['max_price_queries'] = max(self.stats['max_price_queries'], count)
        if not count:
            return np.empty(0, dtype=np.int32), np.empty(0, dtype=np.float64)
        pieces = []
        for column, table in ((0, 'raw_prices'), (1, 'adjusted_prices')):
            for forward in (False, True):
                selected = (queries['column'] == column) & (queries['forward'] == forward)
                if not np.any(selected):
                    continue
                predicate = '"column"=' + str(column) + (' AND "forward"' if forward else ' AND NOT "forward"')
                comparison = '<=' if forward else '>='
                pieces.append(
                    'SELECT q.query_id,p.day AS actual,p.value FROM '
                    '(SELECT query_id,sid,day FROM lookup_queries WHERE ' + predicate + ') q '
                    'ASOF LEFT JOIN (SELECT sid,day,value FROM ' + table + ' '
                    'WHERE sid IN (SELECT DISTINCT sid FROM lookup_queries WHERE ' + predicate + ')) p '
                    'ON q.sid=p.sid AND q.day' + comparison + 'p.day')
        self._db.register('lookup_queries', queries)
        try:
            rows = self._db.execute('SELECT * FROM (' + ' UNION ALL '.join(pieces) +
                                    ') answers ORDER BY query_id').fetchnumpy()
        finally:
            self._db.unregister('lookup_queries')
        if not np.array_equal(rows['query_id'], queries['query_id']):
            raise ValueError('Price ASOF joins changed query identity/order.')
        actual = rows['actual']
        prices = rows['value']
        if np.ma.isMaskedArray(actual):
            actual = actual.filled(0)
        if np.ma.isMaskedArray(prices):
            prices = prices.filled(np.nan)
        actual = np.asarray(actual, dtype=np.int32)
        prices = np.asarray(prices, dtype=np.float64)
        if np.any((actual != 0) & ~np.isfinite(prices)):
            raise ValueError('ASOF resolved a nonfinite attached price.')
        self._guard()
        return actual, prices

    def calculate(self, matrix):
        """Execute source-generated float64 factors for the entire row batch."""
        self._guard()
        columns, count = matrix_columns(matrix, self._policy.input_names)
        self.stats['numeric_batches'] += 1
        self.stats['numeric_rows'] += count
        if not count:
            return np.empty((0, len(self._policy.output_names)), dtype=np.float64)
        columns['__row_id'] = np.arange(count, dtype=np.int64)
        self._db.register('numeric_inputs', columns)
        try:
            rows = self._db.execute(self._numeric_sql).fetchnumpy()
        finally:
            self._db.unregister('numeric_inputs')
        output = np.empty((count, len(self._policy.output_names)), dtype=np.float64)
        for index, name in enumerate(self._policy.output_names):
            values = rows[name]
            output[:, index] = values.filled(np.nan) if np.ma.isMaskedArray(values) else values
        self._guard()
        return output

    def interrupt(self):
        if self._db is not None:
            self._db.interrupt()

    def close(self):
        """Release only executor-owned tables/buffers and temporary spill files."""
        if getattr(self, '_closed', False):
            return
        self._closed = True
        if self._db is not None:
            self._db.close()
            self._db = None
        self._price_views.clear()
        if self._directory is not None:
            shutil.rmtree(self._directory, ignore_errors=True)
        super().close()


def attach(inputs, policy=None, limits=None):
    return Executor(inputs, policy, limits)
