"""Benchmark-only sparse prices with compiled batched nearest-date searches.

Resolve the nearest non-null saved price in the requested direction, including
exact-day matches. Date tolerance belongs to the financial policy adapter.
This module never downloads, writes inputs, ranks holdings or saves results.
"""
from array import array
from datetime import date
import math
from numbers import Integral
import os
import sys
import time

# Set the pool capacity before importing Numba. set_num_threads alone masks an
# already-created pool and can otherwise leave many idle native threads alive.
if 'numba' not in sys.modules:
    os.environ['NUMBA_NUM_THREADS'] = str(min(4, int(os.environ.get('NUMBA_NUM_THREADS', '4'))))
import llvmlite
import numba
import numpy as np
from numba import njit, prange


@njit(parallel=True, fastmath=False, cache=False)
def _search(symbols, days, columns, forwards, raw_offsets, raw_days, raw_values,
            adjusted_offsets, adjusted_days, adjusted_values):
    """Search independent sparse histories without changing their arithmetic."""
    actual_days = np.zeros(len(symbols), dtype=np.int32)
    values = np.zeros(len(symbols), dtype=np.float64)
    found = np.zeros(len(symbols), dtype=np.bool_)
    for query in prange(len(symbols)):
        symbol = symbols[query]
        if symbol < 0:
            continue
        if columns[query] == 0:
            offsets, history_days, prices = raw_offsets, raw_days, raw_values
        else:
            offsets, history_days, prices = adjusted_offsets, adjusted_days, adjusted_values
        begin, end = offsets[symbol], offsets[symbol + 1]
        left, right = begin, end
        target = days[query]
        # Forward uses lower_bound; backward uses upper_bound minus one.
        forward = forwards[query]
        while left < right:
            middle = left + (right - left) // 2
            if history_days[middle] < target or (not forward and history_days[middle] == target):
                left = middle + 1
            else:
                right = middle
        position = left if forward else left - 1
        if begin <= position < end:
            found[query] = True
            actual_days[query] = history_days[position]
            values[query] = prices[position]
    return found, actual_days, values


class Prices:
    """Own immutable numeric buffers; the supplied database remains caller-owned."""

    def __init__(self, db):
        started = time.perf_counter()
        self._closed = False
        self._symbols = {}
        raw_days, raw_values = array('i'), array('d')
        adjusted_days, adjusted_values = array('i'), array('d')
        raw_offsets, adjusted_offsets = array('q'), array('q')
        if raw_days.itemsize != 4 or raw_offsets.itemsize != 8 or raw_values.itemsize != 8:
            raise RuntimeError('The benchmark requires 32-bit days and 64-bit offsets and prices.')
        rows = 0
        current = None
        ordinals = {}
        cursor = db.execute('SELECT symbol,day,price,adjusted FROM prices ORDER BY symbol,day')
        try:
            for symbol, day, raw, adjusted in cursor:
                if symbol != current:
                    self._symbols[symbol] = len(self._symbols)
                    raw_offsets.append(len(raw_days))
                    adjusted_offsets.append(len(adjusted_days))
                    current = symbol
                ordinal = ordinals.get(day)
                if ordinal is None:
                    ordinal = date.fromisoformat(day).toordinal()
                    ordinals[day] = ordinal
                if raw is not None:
                    if not math.isfinite(raw):
                        raise ValueError('Saved prices must be finite or null.')
                    raw_days.append(ordinal)
                    raw_values.append(raw)
                if adjusted is not None:
                    if not math.isfinite(adjusted):
                        raise ValueError('Saved prices must be finite or null.')
                    adjusted_days.append(ordinal)
                    adjusted_values.append(adjusted)
                rows += 1
        finally:
            cursor.close()
        raw_offsets.append(len(raw_days))
        adjusted_offsets.append(len(adjusted_days))
        # Views keep their primitive buffers alive. No Python row list or second
        # full numeric copy survives loading.
        self._raw_offsets = np.frombuffer(raw_offsets, dtype=np.int64)
        self._raw_days = np.frombuffer(raw_days, dtype=np.int32)
        self._raw_values = np.frombuffer(raw_values, dtype=np.float64)
        self._adjusted_offsets = np.frombuffer(adjusted_offsets, dtype=np.int64)
        self._adjusted_days = np.frombuffer(adjusted_days, dtype=np.int32)
        self._adjusted_values = np.frombuffer(adjusted_values, dtype=np.float64)
        self._buffers = (self._raw_offsets, self._raw_days, self._raw_values,
                         self._adjusted_offsets, self._adjusted_days, self._adjusted_values)
        for buffer in self._buffers:
            buffer.flags.writeable = False
        load_seconds = time.perf_counter() - started
        numba.set_num_threads(min(4, numba.get_num_threads()))
        compile_started = time.perf_counter()
        # Compile and start the bounded active threads before measuring requests.
        _search(np.array([-1], dtype=np.int64), np.array([1], dtype=np.int32),
                np.array([0], dtype=np.int8), np.array([False], dtype=np.bool_),
                *self._buffers)
        self.stats = dict(versions=dict(numpy=np.__version__, numba=numba.__version__,
                                        llvmlite=llvmlite.__version__),
                          load_seconds=load_seconds,
                          compile_seconds=time.perf_counter() - compile_started,
                          payload_bytes=sum(buffer.nbytes for buffer in self._buffers),
                          rows=rows, symbols=len(self._symbols),
                          raw_rows=len(raw_days), adjusted_rows=len(adjusted_days),
                          threads=numba.get_num_threads(), compiler_cache=False,
                          thread_pool_capacity=numba.config.NUMBA_NUM_THREADS,
                          memory_accounting='Numeric payload only; excludes symbol dictionary, runtime and query buffers.')

    def resolve(self, queries):
        """Return ordered None or (ordinal, price) answers; apply no date slack."""
        if self._closed:
            raise RuntimeError('The price resolver is closed.')
        count = len(queries)
        if not count:
            return []
        symbols = np.empty(count, dtype=np.int64)
        days = np.empty(count, dtype=np.int32)
        columns = np.empty(count, dtype=np.int8)
        forwards = np.empty(count, dtype=np.bool_)
        for index, query in enumerate(queries):
            if len(query) != 4:
                raise ValueError('Each price query must have four fields.')
            symbol, ordinal, column, forward = query
            if not isinstance(symbol, str):
                raise ValueError('A price query needs a symbol string.')
            if isinstance(ordinal, bool) or not isinstance(ordinal, Integral) or not 1 <= ordinal <= date.max.toordinal():
                raise ValueError('A price query needs a valid ordinal day.')
            if column not in ('price', 'adjusted') or type(forward) is not bool:
                raise ValueError('A price query needs a supported column and boolean direction.')
            symbols[index] = self._symbols.get(symbol, -1)
            days[index] = ordinal
            columns[index] = column == 'adjusted'
            forwards[index] = forward
        found, actual, values = _search(symbols, days, columns, forwards, *self._buffers)
        return [(int(actual[index]), float(values[index])) if found[index] else None
                for index in range(count)]

    def close(self):
        """Release numeric views; never close the caller's SQLite connection."""
        if self._closed:
            return
        self._closed = True
        self._symbols.clear()
        self._buffers = ()
        self._raw_offsets = self._raw_days = self._raw_values = None
        self._adjusted_offsets = self._adjusted_days = self._adjusted_values = None


def open_prices(readonly_sqlite_db):
    """Attach saved prices as sparse compiled-search buffers without input writes."""
    return Prices(readonly_sqlite_db)
