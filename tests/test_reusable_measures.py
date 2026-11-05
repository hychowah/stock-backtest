"""Versioned definitions and exact reusable measure closure."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from datetime import date
import unittest
from unittest.mock import patch
from backtest.financial import books
from backtest.variables import definitions as d, measures, parameters
import test_variable_definitions as lang
import test_annual_observations as annual
from test_annual_observations import Company, state, statement, term, field, formulas, values, explained, root


class ReusableMeasureDefinitions(unittest.TestCase):
    def setUp(self):
        self.company = Company()
        self.addCleanup(self.company.close)

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
        self.company.annual['income-statement']['2014-06-30']['revenue'] = state(None, 'MISSING_INPUT')
        program = formulas(
            term(dict(op='positive_div', left=dict(op='parameter', id='annual.revenue'), right=lang.constant('0')), 'USD'),
            term(dict(op='positive_div', left=lang.constant('1e308'), right=lang.constant('1e-308'))))
        self.assertEqual(values(program, self.company.view(), [root()]),
                         [[(None, 'MISSING_INPUT'), (None, 'NONFINITE_RESULT')]])

    def test_semantic_versions_remain_isolated(self):
        old = {row['id'] for row in parameters.catalog(parameters.V2)}
        new = {row['id'] for row in parameters.catalog(parameters.V3)}
        self.assertNotIn('annual.basic_eps', old)
        self.assertIn('annual.basic_eps', new)
        self.assertLess(old, new)

    def test_positive_division_and_versions(self):
        view = self.company.view()
        for denominator, expected, reason in [('2', -3., None), ('0', None, 'NONPOSITIVE_DENOMINATOR'), ('-2', None, 'NONPOSITIVE_DENOMINATOR')]:
            definition = term(dict(op='positive_div', left=lang.constant('-6'), right=lang.constant(denominator)))
            block = explained(formulas(definition), view, [root()])
            self.assertEqual(block['results'][0]['value'], expected)
            self.assertEqual(block['results'][0]['reason'], reason)
            self.assertEqual(block['operations'][-1]['denominator_rule'], 'positive')
            for version in (1, 2):
                definition['version'] = version
                with self.assertRaises(d.FormulaError):
                    d.validate(lang.bundle(lang.entry(definition)))


class InventoryExecution(unittest.TestCase):
    def setUp(self):
        self.company = Company()
        self.addCleanup(self.company.close)

    def test_report_ebitda_never_reads_annual_statement_rows(self):
        view = self.company.view()
        queries = []
        self.company.db.set_trace_callback(queries.append)
        self.addCleanup(self.company.db.set_trace_callback, None)
        self.assertEqual(values(formulas(field('annual.report_ebitda')), view, [root()]), [[(54e6, None)]])
        self.assertFalse([sql for sql in queries if 'annual_facts' in sql])

    def test_each_measure_executes_in_larger_expression(self):
        income = dict(revenue=100., costOfRevenue=40., operatingIncome=20., ebit=17., eps=2., epsDiluted=1.5, netIncome=90., weightedAverageShsOut=10., weightedAverageShsOutDil=15.)
        self.company.annual = {
            'income-statement': {'2014-06-30': {k: state(v) for k, v in income.items()}},
            'balance-sheet-statement': {'2014-06-30': {k: state(v) for k, v in dict(totalDebt=70., cashAndCashEquivalents=10., totalCurrentAssets=80., totalCurrentLiabilities=30., totalStockholdersEquity=90., goodwill=8., intangibleAssets=7., totalAssets=200.).items()}},
            'cash-flow-statement': {'2014-06-30': {k: state(v) for k, v in dict(freeCashFlow=14., operatingCashFlow=20., capitalExpenditure=-9.).items()}}}
        self.company.books['legacy', 2015] = dict(market_cap=200.,
            metrics=dict(ev_ebitda=[4., .25000000000000006], ev_ebitda_3y=[5., .2]),
            filters=dict(profit_margin=12., pe=8., pb=2., fcf_yield=7., price_fcf=9., peg=1.5,
                roe=10., current_ratio=2., interest_coverage=3., debt_equity=.7,
                return_1y=15., return_3y=25., operating_yield_spread_3y=4.))
        self.company.scopes = [dict(mode='historical', pool='legacy', context_date=self.company.root_date, book=2015)]
        view = self.company.view()
        expected = dict(gross_profit=60., gross_margin=.6, operating_margin=.2, net_margin=.12,
            ebit=17., ebitda=54e6, free_cash_flow=14., operating_cash_flow_plus_capex=11.,
            total_debt=70., net_debt=60., working_capital=50., tangible_book_equity=75.,
            market_cap=200., enterprise_value=180e6, basic_eps=2., diluted_eps=1.5,
            price_sales=2., debt_assets=.35, pe=8., pb=2., fcf_yield=.07, price_fcf=9.,
            peg=1.5, roe=.1, current_ratio=2., interest_coverage=3., debt_equity=.7,
            return_1y=.15, return_3y=.25, ev_ebitda=4., ev_ebitda_3y=5.,
            ebitda_yield=.25000000000000006, operating_yield_spread_3y=.04)
        for descriptor in measures.catalog():
            key = descriptor['id']
            with self.subTest(measure=key):
                bundle = measures.bundle([key])
                expression = dict(op='add', left=dict(op='ref', **bundle['roots'][0]),
                    right=dict(op='constant', value='0', unit=descriptor['unit']))
                outer = lang.entry(term(expression, descriptor['unit'], descriptor['display']), 'outer')
                bundle['definitions'].append(outer)
                bundle['roots'] = [lang.root(outer)]
                program = annual.columns.Formulas(d.validate(bundle))
                with patch.object(annual.columns.measure_observations, 'dated', side_effect=AssertionError('recalculated')):
                    self.assertEqual(values(program, view, [root()]), [[(expected[key], None)]])

    def test_derived_equal_date_uses_owner_and_never_exit(self):
        self.company.financials = {f'{year}-06-30': dict(revenue=100., operatingIncome=20., netIncome=10.,
            totalStockholdersEquity=50., epsDiluted=year-2010.) for year in (2012, 2013, 2014)}
        self.company.treasury10 = [('2015-01-01', 2.)]
        self.company.books['legacy', 2015] = dict(market_cap=123., metrics=dict(ev_ebitda=[4., .25]), filters=dict(pe=9.))
        self.company.scopes = [dict(mode='historical', pool='legacy', context_date=self.company.root_date, book=2015)]
        view = self.company.view()
        same = formulas(field('owner.pe', wrap=dict(op='at', date=self.company.root_date)))
        roots = [root(), root(owner_scope=dict(kind='prepared', book=2015)), root(owner_scope=dict(kind='dated'))]
        with patch.object(books, 'ebitda_yield_and_multiple', wraps=books.ebitda_yield_and_multiple) as helper, \
                patch.object(view, 'lookup', wraps=view.lookup) as lookup:
            results = values(formulas(field('owner.pe')), view, roots) + values(same, view, roots[:1])
        self.assertEqual(results, [[(9., None)], [(9., None)], [(15e6, None)], [(15e6, None)]])
        self.assertEqual(helper.call_count, 2)
        backward = [call.args[1] for call in lookup.call_args_list if not call.args[3]]
        self.assertTrue(backward)
        self.assertTrue(all(day <= date.fromisoformat(self.company.root_date) for day in backward))

    def test_report_ebitda_history_uses_broad_spine_and_missing_year(self):
        self.company.reports = [statement('2016-12-31', ebitda=1.), statement('2017-03-31', ebitda=2.),
                                statement('2017-12-31', ebitda=3.), statement('2018-12-31', ebitda=10. / 49.)]
        self.company.annual = {}
        self.company.root_date = '2019-06-03'
        program = formulas(field('annual.report_ebitda', count=3))
        [members] = [result['members'] for result in explained(program, self.company.view(), [root(day='2019-06-03')])['observations']['results']]
        self.assertEqual([x['value'] for x in members], [1., 3., 10. / 49.])
        self.assertEqual([x['fiscal_date'] for x in members], ['2016-12-31', '2017-12-31', '2018-12-31'])
        del self.company.reports[1:3]
        [members] = [result['members'] for result in explained(program, self.company.view(), [root(day='2019-06-03')])['observations']['results']]
        self.assertEqual(members[1]['reason'], 'MISSING_FISCAL_YEAR')
        # The two owners retain their source arithmetic even for a value whose
        # report division and reciprocal-times-EV round differently.
        ev, multiple = next((ev, multiple) for ev in range(1, 100) for multiple in range(2, 100)
                            if ev / multiple != (1 / multiple) * ev)
        self.company.reports = [statement('2018-12-31', earnings_yield=1 / multiple, market_cap=ev, enterprise=ev, ebitda=ev / multiple)]
        view = self.company.view()
        roots = [root(pool='cached', day='2019-06-03')]
        self.assertEqual(view.admit(roots)[0]['valuation']['ebitda'], (1 / multiple) * ev)
        self.assertEqual(values(formulas(field('annual.report_ebitda')), view, roots), [[(ev / multiple, None)]])
        entry = books.entry_valuation(dict(fiscal=date(2018, 12, 31), market_cap=ev, enterprise=ev,
            **{'yield': 1 / multiple}), date(2019, 6, 1), lambda day, *args: (day, 1.))
        self.assertEqual(entry[-1], (1 / multiple) * ev)


class CaptureAndAdmission(unittest.TestCase):
    def test_capture_restore_and_unused_gates_before_financial_access(self):
        import tempfile
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
        company = Company()
        self.addCleanup(company.close)
        company.reports = [statement('2012-06-30'), statement('2013-06-30', market_cap=1., enterprise=2., ebitda=7.),
                           statement('2013-12-31', market_cap=1., enterprise=2., ebitda=9.), statement('2014-06-30')]
        company.annual = {}
        program = formulas(field('annual.report_ebitda', count=3))
        block = explained(program, company.view(), [root()])
        self.assertTrue(block['results'][0]['valid'])
        members = block['observations']['results'][0]['members']
        self.assertEqual([x['value'] for x in members], [54e6, 9., 54e6])
        self.assertEqual(members[1]['fiscal_date'], '2013-12-31')


if __name__ == '__main__':
    unittest.main()
