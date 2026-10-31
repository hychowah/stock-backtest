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
from process_owner import OwnedProcess, ProcessLimits


def write_fixture(root):
    raw=root/'raw';(raw/'px').mkdir(parents=True);(raw/'financial-inputs').mkdir()
    (root/'results').mkdir();(root/'results/summary-exits.txt').write_text('Through 2026-10-20\n')
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
sys.path[:0]=[str(root/'scripts'),str(root/'website'),str(root/'tools')]
import runtime_access
with runtime_access.ownership(root,timeout=0):
 import run
 run.KEY_PATH=root.parent/'nonexistent-preparation-key';assert not run.KEY_PATH.exists()
 import research as r,schedules as s,prepared_input_coverage as coverage
 for m in (r,s,r.run,r.books,r.metrics,r.baseline,r.cache_assets,r.financial_inputs,r.revalue,r.cache_access,s.portfolio_results,s.schedule_calendar,coverage):
  assert Path(m.__file__).resolve().is_relative_to(root.resolve()),m.__name__
 assert run.FIRST_YEAR==1996 and run.LAST_YEAR==2026
 r.prepare();s.prepare()
 result=coverage.report()
 assert len(result['years'])==31 and all(y['prepared_period'] for y in result['years'])
 assert all(y['pools']['legacy']['selected_holdings']==1 for y in result['years'])
 assert result['daily_books']==dict(periods=0,snapshots=0,period_pools=0)
 with closing(r.connect(full_prices=True)) as db:
  baseline=json.loads(db.execute("SELECT value FROM metadata WHERE key='baseline_result'").fetchone()[0])
  assert len(baseline['years'])==31 and sum(len(y['holdings']) for y in baseline['years'])==31
  audit=r.baseline.Baseline(r.RESULTS,r.DATABASE).audit(db)
  assert audit['details']['bootstrap']
  previous=r.RESULTS/audit['summary']['audit'];previous=previous.parent/'previous-snapshot.json'
  assert json.loads(previous.read_bytes()) is None
 assert str(r.baseline.cutoff((root/'results/summary-exits.txt').read_text()))=='2026-10-20'
 out.write_text(json.dumps(dict(status='prepared',years=31,holdings=31,through=result['through'],module_origins=True,daily_books=result['daily_books'])))
'''

STOP=r'''
assert __import__('sys').stdin.readline()=='GO'+chr(10)
from pathlib import Path
import sqlite3,sys,time
root=Path(sys.argv[1]);ready=Path(sys.argv[2])
sys.path[:0]=[str(root/'scripts'),str(root/'website')]
import runtime_access
with runtime_access.ownership(root,timeout=0):
 import run
 run.KEY_PATH=root.parent/'nonexistent-preparation-key'
 import research
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
        for path in (ROOT/'scripts').glob('*.py'):shutil.copyfile(path,self.root/'scripts'/path.name)
        shutil.copyfile(ROOT/'website/runtime_access.py',self.root/'website/runtime_access.py')
        shutil.copyfile(ROOT/'tools/prepared_input_coverage.py',self.root/'tools/prepared_input_coverage.py')
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
        result=self.prepare();self.assertEqual(result['through'],'2026-10-20')
        self.assertTrue(result['module_origins']);self.assertEqual(result['years'],31)

    def test_terminated_preparation_closes_domain_and_preserves_published_pair(self):
        self.prepare();files=[self.root/'data/research.sqlite',self.root/'results/summary-exits.txt']
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
        # A fresh process must acquire both owners and accept the old published pair.
        verify=r'''from pathlib import Path
import sys
root=Path(sys.argv[1]);sys.path[:0]=[str(root/'scripts'),str(root/'website')]
import runtime_access,cache_access,research
with runtime_access.ownership(root,timeout=0),cache_access.access(timeout=0):
 db=research.connect(full_prices=True);db.close()
'''
        result=subprocess.run([sys.executable,'-I','-B','-c',verify,str(self.root)],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr.decode())


if __name__=='__main__':unittest.main()
