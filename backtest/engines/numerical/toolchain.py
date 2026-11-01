"""Comparison-only verified Rust compiler environment; no application imports.

Inspection is offline. Setup publishes a usable installation only after contained
compile/load/close verification. Neither normal application engine requires it.
Every compiler, target and linker component lives in one immutable installation.
Only the operating system's standard loader/runtime remains external.
"""
from backtest.runtime import backtest_control
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import uuid

ROOT=Path(__file__).absolute().parents[3]
_PENDING={}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def sha(path):
    from backtest.runtime import backtest_control as backtest_control
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):
            backtest_control.checkpoint();value.update(part)
    return value.hexdigest()


def location(root):return Path(root)/'data/numerical-native'


def _relative(value):
    path=Path(value)
    if not isinstance(value,str) or not value or path.is_absolute() or '..' in path.parts or path.as_posix()!=value:
        raise ValueError('Invalid native component name.')
    return path


def _files(directory,files,*,complete=False):
    if not isinstance(files,dict) or not files:raise ValueError('Native component inventory is empty.')
    verified={}
    for name,expected in files.items():
        path=directory/_relative(name)
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory.resolve()):
            raise ImportError('Native component content differs from its installation receipt.')
        before=path.stat()
        identity=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
        key=identity(before) if before.st_ino else None
        actual=verified.get(key) if key is not None else None
        if actual is None:actual=sha(path)
        if actual!=expected or identity(path.stat())!=identity(before):
            raise ImportError('Native component content differs from its installation receipt.')
        if key is not None:verified[key]=actual
    if complete:
        actual={path.relative_to(directory).as_posix() for path in directory.rglob('*') if path.is_file()}
        if actual!=set(files):raise ImportError('Native installation inventory differs.')


def _requirements(value):
    """Supported x86-64 Rust environment; no ambient component discovery."""
    target='x86_64-pc-windows-msvc' if os.name=='nt' else 'x86_64-unknown-linux-gnu'
    compiler='bin/rustc.exe' if os.name=='nt' else 'bin/rustc'
    if (value['schema']!=2 or value['platform']!=sys.platform or value['machine']!=platform.machine().lower()
            or value['machine'] not in ('x86_64','amd64') or value['target']!=target or value['compiler']!=compiler):
        raise ImportError('Native installation targets an unsupported Python platform.')
    files=value['files'];names=set(files);linker=value['linker']
    if set(linker)!={'path','environment'} or _relative(linker['path']).as_posix() not in names:
        raise ValueError('Missing qualified native linker.')
    if compiler not in names or not value['provenance']:raise ValueError('Missing native compiler provenance.')
    for prefix in ('libstd-','libcore-','liballoc-','libcompiler_builtins-','libpanic_abort-'):
        for extension in ('.rlib','.rmeta'):
            if not any(name.startswith('lib/rustlib/'+target+'/lib/'+prefix) and name.endswith(extension) for name in names):
                raise ImportError('Native target libraries or metadata are incomplete.')
    runtime=('bin/rustc_driver-', '.dll') if os.name=='nt' else ('lib/librustc_driver-', '.so')
    if not any(name.startswith(runtime[0]) and name.endswith(runtime[1]) for name in names):
        raise ImportError('Native compiler runtime is incomplete.')
    if os.name!='nt' and not any(name.startswith('lib/libLLVM-') and '.so' in name for name in names):
        raise ImportError('Native compiler LLVM runtime is incomplete.')
    required=('linker/bin/link.exe','linker/lib/vcruntime.lib','linker/lib/ucrt.lib','linker/lib/kernel32.lib') if os.name=='nt' else (
        'linker/bin/x86_64-conda-linux-gnu-gcc','linker/x86_64-conda-linux-gnu/bin/ld')
    comparable={name.lower() for name in names} if os.name=='nt' else names
    if not all(name in comparable for name in required):raise ImportError('Native linker or target runtime inputs are incomplete.')
    allowed={'PATH','LIB'} if os.name=='nt' else {'PATH'}
    if set(linker['environment'])!=allowed:raise ValueError('Unexpected native dependency search environment.')
    for paths in linker['environment'].values():
        if not isinstance(paths,list) or not paths:raise ValueError('Missing managed native search paths.')
        for name in paths:
            relative=_relative(name).as_posix()
            if not relative.startswith('linker/') or not any(part.startswith(relative+'/') for part in names):
                raise ValueError('Native search path is outside the managed inventory.')


def environment(descriptor):
    """Use only qualified managed search paths and explicit OS baseline paths."""
    directory=Path(descriptor['directory'])
    result={name:os.pathsep.join(str(directory/_relative(path)) for path in paths)
            for name,paths in descriptor['linker']['environment'].items()}
    if os.name=='nt':
        system=os.environ.get('SystemRoot')
        if not system:raise ImportError('Windows system directory is unavailable.')
        result.update(SystemRoot=system,WINDIR=system)
        result['PATH']+=os.pathsep+str(Path(system)/'System32')
    else:result.update(LANG='C.UTF-8',LC_ALL='C.UTF-8')
    for name in ('TEMP','TMP','TMPDIR'):
        if name in os.environ:result[name]=os.environ[name]
    return result


def _descriptor(directory,receipt):
    return dict(compiler=str(directory/_relative(receipt['compiler'])),
        linker=deepcopy(receipt['linker']),version=receipt.get('version'),target=receipt['target'],
        signature=digest(receipt),receipt=deepcopy(receipt),directory=str(directory))


