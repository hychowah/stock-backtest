"""Write the generated cases of the whole-run proof (proof/l3.py) and check that they cover the oracle's language.

    python3 proof/cases.py

Run it with no options. It writes
fixtures/fictional/cases/<kind>/<name>/{strategy,run}.json for each case of
`CASES` and `measure_cases()`, byte for byte the same each time. A case is
`builtins` when its strategy file has no variable, else `formulas`. The
hand-written cases of those folders are not listed here and stay as they are.
To drop a generated case, remove it from the list and delete its folder.

The coverage check runs first. It lists what the oracle's own modules define
and reads what the cases use through the adapter (proof/l3.py):
- each built-in of the catalog, in a Rank and in a Filter (a later link of a
  vocabulary entry folds into its first link, which is what a step reads);
- each field in a Filter, and the dollar fields in a Rank; each operator;
- each operation of the formula language, each formula function (each takes
  its own time form: years, months or a date) and a constant in each unit;
- a variable that reads a variable, a chain of three variables and a nested
  expression; each named measure; one whole-name step of a linked quantity and
  one of an unlinked input;
- two sleeves whose first Rank steps overlap, and a rank range from 2;
- fixed weeks, fixed months, explicit dates and random dates; each market.
It stops with the missing items before it writes a file. A new built-in,
function, operation, unit or measure in the oracle makes it fail until a case
uses it.

To add a case: add a `case(...)` line to `CASES` (a name, a market, run
settings, then its sleeves and its variables), and give a market
a window and a schedule that an existing case already uses, so that the day
sets of proof/export.py grow little. Choose thresholds from the candidate
values in fixtures/fictional/expected/<market>/candidates.jsonl, so that a
Filter keeps some candidates and drops some, then regenerate the expected
tables as proof/l3.py and proof/export.py describe.

In a `formulas` case every formula is a named variable, because the table
`formula_values` proves each named variable over every candidate. The
exception is a whole-name step of an unlinked input, such as "Revenue": the
step reads the input's formula, and a variable of the same text proves it.
"""
import json
from pathlib import Path
import re

import l3
import oracle

ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / 'fixtures' / 'fictional' / 'cases'
MARKETS = ('us', 'hk', 'jp')
ARITHMETIC = ('add', 'sub', 'mul', 'div', 'positive_div')
SCHEDULES = ('fixed weeks', 'fixed months', 'explicit dates', 'random dates')

# Run settings that cases share, so that a market's day set grows once per schedule.
# The explicit dates are days that the day sets hold already.
WINDOW = dict(start='2021-07-01', end='2023-06-28')
SIX_MONTHS = dict(WINDOW, interval='6m')
WEEKS = dict(start='2023-01-02', end='2023-03-31', interval='2w')
HK_DATES = dict(WINDOW, dates=['2021-09-24', '2022-01-13', '2022-05-23', '2022-10-20', '2023-03-15'])
JP_DATES = dict(WINDOW, dates=['2021-08-27', '2021-12-01', '2022-03-01', '2022-07-15', '2022-10-25', '2023-02-13'])
JP_RANDOM = dict(SIX_MONTHS, trials=2, seed=7)


def filter_(source, op, value):
    return dict(filter=source, op=op, value=value)


def rank(source, order='highest', first=1, last=3):
    return {'rank': source, 'order': order, 'from': first, 'to': last}


def sleeve(name, *steps):
    return dict(name=name, steps=list(steps))


def pair(source, op, value, order, last):
    """A sleeve of one Filter and one Rank on the same source."""
    return sleeve(source, filter_(source, op, value), rank(source, order, 1, last))


CASES = []


def case(name, market, run, sleeves, variables=None):
    CASES.append(dict(name=name, market=market, run=dict(market=market, **run), sleeves=sleeves, variables=variables))


