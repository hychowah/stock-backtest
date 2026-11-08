"""Selection, temporal availability, price alignment, and invalidation checks."""
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.inputs import market
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
from backtest.inputs import daily, facts
from backtest.inputs import research as r
from backtest.financial import books
from backtest.runtime import cache_access, diagnostics
import book_store_fixture as store


def before(prices, day, slack):
    """The last (day, price) on or before day within slack days, or None."""
    found = [row for row in prices if row[0] <= day]
    return found[-1] if found and (day - found[-1][0]).days <= slack else None


class ResearchTests(unittest.TestCase):
    def setUp(self):
        # Latest and dated books share one selector over the book store.
        self.db=store.connection()
        self.books={}
        for i in range(1,4):
            store.company(self.db,f'S{i}',sector='Energy' if i==1 else 'Technology')
        # Each dated book's rows, ranking pairs and filter values; dated() stores them once.
        self.content={}
        for year in [2015,2016]:
            rows,pairs=self.content.setdefault(year,({},{}))
            for i in range(1,4):
                symbol=f'S{i}'
                for pool in ['legacy','cached']:
                    # EBITDA/EV ranking intentionally disagrees with subsequent returns.
                    rows.setdefault(pool,{})[symbol]=dict(candidate_rank=i,fiscal='2014-01-01',known='2014-03-31',
                              entry=f'{year}-01-02',price=10.,exit=f'{year+1}-01-02',market_cap=i*100e6,enterprise_value=200e6,
                              ebitda=40e6,ebitda_yield=.5/i,ev_ebitda=2*i,spread=.5/i-.02,
                              return_value=(-.9 if i==1 else i*.1),status='Scheduled exit')
                    # A dated book stores its own ranking pair (books.book).
                    pairs.setdefault(pool,{}).setdefault(symbol,{})['ev_ebitda']=(2*i,.5/i)
        self.values={year:{} for year in self.content}

    def dated(self,years,**options):
        """Selected rows of the dated books of these years, book by book."""
        if not self.books:
            for year,(rows,pairs) in self.content.items():
                self.books[year]=store.book(self.db,f'{year}-01-02',f'{year+1}-01-02',spy=.1,candidates=3,
                                            rows=rows,metrics=pairs,values=self.values[year])
        return [row for year in years for row in screening.select(self.db,book=self.books[year],**options)]

    def latest_rows(self,pool='legacy',ranks=True):
        """A latest book of three companies whose ranking pairs come from metrics.evaluate."""
        rows,pairs={},{}
        for i in range(1,4):
            row=dict(candidate_rank=i if ranks else None,fiscal='2014-01-01',known='2014-04-01',entry='2015-01-02',price=10.,
                     market_cap=i*100e6,enterprise_value=200e6,ebitda=.5/i*200e6,ebitda_yield=.5/i,ev_ebitda=2*i,spread=.5/i-.02)
            rows[f'S{i}']=row
            history=[dict(row) for row in self.db.execute('SELECT * FROM research.statements WHERE symbol=? ORDER BY fiscal',(f'S{i}',))]
            pairs[f'S{i}']=r.metrics.evaluate(dict(row,symbol=f'S{i}'),history)
        return store.book(self.db,'2015-01-02',None,candidates=3,pools=(pool,),rows={pool:rows},metrics={pool:pairs})

    def test_shared_selection_validation(self):
        for select in (lambda db,**options:self.dated([2015,2016],**options), screening.latest):
            for options in ({'rank_to':1.5}, {'rank_to':5001}, {'min_yield':float('nan')}, {'min_cap':1e9,'max_cap':100}):
                with self.subTest(options=options), self.assertRaises(ValueError):
                    select(self.db,**options)

    def test_ten_year_treasury_asof_preserves_zero_negative_and_missing(self):
        self.db.research.executemany('INSERT INTO market_days VALUES(?,?,?,?,?,?)',[
            ('2015-01-02',None,1,None,0,None),('2015-01-05',None,1,None,-.1,None),('2015-01-06',None,1,None,4,None),
            ('2015-01-07',None,1,None,None,'MISSING_INPUT')])
        ten_year=lambda day:facts.BookFacts(self.db).ten_year(day)
        self.assertIsNone(ten_year(date(2015,1,1)))
        self.assertEqual(ten_year(date(2015,1,2)),0)
        self.assertEqual(ten_year(date(2015,1,4)),0)
        self.assertEqual(ten_year(date(2015,1,5)),-.1)
        self.assertEqual(ten_year(date(2015,1,7)),4)

    def test_three_year_metric_and_missing_history(self):
        rows=[dict(fiscal=f'{y}-12-31',known=f'{y+1}-03-31',enterprise_value=999,ebitda=v) for y,v in [(2011,3),(2012,6),(2013,12),(2014,999)]]
        self.assertEqual(r.metrics.annual_average(rows,'2013-12-31',3),7)
        self.assertIsNone(r.metrics.annual_average(rows[1:],'2013-12-31',3))
        # The alternate metric must drive both ranking and filter thresholds.
        pairs=self.content[2015][1]['legacy']
        pairs['S1']['ev_ebitda_3y']=(20,.05);pairs['S2']['ev_ebitda_3y']=(3,.3333333333333333)
        selected=self.dated([2015],metric='ev_ebitda_3y',max_multiple=5)
        self.assertEqual([row['symbol'] for row in selected],['S2'])
        self.assertEqual((selected[0]['metric_multiple'],selected[0]['metric_yield']),(3,1/3))
        with self.assertRaises(ValueError):
            screening.latest(self.db,metric='unknown')

    def test_book_ranking_pairs_come_from_the_one_metric_calculator(self):
        for year,ebitda in [(2012,10e6),(2013,20e6),(2014,30e6)]:
            self.db.research.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',('S1',f'{year}-01-01',f'{year}-04-01',100e6,200e6,ebitda,.1))
        self.latest_rows()
        row=screening.latest(self.db,metric='ev_ebitda_3y')[0]
        self.assertEqual(row['metric_multiple'],10)
        self.assertEqual(row['metric_yield'],.1)
        # Same history, different screening-date EV must produce a different value.
        history=[dict(row) for row in self.db.execute("SELECT * FROM research.statements WHERE symbol='S1' ORDER BY fiscal")]
        observation=dict(symbol='S1',fiscal='2014-01-01',enterprise_value=400e6,ev_ebitda=4,ebitda_yield=.25)
        self.assertEqual(r.metrics.evaluate(observation,history)['ev_ebitda_3y'][0],20)
        for row in screening.latest(self.db):
            self.assertEqual(row['metric_multiple'],row['ev_ebitda'])
            self.assertEqual(row['metric_yield'],row['ebitda_yield'])
        # A different formula needs only registration, without selector changes.
        with patch.dict(r.metrics.METRICS,{'test_signal':dict(label='Test signal')}), patch.dict(r.metrics.CALCULATORS,{'test_signal':lambda observation,history:(2.,.5)}):
            self.assertEqual(r.metrics.evaluate(observation,history)['test_signal'],(2.,.5))

    def test_combined_thresholds_before_ranking_and_missing_values(self):
        for symbol,field,number in [('S1','return_1y',-10),('S2','return_1y',20),('S2','ev_ebitda',4),('S3','return_1y',30)]:
            self.values[2015].setdefault('legacy',{}).setdefault(symbol,{})[field]=number
        conditions=[dict(field='return_1y',op='gt',value=0),dict(field='return_1y',op='lt',value=30),dict(field='ev_ebitda',op='lt',value=5)]
        rows=self.dated([2015],rank_to=1,filters=conditions)
        self.assertEqual([(row['symbol'],row['rank']) for row in rows],[('S2',1)])
        for conditions in ([dict(field='unknown_ratio',op='lt',value=15)],[dict(field='return_1y',op='gt',value=float('nan'))],[dict(field='return_1y',op='gte',value=0)],{}):
            with self.assertRaises(ValueError):screening.latest(self.db,filters=conditions)

    def test_trailing_returns_use_only_past_prices_and_require_history(self):
        prices=[(date(2017,2,28),50),(date(2019,2,28),80),(date(2020,2,28),100),(date(2020,3,2),1000)]
        lookup=lambda day,forward,slack:before(prices,day,slack)
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
        rows=self.dated([2015],rank_from=1,rank_to=2)
        self.assertEqual([x['symbol'] for x in rows],['S1','S2'])
        # Entry selection has no future-return lane; schedules close chosen rows.
        self.assertEqual(list(rows[0]),['pool','symbol','candidate_rank','fiscal','entry','price','market_cap','enterprise_value',
            'ebitda','ebitda_yield','ev_ebitda','spread','name','sector','exchange','metric_yield','metric_multiple','rank'])
        rows=self.dated([2015],min_cap=150e6,rank_to=1)
        self.assertEqual([x['symbol'] for x in rows],['S2'])
        self.assertEqual(self.dated([2015,2016],sector='Unknown'),[])
        self.assertEqual({x['symbol'] for x in self.dated([2015,2016],sector='Energy')},{'S1'})

    def test_period_pool_ratio_and_rank_bounds(self):
        self.assertEqual(len(self.dated([2015],pool='cached',rank_from=2,rank_to=3)),2)
        self.assertEqual({x['symbol'] for x in self.dated([2015,2016],max_multiple=2)}, {'S1'})
        with self.assertRaises(ValueError):self.dated([2015,2016],rank_from=3,rank_to=1)

    def test_statement_availability_and_max_age(self):
        statement=dict(fiscal=date(2014,12,31),known=date(2015,3,31))
        self.assertIsNone(rules.latest_statement([statement],date(2015,3,31)))
        self.assertEqual(rules.latest_statement([statement],date(2015,4,1)),statement)
        self.assertIsNone(rules.latest_statement([statement],date(2018,1,1)))

    def test_early_stop_bankruptcy_and_valuation(self):
        statement={'fiscal':date(2014,6,30),'known':date(2014,9,28),'market_cap':100e6,'enterprise':150e6,'yield':.2}
        prices=[(date(2014,6,30),10.),(date(2015,1,2),20.),(date(2015,6,1),5.)]
        def lookup(day,forward,slack):
            if not forward:return before(prices,day,slack)
            found=[row for row in prices if row[0]>=day]
            return found[0] if found and (found[0][0]-day).days<=slack else None
        reason,(fiscal_px,start,cap,ev,ebitda)=books.admit(statement,date(2015,1,2),lookup,books.ENTRY_SLACK)
        self.assertEqual((reason,cap,ev),(None,200e6,250e6))
        self.assertAlmostEqual(books.ebitda_yield_and_multiple(ebitda,ev)[0],.12)
        reason,(end,ret,status)=books.close(start,date(2016,1,4),lookup,False)
        self.assertEqual((reason,ret,status),(None,-.75,'Last available price'))
        self.assertEqual(books.close(start,date(2016,1,4),lookup,True)[1][1:],(-1.,'Bankruptcy'))
        self.assertEqual(books.admit(statement,date(2015,2,2),lookup,books.ENTRY_SLACK),('MISSING_PRICE',None))

    def test_latest_uses_exact_date_and_available_reports(self):
        day=date(2026,10,20)
        statement=dict(fiscal=date(2025,12,31),known=date(2026,3,31),market_cap=100e6,enterprise=150e6)
        statement['yield']=.2
        prices=[(date(2025,12,31),10.),(date(2026,10,19),20.),(date(2026,10,21),100.)]
        # The open book values each company at the exact session: no slack.
        exact=lambda day,forward,slack:next((row for row in prices if row[0]==day),None) if forward else before(prices,day,slack)
        self.assertEqual(books.admit(statement,day,exact,0),('MISSING_PRICE',None))
        prices=sorted(prices+[(day,30.)])
        reason,(fiscal_px,entry,cap,ev,ebitda)=books.admit(statement,day,exact,0)
        self.assertEqual((reason,entry,cap,ev),(None,(day,30.),300e6,350e6))
        self.assertIsNone(rules.latest_statement([dict(statement,known=day)],day))
        self.assertIsNone(rules.latest_statement([dict(statement,fiscal=date(2023,1,1),known=date(2023,4,1))],day))

    def test_latest_filters_before_ranking_without_future_returns(self):
        self.latest_rows('cached',ranks=False)
        rows=screening.latest(self.db,pool='cached',min_cap=150e6,rank_to=1)
        self.assertEqual([h['symbol'] for h in rows],['S2'])
        self.assertEqual(rows[0]['price_date'],'2015-01-02')
        self.assertNotIn('return_value',rows[0])
        # A latest row keeps the old latest snapshot shape.
        self.assertEqual(list(rows[0])[:12],['pool','symbol','candidate_rank','fiscal','known','price_date','price','market_cap',
            'enterprise_value','ebitda_yield','ev_ebitda','spread'])
        self.assertEqual(screening.latest(self.db,pool='cached',sector='Unknown'),[])

    def test_invalidation_and_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'research.sqlite'
            db=sqlite3.connect(path);db.executescript(r.SCHEMA)
            db.executemany('INSERT INTO metadata VALUES(?,?)',[(k,json.dumps(v)) for k,v in dict(version=r.SCHEMA_VERSION,inputs={'a':1},prices={'b':2},
                identity=dict(code=r.code_identity('facts'))).items()]);db.commit();db.close()
            # Readers compare the accepted signature; a data action refreshes it.
            r.forget_signature()
            with patch.object(r,'signature',return_value={'a':1}),patch.object(r,'price_sources',return_value={'b':2}):
                db=r.connect(path)
                with self.assertRaises(sqlite3.OperationalError):db.execute('DELETE FROM metadata')
                db.close()
            with patch.object(r,'signature',return_value={'a':1}),patch.object(r,'price_sources',side_effect=AssertionError('Normal queries must not scan all price files')):
                r.connect(path).close()
            with patch.object(r,'signature',return_value={'a':1}),patch.object(r,'price_sources',return_value={'b':3}):
                with self.assertRaisesRegex(ValueError,'changed'):r.connect(path,full_prices=True)
            with patch.object(r,'signature',return_value={'a':3}):
                r.connect(path).close()  # A hand edit is not seen before a data action.
                r.forget_signature()
                with self.assertRaisesRegex(ValueError,'changed'):r.connect(path)
            r.forget_signature()


