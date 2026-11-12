"""A cold research build on several processes equals the one-process build.

The worker processes import the application afresh, so each test builds in
child processes of a private copy of the application with fictional inputs.
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from contextlib import closing
import json
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

from backtest.inputs import financial_inputs, market

ROOT=Path(__file__).resolve().parents[1]
BUILD='''
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from backtest.inputs import research
# Three workers for this small universe, or the one-process build.
if sys.argv[3]=='parallel':research.MIN_PARALLEL_COMPANIES,research.WORKERS=1,3
try:research.prepare(Path(sys.argv[2]))
except Exception as error:raise SystemExit(type(error).__name__+': '+str(error))
'''
# The universe order is not the symbol order, and NONE has no annual statement.
US=('MIDDLE','ALPHA','ZULU','NONE','SPIKE','BRAVO','OSCAR')
FOREIGN={'hk':('0001.HK','0002.HK','0003.HK'),'jp':('1000.T','2000.T','3000.T')}


def exact(rows):
    """Rows with the type of each value, so that 1 and 1.0 differ."""
    return [tuple((type(value).__name__,value.hex() if isinstance(value,float) else value) for value in row) for row in rows]


def snapshot(path):
    """Every table in its stored order, with the metadata values as saved text."""
    with closing(sqlite3.connect(path)) as db:
        tables={}
        for name,sql in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
            keys=[row[1] for row in sorted(db.execute(f'PRAGMA table_info({name})'),key=lambda row:row[5]) if row[5]]
            order=','.join(keys) if 'WITHOUT ROWID' in sql or name=='metadata' else 'rowid'
            tables[name]=sql,exact(db.execute(f'SELECT * FROM {name} ORDER BY {order}').fetchall())
        return tables


class ParallelResearchTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.application=Path(folder.name)/'application';self.data=self.application/'data';raw=self.raw=self.application/'raw'
        shutil.copytree(ROOT/'backtest',self.application/'backtest',ignore=shutil.ignore_patterns('__pycache__'))
        self.data.mkdir()
        def save(path,value):
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
        days=('2013-12-30','2014-12-30','2014-12-31','2015-07-01','2015-07-20','2015-07-30')
        save(raw/'universe.json',[dict(symbol=symbol,name='US '+symbol,exchange='NYSE',listed=True) for symbol in US])
        (raw/'metrics.jsonl').write_text(''.join(json.dumps(dict(symbol=symbol,rows=[dict(date='2014-12-31',marketCap=100e6+number,
            enterpriseValue=120e6,evToEBITDA=5,reportedCurrency='USD')]))+'\n' for number,symbol in enumerate(US) if symbol!='NONE'))
        for number,symbol in enumerate(US):
            closes=[20+number]*len(days)
            if symbol=='SPIKE':closes[2]*=10
            save(raw/'px'/f'{symbol}.json',dict(div=[dict(date=day,adjClose=close,volume=1000) for day,close in zip(days,closes)]))
            financial_inputs.publish(raw,symbol,'income-statement',[dict(date='2014-12-31',reportedCurrency='USD',netIncome=1e6+number,revenue=10e6)],{},raw/'coverage.json')
        save(raw/'spy-div.json',[dict(date=day,adjClose=100+number) for number,day in enumerate(days)])
        save(raw/'treasury.json',[dict(date='2015-06-30',month3=2,year10=3)])
        for code,symbols in FOREIGN.items():
            quote=market.MARKETS[code]['currency']
            save(market.universe_path(raw,code),[dict(symbol=symbol,name='Foreign '+symbol,exchange=market.MARKETS[code]['exchanges'][0],
                listed=True,market=code,currency=quote) for symbol in reversed(symbols)])
            save(market.calendar_path(raw,code),[dict(date=day,close=100) for day in days])
            for number,symbol in enumerate(symbols):
                price=(100 if code=='hk' else 1000)+number
                save(raw/'px'/market.cache_path_for(symbol).name,dict(div=[dict(date=day,adjClose=price) for day in days]))
                save(market.native_path(raw,symbol),[dict(date=day,close=price) for day in days[:2]])
                reports=[dict(date=f'{year}-12-31',reportedCurrency=quote,weightedAverageShsOut=1e6,ebitda=5e6,revenue=100e6+year,
                              netIncome=1e6,operatingIncome=2e6,epsDiluted=1,ebit=2e6,interestExpense=1e5) for year in (2013,2014)]
                balance=[dict(date=row['date'],reportedCurrency=quote,totalDebt=20e6,cashAndCashEquivalents=10e6,
                              totalStockholdersEquity=50e6,totalCurrentAssets=30e6,totalCurrentLiabilities=10e6) for row in reports]
                for endpoint,rows in (('income-statement',reports),('balance-sheet-statement',balance)):
                    financial_inputs.publish(raw,symbol,endpoint,rows,{},raw/'coverage.json')
        for currency,rate in (('JPY',100),('HKD',8)):
            save(market.fx_path(raw,currency),[dict(date=day,close=rate) for day in days])

    def build(self,name,mode):
        return subprocess.run([sys.executable,'-c',BUILD,str(self.application),str(self.data/name),mode],
                              capture_output=True,text=True,cwd=self.application)

    def test_parallel_cold_build_equals_the_serial_build(self):
        serial=self.build('serial.sqlite','serial');parallel=self.build('parallel.sqlite','parallel')
        self.assertEqual((serial.returncode,serial.stderr),(0,''));self.assertEqual((parallel.returncode,parallel.stderr),(0,''))
        expected=snapshot(self.data/'serial.sqlite')
        self.assertEqual([name for name,(_,rows) in expected.items() if not rows],[],'Each table needs rows for this comparison.')
        self.assertEqual({row[0][1] for row in expected['company_markets'][1]},{*US,*FOREIGN['hk'],*FOREIGN['jp']})
        actual=snapshot(self.data/'parallel.sqlite')
        for name in expected:
            with self.subTest(table=name):self.assertEqual(actual.get(name),expected[name])
        self.assertEqual(actual.keys(),expected.keys())
        left_out=[line for line in serial.stdout.splitlines() if line.startswith('Left out')]
        self.assertEqual(left_out,['Left out 1 price series with an isolated price spike: SPIKE'])
        self.assertEqual([line for line in parallel.stdout.splitlines() if line.startswith('Left out')],left_out)
        # Each of the three ranges reports its end; a one-process build reports once here.
        progress=[line for line in parallel.stdout.splitlines() if line.endswith(' companies')]
        self.assertEqual((len(progress),progress[-1]),(3,'Prepared 12/12 companies'),parallel.stdout)
        self.assertEqual([path.name for path in self.data.iterdir() if '.building' in path.name],[])

    def test_failed_range_gives_the_serial_error_and_keeps_the_database(self):
        (self.raw/'px'/'OSCAR.json').write_text('not a saved price file')
        for name,mode in (('serial.sqlite','serial'),('parallel.sqlite','parallel')):
            with self.subTest(mode=mode):
                # A database of an earlier schema version makes the next build cold.
                with closing(sqlite3.connect(self.data/name)) as db:
                    db.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                    db.execute("INSERT INTO metadata VALUES('version','1')");db.commit()
                before=(self.data/name).read_bytes()
                result=self.build(name,mode)
                self.assertEqual(result.returncode,1)
                self.assertEqual(result.stderr.strip(),'ValueError: Saved file raw/px/OSCAR.json is unreadable. Use the data panel to download it again.')
                self.assertEqual((self.data/name).read_bytes(),before)
                self.assertEqual([path.name for path in self.data.iterdir() if '.building' in path.name],[])


if __name__=='__main__':
    unittest.main()
