"""Selection, temporal availability, price alignment, and invalidation checks."""
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.inputs import market
from backtest.engines.reference import legacy
from backtest.financial import rules

import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0,str(_PackagePath(__file__).resolve().parents[1]))
from backtest import screening
import json
import io
from contextlib import ExitStack, redirect_stdout, closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import date

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from backtest.inputs import research as r
from backtest.runtime import cache_access


class PreparedPriceBindingTests(unittest.TestCase):
    def test_committed_inventory_is_deterministic_closed_and_does_not_scan_raw(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'research.sqlite'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)')
                db.execute('INSERT INTO metadata VALUES(?,?)',('prices',json.dumps({'B.json':[2,3],'A.json':[1,4]})));db.commit()
            connections=[]
            def connect(source):
                self.assertEqual(source,path)
                value=sqlite3.connect(source);connections.append(value);return value
            with patch.object(r,'connect',side_effect=connect),patch.object(r,'price_sources',side_effect=AssertionError('No raw scan')):
                first=r.prepared_price_binding(path)
                with closing(sqlite3.connect(path)) as db:
                    db.execute('UPDATE metadata SET value=?',(json.dumps({'A.json':[1,4],'B.json':[2,3]}),));db.commit()
                self.assertEqual(r.prepared_price_binding(path),first)
                with closing(sqlite3.connect(path)) as db:
                    db.execute('UPDATE metadata SET value=?',(json.dumps({'A.json':[1,5],'B.json':[2,3]}),));db.commit()
                self.assertNotEqual(r.prepared_price_binding(path),first)
            for db in connections:
                with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')

    def test_missing_or_malformed_inventory_fails_closed(self):
        for inventory in (None,[],{'A.json':[1]}, {'A.json':[True,1]}, {'A.json':[1,-1]}, {'../A.json':[1,2]}):
            with self.subTest(inventory=inventory):
                db=sqlite3.connect(':memory:');db.execute('CREATE TABLE metadata(key TEXT,value TEXT)')
                if inventory is not None:db.execute('INSERT INTO metadata VALUES(?,?)',('prices',json.dumps(inventory)))
                with patch.object(r,'connect',return_value=db),self.assertRaisesRegex(ValueError,'price inventory'):
                    r.prepared_price_binding()
                with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.row_factory=sqlite3.Row
        self.db.executescript(r.SCHEMA)
        for year in [2015,2016]:
            self.db.execute('INSERT INTO periods VALUES(?,?,?,?,?,?,?)',(year,f'{year}-01-02',f'{year+1}-01-02',.1,.02,3,3))
            for i in range(1,4):
                symbol=f'S{i}'
                self.db.execute('INSERT OR IGNORE INTO companies VALUES(?,?,?,?)',(symbol,symbol,'NYSE','Energy' if i==1 else 'Technology'))
                for pool in ['legacy','cached']:
                    # EBITDA/EV ranking intentionally disagrees with subsequent returns.
                    self.db.execute('INSERT INTO snapshots VALUES('+','.join('?'*15)+')',(pool,year,symbol,i,'2014-01-01',f'{year}-01-02',f'{year+1}-01-02',i*100e6,200e6,40e6,.5/i,2*i,.5/i-.02,(-.9 if i==1 else i*.1),'Scheduled exit'))

        r.prepare_metrics(self.db)

    def test_shared_selection_validation(self):
        for select in (screening.historical, screening.latest):
            for options in ({'rank_to':1.5}, {'rank_to':5001}, {'min_yield':float('nan')}, {'min_cap':1e9,'max_cap':100}):
                with self.subTest(select=select.__name__,options=options), self.assertRaises(ValueError):
                    select(self.db,**options)

    def test_ten_year_treasury_asof_preserves_zero_negative_and_missing(self):
        self.db.executemany('INSERT INTO treasury10 VALUES(?,?)',[
            ('2015-01-02',0),('2015-01-05',-.1),('2015-01-06',4)])
        self.assertIsNone(r.ten_year_yield(self.db,date(2015,1,1)))
        self.assertEqual(r.ten_year_yield(self.db,date(2015,1,2)),0)
        self.assertEqual(r.ten_year_yield(self.db,date(2015,1,4)),0)
        self.assertEqual(r.ten_year_yield(self.db,date(2015,1,5)),-.1)

    def test_three_year_metric_and_missing_history(self):
        rows=[dict(fiscal=f'{y}-12-31',known=f'{y+1}-03-31',enterprise_value=999,ebitda=v) for y,v in [(2011,3),(2012,6),(2013,12),(2014,999)]]
        self.assertEqual(r.metrics.annual_average(rows,'2013-12-31',3),7)
        self.assertIsNone(r.metrics.annual_average(rows[1:],'2013-12-31',3))
        # The alternate metric must drive both ranking and filter thresholds.
        self.db.executemany('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)', [('historical','legacy',2015,'S1','ev_ebitda_3y',20,.05),('historical','legacy',2015,'S2','ev_ebitda_3y',3,.3333333333333333)])
        selected=screening.historical(self.db,first=2015,last=2015,metric='ev_ebitda_3y',max_multiple=5)
        self.assertEqual([row['symbol'] for row in selected],['S2'])
        self.assertEqual(selected[0]['metric_multiple'],3)
        summary=r.aggregate(selected)[2015]
        self.assertEqual(summary['median_multiple'],3)
        self.assertEqual(summary['median_yield'],1/3)
        with self.assertRaises(ValueError):
            screening.latest(self.db,metric='unknown')

    def test_preparation_owns_calculations_and_exact_default_values(self):
        for year,ebitda in [(2012,10e6),(2013,20e6),(2014,30e6)]:
            self.db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',('S1',f'{year}-01-01',f'{year}-04-01',100e6,200e6,ebitda,.1))
        r.prepare_metrics(self.db)
        row=screening.historical(self.db,first=2015,last=2015,metric='ev_ebitda_3y')[0]
        self.assertEqual(row['metric_multiple'],10)
        self.assertEqual(row['metric_yield'],.1)
        # Same history, different screening-date EV must produce a different value.
        self.db.execute("UPDATE snapshots SET enterprise_value=400e6 WHERE year=2016")
        r.prepare_metrics(self.db)
        self.assertEqual(screening.historical(self.db,first=2016,last=2016,metric='ev_ebitda_3y')[0]['metric_multiple'],20)
        for row in screening.historical(self.db):
            self.assertEqual(row['metric_multiple'],row['ev_ebitda'])
            self.assertEqual(row['metric_yield'],row['ebitda_yield'])
        # A different formula needs only registration, without selector changes.
        with patch.dict(r.metrics.METRICS,{'test_signal':dict(label='Test signal')}), patch.dict(r.metrics.CALCULATORS,{'test_signal':lambda observation,history:(2.,.5)}):
            r.prepare_metrics(self.db)
            self.assertEqual(len(screening.historical(self.db,first=2015,last=2015,metric='test_signal')),3)

    def test_combined_thresholds_before_ranking_and_missing_values(self):
        self.db.executemany('INSERT INTO filter_values VALUES(?,?,?,?,?,?)',[
            ('historical','legacy',2015,'S1','return_1y',-10),
            ('historical','legacy',2015,'S2','return_1y',20),
            ('historical','legacy',2015,'S2','ev_ebitda',4),
            ('historical','legacy',2015,'S3','return_1y',30)])
        conditions=[dict(field='return_1y',op='gt',value=0),dict(field='return_1y',op='lt',value=30),dict(field='ev_ebitda',op='lt',value=5)]
        rows=screening.historical(self.db,first=2015,last=2015,rank_to=1,filters=conditions)
        self.assertEqual([(row['symbol'],row['rank']) for row in rows],[('S2',1)])
        for conditions in ([dict(field='unknown_ratio',op='lt',value=15)],[dict(field='return_1y',op='gt',value=float('nan'))],[dict(field='return_1y',op='gte',value=0)],{}):
            with self.assertRaises(ValueError):screening.latest(self.db,filters=conditions)

    def test_trailing_returns_use_only_past_prices_and_require_history(self):
        prices=[(date(2017,2,28),50),(date(2019,2,28),80),(date(2020,2,28),100),(date(2020,3,2),1000)]
        lookup=lambda day,column,forward,slack:r.before(prices,day,slack)
        observation=dict(market_cap=100e6,enterprise_value=200e6,ebitda_yield=.1)
        values=r.metrics.filter_values(observation,{},date(2020,2,29),lookup)
        self.assertEqual(values['return_1y'],25)
        self.assertEqual(values['return_3y'],100)
        self.assertEqual(values['market_cap'],100)
        values=r.metrics.filter_values(observation,{},date(2019,2,28),lookup)
        self.assertNotIn('return_1y',values)
        self.assertNotIn('return_3y',values)

    def tearDown(self):
        self.db.close()

    def test_rank_not_future_return_and_filter_before_ranking(self):
        rows=screening.historical(self.db,first=2015,last=2015,rank_from=1,rank_to=2)
        self.assertEqual([x['symbol'] for x in rows],['S1','S2'])
        self.assertAlmostEqual(r.aggregate(rows)[2015]['portfolio'],-.35)
        rows=screening.historical(self.db,first=2015,last=2015,min_cap=150e6,rank_to=1)
        self.assertEqual([x['symbol'] for x in rows],['S2'])
        self.assertEqual(screening.historical(self.db,sector='Unknown'),[])
        self.assertEqual({x['symbol'] for x in screening.historical(self.db,sector='Energy')},{'S1'})

    def test_year_pool_ratio_and_rank_bounds(self):
        self.assertEqual(len(screening.historical(self.db,first=2015,last=2015,pool='cached',rank_from=2,rank_to=3)),2)
        self.assertEqual({x['symbol'] for x in screening.historical(self.db,max_multiple=2)}, {'S1'})
        with self.assertRaises(ValueError):screening.historical(self.db,rank_from=3,rank_to=1)
        with self.assertRaises(ValueError):screening.historical(self.db,first=2020,last=2015)

    def test_statement_availability_and_max_age(self):
        statement=dict(fiscal=date(2014,12,31),known=date(2015,3,31))
        self.assertIsNone(rules.latest_statement([statement],date(2015,3,31)))
        self.assertEqual(rules.latest_statement([statement],date(2015,4,1)),statement)
        self.assertIsNone(rules.latest_statement([statement],date(2018,1,1)))

    def test_early_stop_bankruptcy_and_valuation(self):
        statement={'fiscal':date(2014,6,30),'market_cap':100e6,'enterprise':150e6,'yield':.2}
        prices=[(date(2014,6,30),10.),(date(2015,1,2),20.),(date(2015,6,1),5.)]
        result=r.snapshot(statement,date(2015,1,2),date(2016,1,4),[],prices,False)
        self.assertEqual(result[3],200e6)
        self.assertEqual(result[4],250e6)
        self.assertAlmostEqual(result[6],.12)
        self.assertEqual(result[-2],-.75)
        self.assertEqual(result[-1],'Last available price')
        self.assertEqual(r.snapshot(statement,date(2015,1,2),date(2016,1,4),[],prices,True)[-2],-1.)
        self.assertIsNone(r.snapshot(statement,date(2015,2,2),date(2016,1,4),[],prices,False))

    def test_latest_uses_exact_date_and_available_reports(self):
        day=date(2026,10,20)
        statement=dict(fiscal=date(2025,12,31),known=date(2026,3,31),market_cap=100e6,enterprise=150e6)
        statement['yield']=.2
        prices=[(date(2025,12,31),10.),(date(2026,10,19),20.),(date(2026,10,21),100.)]
        self.assertIsNone(r.latest_snapshot(statement,day,[],prices))
        prices=sorted(prices+[(day,30.)])
        row=r.latest_snapshot(statement,day,[],prices)
        self.assertEqual(row[2],'2026-10-20')
        self.assertEqual(row[3],30.)
        self.assertEqual(row[4],300e6)
        self.assertEqual(row[5],350e6)
        self.assertIsNone(r.latest_snapshot(dict(statement,known=day),day,[],prices))
        self.assertIsNone(r.latest_snapshot(dict(statement,fiscal=date(2023,1,1),known=date(2023,4,1)),day,[],prices))

    def test_latest_filters_before_ranking_without_future_returns(self):
        for i in range(1,4):
            self.db.execute('INSERT INTO latest_snapshots VALUES('+','.join('?'*12)+')',('cached',f'S{i}',None,'2025-12-31','2026-03-31','2026-10-20',10.,i*100e6,200e6,.5/i,2*i,.5/i-.02))
        r.prepare_metrics(self.db)
        rows=screening.latest(self.db,pool='cached',min_cap=150e6,rank_to=1)
        self.assertEqual([h['symbol'] for h in rows],['S2'])
        self.assertEqual(rows[0]['price_date'],'2026-10-20')
        self.assertNotIn('return_value',rows[0])
        self.assertEqual(screening.latest(self.db,pool='cached',sector='Unknown'),[])

    def test_invalidation_and_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'research.sqlite'
            db=sqlite3.connect(path);db.executescript(r.SCHEMA)
            db.executemany('INSERT INTO metadata VALUES(?,?)',[(k,json.dumps(v)) for k,v in dict(version=r.SCHEMA_VERSION,inputs={'a':1},prices={'b':2}).items()]);db.commit();db.close()
            with patch.object(r,'signature',return_value={'a':1}),patch.object(r,'price_sources',return_value={'b':2}):
                db=r.connect(path)
                with self.assertRaises(sqlite3.OperationalError):db.execute('DELETE FROM metadata')
                db.close()
            with patch.object(r,'signature',return_value={'a':1}),patch.object(r,'price_sources',side_effect=AssertionError('Normal queries must not scan all price files')):
                r.connect(path).close()
            with patch.object(r,'signature',return_value={'a':1}),patch.object(r,'price_sources',return_value={'b':3}):
                with self.assertRaisesRegex(ValueError,'changed'):r.connect(path,full_prices=True)
            with patch.object(r,'signature',return_value={'a':3}):
                with self.assertRaisesRegex(ValueError,'changed'):r.connect(path)


