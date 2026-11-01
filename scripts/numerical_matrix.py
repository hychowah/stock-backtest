"""Strict compiled matrices with bounded reuse on the complete-book path.

Budgets account retained Python keys and buffers, not process working set.
Inputs, projections and compiler/generation identities are exact cache keys.
"""
from collections import OrderedDict
import sys
from threading import Lock

import backtest_control
import numpy as np
from numba import njit, prange

_compilation_requests=0
_compilation_lock=Lock()


def compilation_requests():
    """Actual factor-kernel compilation entries in this process, including failures."""
    with _compilation_lock:return _compilation_requests


def compile_matrix(policy, outputs=None):
    global _compilation_requests
    with _compilation_lock:_compilation_requests+=1
    selected = policy.output_names if outputs is None else tuple(outputs)
    namespace = {}
    exec(policy.python_source('_row', outputs=outputs), namespace)
    row_function = njit(fastmath=False, cache=False, error_model='numpy')(namespace['_row'])
    width = len(selected)
    @njit(parallel=True, fastmath=False, cache=False, error_model='numpy')
    def calculate(matrix):
        result = np.empty((len(matrix), width), dtype=np.float64)
        for row in prange(len(matrix)):
            values = row_function(matrix[row])
            for column in range(width): result[row, column] = values[column]
        return result
    calculate(np.ones((1, len(policy.input_names)), dtype=np.float64))
    return calculate


def retained_size(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen: return 0
    seen.add(id(value))
    total = sys.getsizeof(value)
    if isinstance(value, np.ndarray):
        if value.base is not None: total += retained_size(value.base, seen)
    elif isinstance(value, dict):
        total += sum(retained_size(k, seen)+retained_size(v, seen) for k,v in value.items())
    elif isinstance(value, (tuple,list)):
        total += sum(retained_size(v, seen) for v in value)
    return total


class CompiledMatrix:
    """Own one prewarmed signature and finite numerical-output LRU.

    All inputs are float64 contiguous matrices. The full input bytes, shape,
    projection and immutable calculation identity participate. Chunking bounds
    native cancellation intervals; the workspace estimate is not an allocator.
    Oversized entries complete without cache retention. Return values are copies.
    """
    def __init__(self, policy, identity, outputs=None, *, cache_bytes=16*1024**2,
                 workspace_bytes=64*1024**2, chunk_rows=1024, kernel=None):
        if (any(type(v) is not int for v in (cache_bytes,workspace_bytes,chunk_rows))
                or cache_bytes < 0 or workspace_bytes <= 0 or not 1 <= chunk_rows <= 4096):
            raise ValueError('Invalid compiled matrix budgets.')
        self.identity, self.outputs = identity, tuple(policy.output_names if outputs is None else outputs)
        self.width = len(policy.input_names)
        self.cache_bytes, self.workspace_bytes, self.chunk_rows = cache_bytes, workspace_bytes, chunk_rows
        self._cache = OrderedDict()
        self.closed = False
        self.stats = dict(hits=0,misses=0,evictions=0,retained_bytes=0,retained_entries=0,
                          peak_workspace_bound=0,native_chunks=0)
        backtest_control.checkpoint()
        self.kernel = compile_matrix(policy, outputs) if kernel is None else kernel
        self.signatures = self._signatures()
        backtest_control.checkpoint()

    def __call__(self, matrix):
        if self.closed: raise ValueError('Compiled matrix is closed.')
        if matrix.dtype != np.float64 or matrix.ndim != 2 or matrix.shape[1] != self.width:
            raise ValueError('Compiled matrix signature differs.')
        estimate = 4096 + len(matrix)*8*(3*self.width+3*len(self.outputs))
        if estimate > self.workspace_bytes: raise ValueError('Numerical matrix exceeds its workspace bound.')
        self.stats['peak_workspace_bound'] = max(self.stats['peak_workspace_bound'],estimate)
        backtest_control.checkpoint()
        key = (self.identity,self.outputs,matrix.shape,matrix.tobytes())
        if key in self._cache:
            value = self._cache.pop(key); self._cache[key] = value
            self.stats['hits'] += 1
        else:
            self.stats['misses'] += 1
            value = np.empty((len(matrix),len(self.outputs)),dtype=np.float64)
            for first in range(0,len(matrix),self.chunk_rows):
                backtest_control.checkpoint()
                part = np.ascontiguousarray(matrix[first:first+self.chunk_rows])
                value[first:first+len(part)] = self.kernel(part)
                self.stats['native_chunks'] += 1
            backtest_control.checkpoint()
            if self._signatures() != self.signatures:
                raise ValueError('Compiled matrix signature changed after prewarm.')
            if retained_size(OrderedDict([(key,value)])) <= self.cache_bytes:
                self._cache[key] = value
                while retained_size(self._cache) > self.cache_bytes:
                    self._cache.popitem(last=False); self.stats['evictions'] += 1
        self.stats.update(retained_bytes=retained_size(self._cache) if self._cache else 0,
                          retained_entries=len(self._cache))
        return value.copy()

    def _signatures(self):
        # Trusted native factor kernels expose their exact ABI/build signature.
        # Numba retains its warmed nopython specialization proof.
        return tuple(self.kernel.nopython_signatures if hasattr(self.kernel,'nopython_signatures')
                     else self.kernel.signatures)

    def close(self):
        self._cache.clear()
        self.stats.update(retained_bytes=0,retained_entries=0)
        self.kernel = None
        self.closed = True
