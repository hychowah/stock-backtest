"""Copy saved inputs for independent preparation; never copy derived books.

Copy the active saved inputs and canonical report into a new independent root.
Return only after exact-content verification and unchanged-source checks.
Existing runtime ownership or live intent defers the operation. A directory
without its completion marker is unusable. Offline exclusion preserves an
already running server by refusing admission. New startup can wait or time out;
this is not live observation or a live-priority handoff.
"""
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import date
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import traceback
from threading import Event

SOURCE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SOURCE/'website'), str(SOURCE/'scripts')]
import cache_access
import runtime_access

FILES = ('raw/universe.json', 'raw/metrics.jsonl', 'raw/spy-div.json',
         'raw/treasury.json', 'raw/download-coverage.json', 'results/summary-exits.txt')
DIRECTORIES = ('raw/px', 'raw/financial-inputs')
BUFFER = 1024*1024
MAX_BYTES = 6*1024**3
MAX_FILES = 100000
MANIFEST_BYTES = 16*1024**2
IO_WORKERS = 4
POLL_SECONDS = .05
# Only this Git-bound older protocol has native peer-lock qualification.
REVISION = 'd877cb40faf0c643e4c4e386e87b6074e8cca5d2'
OWNERSHIP_SOURCES = {
    'scripts/cache_access.py': '5dc7463285d6ae1d0dba58fdf901f832ccc59714e4ff676d108e05d9247f9713',
    'website/runtime_access.py': 'c1e65debe45102ac5f32b63da104cda141918a9bd0c5a136ea2b8e766e8b12eb',
}


class CopyError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class Deferred(CopyError):
    pass


