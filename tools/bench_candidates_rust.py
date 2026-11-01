"""Benchmark-only native report/price searches and source-generated factors.

The version-1 C ABI borrows contiguous numerical arrays for one synchronous
call. No pointer survives that call. Generated financial expressions come from
the common source-bound policy. Hash-named build directories prevent replacing
a DLL while Windows still maps it. The caller owns input and cache lifetimes.
"""
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.inputs import research
from backtest.financial import rules
import ctypes
import hashlib
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from threading import RLock
import time

import numpy as np

from bench_candidates import PythonExecutor


ABI = 1
_I32 = ctypes.POINTER(ctypes.c_int32)
_I64 = ctypes.POINTER(ctypes.c_int64)
_F64 = ctypes.POINTER(ctypes.c_double)
_U8 = ctypes.POINTER(ctypes.c_uint8)
_SIZE = ctypes.c_size_t


def _literal(value):
    value = float(value)
    if math.isnan(value):
        return 'f64::NAN'
    if math.isinf(value):
        return 'f64::INFINITY' if value > 0 else 'f64::NEG_INFINITY'
    return repr(value)+'_f64'


def rust_expressions(policy):
    """Lower the shared ordered arithmetic tree without algebraic rewrites."""
    inputs = {name: index for index, name in enumerate(policy.input_names)}
    derived = {}
    lines = []

    def lower(node):
        if not isinstance(node, tuple) or not node:
            raise ValueError('Rust factors require a shared expression tuple.')
        op = node[0]
        if op == 'input' and len(node) == 2:
            if node[1] not in inputs:
                raise ValueError('Unknown source policy input: '+str(node[1]))
            return f'input[{inputs[node[1]]}]'
        if op == 'const' and len(node) == 2:
            return _literal(node[1])
        if op == 'var' and len(node) == 2:
            if node[1] not in derived:
                raise ValueError('Source policy references an unordered derived value.')
            return derived[node[1]]
        if op == 'neg' and len(node) == 2:
            return '(-'+lower(node[1])+')'
        if op in ('add', 'sub', 'mul', 'div') and len(node) == 3:
            operator = dict(add='+', sub='-', mul='*', div='/')[op]
            return '('+lower(node[1])+operator+lower(node[2])+')'
        if op == 'if' and len(node) == 4:
            return '(if '+lower(node[1])+' != 0.0_f64 {'+lower(node[2])+'} else {'+lower(node[3])+'})'
        raise ValueError('Unsupported shared policy expression for Rust: '+str(op))

    for name, expression in policy.expressions:
        if name in derived:
            raise ValueError('Source policy has duplicate derived names.')
        variable = 'v'+str(len(derived))
        lines.append('let '+variable+': f64 = '+lower(expression)+';')
        derived[name] = variable
    for index, name in enumerate(policy.output_names):
        if name not in derived:
            raise ValueError('Source policy output is not an ordered expression.')
        lines.append(f'output[{index}] = {derived[name]};')
    return '\n'.join(lines)


