"""Run the old product's managed data update (the oracle) on stored provider replies, and freeze its results.

    python3 proof/update.py cases [--out DIR]
    python3 proof/update.py run WORKSPACE --as-of TIME (--replies FILE | --later RAW | --live-provider)
                                [--raw RAW] [--record FILE] [--prepare]
    python3 proof/update.py seed OLD_JSON HOME

The reply store
---------------
A reply store is a JSONL file, one line per provider reply:

    {"endpoint": E, "params": {NAME: VALUE, ...}, "status": S, "retry_after": R, "body": B}

- `endpoint` is the path after `/stable/`, such as `historical-price-eod/full`.
- `params` are the query's parameters, decoded, every value a string, without
  the account key. A request matches a line when the endpoint is equal and the
  parameters are equal as a set of name and value pairs; their order in the
  line does not matter (the files written here sort them).
- `status` is the HTTP status. Status 0 is a connection closed without a reply.
- `retry_after` is the text of the Retry-After header; the key is absent when
  the reply had none.
- `body` is the exact text of the reply, after any gzip decoding. A status 0
  line has an empty body.
- The lines of one request are served in file order, one line per attempt,
  and the last one repeats for any later attempt. A request with no line is
  an error of the store, not a reply.

A store written here groups the lines by request, the requests in the order
of their sorted (endpoint, parameters), and each request's lines in the
order of its attempts.

The harness (`run`)
-------------------
`run` runs the oracle's managed update (`data_refresh.run`: no scope, no
Continue), as the nightly update starts it, in the oracle workspace
WORKSPACE: a folder that holds a copy of this checkout's `backtest/` and
`website/` (added when absent) beside `raw/` and `data/`. With `--raw RAW`,
WORKSPACE must not exist and is made with a private copy of RAW (each file
hard-linked where it can be, except `metrics.jsonl`, which the oracle appends
to in place, and `*.download` files, which it rewrites in place); without it,
WORKSPACE/raw is the cache, and it is changed. `--record FILE` copies an old
`data/data-refresh.json` into the workspace first.

The single attempt of the provider client (`fmp_download.Client._once`) is
replaced; it takes its reply from one source:
- `--replies FILE`, a reply store;
- `--later RAW`, the synthesizer below;
- `--live-provider`, the real provider through the oracle's own attempt. This
  source makes real requests with the account key. It runs only with this
  flag. The key never reaches the store, the request list or the output: the
  recorded parameters are those the client gives the attempt, which adds the
  key itself, and a body that contains the key is stored with the key
  replaced by `[key]`.

With the first two sources the client runs one worker and no pacing or
retry waits (the waits change no file), so the update is repeatable: it
appends new `metrics.jsonl` lines in symbol order. Those sources also point
the key file at a missing path and refuse to open a connection. The live
provider keeps the oracle's 32 workers, pacing and waits.

The clock is pinned to TIME (an ISO date-time with a UTC offset): the
update's `datetime.now` (the price target day: the date of TIME less 22
hours in UTC; the Hong Kong date of the report policy; the record's times)
and `date.today()` of the data options (the date of TIME in its own offset).
Preparation (the research and daily caches, the website build, the sheets and
their check) is stubbed out unless `--prepare` is given; then it runs with
the completed-session clock pinned to TIME too (proof/oracle.py).

`run` writes, in WORKSPACE/update/:
- `replies.jsonl`: every attempt, as a reply store;
- `requests.jsonl`: every attempt as `{"endpoint", "params"}`, one line per
  attempt, the lines sorted as JSON text;
- `end.json`: the update's `outcome`, its `failed` items (a sorted list that
  keeps repeats; the oracle names a price series by its raw file and a report
  by `<endpoint>/<symbol>`) and its `memory` (below).

An error of the reply source (a request the store does not hold, a later
file that cannot be read) ends the run with a non-zero exit.

Synthesized replies (`--later RAW`)
-----------------------------------
The synthesizer answers as the provider would have to answer for the oracle
to end with the raw cache RAW (a later copy of the cache). When RAW is
several nights later, the end differs from RAW in the order of new company
rows and of new `metrics.jsonl` lines, in key-metrics files made from the
`metrics.jsonl` fallback, and in the delisted list's pages. It serves:
- `company-screener` with an exchange: the companies of RAW's list for that
  exchange (`universe.json` for NYSE, NASDAQ and AMEX, the market's
  `markets/<m>/universe.json` otherwise) whose `listed` equals
  `isActivelyTrading`, in file order, paged by `limit` and `page`;
- `delisted-companies`: the companies of `universe.json` that are not listed,
  paged the same way;
- `key-metrics`, `ratios` and the three statements (income, balance sheet,
  cash flow): the `rows` of `financial-inputs/<endpoint>/<symbol>.json`, or
  for key-metrics without that file the rows of the symbol's last
  `metrics.jsonl` line, or an empty list;
- `historical-price-eod/dividend-adjusted`: the rows of the `div` list of
  `px/<symbol>.json` (of `spy-div.json` for SPY, a plain list) dated from
  `from` to `to`, in file order;
- `historical-price-eod/full`: the same from `markets/<m>/calendar.json` for
  an index (^HSI, ^N225), `fx/<symbol>.json` for USDxxx, `px-full/` otherwise;
- `treasury-rates`: the rows of `treasury.json` from `from` to `to`.
A missing file gives an empty list. Bodies are compact JSON. A saved row
that the oracle removed because the provider gave it a non-positive adjusted
close cannot be told from RAW: the synthesized reply leaves the day out, and
the oracle keeps the saved row.

The fictional cases (`cases`)
-----------------------------
`cases` writes fixtures/fictional/update/ (or DIR): two update nights on the
fictional raw (fixtures/fictional/raw) without `markets/jp` (the oracle also
updates Tokyo when `markets/jp/universe.json` exists). Each case folder
holds:
- `case.json`: `as_of`; `after`, the case whose end it starts from, or null;
  `record`, the old `data/data-refresh.json` the oracle starts with; and
  `memory`, the same as the new record's memory (`seed` of `record`);
- `before/`, raw files laid over the start (only `saturday`);
- `replies.jsonl` and `requests.jsonl`, as `run` writes them;
- `after/`, every raw file the update added or changed, except the download
  ledger `download-coverage.json`, which is not compared;
- `end.json`: as `run` writes it, plus `deleted`, the raw files it removed.
A case's start raw is the fictional raw without `markets/jp`; then, when
`after` names a case, that case's start and its `after/` files; then the
case's own `before/` files. The oracle of `monday` also starts with the
ledger that `saturday` left, as on a real night. The ledger is not in the
fixture, so `monday` replays only after `saturday` has run, as `cases` does.
With it, the old updater asks only the last 7 days of an empty history (QNX,
0107.HK), the rule the new updater keeps without a ledger (without it, the
old updater asks such a history from 1995 again), and 0107.HK leaves pending
on `monday`: the old completeness test of a statement file needs the
ledger's receipt for it.

In both cases the Hong Kong pass asks SPY and the Treasury again after the
US pass: three requests, SPY's recent window and the Treasury's split at the
month start. On `monday` they equal the US pass's requests, so each appears
twice in `requests.jsonl`.

Each case is run twice: on synthesized replies with a few scripted
attempts in front, which writes its reply store, then on that store alone;
the two runs must make the same requests and leave the same raw bytes.

- `saturday`, 2023-07-08 07:00 in Hong Kong (prices through 2023-07-07),
  reports due and the 90-day sweep due (last check 2023-07-01, last sweep
  2023-03-25), with QAC (US) and 0103.HK pending:
  - a week of new rows for every price file of a trading company, SPY, the
    Treasury, the Hong Kong calendar and USDHKD;
  - new US listings QNW (complete data: leaves pending) and QNX (no data
    yet: empty files, stays pending), the delisted-list newcomer QZZ (prices,
    no reports: stays pending), and two refused rows (an ETF name, a dot);
  - QNR, listed before without any data (`before/`), now reported: it becomes pending
    and a price target in the same update (its reply also holds `-0`, `1E+2`,
    an exponent float, a 20-digit integer and escaped text);
  - new Hong Kong listings 0107.HK (no data yet: stays pending) and 0108.HK
    (complete data, reports in CNY: USDCNY starts), refused 4102.HK and
    2800.HK, 0106.HK no longer trading, and the saved 4101.HK and 80101.HK
    no longer listed (the symbol rule refuses them);
  - 0109.HK, saved as not listed and never priced (`before/`), reports in SGD: the
    sweep asks its statements, so USDSGD starts;
  - QPX delisted (no sector in the delisted list: the saved one stays);
  - QAA: a dividend changes the overlapping adjusted closes; the whole
    history is asked again and replaces the file;
  - QAB: the same, but the whole history lacks 2018-03-14: the item fails;
  - QAC: a zero adjusted close on a saved day (that row is removed) and a
    negative one on a new day (left out);
  - QST: a new fiscal year (2020) with a changed fiscal-2019 value, in key
    metrics and the income statement; QCF: an income statement without the
    saved repeat of fiscal 2020 and with a changed fiscal 2021 (both saved
    rows stay);
  - QAD's recent prices: 429 with Retry-After 1, then success; QSP's: 500
    three times (the item fails); 0101.HK's recent native closes: a closed
    connection, then success.
  It ends partial (QAB and QSP fail), the report dates advance.
- `monday`, 2023-07-10 07:00 in Hong Kong, from the end of `saturday`;
  reports not due. QAB's whole history is complete now, QSP answers, QMN is
  newly listed (prices, stays pending), 0107.HK has its first prices (leaves
  pending) and USDSGD is not asked. It ends complete.

`seed OLD_JSON HOME`
--------------------
Writes HOME/data/update.json, the new updater's record, from an old
`data/data-refresh.json`: `{"memory": {...}}` with no `progress` (no update
has run). `memory` holds:
- `last_report_check`, `last_full_sweep`: ISO dates (Hong Kong), or null;
- `pending`: `{"us": [...], "hk": [...]}`, sorted symbols; the old
  `pending_symbols` and `pending_markets.hk` (Tokyo is left out);
- `last_success`: the old ISO date-time text, unchanged, or null.
It refuses to replace an existing HOME/data/update.json.
"""
import argparse
from contextlib import ExitStack
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import tempfile
import threading
from unittest.mock import patch

