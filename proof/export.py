"""Export the oracle's values as keyed tables in the neutral form.

    python3 proof/export.py (--raw DIR | --workspace DIR [--prepare]) --as-of TIME --out DIR
                            (--tests DIR | --market MARKET --random-days N [--tests DIR])

- `--raw DIR`: build a temporary oracle workspace from this checkout's Python
  product and the raw folder DIR (proof/oracle.py), prepare it, export and
  delete the workspace.
- `--workspace DIR`: use an oracle workspace folder with its own product. It
  is prepared already, or, with `--prepare`, it has no `data/` yet and the
  export prepares it first (with the limit of the pinned clock in
  proof/oracle.py: on a real-data workspace, give an as-of time after the close
  of each market's last saved calendar row). An export writes what any run writes into that
  folder's data: its cache lock and the dated books it needs.
- `--as-of TIME`: an ISO date-time with a UTC offset; the oracle's
  completed-session clock reads it as the current time.
- `--tests DIR`: every `*.json` file in DIR is one test request in intent form
  (proof/oracle.py); the file name without `.json` names the test.
- `--market MARKET` (us, hk or jp): export that market's prepared data and
  candidates. Without it, the export runs the tests and holds their summaries.
- `--random-days N`: the number of random sessions in a market's day set.
- `--out DIR`: the export folder; its table files are replaced.

The fictional fixture's expected exports (fixtures/fictional/expected/):

    python3 proof/export.py --raw fixtures/fictional/raw --as-of 2023-06-30T07:30:00+00:00 \\
        --tests fixtures/fictional/tests --out fixtures/fictional/expected/runs
    python3 proof/export.py --raw fixtures/fictional/raw --as-of 2023-06-30T07:30:00+00:00 \\
        --tests fixtures/fictional/tests --market us --random-days 40 --out fixtures/fictional/expected/us

and the same for hk and jp. At that time the Hong Kong session of 2023-06-30
has not closed (16:00 local), so the fixture's last Hong Kong session is
2023-06-29.

The export is the neutral form that the `tables` crate (crates/tables)
specifies and compares: `manifest.json` (`producer`, `settings`, `tables` with
each table's key fields) and one `<name>.jsonl` per table, flat rows in
ascending key order, numbers in Python's shortest round-trip spelling,
non-finite numbers as "NaN", "Infinity" or "-Infinity", a missing value as
null. `settings` record the as-of time and `backtest`, the git tree id of the
workspace's product. Running the same export twice writes the same bytes.

A market export holds the market's prepared data (L1) and its candidates on
the days of its day set (L2). `MARKET_TABLES = {name: (key fields,
rows(db, market, days))}` registers them: a rows function reads the daily
connection (research attached as `research`) and yields rows in key order,
which its SQL ORDER BY gives. Field names are the oracle's column names.
- `companies` (symbol): market, currency, name, exchange, sector, listed,
  priced (a saved price file), order (US: the position, from 1, of the first
  report in the statements table, which follows metrics.jsonl).
- `sessions` (day): US: the days with a SPY close; foreign: local_sessions.
- `market_days` (day): spy, month3, year10 and their reasons.
- `fx_days` (currency, day), Hong Kong and Tokyo only: usd, reason.
- `stock_days` (symbol, day): adjusted, volume and their reasons; foreign:
  local sessions only.
- `reports` (symbol, fiscal): US: the statements table; foreign:
  foreign_reports.
- `annual_facts` (symbol, endpoint, fiscal, column): value and reason, one row
  per column whose value or reason is not null.
- `annual_metadata` (symbol, endpoint, fiscal): currency, known, basis.
- `valuation_sums` (symbol, day): the three sums and their day counts.
- `candidates` (screen, day, symbol): the cached-pool book rows: screen
  `dated` on each day of the day set, `latest` on the latest session; the
  book_rows columns from candidate_rank on.
- `screens` (screen, day): reported (the books' candidates: companies with an
  eligible report) and admitted (its book rows).
The dated books are the oracle's own (oracle.store_books); the latest books
come from the preparation.

The day set, written as `days.txt` (one ISO day per line, ascending): the entry
days of the market's tests (oracle.entry_dates), the latest session, every
session from 1996-01-01 dated 29 February, and N sessions from 1996-01-01
drawn with random.Random(market).

A run export holds the test summaries, `RUN_TABLES = {name: (key fields,
rows(results))}` with results `{test name: result summary}` (oracle.run).
`trials` (key: test, trial) and `statistics` (key: test, statistic) are
provisional: they keep the oracle's result field names without the timing
fields, until the rewrite sets the product's result tables and this exporter
adapts to them.
- `trials`: one row per trial of a random test (its trial summary; `dates`
  joins the trial's trade dates with spaces) and one row (trial 1) per custom
  test (its summary); fields a summary lacks are null.
- `statistics`: per random test, `<field>.<statistic>` for each distribution
  (cagr, spy_cagr, excess_cagr, total_return, growth) and its n, mean,
  median, p10, p25, p75, p90, min, max and stddev, and the counts completed,
  valid, incomplete, beat_spy and unique_schedules. The value is `value`.
"""
import argparse
from contextlib import closing, nullcontext
from datetime import date, datetime
import json
import math
from pathlib import Path
import random
import tempfile

