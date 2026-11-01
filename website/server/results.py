"""Grouped HTTP adapters; application owners retain their resource lifetimes."""
import json
import sqlite3
import socket
from backtest.runtime import diagnostics, backtest_control
from backtest.application import jobs as backtest_jobs
from backtest.application import queue as backtest_queue
from backtest.application import library as saved_backtests
from backtest.application import durable_evidence, evidence_views, result_exports

def evidence_request(self,identifier,path):
    """Explicit reader operations. Never acquire financial ownership or readiness."""
    access=self.server.result_access;started=False
    try:
        if self.command=='DELETE' and not path:
            access.release(identifier);self.reply(200,dict(released=True));return
        if self.command=='POST' and not path:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=durable_evidence.MAX_METADATA_BYTES:raise ValueError('Invalid reader request size.')
            request=durable_evidence.decode(self.rfile.read(length))
            self.reply(200,access.acquire(identifier,request));return
        if self.command!='GET':raise ValueError('Unsupported evidence operation.')
        with access.read(identifier) as (metadata,reader):
            if len(path)==3 and path[0]=='export':
                kind=path[1];trial=int(path[2]);export=result_exports.prepare(reader,kind,trial)
                name=export.filename
                # Count through a bounded pass before headers. Content-Length
                # makes a later interrupted transfer detectably incomplete.
                length=export.content_length
                chunks=export.chunks()
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
                        if access.closing:raise backtest_control.Cancelled()
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

def saved_backtest_request(self,store):
    origin=self.headers.get('Origin')
    if origin and origin!='http://'+self.headers.get('Host',''):
        self.reply(403,dict(error='Open the website to manage saved backtests.'));return
    identifier=self.path.removeprefix('/api/backtests/');collection=self.path=='/api/backtests'
    try:
        if self.command=='GET':
            self.reply(200,dict(limit=saved_backtests.LIMIT,records=store.list()) if collection else store.get(identifier))
        elif self.command=='DELETE' and not collection:
            store.delete(identifier);self.reply(200,dict(deleted=True,id=identifier))
        elif self.command=='POST' and not collection:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=4096:raise ValueError('Expected a backtest name with 1–120 characters.')
            request=json.loads(self.rfile.read(length))
            if not isinstance(request,dict):raise ValueError('Expected a backtest name.')
            self.reply(200,store.rename(identifier,request.get('name')))
        elif self.command=='POST' and collection:
            length=int(self.headers.get('Content-Length','0'))
            if length>saved_backtests.MAX_BYTES:
                self.reply(413,dict(error='This backtest is too large to save as one record.'));return
            if length<=0:raise ValueError('Expected a completed backtest.')
            def invalid_constant(value):raise ValueError('Saved values must be finite.')
            request=json.loads(self.rfile.read(length),parse_constant=invalid_constant)
            if not isinstance(request,dict):raise ValueError('Expected a completed backtest.')
            if 'reader' in request:
                record=self.server.result_access.save_reader(request.get('name'),request['reader'])
                self.reply(201,record)
            else:self.reply(201,store.save(request.get('name'),request.get('snapshot')))
        else:self.reply(405,dict(error='Unsupported saved-backtest action.'))
    except saved_backtests.Full as error:self.reply(409,dict(error=str(error)))
    except saved_backtests.Missing as error:self.reply(404,dict(error=str(error)))
    except durable_evidence.RequiresReader as error:self.reply(409,dict(error=str(error),requires_reader=True))
    except (ValueError,TypeError,UnicodeError) as error:self.reply(400,dict(error=str(error)))
    except (OSError,sqlite3.Error) as error:
        diagnostics.failure('saved_backtest.failed',error)
        self.reply(500,dict(error='Could not access saved backtests. Your existing records were kept. Check the development log.'))

def dispatch(handler,store):
    path=handler.path
    parts=path.removeprefix('/api/backtest-runs/').split('/')
    if path.startswith('/api/backtest-runs/') and parts[1:2]==['reader']:
        origin=handler.headers.get('Origin')
        if origin and origin!='http://'+handler.headers.get('Host',''):
            handler.reply(403,dict(error='Open the website to manage backtest runs.'))
        else:evidence_request(handler,parts[0],parts[2:])
    elif (path=='/api/backtests' and handler.command!='DELETE') or path.startswith('/api/backtests/'):
        saved_backtest_request(handler,store)
    else:return False
    return True