import fixture
import oracle

CHECKOUT = Path(__file__).resolve().parents[1]
FICTIONAL = CHECKOUT / 'fixtures' / 'fictional' / 'raw'
CASES = CHECKOUT / 'fixtures' / 'fictional' / 'update'
LEDGER = 'download-coverage.json'


# The reply store

def request_key(endpoint, params):
    return json.dumps([endpoint, sorted(params.items())])


def store_lines(attempts):
    """The reply store of attempts [(endpoint, params, reply)]: grouped by request, in attempt order."""
    groups = {}
    for endpoint, params, reply in attempts:
        groups.setdefault(request_key(endpoint, params), []).append(
            dict(endpoint=endpoint, params=dict(sorted(params.items())), **reply))
    return [line for key in sorted(groups) for line in groups[key]]


def request_lines(attempts):
    return sorted(json.dumps(dict(endpoint=endpoint, params=dict(sorted(params.items()))))
                  for endpoint, params, _ in attempts)


def write_jsonl(path, lines):
    path.write_text(''.join((line if isinstance(line, str) else json.dumps(line)) + '\n' for line in lines),
                    encoding='utf-8', newline='\n')


def reply(status, body='', retry_after=None):
    return dict(status=status, **({} if retry_after is None else dict(retry_after=retry_after)), body=body)


