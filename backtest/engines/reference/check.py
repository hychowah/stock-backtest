"""Development check of the book code against the independent reference engine.

No build, startup or preparation runs the dated check. Run it on the real-data
bench after a change to book policy (books.py, rules.py, the dated book writer
or its price lookups):

    python3 backtest/engines/reference/check.py [--through YYYY-MM-DD] [--json OUT]

The dated run is the fixed 12-month schedule from 1 January FIRST_YEAR to the
through date (default rules.ASOF), legacy pool, ev_ebitda ranks 1-50 and the
default size floors, calculated by Original. adapt() gives it the shape of
revalue.calculate(through); differences() compares both at full precision and
names each difference. The check passes when there is none. report_rows()
compares the annual rows with the frozen report (results/summary-exits.txt) at
its four decimals. The report marks 2026 through its own Through date, so at a
later through date only its 2026 row differs.

agree() is the full-precision comparison of two January results that research
verification uses: equal field lists within the 1e-12 tolerance.
"""
import argparse
import csv
from datetime import date
import io
import json
import math
import sys
from pathlib import Path

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backtest.financial import rules

# Full-precision engines may differ only by floating-point roundoff.
REL_TOL = 1e-12
ABS_TOL = 1e-12
PRICE_FIELDS = ('fiscal_price_date', 'valuation_date', 'fiscal_price', 'valuation_price', 'entry_price', 'exit_price')
HOLDING_FIELDS = ('symbol', 'rank', 'fiscal', 'entry', 'exit', *PRICE_FIELDS, 'market_cap', 'enterprise_value',
                  'ebitda', 'return_value', 'status')
YEAR_FIELDS = ('year', 'entry', 'exit', 'spy_entry', 'spy_exit', 'spy_entry_price', 'spy_exit_price', 'spy', 'portfolio')
# A dated book stores no prices: it is compared on every other field.
DATED_HOLDING_FIELDS = tuple(key for key in HOLDING_FIELDS if key not in PRICE_FIELDS)
DATED_YEAR_FIELDS = ('year', 'entry', 'exit', 'spy', 'portfolio')


def same(a, b):
    if type(a) in (int, float) and type(b) in (int, float):
        return math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL)
    return a == b


def agree(prepared, independent):
    """Reject any difference in coverage, holdings, prices or annual results.

    Equal annual averages cannot conceal swapped or incorrectly priced holdings.
    Values in this comparison are unrounded; nonfinite numbers always fail.
    """
    if prepared['through'] != independent['through'] or [y['year'] for y in prepared['years']] != list(range(rules.FIRST_YEAR, rules.LAST_YEAR + 1)) or [y['year'] for y in prepared['years']] != [y['year'] for y in independent['years']]:
        raise ValueError('Baseline engines disagree on historical coverage. Existing results were kept.')
    for a, b in zip(prepared['years'], independent['years']):
        context = str(a['year'])
        for key in YEAR_FIELDS:
            if not same(a[key], b[key]): raise ValueError(f'Baseline engines disagree for {context}: {key}. Existing results were kept.')
        if len(a['holdings']) != len(b['holdings']): raise ValueError(f'Baseline engines disagree for {context}: holding count. Existing results were kept.')
        for x, y in zip(a['holdings'], b['holdings']):
            for key in HOLDING_FIELDS:
                if not same(x[key], y[key]): raise ValueError(f'Baseline engines disagree for {context}, {x["symbol"]}: {key}. Existing results were kept.')


def options(through):
    """The dated run's request: one Original custom schedule."""
    return dict(start=f'{rules.FIRST_YEAR}-01-01', end=str(through), months=12, pool='legacy', metric='ev_ebitda',
                rank_from=1, rank_to=rules.HOLD)


def dated(through):
    """Calculate the dated run with Original; the caller may hold cache ownership."""
    from backtest.application.original_calculations import Original
    return Original().calculate('custom', options(through), None, None)


def adapt(result, through):
    """Give a dated result the revalue.calculate shape, by book year."""
    years = []
    for period in result['periods']:
        years.append(dict(year=date.fromisoformat(period['entry']).year, entry=period['entry'], exit=period['exit'],
                          spy=period['spy'], portfolio=period['portfolio'],
                          holdings=[{key: holding[key] for key in DATED_HOLDING_FIELDS} for holding in period['holdings']]))
    return dict(through=str(through), years=years)


