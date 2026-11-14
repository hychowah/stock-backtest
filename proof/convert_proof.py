"""Run each test that proof/convert.py converts through the oracle twice, as the original and as the converted file.

    python3 proof/convert_proof.py (--raw DIR | --workspace DIR) --as-of TIME --out DIR [--trials N] \\
        [--data DIR] [REQUEST ...]

`--raw`, `--workspace` and `--as-of` are as in proof/l3.py; `--data` and the
REQUEST files are as in proof/convert.py. The fictional fixture's tests:

    python3 proof/convert_proof.py --raw fixtures/fictional/raw --as-of 2023-06-30T07:30:00+00:00 \\
        --out "$TMPDIR/convert-proof" --data fixtures/fictional/saved/data fixtures/fictional/saved/requests/*.json

The original is the stored or requested request with its own seed (the
recorded seed when the request has none), as the oracle runs it: a strategy
capture (an intent is captured first) runs as proof/l3.py runs a case; flat
options run the server's flat path (Original.calculate, SQL selection, an
inline result), with screening.latest as their latest screen. The deleted
engine label "experimental" is dropped from the original. The converted file
runs as proof/l3.py runs a case. Both sides write proof/l3.py's tables, with
the test's name as the case, to DIR/<n>/original and DIR/<n>/converted (n
counts the tests), and each table that both produce is compared row by row:
- a flat original has no step trail (steps, pick_steps) and no formula values,
  and its holdings' ranking_value is the stored metric yield;
- a capture-1 original has no step trail (l3.step_rows reads chains);
- formula_values covers the entry days of trials 1 to 3 and each variable that
  a step reads (named as in the converted file);
- explore is left out of a test whose periods or ranks are too few for it;
- the built-in filter:ebitda_yield folds into "EBITDA yield", whose lane has
  another storage scale: the value of a step on it, and the ranking_value of a
  holding (and of each pick) ranked by such a step, may differ by at most
  ULPS units in the last place. Every other field and every pick must be
  equal.
`--trials N` runs a random test with at most N trials on both sides (the draws
are trial-major, so these are its first N trials). It prints the rows compared
per table, the first keys that differ and a line per skipped test, ends with
the counts of proven, skipped and different tests, and exits with 1 when a test
differs.
"""
import argparse
from contextlib import closing, nullcontext
import copy
import json
import math
from pathlib import Path
import tempfile
import time

import convert
import export
import l3
import oracle

LIMIT = 3  # formula_values: the entry days of trials 1 to LIMIT.
ULPS = 4  # The difference allowed in a folded lane's value.
FLAT_TABLES = ('trials', 'statistics', 'periods', 'holdings', 'curve', 'growth', 'band', 'sectors', 'contributions',
               'explore', 'picks')


class Eager:
    """A reader over a flat (inline, contract 1) result: the records and trial summaries of the evidence reader."""

    def __init__(self, mode, result, options):
        self.trials = result['trial_results'] if mode == 'random' else [result]
        self.manifest = dict(trials=len(self.trials),
                             summary={key: value for key, value in result.items() if key != 'trial_results'})
        self.metadata = dict(mode=mode, options=options)

    def trial_summary(self, number):
        trial = self.trials[number - 1]
        summary = dict({key: value for key, value in trial.items() if key != 'periods'}, options=self.metadata['options'])
        return summary, [(period['names'], 1) for period in trial['periods']]

    def verified_records(self):
        for number, trial in enumerate(self.trials, 1):
            yield dict(type='trial', number=number)
            for index, period in enumerate(trial['periods'], 1):
                yield dict(type='period', number=index, value=period)
                for row in period['holdings']:
                    yield dict(type='holding', value=row)
                yield dict(type='end_period')
            yield dict(type='end_trial', summary=trial)


class Screen:
    def __init__(self, rows):
        self.rows = rows

    def verified_records(self):
        return (dict(type='screen', value=row) for row in self.rows)


def flat_holding_rows(cases):
    """l3.holding_rows of a flat result: the ranking value is the stored metric yield, and one sleeve."""
    for case in cases:
        for trial, period, _, holdings in l3.stored(case['reader']):
            for row in holdings:
                fields = dict(case=case['name'], trial=trial, period=period, rank=row['rank'],
                              **{field: row[field] for field in l3.HOLDING_FIELDS})
                fields.update({'return': row['return_value']}, status=row['status'], ranking_value=row['metric_yield'],
                              sleeve=1, weight=row['weight'], contribution=row['contribution_pp'])
                yield fields


