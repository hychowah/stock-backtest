"""Write number vectors: the CPython behaviors that the Python product's results depend on.

Run from the repository root with CPython 3.14:

    python3 proof/number_vectors.py

It writes one file per behavior, fixtures/numbers/<behavior>.json:

    {"behavior": name, "python": "3.14", "source": the product call copied,
     "cases": [one object per line]}

Each case holds its exact inputs and the exact expected outputs. Where the
product exposes a function, the expected outputs come from that function;
otherwise from the built-in, called as the product calls it. Numbers use the
shortest round-trip spelling, -0.0 is kept, non-finite numbers are the strings
"NaN", "Infinity" and "-Infinity", and a missing value is null. Dates are ISO
strings. Running the script again writes the same bytes.

Behaviors and case fields:

random_choice    seed, lengths, indices. One Random(seed); for each length in
                 order, indices holds the index that choice() drew from a list
                 of that length (the calendar draws over session lists).
float_sum        values, sum, mean_return. Built-in sum() (compensated since
                 Python 3.12, starting from the integer 0) and the product's
                 mean of holding returns.
statistics       values, mean, median, pstdev, min, max. Exact-fraction mean
                 and pstdev, median of the stably sorted values, and min/max,
                 which keep the first of equal members.
percentile       values, probability, result. The trial-statistics percentile
                 (R type 7) at the probabilities the product reports.
threshold        value, unit, variable_unit, storage_scale; then threshold,
                 comparison_value and storage_comparison_value, or error (the
                 code) when the product rejects the threshold. value and unit
                 are the submitted decimal text and unit; threshold is the
                 normalized text in canonical units.
canonical        value, scale, result. A stored lane value in canonical units:
                 float(Decimal(str(value)).scaleb(scale)), or null when it is
                 not a valid input.
cagr             periods ([strategy, SPY] returns, strategy may be null), start,
                 end (null when unknown); growth, spy_growth, cagr, spy_cagr.
peg              market_cap, net_income, eps (diluted EPS of the selected year,
                 then the three years before it); pe, peg.
annual_cagr      first, last, count; result = (last/first)**(1/(count-1)) - 1
                 for a formula's annual CAGR over count yearly members.
selection_order  direction, rank_from, rank_to, candidates (symbol,
                 candidate_rank, value); selected (symbol, rank, value),
                 matches. One rank step.
legacy_rank      statements ([symbol, report yield] in pool order); ranks
                 ([symbol, rank] in rank order). The US top-250 tie rank.
sqlite_real      value, stored. A value written to a REAL lane of an entry
                 sheet and read back.
csv_number       value, text. The ECMAScript spelling of a CSV number.
"""
from datetime import date, timedelta
import json
import math
from pathlib import Path
import random
import sqlite3
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest import portfolio_results, selection  # noqa: E402
from backtest.application import result_exports, scalar_execution, strategy_requests  # noqa: E402
from backtest.engines.original import robustness  # noqa: E402
from backtest.financial import books, metrics  # noqa: E402
from backtest.inputs import book_store  # noqa: E402
from backtest.variables import definitions  # noqa: E402

INF, NAN = math.inf, math.nan

# Plausible trial CAGRs and period returns; fixed literals so the inputs never move.
TRIALS = [0.1213, 0.0874, 0.1532, -0.0215, 0.0991, 0.1103, 0.0874, 0.1678, 0.0432, 0.1287, 0.0655, 0.1419,
          0.0912, 0.1056, -0.0047, 0.1201, 0.1388, 0.0779, 0.1124, 0.0968, 0.1501, 0.0823, 0.1342, 0.1009]
RETURNS = [0.0412, -0.1873, 0.2291, 0.0057, -0.0321, 0.1135, 0.0768, -0.0049, 0.3312, -0.2505,
           0.0193, 0.0644, -0.0712, 0.1427, 0.0081, -0.0156, 0.0929, 0.0217, -0.1104, 0.0538]


def random_choice():
    seeds = [0, 1, 2**32 - 1, 2607948532, 20261113, 31, 4242, 909090, 777]
    lengths = [1, 2, 3, 4, 5, 7, 8, 9, 15, 16, 17, 21, 31, 32, 33, 63, 64, 65, 127, 128, 129,
               252, 255, 256, 257, 1023, 1024, 1025, 4095, 4096, 4097, 65535, 65536, 65537]
    lengths = lengths + lengths[::-1]
    cases = []
    for seed in seeds:
        generator = random.Random(seed)
        indices = [generator.choice(list(range(length))) for length in lengths]
        cases.append(dict(seed=seed, lengths=lengths, indices=indices))
    return 'random.Random(seed).choice, as drawn in backtest.calendar.SessionCalendar.sample', cases


