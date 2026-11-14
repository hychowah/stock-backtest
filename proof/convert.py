"""Convert the oracle's saved tests, queue and variable library into strategy files, once, at the switch.

    python3 proof/convert.py --out DIR [--data DIR] [REQUEST ...]

`--data` is a folder that holds the product's stores as the product keeps them in `data/`: saved-backtests.sqlite,
backtest-queue.sqlite and variable-library.sqlite (a missing store is empty). They are copied with SQLite's backup
into a temporary folder and read there with the product's own modules, so the folder is never written. A REQUEST is
the JSON file of one test outside the stores: `{mode, options}` as the website sends it, with flat options or a
strategy capture (1 to 3) in options.strategy, or `{mode, options, intent, submitted?, labels?}` with a strategy
intent (1 to 3), which is captured first as the website's capture route does, with the library of `--data`.
Flat options and capture-1 bounds become steps as the website's own conversion makes them (website/browser/
range.js, fromSettings and boundSteps); flat options use the pool that the engine uses (legacy for the US, cached
elsewhere). The deleted engine label "experimental" is dropped: the new program has one engine.

It writes in DIR:
- `strategies/<id>.json`, one file per distinct strategy in the format of proof/l3.py; `<id>` is the first 16 hex
  digits of the file's SHA-256. A step names its source as l3.source_names spells it (a later link of a vocabulary
  entry, such as filter:ebitda_yield, folds into the entry's name). Each formula is a variable, dependencies
  first, whose text is formula_text.to_text of the stored definition. A threshold is the stored decimal, scaled
  exactly into the display unit of its source. A variable name that is a source name, or names another
  variable already, gets " (2)", " (3)" and so on.
- `tests.jsonl`, one line per test: name, source (saved, queue or file), id (the record id or the file path),
  created_at, locked (saved) or state and position (queue), run (proof/oracle.py's run settings, with the
  recorded seed when the request has none) and strategy (the file's path in DIR). Saved tests come newest first,
  queued tests in queue order, files in argument order.
- `variables.jsonl`, one line per active variable of the library: name (renamed as in strategy files), favourite
  and revisions (oldest first), each with formula, display and current.
- `unconverted.jsonl`: source, id, name and reason of each test or revision that cannot be converted exactly.

A converted strategy must read back: its file, read by l3.request and captured by the oracle, gives the same
steps, sources, operators, ranks and decimal thresholds, and each variable the stored formula (references, the
measures as their names read, unit and display). A library revision's text must read back the same way in the
formula editor. proof/convert_proof.py runs each converted test against its original. The fixture's stores were
written once with the oracle's own modules; its expected output:

    python3 proof/convert.py --data fixtures/fictional/saved/data --out fixtures/fictional/saved/expected \\
        fixtures/fictional/saved/requests/*.json
"""
import argparse
from contextlib import closing
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

import cases
import l3
import oracle

ROOT = Path(__file__).resolve().parents[1]
SAVED, QUEUE, VARIABLES = 'saved-backtests.sqlite', 'backtest-queue.sqlite', 'variable-library.sqlite'
OPS = {op: text for text, op in l3.OPS.items()}
# A display unit's decimal exponent: canonical value = display value * 10**exponent.
EXPONENTS = {'percent': -2, 'percentage_points': -2, 'usd_million': 6}
RUN_KEYS = {'market', 'start', 'end', 'months', 'calendar', 'dates', 'trials', 'seed', 'engine'}
FLAT_DEFAULTS = dict(rank_from=1, rank_to=50, metric='ev_ebitda', min_cap=100e6, max_cap=None, min_ev=50e6,
                     min_yield=0, max_multiple=None, sector=None, exchange=None, filters=None,
                     selection_order='filter_first')