def rust_source(policy):
    """Build the fixed numerical ABI plus only source-derived factor arithmetic."""
    factors = rust_expressions(policy)
    return r'''
use std::slice;

fn factors(input: &[f64], output: &mut [f64]) {
__FACTORS__
}

#[no_mangle]
pub unsafe extern "C" fn candidate_abi() -> i32 { 1 }

#[no_mangle]
pub unsafe extern "C" fn candidate_reports(
    entries: *const i32, nbooks: usize, offsets: *const i64,
    nsymbols: usize, report_ids: *const i32, nids: usize,
    known: *const i32, fiscal: *const i32, nreports: usize,
    age: i32, output: *mut i32) -> i32 {
    let entries = slice::from_raw_parts(entries, nbooks);
    let offsets = slice::from_raw_parts(offsets, nsymbols+1);
    let ids = slice::from_raw_parts(report_ids, nids);
    let known = slice::from_raw_parts(known, nreports);
    let fiscal = slice::from_raw_parts(fiscal, nreports);
    let output = slice::from_raw_parts_mut(output, nbooks*nsymbols);
    for (book, &day) in entries.iter().enumerate() {
        for symbol in 0..nsymbols {
            let begin = offsets[symbol] as usize;
            let end = offsets[symbol+1] as usize;
            let (mut left, mut right) = (begin, end);
            while left < right {
                let middle = left+(right-left)/2;
                if known[ids[middle] as usize] < day { left=middle+1; }
                else { right=middle; }
            }
            let mut selected = -1;
            if left > begin {
                let report = ids[left-1];
                if day-fiscal[report as usize] <= age { selected=report; }
            }
            output[book*nsymbols+symbol] = selected;
        }
    }
    0
}

#[no_mangle]
pub unsafe extern "C" fn candidate_prices(
    symbols: *const i32, days: *const i32, columns: *const u8,
    forwards: *const u8, nqueries: usize, nsymbols: usize,
    raw_offsets: *const i64, raw_days: *const i32, raw_values: *const f64,
    nraw: usize, adjusted_offsets: *const i64, adjusted_days: *const i32,
    adjusted_values: *const f64, nadjusted: usize,
    actual: *mut i32, values: *mut f64) -> i32 {
    let symbols=slice::from_raw_parts(symbols,nqueries);
    let days=slice::from_raw_parts(days,nqueries);
    let columns=slice::from_raw_parts(columns,nqueries);
    let forwards=slice::from_raw_parts(forwards,nqueries);
    let raw_offsets=slice::from_raw_parts(raw_offsets,nsymbols+1);
    let raw_days=slice::from_raw_parts(raw_days,nraw);
    let raw_values=slice::from_raw_parts(raw_values,nraw);
    let adjusted_offsets=slice::from_raw_parts(adjusted_offsets,nsymbols+1);
    let adjusted_days=slice::from_raw_parts(adjusted_days,nadjusted);
    let adjusted_values=slice::from_raw_parts(adjusted_values,nadjusted);
    let actual=slice::from_raw_parts_mut(actual,nqueries);
    let values=slice::from_raw_parts_mut(values,nqueries);
    for query in 0..nqueries {
        actual[query]=0; values[query]=f64::NAN;
        let symbol=symbols[query];
        if symbol < 0 || symbol as usize >= nsymbols { continue; }
        let symbol=symbol as usize;
        let (offsets,history,prices)=if columns[query] == 0 {
            (raw_offsets,raw_days,raw_values)
        } else { (adjusted_offsets,adjusted_days,adjusted_values) };
        let begin=offsets[symbol] as usize;
        let end=offsets[symbol+1] as usize;
        let (mut left,mut right)=(begin,end);
        let forward=forwards[query] != 0;
        while left < right {
            let middle=left+(right-left)/2;
            if history[middle] < days[query] || (!forward && history[middle] == days[query]) {
                left=middle+1;
            } else { right=middle; }
        }
        let position=if forward {left as i64} else {left as i64-1};
        if position >= begin as i64 && position < end as i64 {
            actual[query]=history[position as usize];
            values[query]=prices[position as usize];
        }
    }
    0
}

#[no_mangle]
pub unsafe extern "C" fn candidate_factors(
    input: *const f64, nrows: usize, ninputs: usize,
    output: *mut f64, noutputs: usize, threads: usize) -> i32 {
    if ninputs != __NINPUTS__ || noutputs != __NOUTPUTS__ { return -1; }
    let input=slice::from_raw_parts(input,nrows*ninputs);
    let output=slice::from_raw_parts_mut(output,nrows*noutputs);
    let threads=threads.max(1).min(4);
    if nrows < 64 || threads == 1 {
        for row in 0..nrows {
            factors(&input[row*ninputs..(row+1)*ninputs],
                    &mut output[row*noutputs..(row+1)*noutputs]);
        }
    } else {
        let chunk=(nrows+threads-1)/threads;
        std::thread::scope(|scope| {
            for (index,part) in output.chunks_mut(chunk*noutputs).enumerate() {
                let start=index*chunk;
                scope.spawn(move || {
                    for row in 0..part.len()/noutputs {
                        factors(&input[(start+row)*ninputs..(start+row+1)*ninputs],
                                &mut part[row*noutputs..(row+1)*noutputs]);
                    }
                });
            }
        });
    }
    0
}
'''.replace('__FACTORS__', factors).replace('__NINPUTS__', str(len(policy.input_names))).replace(
        '__NOUTPUTS__', str(len(policy.output_names)))


def _compiler(inputs, limits):
    supplied = limits.get('rustc') or os.environ.get('BACKTEST_RUSTC')
    if supplied:
        path = Path(supplied)
    else:
        located = shutil.which('rustc')
        path = Path(located) if located else Path(research.ROOT) / 'tmp/cb02-all-methods/rust/toolchain/bin/rustc.exe'
    if not path.is_file():
        raise ImportError('A native Rust compiler is required for this candidate.')
    if os.name != 'nt' and path.suffix.lower() == '.exe':
        raise ImportError('Use native Windows Python with the installed Windows Rust compiler.')
    return path


