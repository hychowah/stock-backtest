"""Private WSL storage and bounded evidence, inside the comparison supervisor.

Tmpfs capacity bounds allocated data blocks, not logical lengths, inode counts,
I/O or total residency. Persistent publication is a sole-writer allowance, not a
filesystem quota. Outside supervision remains outside application limits.
"""
import array
import ctypes
from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import sqlite3
import stat
import struct
import sys
import time
import uuid

from bench_comparison import ComparisonError, encoded

HEADER_BYTES = 4096
CONTROL_BYTES = 1024 * 1024
MAX_ENTRIES = 4096
MAX_PATH_BYTES = 512
MAX_METADATA_BYTES = 1024
MAX_DEPTH = 32
MAX_INTEGER = 2**63 - 1
CHUNK_BYTES = 65536
PRIVATE_ROOT = '/tmp/cb02-operation'


def validate_limits(storage_bytes, evidence_bytes):
    if storage_bytes is None and evidence_bytes is None:
        return
    if any(type(v) is not int or not HEADER_BYTES <= v <= MAX_INTEGER or v % HEADER_BYTES
           for v in (storage_bytes, evidence_bytes)):
        raise ValueError('Unsupported storage declaration.')


def failure_reason(error, default='child_failed'):
    """Classify resource exhaustion without exposing OS exception text."""
    if isinstance(error, OSError) and error.errno in (errno.ENOSPC, errno.EDQUOT):
        return 'limit'
    if isinstance(error, sqlite3.DatabaseError):
        code = getattr(error, 'sqlite_errorcode', 0)
        if type(code) is int and code & 255 == sqlite3.SQLITE_FULL:
            return 'limit'
    return getattr(error, 'reason', default)


@contextmanager
def storage_io():
    """Translate only owned filesystem failures. Caller failures stay intact."""
    try: yield
    except OSError as error:
        if failure_reason(error) == 'limit':
            raise ComparisonError('limit') from error
        raise


def _local_path(value):
    # Reuse the artifact owner's existing no-symlink/junction path policy.
    # This imports no application financial module and reads no asset contents.
    from bench_execution_inputs import _path, ExecutionInputError
    try: return _path(value)
    except ExecutionInputError as error:
        raise ComparisonError(error.reason) from error


def _valid_header(value):
    required = {'version', 'capacity', 'committed', 'entries', 'state', 'run_id',
                'accepted_result', 'generation'}
    if not isinstance(value, dict): raise ComparisonError('mismatch')
    ready = value.get('state') == 'ready'
    if set(value) != required | ({'terminal_reason', 'storage_received'} if ready else set()):
        raise ComparisonError('mismatch')
    capacity, committed = value['capacity'], value['committed']
    if (type(value['version']) is not int or value['version'] != 1
            or value['accepted_result'] is not False
            or type(capacity) is not int or not HEADER_BYTES <= capacity <= MAX_INTEGER
            or capacity % HEADER_BYTES or type(committed) is not int
            or not HEADER_BYTES <= committed <= capacity
            or type(value['entries']) is not int or not 0 <= value['entries'] <= MAX_ENTRIES
            or type(value['generation']) is not int or not 1 <= value['generation'] <= MAX_INTEGER
            or value['state'] not in ('collecting', 'ready')
            or not isinstance(value['run_id'], str) or len(value['run_id']) != 32
            or any(c not in '0123456789abcdef' for c in value['run_id'])):
        raise ComparisonError('mismatch')
    if ready:
        reason = value['terminal_reason']
        if (type(value['storage_received']) is not bool or (reason is not None and
                (not isinstance(reason, str) or not 0 < len(reason) <= 64
                 or any(not (c.isascii() and (c.isalpha() or c == '_')) for c in reason)))):
            raise ComparisonError('mismatch')
    return value


def _valid_record(value):
    if not isinstance(value, dict) or set(value) != {'path', 'bytes', 'sha256'}:
        raise ComparisonError('mismatch')
    path, size, sha = value['path'], value['bytes'], value['sha256']
    try: length = len(path.encode('utf-8')) if isinstance(path, str) else 0
    except UnicodeError: raise ComparisonError('mismatch') from None
    if (not 0 < length <= MAX_PATH_BYTES or '\\' in path or ':' in path or '\0' in path
            or PurePosixPath(path).is_absolute() or path.count('/') > MAX_DEPTH
            or any(p in ('', '.', '..') for p in path.split('/'))
            or type(size) is not int or not 0 <= size <= MAX_INTEGER
            or not isinstance(sha, str) or len(sha) != 64
            or any(c not in '0123456789abcdef' for c in sha)):
        raise ComparisonError('mismatch')
    return value