def float_sum():
    lists = [[], [-0.0], [-0.0, -0.0], [0.0, -0.0], [0.1] * 10, [0.1, 0.2, 0.3], [1e100, 1.0, -1e100],
             [1.0, 1e100, 1.0, -1e100], [1e16, 1.0, 1.0], [1.0, -1.0, 1e-20], [2.0**53, 1.0, -(2.0**53)],
             [-0.5, 0.25, 0.125, -0.0], [1e-310, 1e-310, -3e-310], [0.7, 0.2, 0.1, -1.0], RETURNS]
    cases = [dict(values=values, sum=sum(values), mean_return=portfolio_results.mean_return(values))
             for values in lists]
    return 'sum() in backtest.portfolio_results.mean_return', cases


def statistics_():
    lists = [[1.0], [-0.0], [-0.0, -0.0], [0.0, -0.0, 1.0], [-0.0, 0.0, 1.0], [0.0, -0.0], [-0.0, 0.0],
             [0.1] * 10, [0.1, 0.2, 0.3], [1.0, 2.0, 3.0, 4.0], [3.0, 1.0, 2.0], [1e308, 1e308],
             [1e16, 1.0, -1e16], [1e-310, 2e-310, 4e-310], [5.0] * 7, TRIALS]
    cases = [dict(values=values, mean=statistics.mean(values), median=statistics.median(values),
                  pstdev=statistics.pstdev(values), min=min(values), max=max(values)) for values in lists]
    source = ('statistics.mean, statistics.median, statistics.pstdev, min and max, as called in '
              'backtest.engines.original.robustness.distribution (statistics.mean also in '
              'backtest.financial.metrics, statistics.median also in backtest.application.result_curves)')
    return source, cases


def percentile():
    hundred = [((k * 7919) % 1000 - 300) / 1000 for k in range(100)]
    lists = [[0.5], [-0.0], [0.0, -0.0], [-0.0, 0.0], [1.0, 2.0], [3.0, 1.0, 2.0, 5.0, 4.0],
             [k / 10 for k in range(11)], TRIALS, [k * 0.01 for k in range(31)], hundred]
    cases = [dict(values=values, probability=probability, result=robustness.percentile(values, probability))
             for values in lists for probability in (.1, .25, .75, .9)]
    return 'backtest.engines.original.robustness.percentile', cases


def threshold():
    # (submitted value, submitted unit, variable unit, storage scale)
    inputs = [('5', 'percent', 'scalar', -2), ('0.1', 'percent', 'scalar', -2), ('1.1', 'percent', 'scalar', -2),
              ('12.5', 'percentage_points', 'scalar', -2), ('-3.25', 'percent', 'scalar', -2),
              ('0.05', 'scalar', 'scalar', -2), ('100', 'usd_million', 'USD', 6),
              ('0.000001', 'usd_million', 'USD', 6), ('2500000000', 'USD', 'USD', 6),
              ('1.5e3', 'multiple', 'scalar', 0), ('007.50', 'number', 'scalar', 0), ('+.5', 'scalar', 'scalar', 0),
              ('5.', 'scalar', 'scalar', 0), ('-0.0', 'scalar', 'scalar', 0), ('0.30000000000000004441', 'scalar', 'scalar', 0),
              ('1e-320', 'scalar', 'scalar', 0), ('1e-400', 'scalar', 'scalar', 0), ('1e309', 'scalar', 'scalar', 0),
              ('2e-322', 'percent', 'scalar', -2), ('1.7e308', 'scalar', 'scalar', -2),
              ('1e-318', 'USD', 'USD', 6), ('1e306', 'usd_million', 'USD', 6)]
    cases = []
    for value, unit, variable_unit, scale in inputs:
        case = dict(value=value, unit=unit, variable_unit=variable_unit, storage_scale=scale)
        try:
            checked = strategy_requests._quantity(dict(threshold=dict(value=value, unit=unit)),
                                                  dict(unit=variable_unit, storage=dict(scale=scale)), '')
        except definitions.FormulaError as error:
            case.update(error=error.code)
        else:
            case.update(threshold=checked['threshold']['value'], comparison_value=checked['comparison_value'],
                        storage_comparison_value=checked['storage_comparison_value'])
        cases.append(case)
    return ('backtest.application.strategy_requests._quantity (definitions.normalize_quantity, then '
            'Decimal.scaleb to the storage scale at precision 2048 and one float())'), cases


