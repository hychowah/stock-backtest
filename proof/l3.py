"""Run the oracle on strategy files and export whole runs (proof level L3) as keyed tables.

    python3 proof/l3.py (--raw DIR | --workspace DIR) --as-of TIME --cases DIR --out DIR

`--raw`, `--as-of` and `--out` are as in proof/export.py; `--workspace` is an
oracle workspace that is prepared already. The fictional fixture's expected
tables (fixtures/fictional/expected/runs/):

    python3 proof/l3.py --raw fixtures/fictional/raw --as-of 2023-06-30T07:30:00+00:00 \\
        --cases fixtures/fictional/cases --out fixtures/fictional/expected/runs

A case is a folder `DIR/<kind>/<name>/`. Its name starts every key. The kind
groups cases: `builtins` use built-ins and fields only, `formulas` use named
variables. It holds:
- `strategy.json`, a strategy file: `sleeves`, each with `steps` and a `name`
  (needed when there are two or more), and optional `variables`, which map a
  name to `{formula, display?}`. A Filter step is `{filter, op, value}`: op is
  <, <=, >, >=, `is` or `is not`, and value is the threshold as decimal text in
  the source's display unit, or the text of a sector or exchange. A Rank step
  is `{rank, order (highest or lowest), from, to}`.
- `run.json`, the run settings (proof/oracle.py).

The adapter (`request`) builds the request that the website sends. A step
source that is, ignoring case and repeated spaces:
- the name of a file variable, reads that variable's formula;
- Sector, Exchange, "Market cap in dollars" or "Enterprise value in dollars",
  reads the candidate's field;
- a vocabulary name with linked built-ins (backtest/application/vocabulary.py),
  reads its first built-in; a step-only name, and "Free cash flow", read their
  built-in;
- anything else is formula text; the whole name of an unlinked input or
  measure has the vocabulary's display.
The formula editor's check (variable_authoring.validate) reads formula text in
catalog /4, with the file's earlier variables as its library, so a formula can
name a variable defined above it. A threshold is `{value, unit}` with the
source's display as the unit: the built-in's, the field's, the variable's
`display`, or the default display of the formula's unit. One sleeve is a
strategy-intent 2, several are an intent 3, both on the cached pool.

Each case runs as the website runs it (Original.calculate_into) into a result
in memory, which the oracle's readers read. The same strategy also screens the
latest session. The tables:
- `trials` (case, trial): start, first_trade, end, dates (the entry days,
  joined by spaces), cash_days, periods, cagr, spy_cagr, excess_cagr,
  total_return, growth, spy_growth, empty_periods, short_periods. A random
  case's rows are its stored trial summaries; a fixed case's one row is the
  same summary (robustness.summarize) of its run, with null first_trade and
  cash_days.
- `statistics` (case, statistic): value of `<field>.<statistic>` for each
  distribution and the counts. A fixed case counts as one trial
  (robustness.summarize_trials).
- `periods` (case, trial, period): entry, exit, names, portfolio, spy.
- `holdings` (case, trial, period, rank): the stored holding's fields, with
  `return` for return_value, `contribution` for contribution_pp and `sleeve`,
  the number of its first picking sleeve.
- `steps` (case, trial, period, rank, sleeve, step): value and step_rank of
  each step of each picking sleeve. A built-in's value is in canonical units;
  a field step has no value; a Filter has no step_rank.
- `curve` (case, trial, period, day): portfolio and spy, the stored returns to
  date.
- `growth` (case, trial, day): strategy and spy (result_curves, one trial).
- `band` (case, day): median, lowest, highest and spy (result_curves, all).
- `sectors` (case, trial, sector): mean, minimum, maximum and present of each
  trial; mean, minimum, maximum and leading of trial `all` (result_sectors).
- `contributions` (case, trial, period): count, gains, losses, net, top_total,
  other_total and top (symbols joined by spaces): website/browser/
  contributions.js under Node on the period's holdings in rank order.
- `explore` (case, selection): result_exploration over periods 2 to the last
  and ranks from the first to one below the last. Selection `1` is trial 1;
  a random case also has `all` (the window, the statistics and the counts)
  and `all N` (trial N of that batch).
- `picks` (case, rank): symbol and ranking_value of the latest screen;
  `pick_steps` (case, rank, sleeve, step) as `steps`.
- `formula_values` (case, day, symbol, variable): value, for each `formulas`
  case: each named variable (Formulas.evaluate) of each candidate of the whole
  book scope (scalar_execution._scope, no exit) of each entry day. A value
  that is not valid is null.
"""
import argparse
from contextlib import closing, nullcontext
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile

import export
import oracle

FIELDS = {'sector': 'sector', 'exchange': 'exchange', 'market cap in dollars': 'market_cap',
          'enterprise value in dollars': 'enterprise_value'}
OPS = {'<': 'lt', '<=': 'le', '>': 'gt', '>=': 'ge', 'is': 'eq', 'is not': 'ne'}
TRIAL_FIELDS = ('start', 'first_trade', 'end', 'cash_days', 'periods', 'cagr', 'spy_cagr', 'excess_cagr',
                'total_return', 'growth', 'spy_growth', 'empty_periods', 'short_periods')
HOLDING_FIELDS = ('symbol', 'name', 'sector', 'exchange', 'candidate_rank', 'fiscal', 'entry', 'exit', 'market_cap',
                  'enterprise_value', 'ebitda', 'ebitda_yield', 'ev_ebitda', 'spread')
DISTRIBUTIONS = ('cagr', 'spy_cagr', 'excess_cagr', 'total_return', 'growth')
STATISTICS = ('n', 'mean', 'median', 'p10', 'p25', 'p75', 'p90', 'min', 'max', 'stddev')
COUNTS = ('completed', 'valid', 'incomplete', 'beat_spy', 'unique_schedules')
STATISTIC_NAMES = sorted([f'{field}.{statistic}' for field in DISTRIBUTIONS for statistic in STATISTICS] + list(COUNTS))
CONTRIBUTIONS = ("const {analyze}=require(process.argv[1]);let text='';process.stdin.on('data',part=>text+=part)"
                 ".on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(text).map(analyze))));")


def key(name):
    return ' '.join(name.split()).casefold()


def content(submitted, labels):
    """Formula content as the website submits it: each definition once, and the labels of those definitions."""
    entries = {(item['variable_id'], item['revision']): item for item in submitted}
    named = {(item['variable_id'], item['revision']): dict(variable_id=item['variable_id'], revision=item['revision'],
                                                           name=item['name']) for item in labels}
    return dict(submitted=list(entries.values()), labels=[label for identity, label in named.items() if identity in entries])


class Library:
    """The file's checked variables, as the formula editor's library."""

    def __init__(self):
        self.entries, self.submitted, self.labels = [], [], []

    def list(self):
        return self.entries

    def capture(self, roots, *, submitted, labels, checkpoint):
        from backtest.variables import library
        return library.capture_submitted(roots, **content(submitted + self.submitted, labels + self.labels),
                                         checkpoint=checkpoint)

    def check(self, text, display=None, name=''):
        """Check formula text with the editor; return its root, display and the content of its closure.

        An empty name is the text, as in the editor.
        """
        from backtest.application import variable_authoring
        checked = variable_authoring.validate(dict(formula=dict(text=text, display=display), name=name,
            variable_id='local:' + hashlib.sha256((name or text).encode()).hexdigest()[:16]), self)
        return dict(root=checked['root'], display=checked['output']['display'], submitted=checked['authored'],
                    labels=checked['capture']['presentation'])

    def define(self, name, variable):
        """Check a file variable and add it to the library."""
        checked = self.check(variable['formula'], variable.get('display'), name)
        self.entries.append(dict(checked['root'], name=name))
        self.submitted += checked['submitted']
        self.labels += checked['labels']
        return checked


def request(strategy, market):
    """The website's capture request {market, intent, submitted, labels} of a strategy file."""
    from backtest.application import strategy_requests, vocabulary
    builtins = {item['id']: item for item in strategy_requests.builtin_catalog()}
    names = {key(item['name']): item['builtins'][0] for item in vocabulary.entries() if item['builtins']}
    names[key('Free cash flow')] = 'filter:fcf'
    inputs = {key(item['name']): item['display'] for item in vocabulary.entries() if item['term'] and not item['builtins']}
    library, used = Library(), []
    variables = {key(name): library.define(name, variable) for name, variable in strategy.get('variables', {}).items()}

    def source(text):
        """The intent source of a step's source text, and its display."""
        name = key(text)
        if name in variables:
            checked = variables[name]
        elif name in FIELDS:
            return dict(kind='field', field=FIELDS[name]), strategy_requests.field_descriptor(FIELDS[name])['display']
        elif name in names:
            return dict(kind='builtin', id=names[name]), builtins[names[name]]['display']
        else:
            checked = library.check(text, inputs.get(name))
        used.append(checked)
        return dict(kind='formula', **checked['root']), checked['display']

    def steps(items):
        result = []
        for step in items:
            if 'rank' in step:
                result.append(dict(kind='rank', source=source(step['rank'])[0], direction=step['order'],
                                   rank_from=step['from'], rank_to=step['to']))
                continue
            found, display = source(step['filter'])
            threshold = step['value'] if display == 'text' else dict(value=step['value'], unit=display)
            result.append(dict(kind='filter', source=found, op=OPS[step['op']], threshold=threshold))
        return result

    intent = dict(format='strategy-intent', universe=dict(pool='cached'))
    if len(strategy['sleeves']) == 1:
        intent.update(version=2, steps=steps(strategy['sleeves'][0]['steps']))
    else:
        intent.update(version=3, sleeves=[dict(name=sleeve['name'], steps=steps(sleeve['steps']))
                                          for sleeve in strategy['sleeves']])
    return dict(market=market, intent=intent, **content([item for checked in used for item in checked['submitted']],
                                                        [item for checked in used for item in checked['labels']]))


