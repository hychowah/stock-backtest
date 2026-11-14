"""Write the formula vectors: what the Python product's formula editor makes of formula text.

Run from the repository root with no options:

    python3 proof/formula_vectors.py

It writes fixtures/formulas/vectors.json, the same bytes each time, which
crates/engine/tests/formulas.rs reads. Each case is a text, the library of
earlier variables it is read with (all of a library's variables, or with
"before" those above one variable), an optional display, and the editor's
outcome in catalog /4 (variable_authoring.validate): the canonical text
(formula_text.to_text), the stored tree with its unit and display, or the
error code with the characters [start, end) of a reader error.
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.application import formula_text, variable_authoring, vocabulary  # noqa: E402
from backtest.variables import definitions, library  # noqa: E402

# The yearly functions, from the reader's own table.
FUNCTIONS = tuple(formula_text._STATS)


class Store:
    """The editor's library of saved variables, held in memory.

    A capture receives only the closure of the requested roots, as the
    durable library gives it.
    """

    def __init__(self):
        self.entries, self.authored, self.labels = [], {}, {}

    def list(self):
        return self.entries

    def capture(self, roots, *, submitted, labels, checkpoint):
        entries = {(item['variable_id'], item['revision']): item for item in submitted}
        names = {(item['variable_id'], item['revision']): item for item in labels}
        seen = set()

        def visit(identity):
            if identity in seen:
                return
            seen.add(identity)
            if identity not in entries:
                entries[identity], names[identity] = self.authored[identity], self.labels[identity]
            for item in definitions.references(entries[identity]['definition']):
                visit((item['variable_id'], item['revision']))

        for root in roots:
            visit((root['variable_id'], root['revision']))
        return library.capture_submitted(roots, submitted=list(entries.values()),
                                         labels=[label for identity, label in names.items() if identity in entries],
                                         checkpoint=checkpoint)

    def check(self, text, display=None, name=''):
        identity = 'local:' + hashlib.sha256((name or text).encode()).hexdigest()[:16]
        return variable_authoring.validate(dict(formula=dict(text=text, display=display), name=name,
                                                variable_id=identity), self, checkpoint=lambda: None)

    def define(self, name, text, display):
        checked = self.check(text, display, name)
        self.entries.append(dict(checked['root'], name=name))
        for item in checked['authored']:
            self.authored[item['variable_id'], item['revision']] = item
        for item in checked['capture']['presentation']:
            self.labels[item['variable_id'], item['revision']] = {key: item[key] for key in ('variable_id', 'revision', 'name')}


def outcome(store, text, display=None):
    """The editor's outcome for text: {"result": ...} or {"error": ...}."""
    try:
        checked = store.check(text, display)
    except formula_text.TextError as error:
        first = error.errors[0]
        return dict(error={key: first[key] for key in ('code', 'start', 'end') if key in first})
    program = checked['capture']['program']['bundle']['definitions']
    expanded = {(item['variable_id'], item['revision']): item['definition'] for item in program}
    names = {(item['variable_id'], item['revision']): item['name'] for item in checked['capture']['presentation']}

    def dump(node):
        if node['op'] == 'ref':
            identity = node['variable_id'], node['revision']
            if node['variable_id'].startswith('measure:'):
                return dict(op='ref', measure=node['variable_id'].split(':', 1)[1], tree=dump(expanded[identity]['expression']))
            return dict(op='ref', variable=names[identity])
        return {key: dump(value) if isinstance(value, dict) else value for key, value in node.items()}

    root = checked['root']['variable_id'], checked['root']['revision']
    authored = next(item['definition'] for item in checked['authored'] if (item['variable_id'], item['revision']) == root)
    canonical = formula_text.to_text(authored, checked['capture']['presentation'])
    output = expanded[root]['output']
    return dict(result=dict(text=canonical, tree=dump(expanded[root]['expression']), unit=output['unit'],
                            display=output['display']))


def chain(prefix, count, first, step):
    """count variables PREFIX1..PREFIXn: the first is `first`, each next is `step` of the one before."""
    return [[prefix + '1', first, None]] + [[f'{prefix}{n}', step.format(f'{prefix}{n - 1}'), None] for n in range(2, count + 1)]