class Unanswered(BaseException):
    """A request that the source cannot answer; it ends the update instead of looking like a provider failure."""


class Store:
    def __init__(self, lines):
        self.lines, self.served, self.lock = {}, {}, threading.Lock()
        for line in lines:
            self.lines.setdefault(request_key(line['endpoint'], line['params']), []).append(
                reply(line['status'], line['body'], line.get('retry_after')))

    @classmethod
    def read(cls, path):
        return cls(json.loads(text) for text in Path(path).read_text(encoding='utf-8').split('\n') if text)

    def __call__(self, endpoint, params):
        key = request_key(endpoint, params)
        with self.lock:
            if key not in self.lines:
                raise Unanswered(f'no stored reply for {key}')
            count = self.served.get(key, 0)
            self.served[key] = count + 1
            return self.lines[key][min(count, len(self.lines[key]) - 1)]


class Synthesizer:
    """Replies from a later raw cache, after the scripted replies of `script` ({request key: [reply]})."""
    INDEX = {'^HSI': 'markets/hk/calendar.json', '^N225': 'markets/jp/calendar.json'}

    def __init__(self, later, script=None):
        self.later, self.script, self.lock, self.files = Path(later), dict(script or {}), threading.Lock(), {}
        self.metrics = None

    def load(self, relative, default):
        if relative not in self.files:
            path = self.later / relative
            self.files = {relative: json.loads(path.read_text(encoding='utf-8')) if path.exists() else default}
        return self.files[relative]

    def last_metrics(self, symbol):
        if self.metrics is None:
            path, self.metrics = self.later / 'metrics.jsonl', {}
            if path.exists():
                for text in path.read_text(encoding='utf-8').split('\n'):
                    if text.strip():
                        record = json.loads(text)
                        self.metrics[record['symbol']] = record['rows']
        return self.metrics.get(symbol, [])

    def __call__(self, endpoint, params):
        key = request_key(endpoint, params)
        with self.lock:
            if self.script.get(key):
                return self.script[key].pop(0)
            return reply(200, json.dumps(self.rows(endpoint, params), separators=(',', ':'), ensure_ascii=False))

    def rows(self, endpoint, params):
        file = file_name(params.get('symbol', ''))
        if endpoint == 'company-screener':
            exchange, listed = params['exchange'], params['isActivelyTrading'] == 'true'
            market = next(code for code, policy in markets().items() if exchange in policy['exchanges'])
            path = 'universe.json' if market == 'us' else f'markets/{market}/universe.json'
            rows = [screener_row(row, exchange) for row in self.load(path, [])
                    if row.get('exchange') == exchange and bool(row.get('listed')) == listed]
            return page(rows, params)
        if endpoint == 'delisted-companies':
            rows = [dict(symbol=row['symbol'], companyName=row.get('name', ''), exchange=row.get('exchange', ''))
                    for row in self.load('universe.json', []) if not row.get('listed')]
            return page(rows, params)
        if endpoint in ('key-metrics', 'income-statement', 'balance-sheet-statement', 'cash-flow-statement', 'ratios'):
            saved = self.load(f'financial-inputs/{endpoint}/{file}', None)
            if saved is not None:
                return saved['rows']
            return self.last_metrics(params['symbol']) if endpoint == 'key-metrics' else []
        if endpoint == 'historical-price-eod/dividend-adjusted':
            saved = self.load('spy-div.json' if params['symbol'] == 'SPY' else f'px/{file}', [])
            return dated(saved.get('div', []) if isinstance(saved, dict) else saved, params)
        if endpoint == 'historical-price-eod/full':
            symbol = params['symbol']
            if symbol in self.INDEX:
                path = self.INDEX[symbol]
            elif len(symbol) == 6 and symbol.startswith('USD') and symbol.isalpha() and symbol.isupper():
                path = f'fx/{symbol}.json'
            else:
                path = f'px-full/{file}'
            return dated(self.load(path, []), params)
        if endpoint == 'treasury-rates':
            return dated(self.load('treasury.json', []), params)
        raise Unanswered(f'no synthesized reply for {endpoint}')


def markets():
    from backtest.inputs import market
    return market.MARKETS


def file_name(symbol):
    from backtest.inputs import market
    return market.cache_path_for(symbol).name if symbol else ''


def screener_row(row, exchange):
    result = dict(symbol=row['symbol'], companyName=row.get('name', ''), sector=row.get('sector', ''),
                  exchangeShortName=exchange, isEtf=False, isFund=False, isActivelyTrading=bool(row.get('listed')))
    if 'currency' in row:
        result['currency'] = row['currency']
    return result


def page(rows, params):
    size, number = int(params['limit']), int(params['page'])
    return rows[number * size:(number + 1) * size]


def dated(rows, params):
    return [row for row in rows if params['from'] <= str(row.get('date', ''))[:10] <= params['to']]