def capture(strategy, market):
    """The captured strategy that the website submits for a strategy file."""
    from backtest.application import variable_authoring
    return variable_authoring.prepare(request(strategy, market), None)['strategy']


def calculate(mode, options, as_of):
    """Run as the website does and return a reader of the complete result."""
    from backtest import scalar_result_evidence
    from backtest.application.original_calculations import Original
    destination = io.BytesIO()
    with oracle.pinned(as_of):
        Original().calculate_into(mode, options, destination, None, None)
    return scalar_result_evidence.Reader(destination, max_bytes=256 * 1024 ** 2)


def run(folder, as_of):
    """Run one case and its latest screen."""
    from backtest.application import evidence_views
    from backtest.engines.original import robustness
    strategy = json.loads((folder / 'strategy.json').read_text(encoding='utf-8'))
    settings = json.loads((folder / 'run.json').read_text(encoding='utf-8'))
    mode, options = oracle.schedule(settings)
    captured = capture(strategy, settings['market'])
    reader = calculate(mode, dict(options, strategy=captured), as_of)
    summary = reader.manifest['summary']
    if mode == 'random':
        trials = summary['trials']
    else:
        view = evidence_views.trial(reader, 1)
        dates = [period['value']['entry'] for period in evidence_views.periods(reader, 1)]
        trials = [robustness.summarize(dict(dict(first_trade=None, cash_days=None), **view['summary']), 1, dates,
                                       period_counts=(view['periods'], view['empty'], view['short']))]
        summary = robustness.summarize_trials(None, trials, 0.)
    return dict(name=folder.name, kind=folder.parent.name, strategy=strategy, market=settings['market'],
                random=mode == 'random', reader=reader, trials=trials, summary=summary,
                screen=calculate('latest', dict(market=settings['market'], strategy=captured), as_of))


def stored(reader):
    """(trial, period number, period, holdings) of each stored period, in order."""
    trial = period = None
    for record in reader.verified_records():
        if record['type'] == 'trial':
            trial = record['number']
        elif record['type'] == 'period':
            period, holdings = record, []
        elif record['type'] == 'holding':
            holdings.append(record['value'])
        elif record['type'] == 'end_period':
            yield trial, period['number'], period['value'], holdings


def sleeves(reader):
    """The steps of each sleeve of the result's strategy."""
    from backtest.application import strategy_requests
    return strategy_requests.chains(reader.metadata['options']['strategy'])


def step_rows(row, sleeves):
    """Each picking sleeve's steps of a holding or screen row: sleeve, step, value, step_rank."""
    evidence = row['scalar_evidence']
    picks = evidence['sleeves'] if 'sleeves' in evidence else [dict(sleeve=0, steps=evidence['steps'])]
    for pick in picks:
        # Lanes number the steps across sleeves.
        start = sum(map(len, sleeves[:pick['sleeve']]))
        for index, (step, rank) in enumerate(zip(sleeves[pick['sleeve']], pick['steps'])):
            lane = None if step['source']['kind'] == 'field' else evidence['lanes']['s' + str(start + index)]
            value = None if lane is None else lane['canonical'] if step['source']['kind'] == 'builtin' else lane['value']
            yield dict(sleeve=pick['sleeve'] + 1, step=index + 1, value=value, step_rank=rank)


def trial_rows(cases):
    for case in cases:
        for row in case['trials']:
            yield dict(case=case['name'], trial=row['trial'], dates=' '.join(row['dates']),
                       **{field: row[field] for field in TRIAL_FIELDS})


def statistic_rows(cases):
    for case in cases:
        summary = case['summary']
        for name in STATISTIC_NAMES:
            field, _, statistic = name.partition('.')
            yield dict(case=case['name'], statistic=name,
                       value=summary['distributions'][field][statistic] if statistic else summary[name])