def canonical():
    inputs = [(0.1, 6), (0.1, -2), (0.07, -2), (1.1, -2), (33.333333333333336, -2), (123.456, 6), (2.5e-08, 6),
              (1234567.891, 6), (0.3, 0), (-0.0, 6), (-0.0, -2), (-0.0, 0), (0.0, -2), (1e308, 6),
              (1.7976931348623157e308, -2), (5e-324, -2), (1e-320, 6), (INF, 0), (NAN, 6),
              (973012718181.5312, -2)]
    cases = [dict(value=value, scale=scale, result=scalar_execution._canonical(value, scale))
             for value, scale in inputs]
    return 'backtest.application.scalar_execution._canonical: float(Decimal(str(value)).scaleb(scale))', cases


def cagr():
    quarterly = [[RETURNS[k % 20], RETURNS[(k * 7) % 20] / 2] for k in range(80)]
    inputs = [([[0.1, 0.05], [-0.2, 0.03], [0.15, -0.01]], '2015-01-02', '2018-01-02'),
              ([[0.1, 0.05]], '2016-02-29', '2020-02-28'),
              (quarterly, '2004-01-02', '2024-01-02'),
              ([[0.012, 0.004]], '2023-03-01', '2023-03-31'),
              ([[-1.0, 0.1]], '2020-01-02', '2021-01-04'),
              ([[None, 0.1], [0.2, 0.0]], '2020-01-02', '2021-01-04'),
              ([[0.1, 0.05], [0.2, -0.1]], None, None),
              ([], '2020-01-02', '2021-01-04')]
    cases = []
    for periods, start, end in inputs:
        result = portfolio_results.reduce_returns(
            [tuple(period) for period in periods],
            start=date.fromisoformat(start) if start else None, end=date.fromisoformat(end) if end else None)
        cases.append(dict(periods=periods, start=start, end=end, **result))
    return ('backtest.portfolio_results.reduce_returns: growth**(1/((end-start).days/365.25))-1', cases)


def peg():
    inputs = [(1e9, 5e7, [2.0, 1.8, 1.5, 1.0]), (1e9, 5e7, [8.0, 4.0, 2.0, 1.0]), (3.3e10, 1.7e9, [3.3, 2.2, 1.1, 0.7]),
              (5e8, 2e7, [1.331, 1.21, 1.1, 1.0]), (7.5e9, 3e8, [1.0, 1.0, 1.0, 1.0]),
              (7.5e9, 3e8, [0.5, 0.8, 0.9, 1.0]), (2.2e9, 1.1e8, [0.47, 0.41, 0.33, 0.29])]
    cases = []
    for cap, income, eps in inputs:
        reports = {f'{2023 - i}-12-31': dict(epsDiluted=value) for i, value in enumerate(eps)}
        reports['2023-12-31']['netIncome'] = income
        values = metrics.financial_values(dict(fiscal='2023-12-31', market_cap=cap), reports)
        cases.append(dict(market_cap=cap, net_income=income, eps=eps, pe=values.get('pe'), peg=values.get('peg')))
    return 'backtest.financial.metrics.financial_values: pe/(((eps[0]/eps[3])**(1/3)-1)*100)', cases


def annual_cagr():
    inputs = [(100.0, 121.0, 2), (100.0, 121.0, 3), (1.0, 8.0, 4), (50.0, 80.0, 5), (2.5, 1.7, 6),
              (1.0, 1.0, 3), (3.7e9, 9.1e9, 10), (0.03, 2.9, 11)]
    cases = [dict(first=first, last=last, count=count, result=(last / first) ** (1 / (count - 1)) - 1)
             for first, last, count in inputs]
    return ('the annual cagr in backtest.variables.columns.Formulas._task: '
            'ratio ** (1 / (len(values) - 1)) - 1'), cases


