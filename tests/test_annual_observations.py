"""Annual evidence: independent inventory, typed annual facts, endpoint joins and formulas.

Synthetic files live in TemporaryDirectory (the source-bound runner places it
outside the checkout). No expected legacy immutable bytes are written.

`Company` is a shared in-memory fixture: one SQLite database serves as the
daily cache and the research facts of one company, A. `formulas`, `values`
and `explained` evaluate checked programs with the column evaluator.
"""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from contextlib import closing, ExitStack
from datetime import date, timedelta
import hashlib
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backtest.application import variable_authoring
from backtest.financial import rules
from backtest.inputs import financial_inputs as financial, facts
from backtest.inputs import daily, research
from backtest.variables import columns, definitions, parameters
from prepared_inputs_fixture import PreparedInputs
import test_prepared_facts
import test_variable_definitions as language
from test_parameter_contract import ORACLE as DIRECT_ORACLE
ORACLE = {endpoint: dict(fields) for endpoint, fields in DIRECT_ORACLE.items()
          if all(identity.startswith('annual.') for identity in fields.values())}
ORACLE['income-statement'].update(ebit='annual.ebit', eps='annual.basic_eps', epsDiluted='annual.diluted_eps')
ORACLE['balance-sheet-statement']['totalDebt'] = 'annual.total_debt'
ORACLE['cash-flow-statement']['freeCashFlow'] = 'annual.free_cash_flow'
UNITS = {item['id']: item['unit'] for item in columns.catalog()}
DISPLAYS = {'USD': 'usd', 'share': 'shares', 'USD/share': 'usd_per_share', 'scalar': 'number'}


def annual_rows(fiscal='2014-06-30'):
    """Different signed/zero values make every endpoint-field error observable."""
    counter = 0
    result = {}
    for endpoint, fields in ORACLE.items():
        values = {}
        for field in fields:
            values[field] = (-1 if counter % 2 else 1) * counter
            counter += 1
        result[endpoint] = [dict(date=fiscal, reportedCurrency='USD', **values)]
    return result


def typed(resolution, symbol='A'):
    """Write one annual resolution to typed facts; return {(endpoint, fiscal): {column: (value, reason)}}."""
    with closing(sqlite3.connect(':memory:')) as db:
        db.row_factory = sqlite3.Row
        db.executescript(facts.SCHEMA)
        facts.store_annual(db, symbol, resolution)
        return {(row['endpoint'], row['fiscal']): {column: (row[column], row[column + '_reason'])
                                                   for column, _, _ in facts.ANNUAL}
                for row in db.execute('SELECT * FROM annual_facts')}


# Formula helpers.

def term(expression, unit='scalar', display=None, *, catalog=parameters.V3):
    """One definition; catalog /3 uses version 3, earlier catalogs version 1."""
    value = language.definition(expression, unit, display or DISPLAYS[unit])
    value['parameter_catalog'] = catalog
    if catalog == parameters.V3:
        value['version'] = 3
    return value


def field(identity, *, wrap=None, count=None, stat='mean', catalog=parameters.V3):
    """A definition that reads one parameter, optionally as an annual statistic or in a dated context."""
    expression = (dict(op='parameter', id=identity) if count is None
                  else dict(op='annual', stat=stat, count=count, parameter=identity))
    if wrap is not None:
        expression = dict(wrap, arg=expression)
    return term(expression, UNITS[identity], catalog=catalog)


def formulas(*values):
    """Checked formulas whose roots are every given definition, in order."""
    entries = [language.entry(value, f'draft:{index}') for index, value in enumerate(values)]
    return columns.Formulas(definitions.validate(language.bundle(*entries, roots=[language.root(e) for e in entries])))


def values(program, view, roots, checkpoint=lambda: None):
    """[(value, reason) per output] per root, values-only."""
    results = program.evaluate(roots, view, checkpoint, decisions=view.admit(roots, checkpoint))
    return [[result[definition['variable_id'], definition['revision']][::2] for definition in program.outputs]
            for result in results]


def explained(program, view, roots):
    return program.explain(roots, view, lambda: None, decisions=view.admit(roots))


def root(symbol='A', pool='legacy', mode='historical', day='2015-01-02', **owner):
    return dict(symbol=symbol, pool=pool, mode=mode, date=day, **owner)


