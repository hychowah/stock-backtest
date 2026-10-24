"""Compiled temporal and source-derived numerical candidate batches."""
import os
import sys
import time

if 'numba' not in sys.modules:
    os.environ.setdefault('NUMBA_NUM_THREADS','4')
import numba
import numpy as np
from numba import njit, prange

from bench_candidates import PythonExecutor


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


class NumbaExecutor(PythonExecutor):
    def __init__(self,inputs,policy=None,limits=None):
        super().__init__(inputs,policy,limits)
        began = time.perf_counter()
        numba.set_num_threads(min(int(self.limits.get('threads',4)),4,numba.config.NUMBA_NUM_THREADS))
        namespace = {}
        exec(self.policy.python_source('_row'),namespace)
        row_function = njit(fastmath=False,cache=False,error_model='numpy')(namespace['_row'])
        width = len(self.policy.output_names)
        @njit(parallel=True,fastmath=False,cache=False,error_model='numpy')
        def calculate(matrix):
            result = np.empty((len(matrix),width),dtype=np.float64)
            for row in prange(len(matrix)):
                values = row_function(matrix[row])
                for column in range(width):result[row,column] = values[column]
            return result
        self._calculate = calculate
        self.select_reports(np.empty(0,dtype=np.int32))
        self.resolve(np.empty(0,dtype=np.int32),np.empty(0,dtype=np.int32),
                     np.empty(0,dtype=np.int8),np.empty(0,dtype=np.bool_))
        calculate(np.ones((1,len(self.policy.input_names)),dtype=np.float64))
        self.stats.update(backend='numba',compile_seconds=time.perf_counter()-began,
            threads=int(numba.get_num_threads()),compiler_cache=False,fastmath=False,
            versions=dict(numba=numba.__version__,numpy=np.__version__),
            nopython_signatures=dict(reports=[str(value) for value in _reports.nopython_signatures],
                prices=[str(value) for value in _resolve.nopython_signatures],
                factors=[str(value) for value in calculate.nopython_signatures]))

    def select_reports(self,entries):
        inputs = self.inputs
        return tuple(_reports(entries,inputs.pool_offsets[pool],inputs.pool_report_ids[pool],
            inputs.pool_known[pool],inputs.pool_fiscal[pool],inputs.s.financial_books.run.MAX_AGE.days)
            for pool in ('cached','legacy'))

    def resolve(self,symbols,days,columns,forwards):
        inputs = self.inputs
        return _resolve(symbols,days,columns,forwards,inputs.raw_offsets,inputs.raw_days,
            inputs.raw_values,inputs.adjusted_offsets,inputs.adjusted_days,inputs.adjusted_values)

    def calculate(self,matrix):
        return self._calculate(matrix)


def attach(inputs,policy=None,limits=None):
    return NumbaExecutor(inputs,policy,limits)