def original(name, mode, options, as_of, identities):
    """(case, tables) of an original request, run as the website or the server's flat path runs it."""
    from backtest import screening
    from backtest.application import strategy_requests
    from backtest.application.original_calculations import Original
    market = options.get('market', 'us')
    tables = {table: rows for table, (_, rows) in l3.TABLES.items()}
    if 'strategy' not in options:
        with oracle.pinned(as_of):
            result = Original().calculate(mode, options, None, None)
            with closing(oracle.connect()) as db:
                selection = {key: value for key, value in options.items() if key not in convert.RUN_KEYS - {'market'}}
                screen = screening.latest(db, **dict(dict(pool='legacy' if market == 'us' else 'cached'), **selection))
        screen = Screen([dict(rank=row['rank'], symbol=row['symbol'], ranking_value=row['metric_yield']) for row in screen])
        case = l3.case(name, 'builtins', None, market, mode, Eager(mode, result, options), screen)
        return case, dict({table: tables[table] for table in FLAT_TABLES}, holdings=flat_holding_rows)
    options = copy.deepcopy(options)
    captured = options.pop('strategy')
    reader = l3.calculate(mode, dict(options, strategy=captured), as_of)
    case = l3.case(name, 'builtins', None, market, mode, reader,
                   l3.calculate('latest', dict(market=market, strategy=captured), as_of))
    if captured['version'] == 1:
        del tables['steps'], tables['pick_steps']
    del tables['formula_values']
    if captured['variables'] is not None:
        checked = strategy_requests.check_options(dict(market=market, strategy=captured))
        outputs = dict.fromkeys((item['variable_id'], item['revision'])
                                for item in strategy_requests.sources(checked) if item['kind'] == 'formula')
        named = sorted((identities[output], output) for output in outputs)
        tables['formula_values'] = lambda cases: l3.formula_values(cases[0], checked, named, LIMIT)
    return case, tables


def converted(name, run, strategy, as_of):
    """(case, tables) of a converted file, run as proof/l3.py runs a case."""
    mode, options = oracle.schedule(run)
    captured = l3.capture(strategy, run['market'])
    reader = l3.calculate(mode, dict(options, strategy=captured), as_of)
    case = l3.case(name, 'formulas' if 'variables' in strategy else 'builtins', strategy, run['market'], mode, reader,
                   l3.calculate('latest', dict(market=run['market'], strategy=captured), as_of))
    read = sorted({step.get('rank', step.get('filter')) for sleeve in strategy['sleeves'] for step in sleeve['steps']}
                  & set(strategy.get('variables', {})))
    tables = {table: rows for table, (_, rows) in l3.TABLES.items()}
    tables['formula_values'] = lambda cases: l3.variable_values(cases[0], read, LIMIT)
    return case, tables


def folds(capture, converter):
    """(sleeve, step) of each step on a built-in that folds into a lane of another storage scale, and the sleeves
    whose final Rank is such a step; 1-based."""
    from backtest.application import strategy_requests
    if capture is None:
        return set(), set()

    def moved(source):
        return (source['kind'] == 'builtin' and converter.catalog[source['id']]['storage']['scale']
                != converter.catalog[converter.read(('builtin', source['id']))[1]]['storage']['scale'])

    if capture['version'] == 1:
        return set(), {1} if moved(capture['selection']['ranking']['source']) else set()
    steps, ranks = set(), set()
    for sleeve, chain in enumerate(strategy_requests.chains(capture), 1):
        steps |= {(sleeve, step) for step, item in enumerate(chain, 1) if moved(item['source'])}
        if moved([item for item in chain if item['kind'] == 'rank'][-1]['source']):
            ranks.add(sleeve)
    return steps, ranks


