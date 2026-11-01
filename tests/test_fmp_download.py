"""Bounded parallelism, cancellable retries and shared request-start timing."""
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import sys
from threading import Event, Lock, Thread, get_ident
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.inputs import fmp_download as f


class Response:
    """Model Python 3.12 read1 EOF without implicit response closure."""
    def __init__(self,body=b'[]',status=200,encoding=None,retry_after=None):
        self.parts=[body[i:i+11] for i in range(0,len(body),11)]+[b'']
        self.status=status;self.headers={'Content-Encoding':encoding,'Retry-After':retry_after};self.closed=False
    def read1(self,size):return self.parts.pop(0)
    def getheader(self,key):return self.headers.get(key)
    def close(self):self.closed=True


class Connection:
    sock=None
    def __init__(self,*responses):
        self.pending=iter(responses);self.response=None;self.requests=[];self.closed=False
    def request(self,*args,**kwargs):self.requests.append(kwargs['headers'])
    def getresponse(self):
        if self.response and not self.response.closed:raise f.http.client.ResponseNotReady()
        self.response=next(self.pending);return self.response
    def close(self):self.closed=True


class ClientTests(unittest.TestCase):
    def test_gzip_and_plain_success_share_the_decoded_list_interface(self):
        payload=[{'symbol':'A','date':'2020-01-02','adjClose':10}]
        body=json.dumps(payload).encode()
        responses=[Response(gzip.compress(body),encoding=' GZip '),Response(body),Response(body,encoding='identity')]
        connection=Connection(*responses)
        with f.Client() as client,patch.object(client,'_connection',return_value=connection):
            client.key='PRIVATE-CANARY';client.gate=Mock()
            for _ in responses:self.assertEqual(client.request('prices',{}),payload)
        self.assertTrue(all(r.closed for r in responses))
        self.assertTrue(all(h['Accept-Encoding']=='gzip' for h in connection.requests))

    def test_corrupt_gzip_and_unknown_encoding_reset_connections_and_retry(self):
        for encoding,body in [('gzip',b'PRIVATE-CANARY'),('gzip',gzip.compress(b'[]')[:-5]),('br',b'[]')]:
            with self.subTest(encoding=encoding,body=body[:2]):
                responses=[Response(body,encoding=encoding) for _ in range(3)]
                connections=[Connection(response) for response in responses]
                with f.Client() as client,patch.object(client,'_connection',side_effect=connections),patch.object(f.diagnostics,'failure'):
                    client.key='PRIVATE-CANARY';client.gate=Mock()
                    with self.assertRaises(ValueError) as error:client.request('prices',{})
                    self.assertEqual(client.gate.enter.call_count,3)
                    self.assertEqual(client.gate.pause.call_count,2)
                    self.assertIsNone(client.local.connection)
                self.assertNotIn('PRIVATE-CANARY',str(error.exception))
                self.assertTrue(all(r.closed for r in responses))
                self.assertTrue(all(c.closed for c in connections))

    def test_encoded_error_body_cannot_hide_status_or_retry_after(self):
        responses=[Response(b'broken gzip PRIVATE-CANARY',429,'gzip','7'),
                   Response(gzip.compress(b'[]'),encoding='gzip')]
        connection=Connection(*responses)
        with f.Client() as client,patch.object(client,'_connection',return_value=connection):
            client.key='PRIVATE-CANARY';client.gate=Mock()
            self.assertEqual(client.request('prices',{}),[])
            client.gate.pause.assert_called_once_with(7.,throttled=True)
        self.assertTrue(all(r.closed for r in responses))

    def test_encoded_permanent_error_does_not_retry(self):
        response=Response(b'broken gzip PRIVATE-CANARY',403,'gzip','7');connection=Connection(response)
        with f.Client() as client,patch.object(client,'_connection',return_value=connection):
            client.key='PRIVATE-CANARY';client.gate=Mock()
            with self.assertRaisesRegex(ValueError,'status 403') as error:client.request('prices',{})
            client.gate.pause.assert_not_called()
        self.assertEqual(len(connection.requests),1);self.assertTrue(response.closed)
        self.assertNotIn('PRIVATE-CANARY',str(error.exception))

    def test_invalid_json_after_decompression_keeps_invalid_response_error(self):
        for body in [b'PRIVATE-CANARY',b'{"error":"PRIVATE-CANARY"}']:
            response=Response(gzip.compress(body),encoding='gzip');connection=Connection(response)
            with f.Client() as client,patch.object(client,'_connection',return_value=connection):
                client.key='PRIVATE-CANARY';client.gate=Mock()
                with self.assertRaisesRegex(ValueError,'invalid response') as error:client.request('prices',{})
            self.assertEqual(len(connection.requests),1);self.assertTrue(response.closed)
            self.assertNotIn('PRIVATE-CANARY',str(error.exception))

    def test_start_gate_advances_only_after_actual_start(self):
        now=[0.];starts=[]
        client=Mock();client.sleep.side_effect=lambda seconds:now.__setitem__(0,now[0]+seconds)
        gate=f.StartGate(4)
        with patch.object(f.time,'monotonic',side_effect=lambda:now[0]):
            for _ in range(4):gate.enter(client);starts.append(now[0])
            gate.pause(2,True);gate.enter(client);starts.append(now[0])
        self.assertEqual(starts[:4],[0,.25,.5,.75])
        self.assertAlmostEqual(starts[-1],2.75)
        self.assertEqual(gate.interval,.5)

    def test_default_gate_spaces_attempts_and_halves_rate_after_429(self):
        now=[0.];starts=[]
        with f.Client() as client:
            self.assertEqual(client.workers,32)
            client.sleep=lambda seconds:now.__setitem__(0,now[0]+seconds)
            with patch.object(f.time,'monotonic',side_effect=lambda:now[0]):
                for _ in range(4):client.gate.enter(client);starts.append(now[0])
                client.gate.pause(2,True);client.gate.enter(client)
            for i,t in enumerate(starts):self.assertAlmostEqual(t,i/45)
            self.assertAlmostEqual(client.gate.interval,2/45)
            self.assertAlmostEqual(now[0],starts[-1]+2)

    def test_rate_limit_and_retry_after_are_shared(self):
        with f.Client() as client:
            client.gate=Mock()
            with patch.object(client,'_once',side_effect=[(429,b'', '2'),(503,b'','4'),(200,b'[]',None)]):
                self.assertEqual(client.request('prices',{}),[])
            self.assertEqual(client.gate.enter.call_count,3)
            self.assertEqual(client.gate.pause.call_args_list[0].args,(2.,))
            self.assertTrue(client.gate.pause.call_args_list[0].kwargs['throttled'])
            self.assertEqual(client.gate.pause.call_args_list[1].args,(4.,))

    def test_permanent_failure_does_not_retry_or_expose_response(self):
        with f.Client() as client:
            client.gate=Mock()
            with patch.object(client,'_once',return_value=(403,b'PRIVATE-CANARY',None)) as once,self.assertRaises(ValueError) as error:
                client.request('prices',{})
            self.assertEqual(once.call_count,1)
            self.assertNotIn('PRIVATE-CANARY',str(error.exception))

    def test_transient_failure_is_bounded(self):
        with f.Client() as client:
            client.gate=Mock()
            with patch.object(client,'_once',return_value=(0,b'',None)) as once,self.assertRaises(ValueError):client.request('prices',{})
            self.assertEqual(once.call_count,3)

    def test_cancel_interrupts_cooldown_without_another_attempt(self):
        cancel=Event();waiting=Event();errors=[]
        def stop():
            if cancel.is_set():raise f.Cancelled()
        with f.Client(stop,lambda **kw:waiting.set()) as client:
            with patch.object(client,'_once',return_value=(429,b'','60')) as once:
                def run():
                    try:client.request('prices',{})
                    except f.Cancelled:errors.append('cancelled')
                thread=Thread(target=run);thread.start()
                self.assertTrue(waiting.wait(2));cancel.set();thread.join(2)
                self.assertFalse(thread.is_alive());self.assertEqual(errors,['cancelled'])
                self.assertEqual(once.call_count,1)

    def test_limited_submission_and_single_caller_result_consumption(self):
        gate=Event();started=Event();lock=Lock();active=[0];maximum=[0];planned=[];threads=[]
        def tasks():
            for i in range(100):planned.append(i);yield i
        def fetch(i):
            with lock:
                active[0]+=1;maximum[0]=max(maximum[0],active[0])
                if active[0]==32:started.set()
            gate.wait(3)
            with lock:active[0]-=1
            return i
        with f.Client() as client:
            result=client.map(tasks(),fetch)
            with ThreadPoolExecutor(max_workers=1) as driver:
                future=driver.submit(next,result)
                self.assertTrue(started.wait(2));self.assertEqual(len(planned),32)
                gate.set();first=future.result(2)
            owner=get_ident();remaining=[]
            for task,value in result:threads.append(get_ident());remaining.append((task,value))
        self.assertEqual(maximum[0],32)
        self.assertEqual(len(remaining)+1,100);self.assertTrue(all(t==owner for t in threads))
        self.assertEqual(sorted([first]+remaining),[(i,i) for i in range(100)])

    def test_error_cancels_pending_work_and_joins_workers(self):
        started=Event();gate=Event();planned=[]
        def tasks():
            for i in range(100):planned.append(i);yield i
        with f.Client(workers=4) as client:
            def fetch(i):
                if i==0:started.set();gate.wait(2);raise ValueError('Failed window')
                while not client.abort.wait(.01):client.check()
                raise f.Cancelled()
            iterator=client.map(tasks(),fetch)
            gate.set()
            with self.assertRaisesRegex(ValueError,'Failed window'):list(iterator)
            self.assertLessEqual(len(planned),4)
        self.assertTrue(all(not thread.is_alive() for thread in client.pool._threads))

    def test_exhausted_response_is_closed_before_connection_reuse(self):
        responses=[Response(),Response()];connection=Connection(*responses)
        with f.Client() as client,patch.object(client,'_connection',return_value=connection):
            client.key='test-key'
            self.assertEqual(client._once('prices',{})[0],200)
            self.assertEqual(client._once('prices',{})[0],200)
        self.assertEqual(len(connection.requests),2)
        self.assertTrue(all(response.closed for response in responses))

    def test_empty_plan_does_not_read_key_or_connect(self):
        with f.Client() as client,patch.object(client,'_once',side_effect=AssertionError('No network')):
            self.assertEqual(list(client.map([],lambda i:client.request('prices',{}))),[])
            self.assertIsNone(client.key)


if __name__=='__main__':unittest.main()
