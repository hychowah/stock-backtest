"""Candidate execution failure leaves a separate ordinary synthetic service usable."""
from http.client import HTTPConnection
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from candidate_browser_fixture import FictionalWorkspace,CandidateService
from bench_source_service_fixture import SourceService


class IsolationTests(unittest.TestCase):
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
