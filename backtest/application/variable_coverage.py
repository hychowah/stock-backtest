"""Complete recorded-scope inspection under a borrowed prepared view.

Every snapshot row of one recorded latest scope is admitted and evaluated
values-only by the column evaluator; counts are exact.
"""
import hashlib
from datetime import date

from backtest.application import scalar_execution, strategy_requests
from backtest.runtime import backtest_control
from backtest.variables import columns, definitions, library


def scopes(source, view):
    """Discover exact recorded roots, including scopes with no snapshot rows."""
    view.validate()
    projection=view.projection
    if (len(projection['scopes'])>scalar_execution.MAX_SCOPES or
            scalar_execution._size(projection)>scalar_execution.MAX_METADATA_BYTES):
        raise definitions.FormulaError('WORK_LIMIT','/coverage','Recorded scope discovery exceeds its complete bound.')
    generation=hashlib.sha256(definitions.canonical(dict(input=view.identity,projection=projection)).encode()).hexdigest()
    return dict(generation=generation,scopes=projection['scopes'])


def inspect(capture, scope, source, view, checkpoint=backtest_control.checkpoint):
    """Reduce all captured output roots over one complete recorded population."""
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
    discovery=scopes(source,view)
    exact={k:scope[k] for k in ('mode','pool','context_date','book')}
    if scope['generation']!=discovery['generation'] or exact not in discovery['scopes']:
        raise definitions.FormulaError('STALE_INPUT_GENERATION','/scope','The recorded scope is absent or its generation changed.')
    checked=strategy_requests.require_strategy(capture,checkpoint=checkpoint)
    if checked['pool']!=scope['pool'] or checked['variables'] is None:
        raise ValueError('A captured formula and matching pool are required.')
    program=library.VariableCapture(definitions.canonical(checked['variables'])).program
    rows,roots=scalar_execution._scope(source,view,checked,None,scope['context_date'],
        latest=True,owner_scope=dict(kind='prepared',book=scope['book']))
    outputs=[]; seen=set()
    for root in definitions.require_program(program)['bundle']['roots']:
        identity=root['variable_id'],root['revision']
        if identity in seen:continue
        seen.add(identity)
        outputs.append(dict(variable_id=root['variable_id'],revision=root['revision'],valid=0,unavailable=0,reasons={}))
    by_id={(item['variable_id'],item['revision']):item for item in outputs}
    decisions=view.admit(roots,checkpoint)
    admitted=0;admission_reasons={}
    for decision in decisions:
        if decision['admitted']:admitted+=1
        else:admission_reasons[decision['reason']]=admission_reasons.get(decision['reason'],0)+1
    for decision in decisions:decision['owner_scope']=dict(kind='prepared',book=scope['book'])
    for values in columns.Formulas(program).evaluate(roots,view,checkpoint,decisions=decisions):
        for key,(value,valid,reason) in values.items():
            output=by_id[key]
            if valid:output['valid']+=1
            else:
                output['unavailable']+=1
                if reason!='ROOT_NOT_ADMITTED':output['reasons'][reason]=output['reasons'].get(reason,0)+1
    view.validate();checkpoint()
    return dict(generation=discovery['generation'],scope=exact,projection=view.projection,
        program=definitions.require_program(program)['bundle_revision'],population=len(rows),
        provider_admitted=admitted,provider_unavailable=len(rows)-admitted,provider_reasons=admission_reasons,outputs=outputs)