def period_rows(cases):
    for case in cases:
        for trial, number, period, _ in stored(case['reader']):
            yield dict(case=case['name'], trial=trial, period=number,
                       **{field: period[field] for field in ('entry', 'exit', 'names', 'portfolio', 'spy')})


def holding_rows(cases):
    for case in cases:
        for trial, period, _, holdings in stored(case['reader']):
            for row in holdings:
                evidence = row['scalar_evidence']
                fields = dict(case=case['name'], trial=trial, period=period, rank=row['rank'],
                              **{field: row[field] for field in HOLDING_FIELDS})
                fields.update({'return': row['return_value']}, status=row['status'], ranking_value=row['ranking_value'],
                              sleeve=evidence['sleeves'][0]['sleeve'] + 1 if 'sleeves' in evidence else 1,
                              weight=row['weight'], contribution=row['contribution_pp'])
                yield fields


def holding_step_rows(cases):
    for case in cases:
        steps = sleeves(case['reader'])
        for trial, period, _, holdings in stored(case['reader']):
            for row in holdings:
                for step in step_rows(row, steps):
                    yield dict(case=case['name'], trial=trial, period=period, rank=row['rank'], **step)


def curve_rows(cases):
    for case in cases:
        for trial, number, period, _ in stored(case['reader']):
            for day, portfolio, spy in period['curve']:
                yield dict(case=case['name'], trial=trial, period=number, day=day, portfolio=portfolio, spy=spy)


def growth_rows(cases):
    from backtest.application import result_curves
    for case in cases:
        for trial in range(1, case['reader'].manifest['trials'] + 1):
            curve = result_curves.evidence(case['reader'], trial)
            for day, strategy, spy in zip(curve['days'], curve['strategy'], curve['spy']):
                yield dict(case=case['name'], trial=trial, day=day, strategy=strategy, spy=spy)


def band_rows(cases):
    from backtest.application import result_curves
    for case in cases:
        band = result_curves.evidence(case['reader'], 'all')
        for day, median, lowest, highest, spy in zip(band['days'], band['median'], band['lowest'], band['highest'],
                                                      band['spy']):
            yield dict(case=case['name'], day=day, median=median, lowest=lowest, highest=highest, spy=spy)


def sector_rows(cases):
    from backtest.application import result_sectors
    for case in cases:
        for trial in range(1, case['reader'].manifest['trials'] + 1):
            for sector in result_sectors.evidence(case['reader'], trial)['trials'][0]['sectors']:
                yield dict(case=case['name'], trial=trial, sector=sector.pop('name'), **sector)
        for sector in result_sectors.evidence(case['reader'], 'all')['sectors']:
            yield dict(case=case['name'], trial='all', sector=sector.pop('name'), **sector)


def contribution_rows(cases):
    for case in cases:
        periods = list(stored(case['reader']))
        books = [[dict(symbol=row['symbol'], return_value=row['return_value']) for row in holdings]
                 for _, _, _, holdings in periods]
        found = subprocess.run(['node', '-e', CONTRIBUTIONS, str(oracle.CHECKOUT / 'website/browser/contributions.js')],
                               input=json.dumps(books), capture_output=True, text=True, check=True).stdout
        for (trial, period, _, _), result in zip(periods, json.loads(found)):
            yield dict(case=case['name'], trial=trial, period=period,
                       **{field: result[field] for field in ('count', 'gains', 'losses', 'net', 'top_total', 'other_total')},
                       top=' '.join(row['symbol'] for row in result['top']))


def explore_rows(cases):
    from backtest import selection
    from backtest.application import result_exploration
    for case in cases:
        reader = case['reader']
        first, last = selection.rank_range(reader.metadata['options'])
        chosen = dict(period_from=2, period_to=sum(trial == 1 for trial, _, _, _ in stored(reader)),
                      rank_from=first, rank_to=last - 1)
        rows = {'1': result_exploration.evidence(reader, dict(chosen, trial=1))}
        if case['random']:
            batch = result_exploration.evidence(reader, dict(chosen, trial='all'))
            rows['all'] = dict({key: batch['exploration'][key] for key in ('start', 'end', 'periods')},
                **{f'{field}.{statistic}': batch['distributions'][field][statistic]
                   for field in DISTRIBUTIONS for statistic in STATISTICS},
                **{name: batch[name] for name in COUNTS})
            for row in batch['trials']:
                rows[f'all {row["trial"]}'] = dict({field: row[field] for field in TRIAL_FIELDS},
                    dates=' '.join(row['dates']), last_exit=row['last_exit'], final_cash_days=row['final_cash_days'])
        for selected in sorted(rows):
            yield dict(case=case['name'], selection=selected, **rows[selected])