# range.js boundSteps: (bound, lane, op); a lane is a field or the ranked metric's yield or multiple.
BOUNDS = (('min_cap', 'market_cap', 'ge'), ('max_cap', 'market_cap', 'le'), ('min_ev', 'enterprise_value', 'ge'),
          ('sector', 'sector', 'eq'), ('exchange', 'exchange', 'eq'), ('min_yield', 'yield', 'ge'),
          ('max_multiple', 'multiple', 'le'))
LEGACY_POOL = 'it selects from the legacy US pool (the top 250 by report yield), which the new program does not have'


class Refused(Exception):
    """A test or variable that cannot be converted exactly; the message is the reason in plain words."""


def number(value):
    """The exact decimal of a stored JSON number."""
    return Decimal(repr(value))


def text(value, exponent=0):
    """Plain decimal text of value / 10**exponent."""
    with localcontext() as context:
        context.prec = 2048
        return format(Decimal(value).scaleb(-exponent).normalize(), 'f')


def unique(name, used):
    """name, or name (2), (3) ... when its key is used already; its key is then used."""
    found, count = name, 1
    while l3.key(found) in used:
        count += 1
        found = f'{name} ({count})'
    used.add(l3.key(found))
    return found


def shape(expression, rename):
    """An expression with each reference node replaced by rename(node)."""
    if expression['op'] == 'ref':
        return rename(expression)
    return {key: shape(value, rename) if key in ('left', 'right', 'arg') else value for key, value in expression.items()}


def failed(error):
    return Refused('the oracle refuses it: ' + str(error))