# The harness

def build_workspace(folder, raw=None):
    """Add this checkout's product to folder, and, given raw, a private copy of it as folder/raw."""
    folder = Path(folder)
    if raw is not None:
        if folder.exists():
            raise SystemExit(f'{folder} exists; --raw makes a new workspace')
        link_copy(Path(raw), folder / 'raw')
    elif not (folder / 'raw').is_dir():
        raise SystemExit(f'{folder} has no raw/')
    for name, ignore in (('backtest', ('__pycache__',)), ('website', ('__pycache__', 'local', 'dist', 'node_modules', '.git'))):
        if not (folder / name).exists():
            shutil.copytree(CHECKOUT / name, folder / name, ignore=shutil.ignore_patterns(*ignore))


def link_copy(source, target):
    for directory, _, names in os.walk(source):
        destination = target / Path(directory).relative_to(source)
        destination.mkdir(parents=True, exist_ok=True)
        for name in names:
            if name == 'metrics.jsonl' or name.endswith('.download'):
                shutil.copy2(Path(directory) / name, destination / name)
                continue
            try:
                os.link(Path(directory) / name, destination / name)
            except OSError:
                shutil.copy2(Path(directory) / name, destination / name)


def pinned_clock(as_of):
    class Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return as_of.astimezone(tz)

    class Today(date):
        @classmethod
        def today(cls):
            return as_of.date()

    return Now, Today


def update(workspace, as_of, source, *, live=False, prepare=False):
    """Run the oracle's managed update in the loaded workspace; return (attempts, failed items, record)."""
    from backtest.engines.original import book_batch
    from backtest.inputs import daily, fmp_download
    from website.server import data_manager, data_refresh

    attempts, failed, lock = [], [], threading.Lock()
    ordinary_once, ordinary_failed = fmp_download.Client._once, data_refresh.failed

    def attempt(client, endpoint, params):
        query = {name: str(value) for name, value in params.items()}
        if live:
            status, body, retry_after = ordinary_once(client, endpoint, params)
            text = body.decode('utf-8', errors='replace')
            if client.key and client.key in text:
                text = text.replace(client.key, '[key]')
            answer = reply(status, text, retry_after)
        else:
            try:
                answer = source(endpoint, query)
            except Exception as error:
                raise Unanswered(f'the reply source failed ({type(error).__name__}) for {request_key(endpoint, query)}') from None
        with lock:
            attempts.append((endpoint, query, answer))
        if live:
            return status, body, retry_after
        return answer['status'], answer['body'].encode('utf-8'), answer.get('retry_after')

    def record_failure(state, asset, error=None):
        failed.append(asset)
        return ordinary_failed(state, asset, error)

    class Sequential(fmp_download.Client):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **dict(kwargs, workers=1))

    def no_connection(client):
        raise Unanswered('the harness opens no connection')

    class Closed:
        def close(self):
            pass

    Now, Today = pinned_clock(as_of)
    with ExitStack() as stack:
        stack.enter_context(patch.object(data_refresh, 'datetime', Now))
        stack.enter_context(patch.object(data_manager, 'date', Today))
        stack.enter_context(patch.object(fmp_download.Client, '_once', attempt))
        stack.enter_context(patch.object(data_refresh, 'failed', record_failure))
        if not live:
            stack.enter_context(patch.object(fmp_download, 'Client', Sequential))
            stack.enter_context(patch.object(fmp_download, 'KEY_PATH', Path(workspace) / 'no-key'))
            stack.enter_context(patch.object(fmp_download.Client, '_connection', no_connection))
            stack.enter_context(patch.object(fmp_download.StartGate, 'enter', lambda gate, client: client.check()))
        if prepare:
            stack.enter_context(oracle.pinned(as_of))
        else:
            stack.enter_context(patch.object(data_manager, 'rebuild', lambda emit, stop: None))
            stack.enter_context(patch.object(book_batch, 'precompute', lambda db, emit, stop: None))
            stack.enter_context(patch.object(daily, 'connect', lambda: Closed()))
            stack.enter_context(patch.object(data_manager, 'derived_status', lambda: []))
        try:
            data_refresh.run()
        except Unanswered as error:
            raise SystemExit(f'the update stopped: {error}') from None
    record = json.loads((Path(workspace) / 'data' / 'data-refresh.json').read_text(encoding='utf-8'))
    return attempts, sorted(failed), record


def end_summary(failed, record):
    return dict(outcome=record.get('outcome'), failed=failed, memory=memory(record))


def write_outputs(folder, attempts, summary):
    folder.mkdir(parents=True, exist_ok=True)
    write_jsonl(folder / 'replies.jsonl', store_lines(attempts))
    write_jsonl(folder / 'requests.jsonl', request_lines(attempts))
    (folder / 'end.json').write_text(json.dumps(summary, indent=1, ensure_ascii=True) + '\n', encoding='utf-8', newline='\n')


def as_of_time(text):
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        raise argparse.ArgumentTypeError('give the time with a UTC offset')
    return value


def run_command(args):
    workspace = args.workspace.resolve()
    build_workspace(workspace, args.raw)
    if args.record is not None:
        (workspace / 'data').mkdir(exist_ok=True)
        shutil.copyfile(args.record, workspace / 'data' / 'data-refresh.json')
    if args.replies is not None:
        source = Store.read(args.replies)
    elif args.later is not None:
        source = Synthesizer(args.later)
    else:
        source = None
    oracle.load(workspace)
    attempts, failed, record = update(workspace, args.as_of, source, live=args.live_provider, prepare=args.prepare)
    write_outputs(workspace / 'update', attempts, end_summary(failed, record))
    print(f'{len(attempts)} attempts; {record.get("outcome")}, {len(failed)} failed items; output in {workspace / "update"}')


