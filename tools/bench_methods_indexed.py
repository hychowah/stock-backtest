"""Benchmark-only temporal report selection with unchanged financial arithmetic.

ReportIndex consumes the two prepared report pools, before cached-price
membership is applied. It returns the complete source candidate mappings and
stable original-buffer ranks. Index storage is proportional to annual reports;
no entry-date factors or completed portfolios are retained between requests.
"""
from bisect import bisect_left
from datetime import date
from pathlib import Path
import sys
import time

from bench_methods import Model
from bench_methods_arrays import open_prices


# Source identity includes the reused resolver, not just this adapter.
SOURCE_FILES = (Path(__file__).with_name('bench_methods_arrays.py'),)


class ReportIndex:
    """Select the last available, nonstale report in each prepared pool.

    ``books`` is the unchanged ``schedules.histories`` result. ``policy`` is
    its production ``run`` module, which owns MAX_AGE and BUFFER. Fiscal and
    availability dates must be nondecreasing within each history. Equal dates
    preserve row order. Unsupported ordering fails during untimed setup.
    ``at(day)`` preserves pool insertion order, report identity, strict
    availability, the inclusive age boundary and stable yield-tie ranking.
    """

    def __init__(self, books, policy):
        began = time.perf_counter()
        self.max_age = policy.MAX_AGE.days
        self.buffer = policy.BUFFER
        self._pools = {}
        indexed_rows = 0
        allocated = 0
        for pool, book in zip(('cached', 'legacy'), books, strict=True):
            series = []
            for symbol, rows in book.items():
                known, fiscal, reports = [], [], tuple(rows)
                for row in reports:
                    if type(row['fiscal']) is not date or type(row['known']) is not date:
                        raise ValueError('Report index requires prepared date objects.')
                    fiscal_day = row['fiscal'].toordinal()
                    known_day = row['known'].toordinal()
                    if fiscal and (fiscal_day < fiscal[-1] or known_day < known[-1]):
                        raise ValueError('Report index requires ordered fiscal and availability dates.')
                    fiscal.append(fiscal_day)
                    known.append(known_day)
                parts = (symbol,known,fiscal,reports)
                series.append(parts)
                indexed_rows += len(reports)
                allocated += sys.getsizeof(parts)
                allocated += sum(sys.getsizeof(part) for part in (known,fiscal,reports))
                allocated += sum(sys.getsizeof(value) for value in known + fiscal)
            self._pools[pool] = series
            allocated += sys.getsizeof(series)
        self.stats = dict(load_seconds=time.perf_counter()-began,
                          indexed_rows=indexed_rows,
                          symbols={pool:len(rows) for pool,rows in self._pools.items()},
                          # Python container estimate, excluding shared reports,
                          # allocator fragmentation and process-level resources.
                          index_allocated_bytes=allocated+sys.getsizeof(self._pools))

    def at(self, day):
        """Return both full statement mappings and original-buffer ranks."""
        ordinal = day.toordinal()
        statements = {}
        for pool, series in self._pools.items():
            selected = {}
            for symbol, known, fiscal, reports in series:
                index = bisect_left(known,ordinal)-1
                if index >= 0 and ordinal-fiscal[index] <= self.max_age:
                    selected[symbol] = reports[index]
            statements[pool] = selected
        original = statements['legacy']
        ranks = {symbol:rank for rank,symbol in enumerate(
            sorted(original,key=lambda symbol:original[symbol]['yield'],reverse=True)[:self.buffer],1)}
        return statements,ranks


class IndexedModel(Model):
    """Share scalar book evaluation; index reports and omit unused thresholds."""

    def __init__(self, source, schedules):
        super().__init__(source,schedules)
        try:
            self.report_index = ReportIndex(self.books,schedules.financial_books.run)
        except BaseException:
            self.close()
            raise
        self.setup_stats = dict(base_load_seconds=self.base_seconds,
                                report_index=self.report_index.stats)

    def candidate_reports(self, entry):
        return self.report_index.at(entry)

    def needs_thresholds(self, needed):
        return bool(needed)


def open_model(source, schedules):
    """Load an independently closeable model before timing a fresh request."""
    return IndexedModel(source,schedules)