def differences(dated_result, reference):
    """Every year, holding and field where the adapted dated run and revalue differ."""
    found = []
    if dated_result['through'] != reference['through']:
        found.append(dict(kind='through', dated=dated_result['through'], reference=reference['through']))
    left = {year['year']: year for year in dated_result['years']}
    right = {year['year']: year for year in reference['years']}
    for number in sorted(left.keys() | right.keys()):
        a, b = left.get(number), right.get(number)
        if a is None or b is None:
            found.append(dict(kind='year_missing', year=number, side='reference' if b is None else 'dated'))
            continue
        for key in DATED_YEAR_FIELDS:
            if not same(a[key], b[key]):
                found.append(dict(kind='year_field', year=number, field=key, dated=a[key], reference=b[key]))
        mine = {holding['symbol']: holding for holding in a['holdings']}
        theirs = {holding['symbol']: holding for holding in b['holdings']}
        for symbol in sorted(mine.keys() - theirs.keys()):
            found.append(dict(kind='holding_only_dated', year=number, symbol=symbol, rank=mine[symbol]['rank']))
        for symbol in sorted(theirs.keys() - mine.keys()):
            found.append(dict(kind='holding_only_reference', year=number, symbol=symbol, rank=theirs[symbol]['rank']))
        for symbol in sorted(mine.keys() & theirs.keys()):
            for key in DATED_HOLDING_FIELDS[1:]:
                if not same(mine[symbol][key], theirs[symbol][key]):
                    found.append(dict(kind='holding_field', year=number, symbol=symbol, field=key,
                                      dated=mine[symbol][key], reference=theirs[symbol][key]))
    return found


def report_rows(dated_result, text):
    """Compare annual rows with the frozen report's four-decimal CSV rows."""
    rows = list(csv.DictReader(io.StringIO(text.replace('\r\n', '\n')[text.index('year,portfolio,spy,'):])))
    years = {year['year']: year for year in dated_result['years']}
    found = []
    for row in rows:
        year = years.get(int(row['year']))
        if year is None:
            found.append(dict(kind='report_year_missing', year=int(row['year'])))
            continue
        stopped = sum(holding['status'] == 'Last available price' for holding in year['holdings'])
        for key, value, expected, tolerance in (
                ('portfolio', year['portfolio'], float(row['portfolio']), .000051),
                ('spy', year['spy'], float(row['spy']), .000051),
                ('names', len(year['holdings']), int(row['names']), 0),
                ('stopped', stopped, int(row['stopped']), 0)):
            if value is None or abs(value - expected) > tolerance:
                found.append(dict(kind='report_field', year=year['year'], field=key, dated=value, report=expected))
    return found


def main():
    from backtest.engines.reference import revalue
    from backtest.paths import RESULTS
    from backtest.runtime import cache_access
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--through', type=date.fromisoformat, default=rules.ASOF)
    parser.add_argument('--json', type=Path, help='Write the dated run and every difference to this file')
    args = parser.parse_args()
    with cache_access.access():
        result = dated(args.through)
        reference = revalue.calculate(args.through)
    adapted = adapt(result, args.through)
    found = differences(adapted, reference)
    frozen = report_rows(adapted, (RESULTS / 'summary-exits.txt').read_text(encoding='utf-8'))
    kinds = {}
    for item in found:
        kinds[item['kind']] = kinds.get(item['kind'], 0) + 1
    print(f'Dated run: {len(adapted["years"])} books, {sum(len(y["holdings"]) for y in adapted["years"])} holdings, '
          f'{result["start"]} -> {result["end"]}.')
    print(f'Against revalue.calculate({args.through}): {len(found)} differences {kinds or ""}.')
    for item in found[:40]:
        print('  ' + json.dumps(item, default=str))
    print(f'Against the frozen report: {len(frozen)} differences.')
    for item in frozen[:40]:
        print('  ' + json.dumps(item, default=str))
    if args.json:
        args.json.write_text(json.dumps(dict(dated=adapted, differences=found, report=frozen), default=str))
    raise SystemExit(1 if found else 0)


if __name__ == '__main__':
    main()
