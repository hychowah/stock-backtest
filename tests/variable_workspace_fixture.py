"""Private current-source browser fixture. Never starts or prepares the real app.

Render fictional HTML with the reviewed external fixture runner first. All API
owners then use private synthetic SQLite and durable stores. Ctrl+C closes jobs,
readers, queue and connections before test-owned files are removed.
"""
import argparse
from contextlib import closing
import json
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import re
import signal
import sqlite3
import sys
from threading import Event, Thread
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from backtest.application import jobs, queue, library as saved, result_access, temporary_evidence
from backtest.variables import library
from backtest.inputs import observation_inputs
from website.server import app, variables, backtests, results
from test_custom_strategy_execution import ExecutionTests
from test_scalar_execution import Fixture


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True);args=parser.parse_args()
    root=args.directory.resolve();owner=root.parent
    assert root.name=='browser-fixture' and owner.parent==Path('/tmp') and owner.name.startswith('cv-phase6-browser-')
    assert (owner/'fixture-owner.json').is_file() and (root/'source-binding.json').is_file()
    case=ExecutionTests();case.setUp();stop=Event()
    try:
        fixture=Fixture(80)
        with closing(sqlite3.connect(case.path)) as db:
            fixture.db.backup(db)
            for table,column in [('snapshots','year'),('periods','year'),('screening_metrics','year'),('filter_values','year'),('period_pools','period_id')]:
                db.execute('UPDATE '+table+' SET '+column+'=2015 WHERE '+column+'=1')
            scopes=[dict(mode='latest',pool=pool,context_date='2015-01-05',book=0) for pool in ('legacy','cached')]
            scopes += [dict(mode='historical',pool=pool,context_date='2015-01-02',book=2015) for pool in ('legacy','cached')]
            db.execute('DELETE FROM observation_metadata')
            observation_inputs.finish(db,'2015-01-05',scopes=scopes)
            db.commit()
        fixture.db.close()
        html=(root/'index.html').read_text()
        pattern=r'(<script id="screening-data" type="application/json">)(.*?)(</script>)'
        match=re.search(pattern,html,re.S);assert match
        data=json.loads(match[2]);data['latest']['metadata'].update(asof='2015-01-05',eligible_financials=len(data['companies']))
        for pool in ('legacy','cached'):
            for row in data['latest'][pool]:
                row[2:5]=['2014-06-30','2014-09-28','2015-01-05']
        html=html[:match.start(2)]+json.dumps(data).replace('<','\\u003c')+html[match.end(2):]
        (root/'index.html').write_text(html)
        library_store=library.Store(owner/'variables.sqlite')
        class Handler(app.Handler):
            def __init__(self,*args,**kwargs):SimpleHTTPRequestHandler.__init__(self,*args,directory=str(root),**kwargs)
            def log_message(self,*args):pass
            def dispatch(self):
                if self.path=='/favicon.ico':self.send_response(204);self.end_headers();return True
                if variables.dispatch(self):return True
                if results.dispatch(self,self.server.saved_store):return True
                return backtests.dispatch(self,type('DataState',(),{'rebuilt':True})())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        server.calculations=case.calc;server.variable_store=library_store
        server.saved_store=saved.Store(owner/'saved.sqlite')
        server.backtest_jobs=jobs.Jobs(case.calc,evidence_root=owner/'jobs')
        server.backtest_queue=queue.Queue(queue.Store(owner/'queue.sqlite'),calculations=case.calc,library=server.saved_store)
        server.backtest_queue.evidence=temporary_evidence.Workspace(owner/'queue-evidence')
        server.backtest_queue.store.pause(True)
        server.result_access=result_access.ResultAccess(server.backtest_jobs,server.saved_store,server.backtest_queue.store)
        thread=Thread(target=server.serve_forever,daemon=False);thread.start()
        for name in ('SIGINT','SIGTERM'):
            signal.signal(getattr(signal,name),lambda *_:stop.set())
        receipt=dict(url='http://127.0.0.1:'+str(server.server_port),pid=__import__('os').getpid(),directory=str(root),
                     samples=['A0000','A0001','UNKNOWN'],latest='2015-01-05',historical='2015-01-02',january=[2015,2015],
                     fixed=dict(start='2015-01-02',end='2015-01-05',months=12),pool_count=80,
                     source_binding=json.loads((root/'source-binding.json').read_text()),synthetic_only=True)
        (owner/'server.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt),flush=True)
        stop.wait()
        server.shutdown();thread.join();server.backtest_queue.close();server.result_access.close();server.backtest_jobs.close();server.server_close()
        print(json.dumps(dict(closed=True,private_directory=str(owner),connections_remaining=len(case.opened))),flush=True)
    finally:case.doCleanups()


if __name__=='__main__':main()
