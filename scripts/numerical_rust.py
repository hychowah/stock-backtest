"""Complete source-derived Rust candidate behind a checked synchronous C ABI.

This is an internal comparison configuration. Shared Python planning, adjusted
query preparation, mechanical encoding, SQL selection and reducer remain timed
work. It never falls back to source guards or a scalar numerical provider.

The caller owns source/cache and input mappings through closure. Compiler
children inherit the existing runtime process containment. Libraries use unique
immutable paths; no pointers survive a call. The bridge validates arrays, not
arbitrary hostile addresses supplied outside Python's owned allocations.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from threading import RLock
import time

import numpy as np
import backtest_control
from numerical_books import PythonExecutor
import numerical_candidates as candidates
from numerical_identity import compiler_identity
from numerical_matrix import CompiledMatrix
import numerical_rust_codegen as codegen

ABI=codegen.ABI
FLAGS=('--edition=2021','-C','opt-level=3','-C','panic=abort','-C','target-cpu=native')


class Buffer(ctypes.Structure):
    _fields_=[('pointer',ctypes.c_void_p),('length',ctypes.c_size_t)]


def _buffer(value):return Buffer(value.ctypes.data,value.size)


def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compiler():
    value=os.environ.get('BACKTEST_RUSTC') or shutil.which('rustc')
    if not value:raise ImportError('The Rust comparison requires an explicitly available native compiler.')
    path=Path(value).absolute()
    if not path.is_file() or os.name!='nt' and path.suffix.lower()=='.exe':
        raise ImportError('The Rust comparison requires a compiler for this Python platform.')
    return path


def _run_compiler(command):
    """Cancellable metadata/build child within the caller's process domain."""
    backtest_control.checkpoint()
    with tempfile.TemporaryFile() as output:
        child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT)
        try:
            while child.poll() is None:
                time.sleep(.025)
                backtest_control.checkpoint()
        except BaseException:
            try:child.terminate()
            finally:child.wait()
            raise
        if child.returncode:
            raise RuntimeError('Rust compiler operation failed (exit '+str(child.returncode)+').')
        backtest_control.checkpoint()
        output.seek(0)
        result=output.read(1024*1024+1)
        if len(result)>1024*1024:raise ValueError('Rust compiler output exceeds its diagnostic bound.')
        return result