def _plain(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise CopyError('linked_path')
    return info


def _ancestors(path):
    for parent in reversed((path, *path.parents)):
        if not stat.S_ISDIR(_plain(parent).st_mode):
            raise CopyError('not_directory')


def _hash(path, check):
    check()
    if not stat.S_ISREG(_plain(path).st_mode):
        raise CopyError('unsupported_file_type')
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(BUFFER):
            check(); value.update(block)
    check()
    return value.hexdigest()


def _pending(root):
    if any((root/'data'/name).exists() for name in
           ('deployment.pending.json', 'research.sqlite.publication.json')):
        raise Deferred('pending_publication')
    for name in ('research.sqlite', 'schedules.sqlite'):
        if any((root/'data'/(name+suffix)).exists() for suffix in ('-wal', '-shm', '-journal')):
            raise Deferred('database_sidecar')


def _binding(root, check):
    path = root/'data/deployment.json'
    _plain(path)
    data = path.read_bytes()
    record = json.loads(data)
    if record.get('commit') != REVISION:
        raise Deferred('unqualified_revision')
    for relative, expected in OWNERSHIP_SOURCES.items():
        _ancestors((root/relative).parent)
        _plain(root/relative)
        if record.get('files', {}).get(relative) != expected or _hash(root/relative, check) != expected:
            raise Deferred('unqualified_ownership_source')
    return dict(revision=REVISION, deployment_sha256=hashlib.sha256(data).hexdigest(),
                ownership_sources=dict(OWNERSHIP_SOURCES))


def _inventory(root, check):
    result = {}
    def add(path, info):
        if not stat.S_ISREG(info.st_mode):
            raise CopyError('unsupported_file_type')
        name = path.relative_to(root).as_posix()
        result[name] = dict(bytes=info.st_size, mtime_ns=info.st_mtime_ns)
        if len(result) > MAX_FILES:
            raise CopyError('file_limit')
    for relative in FILES:
        check(); path = root/relative; _ancestors(path.parent)
        add(path, _plain(path))
    for relative in DIRECTORIES:
        path = root/relative; _ancestors(path); pending = [path]
        while pending:
            check()
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    check(); info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                        raise CopyError('linked_path')
                    path = Path(entry.path)
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(path)
                    else:
                        add(path, info)
    return dict(sorted(result.items()))


def _allocation(path):
    if os.name != 'nt':
        return path.stat().st_blocks*512
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    class Standard(ctypes.Structure):
        _fields_ = [('allocation',ctypes.c_longlong),('end',ctypes.c_longlong),
                    ('links',wintypes.DWORD),('deleting',ctypes.c_ubyte),('directory',ctypes.c_ubyte)]
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
                       wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    query = kernel.GetFileInformationByHandleEx
    query.argtypes = [wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    query.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]; close.restype = wintypes.BOOL
    # Attribute-only, nonfollowing handle. GetCompressedFileSize reports logical
    # length for an uncompressed file; FileStandardInfo supplies allocation.
    handle = create(str(path),0x80,7,None,3,0x00200000,None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        value = Standard()
        if not query(handle,1,ctypes.byref(value),ctypes.sizeof(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        if value.directory or value.deleting or value.allocation < 0:
            raise CopyError('invalid_allocation')
        return value.allocation
    finally:
        if not close(handle):raise ctypes.WinError(ctypes.get_last_error())


def _allocation_unit(path):
    if os.name != 'nt':
        return os.statvfs(path).f_frsize
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    call = kernel.GetDiskFreeSpaceW
    call.argtypes = [wintypes.LPCWSTR] + [ctypes.POINTER(wintypes.DWORD)]*4
    call.restype = wintypes.BOOL
    sectors, sector_bytes, free, total = (wintypes.DWORD() for _ in range(4))
    if not call(path.anchor, ctypes.byref(sectors), ctypes.byref(sector_bytes),
                ctypes.byref(free), ctypes.byref(total)):
        raise ctypes.WinError(ctypes.get_last_error())
    return sectors.value*sector_bytes.value


def _parents(path):
    # Validate each existing ancestor before creating its child.
    if path.exists() or path.is_symlink():
        _ancestors(path)
    else:
        _parents(path.parent)
        path.mkdir()


def _copy_file(source, target, expected, check):
    """File tasks may write only their assigned destination file.

    They return evidence; they do not publish snapshot state.
    """
    check()
    value = hashlib.sha256(); total = 0
    with source.open('rb') as reader, target.open('xb') as writer:
        while block := reader.read(BUFFER):
            check(); total += len(block)
            if total > expected['bytes']:
                raise CopyError('source_changed')
            value.update(block); writer.write(block)
        if total != expected['bytes']:
            raise CopyError('source_changed')
        writer.flush(); os.fsync(writer.fileno())
    os.utime(target, ns=(expected['mtime_ns'], expected['mtime_ns']))
    # Readback belongs to the final verification pass. Opening each new file
    # here duplicated that complete check and dominated native small-file work.
    return value.hexdigest()


def _file_pass(items, work, accept, checkpoint):
    """Return only after every started task has closed its handles.

    A failed pass stops further submission and drains its workers before raising.
    Ownership and external callbacks remain with its caller.
    """
    stopped = Event()
    def check():
        if stopped.is_set():
            raise CopyError('file_pass_stopped')
    iterator = iter(items); pending = set()
    with ThreadPoolExecutor(max_workers=IO_WORKERS, thread_name_prefix='offline-input') as pool:
        try:
            def submit():
                checkpoint()
                try: item = next(iterator)
                except StopIteration: return False
                pending.add(pool.submit(work, item, check))
                return True
            for _ in range(IO_WORKERS):
                if not submit(): break
            while pending:
                checkpoint()
                done, remaining = wait(pending, timeout=POLL_SECONDS, return_when=FIRST_COMPLETED)
                # Inspect every already-completed failure before submitting more.
                results = [future.result() for future in done]
                pending = remaining
                checkpoint()
                for result in results: accept(result)
                for _ in done:
                    if not submit(): break
        finally:
            stopped.set()
            for future in pending: future.cancel()
            # Executor exit joins started work before this function can raise.


def _publish(destination, manifest, check):
    payload = json.dumps(manifest, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(payload) > MANIFEST_BYTES:
        raise CopyError('manifest_limit')
    packed = gzip.compress(payload, mtime=0)
    pending = destination/'manifest.pending'
    with pending.open('xb') as stream:
        stream.write(packed); stream.flush(); os.fsync(stream.fileno())
    pending.replace(destination/'manifest.json.gz')
    check()
    marker = dict(version=1, manifest_sha256=hashlib.sha256(packed).hexdigest())
    pending = destination/'complete.pending'
    with pending.open('xb') as stream:
        stream.write(json.dumps(marker, sort_keys=True).encode())
        stream.flush(); os.fsync(stream.fileno())
    check(); pending.replace(destination/'complete.json')
    return dict(status='complete', root=str(destination), **marker)


def copy_inputs(source, fresh_destination, *, checkpoint=lambda: None, max_bytes=MAX_BYTES):
    """Return a completed root or a retained failed/deferred attempt.

    Resource floors and the outer process envelope belong to the caller.
    ``max_bytes`` bounds conservative charged file storage, not a filesystem
    quota. Unknown ownership revisions defer. No installed code is executed.
    """
    source = Path(os.path.abspath(source)); destination = Path(os.path.abspath(fresh_destination))
    created = False; access = None
    try:
        if type(max_bytes) is not int or not 0 < max_bytes <= MAX_BYTES:
            raise CopyError('invalid_budget')
        if source == destination or source in destination.parents or destination in source.parents:
            raise CopyError('overlapping_paths')
        _ancestors(source); _ancestors(destination.parent)
        if destination.exists() or destination.is_symlink():
            raise CopyError('destination_exists')
        _ancestors(source/'data')
        checkpoint(); _pending(source)
        for name in ('website-source.lock', 'website-data-0.lock'):
            path = source/'data'/name
            if not stat.S_ISREG(_plain(path).st_mode):
                raise CopyError('missing_lock')
        if not (source/'data/website-data-0.lock').stat().st_size:
            raise CopyError('uninitialized_lock')
        with ExitStack() as owners:
            try:
                owners.enter_context(runtime_access.ownership(source, exclusive=True, timeout=0))
            except RuntimeError:
                raise Deferred('source_busy_or_pending') from None
            before_binding = _binding(source, checkpoint)
            access = cache_access.WorkspaceAccess(source/'data/website-data-0.lock', read_only=True)
            if access.live_pending():
                raise Deferred('live_intent')
            try:
                conflict = owners.enter_context(access.observe())
            except cache_access.Contention:
                raise Deferred('cache_busy') from None
            def check():
                checkpoint()
                try:
                    conflict()
                except ValueError:
                    raise Deferred('live_intent') from None
            _pending(source); before = _inventory(source, check)
            logical = sum(row['bytes'] for row in before.values())
            # Round each file to the measured destination allocation unit.
            # Charge 16 KiB/file for metadata and 64 MiB for directories/receipts.
            # This is conservative admission accounting, not a filesystem quota.
            unit = _allocation_unit(destination.parent)
            if unit <= 0:
                raise CopyError('invalid_allocation_unit')
            allowance = 16*1024*len(before)+64*1024**2
            estimated = sum(((r['bytes']+unit-1)//unit)*unit for r in before.values())+allowance
            if estimated > max_bytes or shutil.disk_usage(destination.parent).free < max_bytes:
                raise CopyError('storage_limit')
            if before['results/summary-exits.txt']['bytes'] > BUFFER:
                raise CopyError('report_limit')
            report = (source/'results/summary-exits.txt').read_bytes()
            through = re.findall(rb'^Through (\d{4}-\d{2}-\d{2})\s*$', report, re.MULTILINE)
            if len(through) != 1:
                raise CopyError('report_cutoff')
            through = date.fromisoformat(through[0].decode()).isoformat()
            destination.mkdir(); created = True; hashes = {}; allocated = 0
            for parent in sorted({(destination/name).parent for name in before}):
                check(); _parents(parent)
            def copy_file(item, stop):
                name, row = item; target = destination/name
                digest = _copy_file(source/name, target, row, stop)
                stop()
                return name, digest, _allocation(target)
            def accept_copy(result):
                nonlocal allocated
                name, digest, amount = result
                hashes[name] = digest; allocated += amount
                if allocated+allowance > max_bytes:
                    raise CopyError('storage_limit')
            _file_pass(before.items(), copy_file, accept_copy, check)
            if _inventory(source, check) != before:
                raise CopyError('source_changed')
            if _inventory(destination, check) != before:
                raise CopyError('destination_mismatch')
            def verify(item, stop):
                name, row = item; stop()
                if _hash(source/name, stop) != hashes[name]:
                    raise CopyError('source_changed')
                if _hash(destination/name, stop) != hashes[name]:
                    raise CopyError('destination_mismatch')
                if (destination/name).stat().st_size != row['bytes']:
                    raise CopyError('destination_mismatch')
            _file_pass(before.items(), verify, lambda result: None, check)
            _pending(source)
            if _binding(source, check) != before_binding or _inventory(source, check) != before:
                raise CopyError('source_changed')
            if hashes['results/summary-exits.txt'] != hashlib.sha256(report).hexdigest():
                raise CopyError('source_changed')
            manifest = dict(version=1, kind='offline_saved_inputs', binding=before_binding,
                through=through, files={n:dict(**r, sha256=hashes[n]) for n,r in before.items()},
                logical_bytes=logical, allocated_file_bytes=allocated,
                allocation_unit=unit, metadata_allowance=allowance, estimated_charged_bytes=estimated,
                charged_bytes=allocated+allowance, maximum_bytes=max_bytes,
                io_workers=IO_WORKERS, maximum_outstanding_files=IO_WORKERS,
                callback_poll_seconds=POLL_SECONDS,
                preparation=False, financial_calculation=False, originals_unchanged=True,
                concurrency='Offline source-exclusive capture. Concurrent new startup may wait or time out; older cache actors do not signal live intent.')
            check()
        # No source/cache owner or file handle escapes into publication.
        return _publish(destination, manifest, checkpoint)
    except Exception as error:
        deferred = isinstance(error, Deferred)
        if isinstance(error, ValueError) and access is not None and access.live_pending():
            deferred = True
        result = dict(status='deferred' if deferred else 'failed',
            reason=error.reason if isinstance(error, CopyError) else 'operation_failed',
            error_type=type(error).__name__, errno=getattr(error, 'errno', None),
            locations=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__)])
        if created:
            # Failure metadata cannot confer completion or remove partial inputs.
            try:
                with (destination/'failure.json').open('x', encoding='utf8') as stream:
                    json.dump(result, stream, sort_keys=True)
            except OSError:
                pass
        return result