# Built-ins: each in a Filter and in a Rank, with thresholds near the market's median.
case('us-built-ins-months', 'us', SIX_MONTHS, [
    pair('EV/EBITDA', '<', '18', 'lowest', 3),
    pair('EBITDA yield', '>=', '5.5', 'highest', 3),
    pair('EV/3-year average EBITDA', '<=', '19', 'lowest', 4),
    pair('3-year average EBITDA yield', '>', '5.3', 'highest', 3),
    pair('P/B', '<', '5.2', 'lowest', 3),
    pair('P/E', '<', '28', 'lowest', 3),
    pair('P/S', '>', '2.9', 'highest', 3),
    pair('P/E 3-year average', '<=', '23', 'lowest', 3),
    pair('P/E 5-year average', '<', '18.5', 'lowest', 3)])
case('hk-built-ins-months', 'hk', SIX_MONTHS, [
    pair('P/S 3-year average', '<', '6.4', 'lowest', 2),
    pair('P/S 5-year average', '>', '5.2', 'highest', 2),
    pair('P/B 3-year average', '<=', '10.6', 'lowest', 2),
    pair('P/B 5-year average', '>=', '8.6', 'highest', 2),
    pair('P/E vs 3-year average', '<', '1.37', 'lowest', 2),
    pair('P/E vs 5-year average', '>', '1.64', 'highest', 2),
    pair('P/S vs 3-year average', '<=', '1.35', 'lowest', 2),
    pair('P/S vs 5-year average', '>=', '1.65', 'highest', 2),
    pair('P/B vs 3-year average', '<', '1.35', 'lowest', 2)])
case('jp-built-ins-months', 'jp', SIX_MONTHS, [
    pair('P/B vs 5-year average', '>', '1.22', 'highest', 2),
    pair('Free cash flow', '>=', '188', 'highest', 2),
    pair('FCF yield', '<', '8.9', 'lowest', 2),
    pair('Price/FCF', '<=', '11', 'lowest', 2),
    pair('Dividend yield', '>', '2.5', 'highest', 2),
    pair('Net margin', '>=', '9.4', 'highest', 2),
    pair('Operating yield spread', '<', '9.3', 'lowest', 2),
    pair('PEG', '>', '2.45', 'highest', 2),
    pair('ROE', '<=', '14.4', 'lowest', 2)])
case('us-built-ins-weeks', 'us', WEEKS, [
    pair('Current ratio', '>=', '1.6666666666666667', 'highest', 3),
    pair('Interest coverage', '>', '17', 'highest', 3),
    pair('Debt/equity', '<=', '0.5', 'lowest', 3),
    pair('One year return', '>', '23', 'highest', 3),
    pair('Three year return', '<', '100', 'lowest', 3),
    pair('Turnover rate 1-week average', '>=', '0.21', 'highest', 3),
    pair('Market cap', '<', '8000', 'lowest', 3),
    pair('Enterprise value', '>', '9000', 'highest', 3),
    sleeve('Listed', filter_('Exchange', 'is', 'NASDAQ'), rank('EBITDA yield', 'highest', 1, 3))])

# Fields, the text operators and ranks on the dollar fields.
case('hk-fields-dates', 'hk', HK_DATES, [
    sleeve('Land', filter_('Sector', 'is', 'Real Estate'), rank('Enterprise value in dollars', 'highest', 1, 2)),
    sleeve('Large', filter_('Exchange', 'is not', 'NASDAQ'), filter_('Market cap in dollars', '>=', '13000000000'),
           rank('Market cap in dollars', 'lowest', 1, 2)),
    sleeve('Yield', filter_('Sector', 'is not', 'Financial Services'),
           filter_('Enterprise value in dollars', '<', '13600000000'), rank('EBITDA yield', 'highest', 1, 2))])

# Sleeves whose picks overlap, and rank ranges that start at 2.
case('jp-overlap-random', 'jp', JP_RANDOM, [
    sleeve('Core', rank('EBITDA yield', 'highest', 1, 3)),
    sleeve('Satellite', rank('EBITDA yield', 'highest', 2, 4)),
    sleeve('Quality', filter_('ROE', '>', '10'), rank('Net margin', 'highest', 2, 3))])

