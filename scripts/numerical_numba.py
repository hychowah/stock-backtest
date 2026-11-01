"""Compiled temporal and source-derived numerical candidate batches."""
from datetime import date
import os
import sys
import time
from numerical_execution import effective_lanes, observe_resources, numba_threads

if 'numba' not in sys.modules:
    os.environ.setdefault('NUMBA_NUM_THREADS',str(effective_lanes(observe_resources())))
import numba
import numpy as np
from numba import njit, prange

from numerical_books import PythonExecutor
from numerical_matrix import CompiledMatrix
from numerical_identity import compiler_identity
import numerical_candidates as candidates
import backtest_control


# Compatibility names retain the single source-owned kernel implementation.
from numerical_temporal import TemporalEvaluator, _reports, _resolve


class NumbaExecutor(PythonExecutor):
    def __init__(self,inputs,policy=None,limits=None):
        super().__init__(inputs,policy,limits)
        self.temporal = self._calculate = None
        try: self._initialize(inputs)
        except BaseException:
            self.close()
            raise

    def _initialize(self, inputs):
        self.temporal = TemporalEvaluator(inputs)
        began = time.perf_counter()
        numba.set_num_threads(numba_threads(self.limits.get('threads'),numba.config.NUMBA_NUM_THREADS))
        width = len(self.policy.output_names)
        decisions = self.policy.decisions if self.candidate_assembly == 'compiled' else None
        self.compiler = compiler_identity(inputs,int(numba.get_num_threads()),decisions=decisions)
        calculate = CompiledMatrix(self.policy, (inputs.signature,self.compiler['signature']),
            cache_bytes=self.limits.get('matrix_cache_bytes',16*1024**2),
            workspace_bytes=self.limits.get('workspace_bytes',64*1024**2),
            chunk_rows=self.limits.get('chunk_rows',1024))
        self._calculate = calculate
        self.select_reports(np.empty(0,dtype=np.int32))
        self.resolve(np.empty(0,dtype=np.int32),np.empty(0,dtype=np.int32),
                     np.empty(0,dtype=np.int8),np.empty(0,dtype=np.bool_))
        decision_signatures = {}
        if self.candidate_assembly == 'compiled':
            decision_namespace = {}
            exec(decisions.source, decision_namespace)
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
            value_columns = np.asarray([self.policy.output_index[name] for name in
                candidates.SNAPSHOT+candidates.PAIRS+tuple('filter_'+field for field in self.policy.filter_order)],dtype=np.int32)
            fields = len(self.policy.filter_order)
            @njit(parallel=True,fastmath=False,cache=False,error_model='numpy')
            def materialize(decisions,numeric,requested,first,identities,dates,values,validity):
                count=0
                for row in prange(len(numeric)):
                    identities[row]=first+row
                    if decisions[row,0]:
                        count+=1
                        validity[row,0]=1
                        for column in range(4):dates[row,column]=decisions[row,column+1]
                        for column in range(11):values[row,column]=numeric[row,value_columns[column]]
                        validity[row,1]=decisions[row,5]
                        validity[row,2]=decisions[row,6]
                        for column in range(fields):
                            value=numeric[row,value_columns[11+column]]
                            if requested[column] and np.isfinite(value):
                                values[row,11+column]=value
                                validity[row,3+column]=1
                return count
            self._materialize=materialize
            warmed=candidates.CandidateBatch.empty(1,self.policy)
            materialize(np.zeros((1,7),dtype=np.int64),np.ones((1,width)),
                np.ones(fields,dtype=np.uint8),0,warmed.identities,warmed.dates,warmed.values,warmed.validity)
            self._materialize_signatures=tuple(materialize.nopython_signatures)
            self._decision_signatures = tuple(decide.nopython_signatures)
            decision_signatures = {name:[str(value) for value in kernel.nopython_signatures]
                                   for name,kernel in kernels.items()}
            decision_signatures['materialize']=[str(value) for value in materialize.nopython_signatures]
            decision_signatures['decisions'] = [str(value) for value in decide.nopython_signatures]
        self.stats.update(backend='numba',compile_seconds=time.perf_counter()-began,
            threads=int(numba.get_num_threads()),compiler_cache=False,fastmath=False,
            versions=dict(numba=numba.__version__,numpy=np.__version__),
            nopython_signatures=dict(reports=[str(value) for value in _reports.nopython_signatures],
                prices=[str(value) for value in _resolve.nopython_signatures],
                factors=[str(value) for value in calculate.signatures],
                **decision_signatures))

    def assemble_candidates(self, books, rows, targets, lookup_days, lookup_values,
                            matrix, numeric, ranks, needed, results):
        if self.candidate_assembly == 'source':
            return super().assemble_candidates(books,rows,targets,lookup_days,lookup_values,
                                               matrix,numeric,ranks,needed,results)
        policy=self.policy
        meta=candidates.metadata(self.inputs,books,rows)
        requested=np.asarray([field in needed for field in policy.filter_order],dtype=np.uint8)
        batch=candidates.CandidateBatch.empty(len(rows),policy)
        began=time.perf_counter()
        for first in range(0,len(rows),self._calculate.chunk_rows):
            backtest_control.checkpoint()
            part=slice(first,first+self._calculate.chunk_rows)
            decisions=self._decide(lookup_days[part],lookup_values[part],numeric[part],meta[part],matrix[part])
            batch.count+=int(self._materialize(decisions,numeric[part],requested,first,
                batch.identities[part],batch.dates[part],batch.values[part],batch.validity[part]))
        self._time('decision_seconds',began)
        if (tuple(self._decide.nopython_signatures)!=self._decision_signatures
                or tuple(self._materialize.nopython_signatures)!=self._materialize_signatures):
            raise ValueError('Candidate decision/materialization signature changed after attachment.')
        began=time.perf_counter()
        accepted=candidates.encode(batch,self.inputs,policy,rows,ranks,results)
        self._time('encoding_seconds',began)
        return accepted

    def select_reports(self,entries):
        return self.temporal.select_reports(entries)

    def resolve(self,symbols,days,columns,forwards):
        if not len(days): return self.temporal.resolve(symbols,days,columns,forwards)
        actual = np.empty(len(days),dtype=np.int32)
        values = np.empty(len(days),dtype=np.float64)
        for first in range(0,len(days),2048):
            self.inputs.s.backtest_control.checkpoint()
            part = slice(first,first+2048)
            actual[part],values[part] = self.temporal.resolve(symbols[part],days[part],columns[part],forwards[part])
        return actual,values

    def close(self):
        if getattr(self, '_calculate', None) is not None: self._calculate.close()
        if getattr(self, 'temporal', None) is not None: self.temporal.close()
        self.inputs = self.policy = self._calculate = self._decide = self._materialize = None
        super().close()

    def calculate(self,matrix):
        return self._calculate(matrix)


def attach(inputs,policy=None,limits=None):
    return NumbaExecutor(inputs,policy,limits)