class PreparationTests(unittest.TestCase):
    """Exercise real file publication using a one-company offline fixture."""

    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        root = Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        raw = root / 'raw'
        (raw / 'px').mkdir(parents=True)
        self.path = root / 'data' / 'research.sqlite'
        self.daily = root / 'data' / 'schedules.sqlite'
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
        for owner, key, value in [(r, 'ROOT', root), (r, 'RAW', raw), (market, 'RAW', raw)]:
            self.context.enter_context(patch.object(owner, key, value))
        # The coordinator follows this private root, as in an installed runtime.
        self.context.enter_context(patch.object(cache_access, 'workspace',
            cache_access.WorkspaceAccess(root / 'data' / 'website-data-0.lock')))
        self.context.enter_context(patch.object(r, 'signature', return_value={'fixture': 1}))
        self.context.enter_context(patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected download')))
        self.context.enter_context(redirect_stdout(io.StringIO()))

    def latest(self, **options):
        """Build the daily cache afresh from this research database and screen its latest book.

        The fixture's raw signature is constant, so a kept cache would not see a forced research rebuild.
        """
        self.daily.unlink(missing_ok=True)
        daily.prepare(self.daily, self.path)
        with closing(daily.connect(self.daily, self.path)) as db:
            return screening.latest(db, **options)

    def verify_fixture(self):
        stocks = self.latest()
        self.assertEqual([(h['symbol'], h['price_date'], h['price']) for h in stocks], [('TEST', '2015-10-20', 22.)])
        self.assertAlmostEqual(stocks[0]['market_cap'], 220e6)

    def test_success_publishes_database(self):
        r.prepare(self.path)
        self.assertTrue(self.path.is_file())
        self.assertFalse(self.path.with_name(self.path.name + '.building').exists())
        db = r.connect(self.path, full_prices=True)
        try:
            self.assertEqual(tuple(db.execute('SELECT * FROM companies').fetchone()), ('TEST', 'Test Company', 'NYSE', 'Technology', 1))
        finally:
            db.close()
        self.verify_fixture()

    def test_preparation_logs_its_stages(self):
        folder = self.path.parent.parent / 'logs'
        self.addCleanup(diagnostics.close); diagnostics.configure(folder)
        r.prepare(self.path)
        r.prepare(self.path)
        full, current = [record for record in diagnostics.records(folder) if record['event'] == 'prepare.research']
        self.assertEqual((full['outcome'], full['companies'], current['outcome']), ('prepared', 1, 'current'))
        self.assertLessEqual({'inputs', 'companies', 'dated_facts', 'identity', 'commit', 'publication'},
                             full['stages'].keys())

    def test_windows_sharing_failure_retries_publication(self):
        replace, calls = Path.replace, []
        def flaky(source, target):
            calls.append(source)
            if len(calls) == 1:
                error = PermissionError('sharing violation'); error.winerror = 32; raise error
            return replace(source, target)
        with patch.object(Path, 'replace', flaky), patch.object(r.cache_assets.time, 'sleep'):
            r.prepare(self.path)
        self.assertEqual(len(calls), 2)
        self.verify_fixture()

    def test_operating_spread_preparation_and_browser_sql_parity(self):
        r.financial_inputs.publish(r.RAW,'TEST','income-statement',[
            dict(date=f'{year}-06-30',reportedCurrency='USD',revenue=100e6,operatingIncome=margin*100e6)
            for year,margin in [(2012,.1),(2013,.2),(2014,.3),(2015,99)]],{},r.RAW/'coverage.json')
        (r.RAW/'treasury.json').write_text(json.dumps([
            dict(date='2014-12-31',month3=2,year10=3),
            dict(date='2015-01-03',month3=2,year10=99),
            dict(date='2015-10-20',month3=2,year10=4),
            dict(date='2015-10-21',month3=2,year10=99)]))
        daily.prepare(self.daily,self.path)
        root=Path(__file__).resolve().parents[1]
        sys.path.insert(0,str(root/'website'))
        from website.rendering import data as dataset
        latest=[];cases=[]
        with closing(daily.connect(self.daily,self.path)) as db:
            prepared=dataset.load_screening_data(db)
            saved=[dict(row) for row in db.execute("SELECT f_operating_yield_spread_3y AS value FROM book_rows WHERE f_operating_yield_spread_3y IS NOT NULL")]
            self.assertEqual(len(saved),2)
            for row in saved:
                self.assertAlmostEqual(row['value'],100*20e6/270e6-4)
            for pool in ('legacy','cached'):
                for op,value in [('gt',4),('lt',4),('gt',5),('lt',5),('gt',0)]:
                    options=dict(pool=pool,filters=[dict(field='operating_yield_spread_3y',op=op,value=value)])
                    cases.append(options)
                    latest.append([[h['symbol'],h['rank']] for h in screening.latest(db,**options)])
        code="""
const fs=require('fs'),assert=require('assert'),engine=require(process.argv[1]);
const {dataset,cases,latest}=JSON.parse(fs.readFileSync(0,'utf8'));
for(let i=0;i<cases.length;i++){
 assert.deepStrictEqual(engine.latestScreen(dataset,cases[i]).stocks.map(h=>[h.symbol,h.rank]),latest[i]);
}
"""
        subprocess.run(['node','-e',code,str(root/'website'/'browser'/'screener.js')],
                       input=json.dumps(dict(dataset=prepared,cases=cases,latest=latest)),text=True,check=True)
        # Missing Treasury inputs omit this filter, while ordinary picks remain.
        (r.RAW/'treasury.json').write_text('[{"date":"2015-01-02","month3":2}]')
        r.prepare(self.path,force=True)
        self.assertEqual(len(self.latest()),1)
        self.assertEqual(self.latest(filters=cases[0]['filters']),[])
        with closing(daily.connect(self.daily,self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM book_rows WHERE f_operating_yield_spread_3y IS NOT NULL").fetchone()[0],0)

    def test_preparation_stores_latest_financial_ratios(self):
        ledger={}
        for endpoint,fields in [('income-statement',dict(netIncome=20e6,revenue=100e6)),('balance-sheet-statement',dict(totalStockholdersEquity=50e6)),('cash-flow-statement',dict(freeCashFlow=-5e6))]:
            r.financial_inputs.publish(r.RAW,'TEST',endpoint,[dict(date='2014-06-30',reportedCurrency='USD',**fields)],ledger,r.RAW/'coverage.json')
        r.prepare(self.path)
        with closing(r.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(DISTINCT fiscal) FROM annual_facts').fetchone()[0],1)
        selected=self.latest(filters=[dict(field='pe',op='lt',value=12),dict(field='profit_margin',op='gt',value=19)])
        self.assertEqual([h['symbol'] for h in selected],['TEST'])
        latest=self.latest(filters=[dict(field='pe',op='gt',value=10)])
        self.assertEqual([h['symbol'] for h in latest],['TEST'])
        self.assertEqual(self.latest(filters=[dict(field='fcf_yield',op='gt',value=0)]),[])

    def test_new_saved_session_advances_the_latest_screen(self):
        spy=r.RAW/'spy-div.json'
        rows=json.loads(spy.read_text())+[dict(date='2016-01-04',adjClose=120)]
        spy.write_text(json.dumps(rows))
        path=r.RAW/'px/TEST.json'
        prices=json.loads(path.read_text());prices['div'].append(dict(date='2016-01-04',adjClose=24))
        path.write_text(json.dumps(prices))
        r.prepare(self.path)
        self.assertEqual(self.latest()[0]['price_date'],'2016-01-04')
        self.assertEqual(self.latest()[0]['price'],24.)

    def test_prepare_latest_excludes_unlisted_names(self):
        r.prepare(self.path)
        self.assertEqual(len(self.latest()),1)
        self.assertEqual(self.latest()[0]['price_date'],'2015-10-20')
        self.assertEqual(self.latest()[0]['price'],22.)
        universe=r.RAW/'universe.json'
        rows=json.loads(universe.read_text());rows[0]['listed']=False
        universe.write_text(json.dumps(rows))
        r.prepare(self.path,force=True)
        self.assertEqual(self.latest(),[])

    def test_unchanged_inputs_skip_json_parsing_and_writes(self):
        r.prepare(self.path)
        before = self.path.read_bytes()
        timestamp = self.path.stat().st_mtime_ns
        read = Path.read_bytes
        def source_only(path):
            # The fact-row code identity reads source files, never a saved raw file.
            if path.is_relative_to(r.RAW): raise AssertionError('Unexpected file read')
            return read(path)
        with patch.object(Path, 'read_text', side_effect=AssertionError('Unexpected JSON parse')), \
                patch.object(Path, 'read_bytes', source_only):
            r.prepare(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mtime_ns, timestamp)

    def test_inputs_changed_during_preparation_keep_the_previous_database(self):
        r.prepare(self.path)
        before = self.path.read_bytes()
        calls = []
        def changing():
            calls.append(None)
            return {'fixture': len(calls)}  # The second inspection differs from the first.
        with patch.object(r, 'signature', side_effect=changing):
            with self.assertRaisesRegex(ValueError, 'Inputs changed during preparation'):
                r.prepare(self.path, force=True)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.path.with_name(self.path.name + '.building').exists())

    def test_failed_preparation_preserves_existing_database(self):
        r.prepare(self.path)
        before = self.path.read_bytes()
        with patch.object(r.facts, 'store_market', side_effect=ValueError('Fact failure')):
            with self.assertRaisesRegex(ValueError, 'Fact failure'):
                r.prepare(self.path, force=True)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.path.with_name(self.path.name + '.building').exists())
        self.verify_fixture()

    def test_unreadable_saved_price_file_stops_preparation(self):
        r.prepare(self.path)
        before = self.path.read_bytes()
        # Invalid JSON, a list and a mapping without a 'div' list, as metrics.jsonl fails closed.
        for name, content in (('px/TEST.json', b'{invalid'), ('px/TEST.json', b'[]'), ('px/TEST.json', b'{"light":[]}'),
                              ('spy-div.json', b'{invalid'), ('treasury.json', b'{"rows":[]}')):
            with self.subTest(name=name, content=content):
                path = r.RAW / name
                original = path.read_bytes()
                path.write_bytes(content)
                try:
                    with self.assertRaisesRegex(ValueError, f'raw/{name} is unreadable. Use the data panel'):
                        r.prepare(self.path, force=True)
                finally:
                    path.write_bytes(original)
                self.assertEqual(self.path.read_bytes(), before)
                self.assertFalse(self.path.with_name(self.path.name + '.building').exists())


class SavedDateTests(unittest.TestCase):
    def test_saved_date_reader_equals_strptime(self):
        from datetime import datetime
        def expected(value):
            if not value:return None
            try:return datetime.strptime(str(value)[:10],'%Y-%m-%d').date()
            except ValueError:return None
        values=[f'{y}-{m:02d}-{d:02d}' for y in ('0000','0001','1999','2024','2026','9999') for m in range(14) for d in range(33)]
        values+=['2026-1-05','2026-01-5','2026-1-5','2026-01- 5','20260105','2026/01/05',' 2026-01-05','2026-01-05T09:30:00Z',
                 '2026-01-05 extra','２０２６-01-05','2026-٠١-05','-026-01-05','+2026-01-0','2026-0a-05','',None,0,20260105,
                 date(2026,1,5),'2026-02-29','2024-02-29']
        for value in values:
            self.assertEqual(rules.parse_day(value),expected(value),repr(value))


if __name__=='__main__':
    unittest.main()
