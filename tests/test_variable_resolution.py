"""Exact lookup resolution uses the existing language; all content is fictional."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from copy import deepcopy
import unittest

from backtest.runtime import backtest_control
from backtest.variables import definitions as d
from test_variable_definitions import definition, constant, entry, root, reference, binary


class ResolutionTests(unittest.TestCase):
    def test_lookup_is_exact_ordered_and_detached(self):
        a = entry(identity='saved:a')
        b = entry(definition(reference(a)), 'saved:b')
        seen = []
        def lookup(variable_id, revision):
            seen.append((variable_id, revision))
            return {('saved:a', a['revision']): a['definition'],
                    ('saved:b', b['revision']): b['definition']}.get((variable_id, revision))
        program = d.resolve([root(b), root(a), root(b)], lookup)
        checked = d.require_program(program)
        self.assertEqual(seen, [('saved:b', b['revision']), ('saved:a', a['revision'])])
        self.assertEqual(checked['bundle']['roots'], [root(b), root(a), root(b)])
        self.assertEqual([row['variable_id'] for row in checked['bundle']['definitions']], ['saved:b', 'saved:a'])
        a['definition']['expression']['value'] = '22'
        self.assertEqual(program.to_json(), d.canonical(checked))

    def test_submitted_entries_share_validation_and_no_lookup_for_local_content(self):
        a = entry(identity='draft:a')
        b = entry(definition(reference(a)), 'draft:b')
        program = d.resolve([root(b)], lambda *_: self.fail('local content looked up'), submitted=[b, a])
        self.assertEqual(d.require_program(program)['bundle']['definitions'][0]['variable_id'], 'draft:b')
        invalid = entry(definition({'op': 'constant', 'value': '2', 'unit': 'USD'}), 'draft:unused')
        with self.assertRaises(d.FormulaError) as caught:
            d.resolve([root(a)], lambda *_: None, submitted=[a, invalid])
        self.assertEqual(caught.exception.code, 'UNIT_MISMATCH')

    def test_long_literal_restore_does_not_widen_raw_submission(self):
        a = entry(definition(constant('1e100')))
        program = d.resolve([root(a)], lambda *_: a['definition'])
        self.assertEqual(len(d.require_program(program)['nodes'][0]['value']), 101)
        with self.assertRaises(d.FormulaError) as caught:
            d.resolve([root(a)], lambda *_: program.to_dict()['bundle']['definitions'][0]['definition'])
        self.assertEqual(caught.exception.code, 'INVALID_LITERAL')

    def test_missing_revisions_and_dynamic_roots_fail(self):
        a = entry()
        with self.assertRaises(d.FormulaError) as caught:
            d.resolve([root(a)], lambda *_: None)
        self.assertEqual(caught.exception.code, 'MISSING_REFERENCE')
        for roots in ([], {}, [dict(variable_id='a', revision='latest')], [dict(variable_id='a')]):
            with self.assertRaises(d.FormulaError):
                d.resolve(roots, lambda *_: self.fail('malformed root reached lookup'))

    def test_hash_mismatch_duplicate_conflict_and_cycle_remain_language_errors(self):
        a = entry()
        wrong = definition(constant('2'))
        with self.assertRaises(d.FormulaError) as caught:
            d.resolve([root(a)], lambda *_: wrong)
        self.assertEqual(caught.exception.code, 'REVISION_MISMATCH')
        with self.assertRaises(d.FormulaError) as caught:
            d.resolve([root(a)], lambda *_: None, submitted=[a, dict(a, definition=wrong)])
        self.assertEqual(caught.exception.code, 'REVISION_MISMATCH')
        cyclic = deepcopy(a)
        cyclic['definition']['expression'] = reference(a)
        with self.assertRaises(d.FormulaError) as caught:
            d.resolve([root(a)], lambda *_: cyclic['definition'])
        self.assertEqual(caught.exception.code, 'DEPENDENCY_CYCLE')

    def test_structural_capacity_stops_lookup_before_next_definition(self):
        a = entry(identity='a')
        b = entry(definition(reference(a)), 'b')
        calls = []
        def lookup(*identity):
            calls.append(identity)
            return b['definition']
        with self.assertRaises(d.FormulaError) as caught:
            d.resolve([root(b)], lookup, limits={'definitions': 1})
        self.assertEqual(caught.exception.code, 'DEFINITION_LIMIT')
        self.assertEqual(calls, [('b', b['revision'])])
        with self.assertRaises(d.FormulaError) as caught:
            d.resolve([root(a)] * 10000, lambda *_: self.fail('oversized roots reached lookup'))
        self.assertEqual(caught.exception.code, 'DEFINITION_LIMIT')

    def test_node_byte_and_dependency_bounds_remain_fixed_and_lowerable(self):
        a = entry(definition(binary('add', constant(), constant())), 'a')
        for limits in ({'nodes': 2}, {'bytes': 120}, {'literal': 0}, {'depth': d.CEILINGS['depth'] + 1}):
            with self.assertRaises(d.FormulaError):
                d.resolve([root(a)], lambda *_: a['definition'], limits=limits)
        chain = [entry(identity='v0')]
        for index in range(1, 9):
            chain.append(entry(definition(reference(chain[-1])), 'v' + str(index)))
        values = {(value['variable_id'], value['revision']): value['definition'] for value in chain}
        with self.assertRaises(d.FormulaError) as caught:
            d.resolve([root(chain[-1])], lambda *identity: values.get(identity))
        self.assertEqual(caught.exception.code, 'DEFINITION_LIMIT')

    def test_lookup_faults_and_cancellation_propagate_without_partial_program(self):
        a = entry()
        def fault(*_):
            raise RuntimeError('fixture fault')
        with self.assertRaisesRegex(RuntimeError, 'fixture fault'):
            d.resolve([root(a)], fault)
        calls = []
        def cancel():
            calls.append(1)
            if len(calls) == 3:
                raise backtest_control.Cancelled()
        with self.assertRaises(backtest_control.Cancelled):
            d.resolve([root(a)], lambda *_: a['definition'], checkpoint=cancel)

    def test_equivalent_authored_duplicate_collapses_once(self):
        a = entry(definition(constant('8e-2')))
        equivalent = dict(a, definition=definition(constant('.08')))
        program = d.resolve([root(a)], lambda *_: None, submitted=[a, equivalent])
        self.assertEqual(len(program.to_dict()['bundle']['definitions']), 1)
        self.assertEqual(program.to_dict()['nodes'][0]['value'], '0.08')


if __name__ == '__main__':
    unittest.main()
