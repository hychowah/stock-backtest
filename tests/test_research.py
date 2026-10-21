"""Selection, temporal availability, price alignment, and invalidation checks."""
import json
import io
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import date

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import research as r


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

    def test_shared_selection_validation(self):
        for select in (r.screen, r.latest_screen):
            for options in ({'rank_to':1.5}, {'rank_to':5001}, {'min_yield':float('nan')}, {'min_cap':1e9,'max_cap':100}):
                with self.subTest(select=select.__name__,options=options), self.assertRaises(ValueError):
                    select(self.db,**options)

    def tearDown(self):
        self.db.close()

    def test_rank_not_future_return_and_filter_before_ranking(self):
        rows=r.screen(self.db,first=2015,last=2015,rank_from=1,rank_to=2)
        self.assertEqual([x['symbol'] for x in rows],['S1','S2'])
        self.assertAlmostEqual(r.aggregate(rows)[2015]['portfolio'],-.35)
        rows=r.screen(self.db,first=2015,last=2015,min_cap=150e6,rank_to=1)
        self.assertEqual([x['symbol'] for x in rows],['S2'])
        self.assertEqual(r.screen(self.db,sector='Unknown'),[])
        self.assertEqual({x['symbol'] for x in r.screen(self.db,sector='Energy')},{'S1'})

    def test_year_pool_ratio_and_rank_bounds(self):
        self.assertEqual(len(r.screen(self.db,first=2015,last=2015,pool='cached',rank_from=2,rank_to=3)),2)
        self.assertEqual({x['symbol'] for x in r.screen(self.db,max_multiple=2)}, {'S1'})
        with self.assertRaises(ValueError):r.screen(self.db,rank_from=3,rank_to=1)
        with self.assertRaises(ValueError):r.screen(self.db,first=2020,last=2015)

    def test_statement_availability_and_max_age(self):
        statement=dict(fiscal=date(2014,12,31),known=date(2015,3,31))
        self.assertIsNone(r.run.latest_statement([statement],date(2015,3,31)))
        self.assertEqual(r.run.latest_statement([statement],date(2015,4,1)),statement)
        self.assertIsNone(r.run.latest_statement([statement],date(2018,1,1)))

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
        rows=r.latest_screen(self.db,pool='cached',min_cap=150e6,rank_to=1)
        self.assertEqual([h['symbol'] for h in rows],['S2'])
        self.assertEqual(rows[0]['price_date'],'2026-10-20')
        self.assertNotIn('return_value',rows[0])
        self.assertEqual(r.latest_screen(self.db,pool='cached',sector='Unknown'),[])

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
                                  (r, 'RESULTS', results), (r.run, 'RAW', raw), (r.run, 'FIRST_YEAR', 2015),
                                  (r.run, 'LAST_YEAR', 2015)]:
            self.context.enter_context(patch.object(owner, key, value))
        self.context.enter_context(patch.object(r, 'signature', return_value={'fixture': 1}))
        self.context.enter_context(patch.object(r, 'verify_reference', side_effect=self.verify_fixture))
        self.context.enter_context(patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected download')))
        self.context.enter_context(redirect_stdout(io.StringIO()))

    def verify_fixture(self, db):
        stocks = r.screen(db)
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
            self.assertEqual(r.latest_screen(db)[0]['price_date'],'2016-01-04')
            self.assertEqual(r.latest_screen(db)[0]['price'],24.)
        finally:
            db.close()

    def test_prepare_latest_excludes_unlisted_names(self):
        r.prepare(self.path)
        db=r.connect(self.path)
        self.assertEqual(len(r.latest_screen(db)),1)
        self.assertEqual(r.latest_screen(db)[0]['price_date'],'2015-10-20')
        self.assertEqual(r.latest_screen(db)[0]['price'],22.)
        db.close()
        universe=r.RAW/'universe.json'
        rows=json.loads(universe.read_text());rows[0]['listed']=False
        universe.write_text(json.dumps(rows))
        r.prepare(self.path,force=True)
        db=r.connect(self.path)
        try:
            self.assertEqual(r.latest_screen(db),[])
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
