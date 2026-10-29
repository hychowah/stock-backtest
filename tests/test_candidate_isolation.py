"""Candidate execution failure leaves a separate ordinary synthetic service usable."""
from http.client import HTTPConnection
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import unittest
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))
from candidate_browser_fixture import FictionalWorkspace,CandidateService
from bench_source_service_fixture import SourceService


class IsolationTests(unittest.TestCase):
    def test_preparation_execution_and_restart_preserve_private_stable_service(self):
        # This ordinary service is private and fictional. It cannot qualify the
        # installed runtime. Polls prove successful service, not zero-delay access.
        with FictionalWorkspace() as stable,FictionalWorkspace() as candidate:
            ordinary=CandidateService(stable,scenario='ordinary-workflow').start()
            preview=CandidateService(candidate)
            observations=[]
            options=dict(start='2015-01-02',end='2015-02-27',months=1,rank_to=3)
            def request(service,path,body=None):
                c=HTTPConnection('127.0.0.1',service.port,timeout=120)
                try:
                    c.request('GET' if body is None else 'POST',path,
                        None if body is None else json.dumps(body),
                        {} if body is None else {'Content-Type':'application/json'})
                    response=c.getresponse();content=response.read();self.assertEqual(response.status,200)
                    return content
                finally:c.close()
            original=json.loads(request(ordinary,'/api/schedule',options));original.pop('seconds')
            def probe(stage):
                began=time.monotonic()
                for path in ('/','/data.html'):self.assertTrue(request(ordinary,path))
                actual=json.loads(request(ordinary,'/api/schedule',options));actual.pop('seconds')
                self.assertEqual(actual,original)
                observations.append(dict(stage=stage,seconds=time.monotonic()-began))
            try:
                with ThreadPoolExecutor(max_workers=1) as worker:
                    preparing=worker.submit(preview.start)
                    while not preparing.done():probe('preparation')
                    preparing.result()
                    job=dict(mode='random',options=dict(calendar=dict(version=1,start='2015-01-02',
                        end='2015-02-27',interval=dict(unit='week',count=1)),trials=24,seed=42,rank_to=3))
                    executing=worker.submit(request,preview,'/api/robustness',job['options'])
                    while not executing.done():probe('execution')
                    lines=executing.result().decode().splitlines()
                    self.assertTrue(any(json.loads(line).get('type')=='complete' for line in lines))
                    preview.close();preview=CandidateService(candidate)
                    restarting=worker.submit(preview.start)
                    while not restarting.done():probe('restart')
                    restarting.result()
                for stage in ('preparation','execution','restart'):
                    self.assertTrue(any(row['stage']==stage for row in observations),stage)
                self.assertEqual(stable.inputs,stable.input_inventory())
            finally:preview.close();ordinary.close()
            print(json.dumps(dict(check='private-stable-preparation-execution-restart',observations=observations,
                sources=stable.sources,inputs=stable.inputs,candidate_closure=preview.owner.closure(),
                stable_closure=ordinary.owner.closure())),flush=True)

    def test_execution_failure_preserves_stable_service(self):
        with FictionalWorkspace() as stable,FictionalWorkspace() as candidate:
            ordinary=CandidateService(stable,scenario='ordinary-workflow').start()
            preview=CandidateService(candidate).start()
            def post(service,path,body):
                connection=HTTPConnection('127.0.0.1',service.port,timeout=120)
                try:
                    connection.request('POST',path,json.dumps(body),{'Content-Type':'application/json'})
                    response=connection.getresponse();return response.status,json.loads(response.read())
                finally:connection.close()
            options=dict(start='2015-01-02',end='2015-02-27',months=1,rank_to=3)
            try:
                status,before=post(ordinary,'/api/schedule',options);self.assertEqual(status,200)
                invalid=dict(calendar=dict(version=1,start=options['start'],end=options['end'],interval=dict(unit='week',count=1)),metric='nonexistent')
                self.assertEqual(post(preview,'/api/schedule',invalid)[0],400)
                status,after=post(ordinary,'/api/schedule',options);self.assertEqual(status,200)
                for result in (before,after):result.pop('seconds')
                self.assertEqual(before,after)
                self.assertEqual(stable.inputs,stable.input_inventory())
                preview.close()
                failed=CandidateService(candidate,scenario='dependencies').start()
                try:
                    self.assertEqual(post(failed,'/api/schedule',options)[0],503)
                    self.assertEqual(post(ordinary,'/api/schedule',options)[0],200)
                finally:failed.close()
            finally:preview.close();ordinary.close()
            print(json.dumps(dict(check='candidate-failure-stable-isolation',candidate=preview.owner.closure(),stable=ordinary.owner.closure())),flush=True)


if __name__=='__main__':unittest.main()
