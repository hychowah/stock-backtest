"""Frozen cases where a numerical generation hosts observations or trial evidence.

These cases moved out of live test files when the experimental engine was
frozen (AGENTS.md, Tests). The live files keep the daily SQLite host. No tier
runs this file; run it directly with tmp/numerical-venv when unfreezing.
"""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from contextlib import ExitStack, closing
from copy import deepcopy
from datetime import date
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from backtest import observations as obs, observations as provider, result_evidence
from backtest.application import jobs as backtest_jobs, library as saved, queue
from backtest.financial import books
from backtest.inputs import daily, research, sqlite_observations
from backtest.inputs import dated_observation_inputs as dated
from backtest.inputs import financial_inputs as financial, observation_inputs as observed
from backtest.inputs import observation_inputs as source
from backtest.engines.numerical import generation
from backtest.variables import definitions, reference, parameters
import test_annual_observations as annual
from test_annual_observations import ORACLE
import test_durable_evidence as durable_tests
import test_numerical_generation as generation_fixtures
import test_observation_inputs as input_fixtures
import test_result_evidence as codec
from test_variable_definitions import entry, definition, root, bundle


class ProjectionGenerationTests(unittest.TestCase):
    def setUp(self):
        projection = input_fixtures.ProjectionTests('test_complete_chain_preserves_evidence_dates_and_latest_valuation')
        projection.setUp()
        self.addCleanup(projection.doCleanups)
        self.source, self.path, self.prepare = projection.source, projection.path, projection.prepare

    def test_real_preparation_through_immutable_generation_and_pending_guard(self):
        self.prepare()
        ordinary_connect = daily.connect
        ordinary_research_connect = research.connect
        store = generation.GenerationStore(self.source.parent/'numerical',
            generation.cache_access.WorkspaceAccess(self.source.parent/'fixture.lock'))
        with patch.object(daily, 'connect', side_effect=lambda: ordinary_connect(self.path, self.source)), \
             patch.object(research, 'connect', side_effect=lambda path=self.source, **kw: ordinary_research_connect(path, **kw)):
            receipt = store.prepare()
            with store.open_current() as attached:
                with attached.observations() as view:
                    self.assertEqual(view.identity, receipt['identity'])
                    facts = view.company('TEST', 'legacy')
                    self.assertTrue(facts['latest']['admitted'])
                    self.assertEqual(facts['annual']['income-statement']['2013-06-30']['operatingIncome']['value'], -5e6)
                    self.assertEqual(view.lookup('TEST', date(2015, 10, 20), 'adjusted', False, 0),
                                     (date(2015, 10, 20), 22))
            marker = self.source.parent/'research.sqlite.publication.json'
            marker.write_text('{}')
            try:
                with self.assertRaisesRegex(ValueError, 'Unfinished publication'):
                    store.open_current()
            finally:
                marker.unlink()


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = generation_fixtures.GenerationTests('test_export_values_order_missingness_and_mutable_books_reuse')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.db, self.binding = self.fixture.db, self.fixture.binding
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder)
            financial.publish(raw, 'A', 'income-statement', [
                dict(date='2014-06-30', reportedCurrency='USD', revenue=100, operatingIncome=-5),
                dict(date='2013-06-30', reportedCurrency='USD', revenue=None)], {}, raw/'coverage.json')
            observed.store_annual(self.db, 'A', financial.resolve_history(raw, 'A'))
        for pool in ('legacy', 'cached'):
            observed.store_latest(self.db, 'A', pool, dict(admitted=True, root_date='2016-12-30'))
        self.binding['observations'] = observed.finish(self.db, '2016-12-30')
        self.db.commit()

    def test_generation_copy_borrowed_view_detachment_prices_and_closure(self):
        self.fixture.prepare()
        attached = self.fixture.attach()
        view = attached.observations()
        self.addCleanup(view.close)
        company = view.company('A', 'legacy')
        self.assertEqual(company['annual']['income-statement']['2014-06-30']['operatingIncome']['value'], -5)
        self.assertIn('2013-06-30', company['annual']['income-statement'])
        for table in observed.TABLES:
            self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM '+table)],
                             [tuple(row) for row in attached._db.execute('SELECT * FROM '+table)])
        # Price lookup uses the identical stored series, date and tolerance.
        for column in ('price', 'adjusted'):
            for forward in (False, True):
                for day in (date(2015, 1, 1), date(2015, 1, 2), date(2015, 1, 5)):
                    self.assertEqual(view.lookup('A', day, column, forward, 4),
                                     daily.price(self.db, 'A', day, column, forward, 4))
        detached = observed.encoded(company)
        view.close(); attached.close()
        self.assertEqual(observed.encoded(company), detached)
        with self.assertRaisesRegex(ValueError, 'closed'): view.validate()
        with self.assertRaisesRegex(ValueError, 'closed'): view.company('A', 'legacy')

    def test_missing_projection_stale_generation_and_closed_attachment_reject(self):
        self.fixture.prepare(); attached = self.fixture.attach()
        view = attached.observations(); self.addCleanup(view.close)
        self.binding['prices'] = {'changed': True}
        with self.assertRaisesRegex(ValueError, 'stale'): view.validate()
        attached.close()
        with self.assertRaisesRegex(ValueError, 'closed'): attached.observations()
        self.db.execute('DELETE FROM observation_metadata'); self.db.commit()
        self.binding.pop('observations'); self.fixture.prepare()
        missing = self.fixture.attach()
        with self.assertRaisesRegex(ValueError, 'no admitted'): missing.observations()

    def test_export_cancellation_preserves_current_generation(self):
        first = self.fixture.prepare()
        self.binding['prices'] = {'changed': True}
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls > 5: raise RuntimeError('fixture cancellation')
        with self.assertRaisesRegex(RuntimeError, 'fixture cancellation'):
            self.fixture.store.prepare(checkpoint=cancel)
        self.assertEqual(self.fixture.store._pointer()['current'], first['identity'])

    def test_observation_record_byte_boundary_rejects_before_publication(self):
        row = self.db.execute("SELECT * FROM observation_annual WHERE fiscal='2014-06-30'").fetchone()
        size = sum(len(value.encode('utf-8')) for value in row)
        # Valid JSON whitespace changes only its byte size, not its source facts.
        boundary = row[-1] + ' ' * (generation.MAX_MANIFEST - size)
        def replace(text):
            self.db.execute("UPDATE observation_annual SET evidence_json=? WHERE fiscal='2014-06-30'", (text,))
            self.db.execute('DELETE FROM observation_metadata')
            self.binding['observations'] = observed.finish(self.db, '2016-12-30')
            self.db.commit()
        replace(boundary)
        first = self.fixture.prepare()
        with self.fixture.store.open_current() as attached:
            with attached.observations() as view:
                self.assertEqual(view.company('A', 'legacy')['annual']['income-statement']['2014-06-30'], json.loads(row[-1]))
        pointer = self.fixture.store._pointer()
        replace(boundary + ' ')
        with self.assertRaisesRegex(ValueError, 'observation record exceeds its byte bound'):
            self.fixture.prepare()
        self.assertEqual(self.fixture.store._pointer(), pointer)
        self.assertEqual(pointer['current'], first['identity'])
        self.assertEqual(list(self.fixture.store.path.glob('building-*')), [])
        self.assertFalse((self.fixture.store.path/'publication.json').exists())


class GenerationAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = AttachmentTests('test_generation_copy_borrowed_view_detachment_prices_and_closure')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.db, self.binding = self.fixture.db, self.fixture.binding
        self.binding['daily'] = dict(inputs=dict(historical_through='2016-12-30'))

    def test_complete_population_buffer_order_and_uncached_names_survive_generation(self):
        for index in range(260):
            symbol = f'Z{index:03d}'
            self.db.execute('INSERT INTO companies VALUES(?,?,?,?)', (symbol, symbol, 'NYSE', 'Energy'))
            self.db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',
                (symbol, '2014-06-30', '2014-09-28', 150e6, 180e6, 162e6, .9))
            if index >= 10:
                self.db.executemany('INSERT INTO prices VALUES(?,?,?,?)',
                    [(symbol, day, 10., 10.) for day in ('2014-06-30', '2015-01-02')])
        self.db.commit()
        expected_books = daily.histories(self.db)
        expected_selected, expected_ranks = books.candidates(expected_books, date(2015, 1, 2))
        self.fixture.fixture.prepare()
        with self.fixture.fixture.store.open_current() as attached, attached.observations() as view:
            roots = [dict(id=symbol+pool, kind='root', symbol=symbol, pool=pool, mode='historical', date='2015-01-02')
                     for symbol, pool in (('Z249', 'legacy'), ('Z250', 'legacy'), ('Z005', 'legacy'), ('Z250', 'cached'))]
            requests = [dict(id=root['id'], parameter='market.enterprise_value', context=root['id'], count=1) for root in roots]
            block = obs.observe(obs.plan(requests, roots), view).to_dict()
            decisions = block['roots']
            self.assertEqual([item['admitted'] for item in decisions], [True, False, False, True])
            self.assertEqual(decisions[0]['candidate_rank'], expected_ranks['Z249'])
            self.assertEqual(decisions[0]['candidate_rank'], 250)
            self.assertEqual(decisions[1]['reason'], 'OUTSIDE_LEGACY_BUFFER')
            self.assertEqual(decisions[2]['reason'], 'MISSING_CACHED_PRICES')
            valuation = books.entry_valuation(expected_selected['legacy']['Z249'], date(2015, 1, 2),
                lambda day, column, forward, slack: daily.price(self.db, 'Z249', day, column, forward, slack))
            self.assertEqual(decisions[0]['valuation']['enterprise_value'], valuation[3])
            # A request containing only the low-ranked cached name cannot promote it.
            alone = obs.observe(obs.plan([requests[1]], [roots[1]]), view).to_dict()
            self.assertFalse(alone['roots'][0]['admitted'])


