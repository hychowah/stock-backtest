"""Serve the website and custom cache-only schedules at http://127.0.0.1:3000."""
from contextlib import nullcontext
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import errno
import ipaddress
from urllib.parse import urlsplit
import json
import sqlite3
import select
import socket
import time
import sys
import subprocess
import webbrowser
import launcher

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'scripts'))
import schedules
import data_manager
import cache_access
import diagnostics
import backtest_control
import saved_backtests
import backtest_jobs
import backtest_queue
import durable_evidence
import evidence_views
import result_exports
from build_state import current_build, LOCAL_OUTPUT

DATA_JOBS=data_manager.Jobs()
SAVED_BACKTESTS=saved_backtests.Store()


class Server(ThreadingHTTPServer):
    def __init__(self,*args,**kwargs):
        self.calculations=backtest_jobs.Calculations()
        self.backtest_jobs=backtest_jobs.Jobs(self.calculations)
        self.backtest_queue=backtest_queue.Queue(calculations=self.calculations)
        super().__init__(*args,**kwargs)

    def shutdown(self):
        self.close_calculation_admission()
        super().shutdown()

    def close_calculation_admission(self):
        # Queue cancellation must already mean shutdown when admission closes.
        # Store.finish still gives a durable explicit Stop precedence.
        self.backtest_queue.request_stop()
        self.calculations.close()

    def server_close(self):
        self.close_calculation_admission()
        self.backtest_queue.close()
        self.backtest_jobs.close()
        super().server_close()
        if hasattr(self.calculations,'retire'):self.calculations.retire()

    def handle_error(self,request,client_address):
        error=sys.exc_info()[1]
        diagnostics.failure('http.failed',error)
        print(f'HTTP request failed ({type(error).__name__}). Check the development log.',file=sys.stderr,flush=True)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(LOCAL_OUTPUT),**kwargs)

    def reply(self,status,payload):
        body=json.dumps(payload,allow_nan=False).encode()
        self.json_reply(status,body)

    def json_reply(self,status,body):
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)

    def launcher_request(self):
        lifecycle=getattr(self.server,'lifecycle',None)
        if lifecycle:return lifecycle.control(self)
        if self.path=='/api/launcher':
            self.reply(404,dict(error='No managed server.'));return True
        return False

    def data_allowed(self):
        try:
            local=ipaddress.ip_address(self.client_address[0]).is_loopback
            host=urlsplit('http://'+self.headers.get('Host','')).hostname
        except ValueError:return False
        return local and host in ('127.0.0.1','localhost','::1') and self.headers.get('Origin','http://'+self.headers.get('Host',''))=='http://'+self.headers.get('Host','')

    def calculation_ready(self):
        candidate=getattr(self.server,'candidate_preparation',None)
        if candidate is None:return True
        if getattr(self.server.calculations,'preparation',None) is candidate:
            return self.server.calculations.ready()
        return candidate.status().get('state')=='current'

    def require_calculation(self):
        # A busy inspection is advisory, not a failed execution admission.
        # The calculation owner and child still validate admitted inputs.
        candidate=getattr(self.server,'candidate_preparation',None)
        if candidate is not None and getattr(self.server.calculations,'preparation',None) is candidate:
            status=self.server.calculations.status()
            allowed=status.get('state')=='current' or status.get('busy') is True
        else:allowed=self.calculation_ready()
        if allowed:return True
        self.reply(503,dict(error='Candidate preparation is unavailable. Open the data panel and rebuild. Stored results remain available.'))
        return False

    def do_GET(self):
        if self.launcher_request():return
        if self.path=='/api/backtest-capabilities':
            self.reply(200,dict(calendar=self.server.calculations.calendar_version));return
        if self.path=='/api/backtest-queue' or self.path.startswith('/api/backtest-queue/'):
            self.queue_request();return
        if self.path.startswith('/api/backtest-runs/'):
            self.backtest_run_request();return
        if self.path=='/api/backtests' or self.path.startswith('/api/backtests/'):
            self.saved_backtest_request();return
        if self.path=='/data.html':
            body=data_page().encode('utf-8')
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body);return
        if self.path in ('/api/data/status','/api/data/report'):
            if not self.data_allowed():self.reply(403,dict(error='Open the data panel on this computer using localhost or 127.0.0.1.'));return
            state=DATA_JOBS.snapshot()
            self.reply(200,state if self.path.endswith('status') else state['report']);return
        if self.path in ('/','/index.html') and getattr(self.server,'data_recovery',False) and not DATA_JOBS.rebuilt:
            self.send_response(302);self.send_header('Location','/data.html');self.send_header('Content-Length','0');self.end_headers();return
        super().do_GET()

    def disconnect_check(self):
        """Observe an aborted fetch without consuming any further request bytes."""
        last_check=0.;gone=False
        def cancelled():
            nonlocal last_check,gone
            now=time.monotonic()
            if gone or now-last_check<.05:return gone
            last_check=now
            try:
                readable,_,_=select.select([self.connection],[],[],0)
                if readable:gone=self.connection.recv(1,socket.MSG_PEEK)==b''
            except OSError:
                gone=True
            return gone
        return cancelled

    def do_POST(self):
        if self.launcher_request():return
        if self.path=='/api/backtest-queue' or self.path.startswith('/api/backtest-queue/'):
            self.queue_request();return
        if self.path.startswith('/api/backtest-runs/'):
            self.backtest_run_request();return

        if self.path=='/api/backtests' or self.path.startswith('/api/backtests/'):
            self.saved_backtest_request();return

        if self.path.startswith('/api/data/'):
            self.data_request();return
        if self.path not in ('/api/schedule','/api/robustness'):
            self.reply(404,dict(error='Unknown endpoint.'));return
        if not self.require_calculation():return
        origin=self.headers.get('Origin')
        expected='http://'+self.headers.get('Host','')
        if origin and origin!=expected:
            self.reply(403,dict(error='Open the local website to run a schedule.'));return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16*1024**2:raise ValueError('Invalid request size.')
            request=json.loads(self.rfile.read(length))
            if not isinstance(request,dict):raise ValueError('Expected schedule options.')
            with backtest_control.cancel_when(self.disconnect_check()):
                backtest_control.checkpoint()
                if self.path=='/api/robustness':
                    self.stream_batch(request)
                    return
                result=backtest_jobs.calculate('custom',request,None,None,owner=self.server.calculations)
                backtest_control.checkpoint()
            self.reply(200,result)
        except backtest_jobs.Unavailable:
            self.reply(503,dict(error='Candidate preparation is unavailable. Open the data panel and rebuild. Stored results remain available.'))
        except (backtest_control.Cancelled,BrokenPipeError,ConnectionResetError):
            # Contexts close databases and wait for worker cleanup before cache
            # ownership is released. Completed trial transactions remain saved.
            return
        except (ValueError,TypeError,sqlite3.Error) as error:
            diagnostics.failure('schedule.failed',error,mode='robustness' if self.path=='/api/robustness' else 'schedule')
            self.reply(400,dict(error=str(error)))

    def do_DELETE(self):
        if self.path.startswith('/api/backtest-runs/'):
            self.backtest_run_request();return
        if self.path.startswith('/api/backtest-queue/'):
            self.queue_request();return
        if self.path.startswith('/api/backtests/'):
            self.saved_backtest_request();return
        self.reply(404,dict(error='Unknown endpoint.'))

    def queue_request(self):
        origin=self.headers.get('Origin')
        if origin and origin!='http://'+self.headers.get('Host',''):
            self.reply(403,dict(error='Open the website to manage the backtest queue.'));return
        queue=self.server.backtest_queue;store=queue.store
        collection=self.path=='/api/backtest-queue'
        path=[] if collection else self.path.removeprefix('/api/backtest-queue/').split('/')
        try:
            if (collection or self.command!='GET') and self.calculation_ready() and (not getattr(self.server,'data_recovery',False) or DATA_JOBS.rebuilt):queue.start()
            if self.command=='GET':
                if not collection and len(path)!=1:
                    self.reply(404,dict(error='Unknown queue action.'));return
                self.reply(200,store.listing() if collection else store.get(path[0]));return
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=262144:raise ValueError('Invalid queue request size.')
            def invalid(value):raise ValueError('Queue values must be finite.')
            request=json.loads(self.rfile.read(length),parse_constant=invalid)
            if not isinstance(request,dict):raise ValueError('Expected queue options.')
            if self.command=='POST' and collection:
                if not self.require_calculation():return
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
        except (ValueError,TypeError,UnicodeError) as error:self.reply(400,dict(error=str(error)))
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
            if path[1:2]==['reader']:
                self.evidence_request(identifier,path[2:]);return
            if self.command=='GET' and len(path)==1:
                self.reply(200,jobs.snapshot(identifier))
            elif self.command=='GET' and path[1:]==['status']:
                self.reply(200,jobs.snapshot(identifier,include_result=False))
            elif self.command=='POST' and path[1:]==['stop']:
                self.reply(202,jobs.cancel(identifier))
            elif self.command=='POST' and len(path)==1:
                if not self.require_calculation():return
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=16*1024**2:raise ValueError('Invalid request size.')
                def invalid(value):raise ValueError('Backtest values must be finite.')
                request=json.loads(self.rfile.read(length),parse_constant=invalid)
                if not isinstance(request,dict):raise ValueError('Expected backtest options.')
                self.reply(202,jobs.start(identifier,request.get('mode'),request.get('options'),planned=request.get('planned')))
            else:self.reply(404,dict(error='Unknown run action.'))
        except backtest_jobs.Missing as error:self.reply(404,dict(error=str(error)))
        except backtest_jobs.Busy as error:self.reply(409,dict(error=str(error)))
        except (ValueError,TypeError,UnicodeError) as error:self.reply(400,dict(error=str(error)))
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass

    def evidence_request(self,identifier,path):
        """Explicit reader operations. Never acquire financial ownership or readiness."""
        jobs=self.server.backtest_jobs;started=False
        try:
            if self.command=='DELETE' and not path:
                jobs.release_reader(identifier);self.reply(200,dict(released=True));return
            if self.command=='POST' and not path:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=durable_evidence.MAX_METADATA_BYTES:raise ValueError('Invalid reader request size.')
                request=durable_evidence.decode(self.rfile.read(length));source=request.get('source',{})
                kind=source.get('kind');record_id=source.get('id')
                if kind=='run':opener=lambda:jobs.display_evidence(record_id,request.get('display',{}))
                elif kind=='saved':opener=lambda:SAVED_BACKTESTS.open_evidence(record_id)
                elif kind=='queue':opener=lambda:self.server.backtest_queue.store.open_evidence(record_id)
                else:raise ValueError('Unknown evidence source.')
                self.reply(200,jobs.acquire_reader(identifier,request,opener));return
            if self.command!='GET':raise ValueError('Unsupported evidence operation.')
            with jobs.read_artifact(identifier) as (metadata,reader):
                if len(path)==3 and path[0]=='export':
                    kind=path[1];trial=int(path[2]);name=result_exports.filename(reader,kind,trial)
                    # Count through a bounded pass before headers. Content-Length
                    # makes a later interrupted transfer detectably incomplete.
                    length=sum(len(chunk) for chunk in result_exports.csv(reader,kind,trial))
                    chunks=result_exports.csv(reader,kind,trial)
                    first=next(chunks,b'')
                    self.connection.settimeout(30)
                    self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8')
                    self.send_header('Content-Length',str(length))
                    self.send_header('Content-Disposition','attachment; filename="'+name+'"')
                    self.send_header('Cache-Control','no-store');self.end_headers()
                    started=True
                    self.close_connection=True
                    try:
                        self.wfile.write(first)
                        for chunk in chunks:
                            if jobs.closing:raise backtest_control.Cancelled()
                            self.wfile.write(chunk)
                        self.wfile.flush()
                    except (OSError,ValueError,backtest_control.Cancelled):
                        # An interrupted attachment has no complete-length proof.
                        # Close the transport and request pin, never report success.
                        try:self.connection.shutdown(socket.SHUT_RDWR)
                        except OSError:pass
                    return
                if len(path)==4 and path[0]=='page':
                    selection=dict(operation=path[1],trial=int(path[2]),cursor=int(path[3]))
                elif len(path)==5 and path[0:2]==['page','holdings']:
                    selection=dict(operation='holdings',trial=int(path[2]),period=int(path[3]),cursor=int(path[4]))
                else:raise ValueError('Unknown evidence action.')
                value=dict(identity=identifier,**evidence_views.read(reader,selection))
                self.json_reply(200,evidence_views.encode(value))
        except (saved_backtests.Missing,backtest_queue.Missing,backtest_jobs.Missing) as error:self.reply(404,dict(error=str(error)))
        except (ValueError,TypeError,KeyError) as error:
            if not started:self.reply(400,dict(error=str(error)))
            else:self.close_connection=True
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        except (OSError,sqlite3.Error) as error:
            diagnostics.failure('evidence.request_failed',error)
            if not started:self.reply(500,dict(error='Could not read stored evidence. Existing records were kept.'))
            else:self.close_connection=True

    def saved_backtest_request(self):
        origin=self.headers.get('Origin')
        if origin and origin!='http://'+self.headers.get('Host',''):
            self.reply(403,dict(error='Open the website to manage saved backtests.'));return
        identifier=self.path.removeprefix('/api/backtests/');collection=self.path=='/api/backtests'
        try:
            if self.command=='GET':
                self.reply(200,dict(limit=saved_backtests.LIMIT,records=SAVED_BACKTESTS.list()) if collection else SAVED_BACKTESTS.get(identifier))
            elif self.command=='DELETE' and not collection:
                SAVED_BACKTESTS.delete(identifier);self.reply(200,dict(deleted=True,id=identifier))
            elif self.command=='POST' and collection:
                length=int(self.headers.get('Content-Length','0'))
                if length>saved_backtests.MAX_BYTES:
                    self.reply(413,dict(error='This backtest is too large to save as one record.'));return
                if length<=0:raise ValueError('Expected a completed backtest.')
                def invalid_constant(value):raise ValueError('Saved values must be finite.')
                request=json.loads(self.rfile.read(length),parse_constant=invalid_constant)
                if not isinstance(request,dict):raise ValueError('Expected a completed backtest.')
                if 'reader' in request:
                    with self.server.backtest_jobs.read_artifact(request['reader']) as (metadata,reader):
                        record=SAVED_BACKTESTS.save_evidence(request.get('name'),metadata,reader)
                    self.reply(201,record)
                else:self.reply(201,SAVED_BACKTESTS.save(request.get('name'),request.get('snapshot')))
            else:self.reply(405,dict(error='Unsupported saved-backtest action.'))
        except saved_backtests.Full as error:self.reply(409,dict(error=str(error)))
        except saved_backtests.Missing as error:self.reply(404,dict(error=str(error)))
        except durable_evidence.RequiresReader as error:self.reply(409,dict(error=str(error),requires_reader=True))
        except (ValueError,TypeError,UnicodeError) as error:self.reply(400,dict(error=str(error)))
        except (OSError,sqlite3.Error) as error:
            diagnostics.failure('saved_backtest.failed',error)
            self.reply(500,dict(error='Could not access saved backtests. Your existing records were kept. Check the development log.'))

    def data_request(self):
        if not self.data_allowed():self.reply(403,dict(error='Open the data panel on this computer using localhost or 127.0.0.1.'));return
        action=self.path.removeprefix('/api/data/')
        if action not in ('check','download','rebuild','cancel'):
            self.reply(404,dict(error='Unknown data action.'));return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16*1024**2:raise ValueError('Invalid request size.')
            request=json.loads(self.rfile.read(length))
            if not isinstance(request,dict):raise ValueError('Expected data options.')
            self.reply(202,DATA_JOBS.cancel_job() if action=='cancel' else DATA_JOBS.start(action,request))
        except (ValueError,TypeError):
            self.reply(400,dict(error='Invalid data options, or another data job is running. Check dates, stock symbols and selected data types.'))

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
            result=backtest_jobs.calculate('random',options,event,configuration,planned=planned,
                owner=self.server.calculations,details=getattr(self,'headers',{}).get('X-Backtest-Details')=='holdings')
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


