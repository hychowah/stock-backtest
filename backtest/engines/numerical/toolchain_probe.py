"""Fixed contained setup probe. No financial inputs or application imports."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event,Thread
import time

ROOT=Path(__file__).absolute().parents[3]


def _run(command,stop,output):
    child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT)
    try:
        while child.poll() is None:
            if stop.wait(.025):raise InterruptedError('Native setup owner ended.')
        if child.returncode:raise RuntimeError('Native setup compiler failed.')
    finally:
        if child.poll() is None:
            child.terminate()
            try:child.wait(timeout=1.)
            except subprocess.TimeoutExpired:child.kill();child.wait()


def _watch_parent(stop,finished):
    import select,signal
    while not finished.is_set():
        readable,_,_=select.select([sys.stdin.fileno()],[],[],.05)
        if readable and not os.read(sys.stdin.fileno(),1):
            stop.set()
            if not finished.wait(30.):os.killpg(os.getpgrp(),signal.SIGKILL)
            return

def main():
    if sys.stdin.readline()!='GO\n':return
    import importlib.util as _bootstrap_imports
    _bootstrap_spec = _bootstrap_imports.spec_from_file_location('_backtest_source_owner', ROOT/'website'/'runtime_access.py')
    runtime_access = _bootstrap_imports.module_from_spec(_bootstrap_spec)
    sys.modules[_bootstrap_spec.name] = runtime_access
    _bootstrap_spec.loader.exec_module(runtime_access)
    with runtime_access.ownership(ROOT,timeout=0):
        sys.path.insert(0,str(ROOT))
        stop,finished=Event(),Event()
        if os.name!='nt':Thread(target=_watch_parent,args=(stop,finished),daemon=True).start()
        from backtest.runtime.process_owner import close_own_session
        try:_probe(stop)
        finally:
            # Retain this child's own source guard until ordinary descendants
            # are gone, including when its installer abruptly disappears.
            while True:
                try:close_own_session(timeout=1.);break
                except (TimeoutError,KeyboardInterrupt):pass
            finished.set()


def _probe(stop):
    value=json.loads(Path(sys.argv[1]).read_bytes());descriptor=value['descriptor'];scratch=Path(value['scratch'])
    source=scratch/'probe.rs';source.write_text('#[no_mangle] pub extern "C" fn numerical_setup_probe()->i32 { 19 }\n')
    library=scratch/('probe.dll' if os.name=='nt' else 'probe.so')
    with (scratch/'version.txt').open('w+b') as output:
        _run([descriptor['compiler'],'-vV'],stop,output)
        output.seek(0);version=output.read(1024*1024+1).decode('utf8')
        if len(version)>1024*1024:raise ValueError('Native compiler metadata exceeds its bound.')
    with (scratch/'compiler.log').open('wb') as log:
        _run([descriptor['compiler'],'--edition=2021','--crate-type','cdylib','-C','panic=abort',
            '-C','linker='+str(Path(descriptor['directory'])/descriptor['linker']['path']),str(source),'-o',str(library)],
            stop,log)
    if stop.is_set():raise InterruptedError('Native setup owner ended.')
    handle=ctypes.CDLL(str(library));handle.numerical_setup_probe.restype=ctypes.c_int32
    answer=handle.numerical_setup_probe();del handle.numerical_setup_probe
    import _ctypes
    if os.name=='nt':_ctypes.FreeLibrary(handle._handle)
    else:_ctypes.dlclose(handle._handle)
    handle._handle=0
    moved=library.with_name('released'+library.suffix);library.rename(moved);moved.unlink()
    (scratch/'verified.json').write_text(json.dumps(dict(answer=answer,library_closed=True,version=version)))

if __name__=='__main__':main()