def state(value, reason=None):
    return dict(value=value, valid=reason is None, reason=reason)


def statement(fiscal, *, earnings_yield=.3, market_cap=150e6, enterprise=180e6, ebitda=None):
    day = date.fromisoformat(fiscal)
    return dict(fiscal=fiscal, known=str(day + rules.LAG), market_cap=market_cap, enterprise_value=enterprise,
                ebitda=enterprise * earnings_yield if ebitda is None else ebitda, ebitda_yield=earnings_yield)


class Company:
    """One in-memory database as the daily cache and the research facts of company A.

    Set the attributes, then call view(): it writes them and borrows a
    facts.View. reports are statements rows; annual maps endpoint, fiscal date
    and field to a resolved state; books maps a pool to its stored latest book
    row (market_cap, metrics, filters). Every report fiscal date, the root date and
    the latest date have a price of 10. financials and treasury10 feed the
    dated owner policy. Set stale to fail the view's freshness callback.
    """

    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.executescript(research.SCHEMA + daily.DATED_SCHEMA + facts.SCHEMA)
        self.reports = [statement(f'{year}-06-30') for year in (2012, 2013, 2014)]
        self.annual = {'income-statement': {f'{year}-06-30': dict(revenue=state(100.), operatingIncome=state(income))
                                            for year, income in ((2012, -10.), (2013, 0.), (2014, 20.))}}
        self.root_date, self.latest_date = '2015-01-02', '2015-01-05'
        self.books, self.financials, self.treasury10 = {}, {}, []
        self.stale = False

    def close(self):
        self.db.close()

    def freshness(self):
        if self.stale:
            raise ValueError('Fixture attachment is stale.')

    def view(self):
        db = self.db
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            db.execute('DELETE FROM ' + table)
        db.execute("INSERT INTO companies VALUES('A','A','NYSE','Technology')")
        db.executemany('INSERT INTO statements VALUES(?,?,?,?,?,?,?)', [
            ('A', row['fiscal'], row['known'], row['market_cap'], row['enterprise_value'], row['ebitda'],
             row['ebitda_yield']) for row in self.reports])
        days = {row['fiscal'] for row in self.reports} | {self.root_date, self.latest_date}
        db.executemany('INSERT INTO prices VALUES(?,?,?,?)', [('A', day, 10., 10.) for day in sorted(days)])
        db.executemany('INSERT INTO sessions VALUES(?,?)', [(day, 100.) for day in sorted({self.root_date, self.latest_date})])
        db.execute("INSERT INTO metadata VALUES('daily_inputs',?)", (json.dumps(dict(
            inputs=dict(fixture=max(self.root_date, self.latest_date)))),))
        db.executemany('INSERT INTO financial_inputs VALUES(?,?,?)',
                       [('A', fiscal, json.dumps(values)) for fiscal, values in self.financials.items()])
        db.executemany('INSERT INTO treasury10 VALUES(?,?)', self.treasury10)
        facts.store_annual(db, 'A', dict(annual=self.annual, sources={
            endpoint: dict(endpoint=endpoint, sha256=hashlib.sha256(endpoint.encode()).hexdigest(), disposition='valid')
            for endpoint in self.annual}))
        last = self.reports[-1]
        for pool in ('legacy', 'cached'):
            facts.store_latest(db, 'A', pool, dict(admitted=True, reason=None, candidate_rank=1,
                statement=dict(fiscal=last['fiscal'], known=last['known']),
                valuation=dict(market_cap=160e6, enterprise_value=190e6, ebitda=54e6)))
        for pool, row in self.books.items():
            db.execute('INSERT INTO latest_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (pool, 'A', 1, last['fiscal'],
                last['known'], self.latest_date, 10., row['market_cap'], 190e6, .3, 3., .28))
            db.executemany('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',
                           [('latest', pool, 0, 'A', metric, *pair) for metric, pair in row['metrics'].items()])
            db.executemany('INSERT INTO filter_values VALUES(?,?,?,?,?,?)',
                           [('latest', pool, 0, 'A', name, value) for name, value in row['filters'].items()])
        scopes = [dict(mode='latest', pool=pool, context_date=self.latest_date, book=0) for pool in ('legacy', 'cached')]
        facts.finish(db, self.latest_date, inputs='fixture', scopes=scopes)
        return facts.View(db, db, self.freshness, lambda: None)


class AnnualResolutionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.raw = Path(self.folder.name)
        self.ledger = {}

    def publish(self, endpoints):
        for endpoint, rows in endpoints.items():
            financial.publish(self.raw, 'A', endpoint, rows, self.ledger, self.raw/'coverage.json')
        return financial.resolve_history(self.raw, 'A')

    def test_all_53_endpoint_fields_match_independent_oracle_and_typed_columns(self):
        rows = annual_rows()
        resolved = self.publish(rows)
        expected = {identity: (endpoint, field) for endpoint, fields in ORACLE.items()
                    for field, identity in fields.items()}
        self.assertEqual(len(expected), 53)
        self.assertEqual(financial.observation_fields(), {endpoint: tuple(fields) for endpoint, fields in ORACLE.items()})
        self.assertEqual({column: (endpoint, field) for column, endpoint, field in facts.ANNUAL},
                         {identity.split('.', 1)[1]: place for identity, place in expected.items()})
        stored = typed(resolved)
        for identity, (endpoint, field) in expected.items():
            state = resolved['annual'][endpoint]['2014-06-30'][field]
            self.assertTrue(state['valid'], identity)
            self.assertEqual(state['value'], rows[endpoint][0][field], identity)
            self.assertEqual(stored[endpoint, '2014-06-30'][identity.split('.', 1)[1]],
                             (rows[endpoint][0][field], None), identity)
            path = financial.asset_path(self.raw, 'A', endpoint)
            self.assertEqual(resolved['sources'][endpoint]['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        # Extra fields cannot leak into the established values-only projection.
        for day in resolved['values'].values():
            self.assertTrue(set(day) <= set().union(*map(set, financial.ENDPOINTS.values())))

    def test_new_malformed_fields_do_not_change_admission_completion_or_legacy_values(self):
        for value in (True, False, 'invalid', 'nan', 'inf', '-inf', [], {}, 10**500):
            with self.subTest(value=repr(value)[:20]):
                path = financial.asset_path(self.raw, 'A', 'income-statement')
                path.unlink(missing_ok=True)
                resolved = self.publish({'income-statement': [dict(date='2014-06-30',
                    reportedCurrency='USD', revenue=100, costOfRevenue=value)]})
                before = path.read_bytes()
                self.assertTrue(financial.completed(self.raw, 'A', 'income-statement', self.ledger))
                self.assertEqual(resolved['values'], {'2014-06-30': {'revenue': 100}})
                state = resolved['annual']['income-statement']['2014-06-30']['costOfRevenue']
                self.assertEqual((state['value'], state['valid'], state['reason']), (None, False, 'INVALID_INPUT'))
                row = typed(resolved)['income-statement', '2014-06-30']
                self.assertEqual((row['cost_of_revenue'], row['revenue']), ((None, 'INVALID_INPUT'), (100, None)))
                self.assertEqual(path.read_bytes(), before)

    def test_equal_null_conflicting_currency_and_missing_new_fields_are_independent(self):
        common = dict(date='2014-06-30', reportedCurrency='USD', revenue=100)
        rows = [dict(common, costOfRevenue=-12, interestIncome=0),
                dict(common, costOfRevenue=-12, interestIncome=1),
                dict(common, costOfRevenue=None),
                dict(common, reportedCurrency='EUR', costOfRevenue=999),
                dict(date='2013-06-30', reportedCurrency='EUR', costOfRevenue=10),
                dict(date='2012-06-30', costOfRevenue=10),
                dict(date='2011-06-30', reportedCurrency='USD')]
        resolved = self.publish({'income-statement': rows + [rows[0]]})
        dates = resolved['annual']['income-statement']
        self.assertEqual(dates['2014-06-30']['costOfRevenue']['value'], -12)
        self.assertEqual(dates['2014-06-30']['interestIncome']['reason'], 'CONFLICTING_INPUT')
        self.assertEqual(dates['2013-06-30']['costOfRevenue']['reason'], 'NON_USD_INPUT')
        self.assertEqual(dates['2012-06-30']['costOfRevenue']['reason'], 'MISSING_INPUT')
        self.assertEqual(dates['2011-06-30']['costOfRevenue']['reason'], 'MISSING_INPUT')
        stored = typed(resolved)
        self.assertEqual([stored['income-statement', day]['cost_of_revenue'] for day in
                          ('2014-06-30', '2013-06-30', '2012-06-30', '2011-06-30')],
                         [(-12, None), (None, 'NON_USD_INPUT'), (None, 'MISSING_INPUT'), (None, 'MISSING_INPUT')])
        self.assertEqual(stored['income-statement', '2014-06-30']['interest_income'], (None, 'CONFLICTING_INPUT'))
        again = self.publish({'income-statement': list(reversed(rows))})
        for fiscal in dates:
            for name in dates[fiscal]:
                self.assertEqual({k: v for k, v in dates[fiscal][name].items() if k != 'rows'},
                                 {k: v for k, v in again['annual']['income-statement'][fiscal][name].items() if k != 'rows'})
        self.assertEqual(typed(again), stored)

    def test_same_name_cross_endpoint_fields_never_substitute_for_cash_flow(self):
        resolved = self.publish({'income-statement': [dict(date='2014-06-30', reportedCurrency='USD',
                revenue=100, depreciationAndAmortization=999, inventory=888)],
            'balance-sheet-statement': [dict(date='2014-06-30', reportedCurrency='USD',
                inventory=5, depreciationAndAmortization=777)],
            'cash-flow-statement': [dict(date='2014-06-30', reportedCurrency='USD',
                depreciationAndAmortization=-6, inventory=666)]})
        self.assertNotIn('depreciationAndAmortization', resolved['annual']['income-statement']['2014-06-30'])
        self.assertEqual(resolved['annual']['cash-flow-statement']['2014-06-30']['depreciationAndAmortization']['value'], -6)
        self.assertEqual(resolved['annual']['balance-sheet-statement']['2014-06-30']['inventory']['value'], 5)
        self.assertEqual(resolved['sources']['income-statement']['endpoint'], 'income-statement')
        stored = typed(resolved)
        self.assertEqual(stored['income-statement', '2014-06-30']['depreciation_amortization'], (None, None))
        self.assertEqual(stored['income-statement', '2014-06-30']['inventory'], (None, None))
        self.assertEqual(stored['cash-flow-statement', '2014-06-30']['depreciation_amortization'], (-6, None))
        self.assertEqual(stored['balance-sheet-statement', '2014-06-30']['inventory'], (5, None))


class AnnualFormulaTests(unittest.TestCase):
    def setUp(self):
        self.company = Company()
        self.addCleanup(self.company.close)

    def test_company_reads_are_cached_without_whole_generation_checks(self):
        view = self.company.view()
        wanted = {'income-statement': {'revenue'}}
        queries = []
        self.company.db.set_trace_callback(queries.append)
        self.addCleanup(self.company.db.set_trace_callback, None)
        with patch.object(view, 'validate', side_effect=AssertionError('Whole-generation rescan')):
            first = view.company('A', 'legacy', wanted)
            reads = len(queries)
            for _ in range(3):
                self.assertIs(view.company('A', 'legacy', wanted), first)
            self.assertEqual(len(queries), reads)
            self.assertEqual(view.company('A', 'cached', wanted)['annual'], first['annual'])
        self.assertEqual(first['annual']['income-statement']['2013-06-30']['revenue'], state(100.))
        view.close()
        with self.assertRaisesRegex(ValueError, 'closed'):
            view.validate()

    def test_multiple_company_pools_keep_fixed_freshness_boundaries(self):
        view = self.company.view()
        program = formulas(field('annual.revenue'))
        roots = [root(pool=pool) for pool in ('legacy', 'cached')]
        for count in (1, 2):
            with patch.object(view, 'validate', wraps=view.validate) as freshness, \
                    patch.object(view, 'company', wraps=view.company) as reads:
                results = values(program, view, roots[:count])
            self.assertEqual(results, [[(100., None)]] * count)
            self.assertEqual(reads.call_count, count)
            # Admission entry and exit checks stay authoritative, independent
            # of the number of company reads.
            self.assertEqual(freshness.call_count, 2)
        self.company.stale = True
        with self.assertRaisesRegex(ValueError, 'stale'):
            values(program, view, roots)

    def test_direct_all_field_mapping_values_units_sources_and_legacy_catalog(self):
        rows = annual_rows()
        fiscal = '2014-06-30'
        self.company.annual = {endpoint: {fiscal: {name: state(records[0][name]) for name in ORACLE[endpoint]}}
                               for endpoint, records in rows.items()}
        view = self.company.view()
        places = [(endpoint, name, identity) for endpoint, fields in ORACLE.items() for name, identity in fields.items()]
        self.assertEqual(len(places), 53)
        self.assertEqual(len(columns.catalog()), 77)
        for start in range(0, len(places), 16):
            chunk = places[start:start + 16]
            program = formulas(*[field(identity) for _, _, identity in chunk])
            block = explained(program, view, [root()])
            for result, observation, (endpoint, name, identity) in zip(
                    block['results'], block['observations']['results'], chunk):
                self.assertTrue(result['valid'], identity)
                self.assertEqual(result['value'], rows[endpoint][0][name], identity)
                self.assertEqual(observation['unit'], 'share' if name in ('weightedAverageShsOut', 'weightedAverageShsOutDil')
                                 else 'USD/share' if name in ('eps', 'epsDiluted') else 'USD')
                member = observation['members'][0]
                self.assertEqual(member['fiscal_date'], fiscal)
                self.assertEqual(member['evidence']['fields'], {name: state(rows[endpoint][0][name])})
                self.assertEqual(member['evidence']['source'], dict(endpoint=endpoint,
                    sha256=hashlib.sha256(endpoint.encode()).hexdigest(), disposition='valid'))
        self.assertEqual(variable_authoring.catalog()['parameters'], columns.catalog()[:4])
        self.assertEqual([item['description'] for item in variable_authoring.catalog()['parameters']],
            ['Selected annual revenue', 'Selected annual operating income',
             'Operating income / positive revenue', 'Existing dated enterprise value'])
        self.assertEqual(variable_authoring.catalog()['displays']['share'],
                         parameters.units(parameters.V3)['share']['displays'])

    def test_exact_income_spine_preserves_missing_mismatched_newer_and_shifted_dates(self):
        income = self.company.annual['income-statement']
        income.pop('2013-06-30')
        income['2013-03-31'] = dict(revenue=state(100.), operatingIncome=state(10.))
        income['2013-12-31'] = {'revenue': state(None, 'MISSING_INPUT')}
        self.company.annual['balance-sheet-statement'] = {
            '2012-06-30': {'inventory': state(-2)},
            '2013-03-31': {'inventory': state(333)},
            '2014-06-29': {'inventory': state(444)},
            '2015-06-30': {'inventory': state(555)}}
        program = formulas(*[field(identity, count=3) for identity in
                             ('annual.revenue', 'annual.inventory', 'annual.capital_expenditure')])
        results = explained(program, self.company.view(), [root()])['observations']['results']
        self.assertEqual([[m['fiscal_date'] for m in r['members']] for r in results],
                         [['2012-06-30', '2013-12-31', '2014-06-30']] * 3)
        self.assertEqual([m['value'] for m in results[1]['members']], [-2, None, None])
        self.assertEqual([m['reason'] for m in results[1]['members']], [None, 'MISSING_INPUT', 'MISSING_INPUT'])
        self.assertEqual(results[0]['members'][1]['reason'], 'MISSING_INPUT')
        self.assertEqual([m['reason'] for m in results[2]['members']], ['MISSING_INPUT'] * 3)
        del income['2013-12-31'], income['2013-03-31']
        program = formulas(field('annual.inventory', count=3))
        missing = explained(program, self.company.view(), [root()])['observations']['results'][0]['members'][1]
        self.assertEqual((missing['fiscal_date'], missing['reason']), (None, 'MISSING_FISCAL_YEAR'))

    def test_cross_endpoint_lookback_ninety_day_and_800_day_policy(self):
        fiscal = date(2023, 12, 31)
        self.company.reports = [statement(str(fiscal))]
        self.company.annual = {'income-statement': {str(fiscal): dict(revenue=state(100.), operatingIncome=state(10.))},
                               'cash-flow-statement': {str(fiscal): {'capitalExpenditure': state(-7)}}}
        self.company.root_date = '2024-04-02'
        program = formulas(*[field('annual.capital_expenditure', wrap=dict(op='at', date=str(fiscal + timedelta(days=days))))
                             for days in (90, 91)])
        self.assertEqual(values(program, self.company.view(), [root(day=self.company.root_date)]),
                         [[(None, 'NO_ELIGIBLE_REPORT'), (-7., None)]])
        program = formulas(field('annual.capital_expenditure'))
        for age in (800, 801):
            self.company.root_date = str(fiscal + timedelta(days=age))
            [[(value, reason)]] = values(program, self.company.view(), [root(day=self.company.root_date)])
            self.assertEqual(reason is None, age == 800)
        self.company.root_date = '2024-04-02'
        # A latest root reuses prepared admission, but its own context still
        # cannot observe a future annual report.
        view = self.company.view()
        self.assertEqual(values(program, view, [root(mode='latest', day=self.company.latest_date)]),
                         [[(None, 'NO_ELIGIBLE_REPORT')]])

    def test_each_endpoint_history_is_bounded(self):
        self.company.annual['cash-flow-statement'] = {f'{year}-06-30': {'capitalExpenditure': state(-1)}
                                                      for year in (2010, 2011, 2012, 2013)}
        view = self.company.view()
        wanted = {'cash-flow-statement': {'capitalExpenditure'}}
        with patch.object(facts, 'MAX_HISTORY', 3), self.assertRaisesRegex(ValueError, 'history exceeds'):
            view.company('A', 'legacy', wanted)
        self.assertEqual(len(view.company('A', 'cached', wanted)['annual']['cash-flow-statement']), 4)

    def test_unrequested_annual_fields_are_not_read(self):
        self.company.annual['cash-flow-statement'] = {'2012-06-30': {'capitalExpenditure': state(-1)}}
        view = self.company.view()
        queries = []
        self.company.db.set_trace_callback(queries.append)
        self.addCleanup(self.company.db.set_trace_callback, None)
        self.assertEqual(values(formulas(field('annual.revenue')), view, [root()]), [[(100., None)]])
        reads = [sql for sql in queries if 'annual_facts' in sql]
        self.assertTrue(reads)
        self.assertFalse([sql for sql in queries if 'capital_expenditure' in sql or 'cash-flow' in sql])
        self.assertFalse([sql for sql in reads if 'operating_income' in sql])

    def test_cancellation_fails_the_complete_evaluation(self):
        view = self.company.view()
        roots = [root()]
        decisions = view.admit(roots)
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('private cancellation')
        with self.assertRaisesRegex(RuntimeError, 'private cancellation'):
            formulas(field('annual.revenue', count=3)).evaluate(roots, view, cancel, decisions=decisions)


def publish_all(inputs):
    """PreparedInputs configuration: one row per statement endpoint with every catalog field."""
    for endpoint, rows in annual_rows().items():
        financial.asset_path(research.RAW, 'TEST', endpoint).unlink(missing_ok=True)
        financial.publish(research.RAW, 'TEST', endpoint, rows, {}, research.RAW/'coverage.json')


class AnnualTransportTests(unittest.TestCase):
    def prepared(self):
        inputs = PreparedInputs(configure=publish_all)
        self.addCleanup(inputs.close)
        return inputs

    def test_actual_preparation_writes_typed_facts_that_formulas_read(self):
        inputs = self.prepared()
        rows = annual_rows()
        with closing(research.connect()) as original:
            self.assertEqual(facts.require(original)['version'], facts.VERSION)
            for endpoint, fields in ORACLE.items():
                stored = original.execute('SELECT * FROM annual_facts WHERE symbol=? AND endpoint=? AND fiscal=?',
                                          ('TEST', endpoint, '2014-06-30')).fetchone()
                for name, identity in fields.items():
                    column = identity.split('.', 1)[1]
                    self.assertEqual((stored[column], stored[column + '_reason']), (rows[endpoint][0][name], None))
                source = original.execute('SELECT sha256,disposition FROM fact_sources WHERE symbol=? AND endpoint=?',
                                          ('TEST', endpoint)).fetchone()
                path = financial.asset_path(research.RAW, 'TEST', endpoint)
                self.assertEqual(tuple(source), (hashlib.sha256(path.read_bytes()).hexdigest(), 'valid'))
            metrics = original.execute("SELECT multiple,yield_value FROM screening_metrics WHERE mode='latest' "
                                       "AND pool='cached' AND year=0 AND symbol='TEST' AND metric='ev_ebitda'").fetchone()
        places = [(endpoint, name, identity) for endpoint, fields in ORACLE.items() for name, identity in fields.items()]
        roots = [root('TEST', 'cached'), root('TEST', 'cached', 'latest', '2015-10-20')]
        with inputs.view() as view:
            company = view.company('TEST', 'cached', {endpoint: set(fields) for endpoint, fields in ORACLE.items()})
            for endpoint, name, _ in places:
                self.assertEqual(company['annual'][endpoint]['2014-06-30'][name], state(rows[endpoint][0][name]))
            for start in range(0, len(places), 16):
                chunk = places[start:start + 16]
                results = values(formulas(*[field(identity) for _, _, identity in chunk]), view, roots)
                for result in results:
                    self.assertEqual(result, [(rows[endpoint][0][name], None) for endpoint, name, _ in chunk])
            from backtest.variables import measures
            program = columns.Formulas(definitions.validate(measures.bundle(['ev_ebitda', 'ebitda_yield'])))
            # The latest root reads the stored latest book; the dated root
            # values the report at its entry price (20, fiscal price 10).
            self.assertEqual(values(program, view, roots[1:]), [[(metrics[0], None), (metrics[1], None)]])
            ebitda, ev = 1 / 5 * 150e6, 100e6 * (20 / 10) + (150e6 - 100e6)
            self.assertEqual(values(program, view, roots[:1]), [[(ev / ebitda, None), (ebitda / ev, None)]])

    def test_incompatible_facts_version_is_rejected_by_borrowing(self):
        inputs = self.prepared()
        with closing(sqlite3.connect(inputs.source)) as db:
            db.execute("UPDATE fact_metadata SET value='2' WHERE key='version'")
            db.commit()
            with self.assertRaisesRegex(ValueError, 'incompatible'):
                facts.require(db)
            with self.assertRaisesRegex(ValueError, 'incompatible'):
                facts.View(db, db, lambda: None, lambda: None)

    def test_research_incompatible_facts_block_downstream_fingerprints(self):
        inputs = self.prepared()
        with closing(sqlite3.connect(inputs.source)) as db:
            db.execute("UPDATE fact_metadata SET value='0' WHERE key='version'")
            db.commit()
        with self.assertRaisesRegex(ValueError, 'incompatible'):
            research.prepared_bindings(inputs.source)
        with self.assertRaisesRegex(ValueError, 'incompatible'):
            daily.fingerprint(inputs.source)

    def test_semantic_source_changes_invalidate_research_and_facts_policy(self):
        fixture = test_prepared_facts.ProjectionTests('test_complete_chain_preserves_evidence_dates_and_latest_valuation')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        policy = facts.policy_binding()
        self.assertIn('parameters.py', policy)
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/'parameters.py'
            file.write_bytes(Path(parameters.__file__).read_bytes()+b'\n# private semantic change\n')
            # The binding is hashed once per process; a new process sees the edit.
            self.addCleanup(facts._policy_binding.cache_clear)
            with patch.object(parameters, '__file__', str(file)):
                facts._policy_binding.cache_clear()
                self.assertNotEqual(facts.policy_binding()['parameters.py'], policy['parameters.py'])
            facts._policy_binding.cache_clear()
        # Signature must include the actual semantic source as an independent
        # dependency, even when financial resolver source remains unchanged.
        with ExitStack() as context:
            modules = (research, research.metrics, research.books, research.rules, research.cache_assets,
                research.market, financial, parameters, facts)
            for module in modules:
                file = research.ROOT/Path(module.__file__).name
                file.write_bytes(Path(module.__file__).read_bytes())
                context.enter_context(patch.object(module, '__file__', str(file)))
            before = fixture.real_signature()
            file = Path(parameters.__file__)
            file.write_bytes(file.read_bytes()+b'\n# semantic change\n')
            self.assertNotEqual(fixture.real_signature(), before)


if __name__ == '__main__': unittest.main()
