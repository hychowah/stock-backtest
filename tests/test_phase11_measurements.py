"""Existing process/resource workloads with a version-3 expanded capture."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import unittest
from unittest.mock import patch
import hashlib
import json
import time

from backtest.engines.numerical import formula_capabilities
from backtest.application import strategy_requests
from backtest.variables import definitions, parameters, reference
from backtest.engines.numerical import formulas
from backtest.runtime.process_owner import process_metrics
import scalar_qualification
import test_numerical_scalar_measurements as measurements
import test_variable_definitions as language
import test_strategy_requests as intent
import test_dated_observations as dated_fixture
from test_parameter_contract import ORACLE
from test_phase11_candidate import expanded_capture


def shared_capture(shared=True, **unused):
    if not shared:
        return expanded_capture('cached', 'filter_first')
    definition = language.definition(dict(op='annual', parameter='annual.revenue', stat='growth', count=3), 'scalar', 'percent')
    definition.update(version=3, parameter_catalog=parameters.V3)
    base = language.entry(definition, 'phase11:shared-growth')
    expression = dict(op='positive_div', left=language.reference(base), right=language.constant('2'))
    definition = language.definition(expression, 'scalar', 'percent')
    definition.update(version=3, parameter_catalog=parameters.V3)
    result = language.entry(definition, 'phase11:shared-signal')
    strategy = intent.intent(intent.formula(result),
        [intent.condition(intent.formula(base), '-100', 'percentage_points')], rank_to=10)
    strategy['pool'] = 'cached'
    return strategy_requests.capture_strategy(strategy, submitted=[base, result])


def owner_capture():
    expression = dict(op='add', left=dict(op='parameter', id='owner.ev_ebitda'),
                      right=dict(op='parameter', id='owner.ebitda_yield'))
    definition = language.definition(expression)
    definition.update(version=3, parameter_catalog=parameters.V3)
    entry = language.entry(definition, 'phase11:owner-heavy')
    strategy = intent.intent(intent.formula(entry), rank_to=10)
    strategy['pool'] = 'cached'
    return strategy_requests.capture_strategy(strategy, submitted=[entry])


def many_input_capture():
    def parameter(name): return dict(op='parameter', id=name)
    def ratio(left, right): return dict(op='positive_div', left=left, right=right)
    terms = [ratio(parameter('annual.revenue'), parameter('market.enterprise_value')),
             ratio(parameter('annual.operating_income'), parameter('market.enterprise_value')),
             ratio(parameter('market.adjusted_price'), language.constant('1', 'USD/share')),
             parameter('owner.ev_ebitda'), parameter('owner.ebitda_yield'),
             parameter('treasury.us_3m'), parameter('treasury.us_10y'),
             dict(op='annual', parameter='annual.revenue', stat='growth', count=3),
             dict(op='annual', parameter='annual.revenue', stat='cagr', count=3)]
    expression = terms[0]
    for term in terms[1:]:
        expression = dict(op='add', left=expression, right=term)
    definition = language.definition(expression)
    definition.update(version=3, parameter_catalog=parameters.V3)
    entry = language.entry(definition, 'phase11:many-inputs')
    strategy = intent.intent(intent.formula(entry), rank_to=10)
    strategy['pool'] = 'cached'
    return strategy_requests.capture_strategy(strategy, submitted=[entry])


@unittest.skipUnless(3 in formula_capabilities.capabilities()['definition_versions'],
                     'Expanded application admission remains closed')
class ExpandedMeasurements(measurements.MeasurementTests):
    def setUp(self):
        manifest_path = Path(__file__).resolve().parents[1] / 'candidate-manifest.json'
        if sys.platform != 'win32' and manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text())
            root = manifest_path.parent
            actual = {p.relative_to(root).as_posix() for directory in ('backtest','tests','scripts','tools','website')
                      for p in (root / directory).rglob('*') if p.is_file()
                      and '__pycache__' not in p.parts and p.suffix != '.pyc'}
            if (root / 'requirements-numerical.txt').is_file():
                actual.add('requirements-numerical.txt')
            fixture = 'docs/plans/custom-variables/phases/phase-01/examples.json'
            if (root / fixture).is_file():
                actual.add(fixture)
            if (type(manifest) is not dict or not manifest or set(manifest) != actual
                    or any(not isinstance(name, str) or name.startswith('/') or '..' in Path(name).parts
                           for name in manifest)):
                raise ValueError('Private candidate manifest inventory differs.')
            if any(hashlib.sha256((root / name).read_bytes()).hexdigest() != digest
                   for name, digest in manifest.items()):
                raise ValueError('Private candidate manifest changed.')
            from importlib.metadata import version
            environment = dict(platform=sys.platform, python=sys.version, interpreter=sys.executable,
                dependencies={name:version(name) for name in ('numpy','numba','llvmlite')},
                product_test_files=len(manifest), product_test_sha256=scalar_qualification.digest(manifest),
                native_variances=[], native_cache_coverage='unknown')
            receipt = patch.object(measurements, 'receipt_environment', return_value=environment)
            receipt.start(); self.addCleanup(receipt.stop)
        super().setUp()
        capture = shared_capture
        first = patch.object(measurements, 'program', side_effect=capture)
        second = patch.object(scalar_qualification, 'program', side_effect=capture)
        first.start(); second.start()
        self.addCleanup(first.stop); self.addCleanup(second.stop)

    def test_owner_heavy_complete_application(self):
        with scalar_qualification.Scenario(companies=64, first=2015, last=2016,
                                           capture=owner_capture()) as scenario:
            self.receipt.update(scenario=self.scenario_receipt(scenario))
            options = scenario.options('custom')
            left, original, _ = scenario.run_backend('original', 'custom', options)
            right, numerical, _ = scenario.run_backend('experimental', 'custom', options)
            comparison = scalar_qualification.compare_artifacts(left, right)
            self.assertGreater(comparison['holdings'], 0)
            self.receipt.update(complete_calls=[original, numerical], comparison=comparison)
        self.emit('expanded-owner-heavy-64')

    def test_many_inputs_across_chunks(self):
        with scalar_qualification.Scenario(companies=300, first=2015, last=2015,
                                           capture=many_input_capture()) as scenario:
            self.receipt.update(scenario=self.scenario_receipt(scenario))
            options = scenario.options('custom')
            left, original, _ = scenario.run_backend('original', 'custom', options)
            right, numerical, _ = scenario.run_backend('experimental', 'custom', options)
            comparison = scalar_qualification.compare_artifacts(left, right)
            self.assertGreater(comparison['holdings'], 0)
            self.assertGreater(comparison['evaluations'], 1)
            self.receipt.update(complete_calls=[original, numerical], comparison=comparison)
        self.emit('expanded-many-inputs-300')

    def test_all_52_direct_inputs_in_one_expression(self):
        started = time.perf_counter()
        fixture = dated_fixture.TransportTests('test_all_52_actual_preparation_sqlite_numerical_provider_and_reference')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        sql, numerical_view = fixture.views()
        expected = {identity:fixture.fixture.rows[endpoint][0][field]
                    for endpoint,fields in ORACLE.items() for field,identity in fields.items()
                    if identity.startswith('annual.')}
        expected.update({'market.adjusted_price':20, 'market.volume':12.5,
                         'treasury.us_3m':.02, 'treasury.us_10y':-.01})
        units = {identity:('share' if field in ('weightedAverageShsOut','weightedAverageShsOutDil','volume')
                 else 'USD/share' if field == 'adjClose' else 'scalar' if endpoint == 'treasury-rates' else 'USD')
                 for endpoint,fields in ORACLE.items() for field,identity in fields.items()}
        self.assertEqual(len(expected), 52)
        terms = []
        for identity in expected:
            node = dict(op='parameter', id=identity)
            if units[identity] != 'scalar':
                node = dict(op='div', left=node, right=language.constant('1', units[identity]))
            terms.append(node)
        while len(terms) > 1:
            terms = [dict(op='add', left=terms[index], right=terms[index+1])
                     if index+1 < len(terms) else terms[index]
                     for index in range(0, len(terms), 2)]
        expression = terms[0]
        definition = language.definition(expression)
        definition.update(version=2, parameter_catalog=parameters.V2)
        program = definitions.validate(language.bundle(language.entry(definition)))
        root = {key:value for key,value in fixture.contexts()[0].items() if key not in ('id','kind')}
        plan = reference.plan(program, [root])
        preparation = time.perf_counter() - started
        before = process_metrics()
        with patch.object(numerical_view, 'company', wraps=numerical_view.company) as company, \
             patch.object(numerical_view, '_json', wraps=numerical_view._json) as decoded, \
             formulas.Evaluator() as evaluator:
            began = time.perf_counter(); expected_block = reference.evaluate(plan, sql).to_dict()
            reference_seconds = time.perf_counter() - began
            began = time.perf_counter(); actual = evaluator.evaluate(plan, numerical_view).to_dict()
            cold_seconds = time.perf_counter() - began
            began = time.perf_counter(); again = evaluator.evaluate(plan, numerical_view).to_dict()
            warm_seconds = time.perf_counter() - began
            scalar_qualification.compare_blocks([expected_block], [actual])
            scalar_qualification.compare_blocks([expected_block], [again])
            observed = {item['parameter']:item['members'][0]['value'] for item in actual['observations']['results']}
            self.assertEqual(observed, expected)
            self.assertTrue(all(item['valid'] for item in actual['observations']['results']))
            self.receipt.update(preparation_seconds=preparation, reference_seconds=reference_seconds,
                cold_seconds=cold_seconds, reusable_seconds=warm_seconds, formula=dict(evaluator.stats),
                provider_company_reads=company.call_count, decoded_records=decoded.call_count,
                decoded_bytes=sum(len(call.args[0].encode('utf-8')) for call in decoded.call_args_list),
                tasks=len(actual['operations']), members=sum(len(item['members']) for item in actual['observations']['results']),
                encoded_evidence_bytes=len(definitions.canonical(actual).encode('utf-8')),
                process_before=before, process_after=process_metrics())
        self.assertTrue(fixture.doCleanups())
        self.emit('all-52-direct-one-expression')


if __name__ == '__main__':
    unittest.main()
