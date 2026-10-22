"""Serve the website and custom cache-only schedules at http://127.0.0.1:8765."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import errno
import json
import sqlite3
import sys
import subprocess
import webbrowser
from threading import Lock

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'scripts'))
import schedules
import robustness
from build_state import current_build

CALCULATION_LOCK=Lock()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(ROOT/'dist'),**kwargs)

    def reply(self,status,payload):
        body=json.dumps(payload,allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)

    def do_POST(self):
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
            with CALCULATION_LOCK:
                db=schedules.connect()
                try:
                    db.execute('PRAGMA cache_size=-131072')
                    if self.path=='/api/robustness':
                        configuration=robustness.plan(db,**request)
                        self.stream_batch(db,configuration)
                        return
                    calculate=schedules.backtest_dates if 'dates' in request else schedules.backtest
                    result=calculate(db,**request)
                finally:db.close()
            self.reply(200,result)
        except (ValueError,TypeError,sqlite3.Error) as error:
            self.reply(400,dict(error=str(error)))

    def stream_batch(self,db,configuration):
        self.send_response(200)
        self.send_header('Content-Type','application/x-ndjson; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        def event(payload):
            self.wfile.write((json.dumps(payload,allow_nan=False)+'\n').encode())
            self.wfile.flush()
        try:
            event(dict(type='configuration',configuration=configuration))
            result=robustness.run(db,configuration,progress=event)
            event(dict(type='complete',result=result))
        except (BrokenPipeError,ConnectionResetError):
            # The completed trial transactions remain cached; stop before the
            # next trial when the browser disconnects.
            return
        except Exception as error:
            try:event(dict(type='error',message=str(error)))
            except (BrokenPipeError,ConnectionResetError):pass


def ensure_ready():
    """Resolve all derived-data dependencies before accepting website requests."""
    print('Checking local caches (no downloads)…',flush=True)
    schedules.prepare()
    if not current_build():
        print('Rebuilding the website…',flush=True)
        subprocess.run([sys.executable,str(ROOT/'build.py')],cwd=ROOT.parent,check=True)
    print('Local caches and website are ready.',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-browser',action='store_true',help='Start without opening a browser')
    args=parser.parse_args()
    try:
        ensure_ready()
    except (ValueError,OSError,sqlite3.Error,subprocess.CalledProcessError) as error:
        parser.exit(1,'Could not prepare the local website: '+str(error)+'\n')
    except KeyboardInterrupt:
        parser.exit(1,'Preparation stopped. Run the launcher again to resume safely.\n')
    try:
        server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    except OSError as error:
        if error.errno not in (errno.EADDRINUSE,10048) and getattr(error,'winerror',None)!=10048:
            parser.exit(1,f'Cannot start the local website service: {error}\n')
        # An older process may still serve the updated HTML with an outdated
        # API. Open a fresh local instance instead of reusing that process.
        try:server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        except OSError as retry_error:
            parser.exit(1,f'Cannot start the local website service: {retry_error}\n')
        print(f'Port {args.port} is already in use; opening a fresh website instance.',flush=True)
    port=server.server_address[1]
    print(f'Open http://127.0.0.1:{port} — custom schedules use saved data only.',flush=True)
    if not args.no_browser:
        try:webbrowser.open(f'http://127.0.0.1:{port}')
        except webbrowser.Error:pass
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
