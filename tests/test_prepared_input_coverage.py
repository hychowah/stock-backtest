"""Coverage populations, omissions and read-only freshness boundaries."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
import sys as _owner_sys
from pathlib import Path as _OwnerPath
_owner_sys.path.insert(0,str(_OwnerPath(__file__).resolve().parents[1]))
from backtest.inputs import daily
from contextlib import closing, nullcontext
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tools.ops.prepared_input_coverage as coverage
import test_research


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_research.ResearchTests();self.fixture.setUp()
        self.addCleanup(self.fixture.db.close);self.research=self.fixture.db
        self.daily=sqlite3.connect(':memory:');self.daily.row_factory=sqlite3.Row
        self.daily.executescript(coverage.daily_inputs.SCHEMA);self.addCleanup(self.daily.close)
        for i in range(1,4):
            row=(f'S{i}','2014-01-01','2014-04-01',i*100e6,200e6,100e6/i,.5/i)
            for db in (self.research,self.daily):db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',row)
            for day in ('2014-01-01','2015-01-02','2016-01-02','2017-01-02'):
                self.daily.execute('INSERT INTO prices VALUES(?,?,?)',(f'S{i}',day,10))
        self.spy=[dict(date=d,adjClose=100) for d in ('2015-01-02','2015-07-01','2016-01-02','2017-01-02')]
        self.treasury=[dict(date='2014-01-01',month3=1)]
        self.daily.executemany('INSERT INTO sessions VALUES(?,?)',[(r['date'],100) for r in self.spy])
        self.daily.execute('INSERT INTO treasuries VALUES(?,?)',('2014-01-01',.01))
        metadata=dict(prices={f'S{i}.json':[1,1] for i in (1,2)})
        self.research.executemany('INSERT INTO metadata VALUES(?,?)',[(k,json.dumps(v)) for k,v in metadata.items()])
        self.research.execute("DELETE FROM snapshots WHERE symbol='S3'")

    def report(self):return coverage._coverage(self.research,self.daily,self.spy,self.treasury,lambda:None)

    def test_counts_without_january_books(self):
        report=self.report()
        self.assertEqual(report['version'],2)
        self.assertNotIn('years',report);self.assertNotIn('through',report)
        self.assertEqual((report['financial_symbols'],report['accepted_price_files'],report['financial_symbols_without_price_files']),(3,2,1))
        self.assertEqual(report['daily_books'],dict(periods=0,snapshots=0,period_pools=0))

    def test_observed_gaps_duplicates_and_invalid_rows(self):
        summary=coverage.series_summary(self.spy+[self.spy[0],dict(date='bad',adjClose=1),dict(date='2015-01-03',adjClose=0)],'adjClose',positive=True)
        self.assertEqual(summary['duplicate_dates'],{'2015-01-02':2});self.assertEqual(summary['invalid_rows'],2)
        self.assertEqual(summary['maximum_calendar_gap_days'],366)
        report=self.report()
        self.assertGreater(report['stock_sessions']['totals']['observed_internal_omissions'],0)
        self.assertIn('Legitimate nontrading',report['stock_sessions']['scope'])

    def test_reporting_preserves_rows_and_rejects_stale_daily_before_raw_access(self):
        before=self.research.total_changes,self.daily.total_changes;self.report()
        self.assertEqual((self.research.total_changes,self.daily.total_changes),before)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'daily.sqlite'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE metadata(key,value)');db.execute('INSERT INTO metadata VALUES(?,?)',('daily_inputs','{}'));db.commit()
            original=path.read_bytes()
            with patch.object(coverage.cache_access,'access',side_effect=lambda:nullcontext()),patch.object(coverage.r,'connect',return_value=self.research),patch.object(coverage.daily_inputs,'fingerprint',return_value={'new':1}):
                with self.assertRaisesRegex(ValueError,'Daily cache changed'):coverage.report(Path(tmp)/'research.sqlite',path)
            self.assertEqual(path.read_bytes(),original)

    def test_pre_price_membership_keeps_full_fiscal_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw=Path(tmp);(raw/'universe.json').write_text(json.dumps([dict(symbol='TEST')]))
            rows=[dict(date='2014-01-01',marketCap=500e6,enterpriseValue=600e6,evToEBITDA=5,reportedCurrency='USD'),
                  dict(date='2014-01-01',marketCap=50e6,enterpriseValue=100e6,evToEBITDA=5,reportedCurrency='USD')]
            (raw/'metrics.jsonl').write_text(json.dumps(dict(symbol='TEST',rows=rows))+'\n')
            broad,legacy=coverage._source_histories(raw)
            self.assertEqual(len(broad['TEST']),2);self.assertEqual(len(legacy['TEST']),1)
            self.assertEqual(legacy['TEST'][0]['market_cap'],500e6)


if __name__=='__main__':unittest.main()