class PreparationTests(unittest.TestCase):
    """Exercise real file publication using a one-company offline fixture."""

    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        root = Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        raw = root / 'raw'
        (raw / 'px').mkdir(parents=True)
        self.path = root / 'data' / 'research.sqlite'
        results=root/'results';results.mkdir()
        (results/'summary-exits.txt').write_text('Through 2015-10-20\n')
        (raw / 'universe.json').write_text(json.dumps([
            dict(symbol='TEST', name='Test Company', exchange='NYSE', sector='Technology', listed=True)]))
        (raw / 'metrics.jsonl').write_text(json.dumps(dict(symbol='TEST', rows=[
            dict(date='2014-06-30', marketCap=100e6, enterpriseValue=150e6,
                 evToEBITDA=5, reportedCurrency='USD')])) + '\n')
        (raw / 'spy-div.json').write_text(json.dumps([
            dict(date='2015-01-02', adjClose=100),
            dict(date='2015-10-20', adjClose=110)]))
        (raw / 'treasury.json').write_text(json.dumps([
            dict(date='2015-01-02', month3=2)]))
        (raw / 'px' / 'TEST.json').write_text(json.dumps(dict(div=[
            dict(date='2014-06-30', adjClose=10),
            dict(date='2015-01-02', adjClose=20),
            dict(date='2015-10-20', adjClose=22)])))
        for owner, key, value in [(r, 'ROOT', root), (r, 'RAW', raw),
                                  (r, 'RESULTS', results), (market, 'RAW', raw), (legacy, 'RAW', raw), (legacy, 'FIRST_YEAR', 2015), (rules, 'FIRST_YEAR', 2015),
                                  (legacy, 'LAST_YEAR', 2015), (rules, 'LAST_YEAR', 2015)]:
            self.context.enter_context(patch.object(owner, key, value))
        # The coordinator follows this private root, as in an installed runtime.
        self.context.enter_context(patch.object(cache_access, 'workspace',
            cache_access.WorkspaceAccess(root / 'data' / 'website-data-0.lock')))
        self.context.enter_context(patch.object(r, 'signature', return_value={'fixture': 1}))
        self.context.enter_context(patch.object(r, 'verify_reference', side_effect=lambda db: (self.verify_fixture(db),r.prepared_baseline(db))[1]))
        self.context.enter_context(patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected download')))
        self.context.enter_context(redirect_stdout(io.StringIO()))

    def verify_fixture(self, db):
        stocks = screening.historical(db)
        self.assertEqual([(h['year'], h['symbol']) for h in stocks], [(2015, 'TEST')])
        self.assertAlmostEqual(stocks[0]['return_value'], .1)
        self.assertEqual(stocks[0]['market_cap'], 200e6)

    def test_success_publishes_verified_database(self):
        r.prepare(self.path)
        self.assertTrue(self.path.is_file())
        self.assertFalse(self.path.with_name(self.path.name + '.building').exists())
        db = r.connect(self.path, full_prices=True)
        try:
            self.verify_fixture(db)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0], 2)
        finally:
            db.close()

    def test_operating_spread_preparation_and_browser_sql_parity(self):
        r.financial_inputs.publish(r.RAW,'TEST','income-statement',[
            dict(date=f'{year}-06-30',reportedCurrency='USD',revenue=100e6,operatingIncome=margin*100e6)
            for year,margin in [(2012,.1),(2013,.2),(2014,.3),(2015,99)]],{},r.RAW/'coverage.json')
        (r.RAW/'treasury.json').write_text(json.dumps([
            dict(date='2014-12-31',month3=2,year10=3),
            dict(date='2015-01-03',month3=2,year10=99),
            dict(date='2015-10-20',month3=2,year10=4),
            dict(date='2015-10-21',month3=2,year10=99)]))
        # A delayed stock buy must not advance the January screen's Treasury rate.
        path=r.RAW/'px'/'TEST.json';payload=json.loads(path.read_text())
        payload['div'][1]['date']='2015-01-05';path.write_text(json.dumps(payload))
        r.prepare(self.path)
        root=Path(__file__).resolve().parents[1]
        sys.path.insert(0,str(root/'website'))
        from website.rendering import data as dataset
        with patch.object(dataset,'connect',side_effect=lambda:r.connect(self.path)):
            prepared=dataset.load_screening_data()
        historical=[];latest=[];cases=[]
        with closing(r.connect(self.path)) as db:
            saved=[dict(row) for row in db.execute("SELECT * FROM filter_values WHERE field='operating_yield_spread_3y'")]
            self.assertEqual(len(saved),4)
            for row in saved:
                self.assertAlmostEqual(row['value'],5 if row['mode']=='historical' else 100*20e6/270e6-4)
            for pool in ('legacy','cached'):
                for op,value in [('gt',4),('lt',4),('gt',5),('lt',5),('gt',0)]:
                    options=dict(first=2015,last=2015,pool=pool,filters=[dict(field='operating_yield_spread_3y',op=op,value=value)])
                    cases.append(options)
                    historical.append([[h['symbol'],h['rank']] for h in screening.historical(db,**options)])
                    latest.append([[h['symbol'],h['rank']] for h in screening.latest(db,**{k:v for k,v in options.items() if k not in ('first','last')})])
        code="""
const fs=require('fs'),assert=require('assert'),engine=require(process.argv[1]);
const {dataset,cases,historical,latest}=JSON.parse(fs.readFileSync(0,'utf8'));
for(let i=0;i<cases.length;i++){
 const rows=engine.screen(dataset,cases[i]).years.flatMap(y=>y.holdings);
 assert.deepStrictEqual(rows.map(h=>[h.symbol,h.rank]),historical[i]);
 assert.deepStrictEqual(engine.latestScreen(dataset,cases[i]).stocks.map(h=>[h.symbol,h.rank]),latest[i]);
}
"""
        subprocess.run(['node','-e',code,str(root/'website'/'browser'/'screener.js')],
                       input=json.dumps(dict(dataset=prepared,cases=cases,historical=historical,latest=latest)),text=True,check=True)
        # Missing Treasury inputs omit this filter, while ordinary picks remain.
        (r.RAW/'treasury.json').write_text('[{"date":"2015-01-02","month3":2}]')
        r.prepare(self.path,force=True)
        with closing(r.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM filter_values WHERE field='operating_yield_spread_3y'").fetchone()[0],0)
            self.assertEqual(len(screening.latest(db)),1)
            self.assertEqual(screening.latest(db,filters=cases[0]['filters']),[])

    def test_preparation_stores_dated_financial_ratios_in_both_modes(self):
        ledger={}
        for endpoint,fields in [('income-statement',dict(netIncome=20e6,revenue=100e6)),('balance-sheet-statement',dict(totalStockholdersEquity=50e6)),('cash-flow-statement',dict(freeCashFlow=-5e6))]:
            r.financial_inputs.publish(r.RAW,'TEST',endpoint,[dict(date='2014-06-30',reportedCurrency='USD',**fields)],ledger,r.RAW/'coverage.json')
        r.prepare(self.path)
        with closing(r.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM financial_inputs').fetchone()[0],1)
            historical=screening.historical(db,first=2015,last=2015,filters=[dict(field='pe',op='lt',value=11),dict(field='profit_margin',op='gt',value=19)])
            self.assertEqual([h['symbol'] for h in historical],['TEST'])
            latest=screening.latest(db,filters=[dict(field='pe',op='gt',value=10)])
            self.assertEqual([h['symbol'] for h in latest],['TEST'])
            self.assertEqual(screening.latest(db,filters=[dict(field='fcf_yield',op='gt',value=0)]),[])

    def test_new_latest_prices_do_not_extend_historical_reference(self):
        spy=r.RAW/'spy-div.json'
        rows=json.loads(spy.read_text())+[dict(date='2016-01-04',adjClose=120)]
        spy.write_text(json.dumps(rows))
        path=r.RAW/'px/TEST.json'
        prices=json.loads(path.read_text());prices['div'].append(dict(date='2016-01-04',adjClose=24))
        path.write_text(json.dumps(prices))
        r.prepare(self.path)
        db=r.connect(self.path)
        try:
            self.verify_fixture(db)
            self.assertEqual(db.execute('SELECT exit FROM periods').fetchone()[0],'2015-10-20')
            self.assertEqual(screening.latest(db)[0]['price_date'],'2016-01-04')
            self.assertEqual(screening.latest(db)[0]['price'],24.)
        finally:
            db.close()

    def test_prepare_latest_excludes_unlisted_names(self):
        r.prepare(self.path)
        db=r.connect(self.path)
        self.assertEqual(len(screening.latest(db)),1)
        self.assertEqual(screening.latest(db)[0]['price_date'],'2015-10-20')
        self.assertEqual(screening.latest(db)[0]['price'],22.)
        db.close()
        universe=r.RAW/'universe.json'
        rows=json.loads(universe.read_text());rows[0]['listed']=False
        universe.write_text(json.dumps(rows))
        r.prepare(self.path,force=True)
        db=r.connect(self.path)
        try:
            self.assertEqual(screening.latest(db),[])
            self.verify_fixture(db)
        finally:
            db.close()

    def test_unchanged_inputs_skip_json_parsing_and_writes(self):
        r.prepare(self.path)
        before = self.path.read_bytes()
        timestamp = self.path.stat().st_mtime_ns
        with patch.object(Path, 'read_text', side_effect=AssertionError('Unexpected JSON parse')):
            r.prepare(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mtime_ns, timestamp)

    def test_failed_verification_preserves_existing_database(self):
        r.prepare(self.path)
        before = self.path.read_bytes()
        with patch.object(r, 'verify_reference', side_effect=ValueError('Reference mismatch')):
            with self.assertRaisesRegex(ValueError, 'Reference mismatch'):
                r.prepare(self.path, force=True)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.path.with_name(self.path.name + '.building').exists())
        db = r.connect(self.path)
        try:
            self.verify_fixture(db)
        finally:
            db.close()


if __name__=='__main__':
    unittest.main()