# seed

def memory(record):
    """The new record's memory from an old data-refresh.json record."""
    return dict(last_report_check=record.get('last_report_check'), last_full_sweep=record.get('last_full_sweep'),
                pending=dict(us=sorted(set(record.get('pending_symbols', []))),
                             hk=sorted(set((record.get('pending_markets') or {}).get('hk', [])))),
                last_success=record.get('last_success'))


def seed_command(args):
    record = json.loads(args.old.read_text(encoding='utf-8'))
    target = args.home / 'data' / 'update.json'
    if target.exists():
        raise SystemExit(f'{target} exists; it is not replaced')
    target.parent.mkdir(exist_ok=True)
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_text(json.dumps(dict(memory=memory(record)), indent=2) + '\n', encoding='utf-8', newline='\n')
    os.replace(temporary, target)
    print(f'Wrote {target}')


# The fictional cases

US_DAYS = ['2023-07-03', '2023-07-05', '2023-07-06', '2023-07-07']  # 2023-07-04 is a US holiday
WEEK_DAYS = ['2023-07-03', '2023-07-04', '2023-07-05', '2023-07-06', '2023-07-07']
SATURDAY_RECORD = dict(outcome='complete', last_success='2023-07-06T23:07:41.512903+00:00',
                       last_report_check='2023-07-01', last_full_sweep='2023-03-25',
                       pending_symbols=['QAC'], pending_markets=dict(hk=['0103.HK'], jp=['7101.T']))
# QNR's key-metrics reply, written by hand: number spellings that the old updater reads and writes back its own way.
QNR_METRICS = (
    '[{"symbol":"QNR","date":"2022-12-31","fiscalYear":"2022","period":"FY","reportedCurrency":"USD",'
    '"marketCap":1520000000,"enterpriseValue":1.71E+9,"evToEBITDA":7.125,"grahamNumber":-0,"evToSales":1E+2,'
    '"incomeQuality":2.5e-8,"workingCapital":98765432109876543210,"netDebtToEBITDA":0.30000000000000004,'
    '"note":"N\\u00e9on \\/ résumé \\ud835\\udd14"},'
    '{"symbol":"QNR","date":"2021-12-31","fiscalYear":"2021","period":"FY","reportedCurrency":"USD",'
    '"marketCap":1310000000,"enterpriseValue":1490000000,"evToEBITDA":6.5,"grahamNumber":12.0,"evToSales":1.0}]')


def read(folder, relative):
    return json.loads((folder / relative).read_text(encoding='utf-8'))


def save(folder, relative, value):
    path = folder / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(',', ':')), encoding='utf-8')


def days_between(first, last, closed=lambda day: False):
    return [str(day) for day in fixture.weekdays(date.fromisoformat(first), date.fromisoformat(last)) if not closed(day)]


def extend(rows, field, days, seed, digits=4):
    """Rows (newest first) with a row for each new day put in front, continuing the newest value."""
    rng, value, added = random.Random(seed), float(rows[0][field]), []
    for day in days:
        value *= 1 + rng.randint(-200, 215) / 10000
        row = dict(rows[0], date=day, **{field: round(value, digits)})
        if 'volume' in row:
            row['volume'] = rng.randint(20, 400) * 1000
        added.append(row)
    return added[::-1] + rows


def history(symbol, days, start, seed, shape):
    """A new price history (newest first): 'adjusted' rows in the provider's full shape, or 'close' rows."""
    rng, value, rows = random.Random(seed), float(start), []
    for day in days:
        value *= 1 + rng.randint(-200, 215) / 10000
        if shape == 'adjusted':
            low, high = round(value * .985, 4), round(value * 1.015, 4)
            rows.append(dict(symbol=symbol, date=day, adjOpen=round(value * .995, 4), adjHigh=high, adjLow=low,
                             adjClose=round(value, 4), volume=rng.randint(20, 400) * 1000))
        else:
            rows.append(dict(date=day, close=round(value, 4)))
    return rows[::-1]


def scaled(rows, before, factor):
    """A dividend's adjustment: every adjusted close dated before `before` times factor."""
    return [dict(row, adjClose=round(row['adjClose'] * factor, 4)) if row['date'] < before else row for row in rows]


def report_rows(symbol, currency, years, revenue, kind):
    rows = []
    for number, year in enumerate(years):
        sales = round(revenue * 1.06 ** number)
        base = dict(date=f'{year}-12-31', symbol=symbol, reportedCurrency=currency, period='FY')
        if kind == 'income-statement':
            rows.append(dict(base, revenue=sales, operatingIncome=round(sales * .18), ebit=round(sales * .18),
                             ebitda=round(sales * .22), netIncome=round(sales * .13), epsDiluted=round(sales * .13 / 4e8, 2),
                             interestExpense=round(sales * .01), weightedAverageShsOut=400000000))
        elif kind == 'balance-sheet-statement':
            rows.append(dict(base, totalStockholdersEquity=round(sales * .6), totalCurrentAssets=round(sales * .5),
                             totalCurrentLiabilities=round(sales * .3), totalDebt=round(sales * .2),
                             cashAndCashEquivalents=round(sales * .1)))
        elif kind == 'cash-flow-statement':
            rows.append(dict(base, freeCashFlow=round(sales * .1), commonDividendsPaid=-round(sales * .04)))
        elif kind == 'key-metrics':
            cap = round(sales * 1.4)
            rows.append(dict(base, marketCap=cap, enterpriseValue=cap + round(sales * .1), evToEBITDA=round((cap + sales * .1) / (sales * .22), 6)))
        else:
            rows.append(dict(base, currentRatio=round(1.4 + number / 20, 4), priceToEarningsRatio=round(14 + number / 2, 4)))
    return rows[::-1]


