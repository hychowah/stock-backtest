"""Data-panel HTTP policy and source-served recovery routes."""
import ipaddress
import json
from urllib.parse import urlsplit
from website.rendering.assets import data_page

def data_allowed(self):
    try:
        local=ipaddress.ip_address(self.client_address[0]).is_loopback
        host=urlsplit('http://'+self.headers.get('Host','')).hostname
    except ValueError:return False
    return local and host in ('127.0.0.1','localhost','::1') and self.headers.get('Origin','http://'+self.headers.get('Host',''))=='http://'+self.headers.get('Host','')

def data_request(self,jobs):
    if not data_allowed(self):self.reply(403,dict(error='Open the data panel on this computer using localhost or 127.0.0.1.'));return
    action=self.path.removeprefix('/api/data/')
    if action not in ('check','download','rebuild','cancel'):
        self.reply(404,dict(error='Unknown data action.'));return
    try:
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=16*1024**2:raise ValueError('Invalid request size.')
        request=json.loads(self.rfile.read(length))
        if not isinstance(request,dict):raise ValueError('Expected data options.')
        self.reply(202,jobs.cancel_job() if action=='cancel' else jobs.start(action,request))
    except (ValueError,TypeError):
        self.reply(400,dict(error='Invalid data options, or another data job is running. Check dates, stock symbols and selected data types.'))

def dispatch(handler,jobs):
    if handler.path=='/data.html' and handler.command=='GET':
        body=data_page().encode('utf-8')
        handler.send_response(200);handler.send_header('Content-Type','text/html; charset=utf-8')
        handler.send_header('Cache-Control','no-store');handler.send_header('Content-Length',str(len(body)))
        handler.end_headers();handler.wfile.write(body)
    elif handler.path=='/api/data/status' and handler.command=='GET':
        if not data_allowed(handler):handler.reply(403,dict(error='Open the data panel on this computer using localhost or 127.0.0.1.'));return True
        handler.reply(200,jobs.snapshot())
    elif handler.path.startswith('/api/data/') and handler.command=='POST':
        data_request(handler,jobs)
    else:return False
    return True
