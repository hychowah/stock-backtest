"""Portable source fingerprints for the generated website, never its raw data."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LOCAL_OUTPUT=ROOT/'local'
SNAPSHOT_OUTPUT=ROOT/'dist'
STAMP=LOCAL_OUTPUT/'.build-state.json'


def inputs():
    sources={}
    paths=list(ROOT.glob('*.py'))
    for directory in ('browser','rendering','server'):
        paths.extend((ROOT/directory).rglob('*'))
    paths.extend((ROOT.parent/'backtest/application').rglob('*.py'))
    for path in sorted(paths):
        relative=path.relative_to(ROOT.parent)
        if not path.is_file() or path.suffix not in ('.py','.js','.css','.html'):
            continue
        if any(part in ('__pycache__','local','dist','.openai','node_modules') for part in relative.parts):
            continue
        normalized=path.read_bytes().replace(b'\r\n',b'\n')
        sources[relative.as_posix()]=hashlib.sha256(normalized).hexdigest()
    database=ROOT.parent/'data'/'research.sqlite'
    stat=database.stat()
    return dict(sources=sources,database=[stat.st_size,stat.st_mtime_ns])


def current_build():
    if not all((LOCAL_OUTPUT/name).exists() for name in ('index.html','latest-picks.csv','data.html')):
        return False
    try:return json.loads(STAMP.read_text())==inputs()
    except (OSError,ValueError):return False


def record_build():
    temporary=STAMP.with_suffix('.tmp')
    temporary.write_text(json.dumps(inputs(),sort_keys=True))
    temporary.replace(STAMP)
