"""Complete recorded-scope inspection under a borrowed prepared view."""
import hashlib
from datetime import date

from backtest.application import scalar_execution, strategy_requests
from backtest.runtime import backtest_control
from backtest.variables import definitions, library, reference


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
            or scope['mode'] not in ('historical','latest') or scope['pool'] not in ('legacy','cached')
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
    latest=scope['mode']=='latest';budget=scalar_execution.Budget()
    rows,roots,plans,work=scalar_execution.plan_scope(source,view,program,checked,
        None if latest else scope['book'],scope['context_date'],latest=latest,
        owner_scope=dict(kind='prepared',book=scope['book']),budget=budget,checkpoint=checkpoint)
    outputs=[]; seen=set()
    for root in definitions.require_program(program)['bundle']['roots']:
        identity=root['variable_id'],root['revision']
        if identity in seen:continue
        seen.add(identity)
        outputs.append(dict(variable_id=root['variable_id'],revision=root['revision'],valid=0,unavailable=0,reasons={}))
    # Reserve complete, bounded reason tables before observation. Every reason
    # is a short provider-owned code; unexpected excess fails the whole request.
    if (len(outputs)*64*128 + scalar_execution._size(rows)*2 + scalar_execution._size(view.projection)
            + sum(len(plan.document) for plan in plans)>budget.metadata_bytes):
        raise definitions.FormulaError('WORK_LIMIT','/coverage','Coverage output exceeds its reservation.')
    by_id={(item['variable_id'],item['revision']):item for item in outputs}
    admitted=0;admission_reasons={}
    for plan in plans:
        checkpoint();block=reference.evaluate(plan,view,checkpoint).to_dict()
        for item in block['observations']['roots']:
            if item['admitted']:admitted+=1
            else:
                reason=item['reason'];admission_reasons[reason]=admission_reasons.get(reason,0)+1
        delivered=set()
        for result in block['results']:
            key=result['request'],result['variable_id'],result['revision']
            if key in delivered:continue
            delivered.add(key)
            output=by_id[result['variable_id'],result['revision']]
            if result['valid']:output['valid']+=1
            else:
                output['unavailable']+=1
                reason=result['reason']
                if reason!='ROOT_NOT_ADMITTED':output['reasons'][reason]=output['reasons'].get(reason,0)+1
        for reasons in [admission_reasons]+[item['reasons'] for item in outputs]:
            if len(reasons)>64 or any(type(key) is not str or len(key)>64 for key in reasons):
                raise definitions.FormulaError('WORK_LIMIT','/coverage','Coverage reason table exceeds its reservation.')
    view.validate();checkpoint()
    return dict(generation=discovery['generation'],scope=exact,projection=view.projection,
        program=definitions.require_program(program)['bundle_revision'],population=len(rows),
        provider_admitted=admitted,provider_unavailable=len(rows)-admitted,provider_reasons=admission_reasons,outputs=outputs,
        work=dict(inspected_rows=work,tasks=budget.tasks))
