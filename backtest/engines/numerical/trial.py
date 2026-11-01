"""One recorded numerical trial and bounded provisional evidence.

The caller owns source/cache coordination, the supplied portfolio, provider,
input attachment and binary streams. This module owns no process, checkpoint,
path, lock or publication. A calculation identity comes from the coordinator's
validated binding. The trusted expected task envelope supplies authenticity;
hashes alone do not authenticate an arbitrary producer.
"""
from backtest import portfolio_results
from backtest.runtime import backtest_control

from copy import deepcopy
from datetime import date

from backtest import calendar_requests as numerical_calendar
from backtest import portfolio_results as portfolio_results
from backtest import result_evidence as result_evidence
from backtest.engines.numerical import checkpoints as trial_checkpoints

VERSION = 1
_SPEC_FIELDS = frozenset(('version','number','calculation_identity','request',
                          'options','window_start','window_end','sha256'))
_DESCRIPTOR_FIELDS = frozenset(('version','number','calculation_identity',
                                'specification','start','end','sha256','limits'))


def calculation_identity(binding):
    """Use the existing complete canonical calculation binding unchanged."""
    return trial_checkpoints.digest(trial_checkpoints.binding_json(binding))


def specification(binding, number):
    """Detach exactly one already validated recorded trial; never sample dates."""
    identity=calculation_identity(binding)
    config=binding['configuration']
    if type(number) is not int or not 1<=number<=config['requested']:
        raise ValueError('Invalid recorded trial number.')
    value=dict(version=VERSION,number=number,calculation_identity=identity,
        request=dict(dates=deepcopy(config['samples'][number-1]),
                     **numerical_calendar.request_fields(config)),
        options=deepcopy(config['options']),window_start=config['window_start'],
        window_end=config['window_end'])
    value['sha256']=trial_checkpoints.digest(trial_checkpoints.canonical(value))
    return _specification(value)


def _hash(value):
    return type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def _day(value):
    if type(value) is not str:raise ValueError('Trial dates must be canonical ISO dates.')
    parsed=date.fromisoformat(value)
    if str(parsed)!=value:raise ValueError('Trial dates must be canonical ISO dates.')
    return parsed


def _specification(spec):
    if (type(spec) is not dict or set(spec)!=_SPEC_FIELDS
            or type(spec['version']) is not int or spec['version']!=VERSION
            or type(spec['number']) is not int or not 1<=spec['number']<=100
            or not _hash(spec['calculation_identity']) or not _hash(spec['sha256'])
            or type(spec['options']) is not dict or type(spec['request']) is not dict):
        raise ValueError('Invalid recorded trial specification.')
    value=deepcopy(spec)
    canonical=trial_checkpoints.canonical({k:v for k,v in value.items() if k!='sha256'})
    if trial_checkpoints.digest(canonical)!=value['sha256']:
        raise ValueError('Recorded trial specification digest differs.')
    request=value['request']
    fields={'dates','calendar'} if 'calendar' in request else {'dates','start','end','months'}
    if set(request)!=fields:raise ValueError('Invalid recorded trial request fields.')
    configuration,options,_=numerical_calendar.decode_request(request)
    dates=options['dates']
    first,final=_day(value['window_start']),_day(value['window_end'])
    if not _day(configuration.start)<=first<final<=_day(configuration.end):
        raise ValueError('Recorded trial window differs from its request.')
    if type(dates) is not list or not dates:
        raise ValueError('Recorded trial dates must be a nonempty list.')
    previous=None
    for day in dates:
        parsed=_day(day)
        if not first<=parsed<final or previous is not None and parsed<=previous:
            raise ValueError('Recorded trial dates differ from its window.')
        previous=parsed
    return value


def _limits(limits):
    if type(limits) is not dict or set(limits)!={'max_bytes','piece_bytes','record_bytes'}:
        raise ValueError('Declare complete trial evidence byte limits.')
    result_evidence._limits(**limits)
    return deepcopy(limits)


def _summary(summary,spec):
    if (type(summary) is not dict or 'periods' in summary
            or summary.get('start')!=spec['window_start'] or summary.get('end')!=spec['window_end']
            or numerical_calendar.metadata(summary)!=numerical_calendar.metadata(spec['request'])
            or trial_checkpoints.canonical(summary.get('options'))!=trial_checkpoints.canonical(spec['options'])):
        raise ValueError('Completed trial differs from its recorded specification.')
    return summary


def _pairs(spec):
    days=[_day(day) for day in spec['request']['dates']]+[_day(spec['window_end'])]
    return list(zip(days,days[1:]))


