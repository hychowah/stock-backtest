"""Bounded FMP requests with reusable connections and cancellable retries.

Only workers fetch. The caller consumes completed results and owns publication.
Up to 32 requests may be in flight, with at most 45 starts per second.
Successful gzip responses are decoded here; callers receive ordinary JSON lists.
A provider cooldown applies to every worker, without reserving future slots.
No exception from the HTTP implementation can expose credentials or request URLs.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from email.utils import parsedate_to_datetime
import gzip
import http.client
import json
import threading
import time
import urllib.parse

import run
import diagnostics

WORKERS=32
STARTS_PER_SECOND=45.0
SOCKET_TIMEOUT=15
REQUEST_DEADLINE=30
ATTEMPTS=3


class Cancelled(Exception):
    pass


class StartGate:
    def __init__(self,rate=STARTS_PER_SECOND):
        self.lock=threading.Lock();self.interval=1/rate
        self.last=-float('inf');self.paused_until=0.

    def enter(self,client):
        while True:
            client.check()
            with self.lock:
                now=time.monotonic()
                delay=max(self.last+self.interval,self.paused_until)-now
                if delay<=0:self.last=now;return
            client.sleep(min(delay,.1))

    def pause(self,seconds,throttled=False):
        with self.lock:
            self.paused_until=max(self.paused_until,time.monotonic()+seconds)
            if throttled:self.interval=min(2.,self.interval*2)


class Client:
    """Fetch decoded lists with shared pacing and bounded outstanding work.

    The context joins active workers before returning cache ownership to callers.
    Transport and encoding failures share bounded retries and safe diagnostics.
    """
    def __init__(self,stop=lambda:None,emit=lambda **kw:None,*,workers=WORKERS,rate=STARTS_PER_SECOND):
        self.external_stop=stop;self.emit=emit;self.workers=workers
        self.gate=StartGate(rate);self.abort=threading.Event();self.local=threading.local()
        self.connections=[];self.lock=threading.Lock();self.key=None;self.pool=None

    def check(self):
        self.external_stop()
        if self.abort.is_set():raise Cancelled()

    def sleep(self,seconds):
        end=time.monotonic()+seconds
        while True:
            self.check();remaining=end-time.monotonic()
            if remaining<=0:return
            self.abort.wait(min(.1,remaining))

    def _connection(self):
        connection=getattr(self.local,'connection',None)
        if connection is None:
            connection=http.client.HTTPSConnection('financialmodelingprep.com',timeout=SOCKET_TIMEOUT)
            self.local.connection=connection
            with self.lock:self.connections.append(connection)
        return connection

    def _once(self,endpoint,params):
        deadline=time.monotonic()+REQUEST_DEADLINE
        connection=self._connection()
        try:
            with self.lock:
                if self.key is None:self.key=run.KEY_PATH.read_text(encoding='utf-8').strip()
            query=urllib.parse.urlencode({**params,'apikey':self.key})
            connection.request('GET','/stable/'+endpoint+'?'+query,headers={'Accept':'application/json','Accept-Encoding':'gzip'})
            if connection.sock:connection.sock.settimeout(max(.01,min(SOCKET_TIMEOUT,deadline-time.monotonic())))
            response=connection.getresponse();chunks=[]
            try:
                while True:
                    self.check();remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError()
                    if connection.sock:connection.sock.settimeout(min(SOCKET_TIMEOUT,remaining))
                    chunk=response.read1(65536)
                    if not chunk:break
                    chunks.append(chunk)
                body=b''.join(chunks)
                # Error status and Retry-After take precedence over body encoding.
                if response.status==200:
                    encoding=(response.getheader('Content-Encoding') or 'identity').strip().lower()
                    if encoding=='gzip':body=gzip.decompress(body)
                    elif encoding!='identity':raise ValueError('Unsupported response encoding')
                return response.status,body,response.getheader('Retry-After')
            finally:
                # Python 3.12 read1() can leave an exhausted response open.
                # Close the response before reusing its persistent connection.
                response.close()
        except (Cancelled,FileNotFoundError):raise
        except Exception as error:
            diagnostics.failure('provider.transport_failed',error,symbol=params.get('symbol'),start=params.get('from'),end=params.get('to'))
            connection.close();self.local.connection=None
            return 0,b'',None

    @staticmethod
    def retry_delay(header,fallback):
        if header:
            try:return min(3600.,max(0.,float(header)))
            except ValueError:
                try:return min(3600.,max(0.,parsedate_to_datetime(header).timestamp()-time.time()))
                except (ValueError,TypeError,OverflowError):pass
        return fallback

    def request(self,endpoint,params):
        status=0
        for attempt in range(ATTEMPTS):
            self.gate.enter(self)
            status,body,retry_after=self._once(endpoint,params)
            self.check()
            diagnostics.event('provider.response',status=status,attempt=attempt+1,symbol=params.get('symbol'),start=params.get('from'),end=params.get('to'))
            if status==200:
                try:payload=json.loads(body)
                except (ValueError,UnicodeDecodeError):payload=None
                if isinstance(payload,list):return payload
                raise ValueError('The data provider returned an invalid response. Saved files were kept.')
            transient=status in (0,429,500,502,503,504)
            if not transient or attempt==ATTEMPTS-1:break
            delay=self.retry_delay(retry_after,2**(attempt+1))
            self.gate.pause(delay,throttled=status==429)
            diagnostics.event('provider.retry',status=status,delay=delay,attempt=attempt+1)
            self.emit(message=f'Provider retry (status {status}); waiting {delay:g}s. Saved work is kept.')
        raise ValueError(f'Data provider request failed (status {status}). Saved files were kept. Check your key, subscription or connection, then retry.')

    def map(self,tasks,fetch):
        """Yield completion-order results; retain at most workers submitted tasks.

        The iterator plans work lazily. No worker touches the cache. On failure
        or cancellation, stop submission and join in-flight fetches before the
        shared cache owner can release its lock.
        """
        iterator=iter(tasks);pending={}
        if self.pool is None:self.pool=ThreadPoolExecutor(max_workers=self.workers,thread_name_prefix='fmp')
        def submit():
            self.check()
            try:task=next(iterator)
            except StopIteration:return False
            pending[self.pool.submit(fetch,task)]=task;return True
        try:
            for _ in range(self.workers):
                if not submit():break
            while pending:
                self.check()
                done,_=wait(pending,timeout=.1,return_when=FIRST_COMPLETED)
                for future in done:
                    task=pending.pop(future)
                    yield task,future.result()
                    submit()
        finally:
            if pending:
                self.abort.set()
                for future in pending:future.cancel()

    def close(self):
        self.abort.set()
        if self.pool:self.pool.shutdown(wait=True,cancel_futures=True)
        for connection in self.connections:connection.close()
        self.key=None

    def __enter__(self):return self
    def __exit__(self,*error):self.close()
