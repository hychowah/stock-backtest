"""Private bounded byte transport; no financial encoding or resource ownership.

Acknowledge one verified piece before the sender can replace its slot. Fixed
workspace names prevent caller-supplied paths. Owners preserve the workspace
through transfer/retirement and publish only after complete codec validation.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid
from threading import Event, Lock

VERSION = 1
PIECE_BYTES = 64*1024
MAX_PLAN_BYTES = 16*1024**2
OWNED_FILES = ('recorded-plan.json', 'recorded-plan.pending', 'transfer.bin',
               'transfer.pending', 'produced.evidence')


class Acknowledgements:
    """Accept exactly one matching acknowledgement of an armed boundary."""
    def __init__(self):
        self.lock=Lock();self.ready=Event();self.expected=None;self.failed=False

    def arm(self,operation,sequence):
        with self.lock:
            self.check()
            if self.expected is not None:raise ValueError('Transfer already awaits acknowledgement.')
            self.expected=dict(command='transfer_ack',operation=operation,sequence=sequence)
            self.ready.clear()

    def accept(self,value):
        with self.lock:
            if self.expected is None or value!=self.expected or type(value.get('sequence')) is not int:
                self.failed=True
            self.expected=None;self.ready.set()
            return not self.failed

    def check(self):
        if self.failed:raise ValueError('Evidence transfer acknowledgement differs.')

    def wait(self,timeout):
        ready=self.ready.wait(timeout);self.check();return ready


def _fingerprint(value):
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns]


def _path(root, name):
    root = Path(root)
    path = root/name
    if root.is_symlink() or path.is_symlink() or path.resolve().parent != root.resolve():
        raise ValueError('Transfer file escapes its owned workspace.')
    return path


def _open(root, name):
    path = _path(root,name)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode): raise ValueError('Transfer file is not regular.')
    descriptor = os.open(path,os.O_RDONLY | getattr(os,'O_BINARY',0) | getattr(os,'O_NOFOLLOW',0))
    try:
        handle = os.fdopen(descriptor,'rb')
    except BaseException:
        os.close(descriptor); raise
    if _fingerprint(before) != _fingerprint(os.fstat(handle.fileno())):
        handle.close(); raise ValueError('Transfer file was replaced.')
    return handle, before


def _digest(value):
    return type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def _object(pairs):
    value={}
    for key,part in pairs:
        if key in value:raise ValueError('Duplicate staged plan key.')
        value[key]=part
    return value


def _plan_parts(value, checkpoint):
    from backtest.result_evidence import _json_value
    _json_value(value,MAX_PLAN_BYTES)
    size=0
    for token in json.JSONEncoder(allow_nan=False,sort_keys=True,separators=(',',':')).iterencode(value):
        for offset in range(0,len(token),PIECE_BYTES):
            checkpoint();data=token[offset:offset+PIECE_BYTES].encode('ascii')
            size+=len(data)
            if size>MAX_PLAN_BYTES:raise ValueError('Recorded plan exceeds its staged byte bound.')
            yield data


def plan_identity(value, checkpoint=lambda:None):
    digest=hashlib.sha256()
    for data in _plan_parts(value,checkpoint):digest.update(data)
    return digest.hexdigest()


def stage_plan(root, value, checkpoint=lambda:None):
    """Bind exact private plan bytes. Never enlarge the eager request limit."""
    path=_path(root,'recorded-plan.pending');digest=hashlib.sha256();size=0
    try:
        with path.open('xb') as handle:
            for data in _plan_parts(value,checkpoint):
                handle.write(data);digest.update(data);size+=len(data)
        path.replace(_path(root,'recorded-plan.json'))
        return dict(version=VERSION,bytes=size,sha256=digest.hexdigest(),
                    file_identity=_fingerprint(_path(root,'recorded-plan.json').stat()))
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def read_plan(root, reference, checkpoint=lambda:None):
    if (type(reference) is not dict or set(reference)!={'version','bytes','sha256','file_identity'}
            or type(reference['version']) is not int or reference['version']!=VERSION
            or type(reference['bytes']) is not int or not 0<reference['bytes']<=MAX_PLAN_BYTES
            or not _digest(reference['sha256'])):
        raise ValueError('Invalid staged plan reference.')
    handle,before=_open(root,'recorded-plan.json')
    with handle:
        if reference['file_identity']!=_fingerprint(before):raise ValueError('Staged plan was replaced.')
        digest=hashlib.sha256();data=bytearray()
        while len(data)<reference['bytes']:
            checkpoint();part=handle.read(min(PIECE_BYTES,reference['bytes']-len(data)))
            if not part:raise ValueError('Truncated staged plan.')
            data.extend(part);digest.update(part)
        if (handle.read(1) or digest.hexdigest()!=reference['sha256']
                or _fingerprint(before)!=_fingerprint(os.fstat(handle.fileno()))
                or _fingerprint(before)!=_fingerprint(_path(root,'recorded-plan.json').stat())):
            raise ValueError('Staged plan content differs.')
    def invalid(value):raise ValueError('Staged plan numbers must be finite.')
    value=json.loads(data,object_pairs_hook=_object,parse_constant=invalid)
    from backtest.result_evidence import _json_value
    _json_value(value,MAX_PLAN_BYTES)
    return value


def send(stream, root, exchange, *, max_bytes, checkpoint=lambda:None):
    """Copy a completed stream; exchange returns only after the exact ack."""
    stream.seek(0);digest=hashlib.sha256();size=0
    while True:
        checkpoint();data=stream.read(PIECE_BYTES)
        if not data:break
        size+=len(data)
        if size>max_bytes:raise ValueError('Evidence transfer exceeds its byte bound.')
        digest.update(data)
    identity=uuid.uuid4().hex
    header=dict(version=VERSION,operation=identity,bytes=size,sha256=digest.hexdigest())
    exchange(dict(event='transfer_begin',**header),identity,-1)
    stream.seek(0);offset=sequence=0
    while offset<size:
        checkpoint();data=stream.read(min(PIECE_BYTES,size-offset))
        if not data:raise ValueError('Evidence spool changed during transfer.')
        temporary=_path(root,'transfer.pending')
        with temporary.open('wb') as handle:handle.write(data)
        temporary.replace(_path(root,'transfer.bin'))
        exchange(dict(event='transfer_piece',operation=identity,sequence=sequence,offset=offset,
            bytes=len(data),sha256=hashlib.sha256(data).hexdigest()),identity,sequence)
        offset+=len(data);sequence+=1
    exchange(dict(event='transfer_end',sequence=sequence,**header),identity,sequence)
    return header


class Receiver:
    """Receive into provisional caller storage; no publishable partial result.

    The owner acknowledges only a successful accept. finish is mandatory and
    does not replace complete financial-evidence codec validation.
    """
    def __init__(self, stream, root, *, max_bytes, checkpoint=lambda:None):
        if type(max_bytes) is not int or max_bytes<=0:raise ValueError('Invalid evidence transfer bound.')
        if stream.tell()!=0 or stream.seek(0,2)!=0:raise ValueError('Evidence destination must be empty.')
        self.stream,self.root,self.max_bytes=stream,root,max_bytes
        self.header=None;self.sequence=self.offset=0;self.digest=hashlib.sha256();self.complete=False
        self.checkpoint=checkpoint

    def accept(self, event):
        kind=event.get('event')
        if self.complete:raise ValueError('Transfer follows completion.')
        if kind=='transfer_begin':
            if (self.header is not None or set(event)!={'event','version','operation','bytes','sha256'}
                    or type(event['version']) is not int or event['version']!=VERSION
                    or type(event['operation']) is not str or len(event['operation'])!=32
                    or any(c not in '0123456789abcdef' for c in event['operation'])
                    or type(event['bytes']) is not int or not 0<event['bytes']<=self.max_bytes
                    or not _digest(event['sha256'])):
                raise ValueError('Invalid evidence transfer header.')
            self.header={k:v for k,v in event.items() if k!='event'}
            return self.header['operation'],-1
        if self.header is None or event.get('operation')!=self.header['operation']:
            raise ValueError('Evidence transfer identity differs.')
        if type(event.get('sequence')) is not int or event['sequence']!=self.sequence:
            raise ValueError('Evidence transfer sequence differs.')
        if kind=='transfer_piece':
            if (set(event)!={'event','operation','sequence','offset','bytes','sha256'}
                    or type(event['offset']) is not int or event['offset']!=self.offset
                    or type(event['bytes']) is not int or not 0<event['bytes']<=PIECE_BYTES
                    or self.offset+event['bytes']>self.header['bytes'] or not _digest(event['sha256'])):
                raise ValueError('Evidence transfer piece differs.')
            handle,before=_open(self.root,'transfer.bin')
            with handle:
                data=handle.read(PIECE_BYTES+1)
                if _fingerprint(before)!=_fingerprint(os.fstat(handle.fileno())):
                    raise ValueError('Evidence transfer slot changed.')
            if len(data)!=event['bytes'] or hashlib.sha256(data).hexdigest()!=event['sha256']:
                raise ValueError('Evidence transfer piece content differs.')
            if self.stream.write(data)!=len(data):raise OSError('Evidence receiver write was incomplete.')
            self.digest.update(data);self.offset+=len(data);self.sequence+=1
        elif kind=='transfer_end':
            if (set(event)!={'event','sequence',*self.header}
                    or any(event[k]!=v for k,v in self.header.items())
                    or self.offset!=self.header['bytes'] or self.digest.hexdigest()!=self.header['sha256']):
                raise ValueError('Evidence transfer completion differs.')
            self.complete=True
        else:raise ValueError('Unknown evidence transfer event.')
        return self.header['operation'],event['sequence']

    def finish(self):
        if not self.complete:raise ValueError('Evidence transfer ended before completion.')
        self.stream.flush()
        self.stream.seek(0);digest=hashlib.sha256();size=0
        while True:
            self.checkpoint();data=self.stream.read(PIECE_BYTES)
            if not data:break
            size+=len(data)
            if size>self.header['bytes']:raise ValueError('Received evidence grew after transfer.')
            digest.update(data)
        if size!=self.header['bytes'] or digest.hexdigest()!=self.header['sha256']:
            raise ValueError('Received evidence content differs.')
        return dict(self.header)


def cleanup(root):
    for name in OWNED_FILES:
        _path(root,name).unlink(missing_ok=True)
