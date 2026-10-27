"""Versioned sparse temporal lookup over borrowed immutable numerical inputs.

Report availability is strict; report age is inclusive. Price endpoints include
exact dates. Missing results are report -1 or price (0, NaN). Search does not
apply tolerances: the source snapshot policy owns calendar-day limits and exits.
"""
from datetime import date
import os
import sys

if 'numba' not in sys.modules:
    os.environ.setdefault('NUMBA_NUM_THREADS', '4')
import numpy as np
from numba import njit, prange
from numerical_generation import TEMPORAL_VERSION


@njit(parallel=True,fastmath=False,cache=False)
def _reports(entries,offsets,identities,known,fiscal,max_age):
    symbols = len(offsets)-1
    output = np.full((len(entries),symbols),-1,dtype=np.int32)
    for flat in prange(len(entries)*symbols):
        book,symbol = flat//symbols,flat%symbols
        begin,end = offsets[symbol],offsets[symbol+1]
        left,right = begin,end
        while left<right:
            middle = left+(right-left)//2
            if known[middle]<entries[book]:left=middle+1
            else:right=middle
        position = left-1
        if position>=begin and entries[book]-fiscal[position]<=max_age:
            output[book,symbol] = identities[position]
    return output


@njit(parallel=True,fastmath=False,cache=False)
def _resolve(symbols,targets,columns,forwards,raw_offsets,raw_days,raw_values,
             adjusted_offsets,adjusted_days,adjusted_values):
    actual = np.zeros(len(targets),dtype=np.int32)
    values = np.full(len(targets),np.nan,dtype=np.float64)
    for index in prange(len(targets)):
        symbol = symbols[index]
        if symbol<0:continue
        if columns[index]==0:offsets,days,prices=raw_offsets,raw_days,raw_values
        else:offsets,days,prices=adjusted_offsets,adjusted_days,adjusted_values
        begin,end = offsets[symbol],offsets[symbol+1]
        left,right = begin,end
        while left<right:
            middle = left+(right-left)//2
            if days[middle]<targets[index] or (not forwards[index] and days[middle]==targets[index]):left=middle+1
            else:right=middle
        position = left if forwards[index] else left-1
        if begin<=position<end:actual[index],values[index]=days[position],prices[position]
    return actual,values


class TemporalEvaluator:
    """Borrow verified buffers without owning their lease or database.

    Use original symbol IDs, not alphabetical positions. Series 0 is valuation;
    series 1 is adjusted. Symbol -1 means missing. Close before the attachment.
    The caller owns source and cache, validates freshness before each job, and
    retains ownership through all calculations and closure.
    """
    def __init__(self, inputs):
        if getattr(inputs, 'closed', False):
            raise ValueError('Numerical attachment is closed.')
        if type(getattr(inputs, 'temporal_version', None)) is not int or inputs.temporal_version != TEMPORAL_VERSION:
            raise ValueError('Unsupported temporal interface version.')
        self.inputs = inputs
        self.closed = False

    def _open(self):
        if self.closed or getattr(self.inputs, 'closed', False):
            raise ValueError('Temporal evaluator or attachment is closed.')
        return self.inputs

    @staticmethod
    def _integers(value, name, low, high, dtype):
        array = np.asarray(value)
        if array.ndim != 1 or array.dtype.kind not in 'iu' or np.any(array < low) or np.any(array > high):
            raise ValueError('Invalid temporal ' + name + '.')
        return np.ascontiguousarray(array, dtype=dtype)

    def select_reports(self, entries):
        """Return cached, legacy report-ID matrices in original symbol order."""
        inputs = self._open()
        entries = self._integers(entries, 'entry days', 1, date.max.toordinal(), np.int32)
        return tuple(_reports(entries, inputs.pool_offsets[pool], inputs.pool_report_ids[pool],
            inputs.pool_known[pool], inputs.pool_fiscal[pool], inputs.s.financial_books.run.MAX_AGE.days)
            for pool in ('cached', 'legacy'))

    def resolve(self, symbols, days, columns, forwards):
        """Return nearest actual days and prices, preserving request order.

        Four equal-length one-dimensional vectors are required. Days are valid
        date ordinals. Directions are Boolean. Unknown symbols use exactly -1.
        Empty batches are supported with typed arrays.
        """
        inputs = self._open()
        symbols = self._integers(symbols, 'symbol IDs', -1, len(inputs.symbols)-1, np.int32)
        days = self._integers(days, 'target days', 1, date.max.toordinal(), np.int32)
        columns = self._integers(columns, 'series IDs', 0, 1, np.int8)
        forwards = np.asarray(forwards)
        if forwards.ndim != 1 or forwards.dtype != np.bool_:
            raise ValueError('Invalid temporal directions.')
        forwards = np.ascontiguousarray(forwards)
        if not len(symbols) == len(days) == len(columns) == len(forwards):
            raise ValueError('Temporal request lengths differ.')
        return _resolve(symbols, days, columns, forwards, inputs.raw_offsets, inputs.raw_days,
            inputs.raw_values, inputs.adjusted_offsets, inputs.adjusted_days, inputs.adjusted_values)

    def close(self):
        self.inputs = None
        self.closed = True

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, *args):
        self.close()