def statement_file(symbol, endpoint, rows):
    return dict(version=2, full_response=True, symbol=symbol, endpoint=endpoint, rows=rows)


def start_raw(folder):
    """Copy the fictional raw without markets/jp to folder."""
    shutil.copytree(FICTIONAL, folder)
    shutil.rmtree(folder / 'markets' / 'jp')


def saturday_before(raw, before):
    """Write the Saturday overlay into before/ and onto raw."""
    us = read(raw, 'universe.json') + [dict(symbol='QNR', name='Quartz Néon Resources', exchange='NYSE',
                                            sector='Energy', listed=True)]
    hk = read(raw, 'markets/hk/universe.json') + [dict(symbol='0109.HK', name='Harbour Tern Trading', exchange='HKSE',
                                                       sector='Industrials', listed=False, market='hk', currency='HKD')]
    for folder in (before, raw):
        save(folder, 'universe.json', us)
        save(folder, 'markets/hk/universe.json', hk)


def provider_saturday(start, folder):
    """The provider's data on the Saturday morning, as a raw cache that the synthesizer reads."""
    shutil.copytree(start, folder)
    us = read(folder, 'universe.json')
    for row in us:
        if row['symbol'] == 'QPX':
            row['listed'] = False
    us += [dict(symbol='QNW', name='Quartz Nova Works', exchange='NYSE', sector='Technology', listed=True),
           dict(symbol='QNX', name='Quartz Nexus Labs', exchange='NASDAQ', sector='', listed=True),
           dict(symbol='QETF', name='Quartz Index ETF', exchange='NYSE', sector='', listed=True),
           dict(symbol='QA.B', name='Quartz Alder Holdings Class B', exchange='NYSE', sector='Industrials', listed=True),
           dict(symbol='QZZ', name='Quartz Zephyr Mining', exchange='NYSE', sector='', listed=False)]
    save(folder, 'universe.json', us)
    hk = read(folder, 'markets/hk/universe.json')
    for row in hk:
        if row['symbol'] == '0106.HK':
            row['listed'] = False
        row.pop('isEtf', None)
    hk += [dict(symbol='0107.HK', name='Harbour Wren Shipping', exchange='HKSE', sector='Industrials', listed=True,
                market='hk', currency='USD'),
           dict(symbol='0108.HK', name='Harbour \U0001d514uill Holdings', exchange='HKSE', sector='Communication Services',
                listed=True, market='hk', currency='HKD'),
           dict(symbol='4102.HK', name='Harbour Line of Quartz Birch', exchange='HKSE', sector='Technology', listed=True,
                market='hk', currency='HKD'),
           dict(symbol='2800.HK', name='Harbour Tracker ETF', exchange='HKSE', sector='', listed=True, market='hk',
                currency='HKD')]
    save(folder, 'markets/hk/universe.json', hk)

    for symbol in ('QAA', 'QAB', 'QAC', 'QAD', 'QCF', 'QFS', 'QSP', 'QST'):
        rows = extend(read(folder, f'px/{symbol}.json')['div'], 'adjClose', US_DAYS, 'new:' + symbol)
        if symbol == 'QAA':
            rows = scaled(rows, '2023-07-05', .985)
        if symbol == 'QAB':
            rows = [row for row in scaled(rows, '2023-07-05', .99) if row['date'] != '2018-03-14']
        if symbol == 'QAC':
            rows = [dict(row, adjClose={'2023-06-28': 0.0, '2023-07-05': -1.25}.get(row['date'], row['adjClose']))
                    for row in rows]
        if symbol == 'QFS':
            rows[0]['adjClose'] = round(rows[0]['adjClose'])
        save(folder, f'px/{symbol}.json', dict(div=rows))
    us_sessions = lambda first, last: days_between(first, last, fixture.us_closed)
    save(folder, 'px/QNW.json', dict(div=history('QNW', us_sessions('2022-01-03', '2023-07-07'), 41, 'QNW', 'adjusted')))
    save(folder, 'px/QNR.json', dict(div=history('QNR', us_sessions('2021-06-01', '2023-07-07'), 23, 'QNR', 'adjusted')))
    save(folder, 'px/QZZ.json', dict(div=history('QZZ', us_sessions('2020-01-02', '2020-06-30'), 9, 'QZZ', 'adjusted')))
    save(folder, 'spy-div.json', extend(read(folder, 'spy-div.json'), 'adjClose', US_DAYS, 'new:SPY'))
    treasury, rng = read(folder, 'treasury.json'), random.Random('new:treasury')
    for day in US_DAYS:
        treasury.insert(0, dict(treasury[0], date=day, month3=round(treasury[0]['month3'] + rng.randint(-3, 3) / 100, 2),
                                year10=round(treasury[0]['year10'] + rng.randint(-3, 3) / 100, 2)))
    save(folder, 'treasury.json', treasury)
    for symbol in ('0101.HK', '0102.HK', '0103.HK', '0104.HK', '0105.HK', '0106.HK', '4101.HK', '80101.HK'):
        save(folder, f'px/{symbol}.json', dict(div=extend(read(folder, f'px/{symbol}.json')['div'], 'adjClose', WEEK_DAYS, 'new:' + symbol)))
        save(folder, f'px-full/{symbol}.json', extend(read(folder, f'px-full/{symbol}.json'), 'close', WEEK_DAYS, 'full:' + symbol, 3))
    save(folder, 'px/0108.HK.json', dict(div=history('0108.HK', days_between('2022-03-01', '2023-07-07'), 31, '0108.HK', 'adjusted')))
    save(folder, 'px-full/0108.HK.json', history('0108.HK', days_between('2022-03-01', '2023-07-07'), 33, 'full:0108.HK', 'close'))
    save(folder, 'markets/hk/calendar.json', extend(read(folder, 'markets/hk/calendar.json'), 'close', WEEK_DAYS, 'new:^HSI', 2))
    save(folder, 'fx/USDHKD.json', extend(read(folder, 'fx/USDHKD.json'), 'close', WEEK_DAYS, 'new:HKD'))
    save(folder, 'fx/USDCNY.json', history('USDCNY', days_between('2023-01-02', '2023-07-07'), 7.1, 'CNY', 'close'))
    save(folder, 'fx/USDSGD.json', history('USDSGD', days_between('2023-01-02', '2023-07-07'), 1.35, 'SGD', 'close'))

    statements = ('income-statement', 'balance-sheet-statement', 'cash-flow-statement')
    for symbol, revenue in (('QNW', 9e8), ('QNR', 1.2e9)):
        for endpoint in statements + ('key-metrics',):
            save(folder, f'financial-inputs/{endpoint}/{symbol}.json',
                 statement_file(symbol, endpoint, report_rows(symbol, 'USD', range(2019, 2023), revenue, endpoint)))
    for symbol, currency, revenue in (('0108.HK', 'CNY', 4e9), ('0109.HK', 'SGD', 6e8)):
        for endpoint in statements:
            save(folder, f'financial-inputs/{endpoint}/{symbol}.json',
                 statement_file(symbol, endpoint, report_rows(symbol, currency, range(2018, 2023), revenue, endpoint)))
    for row in us:
        symbol = row['symbol']
        metrics = folder / f'financial-inputs/key-metrics/{symbol}.json'
        if metrics.exists():
            years = [int(item['date'][:4]) for item in read(folder, f'financial-inputs/key-metrics/{symbol}.json')['rows']]
            save(folder, f'financial-inputs/ratios/{symbol}.json',
                 statement_file(symbol, 'ratios', report_rows(symbol, 'USD', sorted(years), 1e9, 'ratios')))
    # QST reports fiscal 2020 late and revises fiscal 2019.
    for endpoint, field in (('key-metrics', 'marketCap'), ('income-statement', 'revenue')):
        saved = read(folder, f'financial-inputs/{endpoint}/QST.json')
        rows = [dict(row, **{field: round(row[field] * 1.05)}) if row['date'] == '2019-12-31' else row for row in saved['rows']]
        newest = dict(rows[0], date='2020-12-31', **{field: round(rows[0][field] * 1.1)})
        save(folder, f'financial-inputs/{endpoint}/QST.json', dict(saved, rows=[newest] + rows))
    # QCF's income statement no longer repeats fiscal 2020 and revises fiscal 2021.
    saved, rows, seen = read(folder, 'financial-inputs/income-statement/QCF.json'), [], set()
    for row in saved['rows']:
        text = json.dumps(row, sort_keys=True)
        if row['date'] == '2020-12-31' and text in seen:
            continue
        seen.add(text)
        rows.append(dict(row, netIncome=row['netIncome'] + 3_000_000) if row['date'] == '2021-12-31' else row)
    save(folder, 'financial-inputs/income-statement/QCF.json', dict(saved, rows=rows))


