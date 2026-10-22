"""Bounded parallelism, cancellable retries and shared request-start timing."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from threading import Event, Lock, Thread, get_ident
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import fmp_download as f


class ClientTests(unittest.TestCase):
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
                if active[0]==4:started.set()
            gate.wait(3)
            with lock:active[0]-=1
            return i
        with f.Client(workers=4) as client:
            result=client.map(tasks(),fetch)
            with ThreadPoolExecutor(max_workers=1) as driver:
                future=driver.submit(next,result)
                self.assertTrue(started.wait(2));self.assertEqual(len(planned),4)
                gate.set();first=future.result(2)
            owner=get_ident();remaining=[]
            for task,value in result:threads.append(get_ident());remaining.append((task,value))
        self.assertLessEqual(maximum[0],4);self.assertGreater(maximum[0],1)
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
        # Mirrors Python 3.12 read1(): EOF alone does not mark isclosed().
        class Response:
            status=200
            def __init__(self):self.parts=[b'[]',b''];self.closed=False
            def read1(self,size):return self.parts.pop(0)
            def getheader(self,key):return None
            def close(self):self.closed=True
        class Connection:
            sock=None
            def __init__(self):self.response=None;self.responses=[]
            def request(self,*args,**kwargs):pass
            def getresponse(self):
                if self.response and not self.response.closed:raise f.http.client.ResponseNotReady()
                self.response=Response();self.responses.append(self.response);return self.response
            def close(self):pass
        connection=Connection()
        with f.Client() as client,patch.object(client,'_connection',return_value=connection):
            client.key='test-key'
            self.assertEqual(client._once('prices',{})[0],200)
            self.assertEqual(client._once('prices',{})[0],200)
        self.assertEqual(len(connection.responses),2)
        self.assertTrue(all(response.closed for response in connection.responses))

    def test_empty_plan_does_not_read_key_or_connect(self):
        with f.Client() as client,patch.object(client,'_once',side_effect=AssertionError('No network')):
            self.assertEqual(list(client.map([],lambda i:client.request('prices',{}))),[])
            self.assertIsNone(client.key)


if __name__=='__main__':unittest.main()