def data_page():
    return (ROOT/'data.html').read_text(encoding='utf-8').replace('__DATA_STYLE__',(ROOT/'data-panel.css').read_text(encoding='utf-8')).replace('__DATA_SCRIPT__',(ROOT/'data-panel.js').read_text(encoding='utf-8'))


def ensure_ready():
    """Resolve all derived-data dependencies before accepting website requests."""
    print('Checking local caches (no downloads)…',flush=True)
    with cache_access.access():
        schedules.prepare()
        if not current_build():
            print('Rebuilding the website…',flush=True)
            subprocess.run([sys.executable,'-X','utf8',str(ROOT/'build.py'),'--cache-owned'],cwd=ROOT.parent,check=True)
    print('Local caches and website are ready.',flush=True)


def close_candidate_owners(server,candidate):
    """Finish application joins before the candidate entry releases source."""
    import signal
    previous=signal.signal(signal.SIGINT,signal.SIG_IGN)
    try:
        server.close_calculation_admission()
        while True:
            try:
                DATA_JOBS.close()
                server.server_close()
                candidate.close()
                return
            except KeyboardInterrupt:continue
    finally:signal.signal(signal.SIGINT,previous)


def main(*,candidate=None,arguments=None):
    global DATA_JOBS
    if candidate is not None:DATA_JOBS=data_manager.Jobs(preparation=candidate)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=3000)
    parser.add_argument('--host',default='0.0.0.0')
    parser.add_argument('--no-browser',action='store_true',help='Start without opening a browser')
    parser.add_argument('--managed',action='store_true',help='Replace this project’s previous server and keep this terminal attached')
    args=parser.parse_args(arguments)
    path=diagnostics.configure()
    print('Development log: '+diagnostics.relative_path(path) if path else 'Development log unavailable. Terminal logging remains active.',flush=True)
    diagnostics.event('server.starting',port=args.port,managed=args.managed)
    try:
        context=launcher.Lifecycle(args.port,args.host) if args.managed else nullcontext()
        with context as lifecycle:run_server(args,lifecycle,parser,candidate=candidate)
    except KeyboardInterrupt:
        print('Website stopped.',flush=True)
    except (OSError,ValueError,RuntimeError) as error:
        diagnostics.failure('server.failed',error)
        parser.exit(1,str(error)+'\n')
    finally:
        diagnostics.event('server.stopped')
        diagnostics.close()


