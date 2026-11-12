"""Typed formula text: printing, reading, names and positioned reader errors."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tempfile
import unittest

from backtest.application import formula_text as f, strategy_requests, variable_authoring, vocabulary
from backtest.variables import definitions as d, library, measures, parameters

V4 = parameters.V4
SAVED = [dict(name='debt/EV', variable_id='var:' + '1' * 32, revision='sha256:' + '1' * 64),
         dict(name='Debt/EV', variable_id='var:' + '2' * 32, revision='sha256:' + '2' * 64)]


def current(expression, unit='scalar', display='percent'):
    return dict(format='variable-definition', version=3, parameter_catalog=V4,
                temporal_policy=d.MARKET_TEMPORAL_POLICY, expression=expression, output=dict(unit=unit, display=display))


def parameter(identity):
    return dict(op='parameter', id=identity)


def constant(value, unit='scalar'):
    return dict(op='constant', value=value, unit=unit)


def binary(op, left, right):
    return dict(op=op, left=left, right=right)


def read(text, saved=()):
    return f.from_text(text, list(saved))


class FormulaTextTests(unittest.TestCase):
    def test_every_operation_reads_back_from_its_text(self):
        gross_profit = next(item['term'] for item in vocabulary.entries() if item['id'] == 'measure:gross_profit')
        newest = dict(op='ref', variable_id=SAVED[1]['variable_id'], revision=SAVED[1]['revision'])
        revenue, ebit = parameter('annual.revenue'), parameter('annual.ebit')
        cases = {
            'Revenue': revenue, 'Gross profit': gross_profit, 'Debt/EV': newest,
            '0.05': constant('0.05'), '1e6 USD': constant('1e6', 'USD'),
            '-5 USD per share': constant('-5', 'USD/share'), '+5 shares': constant('+5', 'share'),
            '-(5)': dict(op='neg', arg=constant('5')), '-P/E': dict(op='neg', arg=parameter('owner.pe')),
            '-(P/E * 2)': dict(op='neg', arg=binary('mul', parameter('owner.pe'), constant('2'))),
            'Revenue - (EBIT - -5 USD)': binary('sub', revenue, binary('sub', ebit, constant('-5', 'USD'))),
            'Revenue - EBIT - -(5 USD)': binary('sub', binary('sub', revenue, ebit), dict(op='neg', arg=constant('5', 'USD'))),
            '(Revenue + EBIT) * 2': binary('mul', binary('add', revenue, ebit), constant('2')),
            'Revenue / (EBIT * 2)': binary('div', revenue, binary('mul', ebit, constant('2'))),
            'Total debt / positive(Shareholders equity)':
                binary('positive_div', parameter('annual.total_debt'), parameter('annual.equity')),
            'average(Revenue, 3 years)': dict(op='annual', stat='mean', count=3, parameter='annual.revenue'),
            'growth(Revenue, 3 years)': dict(op='annual', stat='growth', count=4, parameter='annual.revenue'),
            'cagr(Revenue, 1 year)': dict(op='annual', stat='cagr', count=2, parameter='annual.revenue'),
            'ago(P/E + 1, 12 months)': dict(op='lookback', months=12, arg=binary('add', parameter('owner.pe'), constant('1'))),
            'at(Share price, 2024-12-31)': dict(op='at', date='2024-12-31', arg=parameter('market.adjusted_price')),
        }
        self.assertEqual({node['op'] for node in self._nodes(cases.values())}, set(d.OPERATIONS))
        for text, tree in cases.items():
            with self.subTest(text=text):
                self.assertEqual(f.to_text(current(tree), SAVED), text)
                self.assertEqual(read(text, SAVED)[0], tree)
        self.assertEqual(read('  total DEBT /  positive( shareholders   equity )')[1],
                         {'op': '/', 'top': {'name': 'Total debt'}, 'bottom': {'name': 'Shareholders equity'}, 'positive': True})
        self.assertEqual(read('growth(Revenue, 3 years)')[1]['hint'], 'change across 3 years (4 yearly values)')

    def _nodes(self, trees):
        for tree in trees:
            yield tree
            yield from self._nodes(tree[key] for key in ('left', 'right', 'arg') if key in tree)

    def test_every_stored_measure_revision_and_the_saved_debt_ev_shape_print(self):
        for catalog in (parameters.V3, V4):
            for item in measures.catalog(catalog):
                with self.subTest(catalog=catalog, measure=item['id']):
                    self.assertTrue(f.to_text(measures.exact(**item['root'])['definition'], []))
        enterprise_value = next(item['root'] for item in measures.catalog() if item['id'] == 'enterprise_value')
        debt_ev = dict(current(dict(op='div', left=parameter('annual.total_debt'), right=dict(op='ref', **enterprise_value))),
                       parameter_catalog=parameters.V3, temporal_policy=d.TEMPORAL_POLICY)
        self.assertEqual(f.to_text(debt_ev, []), 'Total debt / Enterprise value')
        oldest = dict(format='variable-definition', version=1, parameter_catalog=parameters.V1, temporal_policy=d.TEMPORAL_POLICY,
                      expression=dict(op='annual', stat='max', count=2, parameter='annual.operating_margin'),
                      output=dict(unit='scalar', display='percent'))
        self.assertEqual(f.to_text(oldest, []), 'max(Operating margin, 2 years)')

    def test_unchanged_text_keeps_the_saved_debt_ev_revision(self):
        enterprise_value = next(item['root'] for item in measures.catalog() if item['id'] == 'enterprise_value')
        saved = dict(current(dict(op='div', left=parameter('annual.total_debt'), right=dict(op='ref', **enterprise_value))),
                     parameter_catalog=parameters.V3, temporal_policy=d.TEMPORAL_POLICY)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        store = library.Store(Path(folder.name) / 'variables.sqlite')
        entry = store.create('debt/EV', saved)
        opened = store.authoring_snapshot({key: entry[key] for key in ('variable_id', 'revision')})
        base = dict(root=opened['selected'], capture=opened['capture'])
        self.assertEqual(variable_authoring.detached(base)['text'], 'Total debt / Enterprise value')
        def check(text, display='percent'):
            return variable_authoring.validate(dict(formula=dict(text=text, display=display), base=base, name='debt/EV',
                                                    variable_id=entry['variable_id']), store)
        kept = check('Total debt  /  Enterprise value ')
        self.assertEqual(kept['root'], opened['selected'])
        self.assertEqual(kept['picture'], {'op': '/', 'top': {'name': 'Total debt'}, 'bottom': {'name': 'Enterprise value'}, 'positive': False})
        shown = check('Total debt / Enterprise value', 'multiple')['authored'][-1]['definition']
        self.assertEqual(shown, dict(saved, output=dict(unit='scalar', display='multiple')))
        edited = check('Total debt / positive(Enterprise value)')['authored'][-1]['definition']
        self.assertEqual(edited, current(binary('positive_div', parameter('annual.total_debt'), parameter('market.enterprise_value'))))

    def test_vocabulary_names_every_current_parameter_once_with_unique_names(self):
        entries = vocabulary.entries()
        names = [item['name'].casefold() for item in entries]
        self.assertEqual(len(names), len(set(names)))
        named = [item['term']['id'] for item in entries if item['term'] and item['term']['op'] == 'parameter']
        self.assertEqual(sorted(named), sorted(item['id'] for item in parameters.catalog(V4)))
        builtins = {item['id'] for item in strategy_requests.builtin_catalog()}
        self.assertTrue(all(identity in builtins for item in entries for identity in item['builtins']))
        self.assertEqual(read('P/E * 2')[0], binary('mul', parameter('owner.pe'), constant('2')))
        self.assertEqual(read('debt/EV * 2', SAVED[:1]), read('[debt/EV] * 2', SAVED[:1]))
        self.assertEqual(f.spelling('3]b'), '[3]]b]')
        self.assertEqual(read('[3]]b] * 2', [dict(SAVED[0], name='3]b')])[0]['left']['variable_id'], SAVED[0]['variable_id'])

    def test_reader_errors_are_positioned_with_codes_and_suggestions(self):
        cases = [('Revenue * (EBIT', 'SYNTAX', 10, 11, []),
                 ('Revnue / 2', 'UNKNOWN_NAME', 0, 6, [dict(text='Revenue', label='Revenue')]),
                 ('1 + [P/S 3-year average]', 'STEP_ONLY', 4, 24, []),
                 ('ago(Revenue, 3 years)', 'BAD_ARGUMENT', 11, 20, [])]
        for text, code, start, end, suggestions in cases:
            with self.subTest(text=text):
                with self.assertRaises(f.TextError) as failure:
                    read(text)
                error = failure.exception.errors[0]
                self.assertEqual((error['code'], error['start'], error['end']), (code, start, end))
                self.assertEqual(error['suggestions'], suggestions)
                self.assertTrue(error['message'])


if __name__ == '__main__':
    unittest.main()