def provider_monday(saturday, folder):
    """The provider's data on the Monday morning: the Saturday's, QAB complete, QMN listed and 0107.HK priced."""
    shutil.copytree(saturday, folder)
    rows = read(folder, 'px/QAB.json')['div']
    original = {row['date']: row for row in read(FICTIONAL, 'px/QAB.json')['div']}
    missing = dict(original['2018-03-14'], adjClose=round(original['2018-03-14']['adjClose'] * .99, 4))
    save(folder, 'px/QAB.json', dict(div=sorted(rows + [missing], key=lambda row: row['date'], reverse=True)))
    us = read(folder, 'universe.json') + [dict(symbol='QMN', name='Quartz Meadow Foods', exchange='NYSE',
                                               sector='Consumer Defensive', listed=True)]
    save(folder, 'universe.json', us)
    save(folder, 'px/QMN.json', dict(div=history('QMN', days_between('2023-01-03', '2023-07-07', fixture.us_closed),
                                                 17, 'QMN', 'adjusted')))
    save(folder, 'px/0107.HK.json', dict(div=history('0107.HK', WEEK_DAYS, 2.4, '0107.HK', 'adjusted')))
    save(folder, 'px-full/0107.HK.json', history('0107.HK', WEEK_DAYS, 2.5, 'full:0107.HK', 'close'))


def saturday_script():
    window = dict(to='2023-07-07')
    return {
        request_key('historical-price-eod/dividend-adjusted', dict(window, symbol='QAD', **{'from': '2023-06-23'})):
            [reply(429, '{"Error Message":"Limit Reach. Please wait and retry."}', '1')],
        request_key('historical-price-eod/dividend-adjusted', dict(window, symbol='QSP', **{'from': '2023-06-23'})):
            [reply(500, 'Internal Server Error')] * 3,
        request_key('historical-price-eod/full', dict(window, symbol='0101.HK', **{'from': '2023-06-23'})): [reply(0)],
        request_key('key-metrics', dict(symbol='QNR', period='annual', limit='40')): [reply(200, QNR_METRICS)],
    }