class Converter:
    """The current catalog's names, and the conversion of one test at a time."""

    def __init__(self):
        from backtest.application import strategy_requests, vocabulary
        self.catalog = {item['id']: item for item in strategy_requests.builtin_catalog()}
        listed = l3.source_names()
        self.spelled = {source: name for name, source in listed.items()}
        self.reads = {link: entry['builtins'][0] for entry in vocabulary.entries() for link in entry['builtins']}
        self.taken = {l3.key(name) for name in listed} | {l3.key(entry['name']) for entry in vocabulary.entries()}
        self.terms = {entry['name']: entry['term'] for entry in vocabulary.entries() if entry['term']}
        self.named = vocabulary.names()

    # A source is ('builtin', id), ('field', field) or ('formula', variable name, display).
    def read(self, source):
        """What a source reads after conversion: a folded built-in reads its entry's first link."""
        return ('builtin', self.reads.get(source[1], source[1])) if source[0] == 'builtin' else source[:2]

    def source(self, source):
        """The step text and display of a source."""
        if source[0] == 'formula':
            return source[1], source[2]
        read = self.read(source)
        if read not in self.spelled:
            raise Refused(f'the built-in {source[1]} has no source name')
        display = (self.catalog[read[1]]['display'] if read[0] == 'builtin'
                   else 'text' if read[1] in ('sector', 'exchange') else 'usd')
        return self.spelled[read], display

    def filter(self, source, op, canonical):
        """A Filter step with its meaning; canonical is the threshold in canonical units, or the text of a field."""
        name, display = self.source(source)
        value = canonical if display == 'text' else text(canonical, EXPONENTS.get(display, 0))
        return dict(filter=name, op=OPS[op], value=value,
                    meaning=('filter', self.read(source), op, canonical if display == 'text' else Decimal(canonical)))

    def rank(self, source, direction, first, last):
        return {'rank': self.source(source)[0], 'order': direction, 'from': first, 'to': last,
                'meaning': ('rank', self.read(source), direction, first, last)}

    def bounds(self, values, metric, flat):
        """The Filter steps of flat or capture-1 bounds (range.js boundSteps)."""
        steps = []
        for key, lane, op in BOUNDS:
            value = values.get(key)
            if key not in values or value == 0 and op == 'ge' or value is None and not (flat and op == 'ge'):
                continue
            if value is None:
                raise Refused(f'its {key} has no value, so it matches no company')
            source = ('builtin', f'metric:{metric}:{lane}') if lane in ('yield', 'multiple') else ('field', lane)
            steps.append(self.filter(source, op, value if op == 'eq' else number(value)))
        return steps

    def flat(self, options, market):
        """(sleeves, no formulas) of flat options, as the website converts them, on the engine's pool."""
        from backtest import screening
        from backtest.application import strategy_requests
        from backtest.financial import metrics
        settings = {key: value for key, value in options.items() if key not in RUN_KEYS}
        unknown = sorted(set(settings) - set(FLAT_DEFAULTS) - {'pool'})
        if unknown:
            raise Refused('it has options the oracle does not know: ' + ', '.join(unknown))
        values = dict(FLAT_DEFAULTS, pool='legacy' if market == 'us' else 'cached')
        values.update(settings)
        try:
            strategy_requests.check_options(dict(options, market=market))
            screening.validate_selection(**values)
        except (ValueError, TypeError) as error:
            raise failed(error) from None
        if values['pool'] != 'cached':
            raise Refused(LEGACY_POOL)
        filters = self.bounds(values, values['metric'], True)
        for item in metrics.validate_filters(values['filters']):
            source = ('builtin', 'filter:' + item['field'])
            stored = self.catalog[source[1]]['storage']['scale']  # A flat value is in the lane's stored scale.
            filters.append(self.filter(source, item['op'], number(item['value']).scaleb(stored)))
        rank = self.rank(('builtin', f'metric:{values["metric"]}:yield'), 'highest', values['rank_from'], values['rank_to'])
        return [dict(steps=ordered(values['selection_order'], filters, rank))], dict(names={}, variables={}, stored={})

    def capture(self, capture, market):
        """(sleeves, formulas) of a strategy capture 1, 2 or 3; formulas as Converter.formulas gives them."""
        from backtest.application import strategy_requests
        try:
            checked = strategy_requests.check_options(dict(market=market, strategy=capture))
        except (ValueError, TypeError, KeyError) as error:
            raise failed(error) from None
        if strategy_requests.pool(checked) != 'cached':
            raise Refused(LEGACY_POOL)
        formulas = self.formulas(checked)

        def source(item):
            if item['kind'] == 'formula':
                name = formulas['names'][item['variable_id'], item['revision']]
                return 'formula', name, formulas['variables'][name]['display']
            return item['kind'], item.get('id', item.get('field'))

        if checked['version'] == 1:
            selection = checked['selection']
            ranking = selection['ranking']
            filters = self.bounds(checked['bounds'], ranking['source'].get('id', ':').split(':')[1], False)
            filters += [self.filter(source(item['source']), item['op'], item['threshold']['value'])
                        for item in selection['conditions']]
            rank = self.rank(source(ranking['source']), ranking['direction'], selection['rank_from'], selection['rank_to'])
            return [dict(steps=ordered(selection['selection_order'], filters, rank))], formulas
        sleeves = []
        for name, chain in zip([item['name'] for item in checked.get('sleeves', [dict(name='')])],
                               strategy_requests.chains(checked)):
            steps = []
            for step in chain:
                if step['kind'] == 'rank':
                    steps.append(self.rank(source(step['source']), step['direction'], step['rank_from'], step['rank_to']))
                else:
                    threshold = step['threshold']
                    steps.append(self.filter(source(step['source']), step['op'],
                                             threshold if step['op'] in ('eq', 'ne') else threshold['value']))
            sleeves.append(dict(name=name, steps=steps))
        return sleeves, formulas

    def formulas(self, checked):
        """{names: each identity's variable name, variables: the file's variables, dependencies first,
        stored: each variable's stored definition, with references as the file reads them}."""
        from backtest.application import formula_text, strategy_requests
        result = dict(names={}, variables={}, stored={})
        if checked['variables'] is None:
            return result
        definitions = {(item['variable_id'], item['revision']): item['definition']
                       for item in checked['variables']['program']['bundle']['definitions']}
        labels = {(item['variable_id'], item['revision']): item['name'] for item in checked['variables']['presentation']}
        names, used = result['names'], set(self.taken)

        def rename(node):
            """A reference as its text reads (formula_text.to_text): a measure as its name's term, else a file variable."""
            if node['variable_id'] in self.named:
                return self.terms[self.named[node['variable_id']]]
            return dict(op='variable', name=names[node['variable_id'], node['revision']])

        def visit(identity):
            if identity in names:
                return
            definition = definitions[identity]
            for node in cases.nodes(definition['expression']):
                if node['op'] == 'ref' and node['variable_id'] not in self.named:
                    visit((node['variable_id'], node['revision']))
            name = names[identity] = unique(labels[identity], used)
            known = [dict(variable_id=key[0], revision=key[1], name=value) for key, value in names.items()]
            try:
                formula = formula_text.to_text(definition, known)
            except KeyError:
                raise Refused(f'the formula of "{labels[identity]}" names an input that the current catalog '
                              'does not have') from None
            result['variables'][name] = dict(formula=formula, display=definition['output']['display'])
            result['stored'][name] = (shape(definition['expression'], rename), definition['output'])

        for item in strategy_requests.sources(checked):
            if item['kind'] == 'formula':
                visit((item['variable_id'], item['revision']))
        return result

    def check(self, strategy, meaning, stored, market):
        """The file, read back by the proof adapter and captured by the oracle, must give the same steps and formulas."""
        from backtest.application import strategy_requests
        try:
            captured = l3.capture(strategy, market)
        except (ValueError, TypeError, KeyError) as error:
            raise Refused('the converted file does not read back: ' + str(error)) from None
        program = captured['variables'] or dict(presentation=[], program=dict(bundle=dict(definitions=[])))
        labels = {(item['variable_id'], item['revision']): item['name'] for item in program['presentation']
                  if item['variable_id'].startswith('local:')}
        found = []
        for step in sum(strategy_requests.chains(captured), []):
            source = step['source']
            read = ((source['kind'], source.get('id', source.get('field'))) if source['kind'] != 'formula'
                    else ('formula', labels[source['variable_id'], source['revision']]))
            if step['kind'] == 'rank':
                found.append(('rank', read, step['direction'], step['rank_from'], step['rank_to']))
            else:
                threshold = step['threshold']
                found.append(('filter', read, step['op'],
                              threshold if step['op'] in ('eq', 'ne') else Decimal(threshold['value'])))
        if found != meaning:
            raise Refused('the converted file reads back to other steps')

        def rename(node):
            identity = node['variable_id'], node['revision']
            return dict(op='variable', name=labels[identity]) if identity in labels else node

        read = {labels[item['variable_id'], item['revision']]: (shape(item['definition']['expression'], rename),
                                                                item['definition']['output'])
                for item in program['program']['bundle']['definitions'] if (item['variable_id'], item['revision']) in labels}
        # A variable that reads back differently comes first; a missing one is only read by such a variable.
        for name in sorted(stored, key=lambda name: name not in read):
            if read.get(name) != stored[name]:
                raise Refused(f'the text of its variable "{name}" reads back as a different formula')

    def test(self, mode, options, seed):
        """(run settings, strategy file, each formula identity's variable name) of one test."""
        if mode == 'january':
            raise Refused('the January mode was removed from the oracle')
        if mode not in ('custom', 'random'):
            raise Refused(f'its mode "{mode}" is not a dated test')
        market = options.get('market', 'us')
        sleeves, formulas = (self.capture(options['strategy'], market) if 'strategy' in options
                             else self.flat(options, market))
        run = schedule(mode, options, seed)
        meaning = [step.pop('meaning') for sleeve in sleeves for step in sleeve['steps']]
        if len(sleeves) == 1:
            sleeves[0].pop('name', None)
        strategy = dict(sleeves=sleeves)
        if formulas['variables']:
            strategy = dict(variables=formulas['variables'], sleeves=sleeves)
        self.check(strategy, meaning, formulas['stored'], market)
        return run, strategy, formulas['names']


