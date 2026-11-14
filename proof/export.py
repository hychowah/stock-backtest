"""Export the oracle's values as keyed tables in the neutral form.

    python3 proof/export.py (--raw DIR | --workspace DIR) --as-of TIME --out DIR
                            [--tests DIR] [--tables NAME ...]

- `--raw DIR`: build a temporary oracle workspace from this checkout's Python
  product and the raw folder DIR (proof/oracle.py), prepare it, run the tests
  and delete the workspace.
- `--workspace DIR`: use an oracle runtime folder that is already prepared,
  with its own product; nothing is prepared. A run still writes what any run
  writes into that folder's data (its cache lock, and books that a test needs
  and that are not yet stored).
- `--as-of TIME`: an ISO date-time with a UTC offset; the oracle's
  completed-session clock reads it as the current time.
- `--tests DIR`: every `*.json` file in DIR is one test request in intent form
  (proof/oracle.py); the file name without `.json` names the test.
- `--out DIR`: the export folder; its table files are replaced.
- `--tables NAME ...`: export only these tables (default: all).

Example, the fictional fixture's expected export:

    python3 proof/export.py --raw fixtures/fictional/raw --as-of 2023-06-30T07:30:00+00:00 \\
        --tests fixtures/fictional/tests --out fixtures/fictional/expected

At that time the Hong Kong session of 2023-06-30 has not closed (16:00 local),
so the fixture's last Hong Kong session is 2023-06-29.

The export is the neutral form that the `tables` crate (crates/tables)
specifies and compares: `manifest.json` (`producer`, `settings`, `tables` with
each table's key fields) and one `<name>.jsonl` per table, flat rows in
ascending key order, numbers in Python's shortest round-trip spelling,
non-finite numbers as "NaN", "Infinity" or "-Infinity", a missing value as
null. Running the same export twice writes the same bytes.

`TABLES = {name: (key_fields, rows_function)}` registers every table.
`rows_function(results)` takes `{test name: result summary}` (oracle.run) and
yields flat rows that hold the key fields; add a table by adding an entry.
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
from contextlib import nullcontext
from datetime import datetime
import json
import math
from pathlib import Path
import tempfile

import oracle

TRIAL_FIELDS = ('start', 'first_trade', 'end', 'dates', 'cash_days', 'periods', 'cagr', 'spy_cagr', 'excess_cagr',
                'total_return', 'growth', 'spy_growth', 'empty_periods', 'short_periods')
DISTRIBUTIONS = ('cagr', 'spy_cagr', 'excess_cagr', 'total_return', 'growth')
STATISTICS = ('n', 'mean', 'median', 'p10', 'p25', 'p75', 'p90', 'min', 'max', 'stddev')
COUNTS = ('completed', 'valid', 'incomplete', 'beat_spy', 'unique_schedules')


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
        for field in DISTRIBUTIONS:
            for statistic in STATISTICS:
                yield dict(test=test, statistic=f'{field}.{statistic}', value=summary['distributions'][field][statistic])
        for count in COUNTS:
            yield dict(test=test, statistic=count, value=summary[count])


TABLES = {
    'trials': (('test', 'trial'), trial_rows),
    'statistics': (('test', 'statistic'), statistic_rows),
}


def neutral(value):
    if isinstance(value, float) and not math.isfinite(value):
        return 'NaN' if value != value else 'Infinity' if value > 0 else '-Infinity'
    return value


def write(out, settings, results, names):
    out.mkdir(parents=True, exist_ok=True)
    for name in names:
        keys, rows = TABLES[name]
        ordered = sorted(rows(results), key=lambda row: tuple(row[key] for key in keys))
        text = ''.join(json.dumps({key: neutral(value) for key, value in row.items()}, ensure_ascii=False,
                                  separators=(',', ':'), allow_nan=False) + '\n' for row in ordered)
        (out / f'{name}.jsonl').write_text(text, encoding='utf-8')
    manifest = dict(producer='python-oracle', settings=settings, tables={name: list(TABLES[name][0]) for name in names})
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1) + '\n', encoding='utf-8')


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
    parser.add_argument('--as-of', type=as_of, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--tests', type=Path)
    parser.add_argument('--tables', nargs='+', choices=sorted(TABLES), default=list(TABLES))
    args = parser.parse_args()
    tests = {path.stem: json.loads(path.read_text(encoding='utf-8'))
             for path in sorted(args.tests.glob('*.json'))} if args.tests else {}
    with tempfile.TemporaryDirectory() if args.workspace is None else nullcontext(args.workspace) as folder:
        if args.workspace is None:
            oracle.build(args.raw, folder)
        oracle.load(folder)
        if args.workspace is None:
            oracle.prepare(args.as_of)
        results = {name: oracle.run(request, args.as_of) for name, request in tests.items()}
    settings = dict(as_of=args.as_of.isoformat(), tests=list(tests))
    write(args.out, settings, results, args.tables)
    print(f'Exported {", ".join(args.tables)} for {len(tests)} tests to {args.out}')


if __name__ == '__main__':
    main()
