"""Synthetic contract tests for immutable definitions; no financial execution."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from copy import deepcopy
import hashlib
import json
import unittest

from backtest.variables import definitions as d


def constant(value='1', unit='scalar'):
    return dict(op='constant', value=value, unit=unit)


def definition(expression=None, unit='scalar', display='number'):
    return dict(format='variable-definition', version=1,
        parameter_catalog='financial-parameters/1', temporal_policy='annual-lag90/1',
        expression=expression or constant(), output=dict(unit=unit, display=display))


def entry(value=None, identity='draft:A'):
    value = value or definition()
    return dict(variable_id=identity, revision=d.revision(value), definition=value)


def root(value):
    return {key: value[key] for key in ('variable_id', 'revision')}


def reference(value):
    return dict(op='ref', **root(value))


def bundle(*values, roots=None):
    values = list(values) or [entry()]
    return dict(format='variable-bundle', version=1, definitions=values,
                roots=[root(values[-1])] if roots is None else roots)


def binary(op, left, right):
    return dict(op=op, left=left, right=right)


class DefinitionTests(unittest.TestCase):
    def assert_error(self, code, function, *args, **kwargs):
        with self.assertRaises(d.FormulaError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(set(caught.exception.to_dict()['errors'][0]), {'code', 'path', 'message'})
        return caught.exception

    def test_equivalent_decimal_spellings_hash_identically(self):
        expected = d.revision(definition(constant('0.08')))
        for value in ('8e-2', '+000.08000', '.08', '080e-3', '0.0800e+0'):
            self.assertEqual(d.revision(definition(constant(value))), expected)
        for value in ('-0', '+0e20', '000.000', '-.0'):
            self.assertEqual(d.revision(definition(constant(value))), d.revision(definition(constant('0'))))

    def test_canonical_bytes_and_identity_are_specified_not_float_spellings(self):
        value = entry(definition(constant('8e-2')))
        result = d.validate(bundle(value)).to_dict()
        captured = result['bundle']['definitions'][0]['definition']
        self.assertEqual(captured['expression']['value'], '0.08')
        encoded = json.dumps(captured, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
        self.assertEqual(value['revision'], 'sha256:' + hashlib.sha256(encoded).hexdigest())
        self.assertEqual(result['bundle_revision'], 'sha256:' + hashlib.sha256(d.canonical(result['bundle']).encode()).hexdigest())
        self.assertEqual(d.require_program(d.validate(bundle(value))), result)

    def test_definition_display_and_tree_order_are_hashed_content(self):
        a = definition(binary('add', constant('1'), constant('2')))
        b = definition(binary('add', constant('2'), constant('1')))
        self.assertNotEqual(d.revision(a), d.revision(b))
        b = deepcopy(a); b['output']['display'] = 'percent'
        self.assertNotEqual(d.revision(a), d.revision(b))

    def test_binary64_literal_edges_and_nonzero_underflow(self):
        for value in ('1.7976931348623157e308', '5e-324', '-5e-324', '2.2250738585072014e-308'):
            program = d.validate(bundle(entry(definition(constant(value)))))
            self.assertEqual(d.require_program(program), program.to_dict())
        for value in ('1.7976931348623159e308', '1e-324', '-1e-324', 'NaN', 'Infinity', ' 1', '1 ', '0x1', '', '1_0', True, 1, None):
            self.assert_error('INVALID_LITERAL', d.revision, definition(constant(value)))

    def test_literal_size_exponent_and_preallocation_bounds(self):
        self.assertEqual(len('0.' + '0' * 61 + '1'), 64)
        d.revision(definition(constant('0.' + '0' * 61 + '1')))
        self.assert_error('INVALID_LITERAL', d.revision, definition(constant('0.' + '0' * 62 + '1')))
        for value in ('1e999999999999999999999999999999', '1e1024', '1e-1024', '0e99999999999999'):
            self.assert_error('INVALID_LITERAL', d.revision, definition(constant(value)))
        value = entry(definition(constant('1e20')))
        d.validate(bundle(value), dict(expanded_literal=21))
        self.assert_error('INVALID_LITERAL', d.validate, bundle(value), dict(expanded_literal=20))

    def test_checked_restore_admits_long_canonical_expansion_only_inside_program(self):
        program = d.validate(bundle(entry(definition(constant('1e100')))))
        self.assertEqual(len(program.to_dict()['bundle']['definitions'][0]['definition']['expression']['value']), 101)
        self.assertEqual(d.require_program(program), program.to_dict())
        self.assert_error('INVALID_LITERAL', d.validate, program.to_dict()['bundle'])
        forged = program.to_dict()
        forged['bundle']['definitions'][0]['definition']['expression']['value'] = '1e100'
        self.assert_error('INVALID_LITERAL', d.require_program, d.FormulaProgram(d.canonical(forged)))

    def test_program_is_immutable_detached_and_requires_checked_restore(self):
        submitted = bundle()
        program = d.validate(submitted)
        submitted['definitions'][0]['definition']['expression']['value'] = '2'
        decoded = program.to_dict(); decoded['nodes'][0]['value'] = '3'
        self.assertEqual(program.to_dict()['nodes'][0]['value'], '1')
        with self.assertRaises(AttributeError):
            program.document = '{}'
        self.assert_error('INVALID_SHAPE', d.require_program, {})
        self.assert_error('INVALID_SHAPE', d.require_program, d.FormulaProgram('invalid'))
        self.assert_error('INVALID_SHAPE', d.require_program, d.FormulaProgram('[]'))
        self.assert_error('DEFINITION_LIMIT', d.require_program, d.FormulaProgram(' ' * (8 * d.CEILINGS['bytes'] + 1)))

    def test_forged_projection_identities_edges_requirements_and_limits_reject(self):
        program = d.validate(bundle()).to_dict()
        for field, value in (('bundle_revision', 'sha256:' + '0' * 64), ('roots', []),
                             ('nodes', []), ('requirements', [dict(parameter='annual.revenue')]),
                             ('definitions', []), ('version', True), ('format', 'other')):
            forged = deepcopy(program); forged[field] = value
            self.assert_error('INVALID_SHAPE', d.require_program, d.FormulaProgram(d.canonical(forged)))
        forged = deepcopy(program); forged['limits']['literal'] = 65
        self.assert_error('INVALID_SHAPE', d.require_program, d.FormulaProgram(d.canonical(forged)))
        forged = deepcopy(program); forged['limits']['nodes'] = 1
        # A lower capability is valid only when every derived byte is rebuilt.
        self.assertEqual(d.require_program(d.FormulaProgram(d.canonical(forged)))['limits']['nodes'], 1)

    def test_exact_shapes_versions_and_integer_types(self):
        for field in ('format', 'version', 'parameter_catalog', 'temporal_policy'):
            value = definition(); value[field] = True
            self.assert_error('UNKNOWN_VERSION', d.revision, value)
        for target in (dict(definition(), extra='x'),
                       dict(definition(), expression=dict(constant(), extra=0)),
                       dict(definition(), output=dict(unit='scalar', display='number', label='x'))):
            self.assert_error('INVALID_SHAPE', d.revision, target)
        for submitted in (dict(bundle(), version=True), dict(bundle(), format='other')):
            self.assert_error('UNKNOWN_VERSION', d.validate, submitted)
        for submitted in ({}, dict(bundle(), roots={}), dict(bundle(), definitions=[]), dict(bundle(), roots=[])):
            self.assert_error('DEFINITION_LIMIT' if submitted.get('definitions') == [] else 'INVALID_SHAPE', d.validate, submitted)
        for op, field in (('lookback', 'months'), ('annual', 'count')):
            node = dict(op=op, months=True, arg=constant()) if op == 'lookback' else dict(op=op, count=True, stat='mean', parameter='annual.revenue')
            self.assert_error('INVALID_SHAPE', d.revision, definition(node))

    def test_invalid_nodes_and_multiple_diagnostics_follow_tree_order(self):
        value = definition(binary('add', dict(op='parameter', id='quarterly.revenue'),
                                  dict(op='parameter', id='ttm.revenue')))
        error = self.assert_error('UNKNOWN_PARAMETER', d.revision, value)
        self.assertEqual([issue['path'] for issue in error.errors], ['/expression/left/id', '/expression/right/id'])
        self.assertNotIn('quarterly.revenue', str(error))
        for op in ('calendar', 'pow', 'if', 'eval', None, [], {}):
            self.assert_error('UNSUPPORTED_OPERATION', d.revision, definition(dict(op=op)))

    def test_only_four_provider_parameters_are_supported(self):
        for parameter, unit in (('annual.revenue', 'USD'), ('annual.operating_income', 'USD'),
                                ('annual.operating_margin', 'scalar'), ('market.enterprise_value', 'USD')):
            display = 'usd' if unit == 'USD' else 'number'
            result = d.validate(bundle(entry(definition(dict(op='parameter', id=parameter), unit, display)))).to_dict()
            self.assertEqual(result['requirements'][0]['parameter'], parameter)
            self.assertEqual(result['requirements'][0]['count'], 1)
        for parameter in ('treasury.us_10y', 'annual.net_income', 'market.adjusted_price', 'Annual.revenue', []):
            self.assert_error('UNKNOWN_PARAMETER', d.revision, definition(dict(op='parameter', id=parameter)))

    def test_annual_statistics_validate_supported_parameter_count_and_stat(self):
        for stat in ('mean', 'min', 'max'):
            for count in (1, 10):
                value = definition(dict(op='annual', stat=stat, count=count, parameter='annual.operating_margin'))
                result = d.validate(bundle(entry(value))).to_dict()
                self.assertEqual(result['nodes'][0]['stat'], stat)
                self.assertEqual(result['requirements'][0]['count'], count)
        for count in (0, 11, 1., True):
            self.assert_error('INVALID_SHAPE', d.revision, definition(dict(op='annual', stat='mean', count=count, parameter='annual.revenue')))
        for parameter, stat in (('market.enterprise_value', 'mean'), ('annual.revenue', 'median')):
            self.assert_error('UNSUPPORTED_OPERATION', d.revision, definition(dict(op='annual', stat=stat, count=1, parameter=parameter)))

    def test_dates_and_lookbacks_are_structural_until_request_binding(self):
        for day in ('2024-02-29', '9999-12-31'):
            d.validate(bundle(entry(definition(dict(op='at', date=day, arg=constant())))))
        for day in ('2023-02-29', '20240101', '2024-1-01', True, None):
            self.assert_error('INVALID_DATE', d.revision, definition(dict(op='at', date=day, arg=constant())))
        for months in (1, 120):
            d.validate(bundle(entry(definition(dict(op='lookback', months=months, arg=constant())))))
        for months in (0, 121, -1, True, 3.):
            self.assert_error('INVALID_SHAPE', d.revision, definition(dict(op='lookback', months=months, arg=constant())))

    def test_unit_inference_and_intermediate_dimension_cancellation(self):
        expression = binary('div', binary('mul', constant('3', 'USD'), constant('2', 'USD/share')), constant('2', 'USD/share'))
        result = d.validate(bundle(entry(definition(expression, 'USD', 'usd')))).to_dict()
        self.assertEqual(result['nodes'][1]['dimensions'], {'USD': 2, 'share': -1})
        self.assertEqual(result['nodes'][0]['dimensions'], {'USD': 1})
        self.assertEqual(result['definitions'][0]['unit'], 'USD')
        self.assert_error('UNIT_MISMATCH', d.validate, bundle(entry(definition(binary('add', constant('1'), constant('1', 'USD'))))))
        self.assert_error('UNIT_MISMATCH', d.validate, bundle(entry(definition(constant('1', 'USD')))))
        self.assert_error('UNSUPPORTED_OUTPUT_UNIT', d.validate, bundle(entry(definition(binary('mul', constant('1', 'USD'), constant('1', 'USD'))))))

    def test_display_compatibility_and_no_implicit_percent_units(self):
        for unit, displays in (('USD', ('usd', 'usd_million')), ('USD/share', ('usd_per_share',)),
                               ('scalar', ('number', 'multiple', 'percent', 'percentage_points'))):
            for display in displays:
                result = d.validate(bundle(entry(definition(constant('12', unit), unit, display)))).to_dict()
                self.assertEqual(result['nodes'][0]['value'], '12')
        self.assert_error('UNIT_MISMATCH', d.revision, definition(constant(), 'scalar', 'usd'))
        self.assert_error('UNIT_MISMATCH', d.revision, definition(constant('1', 'percent')))
        self.assert_error('UNSUPPORTED_OUTPUT_UNIT', d.revision, definition(constant(), 'share'))

    def test_reference_resolution_diamond_and_dependency_reuse(self):
        base = entry(definition(constant('3')), 'saved:base')
        left = entry(definition(binary('add', reference(base), constant('1'))), 'saved:left')
        right = entry(definition(binary('sub', reference(base), constant('1'))), 'saved:right')
        top = entry(definition(binary('mul', reference(left), reference(right))), 'draft:top')
        result = d.validate(bundle(base, left, right, top)).to_dict()
        self.assertEqual(len(result['nodes']), 10)
        targets = [node['target'] for node in result['nodes'] if node['op'] == 'ref']
        self.assertEqual(targets.count(result['definitions'][0]['root']), 2)
        self.assertEqual(result['definitions'][3]['dependencies'], [1, 2])

    def test_reference_identity_and_normalized_duplicate_rules(self):
        base = entry()
        same = deepcopy(base); same['definition']['expression']['value'] = '+01.00'
        result = d.validate(bundle(base, same)).to_dict()
        self.assertEqual(len(result['definitions']), 1)
        bad = deepcopy(base); bad['definition']['expression']['value'] = '2'
        self.assert_error('REVISION_MISMATCH', d.validate, bundle(base, bad))
        bad = deepcopy(base); bad['revision'] = 'sha256:' + '0' * 64
        self.assert_error('REVISION_MISMATCH', d.validate, bundle(bad))
        for revision in ('latest', 'sha256:' + 'A' * 64, 1):
            bad = deepcopy(base); bad['revision'] = revision
            self.assert_error('INVALID_SHAPE', d.validate, bundle(bad))
        for name in ('', 'a' * 129, 'a/b', 'naïve'):
            bad = deepcopy(base); bad['variable_id'] = name
            self.assert_error('INVALID_SHAPE', d.validate, bundle(bad))

    def test_missing_references_and_roots_fail_without_library_lookup(self):
        missing = dict(variable_id='saved:absent', revision='sha256:' + '0' * 64)
        self.assert_error('MISSING_REFERENCE', d.validate, bundle(entry(definition(dict(op='ref', **missing)))))
        self.assert_error('MISSING_REFERENCE', d.validate, bundle(roots=[missing]))

    def test_errors_after_duplicate_definitions_point_to_submitted_entries(self):
        base = entry(definition(), 'a')
        bad_revision = entry(definition(), 'b')
        bad_revision['revision'] = 'sha256:' + '0' * 64
        bad_unit = entry(definition(constant('1', 'USD')), 'b')
        bad_addition = entry(definition(binary('add', constant(), constant('1', 'USD'))), 'b')
        bad_dimensions = entry(definition(binary('mul', constant('1', 'USD'), constant('1', 'USD'))), 'b')
        cyclic_identity = dict(variable_id='b', revision='sha256:' + 'b' * 64)
        cyclic = dict(cyclic_identity, definition=definition(dict(op='ref', **cyclic_identity)))
        dependent = entry(definition(reference(base)), 'b')
        cases = [
            (bad_revision, 'REVISION_MISMATCH', '/revision', {}),
            (bad_unit, 'UNIT_MISMATCH', '/definition/output/unit', {}),
            (bad_addition, 'UNIT_MISMATCH', '/definition/expression', {}),
            (bad_dimensions, 'UNSUPPORTED_OUTPUT_UNIT', '/definition/output', {}),
            (cyclic, 'DEPENDENCY_CYCLE', '', {}),
            (dependent, 'DEFINITION_LIMIT', '', dict(dependency_depth=1)),
        ]
        for invalid, code, suffix, limits in cases:
            with self.subTest(code=code, suffix=suffix):
                error = self.assert_error(code, d.validate, bundle(base, deepcopy(base), invalid), limits)
                self.assertEqual(error.path, '/definitions/2' + suffix)
        valid = entry(definition(constant('2')), 'b')
        program = d.validate(bundle(base, deepcopy(base), valid))
        projection = d.require_program(program)
        self.assertEqual(projection['nodes'][1]['path'], '/definitions/1/definition/expression')

    def test_cycles_are_rejected_before_impossible_content_hash_verification(self):
        fake_a = dict(variable_id='a', revision='sha256:' + 'a' * 64)
        fake_b = dict(variable_id='b', revision='sha256:' + 'b' * 64)
        a = dict(fake_a, definition=definition(dict(op='ref', **fake_b)))
        b = dict(fake_b, definition=definition(dict(op='ref', **fake_a)))
        self.assert_error('DEPENDENCY_CYCLE', d.validate, bundle(a, b))
        a['definition']['expression'] = dict(op='ref', **fake_a)
        self.assert_error('DEPENDENCY_CYCLE', d.validate, bundle(a))

    def test_dependency_depth_exact_and_one_beyond_even_with_shared_cache(self):
        values = [entry(definition(), 'v0')]
        for index in range(1, 9):
            values.append(entry(definition(reference(values[-1])), 'v' + str(index)))
        d.validate(bundle(*values[:8]))
        self.assert_error('DEFINITION_LIMIT', d.validate, bundle(*values))
        self.assert_error('DEFINITION_LIMIT', d.validate, bundle(*values[:8]), dict(dependency_depth=7))

    def test_node_and_expression_depth_exact_limits(self):
        expression = constant()
        for _ in range(31): expression = dict(op='neg', arg=expression)
        d.validate(bundle(entry(definition(expression))))
        expression = dict(op='neg', arg=expression)
        self.assert_error('DEFINITION_LIMIT', d.revision, definition(expression))
        def balanced(leaves):
            if leaves == 1: return constant()
            left = leaves // 2
            return binary('add', balanced(left), balanced(leaves-left))
        expression = dict(op='neg', arg=balanced(128))
        result = d.validate(bundle(entry(definition(expression)))).to_dict()
        self.assertEqual(len(result['nodes']), 256)
        self.assert_error('DEFINITION_LIMIT', d.validate, bundle(entry(definition(expression))), dict(nodes=255))
        self.assert_error('DEFINITION_LIMIT', d.revision, definition(dict(op='neg', arg=expression)))

    def test_resolved_expression_depth_includes_references(self):
        expression = constant()
        for _ in range(30): expression = dict(op='neg', arg=expression)
        base = entry(definition(expression), 'base')
        top = entry(definition(reference(base)), 'top')
        d.validate(bundle(base, top))
        top = entry(definition(dict(op='neg', arg=reference(base))), 'top')
        self.assert_error('DEFINITION_LIMIT', d.validate, bundle(base, top))

    def test_definition_count_shared_nodes_and_lowerable_capabilities(self):
        values = [entry(definition(), 'v' + str(index)) for index in range(33)]
        self.assertEqual(len(d.validate(bundle(*values[:32])).to_dict()['definitions']), 32)
        self.assert_error('DEFINITION_LIMIT', d.validate, bundle(*values))
        for key, maximum in d.CEILINGS.items():
            for value in (True, 0, maximum + 1):
                self.assert_error('INVALID_SHAPE', d.validate, bundle(), {key: value})
        self.assert_error('INVALID_SHAPE', d.validate, bundle(), dict(other=1))
        with self.assertRaises(TypeError): d.CEILINGS['nodes'] = 300

    def test_submission_byte_bound_exact_and_unbounded_root_list_preflight(self):
        submitted = bundle()
        size = len(d.canonical(submitted).encode())
        d.validate(submitted, dict(bytes=size))
        self.assert_error('DEFINITION_LIMIT', d.validate, submitted, dict(bytes=size-1))
        submitted['roots'] *= 10000
        self.assert_error('DEFINITION_LIMIT', d.validate, submitted)

    def test_program_projection_for_operating_yield_and_dated_reference(self):
        cases = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/variable-examples.json').read_text())['cases']
        example = next(case for case in cases if case['id'] == 'operating_yield_three_year')
        base = entry(example['definition'], 'yield')
        dated = entry(definition(dict(op='lookback', months=3,
            arg=dict(op='at', date='2023-07-01', arg=reference(base))), display='percent'), 'dated')
        result = d.validate(bundle(base, dated)).to_dict()
        self.assertEqual([(item['parameter'], item['count']) for item in result['requirements']],
            [('annual.revenue', 1), ('annual.operating_margin', 3), ('market.enterprise_value', 1)])
        self.assertEqual(result['nodes'][-1]['target'], result['definitions'][0]['root'])
        self.assertEqual(result['nodes'][-3]['op'], 'lookback')
        self.assertEqual(result['nodes'][-2]['date'], '2023-07-01')

    def test_historical_examples_are_classified_against_actual_capability(self):
        cases = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/variable-examples.json').read_text())['cases']
        unsupported = {'spread_percentage_points': 'UNKNOWN_PARAMETER', 'calendar_month_clamp': 'UNKNOWN_PARAMETER',
                       'calendar_mean': 'UNSUPPORTED_OPERATION', 'quarterly_not_lookback': 'UNKNOWN_PARAMETER'}
        for case in cases:
            with self.subTest(case=case['id']):
                if case['id'] in unsupported:
                    self.assert_error(unsupported[case['id']], d.revision, case['definition'])
                else:
                    # Date admissibility is intentionally decided at request binding.
                    d.validate(bundle(entry(case['definition'])))


if __name__ == '__main__':
    unittest.main()