class TrialEvaluator:
    """Evaluate exactly one recorded trial.

    Never sample dates, replace settings or publish results. Validate the
    specification and selection before provider work. Emitted periods remain
    provisional until the complete operation succeeds. The portfolio is borrowed
    and retains ownership of its private SQL state.
    """
    def __init__(self,portfolio,*,calculation_identity):
        if not _hash(calculation_identity):raise ValueError('Invalid trial calculation identity.')
        self.portfolio,self.calculation_identity=portfolio,calculation_identity

    def _prepare(self,spec):
        value=_specification(spec)
        if value['calculation_identity']!=self.calculation_identity:
            raise ValueError('Recorded trial calculation identity differs.')
        portfolio=self.portfolio
        portfolio._validate_inputs()
        portfolio.validate_selection(value['options'])
        pairs,first,options,_=numerical_calendar.periods(portfolio._calendar().sessions,
            dict(**value['request'],**value['options']),checkpoint=backtest_control.checkpoint)
        if (str(first),str(pairs[-1][1]))!=(value['window_start'],value['window_end']):
            raise ValueError('Recorded trial window differs from saved sessions.')
        portfolio.validate_selection(options)
        return value

    def evaluate_into(self,spec,emit_period):
        if not callable(emit_period):raise ValueError('Choose a callable period sink.')
        value=self._prepare(spec)
        pairs=_pairs(value);count=0
        def emit(period):
            nonlocal count
            if (count>=len(pairs) or type(period) is not dict
                    or (period.get('entry'),period.get('exit'))!=tuple(map(str,pairs[count]))
                    or period.get('is_final_period') is not (count==len(pairs)-1)):
                raise ValueError('Trial producer changed a recorded period.')
            emit_period(period);count+=1
        evaluate=(self.portfolio.backtest_calendar_into if 'calendar' in value['request']
                  else self.portfolio.backtest_dates_into)
        envelope=evaluate(emit,**value['request'],**value['options'])
        if (envelope.get('contract_version')!=portfolio_results.CONTRACT_VERSION or count!=len(pairs)):
            raise ValueError('Trial producer returned incomplete financial evidence.')
        return _summary(envelope['result'],value)

    def produce(self,spec,stream,*,limits):
        """Seal calculated evidence. No commitment, progress or publication occurs."""
        value=self._prepare(spec);limits=_limits(limits)
        writer=result_evidence.SingleTrialWriter(stream,number=value['number'],**limits,
            checkpoint=backtest_control.checkpoint)
        try:
            summary=self.evaluate_into(value,writer.period)
            view=writer.finish(summary)
            return dict(version=VERSION,number=value['number'],calculation_identity=self.calculation_identity,
                specification=value['sha256'],start=view.start,end=view.end,sha256=view.sha256,limits=limits)
        except BaseException:
            writer.failed=True
            raise


class TrialArtifact:
    """Validated sealed evidence; stream and immutable bytes remain caller-owned."""
    def __init__(self,view,spec,checkpoint):
        self.view,self._spec,self._checkpoint=view,spec,checkpoint

    @property
    def summary(self):return self.view.summary

    def periods(self):return self.view.periods()

    def copy_into(self,emit_period):
        if not callable(emit_period):raise ValueError('Choose a callable period sink.')
        return portfolio_results.validate_completed_into(self.summary,self.view.periods(),_pairs(self._spec),
            emit_period,checkpoint=self._checkpoint)


def open_artifact(stream,descriptor,*,expected_spec,limits,checkpoint):
    """Validate caller-opened sealed bytes against the trusted expected task.

    Accept no worker-supplied path. Verification retains only bounded records and
    the current complete period. This object does not close or publish its stream.
    """
    spec=_specification(expected_spec);limits=_limits(limits)
    if (type(descriptor) is not dict or set(descriptor)!=_DESCRIPTOR_FIELDS
            or type(descriptor['version']) is not int or descriptor['version']!=VERSION
            or type(descriptor['number']) is not int or descriptor['number']!=spec['number']
            or descriptor['calculation_identity']!=spec['calculation_identity']
            or descriptor['specification']!=spec['sha256']
            or trial_checkpoints.canonical(descriptor['limits'])!=trial_checkpoints.canonical(limits)
            or type(descriptor['start']) is not int or descriptor['start']!=0
            or type(descriptor['end']) is not int or not 0<descriptor['end']<=limits['max_bytes']
            or not _hash(descriptor['sha256'])):
        raise ValueError('Trial artifact descriptor differs from the expected task or limits.')
    if stream.seek(0,2)!=descriptor['end']:
        raise ValueError('Trial artifact byte range differs.')
    view=result_evidence.TrialView(stream,start=descriptor['start'],end=descriptor['end'],
        sha256=descriptor['sha256'],number=spec['number'],piece_bytes=limits['piece_bytes'],
        record_bytes=limits['record_bytes'],checkpoint=checkpoint)
    _summary(view.summary,spec)
    portfolio_results.validate_completed_into(view.summary,view.periods(),_pairs(spec),checkpoint=checkpoint)
    return TrialArtifact(view,spec,checkpoint)
