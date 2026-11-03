"""Independent saved-source, bounded transport and all-52 reference evidence.

Private synthetic inputs only. Expected fields come from the independent Phase8
oracle; old immutable fixture files are never regenerated or rewritten.
"""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from contextlib import closing, ExitStack
from datetime import date
import hashlib
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
from backtest.inputs import dated_observation_inputs as dated, observation_inputs as source
from backtest.inputs import daily, research, sqlite_observations
from backtest.engines.numerical import generation
from backtest import observations as provider
from backtest.variables import definitions, reference, parameters
import test_annual_observations as annual
from test_parameter_contract import ORACLE
from test_variable_definitions import entry, definition, root, bundle


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)/'A.json'

    def resolve(self, rows, endpoint=dated.STOCK, ledger=None):
        self.path.write_text(json.dumps(dict(div=rows) if endpoint==dated.STOCK else rows))
        return dated.resolve(self.path,endpoint,ledger or {},stock=endpoint==dated.STOCK)

    def test_equal_null_duplicates_and_fractional_zero_volume(self):
        rows=[dict(date='2015-01-02',adjClose=10,volume=0),dict(date='2015-01-02',adjClose=None),
              dict(date='2015-01-02',adjClose=10,volume=0),dict(date='2015-01-03',adjClose=11,volume=.25)]
        facts=self.resolve(rows)
        self.assertEqual(facts['dated']['2015-01-02']['adjClose']['value'],10)
        self.assertEqual(facts['dated']['2015-01-02']['volume']['value'],0)
        self.assertEqual(len(facts['dated']['2015-01-02']['volume']['rows']),3)
        self.assertEqual(facts['dated']['2015-01-03']['volume']['value'],.25)
        self.assertIsNone(facts['source']['receipt'])

    def test_price_volume_currency_and_conflicts_are_independent(self):
        facts=self.resolve([dict(date='2015-01-02',adjClose=10,volume=7,currency='EUR'),
            dict(date='2015-01-03',adjClose=-1,volume=0),dict(date='2015-01-04',adjClose=10,volume=3),
            dict(date='2015-01-04',adjClose=11,volume=3)])['dated']
        self.assertEqual(facts['2015-01-02']['adjClose']['reason'],'NON_USD_INPUT')
        self.assertEqual(facts['2015-01-02']['volume']['value'],7)
        self.assertEqual(facts['2015-01-03']['adjClose']['reason'],'INVALID_INPUT')
        self.assertEqual(facts['2015-01-03']['volume']['value'],0)
        self.assertEqual(facts['2015-01-04']['adjClose']['reason'],'CONFLICTING_INPUT')
        self.assertEqual(facts['2015-01-04']['volume']['value'],3)

    def test_invalid_values_dates_and_identities_are_retained(self):
        for value in (True,False,[],{},'nan','inf','invalid',10**500):
            facts=self.resolve([dict(date='2015-01-02',adjClose=value,volume=value),dict(date='invalid'),None])
            self.assertEqual(facts['dated']['2015-01-02']['adjClose']['reason'],'INVALID_INPUT')
            self.assertEqual(facts['dated']['2015-01-02']['volume']['reason'],'INVALID_INPUT')
            self.assertEqual([r['index'] for r in facts['source']['invalid_rows']],[1,2])
            source.encoded(facts)

    def test_explicit_reported_currency_survives_absent_null_and_conflicting_route_currency(self):
        for route in ({},dict(currency=None),dict(currency='USD')):
            facts=self.resolve([dict(route,date='2015-01-02',reportedCurrency='EUR',adjClose=10,volume=1)])
            self.assertEqual(facts['dated']['2015-01-02']['adjClose']['reason'],'NON_USD_INPUT')
            self.assertEqual(facts['dated']['2015-01-02']['volume']['value'],1)
            self.assertEqual(facts['dated']['2015-01-02']['adjClose']['rows'][0]['reported_currency'],'EUR')

    def test_receipt_cannot_bind_a_second_read_of_changed_asset_bytes(self):
        self.resolve([dict(date='2015-01-02',adjClose=10)])
        original=dated.cache_assets.SeriesAsset
        def changed(*args,**kwargs):
            self.path.write_text(json.dumps(dict(div=[dict(date='2015-01-02',adjClose=99)])))
            return original(*args,**kwargs)
        with patch.object(dated.cache_assets,'SeriesAsset',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'changed during preparation'):
                dated.resolve(self.path,dated.STOCK,{},stock=True)

    def test_signed_rates_and_latest_null_field_states(self):
        facts=self.resolve([dict(date='2015-01-01',month3=-1,year10=0),
            dict(date='2015-01-02',month3=None,year10=-2)],dated.TREASURY)
        self.assertEqual(facts['dated']['2015-01-01']['month3']['value'],-1)
        self.assertEqual(facts['dated']['2015-01-01']['year10']['value'],0)
        self.assertEqual(facts['dated']['2015-01-02']['month3']['reason'],'MISSING_INPUT')

    def test_matching_current_previous_receipt_and_unbound_receipt(self):
        self.resolve([dict(date='2015-01-02',adjClose=10)])
        digest=hashlib.sha256(self.path.read_bytes()).hexdigest()
        receipt=dict(sha256=digest,windows=[['2015-01-01','2015-01-03']])
        for value in (receipt,dict(sha256='b'*64,previous=receipt)):
            facts=dated.resolve(self.path,dated.STOCK,{'px/A.json':value},stock=True)
            self.assertEqual(facts['source']['receipt']['sha256'],digest)
        facts=dated.resolve(self.path,dated.STOCK,{'px/A.json':dict(sha256='b'*64)},stock=True)
        self.assertIsNone(facts['source']['receipt']);self.assertTrue(facts['dated'])
        # Raw volume facts survive an asset which proves no valid price response.
        facts=self.resolve([dict(date='2015-01-02',volume=1)])
        self.assertEqual(facts['source']['disposition'],'salvaged')
        self.assertIsNone(facts['source']['receipt']);self.assertEqual(facts['dated']['2015-01-02']['volume']['value'],1)

    def test_missing_unreadable_source_no_repairs(self):
        self.assertEqual(dated.resolve(self.path,dated.STOCK,{},stock=True)['source']['disposition'],'missing')
        self.path.write_bytes(b'{invalid');before=self.path.read_bytes()
        self.assertEqual(dated.resolve(self.path,dated.STOCK,{},stock=True)['source']['disposition'],'unreadable')
        self.assertEqual(self.path.read_bytes(),before)

    def test_history_record_bounds_and_cancellation(self):
        self.path.write_text(json.dumps(dict(div=[dict(date='2015-01-02',volume=1)]*4)))
        with patch.object(dated,'MAX_HISTORY',3),self.assertRaisesRegex(ValueError,'history'):
            dated.resolve(self.path,dated.STOCK,{},stock=True)
        with patch.object(dated,'MAX_RECORD_BYTES',10),self.assertRaisesRegex(ValueError,'byte'):
            dated.resolve(self.path,dated.STOCK,{},stock=True)
        with self.assertRaisesRegex(RuntimeError,'cancel'):
            dated.resolve(self.path,dated.STOCK,{},stock=True,checkpoint=Mock(side_effect=RuntimeError('cancel')))

    def test_full_record_boundary_includes_source_dated_and_session_keys(self):
        cases = [('source', dated.STOCK, [None] * 64),
                 ('dated', dated.STOCK, [dict(date='2015-01-02', adjClose=10, volume=0)] * 64),
                 ('dated', dated.TREASURY, [dict(date='2015-01-02', month3=-1, year10=0)] * 64),
                 ('session', dated.CALENDAR, [dict(date='2015-01-02', adjClose=10)] * 64)]
        for kind, endpoint, rows in cases:
            with self.subTest(kind=kind, endpoint=endpoint), ExitStack() as stack:
                facts = self.resolve(rows, endpoint)
                symbol = 'A' if endpoint == dated.STOCK else ''
                if kind == 'source':
                    table, row = 'observation_sources', (symbol, endpoint, source.encoded(facts['source']))
                elif kind == 'session':
                    table, row = 'observation_sessions', ('2015-01-02', source.encoded(facts['dated']['2015-01-02']))
                else:
                    table, row = 'observation_dated', (symbol, endpoint, '2015-01-02', source.encoded(facts['dated']['2015-01-02']))
                exact = source.record_bytes(row)
                first = stack.enter_context(closing(sqlite3.connect(':memory:')))
                first.executescript(source.SCHEMA)
                with patch.object(dated, 'MAX_RECORD_BYTES', exact):
                    source.store_dated(first, symbol, endpoint, facts)
                    source.finish(first, '2015-01-02')
                    # Both daily and numerical transport use this same checked
                    # copy owner. An accepted full record must survive each hop.
                    for _ in range(2):
                        copied = stack.enter_context(closing(sqlite3.connect(':memory:')))
                        copied.executescript(source.SCHEMA)
                        source.copy(first, copied, max_record_bytes=exact)
                        self.assertIn(row, copied.execute('SELECT * FROM '+table).fetchall())
                        first = copied
                rejected = stack.enter_context(closing(sqlite3.connect(':memory:')))
                rejected.executescript(source.SCHEMA)
                with patch.object(dated, 'MAX_RECORD_BYTES', exact-1), self.assertRaisesRegex(ValueError, 'byte bound'):
                    with rejected:
                        source.store_dated(rejected, symbol, endpoint, facts)
                self.assertEqual(rejected.execute('SELECT count(*) FROM observation_sources').fetchone()[0], 0)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.fixture=annual.AnnualTransportTests('test_actual_research_daily_sqlite_and_generation_share_all_endpoint_facts')
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
                formula=reference.evaluate(reference.plan(program,[{key:value for key,value in self.contexts()[0 if context=='root' else 1].items() if key not in ('id','kind')}]),num).to_dict()
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

    def test_session_seven_day_boundary_exact_stock_and_volume_without_price(self):
        sql,num=self.views()
        contexts=self.contexts()+[dict(id='seven',kind='at',parent='latest',date='2015-01-09'),dict(id='eight',kind='at',parent='latest',date='2015-01-10')]
        self.assertTrue(self.observe(sql,['market.volume'],contexts,'seven')['results'][0]['valid'])
        self.assertEqual(self.observe(sql,['market.volume'],contexts,'eight')['results'][0]['reason'],'MISSING_SESSION')
        # Removing only own-stock exact row never carries its earlier row.
        self.db.execute("DELETE FROM observation_dated WHERE symbol='TEST' AND day='2015-01-02'")
        result=self.observe(sql,['market.volume'])['results'][0];self.assertEqual(result['reason'],'MISSING_INPUT')
        # This is a private borrowed SQLite fixture; content checking remains an
        # admission concern and catches this explicit later mutation independently.
        with self.assertRaisesRegex(ValueError,'stale'):source.require(self.db,verify_content=True)

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

    def test_copy_cancellation_record_bounds_and_publication_preserve_previous(self):
        sql,num=self.views()
        target=sqlite3.connect(':memory:');self.addCleanup(target.close);target.executescript(source.SCHEMA)
        with self.assertRaisesRegex(RuntimeError,'cancel'):
            source.copy(self.db,target,Mock(side_effect=RuntimeError('cancel')))
        with self.assertRaisesRegex(ValueError,'byte bound'):
            source.copy(self.db,target,max_record_bytes=20)
        before=self.owner.source.read_bytes()
        with patch.object(research.dated_observation_inputs,'shared',side_effect=RuntimeError('private dated failure')):
            with self.assertRaisesRegex(RuntimeError,'private dated failure'):research.prepare(self.owner.source,force=True)
        self.assertEqual(self.owner.source.read_bytes(),before)
        self.assertFalse(self.owner.source.with_name(self.owner.source.name+'.building').exists())

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

    def test_old_version_missing_dated_relations_and_content_tamper_rejected(self):
        sql,num=self.views()
        for version in (1,2):
            self.db.execute('UPDATE observation_metadata SET value=? WHERE key=?',(json.dumps(version),'version'))
            with self.assertRaisesRegex(ValueError,'stale'):source.require(self.db)
        self.db.execute('UPDATE observation_metadata SET value=? WHERE key=?',('3','version'))
        self.db.execute("UPDATE observation_dated SET evidence_json='{}' WHERE endpoint=?",(dated.TREASURY,))
        with self.assertRaisesRegex(ValueError,'stale'):source.require(self.db,verify_content=True)
        self.db.execute('DROP TABLE observation_sessions')
        with self.assertRaisesRegex(ValueError,'stale'):source.require(self.db)


if __name__=='__main__':unittest.main()