def screened(case):
    return (record['value'] for record in case['screen'].verified_records() if record['type'] == 'screen')


def pick_rows(cases):
    for case in cases:
        for row in screened(case):
            yield dict(case=case['name'], rank=row['rank'], symbol=row['symbol'], ranking_value=row['ranking_value'])


def pick_step_rows(cases):
    for case in cases:
        steps = sleeves(case['screen'])
        for row in screened(case):
            for step in step_rows(row, steps):
                yield dict(case=case['name'], rank=row['rank'], **step)


def formula_value_rows(cases):
    """Each named variable over each entry day's whole book scope, as the scope's formula evaluation reads it."""
    from backtest.application import scalar_execution, strategy_requests
    from backtest.inputs import book_store, fact_view
    from backtest.variables import columns
    with closing(oracle.connect()) as db:
        for case in cases:
            if case['kind'] != 'formulas':
                continue
            names = sorted(case['strategy']['variables'])
            # One Rank per variable makes every named variable a root of the program.
            ranks = [{'rank': name, 'order': 'highest', 'from': 1, 'to': 1} for name in names]
            checked = strategy_requests.check_options(dict(market=case['market'], strategy=capture(
                dict(variables=case['strategy']['variables'], sleeves=[dict(steps=ranks)]), case['market'])))
            formulas = columns.Formulas(checked['variables']['program'])
            outputs = [(step['source']['variable_id'], step['source']['revision']) for step in checked['steps']]
            view = fact_view.View(db, lambda: None, lambda: None, market=case['market'])
            for day in sorted({period['entry'] for _, _, period, _ in stored(case['reader'])}):
                book = book_store.find(db, day, 'cached', market=case['market'])
                rows, admission = scalar_execution._scope(db, checked, book, day, latest=False, market=case['market'])
                if not rows:
                    continue
                roots, decisions = zip(*map(admission, range(len(rows))))
                values = formulas.evaluate(list(roots), view, lambda: None, decisions=list(decisions), outputs=outputs)
                for row, found in zip(rows, values):
                    for name, output in zip(names, outputs):
                        value, valid, _ = found[output]
                        yield dict(case=case['name'], day=day, symbol=row[0], variable=name,
                                   value=value if valid else None)


TABLES = {
    'trials': (('case', 'trial'), trial_rows),
    'statistics': (('case', 'statistic'), statistic_rows),
    'periods': (('case', 'trial', 'period'), period_rows),
    'holdings': (('case', 'trial', 'period', 'rank'), holding_rows),
    'steps': (('case', 'trial', 'period', 'rank', 'sleeve', 'step'), holding_step_rows),
    'curve': (('case', 'trial', 'period', 'day'), curve_rows),
    'growth': (('case', 'trial', 'day'), growth_rows),
    'band': (('case', 'day'), band_rows),
    'sectors': (('case', 'trial', 'sector'), sector_rows),
    'contributions': (('case', 'trial', 'period'), contribution_rows),
    'explore': (('case', 'selection'), explore_rows),
    'picks': (('case', 'rank'), pick_rows),
    'pick_steps': (('case', 'rank', 'sleeve', 'step'), pick_step_rows),
    'formula_values': (('case', 'day', 'symbol', 'variable'), formula_value_rows),
}


def main():
    parser = argparse.ArgumentParser(description='Run the oracle on strategy files and export whole runs.')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--raw', type=Path)
    source.add_argument('--workspace', type=Path)
    parser.add_argument('--as-of', type=export.as_of, required=True)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    folders = sorted((path.parent for path in args.cases.glob('*/*/strategy.json')), key=lambda path: path.name)
    with tempfile.TemporaryDirectory() if args.workspace is None else nullcontext(args.workspace) as folder:
        if args.workspace is None:
            oracle.build(args.raw, folder)
        oracle.load(folder)
        if args.workspace is None:
            oracle.prepare(args.as_of)
        cases = [run(path, args.as_of) for path in folders]
        settings = dict(as_of=args.as_of.isoformat(), backtest=oracle.tree(folder), cases=[path.name for path in folders])
        counts = export.write(args.out, settings, {name: (keys, rows(cases)) for name, (keys, rows) in TABLES.items()})
    print(f'Exported to {args.out}: ' + ', '.join(f'{name} {count}' for name, count in counts.items()))


if __name__ == '__main__':
    main()
