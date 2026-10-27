"""Compiled temporal and source-derived numerical candidate batches."""
from datetime import date
import os
import sys
import time

if 'numba' not in sys.modules:
    os.environ.setdefault('NUMBA_NUM_THREADS','4')
import numba
import numpy as np
from numba import njit, prange

from bench_candidates import PythonExecutor


# Compatibility names retain the single source-owned kernel implementation.
from numerical_temporal import TemporalEvaluator, _reports, _resolve


class NumbaExecutor(PythonExecutor):
    def __init__(self,inputs,policy=None,limits=None):
        super().__init__(inputs,policy,limits)
        self.temporal = TemporalEvaluator(inputs)
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
        decision_signatures = {}
        if self.candidate_assembly == 'compiled':
            decision_namespace = {}
            exec(self.policy.decisions.source, decision_namespace)
            kernels = {name:njit(fastmath=False,cache=False,error_model='numpy')(
                decision_namespace['_decision_'+name])
                for name in ('snapshot','eligible','current','three')}
            snapshot,eligible,current,three = (kernels[name] for name in
                                              ('snapshot','eligible','current','three'))
            average_column = self.policy.input_index['average_3y']
            bankruptcy_column = self.policy.input_index['bankruptcy']
            @njit(parallel=True,fastmath=False,cache=False,error_model='numpy')
            def decide(days, prices, numeric, metadata, matrix):
                decisions = np.zeros((len(numeric),7),dtype=np.int64)
                for row in prange(len(numeric)):
                    meta = metadata[row]
                    value = snapshot(days[row],prices[row],numeric[row],meta[0],meta[1],
                                     meta[2],meta[3],meta[4],matrix[row,bankruptcy_column])
                    if value[0] and eligible(numeric[row],meta[5]):
                        for column in range(5):decisions[row,column] = value[column]
                        decisions[row,5] = current(numeric[row],matrix[row,average_column],not np.isnan(matrix[row,average_column]))
                        decisions[row,6] = three(numeric[row],matrix[row,average_column],not np.isnan(matrix[row,average_column]))
                return decisions
            self._decide = decide
            decide(np.ones((1,7),dtype=np.int32),np.ones((1,7),dtype=np.float64),
                   np.ones((1,width),dtype=np.float64),np.ones((1,6),dtype=np.int32),
                   np.ones((1,len(self.policy.input_names)),dtype=np.float64))
            self._decision_signatures = tuple(decide.nopython_signatures)
            decision_signatures = {name:[str(value) for value in kernel.nopython_signatures]
                                   for name,kernel in kernels.items()}
            decision_signatures['decisions'] = [str(value) for value in decide.nopython_signatures]
        self.stats.update(backend='numba',compile_seconds=time.perf_counter()-began,
            threads=int(numba.get_num_threads()),compiler_cache=False,fastmath=False,
            versions=dict(numba=numba.__version__,numpy=np.__version__),
            nopython_signatures=dict(reports=[str(value) for value in _reports.nopython_signatures],
                prices=[str(value) for value in _resolve.nopython_signatures],
                factors=[str(value) for value in calculate.nopython_signatures],
                **decision_signatures))

    def assemble_candidates(self, books, rows, targets, lookup_days, lookup_values,
                            matrix, numeric, ranks, needed, results):
        if self.candidate_assembly == 'source':
            return super().assemble_candidates(books,rows,targets,lookup_days,lookup_values,
                                               matrix,numeric,ranks,needed,results)
        inputs,policy = self.inputs,self.policy
        metadata = np.empty((len(rows),6),dtype=np.int32)
        row_books = np.fromiter((row[0] for row in rows),dtype=np.int32,count=len(rows))
        row_reports = np.fromiter((row[2] for row in rows),dtype=np.int32,count=len(rows))
        book_dates = np.asarray([(entry.toordinal(),exit_day.toordinal(),entry.year,exit_day.year,
                                  int(pool=='legacy')) for entry,exit_day,pool in books],dtype=np.int32).reshape((-1,5))
        metadata[:,0] = inputs.report_fiscal[row_reports]
        metadata[:,1:] = book_dates[row_books]
        began = time.perf_counter()
        decisions = self._decide(lookup_days,lookup_values,numeric,metadata,matrix)
        self._time('decision_seconds',began)
        if tuple(self._decide.nopython_signatures) != self._decision_signatures:
            raise ValueError('Candidate decision signature changed after attachment.')
        began = time.perf_counter()
        if decisions.shape != (len(rows),7):raise ValueError('Backend candidate-decision shape differs.')
        accepted = decisions[:,0].astype(np.bool_)
        oi = policy.output_index
        for row in np.flatnonzero(accepted):
            book,symbol_id,report = rows[row]
            _,fiscal,buy,sell,status,current,three = decisions[row].tolist()
            if not 1<=status<=len(policy.decisions.statuses):
                raise ValueError('Backend candidate status differs.')
            values = numeric[row].tolist()
            observation = [str(date.fromordinal(int(day))) for day in (fiscal,buy,sell)]
            observation.extend(float(values[oi[name]]) for name in
                ('cap','ev','ebitda','yield_value','multiple','return_value'))
            observation.append(policy.decisions.statuses[status-1])
            current_pair = tuple(float(values[oi[name]]) for name in ('multiple','yield_value')) if current else None
            three_pair = tuple(float(values[oi[name]]) for name in ('metric3_multiple','metric3_yield')) if three else None
            self._encode_candidate(results[book],inputs.symbols[symbol_id],int(ranks[book,symbol_id]) or None,
                                   observation,current_pair,three_pair,values,needed)
        self._time('encoding_seconds',began)
        return accepted

    def select_reports(self,entries):
        return self.temporal.select_reports(entries)

    def resolve(self,symbols,days,columns,forwards):
        return self.temporal.resolve(symbols,days,columns,forwards)

    def close(self):
        self.temporal.close()
        super().close()

    def calculate(self,matrix):
        return self._calculate(matrix)


def attach(inputs,policy=None,limits=None):
    return NumbaExecutor(inputs,policy,limits)
