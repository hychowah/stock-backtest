"""Private recorded-plan staging; no financial encoding or resource ownership.

A fixed workspace name prevents caller-supplied paths. The owner preserves the
workspace while it reads the staged plan.
"""
import hashlib
import json
import os
from pathlib import Path
import stat

VERSION = 1
PIECE_BYTES = 64*1024
MAX_PLAN_BYTES = 16*1024**2


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