def compare(left, right, tables, folded):
    """Print the rows compared of each table; return (differences, accepted values of a folded lane)."""
    steps, ranks = folded
    differences = accepted = 0
    for name, keys in tables.items():
        rows = []
        for folder in (left, right):
            with open(folder / f'{name}.jsonl', encoding='utf-8') as file:
                rows.append({tuple(row[key] for key in keys): row for row in map(json.loads, file)})
        missing, extra = rows[0].keys() - rows[1].keys(), rows[1].keys() - rows[0].keys()
        changed, close = [], 0
        for key in rows[0].keys() & rows[1].keys():
            one, other = rows[0][key], rows[1][key]
            if json.dumps(one) == json.dumps(other):
                continue
            loose = ('value' if name in ('steps', 'pick_steps') and (key[-2], key[-1]) in steps else
                     'ranking_value' if name == 'holdings' and one['sleeve'] in ranks or name == 'picks' and ranks else None)
            if (loose and json.dumps(dict(one, **{loose: None})) == json.dumps(dict(other, **{loose: None}))
                    and abs(one[loose] - other[loose]) <= ULPS * math.ulp(max(abs(one[loose]), abs(other[loose])))):
                close += 1
            else:
                changed.append(key)
        print(f'  {name}: {len(rows[0])} rows compared, {len(missing)} missing, {len(extra)} extra, {len(changed)} different'
              + (f', {close} folded-lane values within {ULPS} ulps' if close else ''))
        for key in sorted(map(str, [*missing, *extra, *changed]))[:5]:
            print(f'    {key}')
        differences += len(missing) + len(extra) + len(changed)
        accepted += close
    return differences, accepted


def prove(index, item, mode, options, seed, converter, args, folder):
    """Run and compare one test; return 'proven', 'skipped' or 'different'."""
    name = item['name']
    try:
        if isinstance(mode, convert.Refused):
            raise mode
        run, strategy, identities = converter.test(mode, options, seed)
    except convert.Refused as reason:
        print(f'{name}: skipped, not converted: {reason}')
        return 'skipped'
    options = dict(options)
    if options.get('engine') == 'experimental':
        del options['engine']
        print(f'{name}: the original runs without its deleted engine label "experimental"')
    if mode == 'random':
        options['seed'] = seed if options.get('seed') is None else options['seed']
        if args.trials and run['trials'] > args.trials:
            options['trials'] = run['trials'] = args.trials
    started = time.time()
    try:
        case, tables = original(name, mode, options, args.as_of, identities)
    except (ValueError, TypeError) as error:
        print(f'{name}: skipped, the oracle cannot run the original: {error}')
        return 'skipped'
    middle = time.time()
    mine, theirs = converted(name, run, strategy, args.as_of)
    ended = time.time()
    if 'explore' in tables:
        try:
            list(l3.explore_rows([case]))
        except ValueError as error:
            print(f'{name}: explore left out: {error}')
            del tables['explore']
    settings = dict(as_of=args.as_of.isoformat(), backtest=oracle.tree(folder), test=item, run=run)
    keys = {table: l3.TABLES[table][0] for table in tables}
    out = args.out / f'{index:03d}'
    export.write(out / 'original', settings, {table: (keys[table], rows([case])) for table, rows in tables.items()})
    export.write(out / 'converted', settings, {table: (keys[table], theirs[table]([mine])) for table in tables})
    print(f'{name} ({out.name}): original {middle - started:.1f} s, converted {ended - middle:.1f} s, '
          f'tables {time.time() - ended:.1f} s')
    differences, _ = compare(out / 'original', out / 'converted', keys, folds(options.get('strategy'), converter))
    return 'different' if differences else 'proven'


def main():
    parser = argparse.ArgumentParser(description='Run each converted test and its original through the oracle and compare.')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--raw', type=Path)
    source.add_argument('--workspace', type=Path)
    parser.add_argument('--as-of', type=export.as_of, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--trials', type=int)
    parser.add_argument('--data', type=Path)
    parser.add_argument('requests', type=Path, nargs='*')
    args = parser.parse_args()
    counts = dict(proven=0, skipped=0, different=0)
    with tempfile.TemporaryDirectory() if args.workspace is None else nullcontext(args.workspace) as folder:
        if args.workspace is None:
            oracle.build(args.raw, folder)
        oracle.load(folder)
        if args.workspace is None:
            oracle.prepare(args.as_of)
        converter = convert.Converter()
        found, _ = convert.originals(args.data, args.requests, converter)
        for index, (item, mode, options, seed) in enumerate(found, 1):
            counts[prove(index, item, mode, options, seed, converter, args, folder)] += 1
    print(', '.join(f'{count} {state}' for state, count in counts.items()) + '.')
    raise SystemExit(1 if counts['different'] else 0)


if __name__ == '__main__':
    main()
