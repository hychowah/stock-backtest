"""Development check of the book code against the independent reference engine.

No build, startup or preparation runs it. Run it on the real-data bench after a
change to book policy (books.py, rules.py, the dated book writer or its price
lookups):

    python3 scripts/check.py [--through YYYY-MM-DD] [--json OUT]

The dated run is the fixed 12-month schedule from 1 January legacy.FIRST_YEAR to
the through date (default: the frozen report's Through date, 2026-10-20):
legacy pool, ev_ebitda ranks 1 to legacy.HOLD and the default size floors,
calculated by Original. adapt() gives it the shape of revalue.calculate(through);
differences() is the one comparator. It compares both at full precision, within
the 1e-12 tolerance, and names each difference. report_rows() compares the
annual rows with the frozen report (results/summary-exits.txt) at its four
decimals. The check passes when neither finds a difference.
"""
import argparse
import csv
from datetime import date
import io
import json
import math
from pathlib import Path
import re

from backtest.engines.reference import legacy

# Full-precision engines may differ only by floating-point roundoff.
REL_TOL = 1e-12
ABS_TOL = 1e-12
DATED_HOLDING_FIELDS = ('symbol', 'rank', 'fiscal', 'entry', 'exit', 'market_cap', 'enterprise_value',
                        'ebitda', 'return_value', 'status')
DATED_YEAR_FIELDS = ('year', 'entry', 'exit', 'spy', 'portfolio')


def same(a, b):
    if type(a) in (int, float) and type(b) in (int, float):
        return math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL)
    return a == b


def options(through):
    """The dated run's request: one Original custom schedule."""
    return dict(start=f'{legacy.FIRST_YEAR}-01-01', end=str(through), months=12, pool='legacy', metric='ev_ebitda',
                rank_from=1, rank_to=legacy.HOLD)


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


def report_through(text):
    """The frozen report's Through date: its 2026 row is marked through it."""
    return date.fromisoformat(re.search(r'^Through (\d{4}-\d{2}-\d{2})$', text, re.MULTILINE).group(1))


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
    parser.add_argument('--through', type=date.fromisoformat, help="Default: the frozen report's Through date")
    parser.add_argument('--json', type=Path, help='Write the dated run and every difference to this file')
    args = parser.parse_args()
    text = (RESULTS / 'summary-exits.txt').read_text(encoding='utf-8')
    through = args.through or report_through(text)
    with cache_access.access():
        result = dated(through)
        reference = revalue.calculate(through)
    adapted = adapt(result, through)
    found = differences(adapted, reference)
    frozen = report_rows(adapted, text)
    kinds = {}
    for item in found:
        kinds[item['kind']] = kinds.get(item['kind'], 0) + 1
    print(f'Dated run: {len(adapted["years"])} books, {sum(len(y["holdings"]) for y in adapted["years"])} holdings, '
          f'{result["start"]} -> {result["end"]}.')
    print(f'Against revalue.calculate({through}): {len(found)} differences {kinds or ""}.')
    for item in found[:40]:
        print('  ' + json.dumps(item, default=str))
    print(f'Against the frozen report: {len(frozen)} differences.')
    for item in frozen[:40]:
        print('  ' + json.dumps(item, default=str))
    if args.json:
        args.json.write_text(json.dumps(dict(dated=adapted, differences=found, report=frozen), default=str))
    raise SystemExit(1 if found or frozen else 0)


if __name__ == '__main__':
    main()