def ordered(selection_order, filters, rank):
    return [rank] + filters if selection_order == 'rank_first' else filters + [rank]


def schedule(mode, options, seed):
    """The run settings of proof/oracle.py: market, start, end, interval or dates, trials and seed."""
    from backtest import calendar_requests
    run = dict(market=options.get('market', 'us'))
    try:
        configuration, _, _ = calendar_requests.decode_request(
            {key: options[key] for key in ('calendar', 'start', 'end', 'months') if key in options})
    except ValueError as error:
        raise Refused('its dates cannot be read: ' + str(error)) from None
    run.update(start=configuration.start, end=configuration.end)
    if 'dates' in options:
        run['dates'] = options['dates']
    else:
        run['interval'] = f'{configuration.interval.count}{configuration.interval.unit[0]}'
    if mode == 'random':
        run.update(trials=options.get('trials', 24), seed=seed if options.get('seed') is None else options['seed'])
        if run['seed'] is None:
            raise Refused('its random dates have no recorded seed')
    return run


def copy_stores(data, folder):
    """Copy each store of data into folder with SQLite's backup, reading the originals only."""
    for name in (SAVED, QUEUE, VARIABLES):
        if (data / name).is_file():
            with closing(sqlite3.connect(f'{(data / name).resolve().as_uri()}?mode=ro', uri=True)) as source, \
                    closing(sqlite3.connect(folder / name)) as target:
                source.backup(target)


