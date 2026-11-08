"""Portable source fingerprints for the generated website, never its raw data."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from backtest.inputs import cache_assets

ROOT=Path(__file__).resolve().parents[1]
LOCAL_OUTPUT=ROOT/'local'
SNAPSHOT_OUTPUT=ROOT/'dist'
STAMP=LOCAL_OUTPUT/'.build-state.json'
OUTPUTS=('index.html','latest-picks.csv','data.html','snapshot.json')


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
    return dict(sources=sources,latest_book=latest_book())


def latest_book():
    """Identify the latest book: the daily generation that wrote it, not the cache file's stamp.

    Saving a dated book rewrites schedules.sqlite but leaves the latest book and
    this identity unchanged. A missing or unreadable cache raises OSError.
    """
    from backtest.inputs import daily
    path=ROOT.parent/'data'/'schedules.sqlite'
    if not path.exists():raise OSError('The daily cache is missing.')
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            binding=daily.binding(db)
    except sqlite3.Error as error:
        raise OSError('The daily cache is unreadable.') from error
    if binding is None:raise OSError('The daily cache has no generation.')
    return hashlib.sha256(binding.encode('utf-8')).hexdigest()


def current_build():
    if not all((LOCAL_OUTPUT/name).exists() for name in OUTPUTS):return False
    try:
        saved=json.loads(STAMP.read_text())
        return saved==inputs()
    except (OSError,ValueError,TypeError,AttributeError):return False


def record_build():
    cache_assets.write_json(STAMP,inputs())
