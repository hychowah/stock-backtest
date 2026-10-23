"""Persistent local diagnostics without exception messages, source or locals.

Callers supply controlled operational context, never credentials, provider URLs
or response bodies. Error chains retain types, OS codes and stack locations.
Each server process owns its rotating files, including when ports run together.
"""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import time

from paths import ROOT

MAX_BYTES=5*1024*1024
BACKUPS=2
LOGGER=logging.getLogger('backtest')
LOGGER.setLevel(logging.INFO)
LOGGER.propagate=False
LOGGER.addHandler(logging.NullHandler())
_handler=None


def relative_path(path):
    if '://' in str(path) or '?' in str(path):return '<external path>'
    path=Path(path)
    try:return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:return path.name


def configure(directory=None):
    """Open a process-owned log; unavailable logging must not stop the server."""
    global _handler
    close()
    directory=Path(directory) if directory is not None else ROOT/'data'/'logs'
    try:
        directory.mkdir(parents=True,exist_ok=True)
        handler=RotatingFileHandler(directory/f'website-{os.getpid()}.log',maxBytes=MAX_BYTES,backupCount=BACKUPS,encoding='utf-8')
    except OSError:return None
    formatter=logging.Formatter('%(asctime)sZ %(levelname)s %(message)s',datefmt='%Y-%m-%dT%H:%M:%S')
    formatter.converter=time.gmtime
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler);_handler=handler
    return Path(handler.baseFilename)


def close():
    global _handler
    if _handler is not None:
        LOGGER.removeHandler(_handler);_handler.close();_handler=None


def log_path():
    return Path(_handler.baseFilename) if _handler is not None else None


def event(name,**context):
    LOGGER.info(json.dumps(dict(event=name,pid=os.getpid(),**context),ensure_ascii=True))


def failure(name,error,**context):
    """Keep safe tracebacks, omitting arbitrary exception text and source lines."""
    errors=[];seen=set()
    while error is not None and id(error) not in seen:
        seen.add(id(error));frames=[];tb=error.__traceback__
        while tb is not None:
            code=tb.tb_frame.f_code
            frames.append(dict(file=relative_path(code.co_filename),line=tb.tb_lineno,function=code.co_name))
            tb=tb.tb_next
        detail=dict(type=type(error).__name__,frames=frames)
        for key in ('errno','winerror','sqlite_errorcode','returncode'):
            value=getattr(error,key,None)
            if isinstance(value,int):detail[key]=value
        if isinstance(error,OSError):
            for key in ('filename','filename2'):
                value=getattr(error,key,None)
                if value:detail[key]=relative_path(value)
        errors.append(detail)
        error=error.__cause__ or (error.__context__ if not error.__suppress_context__ else None)
    LOGGER.error(json.dumps(dict(event=name,pid=os.getpid(),errors=errors,**context),ensure_ascii=True))
