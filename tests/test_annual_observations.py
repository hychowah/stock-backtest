"""Phase 9 annual evidence: independent inventory, endpoint joins and transport.

Synthetic files live in TemporaryDirectory (the source-bound runner places it
outside the checkout). No expected legacy or Phase 8 immutable bytes are written.
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
from unittest.mock import Mock, patch

from backtest import observations as provider
from backtest.application import variable_authoring
from backtest.inputs import financial_inputs as financial, observation_inputs as source
from backtest.inputs import daily, research, sqlite_observations
from backtest.engines.numerical import generation
from backtest.variables import parameters
from test_parameter_contract import ORACLE as DIRECT_ORACLE
ORACLE = {endpoint: fields for endpoint, fields in DIRECT_ORACLE.items()
          if all(identity.startswith('annual.') for identity in fields.values())}
import test_observations as provider_fixtures
import test_observation_inputs as input_fixtures


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

    def test_all_48_endpoint_fields_match_independent_oracle_and_units(self):
        rows = annual_rows()
        resolved = self.publish(rows)
        expected = {identity: (endpoint, field) for endpoint, fields in ORACLE.items()
                    for field, identity in fields.items()}
        self.assertEqual(len(expected), 48)
        self.assertEqual(financial.observation_fields(), {endpoint: tuple(fields) for endpoint, fields in ORACLE.items()})
        for identity, (endpoint, field) in expected.items():
            state = resolved['annual'][endpoint]['2014-06-30'][field]
            self.assertTrue(state['valid'], identity)
            self.assertEqual(state['value'], rows[endpoint][0][field], identity)
            self.assertEqual(state['rows'][0]['index'], 0)
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
                self.assertIsNone(state['rows'][0]['value'])
                source.encoded(resolved)
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
        self.assertEqual(len(dates['2014-06-30']['costOfRevenue']['rows']), 5)
        self.assertEqual(dates['2014-06-30']['interestIncome']['reason'], 'CONFLICTING_INPUT')
        self.assertEqual(dates['2013-06-30']['costOfRevenue']['reason'], 'NON_USD_INPUT')
        self.assertEqual(dates['2012-06-30']['costOfRevenue']['reason'], 'MISSING_INPUT')
        self.assertEqual(dates['2011-06-30']['costOfRevenue']['reason'], 'MISSING_INPUT')
        again = self.publish({'income-statement': list(reversed(rows))})
        for fiscal in dates:
            for field in dates[fiscal]:
                self.assertEqual({k:v for k,v in dates[fiscal][field].items() if k != 'rows'},
                                 {k:v for k,v in again['annual']['income-statement'][fiscal][field].items() if k != 'rows'})

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


class AnnualProviderTests(unittest.TestCase):
    def setUp(self):
        self.fixture = provider_fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.extra = {}

    def view(self):
        view = self.fixture.view()
        for endpoint, dates in self.extra.items():
            self.fixture.db.execute('INSERT INTO observation_sources VALUES(?,?,?)',
                ('A', endpoint, source.encoded(dict(endpoint=endpoint, disposition='valid', sha256='c'*64))))
            for fiscal, fields in dates.items():
                self.fixture.db.execute('INSERT INTO observation_annual VALUES(?,?,?,?)',
                    ('A', endpoint, fiscal, source.encoded(fields)))
        self.fixture.db.execute('DELETE FROM observation_metadata')
        view._expected = source.finish(self.fixture.db, self.fixture.latest_date)
        view._bounds['max_annual'] += sum(map(len, self.extra.values()))
        return view

    def observe(self, requests, contexts=None, **limits):
        return provider.observe(provider.plan(requests, contexts or self.fixture.contexts(), limits or None), self.view()).to_dict()

    def request(self, identity, count=1, context='root'):
        return self.fixture.request(identity, count, context, identity+':'+context)

    def test_company_reads_do_not_repeat_whole_generation_admission(self):
        view = self.view()
        with patch.object(view, '_validate', side_effect=AssertionError('Whole-generation rescan')):
            first = view.company('A', 'legacy')
            for _ in range(3):
                self.assertEqual(view.company('A', 'legacy'), first)
            self.assertEqual(view.company('A', 'cached')['annual'], first['annual'])
        view.close()
        with self.assertRaisesRegex(ValueError, 'closed'):
            view.company('A', 'legacy')

    def test_multiple_company_pools_keep_fixed_observation_freshness_boundaries(self):
        view = self.view()
        freshness = Mock(wraps=view._validate)
        view._validate = freshness
        contexts = [dict(self.fixture.contexts()[0], id=pool, pool=pool)
                    for pool in ('legacy', 'cached')]
        for count in (1, 2):
            freshness.reset_mock()
            roots = contexts[:count]
            requests = [self.request('annual.revenue', context=root['id']) for root in roots]
            with patch.object(view, 'company', wraps=view.company) as reads:
                block = provider.observe(provider.plan(requests, roots), view).to_dict()
            self.assertTrue(all(result['valid'] for result in block['results']))
            self.assertEqual(reads.call_count, count)
            # Initial/final observation checks and initial/final admission checks
            # remain authoritative, independent of the number of company reads.
            self.assertEqual(freshness.call_count, 4)
        self.fixture.stale = True
        with self.assertRaisesRegex(ValueError, 'stale'):
            provider.observe(provider.plan(requests, roots), view)

    def test_direct_all_field_mapping_values_units_receipts_and_unchanged_picker(self):
        rows = annual_rows()
        fiscal = '2014-06-30'
        for endpoint, records in rows.items():
            fields = {field: provider_fixtures.state(records[0][field]) for field in ORACLE[endpoint]}
            if endpoint == 'income-statement': self.fixture.annual[fiscal] = fields
            else: self.extra[endpoint] = {fiscal: fields}
        ids = [identity for fields in ORACLE.values() for identity in fields.values()]
        results = self.observe([self.request(identity) for identity in ids])['results']
        self.assertEqual(len(provider.catalog()), 50)
        self.assertEqual(len(results), 48)
        for result, (endpoint, field) in zip(results, [(e,f) for e,fs in ORACLE.items() for f in fs]):
            self.assertTrue(result['valid'], result['parameter'])
            self.assertEqual(result['members'][0]['value'], rows[endpoint][0][field])
            self.assertEqual(result['unit'], 'share' if field in ('weightedAverageShsOut','weightedAverageShsOutDil') else 'USD')
            self.assertEqual(result['members'][0]['fiscal_date'], fiscal)
            self.assertEqual(result['members'][0]['evidence']['fields'][field]['rows'][0]['index'], 0)
        self.assertEqual(variable_authoring.catalog()['parameters'], provider.catalog()[:4])
        self.assertEqual([item['description'] for item in variable_authoring.catalog()['parameters']],
            ['Selected annual revenue', 'Selected annual operating income',
             'Operating income / positive revenue', 'Existing dated enterprise value'])
        self.assertNotIn('share', variable_authoring.catalog()['displays'])

    def test_exact_income_spine_preserves_missing_mismatched_newer_and_shifted_dates(self):
        self.fixture.annual.pop('2013-06-30')
        self.fixture.annual['2013-03-31'] = provider_fixtures.annual()
        self.fixture.annual['2013-12-31'] = {'revenue': provider_fixtures.state(None, 'MISSING_INPUT')}
        self.extra = {'balance-sheet-statement': {
            '2012-06-30': {'inventory': provider_fixtures.state(-2)},
            '2013-03-31': {'inventory': provider_fixtures.state(333)},
            '2014-06-29': {'inventory': provider_fixtures.state(444)},
            '2015-06-30': {'inventory': provider_fixtures.state(555)}}}
        requests = [self.request('annual.revenue', 3), self.request('annual.inventory', 3),
                    self.request('annual.capital_expenditure', 3)]
        with patch.object(provider, '_periods', wraps=provider._periods) as periods:
            results = self.observe(requests)['results']
        self.assertEqual(periods.call_count, 1)
        self.assertEqual([[m['fiscal_date'] for m in r['members']] for r in results],
                         [['2012-06-30','2013-12-31','2014-06-30']] * 3)
        self.assertEqual([m['value'] for m in results[1]['members']], [-2,None,None])
        self.assertEqual([m['reason'] for m in results[1]['members']], [None,'MISSING_INPUT','MISSING_INPUT'])
        self.assertEqual(results[0]['members'][1]['reason'], 'MISSING_INPUT')
        del self.fixture.annual['2013-12-31']; del self.fixture.annual['2013-03-31']
        missing = self.observe([self.request('annual.inventory', 3)])['results'][0]['members'][1]
        self.assertEqual((missing['fiscal_date'],missing['reason']), (None,'MISSING_FISCAL_YEAR'))

    def test_cross_endpoint_lookback_ninety_day_and_800_day_policy(self):
        fiscal = date(2023,12,31)
        self.fixture.reports = [provider_fixtures.statement(str(fiscal))]
        self.fixture.annual = {str(fiscal): provider_fixtures.annual()}
        self.extra = {'cash-flow-statement': {str(fiscal): {'capitalExpenditure': provider_fixtures.state(-7)}}}
        self.fixture.root_date = '2024-04-02'
        contexts = self.fixture.contexts()+[
            dict(id='equal',kind='at',parent='root',date=str(fiscal+timedelta(days=90))),
            dict(id='after',kind='at',parent='root',date=str(fiscal+timedelta(days=91)))]
        results = self.observe([self.request('annual.capital_expenditure',context=name) for name in ('equal','after')],contexts)['results']
        self.assertEqual(results[0]['reason'], 'NO_ELIGIBLE_REPORT')
        self.assertEqual(results[1]['members'][0]['value'], -7)
        for age in (800,801):
            self.fixture.root_date = str(fiscal+timedelta(days=age))
            result = self.observe([self.request('annual.capital_expenditure')])['results'][0]
            self.assertEqual(result['valid'], age == 800)
        self.fixture.root_date = '2024-04-02'
        contexts = [dict(self.fixture.contexts()[0], mode='latest',date=self.fixture.latest_date)]
        # A latest root reuses prepared admission, but its own context still
        # cannot observe a future annual report.
        self.assertEqual(self.observe([self.request('annual.capital_expenditure')],contexts)['results'][0]['reason'], 'NO_ELIGIBLE_REPORT')

    def test_preflight_counts_every_endpoint_before_company_reads(self):
        self.extra = {'balance-sheet-statement': {f'{year}-06-30': {'inventory': provider_fixtures.state(1)} for year in (2012,2013,2014)},
                      'cash-flow-statement': {f'{year}-06-30': {'capitalExpenditure': provider_fixtures.state(-1)} for year in (2012,2013,2014)}}
        view = self.view()
        self.assertEqual(view.bounds['max_annual'], 9)
        bounds = view.bounds
        exact = 2*(bounds['report_rows']+bounds['population'])+1+2*bounds['max_reports']+2*bounds['max_annual']+7
        request = self.request('annual.inventory')
        self.assertTrue(provider.observe(provider.plan([request],self.fixture.contexts(),{'rows':exact}),view).to_dict()['results'][0]['valid'])
        with patch.object(view,'company',side_effect=AssertionError('No company read')):
            with self.assertRaises(provider.ObservationError):
                provider.observe(provider.plan([request],self.fixture.contexts(),{'rows':exact-1}),view)

    def test_each_endpoint_history_record_and_total_company_bytes_are_bounded(self):
        self.extra = {'cash-flow-statement': {f'{year}-06-30': {'capitalExpenditure': provider_fixtures.state(-1)} for year in (2010,2011,2012,2013)}}
        view = self.view()
        view.max_history = 3
        with self.assertRaisesRegex(ValueError,'history exceeds'): view.company('A','legacy')
        view.max_history = 16384
        facts = view.company('A','legacy')
        size = len(source.encoded(facts).encode())
        self.assertEqual(view.company('A','legacy',budget={'bytes':size}),facts)
        with self.assertRaisesRegex(ValueError,'byte bound'): view.company('A','legacy',budget={'bytes':size-1})
        view.max_record_bytes = 10
        with self.assertRaisesRegex(ValueError,'record exceeds'): view.company('A','legacy')

    def test_unrequested_cash_flow_history_counts_toward_bytes_before_decode(self):
        self.extra = {'cash-flow-statement': {'2012-06-30': {'capitalExpenditure':
            dict(provider_fixtures.state(-1), rows=[dict(index=index,sha256='d'*64) for index in range(1000)])}}}
        view = self.view()
        with patch.object(view,'_json',wraps=view._json) as decoded:
            with self.assertRaisesRegex(ValueError,'company facts exceed'):
                provider.observe(provider.plan([self.request('annual.revenue')],self.fixture.contexts(),{'bytes':10000}),view)
            # Income/balance order is irrelevant: the large cash-flow record
            # itself must fail the aggregate allowance before JSON decoding.
            self.assertFalse(any(len(call.args[0]) > 10000 for call in decoded.call_args_list))

    def test_unknown_endpoint_and_cancellation_fail_the_complete_company(self):
        self.extra = {'unrecognized-endpoint': {'2014-06-30': {}}}
        view = self.view()
        with self.assertRaisesRegex(ValueError,'history exceeds'): view.company('A','legacy')
        self.extra = {'cash-flow-statement': {'2014-06-30': {'capitalExpenditure':provider_fixtures.state(-1)}}}
        view = self.view()
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls == 2: raise RuntimeError('private cancellation')
        with self.assertRaisesRegex(RuntimeError,'private cancellation'):
            view.company('A','legacy',checkpoint=cancel)


class AnnualTransportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = input_fixtures.ProjectionTests('test_complete_chain_preserves_evidence_dates_and_latest_valuation')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        research.signature.return_value['historical_through'] = '2015-10-20'
        self.rows = annual_rows()
        for endpoint, rows in self.rows.items():
            financial.asset_path(research.RAW,'TEST',endpoint).unlink(missing_ok=True)
            financial.publish(research.RAW,'TEST',endpoint,rows,{},research.RAW/'coverage.json')

    def test_actual_research_daily_sqlite_and_generation_share_all_endpoint_facts(self):
        self.fixture.prepare()
        ordinary_daily, ordinary_research = daily.connect, research.connect
        store = generation.GenerationStore(self.fixture.source.parent/'annual-numerical',
            generation.cache_access.WorkspaceAccess(self.fixture.source.parent/'annual.lock'))
        with patch.object(daily,'connect',side_effect=lambda: ordinary_daily(self.fixture.path,self.fixture.source)), \
             patch.object(research,'connect',side_effect=lambda path=self.fixture.source,**kw: ordinary_research(path,**kw)):
            receipt = store.prepare()
            with closing(ordinary_research(self.fixture.source)) as original, \
                 closing(ordinary_daily(self.fixture.path,self.fixture.source)) as copied, \
                 store.open_current() as attachment:
                with sqlite_observations.prepared_view(copied,lambda:None) as sqlview, attachment.observations() as numview:
                    self.assertEqual(source.require(original,verify_content=True)['version'],2)
                    self.assertEqual(sqlview.company('TEST','cached'),numview.company('TEST','cached'))
                    facts = numview.company('TEST','cached')
                    for endpoint, fields in ORACLE.items():
                        for field in fields:
                            self.assertEqual(facts['annual'][endpoint]['2014-06-30'][field]['value'],self.rows[endpoint][0][field])
                    for table in source.TABLES:
                        self.assertEqual([tuple(row) for row in original.execute('SELECT * FROM '+table)],
                                         [tuple(row) for row in attachment._db.execute('SELECT * FROM '+table)])
                    contexts = [dict(id='root',kind='root',symbol='TEST',pool='cached',mode='historical',date='2015-01-02'),
                                dict(id='latest',kind='root',symbol='TEST',pool='cached',mode='latest',date='2015-10-20')]
                    requests = [dict(id=f'{context}:{identity}',parameter=identity,context=context,count=1)
                        for context in ('root','latest') for fields in ORACLE.values() for identity in fields.values()]
                    planned = provider.plan(requests,contexts)
                    sqlresults = provider.observe(planned,sqlview).to_dict()
                    numresults = provider.observe(planned,numview).to_dict()
                    self.assertEqual(sqlresults['results'],numresults['results'])
                    self.assertTrue(all(result['valid'] for result in numresults['results']))
                    self.assertEqual(numview.identity,receipt['identity'])
                    detached = source.encoded(facts)
                attachment.close()
                with self.assertRaisesRegex(ValueError,'closed'): numview.company('TEST','cached')
                self.assertEqual(source.encoded(facts),detached)

    def test_version_one_is_rejected_by_daily_copy_borrowing_and_numerical_preparation(self):
        self.fixture.prepare()
        with closing(sqlite3.connect(self.fixture.path)) as db:
            db.execute("UPDATE observation_metadata SET value='1' WHERE key='version'");db.commit()
            with self.assertRaisesRegex(ValueError,'incompatible'): source.require(db,verify_content=True)
            with self.assertRaisesRegex(ValueError,'incompatible'): sqlite_observations.prepared_view(db,lambda:None)
            target = sqlite3.connect(':memory:'); self.addCleanup(target.close); target.executescript(source.SCHEMA)
            with self.assertRaisesRegex(ValueError,'incompatible'): source.copy(db,target)
            self.assertEqual(target.execute('SELECT count(*) FROM observation_annual').fetchone()[0],0)
        ordinary_daily, ordinary_research = daily.connect, research.connect
        store = generation.GenerationStore(self.fixture.source.parent/'old-projection',
            generation.cache_access.WorkspaceAccess(self.fixture.source.parent/'old.lock'))
        # A real numerical preparation rejects the mismatching daily evidence.
        with patch.object(daily,'connect',side_effect=lambda: ordinary_daily(self.fixture.path,self.fixture.source)), \
             patch.object(research,'connect',side_effect=lambda path=self.fixture.source,**kw: ordinary_research(path,**kw)):
            with self.assertRaisesRegex(ValueError,'incompatible'): store.prepare()
        self.assertFalse((store.path/'current.json').exists())

    def test_research_version_one_projection_blocks_downstream_fingerprints(self):
        self.fixture.prepare()
        with closing(sqlite3.connect(self.fixture.source)) as db:
            db.execute("UPDATE observation_metadata SET value='1' WHERE key='version'"); db.commit()
        with self.assertRaisesRegex(ValueError,'incompatible'):
            research.prepared_observation_binding(self.fixture.source)
        with self.assertRaisesRegex(ValueError,'incompatible'):
            daily.fingerprint(self.fixture.source)

    def test_semantic_source_changes_invalidate_research_and_observation_policy(self):
        policy = source.policy_binding()
        self.assertIn('parameters.py',policy)
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/'parameters.py'
            file.write_bytes(Path(parameters.__file__).read_bytes()+b'\n# private semantic change\n')
            with patch.object(parameters,'__file__',str(file)):
                self.assertNotEqual(source.policy_binding()['parameters.py'],policy['parameters.py'])
        # Signature must include the actual semantic source as an independent
        # dependency, even when financial resolver source remains unchanged.
        actual_signature = self.fixture.real_signature
        with ExitStack() as context:
            modules = (research, research.baseline, research.metrics, research.books, research.rules,
                research.screening, research.selection, research.cache_assets, research.market,
                research.legacy,research.revalue,financial,source,parameters)
            source_folder = Path(research.__file__).parent
            for module in modules:
                file = research.ROOT/Path(module.__file__).name
                file.write_bytes(Path(module.__file__).read_bytes())
                context.enter_context(patch.object(module,'__file__',str(file)))
            for name in ('legacy_downloads.py','fmp_download.py','daily.py'):
                (research.ROOT/name).write_bytes((source_folder/name).read_bytes())
            before = actual_signature()
            file = Path(parameters.__file__); file.write_bytes(file.read_bytes()+b'\n# semantic change\n')
            self.assertNotEqual(actual_signature(),before)


if __name__ == '__main__': unittest.main()