# Formulas: every formula is a named variable.
case('us-time-forms', 'us', SIX_MONTHS, [
    sleeve('Growth', filter_('Revenue growth 3y', '>', '10'), rank('Price change 1y', 'highest', 1, 3)),
    sleeve('Steady', filter_('Margin mean 1y', '>', '19'), rank('Revenue mean 3y', 'lowest', 1, 3))], {
    'Revenue mean 3y': dict(formula='average(Revenue, 3 years)'),
    'Revenue low 3y': dict(formula='min(Revenue, 3 years)'),
    'Revenue high 5y': dict(formula='max(Revenue, 5 years)'),
    'Revenue growth 3y': dict(formula='growth(Revenue, 3 years)'),
    'Income cagr 2y': dict(formula='cagr(Net income, 2 years)'),
    'Margin mean 1y': dict(formula='average(Operating margin, 1 year)'),
    'Revenue year ago': dict(formula='ago(Revenue, 12 months)'),
    'Price 6m ago': dict(formula='ago(Share price, 6 months)'),
    'Volume 1m ago': dict(formula='ago(Trading volume, 1 month)'),
    'Price June 2021': dict(formula='at(Share price, 2021-06-30)'),
    'Revenue 2020': dict(formula='at(Revenue, 2020-12-31)'),
    'Price change 1y': dict(formula='Share price / ago(Share price, 12 months) - 1'),
    'Debt to equity': dict(formula='Total debt / positive(Shareholders equity)')})
case('hk-arithmetic', 'hk', HK_DATES, [
    sleeve('Cash', filter_('Net cash', '>', '-1100'), rank('Nested', 'highest', 1, 3)),
    sleeve('Sales', filter_('Sales per share', '>', '0.6'), rank('Precedence', 'lowest', 2, 4))], {
    'Cash plus debt': dict(formula='Cash and equivalents + Total debt'),
    'Net cash': dict(formula='Cash and equivalents - Total debt'),
    'Margin doubled': dict(formula='Operating margin * 2'),
    'Sales per share': dict(formula='Revenue / Basic shares'),
    'Cash negated': dict(formula='-Cash and equivalents'),
    'Gap negated': dict(formula='-(Revenue - Operating income)'),
    'Double sign': dict(formula='Net income - -Operating income'),
    'Revenue plus': dict(formula='Revenue + 5000000 USD'),
    'Earnings plus': dict(formula='Basic EPS + 0.25 USD per share'),
    'Shares plus': dict(formula='Basic shares + 1000 shares'),
    'Half revenue': dict(formula='.5 * Revenue'),
    'Nested': dict(formula='(((Revenue - Operating income) * (Cash and equivalents - Total debt)) / (Revenue + Total debt)) + Net income'),
    'Precedence': dict(formula='Revenue / 4 + Net income * 3 - Cash and equivalents / 2')})
case('jp-references', 'jp', JP_DATES, [
    sleeve('Quality', filter_('Quality adjusted', '>', '300'), rank('Quality', 'highest', 1, 3)),
    sleeve('Size', filter_('Net income', '>=', '200'), rank('Revenue', 'highest', 1, 2))], {
    'Cash cover': dict(formula='Cash and equivalents / positive(Current liabilities)'),
    'Cash cover doubled': dict(formula='Cash cover * 2'),
    'Margin mean 3y': dict(formula='average(Operating margin, 3 years)'),
    'Quality': dict(formula='Cash cover doubled + Margin mean 3y'),
    'Quality adjusted': dict(formula='(Quality - Cash cover / 2) * 3'),
    'Revenue copy': dict(formula='Revenue')})


