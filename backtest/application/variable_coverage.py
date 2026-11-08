"""Complete stored-book inspection under a borrowed prepared view.

Every stored row of one latest scope (the open book's pool) is its root's
admission and is evaluated values-only by the column evaluator; counts are
exact. A stored row is admitted by construction, so the population is the
admitted count.
"""
import hashlib
from datetime import date

from backtest.application import scalar_execution
from backtest.inputs import book_store
from backtest.runtime import backtest_control
from backtest.variables import columns, definitions


def scopes(db, view):
    """Discover the inspectable scopes: each completed pool of the stored open book, including empty pools.

    Dated books are not listed: no caller inspects one. An inspect request
    names only a scope discovered in the same generation (a book id is a
    handle, book_store).
    """
    view.validate()
    generation=hashlib.sha256(definitions.canonical(dict(input=view.identity,projection=view.projection)).encode()).hexdigest()
    book=book_store.open_book(db);entry=book_store.record(db,book)['entry']
    found=[dict(mode='latest',pool=pool,context_date=entry,book=book)
           for pool in ('legacy','cached') if book_store.find(db,entry,pool,latest=True)==book]
    return dict(generation=generation,scopes=found)


def inspect(checked, scope, db, view, checkpoint=backtest_control.checkpoint):
    """Reduce all captured output roots over one complete stored population.

    checked is the strategy that strategy_requests.check_options restored; its
    program projection is the evaluator's input. db is the operation's daily
    connection: the population is the open book's pool in the book store.
    """
    if (type(scope) is not dict or set(scope)!={'generation','mode','pool','context_date','book'}
            or type(scope['generation']) is not str or len(scope['generation'])!=64
            or any(c not in '0123456789abcdef' for c in scope['generation'])
            or scope['mode']!='latest' or scope['pool'] not in ('legacy','cached')
            or type(scope['book']) is not int or scope['book']<0 or type(scope['context_date']) is not str):
        raise definitions.FormulaError('INVALID_SHAPE','/scope','An exact discovered generation and scope are required.')
    try:
        if str(date.fromisoformat(scope['context_date']))!=scope['context_date']:raise ValueError()
    except ValueError:
        raise definitions.FormulaError('INVALID_SHAPE','/scope/context_date','A canonical recorded date is required.') from None
    discovery=scopes(db,view)
    exact={k:scope[k] for k in ('mode','pool','context_date','book')}
    if scope['generation']!=discovery['generation'] or exact not in discovery['scopes']:
        raise definitions.FormulaError('STALE_INPUT_GENERATION','/scope','The recorded scope is absent or its generation changed.')
    if checked['pool']!=scope['pool'] or checked['variables'] is None:
        raise ValueError('A captured formula and matching pool are required.')
    projection=checked['variables']['program']
    rows,admission=scalar_execution._scope(db,checked,scope['book'],scope['context_date'],latest=True)
    outputs=[]; seen=set()
    for root in projection['bundle']['roots']:
        identity=root['variable_id'],root['revision']
        if identity in seen:continue
        seen.add(identity)
        outputs.append(dict(variable_id=root['variable_id'],revision=root['revision'],valid=0,unavailable=0,reasons={}))
    by_id={(item['variable_id'],item['revision']):item for item in outputs}
    # A stored row is its root's admission.
    roots,decisions=(list(items) for items in zip(*map(admission,range(len(rows))))) if rows else ([],[])
    for values in columns.Formulas(projection).evaluate(roots,view,checkpoint,decisions=decisions):
        for key,(value,valid,reason) in values.items():
            output=by_id[key]
            if valid:output['valid']+=1
            else:
                output['unavailable']+=1
                output['reasons'][reason]=output['reasons'].get(reason,0)+1
    view.validate();checkpoint()
    return dict(generation=discovery['generation'],scope=exact,projection=view.projection,
        program=projection['bundle_revision'],population=len(rows),outputs=outputs)