class AnnualGenerationTransportTests(unittest.TestCase):
    setUp = annual.AnnualTransportTests.setUp

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
                    self.assertEqual(source.require(original,verify_content=True)['version'],4)
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
                    from backtest.variables import definitions, measures, reference
                    program = definitions.validate(measures.bundle(['ev_ebitda','ebitda_yield']))
                    root = dict(symbol='TEST',pool='cached',mode='historical',date='2015-01-02')
                    plan = reference.plan(program, [root])
                    sqlresult = reference.evaluate(plan, sqlview).to_dict()['results']
                    numresult = reference.evaluate(plan, numview).to_dict()['results']
                    self.assertEqual(sqlresult, numresult)
                    stored = original.execute("SELECT multiple,yield_value FROM screening_metrics WHERE mode='historical' AND pool='cached' AND year=2015 AND symbol='TEST' AND metric='ev_ebitda'").fetchone()
                    self.assertEqual([item['value'] for item in sqlresult], list(stored))
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


class GenerationTransportTests(unittest.TestCase):
    def setUp(self):
        self.fixture=annual.AnnualTransportTests('test_actual_research_and_daily_sqlite_share_all_endpoint_facts')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.owner=self.fixture.fixture
        self.path=research.RAW/'px/TEST.json'
        payload=json.loads(self.path.read_text())
        for row in payload['div']:row['volume']=12.5
        self.path.write_text(json.dumps(payload))
        treasury=json.loads((research.RAW/'treasury.json').read_text())
        for row in treasury:row['year10']=-1
        (research.RAW/'treasury.json').write_text(json.dumps(treasury))

    def views(self):
        self.owner.prepare()
        stack=ExitStack();self.addCleanup(stack.close)
        ordinary_daily,ordinary_research=daily.connect,research.connect
        store=generation.GenerationStore(self.owner.source.parent/'dated-numerical',
              generation.cache_access.WorkspaceAccess(self.owner.source.parent/'dated.lock'))
        stack.enter_context(patch.object(daily,'connect',side_effect=lambda:ordinary_daily(self.owner.path,self.owner.source)))
        stack.enter_context(patch.object(research,'connect',side_effect=lambda path=self.owner.source,**kw:ordinary_research(path,**kw)))
        store.prepare()
        self.db=stack.enter_context(closing(ordinary_daily(self.owner.path,self.owner.source)))
        self.attached=stack.enter_context(store.open_current())
        return stack.enter_context(sqlite_observations.prepared_view(self.db,lambda:None)),stack.enter_context(self.attached.observations())

    def contexts(self):
        return [dict(id='root',kind='root',symbol='TEST',pool='cached',mode='historical',date='2015-01-02'),
                dict(id='latest',kind='root',symbol='TEST',pool='cached',mode='latest',date='2015-10-20')]

    def observe(self,view,ids,contexts=None,context='root',limits=None):
        requests=[dict(id=str(i),parameter=identity,context=context,count=1) for i,identity in enumerate(ids)]
        return provider.observe(provider.plan(requests,contexts or self.contexts(),limits),view).to_dict()

    def _assert_spy_wrapper(self, key):
        spy = research.RAW/'spy-div.json'
        rows = json.loads(spy.read_bytes())
        payload = ({'historical': rows, 'data': [dict(date='2099-01-01', adjClose=999)]}
                   if key == 'historical' else {'historical': [], 'data': rows})
        spy.write_text(json.dumps(payload))
        digest = hashlib.sha256(spy.read_bytes()).hexdigest()
        (research.RAW/'download-coverage.json').write_text(json.dumps({'spy-div.json': dict(sha256=digest, windows=[])}))
        sql, num = self.views()
        for view in (sql, num):
            receipt = view.source('', dated.CALENDAR)
            self.assertEqual(receipt['sha256'], digest)
            self.assertIsNone(receipt['receipt'])
            self.assertEqual(view.session_backward(date(2015,1,2),7)['day'], '2015-01-02')
            results = self.observe(view, ['market.adjusted_price','market.volume'])['results']
            self.assertTrue(all(result['valid'] for result in results))
            self.assertEqual(results[1]['members'][0]['value'], 12.5)
        self.assertEqual(json.loads(spy.read_bytes()), payload)

    def test_retained_historical_spy_wrapper_prepares_sessions_without_false_receipt(self):
        self._assert_spy_wrapper('historical')

    def test_retained_data_spy_wrapper_prepares_sessions_without_false_receipt(self):
        self._assert_spy_wrapper('data')

    def test_actual_full_record_boundary_survives_daily_and_numerical_or_preserves_research(self):
        payload = json.loads(self.path.read_bytes())
        rows = []
        for row in payload['div']:
            rows.extend([row] * (64 if row['date'] == '2015-01-02' else 1))
        payload['div'] = rows
        self.path.write_text(json.dumps(payload))
        facts = dated.stock(research.RAW, 'TEST', {})
        exact = max(source.record_bytes(('TEST', dated.STOCK, day, source.encoded(states)))
                    for day, states in facts['dated'].items())
        with patch.object(dated, 'MAX_RECORD_BYTES', exact):
            sql, num = self.views()
            for view in (sql, num):
                self.assertTrue(self.observe(view, ['market.adjusted_price','market.volume'])['results'][1]['valid'])
        before = self.owner.source.read_bytes()
        with patch.object(dated, 'MAX_RECORD_BYTES', exact-1), self.assertRaisesRegex(ValueError, 'byte bound'):
            research.prepare(self.owner.source, force=True)
        self.assertEqual(self.owner.source.read_bytes(), before)
        self.assertFalse(self.owner.source.with_name(self.owner.source.name+'.building').exists())

    def test_actual_matching_previous_receipt_survives_complete_projection_transport(self):
        digest=hashlib.sha256(self.path.read_bytes()).hexdigest()
        treasury=research.RAW/'treasury.json';tdigest=hashlib.sha256(treasury.read_bytes()).hexdigest()
        ledger={'px/TEST.json':dict(sha256='a'*64,previous=dict(sha256=digest,windows=[['2015-01-01','2015-10-20']])),
                'treasury.json':dict(sha256=tdigest,windows=[])}
        (research.RAW/'download-coverage.json').write_text(json.dumps(ledger))
        sql,num=self.views()
        for view in (sql,num):
            self.assertEqual(view.source('TEST',dated.STOCK)['receipt']['sha256'],digest)
            self.assertEqual(view.source('',dated.TREASURY)['receipt']['sha256'],tdigest)
            self.assertEqual(view.source('TEST',dated.STOCK)['receipt']['windows'],[['2015-01-01','2015-10-20']])
        receipt=sql.source('TEST',dated.STOCK);receipt['receipt']['windows'].clear()
        self.assertTrue(sql.source('TEST',dated.STOCK)['receipt']['windows'])

    def test_all_52_actual_preparation_sqlite_numerical_provider_and_reference(self):
        sql,num=self.views()
        expected={identity:self.fixture.rows[endpoint][0][field] for endpoint,fields in ORACLE.items()
                  for field,identity in fields.items() if identity.startswith('annual.')}
        expected.update({'market.adjusted_price':20,'market.volume':12.5,'treasury.us_3m':.02,'treasury.us_10y':-.01})
        self.assertEqual(len(expected),52)
        units={identity:('share' if field in ('weightedAverageShsOut','weightedAverageShsOutDil','volume') else 'USD/share' if field=='adjClose' else 'scalar' if endpoint=='treasury-rates' else 'USD')
               for endpoint,fields in ORACLE.items() for field,identity in fields.items()}
        entries=[]
        for identity in expected:
            unit=units[identity];display={'USD':'usd','share':'shares','USD/share':'usd_per_share','scalar':'number'}[unit]
            value=definition(dict(op='parameter',id=identity),unit,display);value['parameter_catalog']=parameters.V2
            entries.append(entry(value,'draft:'+identity))
        programs=[definitions.validate(bundle(*entries[i:i+16],roots=[root(e) for e in entries[i:i+16]])) for i in range(0,len(entries),16)]
        for context in ('root','latest'):
            results=self.observe(sql,list(expected),context=context)['results']
            self.assertEqual(results,self.observe(num,list(expected),context=context)['results'])
            computed_results=[]
            for program in programs:
                plan=reference.plan(program,[{key:value for key,value in self.contexts()[0 if context=='root' else 1].items() if key not in ('id','kind')}])
                formula=reference.evaluate(plan,num).to_dict()
                from backtest.engines.numerical import formula_capabilities
                if 2 in formula_capabilities.capabilities()['definition_versions']:
                    from backtest.engines.numerical import formulas
                    from scalar_qualification import compare_blocks
                    with formulas.Evaluator() as evaluator:
                        numerical = evaluator.evaluate(plan,num).to_dict()
                    compare_blocks([formula], [numerical])
                computed_results.extend(formula['results'])
            self.assertEqual(len(computed_results),52)
            for result,computed in zip(results,computed_results):
                identity=result['parameter'];want=22 if identity=='market.adjusted_price' and context=='latest' else expected[identity]
                self.assertTrue(result['valid'],identity);self.assertEqual(result['members'][0]['value'],want,identity)
                self.assertTrue(computed['valid'],identity);self.assertEqual(computed['value'],want,identity)
        for table in source.TABLES:
            self.assertEqual([tuple(r) for r in self.db.execute('SELECT * FROM '+table)],
                             [tuple(r) for r in self.attached._db.execute('SELECT * FROM '+table)])

    def test_at_and_lookback_without_annual_anchor_and_future_exclusion(self):
        payload=json.loads(self.path.read_text());payload['div'].append(dict(date='2010-01-04',adjClose=8,volume=0));self.path.write_text(json.dumps(payload))
        p=research.RAW/'spy-div.json';rows=json.loads(p.read_text());rows.append(dict(date='2010-01-04',adjClose=80));p.write_text(json.dumps(rows))
        p=research.RAW/'treasury.json';rows=json.loads(p.read_text());rows.append(dict(date='2010-01-04',month3=-2,year10=0));p.write_text(json.dumps(rows))
        sql,num=self.views();contexts=self.contexts()+[dict(id='past',kind='at',parent='root',date='2010-01-04'),dict(id='look',kind='lookback',parent='root',months=60)]
        for context in ('past','look'):
            block=self.observe(num,['market.volume','market.adjusted_price','treasury.us_3m','annual.revenue'],contexts,context)
            if context=='past':
                self.assertEqual([r['members'][0]['value'] for r in block['results'][:3]],[0,8,-.02])
                self.assertIsNone(block['results'][0]['anchor'])
            self.assertFalse(block['results'][-1]['valid'])
        with self.assertRaises(provider.ObservationError):
            self.observe(sql,['market.volume'],contexts+[dict(id='future',kind='at',parent='root',date='2015-01-03')],'future')

    def test_treasury_latest_date_null_conflict_and_no_older_field_fallback(self):
        p=research.RAW/'treasury.json';rows=[r for r in json.loads(p.read_text()) if r['date'] not in ('2015-01-02','2015-10-20')];rows.extend([
            dict(date='2015-01-01',month3=3,year10=1),dict(date='2015-01-02',month3=None,year10=-2),
            dict(date='2015-10-20',month3=5,year10=0),dict(date='2015-10-20',month3=6,year10=0)])
        p.write_text(json.dumps(rows));sql,num=self.views()
        for context,reason,rate in (('root','MISSING_INPUT',-.02),('latest','CONFLICTING_INPUT',0)):
            results=self.observe(num,['treasury.us_3m','treasury.us_10y'],context=context)['results']
            self.assertEqual(results[0]['reason'],reason);self.assertEqual(results[1]['members'][0]['value'],rate)
            self.assertEqual(results[0]['members'][0]['observation_date'],self.contexts()[0 if context=='root' else 1]['date'])

    def test_actual_independent_volume_foreign_price_and_future_only_stock_row(self):
        payload=json.loads(self.path.read_text());payload['div'].extend([
            dict(date='2015-10-19',volume=0),
            dict(date='2015-10-16',volume=.5,adjClose=99,currency='EUR'),
            dict(date='2015-10-15',volume=3,adjClose=88)])
        self.path.write_text(json.dumps(payload))
        p=research.RAW/'spy-div.json';rows=json.loads(p.read_text());rows.extend([
            dict(date='2015-10-19',adjClose=100),dict(date='2015-10-16',adjClose=100),
            dict(date='2015-10-14',adjClose=100)])
        p.write_text(json.dumps(rows));sql,num=self.views()
        contexts=self.contexts()+[dict(id=str(i),kind='at',parent='latest',date=day) for i,day in enumerate(('2015-10-19','2015-10-16','2015-10-14'))]
        for view in (sql,num):
            values=self.observe(view,['market.adjusted_price','market.volume'],contexts,'0')['results']
            self.assertFalse(values[0]['valid']);self.assertEqual(values[1]['members'][0]['value'],0)
            values=self.observe(view,['market.adjusted_price','market.volume'],contexts,'1')['results']
            self.assertEqual(values[0]['reason'],'NON_USD_INPUT');self.assertEqual(values[1]['members'][0]['value'],.5)
            values=self.observe(view,['market.adjusted_price','market.volume'],contexts,'2')['results']
            self.assertTrue(all(r['reason']=='MISSING_INPUT' for r in values))
            self.assertTrue(all(r['members'][0]['observation_date']=='2015-10-14' for r in values))

    def test_reference_at_and_lookback_dated_inputs_without_annual_anchor(self):
        payload=json.loads(self.path.read_text());payload['div'].append(dict(date='2010-01-04',adjClose=8,volume=.25));self.path.write_text(json.dumps(payload))
        p=research.RAW/'spy-div.json';rows=json.loads(p.read_text());rows.append(dict(date='2010-01-04',adjClose=80));p.write_text(json.dumps(rows))
        p=research.RAW/'treasury.json';rows=json.loads(p.read_text());rows.append(dict(date='2010-01-04',month3=-2,year10=0));p.write_text(json.dumps(rows))
        sql,num=self.views()
        roots=[dict(symbol='TEST',pool='cached',mode='latest',date='2015-10-20')]
        for operation in (dict(op='at',date='2010-01-04'),dict(op='lookback',months=60)):
            # The lookback resolves to 20 October 2010. Treasury has no age
            # ceiling; stock/session uses seven days and therefore is absent.
            for identity,unit,display,want in (('treasury.us_3m','scalar','number',-.02),('market.volume','share','shares',.25)):
                value=definition(dict(operation,arg=dict(op='parameter',id=identity)),unit,display)
                value['parameter_catalog']=parameters.V2
                program=definitions.validate(bundle(entry(value)))
                result=reference.evaluate(reference.plan(program,roots),num).to_dict()['results'][0]
                if operation['op']=='lookback' and identity=='market.volume':self.assertFalse(result['valid'])
                else:self.assertTrue(result['valid']);self.assertEqual(result['value'],want)

    def test_bounded_queries_keep_four_freshness_checks_and_close(self):
        sql,num=self.views()
        for view in (sql,num):
            freshness=Mock(wraps=view._validate);view._validate=freshness
            self.observe(view,['market.volume','market.adjusted_price','treasury.us_3m','treasury.us_10y'])
            self.assertEqual(freshness.call_count,4)
            with patch.object(view,'_validate',side_effect=AssertionError('whole generation scan')):
                self.assertIsNotNone(view.session_backward(date(2015,1,2),7))
                self.assertIsNotNone(view.dated('TEST',dated.STOCK,date(2015,1,2)))
                self.assertIsNotNone(view.source('',dated.TREASURY))
            view.close()
            for call in (lambda:view.source('',dated.TREASURY),lambda:view.dated('TEST',dated.STOCK,date(2015,1,2)),lambda:view.session_backward(date(2015,1,2),7)):
                with self.assertRaisesRegex(ValueError,'closed'):call()

    def test_dated_reads_pay_rows_bytes_and_cancellation(self):
        sql,num=self.views()
        with patch.object(sql,'dated',side_effect=AssertionError('No read before preflight')):
            with self.assertRaises(provider.ObservationError):self.observe(sql,['market.volume'],limits={'rows':1})
        with self.assertRaisesRegex(ValueError,'byte bound'):self.observe(num,['market.volume'],limits={'bytes':500})
        with self.assertRaisesRegex(RuntimeError,'cancel'):
            num.dated('TEST',dated.STOCK,date(2015,1,2),checkpoint=Mock(side_effect=RuntimeError('cancel')))