def run_server(args,lifecycle,parser,*,candidate=None):
    try:
        if candidate is not None:
            from numerical_preparation import PreparationError
            try:
                candidate.prepare(progress=lambda **value:print(value['message'],flush=True))
                recovery=False
            except PreparationError as error:
                recovery=True
                print(str(error),flush=True)
        else:
            with cache_access.access():
                recovery=data_manager.source_problem()
                if recovery:print('Saved source data is missing or invalid. Opening the data control panel.',flush=True)
                else:ensure_ready()
    except (ValueError,OSError,sqlite3.Error,subprocess.CalledProcessError) as error:
        diagnostics.failure('startup.failed',error)
        parser.exit(1,'Could not prepare the local website: '+str(error)+'\n')
    except KeyboardInterrupt:
        parser.exit(1,'Preparation stopped. Run the launcher again to resume safely.\n')
    try:
        server=Server((args.host,args.port),Handler)
    except OSError as error:
        if error.errno not in (errno.EADDRINUSE,10048) and getattr(error,'winerror',None)!=10048:
            diagnostics.failure('server.bind_failed',error,port=args.port)
            parser.exit(1,f'Cannot start the local website service: {error}\n')
        # An older process may still serve the updated HTML with an outdated
        # API. Open a fresh local instance instead of reusing that process.
        try:server=Server((args.host,0),Handler)
        except OSError as retry_error:
            diagnostics.failure('server.bind_failed',retry_error)
            parser.exit(1,f'Cannot start the local website service: {retry_error}\n')
        print(f'Port {args.port} is already in use; opening a fresh website instance.',flush=True)
    server.data_recovery=recovery
    server.candidate_preparation=candidate
    if candidate is not None:
        from candidate_calculations import Candidate
        server.calculations=Candidate(candidate)
        server.backtest_jobs.calculations=server.calculations
        server.backtest_queue.calculations=server.calculations
        DATA_JOBS.calculations=server.calculations
    port=server.server_address[1]
    # Managed cleanup owns the server immediately, including publication failure.
    if lifecycle:lifecycle.attach(server)
    else:server.daemon_threads=False
    try:
        if not recovery:server.backtest_queue.start()
        print('Server attached to this terminal. Press Ctrl+C to stop.',flush=True)
        print(f'Open http://127.0.0.1:{port} — custom schedules use saved data only.',flush=True)
        diagnostics.event('server.ready',port=port)
        if not args.no_browser:
            try:webbrowser.open(f'http://127.0.0.1:{port}')
            except webbrowser.Error:pass
        server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        server.close_calculation_admission()
        if candidate is not None:close_candidate_owners(server,candidate)
        else:
            DATA_JOBS.close()
            if not lifecycle:server.server_close()