LIBRARIES = {
    'file': [
        ['Debt to EV', 'Total debt / positive(Enterprise value)', 'multiple'],
        ['Doubled', 'Debt to EV * 2', None],
        ['Margin', 'Gross margin', 'percent'],
        ['Cash and equivalents ratio', 'Cash and equivalents / positive(Total assets)', 'number'],
        ['3m change', 'Share price / ago(Share price, 3 months) - 1', None],
        ['a]b', 'Revenue', None],
        ['Sales per share', 'Revenue / Diluted shares', None],
    ],
    # Dependency depth: each variable reads the one before it.
    'chain': chain('Level', 8, 'Revenue', '{} * 2'),
    # Resolved definitions: a formula of 31 of them makes 32 with itself.
    'many': [[f'Part {n}', f'Revenue + {n} USD', None] for n in range(1, 34)],
    # Resolved nodes: each variable has 99 nodes, 14 deep.
    'big': [[f'Big {n}', ' + '.join(['(' + ' + '.join(['Revenue'] * 10) + ')'] * 5), None] for n in range(1, 4)],
    # Expanded depth: Deep 1 is 30 deep, each next one more.
    'deep': [['Deep 1', '-' * 29 + 'Revenue', None], ['Deep 2', '-(Deep 1)', None], ['Deep 3', '-(Deep 2)', None]],
}


def parts(count):
    """The sum of Part 1 to Part count, in groups of four so that it stays shallow."""
    names = [f'Part {n}' for n in range(1, count + 1)]
    return ' + '.join('(' + ' + '.join(names[n:n + 4]) + ')' for n in range(0, count, 4))