class AdapterParityTests(unittest.TestCase):
    def test_sqlite_and_generation_provider_evidence_match(self):
        import test_observation_inputs as fixtures
        from backtest import observations
        fixture=fixtures.ProjectionTests('test_complete_chain_preserves_evidence_dates_and_latest_valuation')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        research.signature.return_value['historical_through']='2015-10-20'
        fixture.prepare()
        ordinary_connect=daily.connect;ordinary_research=research.connect
        store=generation.GenerationStore(fixture.source.parent/'scalar-provider-parity',generation.cache_access.WorkspaceAccess(fixture.source.parent/'parity.lock'))
        roots=[dict(id='r'+str(i),kind='root',symbol='TEST',pool='legacy',mode=mode,date=day) for i,(mode,day) in enumerate([('historical','2015-01-02'),('latest','2015-10-20')])]
        plan=observations.plan([dict(id='o'+str(i),parameter='annual.revenue',context='r'+str(i),count=1) for i in range(2)],roots)
        with patch.object(daily,'connect',side_effect=lambda:ordinary_connect(fixture.path,fixture.source)), patch.object(research,'connect',side_effect=lambda path=fixture.source,**kw:ordinary_research(path,**kw)):
            store.prepare()
            with store.open_current() as attached, closing(ordinary_connect(fixture.path,fixture.source)) as db:
                expected=daily.fingerprint(fixture.source)
                def fresh():self.assertEqual(daily.fingerprint(fixture.source),expected)
                with attached.observations() as original, sqlite_observations.prepared_view(db,fresh) as current:
                    before=observations.observe(plan,original).to_dict()
                    after=observations.observe(plan,current).to_dict()
                    before.pop('generation');after.pop('generation')
                    self.assertEqual(before,after)