import oracle

TRIAL_FIELDS = ('start', 'first_trade', 'end', 'dates', 'cash_days', 'periods', 'cagr', 'spy_cagr', 'excess_cagr',
                'total_return', 'growth', 'spy_growth', 'empty_periods', 'short_periods')
DISTRIBUTIONS = ('cagr', 'spy_cagr', 'excess_cagr', 'total_return', 'growth')
STATISTICS = ('n', 'mean', 'median', 'p10', 'p25', 'p75', 'p90', 'min', 'max', 'stddev')
COUNTS = ('completed', 'valid', 'incomplete', 'beat_spy', 'unique_schedules')
STATISTIC_NAMES = sorted([f'{field}.{statistic}' for field in DISTRIBUTIONS for statistic in STATISTICS] + list(COUNTS))


def query(db, sql, *args):
    cursor = db.cursor()
    cursor.row_factory = None
    cursor.execute(sql, args)
    names = [column[0] for column in cursor.description]
    for row in cursor:
        yield dict(zip(names, row))


def in_market(table, extra=''):
    return (f'SELECT t.* FROM research.{table} t JOIN research.company_markets m USING(symbol) '
            f'WHERE m.market=?{extra} ORDER BY ')


def company_rows(db, market, days):
    from backtest.inputs import facts
    for row in query(db, '''SELECT c.symbol,m.market,m.currency,c.name,c.exchange,c.sector,c.listed,
            EXISTS(SELECT 1 FROM research.fact_sources f WHERE f.symbol=c.symbol AND f.endpoint=?
                   AND f.disposition!='missing') AS priced,o."order"
            FROM research.companies c JOIN research.company_markets m USING(symbol)
            LEFT JOIN (SELECT symbol,ROW_NUMBER() OVER (ORDER BY MIN(rowid)) AS "order"
                       FROM research.statements GROUP BY symbol) o USING(symbol)
            WHERE m.market=? ORDER BY c.symbol''', facts.STOCK, market):
        yield dict(row, listed=bool(row['listed']), priced=bool(row['priced']))


def session_rows(db, market, days):
    if market == 'us':
        return query(db, 'SELECT day FROM research.market_days WHERE spy IS NOT NULL ORDER BY day')
    return query(db, 'SELECT day FROM research.local_sessions WHERE market=? ORDER BY day', market)


def market_day_rows(db, market, days):
    return query(db, 'SELECT * FROM research.market_days ORDER BY day')


def fx_rows(db, market, days):
    return query(db, 'SELECT * FROM research.fx_days ORDER BY currency,day')


