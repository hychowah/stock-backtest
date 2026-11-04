"""WSL loopback-only scalar admission, preview and immutable HTTP reader surface."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from http.server import ThreadingHTTPServer
import http.client
import json
import subprocess
import tempfile
from threading import Event, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from backtest.application import jobs, library, queue, result_access
from website.server import app
from test_custom_strategy_execution import ExecutionTests, formula_failure


class HttpTests(ExecutionTests):
    # Only these tests are loaded below; shared setup/fixtures retain actual owners.
    def setUp(self):
        super().setUp()
        class Handler(app.Handler):
            def log_message(self,*args):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.calculations=self.calc
        self.manager=jobs.Jobs(self.calc,evidence_root=Path(self.folder.name)/'http-jobs')
        self.server.backtest_jobs=self.manager
        self.server.result_access=result_access.ResultAccess(self.manager,
            library.Store(Path(self.folder.name)/'saved.sqlite'),queue.Store(Path(self.folder.name)/'queue.sqlite'))
        self.thread=Thread(target=self.server.serve_forever,daemon=False);self.thread.start()
        self.addCleanup(self.close_server)
    def close_server(self):
        self.server.shutdown();self.thread.join();self.server.result_access.close();self.manager.close();self.server.server_close()
    def request(self,path,payload=None,*,method='POST',headers=None):
        client=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        try:
            client.request(method,path,json.dumps(payload).encode() if payload is not None else None,
                {'Content-Type':'application/json',**(headers or {})})
            response=client.getresponse();body=response.read()
            return response.status,body,dict(response.headers)
        finally:client.close()
    def test_http_preview_is_explicit_bounded_and_does_not_create_job(self):
        roots=[dict(symbol='A0000',pool='cached',mode='historical',date='2015-01-02')]
        status,body,_=self.request('/api/variable-preview',dict(strategy=self.capture.to_dict(),roots=roots))
        self.assertEqual(status,200,body)
        self.assertEqual(json.loads(body)['population'],'explicit-request-scopes')
        self.assertEqual(json.loads(body)['producer']['engine'],'original')
        self.assertEqual(self.manager.runs,{})
        status,body,_=self.request('/api/variable-preview',dict(strategy=self.capture.to_dict(),roots=roots,engine='experimental'))
        self.assertEqual(status,400,body)
        self.assertEqual((json.loads(body)['code'],json.loads(body)['path']),('UNSUPPORTED_CAPABILITY','/engine'))
        self.assertFalse(self.opened);self.assertFalse(self.manager.runs)
        status,body,_=self.request('/api/variable-preview',dict(strategy=self.capture.to_dict(),roots=roots*17))
        self.assertEqual(status,400)
        self.assertEqual(json.loads(body)['code'],'WORK_LIMIT')
    def test_http_origin_and_experimental_admission_precede_work(self):
        self.assertEqual(self.request('/api/variable-preview',{},headers={'Origin':'http://foreign.test'})[0],403)
        status,body,_=self.request('/api/backtest-runs/'+'a'*32,dict(mode='custom',options=self.options(engine='experimental')))
        self.assertEqual(status,400,body)
        failure=json.loads(body)
        self.assertEqual((failure['code'],failure['path']),('UNSUPPORTED_CAPABILITY','/engine'))
        self.assertEqual(failure['errors'][0]['code'],failure['code'])
        self.assertFalse(self.manager.runs);self.assertFalse(self.opened)
    def test_http_scalar_failures_keep_diagnostics_and_legacy_error_shape(self):
        error=formula_failure()
        with patch('website.server.backtests.strategy_requests.check_request',side_effect=error):
            status,body,_=self.request('/api/backtest-runs/'+'d'*32,dict(mode='custom',options=self.options()))
        self.assertEqual(status,400,body)
        self.assertEqual(json.loads(body)['errors'],error.to_dict()['errors'])
        store=queue.Store(Path(self.folder.name)/'admission-queue.sqlite')
        self.server.backtest_queue=SimpleNamespace(store=store,start=lambda:None,wake=Event())
        request=dict(id='e'*32,name='Scalar',mode='custom',options=self.options(engine='experimental'),catalog=dict(metrics={},filters={}),presentation={})
        status,body,_=self.request('/api/backtest-queue',request)
        self.assertEqual(status,400,body)
        self.assertEqual((json.loads(body)['code'],json.loads(body)['path']),('UNSUPPORTED_CAPABILITY','/engine'))
        self.assertEqual(store.listing()['records'],[])
        request['options']=self.options()
        store.enqueue(request)
        consumer=queue.Queue(store,calculations=self.calc,library=library.Store(Path(self.folder.name)/'failure-saved.sqlite'))
        self.addCleanup(consumer.close)
        with patch.object(self.calc,'calculate_into',side_effect=error):consumer._run(store.claim())
        status,body,_=self.request('/api/backtest-queue/'+request['id'],method='GET')
        self.assertEqual(status,200,body)
        self.assertEqual(json.loads(body)['errors'],error.to_dict()['errors'])
        with patch.object(self.calc,'calculate_into',side_effect=error):
            status,body,_=self.request('/api/backtest-runs/'+'f'*32,dict(mode='custom',options=self.options()))
            self.assertEqual(status,202,body)
            self.manager.runs['f'*32]['thread'].join(10)
        status,body,_=self.request('/api/backtest-runs/'+'f'*32+'/status',method='GET')
        self.assertEqual(status,200,body)
        failure=json.loads(body)
        self.assertEqual(failure['state'],'failed')
        self.assertEqual((failure['error'],failure['code'],failure['path']),(str(error),error.code,error.path))
        self.assertEqual(failure['errors'],error.to_dict()['errors'])
        status,body,_=self.request('/api/backtest-runs/'+'c'*32,dict(mode='unsupported',options={}))
        self.assertEqual(status,400,body)
        self.assertEqual(set(json.loads(body)),{'error'})
    def test_http_job_reader_and_complete_export_are_original_bytes(self):
        status,body,_=self.request('/api/backtest-runs/'+'b'*32,dict(mode='custom',options=self.options()))
        self.assertEqual(status,202,body)
        self.manager.runs['b'*32]['thread'].join(10)
        status,body,_=self.request('/api/backtest-runs/'+'c'*32+'/reader',dict(source=dict(kind='run',id='b'*32)))
        self.assertEqual(status,200,body)
        artifact=json.loads(body);self.assertEqual(artifact['version'],4)
        base='/api/backtest-runs/'+'c'*32+'/reader/'
        status,body,_=self.request(base+'page/scopes/1/0',method='GET')
        self.assertEqual(status,200,body);self.assertEqual(json.loads(body)['rows'][0]['rows'],12)
        status,body,headers=self.request(base+'export/evidence/1',method='GET')
        self.assertEqual(status,200);self.assertEqual(int(headers['Content-Length']),len(body))
        self.assertEqual(headers['Content-Type'],'application/octet-stream')
        self.assertEqual(self.request(base[:-1],method='DELETE')[0],200)
        self.assertEqual(self.request(base+'page/scopes/1/0',method='GET')[0],400)


class FrozenEngineAdmissionTests(unittest.TestCase):
    def test_formula_requests_naming_experimental_load_no_numerical_code(self):
        # A fresh process, so imports made by other tests cannot hide one.
        code='''
import json,sys,tempfile
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Event,Thread
from types import SimpleNamespace
sys.path[:0]=[sys.argv[1],sys.argv[2]]
from backtest.application import jobs,queue,strategy_requests as s
from backtest.application.original_calculations import Original
from website.server import app
import test_strategy_requests as requests,test_variable_definitions as language
authored=language.entry(language.definition(dict(op='parameter',id='annual.revenue'),'USD','usd'),'draft:ranking')
capture=s.capture_strategy(requests.intent(requests.formula(authored)),submitted=[authored]).to_dict()
options=dict(strategy=capture,start='2015-01-02',end='2015-01-05',months=12,engine='experimental')
class Handler(app.Handler):
    def log_message(self,*args):pass
with tempfile.TemporaryDirectory() as folder:
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.calculations=Original()
    server.backtest_jobs=jobs.Jobs(server.calculations,evidence_root=Path(folder)/'jobs')
    server.backtest_queue=SimpleNamespace(store=queue.Store(Path(folder)/'queue.sqlite'),start=lambda:None,wake=Event())
    thread=Thread(target=server.serve_forever);thread.start()
    try:
        for path,body in (('/api/backtest-runs/'+'a'*32,dict(mode='custom',options=options)),
                          ('/api/backtest-queue',dict(id='b'*32,name='Frozen',mode='custom',options=options,
                                                      catalog=dict(metrics={},filters={}),presentation={}))):
            client=HTTPConnection(*server.server_address,timeout=10)
            client.request('POST',path,json.dumps(body),{'Content-Type':'application/json'})
            response=client.getresponse();failure=json.loads(response.read());client.close()
            assert response.status==400 and (failure['code'],failure['path'])==('UNSUPPORTED_CAPABILITY','/engine'),(path,response.status,failure)
        assert server.backtest_jobs.runs=={} and server.backtest_queue.store.listing()['records']==[]
    finally:
        server.shutdown();thread.join();server.backtest_jobs.close();server.server_close()
loaded=[name for name in sys.modules if name.startswith('backtest.engines.numerical')]
assert not loaded,loaded
'''
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            result=subprocess.run([sys.executable,'-I','-B','-c',code,str(root),str(root/'tests')],
                                  cwd=folder,capture_output=True,text=True,timeout=120)
        self.assertEqual(result.returncode,0,result.stderr)


def load_tests(loader,tests,pattern):
    return unittest.TestSuite([*(HttpTests(name) for name in ('test_http_preview_is_explicit_bounded_and_does_not_create_job',
        'test_http_origin_and_experimental_admission_precede_work','test_http_scalar_failures_keep_diagnostics_and_legacy_error_shape',
        'test_http_job_reader_and_complete_export_are_original_bytes')),
        FrozenEngineAdmissionTests('test_formula_requests_naming_experimental_load_no_numerical_code')])

if __name__=='__main__':unittest.main()