def cases():
    """[(library or None, text, display or None)]."""
    entries = vocabulary.entries()
    result = []
    add = lambda text, library=None, display=None: result.append((library, text, display))  # noqa: E731
    # Each name of the vocabulary alone, then once inside a yearly function, a lookback and a sum.
    for item in entries:
        add(formula_text.spelling(item['name']))
    for n, item in enumerate(entries):
        spelled = formula_text.spelling(item['name'])
        add(f'{FUNCTIONS[n % 5]}({spelled}, {n % 4 + 1} years)')
        if n % 3 == 0:
            add(f'ago({spelled}, {n % 12 + 1} months) - {spelled}')
    # Spelling: case, spaces, brackets and the longest whole name.
    for text in ('  revenue  ', 'REVENUE', 'net    income', 'Net\tincome / 2', '[net income]', '[ Net income ]',
                 '[P/E]', 'P/E * 2', 'p/e*2', 'P/E5', 'P/E 4-year average', '[3-year average EBITDA yield]',
                 '3-year average EBITDA yield', 'Revenu', 'Revenue foo', '[Revenu]', 'Revenue(', 'price/sales',
                 'EV/EBITDA + EV/3-year average EBITDA', 'Treasury 10 year yield - Treasury 3 month yield',
                 'Shareholders equity', 'shareholders  EQUITY*2', 'R&D expense / Revenue', 'SG&A expense + R&D expense',
                 'Net PP&E', 'Operating cash flow plus CapEx', 'Operating cash flow + CapEx', 'Operating cash flow plus',
                 'Market cap / Enterprise value', 'Dividend yield * 2', '[]', '[Revenue',
                 '[Revenue]]', 'Revenue]', 'Revenue * 2', 'Revenue × 2', '“Revenue”'):
        add(text)
    # Numbers and units.
    for text in ('5', '-5', '+5', '- 5', '-(5)', '5.', '.5', '0.50', '007.50', '-0', '0', '1e3', '1E-3', '1.5e+2',
                 '2.5e', '1e2048', '1e309', '1e-400', '1e10000', '1' * 64, '1' * 65, '0.' + '0' * 61 + '1',
                 '1.000000000000000000000000000000000000000001e300', '5e-324',
                 '5 USD', '5USD', '5 usd', '5 Usd Per Share', '5 USD  per   share', '5 shares', '5 share', '5 USDx',
                 '1000 shares + Basic shares', 'Revenue + 5000000 USD', 'Revenue + 5', 'Basic EPS + 0.25 USD per share',
                 'Revenue / Basic shares', 'Basic shares / Revenue', 'Revenue * Revenue', 'Revenue * Revenue / Revenue',
                 'Revenue / Revenue', '2 USD / 4 USD', '1 USD per share * 3 shares', 'Revenue - Total debt * 2',
                 'Share price * Diluted shares', 'Share price * Diluted shares - Market cap', 'P/E + 1',
                 'ROE * 2', 'growth(Revenue, 3 years) + 1', 'Revenue + growth(Revenue, 3 years)'):
        add(text)
    # Operators, precedence, signs and grouping.
    for text in ('1 + 2 * 3', '(1 + 2) * 3', '1 - (2 - 3)', '(1 - 2) - 3', '1 / (2 / 3)', '1 / 2 / 3', '1 - 2 + 3',
                 '1 * (2 * 3)', '(1 * 2) * 3', '2 * -3', '2 * - 3', '2*-Revenue', '-Revenue', '--Revenue', '-(-Revenue)',
                 '-(Revenue)', '-(Revenue + 1 USD)', '-(5 * 2)', '3 - -5', '3--5', '3 -5', '3 +-5', '3 + +5', '3 + + 5',
                 '-(-5)', '- -5', '((Revenue))', '-(1 * 2) * 3', '(-Revenue) * 2', '1 - -(2)',
                 'Revenue / positive(Total assets)', 'Revenue/positive(Total assets) * 2', 'Revenue / (positive(Total assets))',
                 'Revenue / -positive(Total assets)', 'positive(Total assets)', 'Revenue * positive(Total assets)',
                 'Revenue / POSITIVE(Total assets)', 'Revenue / positive(Total assets', 'Revenue / positive (Total assets)',
                 'Revenue / positive(Total assets - Total liabilities) / 2', '1 / positive(2) / positive(3)',
                 'Revenue - (Cost of revenue + SG&A expense) - R&D expense',
                 '((Revenue - Operating income) * (Cash and equivalents - Total debt)) / (Revenue + Total debt)',
                 'Revenue / 4 + Net income * 3 - Cash and equivalents / 2'):
        add(text)
    # Time forms.
    for text in ('average(Revenue, 3 years)', 'Average(Revenue, 3 years)', 'AVERAGE(Revenue,3years)', 'min(Revenue, 1 year)',
                 'max(Revenue, 10 years)', 'max(Revenue, 11 years)', 'average(Revenue, 0 years)', 'growth(Revenue, 9 years)',
                 'growth(Revenue, 10 years)', 'growth(Revenue, 0 years)', 'cagr(Revenue, 1 year)', 'cagr(Revenue, 1 years)',
                 'average(Revenue, 03 years)', 'average(Revenue, 3 yearss)', 'average(Revenue, 3 months)',
                 'average(Revenue, 99999999999999999999 years)', 'average(Revenue)', 'average(Revenue, )',
                 'average(Revenue, three years)', 'average(Revenue, 3 years', 'average(Revenue, 3 years, 2)',
                 'average(Revenue * 2, 3 years)', 'average(Revenue * 2 , 3 years)', 'average((Revenue), 3 years)',
                 'average(Gross profit, 3 years)', 'average(P/E, 3 years)', 'average(Share price, 3 years)',
                 'average(Operating margin, 3 years)', 'average(3, 3 years)',
                 'ago(Revenue, 12 months)', 'ago(Revenue, 1 month)', 'ago(Revenue, 1 months)', 'ago(Revenue, 120 months)',
                 'ago(Revenue, 121 months)', 'ago(Revenue, 0 months)', 'ago(Revenue, 3 years)', 'ago(Revenue, 12 MONTHS)',
                 'ago(Revenue,12months)', 'ago(Revenue + 1 USD, 3 months)', 'ago(ago(Revenue, 3 months), 3 months)',
                 'ago(average(Revenue, 3 years), 12 months)', 'ago(-Revenue, 2 months)', 'ago(Gross profit, 6 months)',
                 'at(Revenue, 2024-12-31)', 'at(Revenue, 2024-02-29)', 'at(Revenue, 2023-02-29)', 'at(Revenue, 2024-13-01)',
                 'at(Revenue, 0000-01-01)', 'at(Revenue, 0001-01-01)', 'at(Revenue, 9999-12-31)', 'at(Revenue, 2024-1-1)',
                 'at(Revenue, 2024-12-31x)', 'at(Revenue, 2024-12-31-)', 'at(Revenue, 31.12.2024)', 'at(Revenue)',
                 'at(at(Revenue, 2020-12-31), 2024-12-31)', 'at(ago(Share price, 6 months), 2021-06-30)',
                 'at(Share price, 2021-06-30) / ago(Share price, 12 months) - 1', 'sum(Revenue, 3 years)',
                 'avg(Revenue, 3 years)', 'average (Revenue, 3 years)', 'average(Revenue, 3 years) + at(Revenue, 2020-12-31)'):
        add(text)
    # Missing values and stray characters.
    for text in ('', '   ', '(', ')', '()', 'Revenue)', '(Revenue', 'Revenue Revenue', 'Revenue +', '* Revenue', '+ Revenue',
                 '/ 2', 'Revenue , 2', '#', 'Revenue # 2', 'Revenue +* 2', 'Revenue * (', 'Revenue * ()', '(1 + 2',
                 '1 + 2)', '1 2', ',', '-', '--', '- ', 'Revenue -'):
        add(text)
    # Limits: 256 nodes and 32 levels.
    add(' + '.join(['1'] * 128))
    add(' + '.join(['1'] * 129))
    add('-' * 31 + 'Revenue')
    add('-' * 32 + 'Revenue')
    add('(' * 60 + 'Revenue' + ')' * 60)
    add('ago(' * 31 + 'Revenue' + ', 1 month)' * 31)
    add('ago(' * 32 + 'Revenue' + ', 1 month)' * 32)
    # The first fault in the formula's order: a later count, date or literal after an earlier one.
    add('ago(Revenue, 0 months) + average(Revenue, 0 years)')
    add('at(Revenue, 2023-02-29) * 1e400')
    add('1e400 + ago(Revenue, 0 months)')
    add('ago(average(P/E, 3 years), 200 months)')
    add('ago(Revenue, 0 months) + 1')
    add(' + '.join(['1'] * 129) + ' + Revenue')
    add('Revenue + 1 + ago(Revenue, 200 months)')
    add('Revenue * Revenue + 1')
    add('(Revenue + 1) * (Basic shares + 1 USD)')
    # Library variables.
    for text in ('Debt to EV', 'debt  to ev + Doubled', '[Doubled] / 2', 'Doubled(', 'Margin * 100', 'Debt to EV + Margin',
                 'Cash and equivalents ratio * 2', 'Cash and equivalents * 2', 'Cash and equivalents rat',
                 '[3m change] + 1', '3m change', 'ago(3m change, 1 month)', '[a]]b] * 2', 'a]b', 'Sales per share * Diluted shares',
                 'average(Debt to EV, 3 years)', 'Unknown variable', 'Debt to EV + Revenue', 'Doubled + Doubled * Doubled'):
        add(text, 'file')
    add('Level8', 'chain')
    add('Level7 + 1 USD', 'chain')
    add('Level8 + 1 USD', 'chain')
    add('Level8 + 1', 'chain')
    add('Level1 + Level8', 'chain')
    add(parts(31), 'many')
    add(parts(32), 'many')
    add(parts(33), 'many')
    add(parts(32) + ' + 1', 'many')
    add(parts(33) + ' + 1', 'many')
    add('Big 1 + Big 2', 'big')
    add('Big 1 + Big 2 + 1', 'big')
    add('Big 1 + Big 2 + Big 3', 'big')
    add('Big 1 + Big 2 + Big 3 + 1', 'big')
    add('Big 1 + Big 2 + (' + ' + '.join(['1'] * 30) + ')', 'big')
    add('Big 1 + Big 2 + ' + ' + '.join(['Revenue'] * 30), 'big')
    add('Deep 2', 'deep')
    add('-(Deep 2)', 'deep')
    add('Deep 3', 'deep')
    add('Deep 2 + 1', 'deep')
    # Displays that suit the unit.
    for text, display in (('Gross margin', 'multiple'), ('Revenue', 'usd'), ('Revenue / Revenue', 'number'),
                          ('Price/sales', 'multiple'), ('Operating margin', 'percentage_points'), ('Share price', 'usd_per_share'),
                          ('Trading volume', 'shares'), ('Revenue', 'usd_million')):
        add(text, None, display)
    return result