def stock_rows(db, market, days):
    session = '' if market == 'us' else (' AND EXISTS(SELECT 1 FROM research.local_sessions s '
                                         'WHERE s.market=m.market AND s.day=t.day)')
    return query(db, in_market('stock_days', session) + 't.symbol,t.day', market)


def report_rows(db, market, days):
    if market == 'us':
        return query(db, 'SELECT * FROM research.statements ORDER BY symbol,fiscal')
    return query(db, in_market('foreign_reports') + 't.symbol,t.fiscal', market)


def annual_fact_rows(db, market, days):
    rows = query(db, in_market('annual_facts') + 't.symbol,t.endpoint,t.fiscal', market)
    columns = None
    for row in rows:
        if columns is None:
            columns = sorted(name for name in row if name + '_reason' in row)
        for column in columns:
            value, reason = row[column], row[column + '_reason']
            if value is not None or reason is not None:
                yield dict(symbol=row['symbol'], endpoint=row['endpoint'], fiscal=row['fiscal'], column=column,
                           value=value, reason=reason)


def annual_metadata_rows(db, market, days):
    return query(db, in_market('annual_metadata') + 't.symbol,t.endpoint,t.fiscal', market)


def valuation_rows(db, market, days):
    return query(db, in_market('valuation_sums') + 't.symbol,t.day', market)


def books(db, market, days, columns, join, order):
    """Rows of the market's cached-pool books: the latest one and the dated ones of days."""
    return query(db, f"SELECT CASE b.latest WHEN 1 THEN 'latest' ELSE 'dated' END AS screen,b.entry AS day,{columns} "
                     f"FROM books b JOIN book_pools p ON p.book=b.book AND p.pool='cached'{join} WHERE b.market=? "
                     f"AND (b.latest=1 OR b.entry IN ({','.join('?' * len(days))})) ORDER BY {order}", market, *days)


def candidate_rows(db, market, days):
    for row in books(db, market, days, 'r.*', ' JOIN book_rows r ON r.book=b.book AND r.pool=p.pool',
                     'screen,day,r.symbol'):
        del row['book'], row['pool']
        yield row


def screen_rows(db, market, days):
    return books(db, market, days, 'b.candidates AS reported,'
                 '(SELECT COUNT(*) FROM book_rows r WHERE r.book=b.book AND r.pool=p.pool) AS admitted', '', 'screen,day')


MARKET_TABLES = {
    'companies': (('symbol',), company_rows),
    'sessions': (('day',), session_rows),
    'market_days': (('day',), market_day_rows),
    'fx_days': (('currency', 'day'), fx_rows),
    'stock_days': (('symbol', 'day'), stock_rows),
    'reports': (('symbol', 'fiscal'), report_rows),
    'annual_facts': (('symbol', 'endpoint', 'fiscal', 'column'), annual_fact_rows),
    'annual_metadata': (('symbol', 'endpoint', 'fiscal'), annual_metadata_rows),
    'valuation_sums': (('symbol', 'day'), valuation_rows),
    'candidates': (('screen', 'day', 'symbol'), candidate_rows),
    'screens': (('screen', 'day'), screen_rows),
}


def trial_rows(results):
    for test, summary in results.items():
        for number, trial in enumerate(summary['trials'] if summary.get('kind') == 'random_dates' else [summary], 1):
            row = dict(test=test, trial=number, **{field: trial.get(field) for field in TRIAL_FIELDS})
            if row['dates'] is not None:
                row['dates'] = ' '.join(row['dates'])
            yield row


def statistic_rows(results):
    for test, summary in results.items():
        if summary.get('kind') != 'random_dates':
            continue
        for name in STATISTIC_NAMES:
            field, _, statistic = name.partition('.')
            yield dict(test=test, statistic=name,
                       value=summary['distributions'][field][statistic] if statistic else summary[name])