def _decode(raw):
    try: return json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise ComparisonError('mismatch') from None


def _header(fd):
    candidates = []
    for offset in (0, HEADER_BYTES // 2):
        try: record = _decode(os.pread(fd, HEADER_BYTES // 2, offset).rstrip(b'\0'))
        except ComparisonError: continue  # A torn next slot preserves its predecessor.
        if not isinstance(record, dict) or set(record) != {'value', 'sha256'}: continue
        try: actual = hashlib.sha256(encoded(record['value'])).hexdigest()
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise ComparisonError('mismatch') from None
        if actual != record['sha256']: continue
        value = _valid_header(record['value'])
        if (os.fstat(fd).st_size != value['capacity']
                or value['generation'] % 2 != offset // (HEADER_BYTES // 2)):
            raise ComparisonError('mismatch')
        candidates.append(value)
    if not candidates: raise ComparisonError('mismatch')
    return max(candidates, key=lambda v: v['generation'])


def _records(fd, header, checkpoint=lambda: None):
    """Verify only durable complete records. Ignore any uncommitted tail."""
    position, records = HEADER_BYTES, []
    while position < header['committed']:
        checkpoint()
        raw = os.pread(fd, 4, position)
        if len(raw) != 4: raise ComparisonError('mismatch')
        length = struct.unpack('!I', raw)[0]
        if not 0 < length <= MAX_METADATA_BYTES: raise ComparisonError('mismatch')
        if position + 4 + length > header['committed']: raise ComparisonError('mismatch')
        raw_metadata = os.pread(fd, length, position + 4)
        if len(raw_metadata) != length: raise ComparisonError('mismatch')
        metadata = _valid_record(_decode(raw_metadata))
        size = metadata['bytes']
        position += 4 + length
        end, hashed = position + size, hashlib.sha256()
        if end > header['committed']: raise ComparisonError('mismatch')
        while position < end:
            checkpoint()
            chunk = os.pread(fd, min(CHUNK_BYTES, end - position), position)
            if not chunk: raise ComparisonError('mismatch')
            hashed.update(chunk); position += len(chunk)
        if hashed.hexdigest() != metadata.get('sha256'): raise ComparisonError('mismatch')
        records.append(metadata)
        if len(records) > MAX_ENTRIES: raise ComparisonError('mismatch')
    if position != header['committed'] or len(records) != header['entries']:
        raise ComparisonError('mismatch')
    if len({r['path'] for r in records}) != len(records): raise ComparisonError('mismatch')
    return records


def inspect_evidence(path):
    """Inspect bounded verified records; a receipt never proves accepted return.

    An interrupted container survives supervisor death. Uncollected tmpfs bytes
    do not. This operation neither extracts files nor resumes a comparison.
    """
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        header = _header(fd)
        return dict(header=header, records=_records(fd, header),
                    uncollected_storage='lost_if_original_owner_is_gone',
                    comparison_resumable=False)
    finally: os.close(fd)


def recover_publication(path):
    """Finish a ready container's atomic rename, without accepting a result.

    Incomplete records remain inspectable but cannot recreate lost tmpfs data.
    """
    path = _local_path(path)
    value = inspect_evidence(path)
    if value['header']['state'] != 'ready' or path.suffix != '.pending':
        raise ComparisonError('incomplete')
    target = path.with_suffix('.evidence')
    if target.exists(): raise ComparisonError('busy')
    path.replace(target)
    return target


class ExperimentalStorage:
    """Own one comparison's private writable filesystem through collection.

    A controller exit does not release storage. Unconfirmed collection or
    closure retains this owner for explicit retry. Effective platform
    capabilities determine enforcement claims. The supervisor holds the strong
    pending-owner registration before this object creates any resources.
    """
    def __init__(self, storage_bytes, evidence_bytes, output, close_seconds, *, protected=()):
        validate_limits(storage_bytes, evidence_bytes)
        if sys.platform != 'linux' or not shutil.which('bwrap'):
            raise ComparisonError('unsupported')
        self.capacity, self.evidence_bytes = storage_bytes, evidence_bytes
        self.output, self.seconds = Path(output), close_seconds
        self.protected = tuple(map(_local_path, protected))
        self._validate_destination()
        self.run_id = uuid.uuid4().hex
        self.address = 'cb02-storage-' + self.run_id
        self.nonce = uuid.uuid4().hex.encode()
        self.listener = self.connection = None
        self.pin = self.writer = None
        self.configuration = None
        self.closed = self.published = self.reserved = False
        self.pending = self.output / ('storage-' + self.run_id + '.pending')
        self.target = self.pending.with_suffix('.evidence')
        self.header = dict(version=1, capacity=evidence_bytes, committed=HEADER_BYTES,
            entries=0, state='collecting', run_id=self.run_id, accepted_result=False, generation=0)

    def _validate_destination(self):
        output = _local_path(self.output)
        for original in self.protected:
            current = _local_path(original)
            if output.is_relative_to(current) or current.is_relative_to(output):
                raise ComparisonError('unsupported')
        self.output = output

    @storage_io()
    def prepare(self):
        self._validate_destination()
        self.output.mkdir(parents=True, exist_ok=True)
        self.writer = os.open(self.pending, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        # Reserve the ONE container. Rename publishes this same allocation;
        # recovery never creates a second staging copy.
        self._reserve()
        self._save_header()
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind('\0' + self.address)
        self.listener.listen(1)
        self.listener.settimeout(.05)

    @storage_io()
    def _reserve(self):
        # A failed allocation can leave an open, shorter pending file. Retry
        # the reservation before writing a valid container, without discarding
        # that file or starting any comparison work.
        if not self.reserved:
            os.posix_fallocate(self.writer, 0, self.evidence_bytes)
            self.reserved = True

    @storage_io()
    def _save_header(self):
        value = _valid_header(dict(self.header, generation=self.header['generation'] + 1))
        raw = encoded(dict(value=value, sha256=hashlib.sha256(encoded(value)).hexdigest()))
        slot = HEADER_BYTES // 2
        if len(raw) > slot: raise ComparisonError('limit')
        self._write_at(raw.ljust(slot, b'\0'), (value['generation'] % 2) * slot)
        os.fsync(self.writer)
        self.header = value

    @storage_io()
    def _write_at(self, data, offset):
        if offset < 0 or offset + len(data) > self.evidence_bytes:
            raise ComparisonError('limit')
        while data:
            written = os.pwrite(self.writer, data, offset)
            if not written: raise OSError('Evidence write did not advance.')
            data = data[written:]; offset += written

    def command(self, command, readonly):
        # /tmp is the only writable filesystem. All caches/home/temp paths
        # below use it, including /dev/shm's alias. A fixed read-only device
        # scaffold adds no writable file area. /var/tmp, home and root stay
        # recursively read-only. Private PID/proc hides parent-root/FD aliases.
        prefix = ['bwrap', '--unshare-user', '--unshare-pid', '--die-with-parent',
            '--cap-drop', 'ALL', '--ro-bind', '/', '/', '--proc', '/proc',
            '--remount-ro', '/proc',
            '--tmpfs', '/dev', '--dev-bind', '/dev/null', '/dev/null',
            '--dev-bind', '/dev/zero', '/dev/zero',
            '--dev-bind', '/dev/random', '/dev/random',
            '--dev-bind', '/dev/urandom', '/dev/urandom',
            '--symlink', '/proc/self/fd', '/dev/fd',
            '--symlink', '/proc/self/fd/0', '/dev/stdin',
            '--symlink', '/proc/self/fd/1', '/dev/stdout',
            '--symlink', '/proc/self/fd/2', '/dev/stderr',
            '--symlink', PRIVATE_ROOT + '/shm', '/dev/shm',
            '--remount-ro', '/dev',
            '--size', str(self.capacity), '--tmpfs', '/tmp',
            '--dir', PRIVATE_ROOT, '--dir', PRIVATE_ROOT + '/temporary',
            '--dir', PRIVATE_ROOT + '/home', '--dir', PRIVATE_ROOT + '/shm', '--chdir', PRIVATE_ROOT]
        # Synthetic inputs can themselves be under host /tmp. Re-expose only
        # explicit read-only dependencies, never the persistent output folder.
        for path in sorted({str(Path(p).resolve()) for p in readonly}):
            bound = Path(path)
            if bound.is_relative_to(PRIVATE_ROOT) or Path(PRIVATE_ROOT).is_relative_to(bound):
                raise ComparisonError('unsupported')
            prefix += ['--ro-bind', path, path]
        for key, value in self.environment().items():
            prefix += ['--setenv', key, value]
        code = ('import sys;sys.path.insert(0,sys.argv.pop(1));'
                'from bench_execution_storage import bootstrap;bootstrap()')
        return prefix + ['--', sys.executable, '-I', '-B', '-c', code,
            str(Path(__file__).parent), self.address, self.nonce.decode(), *command]

    def environment(self):
        return dict(HOME=PRIVATE_ROOT + '/home', TMPDIR=PRIVATE_ROOT + '/temporary',
            TMP=PRIVATE_ROOT + '/temporary', TEMP=PRIVATE_ROOT + '/temporary',
            XDG_CACHE_HOME=PRIVATE_ROOT + '/home/cache',
            NUMBA_CACHE_DIR=PRIVATE_ROOT + '/compiler',
            MPLCONFIGDIR=PRIVATE_ROOT + '/config', PYTHONDONTWRITEBYTECODE='1')

    def attach(self, owned, check):
        deadline = time.monotonic() + self.seconds
        while self.connection is None:
            check()
            try: self.connection, _ = self.listener.accept()
            except socket.timeout:
                if owned.process.poll() is not None: raise ComparisonError('child_failed')
                if time.monotonic() > deadline: raise ComparisonError('limit')
        self.connection.settimeout(self.seconds)
        received = []
        try:
            data, ancillary, flags, _ = self.connection.recvmsg(64, socket.CMSG_SPACE(16 * 4))
            unexpected = False
            for level, kind, raw in ancillary:
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                    fds = array.array('i'); fds.frombytes(raw[:len(raw) - len(raw) % fds.itemsize])
                    received.extend(fds)
                else: unexpected = True
            peer, uid, _ = struct.unpack('3i', self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if (unexpected or data != self.nonce or flags or len(received) != 1
                    or uid != os.getuid() or peer not in owned._session_members()):
                raise ComparisonError('mismatch')
            # Adopt before validation. Failure retains the mount for closure.
            self.pin = received.pop()
            os.set_inheritable(self.pin, False)
            class Statfs(ctypes.Structure):
                _fields_ = [('type', ctypes.c_long), ('remainder', ctypes.c_byte * 248)]
            info = Statfs()
            if ctypes.CDLL(None, use_errno=True).fstatfs(self.pin, ctypes.byref(info)):
                raise OSError(ctypes.get_errno(), 'Filesystem query failed.')
            usage = os.fstatvfs(self.pin)
            if (not stat.S_ISDIR(os.fstat(self.pin).st_mode) or info.type != 0x01021994
                    or usage.f_blocks * usage.f_frsize != self.capacity):
                raise ComparisonError('mismatch')
            self.configuration = dict(filesystem='tmpfs', allocated_capacity=self.capacity,
                inode_capacity=usage.f_files, verified_before_GO=True,
                storage_scope='one_writable_tmpfs; host_root_devices_and_proc_readonly')
            self.connection.sendall(b'G')
        finally:
            for fd in received: os.close(fd)

    @property
    def root(self):
        if self.pin is None or self.configuration is None: raise ComparisonError('incomplete')
        return Path('/proc/self/fd') / str(self.pin)

    def capability(self):
        return dict(bound=self.capacity, status='hard',
            mechanism='private tmpfs allocated data-block capacity',
            scope='application_writable_files; not_logical_lengths_inodes_or_IO',
            configuration=self.configuration,
            persistent_publication=dict(bound=self.evidence_bytes, status='bounded_sole_writer',
                container_header_bytes=HEADER_BYTES, entry_limit=MAX_ENTRIES,
                path_bytes=MAX_PATH_BYTES, metadata_bytes=MAX_METADATA_BYTES),
            control_file_payload_bytes=CONTROL_BYTES,
            simultaneous_payload_allowance=self.capacity + self.evidence_bytes + CONTROL_BYTES)

    def _files(self, directory, relative='', count=None):
        count = [0] if count is None else count
        names = []
        with os.scandir(directory) as entries:
            for entry in entries:
                count[0] += 1
                if count[0] > MAX_ENTRIES: raise ComparisonError('limit')
                names.append(entry.name)
        for name in sorted(names):
            path = relative + name
            if len(path.encode()) > MAX_PATH_BYTES or path.count('/') > MAX_DEPTH:
                raise ComparisonError('limit')
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                info = os.fstat(fd)
                if stat.S_ISDIR(info.st_mode):
                    yield from self._files(fd, path + '/', count)
                elif stat.S_ISREG(info.st_mode):
                    yield path, fd, info.st_size
                else: raise ComparisonError('unsupported')
            finally: os.close(fd)

    def _copy_record(self, path, fd, size, check):
        position = self.header['committed']
        # Hash first, with finite logical length. Sparse files may be much
        # larger than their tmpfs allocation; never materialize them blindly.
        if size > self.evidence_bytes - position: raise ComparisonError('limit')
        hashed = hashlib.sha256()
        while True:
            check(); chunk = os.read(fd, CHUNK_BYTES)
            if not chunk: break
            hashed.update(chunk)
        metadata = _valid_record(dict(path=path, bytes=size, sha256=hashed.hexdigest()))
        raw = encoded(metadata)
        if len(raw) > MAX_METADATA_BYTES or position + 4 + len(raw) + size > self.evidence_bytes:
            raise ComparisonError('limit')
        self._write_at(struct.pack('!I', len(raw)) + raw, position)
        position += 4 + len(raw); os.lseek(fd, 0, 0)
        copied = 0; transferred = hashlib.sha256()
        while copied < size:
            check(); chunk = os.read(fd, min(CHUNK_BYTES, size - copied))
            if not chunk: raise ComparisonError('mismatch')
            transferred.update(chunk)
            self._write_at(chunk, position); position += len(chunk); copied += len(chunk)
        if os.read(fd, 1) or transferred.hexdigest() != metadata['sha256']:
            raise ComparisonError('mismatch')
        os.fsync(self.writer)
        self.header.update(committed=position, entries=self.header['entries'] + 1)
        self._save_header()

    @storage_io()
    def finish(self, *, domain_closed, reason=None, checkpoint=lambda: None):
        """Publish evidence from a closed domain within finite transfer limits.

        Durable complete records survive interruption. An unverified tail does
        not count. Recovery never resumes or makes a failed comparison succeed.
        """
        if self.closed: return
        if not domain_closed: raise ComparisonError('closure_pending')
        self._validate_destination()
        deadline = time.monotonic() + self.seconds
        def check():
            checkpoint()
            if time.monotonic() > deadline: raise ComparisonError('limit')
        if self.writer is not None and not self.published:
            self._reserve()
            if self.header['generation']: self.header = _header(self.writer)
            complete = {r['path']: r for r in _records(self.writer, self.header, check)}
            if self.pin is not None and self.configuration is not None:
                for path, fd, size in self._files(self.pin):
                    check()
                    if path in complete:
                        if size != complete[path]['bytes']: raise ComparisonError('mismatch')
                    else: self._copy_record(path, fd, size, check)
            self.header.update(state='ready', terminal_reason=reason,
                               storage_received=self.configuration is not None)
            self._save_header()
            self.pending.replace(self.target)
            self.published = True
        self._release()
        self.closed = True

    def _release(self):
        # Retain each handle until its actual close succeeds. No finalizer owns
        # cleanup, and no pending evidence is deleted on failure.
        for name in ('pin', 'writer'):
            value = getattr(self, name)
            if value is not None:
                os.close(value); setattr(self, name, None)
        for name in ('connection', 'listener'):
            value = getattr(self, name)
            if value is not None:
                value.close(); setattr(self, name, None)


def bootstrap():
    """Transfer storage before application GO. No financial admission is added."""
    address, nonce, *command = sys.argv[1:]
    root = Path(PRIVATE_ROOT)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(10.)
        connection.connect('\0' + address)
        connection.sendmsg([nonce.encode()], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                              array.array('i', [fd]))])
        os.close(fd)
        if connection.recv(1) != b'G': raise ComparisonError('protocol')
    os.execvpe(command[0], command, os.environ)
