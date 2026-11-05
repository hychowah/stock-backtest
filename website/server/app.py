"""Serve the website and custom cache-only schedules at http://127.0.0.1:3000."""
from contextlib import nullcontext
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import errno
import json
import re
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
from backtest.application.original_calculations import Original
from website.rendering.state import current_build, LOCAL_OUTPUT

DATA_JOBS=data_manager.Jobs()
SAVED_BACKTESTS=saved_backtests.Store()
SLOW_REQUEST_SECONDS=1.


def route(path):
    """Return a request path without its query or identifiers, for the log."""
    if not path.startswith('/'):return '{other}'
    parts=path.split('?',1)[0].split('#',1)[0].split('/')
    if parts[1:2]==['api']:
        parts=parts[:3]+[part if re.fullmatch(r'[a-z][a-z-]{0,23}',part) else '{id}' for part in parts[3:]]
    return '/'.join(parts)


class Server(ThreadingHTTPServer):
    def __init__(self,*args,**kwargs):
        self.calculations=Original()
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

    def handle_error(self,request,client_address):
        error=sys.exc_info()[1]
        diagnostics.failure('http.failed',error)
        print(f'HTTP request failed ({type(error).__name__}). Check the development log.',file=sys.stderr,flush=True)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(LOCAL_OUTPUT),**kwargs)

    def handle_one_request(self):
        """Log a request slower than SLOW_REQUEST_SECONDS, timed from its request line."""
        self.request_started=self.response_status=None
        super().handle_one_request()
        if self.request_started is not None:
            seconds=time.perf_counter()-self.request_started
            if seconds>=SLOW_REQUEST_SECONDS:
                diagnostics.event('http.slow',method=self.command,route=route(getattr(self,'path','')),status=self.response_status,seconds=round(seconds,3))

    def parse_request(self):
        # The request line has arrived; an idle keep-alive wait is not counted.
        self.request_started=time.perf_counter()
        return super().parse_request()

    def log_request(self,code='-',size='-'):
        if isinstance(code,int):self.response_status=int(code)
        super().log_request(code,size)

    def log_message(self,format,*args):
        # The stamped terminal already starts the line with the time.
        message=format%args;table=getattr(self,'_control_char_table',None)
        sys.stderr.write(f'{self.address_string()} {message.translate(table) if table else message}\n')

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
        diagnostics.lap('prepare')
        if not current_build():
            print('Rebuilding the website…',flush=True)
            subprocess.run([sys.executable,'-X','utf8',str(ROOT/'build.py'),'--cache-owned'],cwd=ROOT.parent,check=True)
            diagnostics.lap('website_build')
    print('Local caches and website are ready.',flush=True)


def close_owners(server):
    """Finish application joins before the entry point releases source."""
    import signal
    previous=signal.signal(signal.SIGINT,signal.SIG_IGN)
    try:
        server.close_calculation_admission()
        while True:
            try:
                DATA_JOBS.close()
                server.server_close()
                return
            except KeyboardInterrupt:continue
    finally:signal.signal(signal.SIGINT,previous)


def main(*,arguments=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=3000)
    parser.add_argument('--host',default='0.0.0.0')
    parser.add_argument('--no-browser',action='store_true',help='Start without opening a browser')
    parser.add_argument('--managed',action='store_true',help='Replace this project’s previous server and keep this terminal attached')
    args=parser.parse_args(arguments)
    started=time.perf_counter()
    sys.stdout,sys.stderr=diagnostics.Stamped(sys.stdout),diagnostics.Stamped(sys.stderr)
    path=diagnostics.configure()
    print('Development log: '+diagnostics.relative_path(path) if path else 'Development log unavailable. Terminal logging remains active.',flush=True)
    diagnostics.event('server.starting',port=args.port,managed=args.managed)
    try:
        context=launcher.Lifecycle(args.port,args.host) if args.managed else nullcontext()
        with context as lifecycle:run_server(args,lifecycle,parser,started)
    except KeyboardInterrupt:
        print('Website stopped.',flush=True)
    except (OSError,ValueError,RuntimeError) as error:
        diagnostics.failure('server.failed',error)
        parser.exit(1,str(error)+'\n')
    finally:
        diagnostics.event('server.stopped')
        diagnostics.close()


def run_server(args,lifecycle,parser,started):
    try:
        with diagnostics.operation('startup.prepare'),cache_access.access():
            diagnostics.lap('admission')
            recovery=cache_assets.source_problem()
            diagnostics.lap('source_check')
            if recovery:
                diagnostics.note(outcome='recovery')
                print('Saved source data is missing or invalid. Opening the data control panel.',flush=True)
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
    port=server.server_address[1]
    # Managed cleanup owns the server immediately, including publication failure.
    if lifecycle:lifecycle.attach(server)
    else:server.daemon_threads=False
    try:
        if not recovery:server.backtest_queue.start()
        print('Server attached to this terminal. Press Ctrl+C to stop.',flush=True)
        print(f'Open http://127.0.0.1:{port} — custom schedules use saved data only.',flush=True)
        diagnostics.event('server.ready',port=port,startup_seconds=round(time.perf_counter()-started,3))
        if not args.no_browser:
            try:webbrowser.open(f'http://127.0.0.1:{port}')
            except webbrowser.Error:pass
        server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        server.close_calculation_admission()
        close_owners(server)
