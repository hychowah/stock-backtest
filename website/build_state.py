"""Portable source fingerprints for the generated website, never its raw data."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
LOCAL_OUTPUT=ROOT/'local'
SNAPSHOT_OUTPUT=ROOT/'dist'
STAMP=LOCAL_OUTPUT/'.build-state.json'


def inputs():
    sources={}
    for path in sorted(ROOT.iterdir()):
        if path.suffix in ('.py','.js','.css','.html'):
            normalized=path.read_bytes().replace(b'\r\n',b'\n')
            sources[path.name]=hashlib.sha256(normalized).hexdigest()
    database=ROOT.parent/'data'/'research.sqlite'
    stat=database.stat()
    return dict(sources=sources,database=[stat.st_size,stat.st_mtime_ns])


def current_build():
    if not all((LOCAL_OUTPUT/name).exists() for name in ('index.html','returns.csv','holdings.csv','valuations.json','latest-picks.csv','data.html')):
        return False
    try:return json.loads(STAMP.read_text())==inputs()
    except (OSError,ValueError):return False


def record_build():
    temporary=STAMP.with_suffix('.tmp')
    temporary.write_text(json.dumps(inputs(),sort_keys=True))
    temporary.replace(STAMP)