def _ptr(array, kind):
    return array.ctypes.data_as(kind)


class NativeKernel:
    """Own one generated library and serialize native calls with library closure."""

    def __init__(self, inputs, policy, limits):
        began = time.perf_counter()
        self.inputs, self.policy = inputs, policy
        self._lock = RLock()
        self._closed = False
        self._library = None
        self.threads = min(4, int(limits.get('threads', 4)))
        if self.threads < 1:
            raise ValueError('Rust candidate threads must be positive.')
        compiler = _compiler(inputs, limits)
        version = subprocess.run([str(compiler), '--version'], capture_output=True, text=True,
                                 check=True, timeout=30).stdout.strip()
        source = rust_source(policy)
        compile_flags = ('--edition=2021','-O','-C','panic=abort','-C','target-cpu=native')
        signature = hashlib.sha256((str(ABI)+policy.signature+version+repr(compile_flags)+source).encode()).hexdigest()
        workdir = Path(limits.get('workdir') or Path(research.ROOT) / 'tmp/cb02-candidates/rust')
        workdir.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix='kernel-'+signature[:16]+'-', dir=workdir))
        source_path = self.directory / 'kernel.rs'
        source_path.write_text(source, encoding='utf-8')
        library_path = self.directory / ('kernel.dll' if os.name == 'nt' else 'kernel.so')
        compile_started = time.perf_counter()
        command = [str(compiler), '--crate-name', 'candidate_kernel', '--crate-type', 'cdylib',
                   *compile_flags, str(source_path), '-o', str(library_path)]
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=float(limits.get('setup_seconds', 600.)))
        if result.returncode:
            raise RuntimeError('Rust candidate compilation failed: '+result.stderr[-4000:])
        compile_seconds = time.perf_counter()-compile_started
        try:
            self._library = ctypes.CDLL(str(library_path))
            self._library.candidate_abi.restype = ctypes.c_int
            self._library.candidate_abi.argtypes = []
            if self._library.candidate_abi() != ABI:
                raise ValueError('Rust candidate library ABI disagrees.')
            self._reports = self._library.candidate_reports
            self._reports.argtypes = [_I32,_SIZE,_I64,_SIZE,_I32,_SIZE,_I32,_I32,_SIZE,ctypes.c_int32,_I32]
            self._reports.restype = ctypes.c_int
            self._prices = self._library.candidate_prices
            self._prices.argtypes = [_I32,_I32,_U8,_U8,_SIZE,_SIZE,_I64,_I32,_F64,_SIZE,
                                    _I64,_I32,_F64,_SIZE,_I32,_F64]
            self._prices.restype = ctypes.c_int
            self._factors = self._library.candidate_factors
            self._factors.argtypes = [_F64,_SIZE,_SIZE,_F64,_SIZE,_SIZE]
            self._factors.restype = ctypes.c_int
        except BaseException:
            self.close()
            raise
        self.stats = dict(rustc=version, abi=ABI, signature=signature,
                          policy_signature=policy.signature,
                          source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                          library_sha256=hashlib.sha256(library_path.read_bytes()).hexdigest(),
                          compile_seconds=compile_seconds, setup_seconds=time.perf_counter()-began,
                          artifact_bytes=sum(path.stat().st_size for path in self.directory.iterdir()),
                          compiler_cache=False, threads=self.threads,
                          target_cpu='native', fastmath=False,
                          temporal_threads=1, boundary='Synchronous borrowed-buffer C ABI; no retained pointers.')

    def reports(self, entries):
        inputs = self.inputs
        entries = np.ascontiguousarray(entries, dtype=np.int32)
        count = len(inputs.symbols)
        known = np.ascontiguousarray(inputs.report_known, dtype=np.int32)
        fiscal = np.ascontiguousarray(inputs.report_fiscal, dtype=np.int32)
        outputs = []
        with self._lock:
            self._ensure_open()
            for pool in ('cached', 'legacy'):
                offsets = np.ascontiguousarray(inputs.pool_offsets[pool], dtype=np.int64)
                ids = np.ascontiguousarray(inputs.pool_report_ids[pool], dtype=np.int32)
                output = np.empty((len(entries),count), dtype=np.int32)
                if len(entries) and count:
                    code = self._reports(_ptr(entries,_I32),len(entries),_ptr(offsets,_I64),count,
                        _ptr(ids,_I32),len(ids),_ptr(known,_I32),_ptr(fiscal,_I32),len(known),
                        rules.MAX_AGE.days,_ptr(output,_I32))
                    if code:
                        raise RuntimeError('Rust report search failed.')
                outputs.append(output)
        return tuple(outputs)

    def resolve(self, symbols, days, columns, forwards):
        inputs = self.inputs
        symbols = np.ascontiguousarray(symbols, dtype=np.int32)
        days = np.ascontiguousarray(days, dtype=np.int32)
        columns = np.ascontiguousarray(columns, dtype=np.uint8)
        forwards = np.ascontiguousarray(forwards, dtype=np.uint8)
        count = len(symbols)
        if any(len(part) != count for part in (days,columns,forwards)):
            raise ValueError('Rust price query columns must have equal length.')
        if np.any(columns > 1) or np.any(forwards > 1):
            raise ValueError('Rust price query directions and columns must be binary.')
        actual = np.zeros(count,dtype=np.int32)
        values = np.full(count,np.nan,dtype=np.float64)
        # Core numerical arrays have the stated dtypes; conversion does not
        # allocate another full copy when they are contiguous read-only maps.
        ro = np.ascontiguousarray(inputs.raw_offsets,dtype=np.int64)
        rd = np.ascontiguousarray(inputs.raw_days,dtype=np.int32)
        rv = np.ascontiguousarray(inputs.raw_values,dtype=np.float64)
        ao = np.ascontiguousarray(inputs.adjusted_offsets,dtype=np.int64)
        ad = np.ascontiguousarray(inputs.adjusted_days,dtype=np.int32)
        av = np.ascontiguousarray(inputs.adjusted_values,dtype=np.float64)
        with self._lock:
            self._ensure_open()
            if count:
                code = self._prices(_ptr(symbols,_I32),_ptr(days,_I32),_ptr(columns,_U8),
                    _ptr(forwards,_U8),count,len(inputs.symbols),_ptr(ro,_I64),_ptr(rd,_I32),
                    _ptr(rv,_F64),len(rd),_ptr(ao,_I64),_ptr(ad,_I32),_ptr(av,_F64),len(ad),
                    _ptr(actual,_I32),_ptr(values,_F64))
                if code:
                    raise RuntimeError('Rust price search failed.')
        return actual,values

    def calculate(self, matrix):
        matrix = np.ascontiguousarray(matrix,dtype=np.float64)
        if matrix.ndim != 2 or matrix.shape[1] != len(self.policy.input_names):
            raise ValueError('Rust factor input matrix has an incompatible shape.')
        output = np.empty((len(matrix),len(self.policy.output_names)),dtype=np.float64)
        with self._lock:
            self._ensure_open()
            if len(matrix):
                code = self._factors(_ptr(matrix,_F64),len(matrix),matrix.shape[1],
                    _ptr(output,_F64),output.shape[1],self.threads)
                if code:
                    raise RuntimeError('Rust factor execution failed.')
        return output

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError('Rust candidate library is closed.')

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._library is not None:
                import _ctypes
                handle = self._library._handle
                self._reports = self._prices = self._factors = None
                if handle:
                    if os.name == 'nt':
                        _ctypes.FreeLibrary(handle)
                    else:
                        _ctypes.dlclose(handle)
                    self._library._handle = 0
                self._library = None


class RustExecutor(PythonExecutor):
    """Use the common adapter with native report, price and factor primitives."""

    def __init__(self, inputs, policy=None, limits=None):
        super().__init__(inputs, policy=policy, limits=limits)
        self.kernel = NativeKernel(inputs, policy or inputs.policy, dict(limits or {}))
        self.stats.update(self.kernel.stats)
        self.stats['backend'] = 'rust'
        self.stats['coverage'] = 'Native temporal searches and source-derived factors; common candidate guards/assembly.'

    def select_reports(self, entry_ordinals):
        return self.kernel.reports(entry_ordinals)

    def resolve(self, symbol_ids, days, columns, forwards):
        return self.kernel.resolve(symbol_ids,days,columns,forwards)

    def calculate(self, matrix):
        return self.kernel.calculate(matrix)

    def close(self):
        if hasattr(self, 'kernel'):
            self.kernel.close()
        super().close()


def attach(inputs, policy=None, limits=None):
    """Attach a source-bound native candidate executor; inputs remain borrowed."""
    return RustExecutor(inputs, policy=policy, limits=limits)
