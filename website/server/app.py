"""Serve the website and custom cache-only schedules at http://127.0.0.1:3000."""
from contextlib import nullcontext
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import errno
import json
import sqlite3
import select
import socket
import time
import sys
import subprocess
import webbrowser
from website.server import launcher, backtests, results, data, variables

ROOT=Path(__file__).resolve().parents[1]
from backtest.inputs import daily, cache_assets
from website.server import data_manager
from backtest.runtime import cache_access as cache_access
from backtest.runtime import diagnostics as diagnostics
from backtest.application import library as saved_backtests
from backtest.application import jobs as backtest_jobs
from backtest.application.result_access import ResultAccess
from backtest.application import queue as backtest_queue
from website.rendering.state import current_build, LOCAL_OUTPUT

DATA_JOBS=data_manager.Jobs()
SAVED_BACKTESTS=saved_backtests.Store()


class Server(ThreadingHTTPServer):
    def __init__(self,*args,**kwargs):
        from backtest.application.preparation import Preparation
        from website.rendering.state import ensure_presentation
        from backtest.application.calculations import Selectable
        self.calculations=Selectable(Preparation(ROOT.parent,ensure_presentation=ensure_presentation))
        self.backtest_jobs=backtest_jobs.Jobs(self.calculations)
        self.backtest_queue=backtest_queue.Queue(calculations=self.calculations,library=SAVED_BACKTESTS)
        self.result_access=ResultAccess(self.backtest_jobs,SAVED_BACKTESTS,self.backtest_queue.store)
        super().__init__(*args,**kwargs)

    def shutdown(self):
        self.close_calculation_admission()
        super().shutdown()

    def close_calculation_admission(self):
        # Queue cancellation must already mean shutdown when admission closes.
        # Store.finish still gives a durable explicit Stop precedence.
        self.backtest_queue.request_stop()
        self.calculations.close()
        self.backtest_jobs.request_stop()
        self.result_access.close_admission()

    def server_close(self):
        self.close_calculation_admission()
        self.backtest_queue.close()
        self.result_access.close()
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

    def dispatch(self):
        if self.command in ('GET','POST') and self.launcher_request():return True
        if variables.dispatch(self):return True
        if results.dispatch(self,SAVED_BACKTESTS):return True
        if backtests.dispatch(self,DATA_JOBS):return True
        return data.dispatch(self,DATA_JOBS)

    def do_GET(self):
        self.command='GET'
        if self.dispatch():return
        if self.path in ('/','/index.html') and getattr(self.server,'data_recovery',False) and not DATA_JOBS.rebuilt:
            self.send_response(302);self.send_header('Location','/data.html');self.send_header('Content-Length','0');self.end_headers();return
        super().do_GET()

    def do_POST(self):
        self.command='POST'
        if not self.dispatch():self.reply(404,dict(error='Unknown endpoint.'))

    def do_DELETE(self):
        self.command='DELETE'
        if not self.dispatch():self.reply(404,dict(error='Unknown endpoint.'))


def ensure_ready():
    """Resolve all derived-data dependencies before accepting website requests."""
    print('Checking local caches (no downloads)…',flush=True)
    with cache_access.access():
        daily.prepare()
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
        # Report optional setup before data preparation, without blocking Original.
        from backtest.application.preparation import dependencies, PreparationError
        try:dependencies()
        except PreparationError:pass
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
            from backtest.application.preparation import PreparationError
            try:
                candidate.prepare(progress=lambda **value:print(value['message'],flush=True))
                recovery=False
            except PreparationError as error:
                recovery=True
                print(str(error),flush=True)
        else:
            with cache_access.access():
                recovery=cache_assets.source_problem()
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
        from backtest.application.candidate_calculations import Candidate
        server.calculations=Candidate(candidate)
        server.backtest_jobs.calculations=server.calculations
        server.backtest_queue.calculations=server.calculations
        DATA_JOBS.calculations=server.calculations
    else:
        DATA_JOBS.preparation=server.calculations.preparation
        DATA_JOBS.optional_preparation=True
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
        close_candidate_owners(server,candidate or server.calculations.preparation)
