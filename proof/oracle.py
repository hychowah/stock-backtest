"""Drive the Python product (the oracle) in this process: workspace, preparation, clock and runs.

The product resolves every file location from its own source folder
(backtest/paths.py), so an oracle workspace is a folder that holds a copy of
`backtest/` beside `raw/` and `data/`. Its data and its cache lock
(data/website-data-0.lock) belong to that folder only; the checkout's own
`data/` and `raw/` are never read or written.

- `build(raw, folder)` copies this checkout's `backtest/` and a raw folder into
  `folder`.
- `load(folder)` imports the product from a workspace: a built one or an
  already prepared runtime folder. Call it once, before any other function.
- `prepare(as_of)` runs the ordinary preparation (research, then the daily
  cache) with the clock pinned.
- `run(request, as_of)` runs one strategy request in process (no queue, no
  server) with the clock pinned, and returns the result summary.

The only clock that changes results is the completed-session test of the
local index calendars (`completed_session` in backtest/inputs/market.py). It
reads `datetime.now`; `pinned(as_of)` makes it read `as_of` instead.

A request is one test in intent form, as the website submits it:
`{mode, options, intent, submitted?, labels?}`. `mode` is "random" or
"custom"; `options` are the calculation options without the strategy
(market, start, end, months, and for random trials and seed); `intent` is a
strategy-intent; `submitted` and `labels` carry the formula definitions and
names that the intent's formula sources name.
"""
from contextlib import contextmanager
import datetime
from pathlib import Path
import shutil
import sys
import tempfile

CHECKOUT = Path(__file__).resolve().parents[1]


def build(raw, folder):
    """Make folder an unprepared oracle workspace of this checkout's product and raw."""
    shutil.copytree(CHECKOUT / 'backtest', Path(folder) / 'backtest', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(raw, Path(folder) / 'raw')


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


def run(request, as_of):
    """Capture the request's strategy as the website does, run it and return the result summary."""
    from backtest.application import variable_authoring
    from backtest.application.original_calculations import Original
    options = request['options']
    capture = dict(market=options['market'], intent=request['intent'],
                   submitted=request.get('submitted', []), labels=request.get('labels', []))
    strategy = variable_authoring.prepare(capture, None)['strategy']
    with pinned(as_of), tempfile.TemporaryFile() as destination:
        result = Original().calculate_into(request['mode'], dict(options, strategy=strategy), destination, None, None)
    return result['manifest']['summary']