RUN_TABLES = {
    'trials': (('test', 'trial'), trial_rows),
    'statistics': (('test', 'statistic'), statistic_rows),
}


def day_set(db, market, tests, count):
    """The ISO days of a market export's candidates, ascending."""
    from backtest.financial import rules
    sessions = [date.fromisoformat(row['day']) for row in session_rows(db, market, None)]
    eligible = [str(day) for day in sessions if day >= rules.FIRST_DAY]
    days = {eligible[-1]} | {day for day in eligible if day[5:] == '02-29'}
    for request in tests.values():
        if request['options'].get('market', 'us') == market:
            days |= oracle.entry_dates(request, sessions)
    days |= set(random.Random(market).sample(eligible, count))
    return sorted(days)


def neutral(value):
    if isinstance(value, float) and not math.isfinite(value):
        return 'NaN' if value != value else 'Infinity' if value > 0 else '-Infinity'
    return value


def write(out, settings, tables):
    """Write each table's rows, as they come, and the manifest; return {name: row count}."""
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, (keys, rows) in tables.items():
        counts[name] = 0
        with open(out / f'{name}.jsonl', 'w', encoding='utf-8', newline='\n') as file:
            for row in rows:
                file.write(json.dumps({key: neutral(value) for key, value in row.items()}, ensure_ascii=False,
                                      separators=(',', ':'), allow_nan=False) + '\n')
                counts[name] += 1
    manifest = dict(producer='python-oracle', settings=settings,
                    tables={name: list(keys) for name, (keys, _) in tables.items()})
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1) + '\n', encoding='utf-8', newline='\n')
    return counts


def as_of(text):
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        raise argparse.ArgumentTypeError('give the time with a UTC offset')
    return value


def main():
    parser = argparse.ArgumentParser(description='Export the oracle\'s values as keyed tables in the neutral form.')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--raw', type=Path)
    source.add_argument('--workspace', type=Path)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--as-of', type=as_of, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--tests', type=Path)
    parser.add_argument('--market', choices=('us', 'hk', 'jp'))
    parser.add_argument('--random-days', type=int)
    args = parser.parse_args()
    if args.prepare and (args.workspace is None or (args.workspace / 'data').exists()):
        parser.error('--prepare needs a --workspace without data/')
    if (args.market is None) != (args.random_days is None) or (args.market is None and args.tests is None):
        parser.error('give --tests, or --market with --random-days')
    tests = {path.stem: json.loads(path.read_text(encoding='utf-8'))
             for path in sorted(args.tests.glob('*.json'), key=lambda path: path.stem)} if args.tests else {}
    with tempfile.TemporaryDirectory() if args.workspace is None else nullcontext(args.workspace) as folder:
        if args.workspace is None:
            oracle.build(args.raw, folder)
        oracle.load(folder)
        if args.workspace is None or args.prepare:
            oracle.prepare(args.as_of)
        settings = dict(as_of=args.as_of.isoformat(), backtest=oracle.tree(folder), tests=list(tests))
        if args.market is None:
            results = {name: oracle.run(request, args.as_of) for name, request in tests.items()}
            counts = write(args.out, settings, {name: (keys, rows(results)) for name, (keys, rows) in RUN_TABLES.items()})
        else:
            settings.update(market=args.market, random_days=args.random_days)
            with closing(oracle.connect()) as db:
                days = day_set(db, args.market, tests, args.random_days)
                oracle.store_books(db, args.market, days)
                counts = write(args.out, settings, {name: (keys, rows(db, args.market, days))
                                                    for name, (keys, rows) in MARKET_TABLES.items()
                                                    if name != 'fx_days' or args.market != 'us'})
            (args.out / 'days.txt').write_text(''.join(day + '\n' for day in days), encoding='utf-8', newline='\n')
    print(f'Exported to {args.out}: ' + ', '.join(f'{name} {count}' for name, count in counts.items()))


if __name__ == '__main__':
    main()