def inspect_toolchain(root=None):
    """Content-verify the complete managed installation without native imports."""
    base=location(ROOT if root is None else root)
    try:
        receipt=json.loads((base/'installation.json').read_bytes());_requirements(receipt)
        directory=base/'toolchains'/_relative(receipt['directory'])
        _files(directory,receipt['files'],complete=True)
        if (not receipt['probe']['closed'] or not receipt['probe']['library_closed']
                or 'host: '+receipt['target']+'\n' not in receipt['version']):
            raise ImportError('Native installation has no verified contained probe.')
        return _descriptor(directory,receipt)
    except (OSError,ValueError,KeyError,TypeError):
        raise ImportError('Managed Rust installation is unavailable or invalid. Run offline native setup.') from None


def verify_build(root,record,installation):
    """Verify prepared build evidence without loading a native library."""
    if record['identity']['fields']['native']['installation']!=installation:
        raise ImportError('Prepared native build belongs to a different installation.')
    directory=location(root)/'builds'/_relative(record['directory'])
    library='kernel.dll' if os.name=='nt' else 'kernel.so'
    _files(directory,{'kernel.rs':record['source_sha256'],library:record['library_sha256']})


class SetupClosureError(TimeoutError):
    def __init__(self,installation,primary=None):
        super().__init__('Native setup closure is unconfirmed. Retain source ownership and retry close.')
        self.installation=installation;self.primary_error=primary


class Installation:
    """Own probe, immutable files and receipt intent through confirmed closure.

    Caller holds source ownership through close, including retryable failures.
    A current installation is never removed, even if later verification fails.
    """
    def __init__(self,root,components,manifest,python):
        self.root=Path(root).absolute();self.components=Path(components).absolute()
        self.manifest=deepcopy(manifest);self.python=str(python or sys.executable)
        self.base=location(self.root);self.directory=self.base/'toolchains'/('install-'+uuid.uuid4().hex)
        self.scratch=self.base/('setup-'+uuid.uuid4().hex)
        self.owner=None;self.published=False;self.closed=False;self.verified=False
        self.lock=None
        _PENDING[id(self)]=self

    def run(self):
        from backtest.runtime.process_owner import OwnedProcess
        from backtest.engines.numerical.runtime import write_payload
        from backtest.runtime.cache_access import WorkspaceAccess
        value=self.manifest
        try:
            self.lock=WorkspaceAccess(self.base/'setup.lock').hold(timeout=120)
            self.lock.__enter__()
            if set(value)!={'schema','platform','machine','compiler','target','files','linker','provenance'}:
                raise ValueError('Invalid qualified native component manifest.')
            _requirements(value);_files(self.components,value['files'])
            self.directory.mkdir(parents=True)
            copied={}
            for name in value['files']:
                target=self.directory/_relative(name);target.parent.mkdir(parents=True,exist_ok=True)
                checksum=value['files'][name]
                # Flattened offline bundles can contain many aliases for one
                # library. Hard-link equal verified bytes only WITHIN this new
                # immutable installation; never borrow a source component inode.
                previous=copied.get(checksum)
                if previous is not None:
                    try:os.link(previous,target)
                    except OSError:shutil.copy2(self.components/name,target)
                else:shutil.copy2(self.components/name,target)
                copied[checksum]=target
            _files(self.directory,value['files'],complete=True)
            descriptor=_descriptor(self.directory,value)
            self.scratch.mkdir();request=self.scratch/'request.json'
            request.write_text(json.dumps(dict(descriptor=descriptor,scratch=str(self.scratch))))
            try:
                self.owner=OwnedProcess([self.python,'-I','-B',str(ROOT/'backtest/engines/numerical/toolchain_probe.py'),str(request)],env=environment(descriptor))
            except BaseException as error:
                self.owner=getattr(error,'owned_process',None);raise
            # Keep the parent pipe open through the probe's lifetime. POSIX
            # setup observes its EOF; Windows also has kill-on-close Job ownership.
            self.owner.process.stdin.write('GO\n');self.owner.process.stdin.flush()
            self.owner.process.wait(timeout=120)
            self.owner.close()
            if self.owner.process.returncode or not (self.scratch/'verified.json').is_file():
                raise ImportError('Contained native compile/load/close probe failed.')
            probe=json.loads((self.scratch/'verified.json').read_bytes())
            if probe.get('answer')!=19 or not probe.get('library_closed'):
                raise ImportError('Native setup ABI probe differs.')
            version=probe['version']
            if 'host: '+value['target']+'\n' not in version:raise ValueError('Native compiler target differs.')
            probe['closed']=self.owner.closed;self.verified=True
            receipt=dict(value,directory=self.directory.name,version=version,probe=probe)
            write_payload(self.base/'installation.json',receipt,4*1024**2)
            self.published=True
            result=inspect_toolchain(self.root)
        except BaseException as primary:
            try:self.close()
            except BaseException:raise SetupClosureError(self,primary) from primary
            raise
        self.close()
        return result

    def close(self):
        if self.closed:return
        if self.owner is not None:
            try:self.owner.close()
            except BaseException:raise SetupClosureError(self) from None
        # Publication may have completed just before an interrupt prevented
        # the in-memory flag update. Unknown durable state is conservative.
        pointer=self.base/'installation.json'
        if not self.published and pointer.exists():
            try:self.published=json.loads(pointer.read_bytes()).get('directory')==self.directory.name
            except (OSError,ValueError,AttributeError):self.published=True
        if not self.published and self.directory.exists():shutil.rmtree(self.directory)
        if self.verified and self.scratch.exists():shutil.rmtree(self.scratch)
        if self.lock is not None:
            self.lock.__exit__(None,None,None);self.lock=None
        self.closed=True;_PENDING.pop(id(self),None)


def setup_toolchain(root,components,manifest,*,python=None):
    """Explicit offline setup; caller retains source ownership through closure."""
    return Installation(root,components,manifest,python).run()