def main():
    stores = {}
    for name, variables in LIBRARIES.items():
        store = stores[name] = Store()
        for variable, text, display in variables:
            try:
                store.define(variable, text, display)
            except formula_text.TextError:
                # A refused definition is a vector of its own; later variables do not see it.
                pass
    lines = []
    for library_name, text, display in cases():
        store = stores[library_name] if library_name else Store()
        found = outcome(store, text, display)
        if 'result' in found:
            again = outcome(store, found['result']['text'], found['result']['display'])
            assert again == found, (text, found, again)
        case = dict(text=text)
        if library_name:
            case['library'] = library_name
        if display:
            case['display'] = display
        lines.append(json.dumps(dict(case, **found), ensure_ascii=False))
    # Each library variable is a case too, read against the variables before it.
    for name, variables in LIBRARIES.items():
        store = Store()
        for variable, text, display in variables:
            found = outcome(store, text, display)
            lines.append(json.dumps(dict(text=text, library=name, before=variable, **({'display': display} if display else {}),
                                         **found), ensure_ascii=False))
            if 'result' in found:
                store.define(variable, text, display)
    folder = ROOT / 'fixtures' / 'formulas'
    folder.mkdir(parents=True, exist_ok=True)
    libraries = json.dumps(LIBRARIES, ensure_ascii=False)
    source = 'backtest.application.variable_authoring.validate in catalog /4; formula_text.to_text'
    text = (f'{{"source": {json.dumps(source)}, "libraries": {libraries},\n"cases": [\n' + ',\n'.join(lines) + '\n]}\n')
    (folder / 'vectors.json').write_text(text, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()
