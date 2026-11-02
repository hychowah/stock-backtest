"""Grouped HTTP adapters; application owners retain their resource lifetimes."""
import json
import sqlite3
from backtest.runtime import diagnostics, backtest_control
from backtest.application import jobs as backtest_jobs
from backtest.application import queue as backtest_queue
from backtest.application import durable_evidence, strategy_requests
from backtest.application.calculation_contract import Busy, Unavailable

def calculation_ready(self,options=None):
    if hasattr(self.server.calculations,'ready_for'):
        return self.server.calculations.ready_for(options or {})
    candidate=getattr(self.server,'candidate_preparation',None)
    if candidate is None:return True
    if getattr(self.server.calculations,'preparation',None) is candidate:
        return self.server.calculations.ready()
    return candidate.status().get('state')=='current'

def require_calculation(self,options=None,*,planned=None):
    # A busy inspection is advisory, not a failed execution admission.
    # The calculation owner and child still validate admitted inputs.
    if hasattr(self.server.calculations,'preflight'):
        self.server.calculations.preflight(options,planned=planned)
        if self.server.calculations.ready_for(options,advisory=True):return True
        self.reply(503,dict(error='Experimental preparation is unavailable. Use Prepare experimental engine in Manage backtest data. Original and stored results remain available.'))
        return False
    candidate=getattr(self.server,'candidate_preparation',None)
    if candidate is not None and getattr(self.server.calculations,'preparation',None) is candidate:
        status=self.server.calculations.status()
        allowed=status.get('state')=='current' or status.get('busy') is True
    else:allowed=calculation_ready(self)
    if allowed:return True
    self.reply(503,dict(error='Candidate preparation is unavailable. Open the data panel and rebuild. Stored results remain available.'))
    return False

def queue_request(self,data_jobs):
    origin=self.headers.get('Origin')
    if origin and origin!='http://'+self.headers.get('Host',''):
        self.reply(403,dict(error='Open the website to manage the backtest queue.'));return
    queue=self.server.backtest_queue;store=queue.store
    collection=self.path=='/api/backtest-queue'
    path=[] if collection else self.path.removeprefix('/api/backtest-queue/').split('/')
    try:
        if (collection or self.command!='GET') and (not getattr(self.server,'data_recovery',False) or data_jobs.rebuilt):queue.start()
        if self.command=='GET':
            if not collection and len(path)!=1:
                self.reply(404,dict(error='Unknown queue action.'));return
            self.reply(200,store.listing() if collection else store.get(path[0]));return
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=262144:raise ValueError('Invalid queue request size.')
        def invalid(value):raise ValueError('Queue values must be finite.')
        request=json.loads(self.rfile.read(length),parse_constant=invalid)
        if not isinstance(request,dict):raise ValueError('Expected queue options.')
        if not (self.command=='POST' and collection and store.accepted(request.get('id'))):strategy_requests.check_request(request)
        if self.command=='POST' and collection:
            if not store.accepted(request.get('id')) and not require_calculation(self,request.get('options')):return
            result=store.enqueue(request)
        elif self.command=='POST' and path==['pause']:
            result=store.pause(request.get('paused'))
        elif self.command=='POST' and len(path)==2:
            if path[1]=='update' and hasattr(self.server.calculations,'preflight'):
                self.server.calculations.preflight(request.get('options'))
            result=store.change(path[0],path[1],request)
        elif self.command=='DELETE' and len(path)==1:
            result=store.change(path[0],'delete',request)
        else:self.reply(404,dict(error='Unknown queue action.'));return
        queue.wake.set();self.reply(200,result)
    except backtest_queue.Missing as error:self.reply(404,dict(error=str(error)))
    except backtest_queue.Conflict as error:self.reply(409,dict(error=str(error)))
    except durable_evidence.RequiresReader as error:self.reply(409,dict(error=str(error),requires_reader=True))
    except (ValueError,TypeError,UnicodeError) as error:
        self.reply(400,dict(error=str(error),**(strategy_requests.failure_details(error) or {})))
    except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    except (OSError,sqlite3.Error) as error:
        diagnostics.failure('queue.request_failed',error)
        self.reply(500,dict(error='Could not access the backtest queue. Existing records were kept. Check the server log.'))

def backtest_run_request(self):
    origin=self.headers.get('Origin')
    if origin and origin!='http://'+self.headers.get('Host',''):
        self.reply(403,dict(error='Open the website to manage backtest runs.'));return
    path=self.path.removeprefix('/api/backtest-runs/').split('/')
    identifier=path[0]
    jobs=self.server.backtest_jobs
    try:
        if self.command=='GET' and len(path)==1:
            self.reply(200,jobs.snapshot(identifier))
        elif self.command=='GET' and path[1:]==['status']:
            self.reply(200,jobs.snapshot(identifier,include_result=False))
        elif self.command=='POST' and path[1:]==['stop']:
            self.reply(202,jobs.cancel(identifier))
        elif self.command=='POST' and len(path)==1:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16*1024**2:raise ValueError('Invalid request size.')
            def invalid(value):raise ValueError('Backtest values must be finite.')
            request=json.loads(self.rfile.read(length),parse_constant=invalid)
            if not isinstance(request,dict):raise ValueError('Expected backtest options.')
            if not jobs.accepted(identifier):strategy_requests.check_request(request)
            if not jobs.accepted(identifier) and not require_calculation(self,request.get('options'),planned=request.get('planned')):return
            self.reply(202,jobs.start(identifier,request.get('mode'),request.get('options'),planned=request.get('planned')))
        else:self.reply(404,dict(error='Unknown run action.'))
    except backtest_jobs.Missing as error:self.reply(404,dict(error=str(error)))
    except Busy as error:self.reply(409,dict(error=str(error)))
    except (ValueError,TypeError,UnicodeError) as error:
        self.reply(400,dict(error=str(error),**(strategy_requests.failure_details(error) or {})))
    except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass

def stream_batch(self,options,*,planned=None):
    """Adapt calculation callbacks to the legacy stream after planning.

    Pre-configuration failures remain HTTP errors. Once headers are sent,
    calculation failures use an error frame. No database belongs here.
    """
    started=False
    def event(payload):
        backtest_control.checkpoint()
        self.wfile.write((json.dumps(payload,allow_nan=False)+'\n').encode())
        self.wfile.flush()
    def configuration(value):
        nonlocal started
        self.send_response(200)
        self.send_header('Content-Type','application/x-ndjson; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        started=True
        event(dict(type='configuration',configuration=value))
    try:
        result=self.server.calculations.calculate('random',options,event,configuration,planned=planned,
            details=getattr(self,'headers',{}).get('X-Backtest-Details')=='holdings')
        event(dict(type='complete',result=result))
    except (backtest_control.Cancelled,BrokenPipeError,ConnectionResetError):
        # The completed trial transactions remain cached; stop before the
        # next trial when the browser disconnects.
        return
    except Exception as error:
        if not started:raise
        diagnostics.failure('robustness.failed',error)
        try:event(dict(type='error',message=str(error)))
        except (BrokenPipeError,ConnectionResetError):pass

def schedule_request(self):
    origin=self.headers.get('Origin')
    expected='http://'+self.headers.get('Host','')
    if origin and origin!=expected:
        self.reply(403,dict(error='Open the local website to run a schedule.'));return
    try:
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=16*1024**2:raise ValueError('Invalid request size.')
        request=json.loads(self.rfile.read(length))
        if not isinstance(request,dict):raise ValueError('Expected schedule options.')
        if not require_calculation(self,request):return
        with backtest_control.cancel_when(self.disconnect_check()):
            backtest_control.checkpoint()
            if self.path=='/api/robustness':
                stream_batch(self,request)
                return
            result=self.server.calculations.calculate('custom',request,None,None)
            backtest_control.checkpoint()
        self.reply(200,result)
    except Unavailable:
        self.reply(503,dict(error='Candidate preparation is unavailable. Open the data panel and rebuild. Stored results remain available.'))
    except (backtest_control.Cancelled,BrokenPipeError,ConnectionResetError):
        # Contexts close databases and wait for worker cleanup before cache
        # ownership is released. Completed trial transactions remain saved.
        return
    except (ValueError,TypeError,sqlite3.Error) as error:
        diagnostics.failure('schedule.failed',error,mode='robustness' if self.path=='/api/robustness' else 'schedule')
        self.reply(400,dict(error=str(error),**(strategy_requests.failure_details(error) or {})))

def dispatch(handler,data_jobs):
    path=handler.path
    if path=='/api/variable-preview' and handler.command=='POST':
        origin=handler.headers.get('Origin')
        if origin and origin!='http://'+handler.headers.get('Host',''):
            handler.reply(403,dict(error='Open the website to preview variables.'));return True
        try:
            length=int(handler.headers.get('Content-Length','0'))
            if not 0<length<=strategy_requests.REQUEST_BYTES:raise ValueError('Invalid preview request size.')
            request=durable_evidence.decode(handler.rfile.read(length))
            if (type(request) is not dict or not {'strategy','roots'}<=set(request)
                    or set(request)-{'strategy','roots','engine'}):raise ValueError('Expected a captured strategy and explicit preview roots.')
            engine=strategy_requests.preview_engine(request.get('engine','original'))
            with backtest_control.cancel_when(handler.disconnect_check()):
                value=handler.server.calculations.preview(request['strategy'],request['roots'],engine=engine)
            handler.reply(200,value)
        except (ValueError,TypeError) as error:
            details=strategy_requests.failure_details(error) or dict(code=None,path=None)
            handler.reply(400,dict(error=str(error),**details))
        return True
    if path=='/api/backtest-capabilities' and handler.command=='GET':
        owner=handler.server.calculations
        handler.reply(200,owner.capabilities() if hasattr(owner,'capabilities') else dict(calendar=owner.calendar_version))
    elif (path=='/api/backtest-queue' and handler.command!='DELETE') or path.startswith('/api/backtest-queue/'):
        queue_request(handler,data_jobs)
    elif path.startswith('/api/backtest-runs/'):
        backtest_run_request(handler)
    elif path in ('/api/schedule','/api/robustness') and handler.command=='POST':
        schedule_request(handler)
    else:return False
    return True