def snapshot(raw):
    return {path.relative_to(raw).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in raw.rglob('*') if path.is_file()}


def reset(workspace, raw, record):
    for name in ('raw', 'data'):
        if (workspace / name).exists():
            shutil.rmtree(workspace / name)
    shutil.copytree(raw, workspace / 'raw')
    (workspace / 'data').mkdir()
    (workspace / 'data' / 'data-refresh.json').write_text(json.dumps(record), encoding='utf-8')


def night(workspace, start, record, as_of, source):
    """Run one update from start; return its attempts, summary and the raw files it changed or removed."""
    reset(workspace, start, record)
    before = snapshot(workspace / 'raw')
    attempts, failed, end = update(workspace, as_of, source)
    after = snapshot(workspace / 'raw')
    changed = {name: (workspace / 'raw' / name).read_bytes() for name, digest in after.items()
               if name != LEDGER and before.get(name) != digest}
    deleted = sorted(set(before) - set(after) - {LEDGER})
    return attempts, dict(end_summary(failed, end), deleted=deleted), changed, end


def kept_record(end):
    """The fields of an old record that the next update reads."""
    return {key: end[key] for key in ('outcome', 'last_success', 'last_report_check', 'last_full_sweep',
                                      'pending_symbols', 'pending_markets') if key in end}


def write_case(folder, name, as_of, after_case, record, attempts, summary, changed, before=None):
    case = folder / name
    case.mkdir(parents=True)
    (case / 'case.json').write_text(json.dumps(dict(as_of=as_of.isoformat(), after=after_case, record=record,
                                                    memory=memory(record)), indent=1) + '\n', encoding='utf-8', newline='\n')
    if before is not None:
        shutil.copytree(before, case / 'before')
    write_outputs(case, attempts, summary)
    for relative, content in changed.items():
        path = case / 'after' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def cases_command(args):
    out = args.out.resolve()
    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        workspace, start = scratch / 'workspace', scratch / 'start-saturday'
        start_raw(start)
        saturday_before(start, scratch / 'before')
        shutil.copytree(start, workspace / 'raw')
        build_workspace(workspace)
        oracle.load(workspace)
        provider_saturday(start, scratch / 'provider-saturday')
        provider_monday(scratch / 'provider-saturday', scratch / 'provider-monday')
        runs = {}
        nights = (('saturday', datetime(2023, 7, 7, 23, tzinfo=timezone.utc), None, scratch / 'provider-saturday', saturday_script),
                  ('monday', datetime(2023, 7, 9, 23, tzinfo=timezone.utc), 'saturday', scratch / 'provider-monday', dict))
        for name, as_of, after_case, provider, script in nights:
            record = SATURDAY_RECORD if after_case is None else kept_record(runs[after_case]['end'])
            begin = start if after_case is None else runs[after_case]['end_raw']
            attempts, summary, changed, end = night(workspace, begin, record, as_of, Synthesizer(provider, script()))
            end_raw = scratch / ('end-' + name)
            shutil.copytree(workspace / 'raw', end_raw)
            replayed = night(workspace, begin, record, as_of, Store(store_lines(attempts)))
            if (request_lines(replayed[0]), replayed[1], replayed[2]) != (request_lines(attempts), summary, changed):
                raise SystemExit(f'{name}: the replay of the recorded replies does not give the same update')
            if store_lines(replayed[0]) != store_lines(attempts):
                raise SystemExit(f'{name}: the replay served other replies')
            runs[name] = dict(end=end, end_raw=end_raw)
            write_case(scratch / 'cases', name, as_of, after_case, record, attempts, summary, changed,
                       scratch / 'before' if after_case is None else None)
            print(f'{name}: {len(attempts)} attempts, {len(changed)} files changed, {summary["outcome"]}, '
                  f'failed {summary["failed"]}')
        if out.exists():
            shutil.rmtree(out)
        shutil.copytree(scratch / 'cases', out)
    files = [path for path in out.rglob('*') if path.is_file()]
    print(f'Wrote {len(files)} files, {sum(path.stat().st_size for path in files) / 1e6:.2f} MB, in {out}')


def main():
    parser = argparse.ArgumentParser(description='Run the oracle\'s managed data update on stored provider replies.')
    commands = parser.add_subparsers(dest='command', required=True)
    cases = commands.add_parser('cases', help='write the fictional update cases')
    cases.add_argument('--out', type=Path, default=CASES)
    run = commands.add_parser('run', help='run one update in an oracle workspace')
    run.add_argument('workspace', type=Path)
    run.add_argument('--as-of', type=as_of_time, required=True)
    sources = run.add_mutually_exclusive_group(required=True)
    sources.add_argument('--replies', type=Path)
    sources.add_argument('--later', type=Path)
    sources.add_argument('--live-provider', action='store_true')
    run.add_argument('--raw', type=Path)
    run.add_argument('--record', type=Path)
    run.add_argument('--prepare', action='store_true')
    seed = commands.add_parser('seed', help='write the new update record from an old data-refresh.json')
    seed.add_argument('old', type=Path)
    seed.add_argument('home', type=Path)
    args = parser.parse_args()
    dict(cases=cases_command, run=run_command, seed=seed_command)[args.command](args)


if __name__ == '__main__':
    main()
