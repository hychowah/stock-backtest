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
import robustness
import data_manager
import cache_access
import diagnostics
import backtest_control
from build_state import current_build, LOCAL_OUTPUT

DATA_JOBS=data_manager.Jobs()


class Server(ThreadingHTTPServer):
    def handle_error(self,request,client_address):
        error=sys.exc_info()[1]
        diagnostics.failure('http.failed',error)
        print(f'HTTP request failed ({type(error).__name__}). Check the development log.',file=sys.stderr,flush=True)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(LOCAL_OUTPUT),**kwargs)

    def reply(self,status,payload):
        body=json.dumps(payload,allow_nan=False).encode()
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

    def do_GET(self):
        if self.launcher_request():return
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

        if self.path.startswith('/api/data/'):
            self.data_request();return
        if self.path not in ('/api/schedule','/api/robustness'):
            self.reply(404,dict(error='Unknown endpoint.'));return
        origin=self.headers.get('Origin')
        expected='http://'+self.headers.get('Host','')
        if origin and origin!=expected:
            self.reply(403,dict(error='Open the local website to run a schedule.'));return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16384:raise ValueError('Invalid request size.')
            request=json.loads(self.rfile.read(length))
            if not isinstance(request,dict):raise ValueError('Expected schedule options.')
            with backtest_control.cancel_when(self.disconnect_check()), cache_access.daily() as db:
                backtest_control.checkpoint()
                db.execute('PRAGMA cache_size=-131072')
                if self.path=='/api/robustness':
                    configuration=robustness.plan(db,**request)
                    self.stream_batch(db,configuration)
                    return
                calculate=schedules.backtest_dates if 'dates' in request else schedules.backtest
                result=calculate(db,**request)
                backtest_control.checkpoint()
            self.reply(200,result)
        except (backtest_control.Cancelled,BrokenPipeError,ConnectionResetError):
            # Contexts close databases and wait for worker cleanup before cache
            # ownership is released. Completed trial transactions remain saved.
            return
        except (ValueError,TypeError,sqlite3.Error) as error:
            diagnostics.failure('schedule.failed',error,mode='robustness' if self.path=='/api/robustness' else 'schedule')
            self.reply(400,dict(error=str(error)))

    def data_request(self):
        if not self.data_allowed():self.reply(403,dict(error='Open the data panel on this computer using localhost or 127.0.0.1.'));return
        action=self.path.removeprefix('/api/data/')
        if action not in ('check','download','rebuild','cancel'):
            self.reply(404,dict(error='Unknown data action.'));return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16384:raise ValueError('Invalid request size.')
            request=json.loads(self.rfile.read(length))
            if not isinstance(request,dict):raise ValueError('Expected data options.')
            self.reply(202,DATA_JOBS.cancel_job() if action=='cancel' else DATA_JOBS.start(action,request))
        except (ValueError,TypeError):
            self.reply(400,dict(error='Invalid data options, or another data job is running. Check dates, stock symbols and selected data types.'))

    def stream_batch(self,db,configuration):
        self.send_response(200)
        self.send_header('Content-Type','application/x-ndjson; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        def event(payload):
            backtest_control.checkpoint()
            self.wfile.write((json.dumps(payload,allow_nan=False)+'\n').encode())
            self.wfile.flush()
        try:
            event(dict(type='configuration',configuration=configuration))
            result=robustness.run(db,configuration,progress=event)
            event(dict(type='complete',result=result))
        except (backtest_control.Cancelled,BrokenPipeError,ConnectionResetError):
            # The completed trial transactions remain cached; stop before the
            # next trial when the browser disconnects.
            return
        except Exception as error:
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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=3000)
    parser.add_argument('--host',default='0.0.0.0')
    parser.add_argument('--no-browser',action='store_true',help='Start without opening a browser')
    parser.add_argument('--managed',action='store_true',help='Replace this project’s previous server and keep this terminal attached')
    args=parser.parse_args()
    path=diagnostics.configure()
    print('Development log: '+diagnostics.relative_path(path) if path else 'Development log unavailable. Terminal logging remains active.',flush=True)
    diagnostics.event('server.starting',port=args.port,managed=args.managed)
    try:
        context=launcher.Lifecycle(args.port,args.host) if args.managed else nullcontext()
        with context as lifecycle:run_server(args,lifecycle,parser)
    except KeyboardInterrupt:
        print('Website stopped.',flush=True)
    except (OSError,ValueError,RuntimeError) as error:
        diagnostics.failure('server.failed',error)
        parser.exit(1,str(error)+'\n')
    finally:
        diagnostics.event('server.stopped')
        diagnostics.close()


def run_server(args,lifecycle,parser):
    try:
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
    port=server.server_address[1]
    # Managed cleanup owns the server immediately, including publication failure.
    if lifecycle:lifecycle.attach(server)
    else:server.daemon_threads=False
    try:
        print('Server attached to this terminal. Press Ctrl+C to stop.',flush=True)
        print(f'Open http://127.0.0.1:{port} — custom schedules use saved data only.',flush=True)
        diagnostics.event('server.ready',port=port)
        if not args.no_browser:
            try:webbrowser.open(f'http://127.0.0.1:{port}')
            except webbrowser.Error:pass
        server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        DATA_JOBS.close()
        if not lifecycle:server.server_close()