def identity(inputs,threads):
    """Predict exact recovery identity without building or loading a provider."""
    path=compiler()
    version=_run_compiler([str(path),'-vV']).decode('utf-8')
    generated=codegen.source(inputs.policy)
    fields=compiler_identity(inputs,threads,decisions=inputs.policy.decisions)['fields']
    linker=os.environ.get('BACKTEST_RUST_LINKER')
    link_identity=None
    if linker:
        located=shutil.which(linker) or linker
        if not Path(located).is_file():raise ImportError('Configured Rust linker is unavailable.')
        link_identity=dict(sha256=_sha(located),name=Path(located).name)
    fields['native']=dict(backend='rust',abi=ABI,layout=candidates.signature(inputs.policy),
        generated_source_sha256=hashlib.sha256(generated.encode()).hexdigest(),
        compiler_version=version.strip(),compiler_sha256=_sha(path),flags=list(FLAGS),
        linker=link_identity,pointer_bits=ctypes.sizeof(ctypes.c_void_p)*8,
        buffer_size=ctypes.sizeof(Buffer),buffer_alignment=ctypes.alignment(Buffer),
        reassociation=False,fastmath=False)
    signature=hashlib.sha256(json.dumps(fields,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return dict(signature=signature,fields=fields)


def _build(inputs,expected):
    """Publish a completed immutable build once; workers verify and reuse it.

    Trial readiness is serial at present. A private unique build directory also
    makes concurrent independent runtimes safe without replacing a loaded DLL.
    The manifest is an atomic pointer to immutable bytes; broken bytes fail and
    are never silently recompiled under the existing manifest.
    """
    root=Path(os.environ.get('BACKTEST_RUST_BUILDS') or Path(inputs.s.r.ROOT)/'tmp/numerical-rust')
    root.mkdir(parents=True,exist_ok=True)
    manifest=root/(expected['signature']+'.json')
    def verify():
        saved=json.loads(manifest.read_text())
        directory=root/saved['directory']
        if directory.parent!=root or directory.name!=saved['directory']:raise ValueError('Invalid native build path.')
        library=directory/('kernel.dll' if os.name=='nt' else 'kernel.so')
        if (saved['identity']!=expected
                or saved['source_sha256']!=expected['fields']['native']['generated_source_sha256']
                or saved['source_sha256']!=_sha(directory/'kernel.rs')
                or saved['library_sha256']!=_sha(library)):
            raise ValueError('Native build identity or artifact integrity differs.')
        return library,saved
    if manifest.exists():
        path,record=verify();return path,dict(record,build_reused=True,build_seconds=0.)
    generated=codegen.source(inputs.policy)
    began=time.perf_counter()
    # The directory remains immutable after publication. Failed builds are
    # task-owned and removed by TemporaryDirectory before the error escapes.
    with tempfile.TemporaryDirectory(prefix='build-',dir=root) as temporary:
        directory=Path(temporary);source=directory/'kernel.rs';source.write_bytes(generated.encode('utf-8'))
        library=directory/('kernel.dll' if os.name=='nt' else 'kernel.so')
        command=[str(compiler()),'--crate-name','numerical_candidate','--crate-type','cdylib',*FLAGS]
        linker=os.environ.get('BACKTEST_RUST_LINKER')
        if linker:command+=['-C','linker='+linker]
        command += [str(source),'-o',str(library)]
        backtest_control.checkpoint()
        # No historical setup deadline becomes a calculation capacity limit.
        # Runtime initialization cancellation is handled cooperatively while
        # draining this ordinary inherited compiler child.
        try:_run_compiler(command)
        except RuntimeError as error:
            raise RuntimeError('Rust comparison compilation failed.') from error
        backtest_control.checkpoint()
        # Verify that source/compiler configuration did not change during build.
        if identity(inputs,expected['fields']['threads'])!=expected:
            raise ValueError('Native compiler identity changed during build.')
        source_hash=_sha(source)
        if source_hash!=expected['fields']['native']['generated_source_sha256']:
            raise ValueError('Native generated source integrity differs before publication.')
        immutable=root/('library-'+expected['signature'][:16]+'-'+directory.name)
        record=dict(identity=expected,directory=immutable.name,
            source_sha256=source_hash,library_sha256=_sha(library),
            artifact_bytes=sum(p.stat().st_size for p in directory.iterdir()),build_seconds=time.perf_counter()-began)
        directory.rename(immutable)
        fd,name=tempfile.mkstemp(prefix='receipt-',suffix='.json',dir=root)
        try:
            with os.fdopen(fd,'w') as handle:json.dump(record,handle,sort_keys=True)
            os.replace(name,manifest)
        finally:Path(name).unlink(missing_ok=True)
    path,saved=verify()
    return path,dict(saved,build_reused=False)


class NativeKernel:
    def __init__(self,inputs,expected,limits):
        self.inputs=inputs;self.policy=inputs.policy;self.identity=expected
        self.threads=limits.get('threads',1);self.chunk_rows=limits.get('chunk_rows',1024)
        if any(type(v) is not int or v<=0 for v in (self.threads,self.chunk_rows)):
            raise ValueError('Invalid Rust execution configuration.')
        self._lock=RLock();self._library=None;self.closed=False
        self.stats=dict(native_chunks=0)
        library,record=_build(inputs,expected)
        self.stats.update(record)
        began=time.perf_counter()
        try:
            self._library=ctypes.CDLL(str(library))
            self._library.candidate_abi.argtypes=[];self._library.candidate_abi.restype=ctypes.c_int32
            if self._library.candidate_abi()!=ABI:raise ValueError('Native ABI version differs.')
            signatures=dict(candidate_reports=[ctypes.c_size_t]*3+[ctypes.c_int32]+[Buffer]*6,
                candidate_prices=[ctypes.c_size_t]*2+[Buffer]*12,
                candidate_factors=[ctypes.c_size_t]*2+[Buffer]*2,
                candidate_materialize=[ctypes.c_size_t]*2+[ctypes.c_int64]+[Buffer]*11)
            for name,arguments in signatures.items():
                function=getattr(self._library,name);function.argtypes=arguments;function.restype=ctypes.c_int32
        except BaseException:self.close();raise
        self.stats['library_attach_seconds']=time.perf_counter()-began

    def _call(self,name,scalars,inputs,outputs):
        types=dict(candidate_reports=[np.int32,np.int64,np.int32,np.int32,np.int32,np.int32],
            candidate_prices=[np.int32,np.int32,np.int8,np.bool_,np.int64,np.int32,np.float64,np.int64,np.int32,np.float64,np.int32,np.float64],
            candidate_factors=[np.float64,np.float64],
            candidate_materialize=[np.int32,np.float64,np.float64,np.int32,np.float64,np.uint8,np.int64,np.int32,np.float64,np.uint8,np.int64])
        scalar_types=dict(candidate_reports=('size','size','size','i32'),candidate_prices=('size','size'),
            candidate_factors=('size','size'),candidate_materialize=('size','size','i64'))
        if name not in scalar_types or len(scalars)!=len(scalar_types[name]):raise ValueError('Invalid native scalar layout.')
        for value,kind in zip(scalars,scalar_types[name],strict=True):
            low,high=(0,2**(ctypes.sizeof(ctypes.c_size_t)*8)-1) if kind=='size' else (-2**31,2**31-1) if kind=='i32' else (-2**63,2**63-1)
            if type(value) is not int or not low<=value<=high:raise ValueError('Native scalar range differs.')
        all_arrays=(*inputs,*outputs)
        if name not in types or len(all_arrays)!=len(types[name]):raise ValueError('Invalid native call layout.')
        for index,(value,dtype) in enumerate(zip(all_arrays,types[name],strict=True)):
            if not isinstance(value,np.ndarray):raise ValueError('Invalid native allocation.')
            candidates.array(value,dtype,value.shape,'call',writable=index>=len(inputs))
        candidates.disjoint(inputs,outputs)
        with self._lock:
            if self.closed or getattr(self.inputs,'closed',False):raise ValueError('Rust kernel or inputs are closed.')
            result=getattr(self._library,name)(*scalars,*(_buffer(v) for v in (*inputs,*outputs)))
            if result:raise ValueError('Native buffer contract rejected ('+str(result)+').')
            self.stats['native_chunks']+=1

    @staticmethod
    def _vector(value,dtype,name):
        if not isinstance(value,np.ndarray) or value.ndim!=1:raise ValueError('Invalid native '+name+' dimensions.')
        return candidates.array(value,dtype,(len(value),),name)

    def reports(self,entries):
        self._vector(entries,np.int32,'report entries')
        if np.any(entries<1) or np.any(entries>3652059):raise ValueError('Invalid native report days.')
        results=[];inputs=self.inputs
        for pool in ('cached','legacy'):
            off,ids,known,fiscal=(inputs.pool_offsets[pool],inputs.pool_report_ids[pool],inputs.pool_known[pool],inputs.pool_fiscal[pool])
            self._vector(off,np.int64,'report offsets');self._vector(ids,np.int32,'report IDs')
            candidates.array(off,np.int64,(len(inputs.symbols)+1,),'report offsets')
            for values in (known,fiscal):candidates.array(values,np.int32,(len(ids),),'report dates')
            if off[0]!=0 or off[-1]!=len(ids) or np.any(np.diff(off)<0) or np.any(ids<0) or np.any(ids>=len(inputs.report_fiscal)):
                raise ValueError('Invalid native report ranges.')
            output=np.empty((len(entries),len(inputs.symbols)),dtype=np.int32)
            for first in range(0,len(entries),self.chunk_rows):
                backtest_control.checkpoint();part=entries[first:first+self.chunk_rows]
                self._call('candidate_reports',(len(part),len(inputs.symbols),len(inputs.report_fiscal),inputs.s.financial_books.run.MAX_AGE.days),
                    [part,off,ids,known,fiscal],[output[first:first+len(part)]])
            results.append(output)
        return tuple(results)

    def resolve(self,symbols,days,columns,forwards):
        for value,dtype,name in ((symbols,np.int32,'symbols'),(days,np.int32,'days'),(columns,np.int8,'columns'),(forwards,np.bool_,'directions')):
            self._vector(value,dtype,name)
        if (not len(symbols)==len(days)==len(columns)==len(forwards) or np.any(symbols < -1)
                or np.any(symbols>=len(self.inputs.symbols)) or np.any(days<1) or np.any(days>3652059)
                or np.any(columns<0) or np.any(columns>1)):
            raise ValueError('Invalid native temporal query values or lengths.')
        histories=[]
        for prefix in ('raw','adjusted'):
            off,history,prices=(getattr(self.inputs,prefix+'_'+part) for part in ('offsets','days','values'))
            candidates.array(off,np.int64,(len(self.inputs.symbols)+1,),'price offsets')
            self._vector(history,np.int32,'price days');candidates.array(prices,np.float64,(len(history),),'prices')
            if off[0]!=0 or off[-1]!=len(history) or np.any(np.diff(off)<0):raise ValueError('Invalid native price ranges.')
            histories.extend((off,history,prices))
        actual=np.zeros(len(days),dtype=np.int32);values=np.full(len(days),np.nan)
        for first in range(0,len(days),self.chunk_rows):
            backtest_control.checkpoint();part=slice(first,first+self.chunk_rows)
            self._call('candidate_prices',(len(days[part]),len(self.inputs.symbols)),
                [symbols[part],days[part],columns[part],forwards[part],*histories],[actual[part],values[part]])
        return actual,values

    def calculate(self,matrix):
        candidates.array(matrix,np.float64,(len(matrix),len(self.policy.input_names)),'factor inputs')
        output=np.empty((len(matrix),len(self.policy.output_names)))
        self._call('candidate_factors',(len(matrix),self.threads),[matrix],[output])
        return output

    def materialize(self,days,prices,numeric,meta,matrix,requested,first=0):
        count=len(numeric);policy=self.policy
        for value,dtype,shape,name in ((days,np.int32,(count,7),'lookup days'),(prices,np.float64,(count,7),'lookup prices'),
            (numeric,np.float64,(count,len(policy.output_names)),'numerical outputs'),(meta,np.int32,(count,6),'metadata'),
            (matrix,np.float64,(count,len(policy.input_names)),'numerical inputs'),(requested,np.uint8,(len(policy.filter_order),),'requested fields')):
            candidates.array(value,dtype,shape,name)
        if type(first) is not int or not 0<=first<=2**63-1-count:raise ValueError('Invalid native candidate index.')
        if (np.any(days<0) or np.any(days>3652059) or np.any(meta[:,:3]<1) or np.any(meta[:,:3]>3652059)
                or np.any(meta[:,3:5]<1) or np.any(meta[:,3:5]>9999) or np.any(meta[:,5]<0) or np.any(meta[:,5]>1)
                or np.any(requested>1)):
            raise ValueError('Invalid native candidate representation.')
        batch=candidates.CandidateBatch.empty(count,policy);accepted=np.zeros(1,dtype=np.int64)
        self._call('candidate_materialize',(count,self.threads,first),[days,prices,numeric,meta,matrix,requested],
            [batch.identities,batch.dates,batch.values,batch.validity,accepted])
        batch.count=int(accepted[0]);return batch

    def close(self):
        with self._lock:
            if self.closed:return
            if self._library is not None:
                import _ctypes
                library=self._library
                # ctypes caches symbol objects on the CDLL. Drop every callable
                # before unloading; the lock excludes all synchronous borrowers.
                for name in ('candidate_abi','candidate_reports','candidate_prices','candidate_factors','candidate_materialize'):
                    library.__dict__.pop(name,None)
                if os.name=='nt':_ctypes.FreeLibrary(library._handle)
                else:_ctypes.dlclose(library._handle)
                library._handle=0;self._library=None
            self.inputs=None;self.closed=True


class _Factors:
    def __init__(self,kernel):self.kernel=kernel
    @property
    def signatures(self):return (self.kernel.identity['signature'],ABI)
    def __call__(self,matrix):return self.kernel.calculate(matrix)


class RustExecutor(PythonExecutor):
    def __init__(self,inputs,policy=None,limits=None):
        limits=dict(limits or {});limits.setdefault('candidate_assembly','compiled')
        if limits['candidate_assembly']!='compiled':raise ValueError('Rust comparison requires compiled candidates.')
        super().__init__(inputs,policy,limits)
        self.kernel=self._calculate=None
        try:
            self.compiler=identity(inputs,self.limits.get('threads',1))
            self.kernel=NativeKernel(inputs,self.compiler,self.limits)
            self._calculate=CompiledMatrix(self.policy,(inputs.signature,self.compiler['signature']),
                cache_bytes=self.limits.get('matrix_cache_bytes',16*1024**2),workspace_bytes=self.limits.get('workspace_bytes',64*1024**2),
                chunk_rows=self.limits.get('chunk_rows',1024),kernel=_Factors(self.kernel))
            self.stats.update(backend='rust',threads=self.kernel.threads,fastmath=False,compiler_cache=False,
                coverage='Native temporal/factors/financial decisions/typed candidate materialization; common planning/encoding/SQL/reducer.',
                native_build=self.kernel.stats)
        except BaseException:self.close();raise

    def select_reports(self,entries):return self.kernel.reports(entries)
    def resolve(self,symbols,days,columns,forwards):return self.kernel.resolve(symbols,days,columns,forwards)
    def calculate(self,matrix):return self._calculate(matrix)

    def assemble_candidates(self,books,rows,targets,lookup_days,lookup_values,matrix,numeric,ranks,needed,results):
        meta=candidates.metadata(self.inputs,books,rows)
        requested=np.asarray([field in needed for field in self.policy.filter_order],dtype=np.uint8)
        batch=candidates.CandidateBatch.empty(len(rows),self.policy);began=time.perf_counter()
        for first in range(0,len(rows),self.kernel.chunk_rows):
            backtest_control.checkpoint();part=slice(first,first+self.kernel.chunk_rows)
            produced=self.kernel.materialize(lookup_days[part],lookup_values[part],numeric[part],meta[part],matrix[part],requested,first)
            for name in ('identities','dates','values','validity'):getattr(batch,name)[part]=getattr(produced,name)
            batch.count+=produced.count
        self._time('decision_seconds',began);began=time.perf_counter()
        accepted=candidates.encode(batch,self.inputs,self.policy,rows,ranks,results)
        self._time('encoding_seconds',began);return accepted

    def close(self):
        if getattr(self,'_calculate',None) is not None:self._calculate.close()
        if getattr(self,'kernel',None) is not None:self.kernel.close()
        self._calculate=self.kernel=None
        self.inputs=self.policy=None
        super().close()


def attach(inputs,policy=None,limits=None):return RustExecutor(inputs,policy,limits)