def selection_order():
    candidates = [('AAA', 3, 1.0), ('BBB', None, 1.0), ('CCC', 1, 1.0), ('DDD', None, 1.0), ('EEE', None, -0.0),
                  ('FFF', None, 0.0), ('GGG', None, None), ('HHH', None, NAN), ('III', None, INF),
                  ('aaa', None, 0.5), ('ZZZ', None, 0.5), ('0005.HK', None, 0.5), ('7203.T', 2, 0.5),
                  ('JJJ', None, -2.5), ('KKK', 2, -2.5)]
    rows = [dict(symbol=symbol, candidate_rank=rank, values=dict(value=value)) for symbol, rank, value in candidates]
    cases = []
    for direction, first, last in (('highest', 1, 50), ('lowest', 1, 50), ('highest', 3, 6)):
        step = dict(kind='rank', lane='value', direction=direction, rank_from=first, rank_to=last)
        result = selection.execute(rows, [step])
        cases.append(dict(direction=direction, rank_from=first, rank_to=last,
                          candidates=[dict(symbol=s, candidate_rank=r, value=v) for s, r, v in candidates],
                          selected=[dict(symbol=rows[item['index']]['symbol'], rank=item['rank'], value=item['value'])
                                    for item in result['selected']],
                          matches=result['matches']))
    return 'backtest.selection.execute with one rank step', cases


def legacy_rank():
    day = date(2020, 6, 1)
    lists = [[['BBB', 0.1], ['AAA', 0.2], ['CCC', 0.1], ['DDD', 0.3], ['EEE', 0.1]],
             [['S%03d' % (250 - k), 0.05] for k in range(251)] + [['TOP', 0.06]]]
    cases = []
    for statements in lists:
        broad = {symbol: [{'fiscal': day - timedelta(days=150), 'known': day - timedelta(days=60), 'yield': value}]
                 for symbol, value in statements}
        _, ranks = books.candidates((broad, broad), day)
        cases.append(dict(statements=statements, ranks=[[symbol, rank] for symbol, rank in ranks.items()]))
    return 'backtest.financial.books.candidates: sorted(..., key=report yield, reverse=True)[:250]', cases


def sqlite_real():
    values = [0.0, -0.0, 1.0, -1.5, 0.1, 5e-324, 2.2250738585072014e-308, 1e-300, 123456789.0, -123456789.0,
              2.0**53, 1e15, 1e18, 2.0**63, -(2.0**63), 1e19, 1.7976931348623157e308, INF, -INF, NAN]
    symbols = ['S%02d' % k for k in range(len(values))]
    db = sqlite3.connect(':memory:')
    db.executescript(book_store.SCHEMA)
    rows = [(symbol, None, '2019-12-31', '2020-03-01', '2020-06-01', 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
            for symbol in symbols]
    book = book_store.store(db, dict(market='us', entry='2020-06-01', latest=0, candidates=len(rows), pool='cached',
                                     rows=rows, metrics=[], filters=list(zip(symbols, ['pe'] * len(values), values))))
    _, stored = book_store.lanes(db, book, 'cached', metrics=(), fields=('pe',))
    db.close()
    cases = [dict(value=value, stored=stored['pe'].get(symbol)) for symbol, value in zip(symbols, values)]
    return 'a REAL lane written by backtest.inputs.book_store.store and read by book_store.lanes', cases


def csv_number():
    values = [0.0, -0.0, 1.0, -1.5, 0.1, 100.0, 123.456, -0.000001234, 0.000123, 1e-6, 1e-7, 1.5e-7, 2.0**53,
              1e20, 1.2345678901234568e20, 1e21, 1.5e21, 1e300, 5e-324, 1.7976931348623157e308, 4294967295.0]
    return 'backtest.application.result_exports.number', [dict(value=v, text=result_exports.number(v)) for v in values]


BEHAVIORS = dict(random_choice=random_choice, float_sum=float_sum, statistics=statistics_, percentile=percentile,
                 threshold=threshold, canonical=canonical, cagr=cagr, peg=peg, annual_cagr=annual_cagr,
                 selection_order=selection_order, legacy_rank=legacy_rank, sqlite_real=sqlite_real,
                 csv_number=csv_number)


def neutral(value):
    """The value with non-finite floats spelled as strings."""
    if isinstance(value, float) and not math.isfinite(value):
        return 'NaN' if math.isnan(value) else 'Infinity' if value > 0 else '-Infinity'
    if isinstance(value, dict):
        return {key: neutral(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [neutral(item) for item in value]
    return value


def main():
    folder = ROOT / 'fixtures' / 'numbers'
    folder.mkdir(parents=True, exist_ok=True)
    python = '%d.%d' % sys.version_info[:2]
    for name, build in BEHAVIORS.items():
        source, cases = build()
        lines = ',\n'.join(json.dumps(neutral(case), allow_nan=False) for case in cases)
        text = (f'{{"behavior": {json.dumps(name)}, "python": {json.dumps(python)}, '
                f'"source": {json.dumps(source)}, "cases": [\n{lines}\n]}}\n')
        (folder / f'{name}.json').write_text(text, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()
