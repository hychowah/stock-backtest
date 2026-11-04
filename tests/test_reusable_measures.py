"""Versioned definitions and exact reusable measure closure."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import unittest
from unittest.mock import patch
from backtest.variables import definitions as d, measures, reference, parameters
from backtest.inputs import observation_inputs as source
import test_variable_definitions as lang
import test_observations as fixtures


class ReusableMeasureDefinitions(unittest.TestCase):
    def test_registry_closures_and_bound(self):
        rows = measures.catalog()
        self.assertEqual(len(rows), 33)
        self.assertEqual(len({row['id'] for row in rows}), 33)
        for row in rows:
            program = d.validate(measures.bundle([row['id']]))
            with patch.object(measures, 'catalog', side_effect=AssertionError), patch.object(measures, 'bundle', side_effect=AssertionError):
                self.assertEqual(d.require_program(program), program.to_dict())
        self.assertEqual(len(measures.bundle(['gross_margin'])['definitions']), 2)
        with self.assertRaises(d.FormulaError) as caught:
            measures.bundle([row['id'] for row in rows])
        self.assertEqual(caught.exception.code, 'DEFINITION_LIMIT')

    def test_positive_division_missing_precedence_and_overflow(self):
        fixture = fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.annual['2014-06-30']['revenue'] = fixtures.state(None, 'MISSING_INPUT')
        root = dict(symbol='A', pool='legacy', mode='historical', date=fixture.root_date)
        for expression, unit, display, expected in (
            (dict(op='positive_div', left=dict(op='parameter',id='annual.revenue'), right=lang.constant('0')), 'USD', 'usd', 'MISSING_INPUT'),
            (dict(op='positive_div', left=lang.constant('1e308'), right=lang.constant('1e-308')), 'scalar', 'number', 'NONFINITE_RESULT')):
            definition = lang.definition(expression,unit,display)
            definition.update(version=3,parameter_catalog=parameters.V3)
            program = d.validate(lang.bundle(lang.entry(definition)))
            result = reference.evaluate(reference.plan(program,[root]),fixture.view()).to_dict()['results'][0]
            self.assertEqual(result['reason'],expected)

    def test_semantic_versions_remain_isolated(self):
        old = {row['id'] for row in parameters.catalog(parameters.V2)}
        new = {row['id'] for row in parameters.catalog(parameters.V3)}
        self.assertNotIn('annual.basic_eps', old)
        self.assertIn('annual.basic_eps', new)
        self.assertLess(old, new)

    def test_positive_division_and_versions(self):
        fixture = fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root = dict(symbol='A', pool='legacy', mode='historical', date=fixture.root_date)
        for denominator, expected, reason in [('2', -3., None), ('0', None, 'NONPOSITIVE_DENOMINATOR'), ('-2', None, 'NONPOSITIVE_DENOMINATOR')]:
            expr = dict(op='positive_div', left=lang.constant('-6'), right=lang.constant(denominator))
            definition = lang.definition(expr)
            definition.update(version=3, parameter_catalog=parameters.V3)
            program = d.validate(lang.bundle(lang.entry(definition)))
            block = reference.evaluate(reference.plan(program, [root]), fixture.view()).to_dict()
            self.assertEqual(block['results'][0]['value'], expected)
            self.assertEqual(block['results'][0]['reason'], reason)
            self.assertEqual(block['operations'][-1]['denominator_rule'], 'positive')
            for version in (1, 2):
                definition['version'] = version
                with self.assertRaises(d.FormulaError):
                    d.validate(lang.bundle(lang.entry(definition)))


class InventoryExecution(unittest.TestCase):
    def test_repeated_report_history_reserves_every_scan_before_input_reads(self):
        from backtest import observations
        fixture = fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.reports = [fixtures.statement('2014-06-30') for _ in range(100)]
        fixture.annual = {}
        view = fixture.view()
        requests = [fixture.request(parameter='annual.report_ebitda', identity=f'r{i}')
                    for i in range(20)]
        with patch.object(view, 'admit', wraps=view.admit) as admission, \
                patch.object(view, 'company', wraps=view.company) as company, \
                patch.object(view, 'broad_reports', wraps=view.broad_reports) as reports:
            with self.assertRaises(observations.ObservationError) as caught:
                observations.observe(observations.plan(requests, fixture.contexts(), {'rows': 600}), view)
            self.assertEqual(caught.exception.code, 'WORK_LIMIT')
            admission.assert_not_called()
            company.assert_not_called()
            reports.assert_not_called()
        block = observations.observe(
            observations.plan(requests, fixture.contexts(), {'rows': 3000}), view).to_dict()
        self.assertEqual(len(block['results']), 20)
        self.assertTrue(all(result['valid'] for result in block['results']))

    def test_report_ebitda_never_reads_annual_statement_rows(self):
        from backtest import observations
        fixture = fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        view = fixture.view()
        view._bounds['max_annual'] = observations.CEILINGS['rows']
        queries = []
        fixture.db.set_trace_callback(queries.append)
        self.addCleanup(fixture.db.set_trace_callback, None)
        block = observations.observe(observations.plan(
            [fixture.request(parameter='annual.report_ebitda')], fixture.contexts()), view).to_dict()
        self.assertTrue(block['results'][0]['valid'])
        self.assertFalse(any('observation_annual' in sql and 'LIMIT 0' not in sql for sql in queries))

    def test_each_measure_executes_in_larger_expression(self):
        fixture = fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        income = dict(revenue=100., costOfRevenue=40., operatingIncome=20., ebit=17., eps=2., epsDiluted=1.5, netIncome=90., weightedAverageShsOut=10., weightedAverageShsOutDil=15.)
        fixture.annual['2014-06-30'] = {k: fixtures.state(v) for k, v in income.items()}
        view = fixture.view()
        db = fixture.db
        for endpoint, values in (
            ('balance-sheet-statement', dict(totalDebt=70., cashAndCashEquivalents=10., totalCurrentAssets=80., totalCurrentLiabilities=30., totalStockholdersEquity=90., goodwill=8., intangibleAssets=7., totalAssets=200.)),
            ('cash-flow-statement', dict(freeCashFlow=14., operatingCashFlow=20., capitalExpenditure=-9.))):
            db.execute('INSERT INTO observation_annual VALUES(?,?,?,?)', ('A', endpoint, '2014-06-30',
                source.encoded({k: fixtures.state(v) for k, v in values.items()})))
        evidence = dict(snapshot=dict(market_cap=200., enterprise_value=250.),
            metrics=dict(ev_ebitda=[4., .25000000000000006], ev_ebitda_3y=[5., .2]),
            filters=dict(profit_margin=12., pe=8., pb=2., fcf_yield=7., price_fcf=9., peg=1.5,
                roe=10., current_ratio=2., interest_coverage=3., debt_equity=.7,
                return_1y=15., return_3y=25., operating_yield_spread_3y=4.))
        db.execute('INSERT INTO observation_measure_contexts VALUES(?,?,?,?,?)',
            ('historical', 'legacy', fixture.root_date, 'A', source.encoded(evidence)))
        db.execute('DELETE FROM observation_metadata')
        metadata = source.finish(db, fixture.latest_date, scopes=[dict(mode='historical', pool='legacy',
            context_date=fixture.root_date, book=2015)])
        view._expected = metadata
        expected = dict(gross_profit=60., gross_margin=.6, operating_margin=.2, net_margin=.12,
            ebit=17., ebitda=54e6, free_cash_flow=14., operating_cash_flow_plus_capex=11.,
            total_debt=70., net_debt=60., working_capital=50., tangible_book_equity=75.,
            market_cap=200., enterprise_value=180e6, basic_eps=2., diluted_eps=1.5,
            price_sales=2., debt_assets=.35, pe=8., pb=2., fcf_yield=.07, price_fcf=9.,
            peg=1.5, roe=.1, current_ratio=2., interest_coverage=3., debt_equity=.7,
            return_1y=.15, return_3y=.25, ev_ebitda=4., ev_ebitda_3y=5.,
            ebitda_yield=.25000000000000006, operating_yield_spread_3y=.04)
        root = dict(symbol='A', pool='legacy', mode='historical', date=fixture.root_date)
        for descriptor in measures.catalog():
            key = descriptor['id']
            with self.subTest(measure=key):
                bundle = measures.bundle([key])
                expression = dict(op='add', left=dict(op='ref', **bundle['roots'][0]),
                    right=dict(op='constant', value='0', unit=descriptor['unit']))
                definition = lang.definition(expression, descriptor['unit'], descriptor['display'])
                definition.update(version=3, parameter_catalog=parameters.V3)
                outer = lang.entry(definition, 'outer')
                bundle['definitions'].append(outer)
                bundle['roots'] = [lang.root(outer)]
                plan = reference.plan(d.validate(bundle), [root])
                block = reference.evaluate(plan, view).to_dict()
                result = block['results'][0]
                self.assertTrue(result['valid'], result)
                self.assertEqual(result['value'], expected[key])

    def test_derived_equal_date_uses_owner_and_never_exit(self):
        from unittest.mock import patch
        from backtest.financial import books
        fixture = fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        view = fixture.view()
        db = fixture.db
        db.executescript('CREATE TABLE financial_inputs(symbol TEXT, fiscal TEXT, values_json TEXT); CREATE TABLE treasury10(day TEXT, yield_percent REAL);')
        for year in (2012, 2013, 2014):
            db.execute('INSERT INTO financial_inputs VALUES(?,?,?)', ('A', f'{year}-06-30', source.encoded(dict(revenue=100., operatingIncome=20., netIncome=10., totalStockholdersEquity=50., epsDiluted=year-2010))))
        db.execute("INSERT INTO treasury10 VALUES('2015-01-01',2.)")
        evidence = dict(snapshot=dict(market_cap=123.), metrics=dict(ev_ebitda=[4., .25]), filters=dict(pe=9.))
        db.execute('INSERT INTO observation_measure_contexts VALUES(?,?,?,?,?)', ('historical', 'legacy', fixture.root_date, 'A', source.encoded(evidence)))
        db.execute('DELETE FROM observation_metadata')
        view._expected = source.finish(db, fixture.latest_date, scopes=[dict(mode='historical', pool='legacy', context_date=fixture.root_date, book=2015)])
        from backtest import observations
        contexts = fixture.contexts() + [dict(id='same', kind='at', parent='root', date=fixture.root_date),
            dict(fixture.contexts()[0], id='prepared', owner_scope=dict(kind='prepared', book=2015)),
            dict(fixture.contexts()[0], id='dated', owner_scope=dict(kind='dated'))]
        requests = [fixture.request(parameter='owner.pe', context=context, identity=context)
                    for context in ('root','same','prepared','dated')]
        with patch.object(books, 'ebitda_yield_and_multiple', wraps=books.ebitda_yield_and_multiple) as helper:
            block = observations.observe(observations.plan(requests, contexts), view).to_dict()
        self.assertEqual([x['members'][0]['value'] for x in block['results']], [9., 15e6, 9., 15e6])
        self.assertEqual(helper.call_count, 2)
        self.assertTrue(all(call.args[1] <= __import__('datetime').date.fromisoformat(fixture.root_date) for call in fixture.lookup.call_args_list if not call.args[3]))

    def test_report_ebitda_history_uses_broad_spine_and_missing_year(self):
        from datetime import date
        from backtest import observations
        anchor = dict(fiscal=date(2018,12,31), ebitda=10. / 49.)
        broad = [dict(fiscal='2016-12-31', ebitda=1.), dict(fiscal='2017-03-31', ebitda=2.),
                 dict(fiscal='2017-12-31', ebitda=3.), dict(fiscal='2018-12-31', ebitda=999.)]
        values = observations._report_ebitda(broad, anchor, 3, lambda: None)
        self.assertEqual([x['value'] for x in values], [1., 3., 10. / 49.])
        self.assertEqual([x['fiscal_date'] for x in values], ['2016-12-31','2017-12-31','2018-12-31'])
        missing = observations._report_ebitda([broad[0]], anchor, 3, lambda: None)
        self.assertEqual(missing[1]['reason'], 'MISSING_FISCAL_YEAR')
        from backtest.financial import books
        report_ebitda = 1. / 49.
        entry_ebitda = (1. / 49.) * 1.
        self.assertEqual(report_ebitda, entry_ebitda)
        # The two owners retain their source arithmetic even for a value whose
        # report division and reciprocal-times-EV round differently.
        found = next((ev,multiple) for ev in range(1,100) for multiple in range(2,100)
                     if ev / multiple != (1 / multiple) * ev)
        ev,multiple = found
        self.assertNotEqual(ev / multiple, (1 / multiple) * ev)
        entry = books.entry_valuation(dict(fiscal=date(2018,12,31), market_cap=ev, enterprise=ev,
            **{'yield':1 / multiple}), date(2019,6,1), lambda day,*args:(day,1.))
        self.assertEqual(entry[-1], (1 / multiple) * ev)
        self.assertEqual(observations._report_ebitda([], dict(fiscal=date(2018,12,31),ebitda=ev / multiple), 1, lambda:None)[0]['value'], ev / multiple)


class CaptureAndAdmission(unittest.TestCase):
    def test_capture_restore_and_unused_gates_before_financial_access(self):
        import tempfile
        from unittest.mock import patch
        from backtest.variables import library, selection
        bundle = measures.bundle(['gross_margin'])
        with tempfile.TemporaryDirectory() as folder:
            store = library.Store(Path(folder) / 'private.sqlite')
            store.create('Private fixture', lang.definition(lang.constant('1')))
            capture = store.capture(bundle['roots'], submitted=bundle['definitions'])
            with patch.object(measures, 'bundle', side_effect=AssertionError('registry access')), patch.object(measures, 'catalog', side_effect=AssertionError('registry access')):
                self.assertEqual(library.require_capture(library.VariableCapture(capture.to_json())), capture.to_dict())
        old = lang.entry(lang.definition(lang.constant('2')), 'old')
        new_definition = lang.definition(lang.constant('3'))
        new_definition.update(version=3, parameter_catalog=parameters.V3)
        new = lang.entry(new_definition, 'new')
        for roots in ([lang.root(old)], [lang.root(new)]):
            program = d.validate(lang.bundle(old, new, roots=roots))
            self.assertEqual(selection.require_program(program), program.to_dict())
        from backtest.application import strategy_requests
        import test_strategy_requests as requests
        capture = strategy_requests.capture_strategy(requests.intent(requests.formula(new)), submitted=[new]).to_dict()
        self.assertEqual(strategy_requests.check_options(dict(strategy=capture, engine='original')), capture)

    def test_broad_report_history_does_not_require_income_or_legacy_eligibility(self):
        from backtest import observations
        fixture = fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        prior = fixtures.statement('2013-06-30')
        prior['market_cap'] = 1.
        prior['enterprise'] = 2.
        prior['ebitda'] = 7.
        duplicate = fixtures.statement('2013-12-31')
        duplicate['market_cap'] = 1.
        duplicate['enterprise'] = 2.
        duplicate['ebitda'] = 9.
        fixture.reports = [fixtures.statement('2012-06-30'), prior, duplicate, fixtures.statement('2014-06-30')]
        fixture.annual = {}
        view = fixture.view()
        request = fixture.request(parameter='annual.report_ebitda', count=3)
        result = observations.observe(observations.plan([request], fixture.contexts()), view).to_dict()['results'][0]
        self.assertTrue(result['valid'])
        self.assertEqual([x['value'] for x in result['members']], [54e6, 9., 54e6])
        self.assertEqual(result['members'][1]['fiscal_date'], '2013-12-31')

if __name__ == '__main__':
    unittest.main()