def saved(folder):
    """(record, mode, options, recorded seed) of each saved test."""
    from backtest.application import durable_evidence, library
    if not (folder / SAVED).is_file():
        return
    store = library.Store(folder / SAVED)
    with closing(store.connect()) as db:
        for record in store.list():
            item = dict(name=record['name'], source='saved', id=record['id'], created_at=record['created_at'],
                        locked=record['locked'])
            try:
                packed = db.execute('SELECT snapshot FROM records WHERE id=?', (record['id'],)).fetchone()[0]
                snapshot = (durable_evidence._unpack(packed, record['id'], durable_evidence.MAX_EVIDENCE_BYTES)[0]
                            if durable_evidence.is_evidence(packed) else store.get(record['id'])['snapshot'])
                options = dict(snapshot['settings'])
                yield item, options.pop('mode'), options, snapshot['result'].get('configuration', {}).get('seed')
            except (ValueError, KeyError, TypeError) as error:
                yield item, Refused('its stored record cannot be read: ' + str(error)), None, None


def queued(folder):
    """(record, mode, options, seed) of each queued test, in queue order."""
    from backtest.application import queue
    if not (folder / QUEUE).is_file():
        return
    store = queue.Store(folder / QUEUE)
    listing = store.listing()['records']
    with store.database() as db:
        seeds = {record['id']: queue.Store.row(db, record['id'])['seed'] for record in listing}
    for record in listing:
        yield (dict(name=record['name'], source='queue', id=record['id'], created_at=record['created_at'],
                    state=record['state'], position=record['position']),
               record['mode'], record['options'], seeds[record['id']])


def requested(paths, folder):
    """(record, mode, options, None) of each request file; an intent is captured first."""
    from backtest.application import variable_authoring
    from backtest.variables import library
    store = library.Store(folder / VARIABLES)  # An absent library holds no variable.
    for path in paths:
        item = dict(name=path.stem, source='file', id=str(path))
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            mode, options = value['mode'], dict(value['options'])
            if 'intent' in value:
                options['strategy'] = variable_authoring.prepare(dict(
                    market=options.get('market', 'us'), intent=value['intent'], submitted=value.get('submitted', []),
                    labels=value.get('labels', [])), store)['strategy']
        except (ValueError, TypeError, KeyError) as error:
            yield item, Refused('the oracle cannot read or capture the request: ' + str(error)), None, None
            continue
        yield item, mode, options, None


