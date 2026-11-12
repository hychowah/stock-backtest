"""Grouped HTTP adapters; application owners retain their resource lifetimes."""
import json
import sqlite3
from backtest.runtime import diagnostics
from backtest.application import jobs as backtest_jobs
from backtest.application import queue as backtest_queue
from backtest.application import library as saved_backtests
from backtest.application import durable_evidence, strategy_requests
from backtest.application.calculation_contract import Busy

def require_calculation(self,options=None,*,planned=None):
    # Admission refuses an engine this server does not run. Readiness is
    # advisory here; the calculation owner still validates admitted inputs.
    self.server.calculations.preflight(options,planned=planned)
    if self.server.calculations.ready():return True
    self.reply(503,dict(error='Prepared inputs are unavailable. Rebuild from the data panel. Stored results remain available.'))
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
            if collection:self.reply(200,store.listing())
            else:self.json_reply(200,saved_backtests.inline_response(store.get(path[0])))
            return
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=262144:raise ValueError('Invalid queue request size.')
        def invalid(value):raise ValueError('Queue values must be finite.')
        request=json.loads(self.rfile.read(length),parse_constant=invalid)
        if not isinstance(request,dict):raise ValueError('Expected queue options.')
        adding=self.command=='POST' and collection
        # Refuse an engine this server does not run before any strategy check.
        if adding and not store.accepted(request.get('id')) and not require_calculation(self,request.get('options')):return
        if self.command=='POST' and path[1:]==['update']:self.server.calculations.preflight(request.get('options'))
        if not (adding and store.accepted(request.get('id'))):strategy_requests.check_request(request)
        if adding:
            result=store.enqueue(request)
        elif self.command=='POST' and path==['pause']:
            result=store.pause(request.get('paused'))
        elif self.command=='POST' and len(path)==2:
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
            strategy_requests.require_mode(request.get('mode'))
            if not jobs.accepted(identifier):
                # Refuse an engine this server does not run before any strategy check.
                if not require_calculation(self,request.get('options'),planned=request.get('planned')):return
                strategy_requests.check_request(request)
            self.reply(202,jobs.start(identifier,request.get('mode'),request.get('options'),planned=request.get('planned')))
        else:self.reply(404,dict(error='Unknown run action.'))
    except backtest_jobs.Missing as error:self.reply(404,dict(error=str(error)))
    except Busy as error:self.reply(409,dict(error=str(error)))
    except (ValueError,TypeError,UnicodeError) as error:
        self.reply(400,dict(error=str(error),**(strategy_requests.failure_details(error) or {})))
    except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass

def dispatch(handler,data_jobs):
    path=handler.path
    if path=='/api/backtest-capabilities' and handler.command=='GET':
        handler.reply(200,handler.server.calculations.capabilities())
    elif (path=='/api/backtest-queue' and handler.command!='DELETE') or path.startswith('/api/backtest-queue/'):
        queue_request(handler,data_jobs)
    elif path.startswith('/api/backtest-runs/'):
        backtest_run_request(handler)
    else:return False
    return True