def measure_cases():
    """The named measures, half in each of two cases: one variable per measure, named as the measure; a few steps read them."""
    from backtest.application import vocabulary
    from backtest.variables import measures, parameters
    names = vocabulary.names()
    named = [(names[measure['root']['variable_id']], measure) for measure in measures.catalog(parameters.V4)]
    half = len(named) // 2 + 1  # A case's closure holds at most 32 definitions.

    def variables(items):
        # A ratio shows as its measure does; an amount shows in the default unit.
        return {name + ' value': dict(formula=name, **({'display': measure['display']} if measure['unit'] == 'scalar' else {}))
                for name, measure in items}

    first, second = variables(named[:half]), variables(named[half:])
    return [
        dict(name='us-measures-first', market='us', run=dict(market='us', **SIX_MONTHS), variables=first, sleeves=[
            sleeve('Cheap', filter_('Price/sales value', '<', '3'), rank('Net margin value', 'highest', 1, 3)),
            sleeve('Cash', filter_('Working capital value', '>', '450'), rank('Net debt value', 'lowest', 1, 3))]),
        dict(name='hk-measures-second', market='hk', run=dict(market='hk', **HK_DATES), variables=second, sleeves=[
            sleeve('Returns', filter_('P/E value', '<', '40'), rank('ROE value', 'highest', 1, 3)),
            sleeve('Safe', filter_('Debt/equity value', '<=', '1.4'), rank('Interest coverage value', 'highest', 1, 3))])]


def text(strategy):
    """strategy.json: one line per variable, sleeve header and step."""
    def line(value):
        return json.dumps(value, ensure_ascii=False)

    parts = []
    if strategy.get('variables'):
        parts.append(' "variables": {\n' + ',\n'.join(f'  {line(name)}: {line(variable)}'
                                                       for name, variable in strategy['variables'].items()) + '\n }')
    sleeves = []
    for item in strategy['sleeves']:
        name = f'"name": {line(item["name"])}, ' if len(strategy['sleeves']) > 1 else ''
        sleeves.append(f'  {{{name}"steps": [\n' + ',\n'.join('   ' + line(step) for step in item['steps']) + '\n  ]}')
    parts.append(' "sleeves": [\n' + ',\n'.join(sleeves) + '\n ]')
    return '{\n' + ',\n'.join(parts) + '\n}\n'


def strategy_of(item):
    result = dict(sleeves=item['sleeves'])
    if item['variables']:
        result['variables'] = item['variables']
    return result


def nodes(node):
    yield node
    for side in ('left', 'right', 'arg'):
        if side in node:
            yield from nodes(node[side])


def height(node):
    """The number of arithmetic operations from a node down its longest path."""
    if node['op'] not in ARITHMETIC:
        return 0
    return 1 + max(height(node['left']), height(node['right']))


def used(item, vocabulary, measure_terms):
    """The items of the language that a case uses, as the adapter reads it."""
    run, variables, found = item['run'], item['variables'] or {}, set()
    found.add('market ' + item['market'])
    found.add('schedule ' + ('explicit dates' if 'dates' in run else 'random dates' if 'trials' in run else
                             'fixed weeks' if run['interval'].endswith('w') else 'fixed months'))
    taken = {l3.key(name) for name in variables}
    texts = [variable['formula'] for variable in variables.values()]
    firsts = []
    for sleeve_ in item['sleeves']:
        first = sleeve_['steps'][0]
        if 'rank' in first:
            firsts.append((first['rank'], first['order'], first['from'], first['to']))
        for step in sleeve_['steps']:
            source = l3.key(step.get('rank', step.get('filter')))
            if 'from' in step and step['from'] >= 2:
                found.add('rank from 2')
            entry = next((entry for entry in vocabulary if l3.key(entry['name']) == source and entry['term']), None)
            if entry:
                found.add('step of a linked input' if entry['builtins'] else 'step of an unlinked input')
            elif source not in taken | set(l3.FIELDS):
                texts.append(step.get('rank', step.get('filter')))
    found |= {'sleeve overlap' for index, one in enumerate(firsts) for other in firsts[index + 1:]
              if one[:2] == other[:2] and one[2] <= other[3] and other[2] <= one[3]}
    for formula in texts:
        found |= {'function ' + word.casefold() for word in re.findall(r'(\w+)\(', formula)}
    requests = [l3.request(strategy_of(item), item['market'])]
    if variables:
        # A Rank of every variable puts each definition into a request.
        every = dict(variables=variables, sleeves=[dict(steps=[rank(name, 'highest', 1, 1) for name in variables])])
        requests.append(l3.request(every, item['market']))
    terms = set()
    for request in requests:
        intent = request['intent']
        for step in sum((sleeve_['steps'] for sleeve_ in intent['sleeves']), []) if intent['version'] == 3 else intent['steps']:
            source = step['source']
            if source['kind'] in ('field', 'builtin'):
                found.add(f'{step["kind"]} {source["kind"]} ' + source.get('field', source.get('id')))
            if step['kind'] == 'filter':
                found.add('operator ' + step['op'])
        # Only the file's own formulas count: a measure's definition is the oracle's, not the case's.
        expressions = {(entry['variable_id'], entry['revision']): entry['definition']['expression']
                       for entry in request['submitted'] if entry['variable_id'].startswith('local:')}
        depths = {}

        def chain(identity):
            if identity not in depths:
                refs = [(node['variable_id'], node['revision']) for node in nodes(expressions[identity])
                        if node['op'] == 'ref' and (node['variable_id'], node['revision']) in expressions]
                depths[identity] = 1 + max(map(chain, refs), default=0)
            return depths[identity]

        for identity, expression in expressions.items():
            if chain(identity) > 1:
                found.add('variable reference')
            if chain(identity) > 2:
                found.add('variable chain')
            if height(expression) > 3:
                found.add('nested expression')
            for node in nodes(expression):
                found.add('operation ' + node['op'])
                if node['op'] == 'constant':
                    found.add('constant ' + node['unit'])
                if node['op'] == 'ref':
                    terms.add('reference ' + node['variable_id'])
                if node['op'] in ('parameter', 'annual'):
                    terms.add('parameter ' + node.get('id', node.get('parameter')))
    return found | {measure_terms[term] for term in terms if term in measure_terms}


