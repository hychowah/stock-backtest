"""Drive the Python product (the oracle) in this process: workspace, preparation, clock and runs.

The product resolves every file location from its own source folder
(backtest/paths.py), so an oracle workspace is a folder that holds a copy of
`backtest/` beside `raw/` and `data/`. Its data and its cache lock
(data/website-data-0.lock) belong to that folder only; the checkout's own
`data/` and `raw/` are never read or written.

- `build(raw, folder)` copies this checkout's `backtest/` and a raw folder into
  `folder`.
- `tree(folder)` is the git tree id of the workspace's `backtest/`, computed
  from its files.
- `load(folder)` imports the product from a workspace: a built one or an
  already prepared runtime folder. Call it once, before any other function.
- `prepare(as_of)` runs the ordinary preparation (research, then the daily
  cache with the latest books) with the clock pinned.
- `connect()` opens the prepared daily cache with the research database
  attached as `research`, as every run does.
- `schedule(run)` gives the run mode and schedule options of a case's run
  settings.
- `entry_dates(run, sessions)` gives the entry days of a case's schedule from
  the product's planner.
- `store_books(db, market, days)` stores the dated cached-pool book of each
  day that the daily cache does not hold yet, as the book batch does.

The only clock that changes results is the completed-session test of the
local index calendars (`completed_session` in backtest/inputs/market.py). It
reads `datetime.now`; `pinned(as_of)` makes it read `as_of` instead. The pin
covers the build in this process only: on a workspace large enough for the
research build's worker processes (2,000 companies or more), a preparation is
exact only when the as-of time falls after the close of the last saved
calendar row of each market.

A case's run settings (`run.json`, see proof/l3.py) are `market`, `start`
and `end`, then either `interval` (a count and `w` or `m`, such as "6m") or
`dates` (a list of ISO days), and, for random trials, `trials` and `seed`.
`schedule` turns them into the options the website sends: an interval becomes
a version-1 calendar, run once (mode "custom") or, with trials, as random
trials (mode "random"); explicit dates become `dates` (mode "custom").
"""
from contextlib import contextmanager
import datetime
import hashlib
from pathlib import Path
import shutil
import sys

CHECKOUT = Path(__file__).resolve().parents[1]


def build(raw, folder):
    """Make folder an unprepared oracle workspace of this checkout's product and raw."""
    shutil.copytree(CHECKOUT / 'backtest', Path(folder) / 'backtest', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(raw, Path(folder) / 'raw')


def tree(folder):
    """The git tree id of folder/backtest, without its __pycache__ folders."""
    def digest(kind, content):
        return hashlib.sha1(kind + b' %d\0' % len(content) + content).digest()

    def walk(path):
        entries = []
        for child in path.iterdir():
            name = child.name.encode()
            if child.is_dir():
                if child.name != '__pycache__':
                    entries.append((name + b'/', b'40000 ' + name + b'\0' + walk(child)))
            else:
                mode = b'100755' if child.stat().st_mode & 0o100 else b'100644'
                entries.append((name, mode + b' ' + name + b'\0' + digest(b'blob', child.read_bytes())))
        return digest(b'tree', b''.join(entry for _, entry in sorted(entries)))

    return walk(Path(folder) / 'backtest').hex()


def load(folder):
    """Import the product of the workspace folder."""
    sys.path.insert(0, str(Path(folder).resolve()))


@contextmanager
def pinned(as_of):
    """Make the completed-session test read as_of (an aware datetime) as the current time."""
    from backtest.inputs import market
    ordinary = market.completed_session

    class Clock(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return as_of.astimezone(tz)

    def completed_session(day, market_id):
        real, datetime.datetime = datetime.datetime, Clock
        try:
            return ordinary(day, market_id)
        finally:
            datetime.datetime = real

    market.completed_session = completed_session
    try:
        yield
    finally:
        market.completed_session = ordinary


def prepare(as_of):
    """The ordinary preparation of the data panel's rebuild, without the website build."""
    from backtest.inputs import daily
    from backtest.engines.original import book_batch
    with pinned(as_of):
        daily.prepare(repair=book_batch.repair)


def connect():
    """The daily connection of a run: the daily cache, with the research database attached as 'research'."""
    from backtest.inputs import daily
    return daily.connect()


def schedule(run):
    """(mode, options) of a case's run settings: the calculation options without the strategy."""
    options = dict(market=run['market'])
    if 'dates' in run:
        return 'custom', dict(options, start=run['start'], end=run['end'], dates=run['dates'])
    count, unit = int(run['interval'][:-1]), dict(w='week', m='month')[run['interval'][-1]]
    options['calendar'] = dict(version=1, start=run['start'], end=run['end'], interval=dict(unit=unit, count=count))
    if 'trials' not in run:
        return 'custom', options
    return 'random', dict(options, trials=run['trials'], seed=run['seed'])


def entry_dates(run, sessions):
    """The ISO entry days of a case's schedule: its random trials' dates, or its fixed periods' entries."""
    from backtest import calendar_requests
    mode, options = schedule(run)
    if mode == 'random':
        return {day for sample in calendar_requests.plan(sessions, options)['samples'] for day in sample}
    return {str(entry) for entry, _ in calendar_requests.periods(sessions, options)[0]}


def store_books(db, market, days):
    """Store the dated cached-pool book of each ISO day in days that is not stored yet."""
    from backtest.engines.original import book_batch
    from backtest.inputs import book_store
    stored = {entry for _, entry, latest in book_store.completed(db, 'cached', market=market) if not latest}
    jobs = [(day, 'cached') if market == 'us' else (day, 'cached', market) for day in days if day not in stored]
    with book_batch.calculations(db, jobs, book_batch.worker_count(db, jobs, None), lambda: None) as books:
        for book in books:
            with db:
                db.execute('BEGIN IMMEDIATE')
                book_store.store(db, book)
