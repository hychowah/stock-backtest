"""Ordinary preparation in an exported root, including forced owned shutdown."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.runtime.process_owner import OwnedProcess, ProcessLimits


def write_fixture(root):
    raw=root/'raw';(raw/'px').mkdir(parents=True);(raw/'financial-inputs').mkdir()
    dates=sorted({f'{y}-01-02' for y in range(1994,2027)}|{f'{y}-12-31' for y in range(1994,2026)}|{'2026-10-20'})
    prices=[dict(date=d,adjClose=100+i) for i,d in enumerate(dates)]
    spy=[r for r in prices if '1995-01-01'<=r['date']<='2026-10-20']
    (raw/'universe.json').write_text(json.dumps([dict(symbol='TEST',name='Fictional',exchange='NYSE',sector='Technology',listed=True)]))
    (raw/'metrics.jsonl').write_text(json.dumps(dict(symbol='TEST',rows=[dict(date=f'{y}-12-31',marketCap=500e6,enterpriseValue=1000e6,evToEBITDA=5,reportedCurrency='USD') for y in range(1994,2026)]))+'\n')
    (raw/'px/TEST.json').write_text(json.dumps(dict(div=prices)))
    (raw/'spy-div.json').write_text(json.dumps(spy));(raw/'treasury.json').write_text(json.dumps([dict(date=r['date'],month3=2) for r in spy]))
    (raw/'download-coverage.json').write_text('{}')


BOOTSTRAP=r'''
from pathlib import Path
from contextlib import closing
import json,sys
root=Path(sys.argv[1]);out=Path(sys.argv[2])
sys.path[:0]=[str(root)]
from website import runtime_access
with runtime_access.ownership(root,timeout=0):
 sys.path.insert(0,str(root))
 from backtest.inputs import fmp_download
 fmp_download.KEY_PATH=root.parent/'nonexistent-preparation-key';assert not fmp_download.KEY_PATH.exists()
 from backtest.inputs import research as r, daily
 from backtest.engines.original import schedules as s
 from backtest import portfolio_results, calendar as schedule_calendar
 import tools.ops.prepared_input_coverage as coverage
 for m in (r,s,r.market,r.books,r.metrics,r.cache_assets,r.financial_inputs,r.cache_access,portfolio_results,schedule_calendar,coverage):
  assert Path(m.__file__).resolve().is_relative_to(root.resolve()),m.__name__
 for name,module in list(sys.modules.items()):
  if name=='backtest' or name.startswith('backtest.'):
   assert Path(module.__file__).resolve().is_relative_to(root.resolve()),name
 r.prepare();daily.prepare()
 result=coverage.report()
 assert result['version']==2 and result['financial_symbols']==result['accepted_price_files']
 assert result['daily_books']==dict(periods=0,snapshots=0,period_pools=0)
 with closing(r.connect(full_prices=True)) as db:
  latest=json.loads(db.execute("SELECT value FROM metadata WHERE key='latest'").fetchone()[0])
  stocks=db.execute('SELECT COUNT(*) FROM latest_snapshots').fetchone()[0]
 assert not (root/'results').exists()
 out.write_text(json.dumps(dict(status='prepared',latest=latest['asof'],stocks=stocks,module_origins=True,daily_books=result['daily_books'])))
'''

STOP=r'''
assert __import__('sys').stdin.readline()=='GO'+chr(10)
from pathlib import Path
import sqlite3,sys,time
root=Path(sys.argv[1]);ready=Path(sys.argv[2])
sys.path[:0]=[str(root)]
from website import runtime_access
with runtime_access.ownership(root,timeout=0):
 sys.path.insert(0,str(root))
 from backtest.inputs import fmp_download
 fmp_download.KEY_PATH=root.parent/'nonexistent-preparation-key'
 from backtest.inputs import research as research
 original=sqlite3.connect
 def connect(path,*args,**kwargs):
  db=original(path,*args,**kwargs)
  if str(path).endswith('.building'):
   def trace(sql):
    if sql.startswith('INSERT INTO companies'):
     ready.write_text('inside ordinary preparation transaction')
     while True:time.sleep(.01)
   db.set_trace_callback(trace)
  return db
 sqlite3.connect=connect # Test-only pause; financial policy/freshness are unchanged.
 research.prepare(force=True)
'''


class ExportedPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'source';self.root.mkdir()
        (self.root/'scripts').mkdir();(self.root/'website').mkdir();(self.root/'tools').mkdir()
        shutil.copytree(ROOT/'backtest',self.root/'backtest',ignore=shutil.ignore_patterns('__pycache__'))
        for path in (ROOT/'scripts').glob('*.py'):shutil.copyfile(path,self.root/'scripts'/path.name)
        for name in ('website/__init__.py','website/runtime_access.py'):
            shutil.copyfile(ROOT/name,self.root/name)
        (self.root/'tools/ops').mkdir()
        for name in ('tools/__init__.py','tools/ops/__init__.py','tools/ops/prepared_input_coverage.py'):
            shutil.copyfile(ROOT/name,self.root/name)
        write_fixture(self.root)

    def prepare(self):
        out=self.base/'result.json'
        owner=OwnedProcess([sys.executable,'-I','-B','-X','utf8','-c',BOOTSTRAP,str(self.root),str(out)],
            limits=ProcessLimits(2*1024**3,16,25,user_cpu_seconds=360 if os.name=='nt' else None,close_seconds=10,
                                 output_bytes=1024**2,frame_bytes=65536,queued_events=128))
        logs=[]
        try:
            owner.start();deadline=time.monotonic()+30
            while True:
                self.assertLess(time.monotonic(),deadline,'Synthetic preparation deadline')
                event=owner.event(.05)
                if event and event.get('event')=='worker_log':logs.append(event['text'])
                if event and event.get('event')=='failed':self.fail('Owned preparation failed')
                if owner.process.poll() is not None and owner.eof and owner.events.empty():break
            code=owner.process.returncode;owner.close()
            self.assertTrue(owner.closed and owner.descendants_empty and owner.eof)
            self.assertEqual(code,0,'\n'.join(logs))
        finally:
            if not owner.closed:owner.terminate();owner.close()
        return json.loads(out.read_bytes())

    def test_ordinary_preparation_freshness_and_coverage_have_self_contained_origins(self):
        result=self.prepare();self.assertEqual((result['latest'],result['stocks']),('2026-10-20',2))
        self.assertTrue(result['module_origins'])

    def test_terminated_preparation_closes_domain_and_preserves_published_database(self):
        self.prepare();files=[self.root/'data/research.sqlite']
        before=[hashlib.sha256(p.read_bytes()).hexdigest() for p in files];ready=self.base/'stop-ready'
        owner=OwnedProcess([sys.executable,'-I','-B','-X','utf8','-c',STOP,str(self.root),str(ready)],
            limits=ProcessLimits(2*1024**3,16,25,user_cpu_seconds=360 if os.name=='nt' else None,close_seconds=10,
                                 output_bytes=1024**2,frame_bytes=65536,queued_events=128))
        try:
            owner.start();deadline=time.monotonic()+10
            while not ready.exists():
                self.assertLess(time.monotonic(),deadline,'Preparation pause not reached')
                event=owner.event(.05)
                if event and event.get('event')=='failed':self.fail('Owned fixture failed')
                self.assertIsNone(owner.process.poll(),'Preparation exited before controlled stop')
            if os.name=='nt':
                self.assertEqual(owner.capabilities()['user_cpu_time']['bound'],360)
                self.assertEqual(owner.capabilities()['user_cpu_time']['status'],'hard')
            owner.terminate();owner.close()
            self.assertTrue(all(owner.closure()[k] for k in ('closed','eof','reader_stopped','streams_closed','descendants_empty','native_handles_released')))
        finally:
            if not owner.closed:owner.terminate();owner.close()
        self.assertEqual([hashlib.sha256(p.read_bytes()).hexdigest() for p in files],before)
        # A fresh process must acquire both owners and accept the old published database.
        verify=r'''from pathlib import Path
import sys
root=Path(sys.argv[1]);sys.path[:0]=[str(root)]
from website import runtime_access
with runtime_access.ownership(root,timeout=0):
 sys.path.insert(0,str(root))
 from backtest.runtime import cache_access
 from backtest.inputs import research
 with cache_access.access(timeout=0):
  db=research.connect(full_prices=True);db.close()
'''
        result=subprocess.run([sys.executable,'-I','-B','-c',verify,str(self.root)],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr.decode())


if __name__=='__main__':unittest.main()