def required(vocabulary, measure_terms):
    """The items that the oracle's modules define."""
    from backtest.application import formula_text, strategy_requests
    from backtest.variables import definitions, parameters
    folded = {identity for entry in vocabulary for identity in entry['builtins'][1:]}
    items = {f'{kind} builtin {item["id"]}' for item in strategy_requests.builtin_catalog() if item['id'] not in folded
             for kind in ('rank', 'filter')}
    items |= {'filter field ' + field for field in l3.FIELDS.values()}
    items |= {'rank field ' + field for field in l3.FIELDS.values()
              if strategy_requests.field_descriptor(field)['unit'] != 'text'}
    items |= {'operator ' + op for op in l3.OPS.values()}
    items |= {'operation ' + op for op in definitions.OPERATIONS}
    items |= {'function ' + function['name'] for function in formula_text.FUNCTIONS}
    items |= {'constant ' + unit for unit in parameters.units(parameters.V4)}
    items |= {'schedule ' + schedule for schedule in SCHEDULES} | {'market ' + market for market in MARKETS}
    items |= {'variable reference', 'variable chain', 'nested expression', 'step of a linked input',
              'step of an unlinked input', 'sleeve overlap', 'rank from 2'}
    return items | set(measure_terms.values())


def missing(items):
    """The required items that no case uses."""
    from backtest.application import vocabulary
    from backtest.variables import measures, parameters
    entries = vocabulary.entries()
    # A measure of one parameter is that parameter in a formula; any other is a reference.
    measure_terms = {}
    for measure in measures.catalog(parameters.V4):
        expression = measures.exact(**measure['root'])['definition']['expression']
        term = 'parameter ' + expression['id'] if expression['op'] == 'parameter' else 'reference ' + measure['root']['variable_id']
        measure_terms[term] = 'measure ' + measure['id']
    return required(entries, measure_terms) - set().union(*(used(item, entries, measure_terms) for item in items))


def main():
    oracle.load(ROOT)
    items = CASES + measure_cases()
    gaps = missing(items)
    if gaps:
        raise SystemExit('The cases do not cover:\n' + '\n'.join(sorted(gaps)))
    for item in items:
        folder = CASES_DIR / ('formulas' if item['variables'] else 'builtins') / item['name']
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'strategy.json').write_text(text(strategy_of(item)), encoding='utf-8', newline='\n')
        (folder / 'run.json').write_text(json.dumps(item['run']) + '\n', encoding='utf-8', newline='\n')
    print(f'Wrote {len(items)} cases.')


if __name__ == '__main__':
    main()
