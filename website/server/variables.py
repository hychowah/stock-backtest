"""Bounded same-origin variable authoring; no financial or library SQL access."""
import json
from backtest.application import formula_text, variable_authoring, strategy_requests
from backtest.variables import library
from backtest.runtime import diagnostics

STORE = library.Store()
MAX_REQUEST = strategy_requests.REQUEST_BYTES


def dispatch(handler):
    path=handler.path.split('?',1)[0]
    if path!='/api/variables' and not path.startswith('/api/variables/'):
        return False
    origin=handler.headers.get('Origin')
    if origin and origin!='http://'+handler.headers.get('Host',''):
        handler.reply(403,dict(error='Open the website to manage variables.'));return True
    store=getattr(handler.server,'variable_store',STORE)
    parts=path.removeprefix('/api/variables').strip('/').split('/') if path!='/api/variables' else []
    try:
        if handler.command=='GET':
            if not parts:value=dict(entries=variable_authoring.entries(store))
            elif parts==['catalog']:value=variable_authoring.catalog()
            else:raise ValueError('Use an exact authored read to open a variable.')
        elif handler.command=='POST':
            length=int(handler.headers.get('Content-Length','0'))
            if not 0<length<=MAX_REQUEST:raise ValueError('Variable request exceeds its complete byte bound.')
            def invalid(value):raise ValueError('Variable values must be finite JSON data.')
            request=json.loads(handler.rfile.read(length),parse_constant=invalid)
            if type(request) is not dict:raise ValueError('Expected variable authoring content.')
            if parts==['validate']:value=variable_authoring.validate(request,store)
            elif parts==['capture']:value=variable_authoring.prepare(request,store)
            elif parts==['detached']:value=variable_authoring.detached(request)
            elif parts==['authored']:value=variable_authoring.authoring_snapshot(request,store)
            elif not parts:value=store.create(request.get('name'),request.get('definition'),favourite=request.get('favourite',False))
            elif len(parts)==2:
                identifier,action=parts;version=request.get('version')
                if action=='save':value=store.save(identifier,version,request.get('name'),request.get('definition'))
                elif action=='edit':value=store.edit(identifier,version,request.get('definition'))
                elif action=='rename':value=store.rename(identifier,version,request.get('name'))
                elif action=='favourite':value=store.favourite(identifier,version,request.get('favourite'))
                elif action=='delete':value=store.delete(identifier,version)
                else:raise ValueError('Unknown variable action.')
            else:raise ValueError('Unknown variable action.')
        else:raise ValueError('Unsupported variable action.')
        handler.reply(200,value)
    except library.Conflict as error:handler.reply(409,dict(error=str(error)))
    except library.Missing as error:handler.reply(404,dict(error=str(error)))
    except (library.Unavailable,library.InvalidStore) as error:handler.reply(503,dict(error=str(error)))
    except formula_text.TextError as error:handler.reply(400,dict(error=str(error),errors=error.errors))
    except (ValueError,TypeError,KeyError,UnicodeError) as error:
        safe=str(error) if not isinstance(error,KeyError) else 'Variable request fields are incomplete.'
        handler.reply(400,dict(error=safe,**(strategy_requests.failure_details(error) or {})))
    except (OSError,) as error:
        diagnostics.failure('variable.request_failed',error)
        handler.reply(500,dict(error='Could not access the variable library. Existing data was kept.'))
    return True