def variables(folder, converter):
    """(lines of variables.jsonl, refusals) of the variable library."""
    from backtest.application import formula_text, variable_authoring
    from backtest.variables import library
    if not (folder / VARIABLES).is_file():
        return [], []
    store = library.Store(folder / VARIABLES)
    with store._transaction() as db:
        revisions = db.execute('SELECT variable_id, revision FROM revisions ORDER BY created_at, revision').fetchall()

    def rename(node):
        """A measure reads as its name's term; a saved variable stays itself."""
        return node if node['variable_id'].startswith('var:') else converter.terms[converter.named[node['variable_id']]]

    lines, refused, used = [], [], set(converter.taken)
    for entry in store.list():
        kept = []
        for variable_id, revision in revisions:
            if variable_id != entry['variable_id']:
                continue
            snapshot = store.authoring_snapshot(dict(variable_id=variable_id, revision=revision))
            definition = next(item['definition'] for item in snapshot['authored']
                              if (item['variable_id'], item['revision']) == (variable_id, revision))
            display = definition['output']['display']
            try:
                formula = formula_text.to_text(definition, snapshot['capture']['presentation'])
                checked = variable_authoring.validate(
                    dict(formula=dict(text=formula, display=display), name=entry['name']), store)
                read = next(item['definition'] for item in checked['authored']
                            if (item['variable_id'], item['revision']) == tuple(checked['root'].values()))
                if (shape(read['expression'], rename), read['output']) != (shape(definition['expression'], rename),
                                                                           definition['output']):
                    raise Refused('its text reads back as a different formula')
            except (Refused, ValueError, KeyError) as error:
                refused.append(dict(source='variables', id=f'{variable_id} {revision}', name=entry['name'],
                                    reason='the revision does not convert: ' + str(error)))
                continue
            kept.append(dict(formula=formula, display=display, current=revision == entry['revision']))
        if kept:
            lines.append(dict(name=unique(entry['name'], used), favourite=entry['favourite'], revisions=kept))
    return lines, refused


def write_lines(path, rows):
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8', newline='\n')


def originals(data, paths, converter):
    """((record, mode, options, seed) of each test, (variable lines, refusals)) of a data folder and request files."""
    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch)
        if data is not None:
            copy_stores(data, folder)
        return [*saved(folder), *queued(folder), *requested(paths, folder)], variables(folder, converter)


def convert(data, paths):
    """(tests, strategies by file name, variable lines, refusals) of a data folder and request files."""
    converter, tests, strategies, refused = Converter(), [], {}, []
    found, (lines, unread) = originals(data, paths, converter)
    for item, mode, options, seed in found:
        try:
            if isinstance(mode, Refused):
                raise mode
            run, strategy, _ = converter.test(mode, options, seed)
        except Refused as reason:
            refused.append(dict(item, reason=str(reason)))
            continue
        body = cases.text(strategy)
        name = 'strategies/' + hashlib.sha256(body.encode()).hexdigest()[:16] + '.json'
        strategies[name] = body
        tests.append(dict(item, run=run, strategy=name))
    refused = [{key: row[key] for key in ('source', 'id', 'name', 'reason')} for row in refused]
    return tests, strategies, lines, refused + unread


def main():
    parser = argparse.ArgumentParser(description="Convert the oracle's saved tests, queue and variables.")
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--data', type=Path)
    parser.add_argument('requests', type=Path, nargs='*')
    args = parser.parse_args()
    oracle.load(ROOT)
    tests, strategies, lines, refused = convert(args.data, args.requests)
    (args.out / 'strategies').mkdir(parents=True, exist_ok=True)
    for name, body in strategies.items():
        (args.out / name).write_text(body, encoding='utf-8', newline='\n')
    write_lines(args.out / 'tests.jsonl', tests)
    write_lines(args.out / 'variables.jsonl', lines)
    write_lines(args.out / 'unconverted.jsonl', refused)
    print(f'Converted {len(tests)} tests into {len(strategies)} strategy files and {len(lines)} variables; '
          f'{len(refused)} not converted.')


if __name__ == '__main__':
    main()