LIMIT = durable_tests.LIMIT


class DurableGenerationTests(unittest.TestCase):
    setUp = durable_tests.DurableTests.setUp
    clean = durable_tests.DurableTests.clean
    completed_queue = durable_tests.DurableTests.completed_queue

    def test_real_fictional_input_generation_replacement_and_checkpoint_eviction(self):
        import test_numerical_trials as trials
        from numerical_inputs_fixture import NumericInputs
        from backtest.engines.numerical.numba import NumbaExecutor
        from backtest.engines.numerical.portfolio import NumericalPortfolio
        from backtest.engines.numerical.portfolio import compare_results
        fixture=trials.NumericalTrialsTests('test_full_month_pool_metric_filter_rank_matrix_and_exact_recovery')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        inputs,provider,portfolio,checkpoints=fixture.evaluator('source')
        config=fixture.config(months=12,rank_to=3);binding=trials.diagnostic.checkpoint_binding(portfolio,config)
        experiment=checkpoints.open(binding);details=[]
        result=trials.diagnostic.run(portfolio,config,experiment,capture=lambda n,r:details.append(r))['result']
        options=dict(start=config['start'],end=config['end'],months=config['months'],trials=config['requested'],seed=config['seed'],**config['options'])
        stream=io.BytesIO();writer=result_evidence.Writer(stream,trials=config['requested'],
            metadata=dict(mode='random',options=options,configuration=config,generation=inputs.signature,source=binding['implementation']),max_bytes=LIMIT)
        for n,trial in enumerate(details,1):
            writer.start_trial(n)
            for period in trial['periods']:writer.period(period)
            writer.end_trial({k:v for k,v in trial.items() if k!='periods'})
        writer.finish(result);reader=result_evidence.Reader(stream,max_bytes=LIMIT)
        meta=dict(version=3,kind='random',settings=dict(mode='random',**options),result=result,
            catalog={'metrics':{},'filters':{}},presentation={'original':'saved labels'})
        record=self.library.save_evidence('generation bound original',meta,reader);req=self.completed_queue(reader,meta)
        with fixture.db:fixture.db.execute("UPDATE prices SET adjusted=adjusted*1.1 WHERE day>='2016-01-04'")
        replacement=NumericInputs(fixture.reader,trials.s);self.addCleanup(replacement.close)
        self.assertNotEqual(replacement.signature,inputs.signature)
        new_provider=NumbaExecutor(replacement,limits=deepcopy(provider.limits));self.addCleanup(new_provider.close)
        new_portfolio=NumericalPortfolio(replacement,new_provider);self.addCleanup(new_portfolio.close)
        new_binding=trials.diagnostic.checkpoint_binding(new_portfolio,config);checkpoints.max_experiments=1
        changed=trials.diagnostic.run(new_portfolio,config,checkpoints.open(new_binding))['result']
        self.assertNotEqual(result['distributions'],changed['distributions']);self.assertEqual(experiment.read(),[])
        with ExitStack() as guards:
            for owner,name in ((trials.diagnostic,'run'),(trials.diagnostic,'run_into'),(trials.s,'backtest'),
                    (trials.s,'backtest_dates'),(backtest_jobs.Original,'calculate'),(trials.trial_checkpoints.Experiment,'load'),
                    (trials.trial_checkpoints.Store,'open')):
                guards.enter_context(patch.object(owner,name,side_effect=AssertionError('Stored evidence must not calculate')))
            for store,identifier in ((saved.Store(self.library.path),record['id']),(queue.Store(self.queue.path),req['id'])):
                with store.open_evidence(identifier) as opened:
                    actual=codec.collect(opened.reader)
                    self.assertEqual(actual,details)
                    for original,copy in zip(details,actual,strict=True):
                        self.assertTrue(compare_results(original,copy)['exact'])
                    self.assertEqual(opened.metadata,meta)
                    self.assertEqual(opened.reader.metadata['generation'],inputs.signature)


if __name__ == '__main__':
    unittest.main()
