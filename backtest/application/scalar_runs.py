"""Original scalar orchestration over existing dated books and financial reduction.

The caller owns admitted connections, borrowed observation view and output writer.
Calendar sampling, trial book publication and portfolio arithmetic remain delegated
owners. This module never owns a library lookup.
"""
from datetime import date
import time

from backtest import calendar_requests, portfolio_results
from backtest.application import scalar_execution, strategy_requests
from backtest.variables import definitions
from backtest.runtime import diagnostics
from backtest.engines.original import schedules, robustness, book_batch


class TrialSink:
    def __init__(self, writer, requested):
        self.writer, self.requested = writer, requested
    def start_trial(self, number):
        self.counts = [0,0,0]
        self.writer.start_trial(number)
    def period(self, period):
        self.counts[0] += 1; self.counts[1] += period['names'] == 0
        self.counts[2] += period['names'] < self.requested
        self.writer.period(period)


def check_size(writer, executor, periods):
    """Refuse, before any work, a result that would exceed the writer's byte bound.

    The estimate is an upper bound from record sizes measured on the real cache
    (2026-11-05): about 8 KB per screen date, 3.2 KB per holding and, for each
    explained holding, 300 B plus 350 B per formula node and 600 B per observed
    member. The writer's bound still applies during the run.
    """
    selection = executor.capture['selection']
    ranks = selection['rank_to'] - selection['rank_from'] + 1
    trace = 0
    if executor.formulas is not None and executor.explain:
        nodes = executor.formulas.projection['nodes']
        members = sum(node.get('count', 1) for node in nodes if node['op'] in ('parameter', 'annual'))
        trace = 300 + 350 * len(nodes) + 600 * members
    estimate = periods * (8 * 1024 + ranks * (3200 + trace))
    if estimate > writer.max_bytes:
        raise definitions.FormulaError('WORK_LIMIT', '/execution',
            f'This test would store about {estimate / 1e6:.0f} MB of results, above the '
            f'{writer.max_bytes / 1e6:.0f} MB limit. Use fewer trials, dates or ranks.')


def execute(db, source, mode, options, writer, view, configuration, *, planned=None, progress=None, checkpoint=lambda:None):
    checked = strategy_requests.check_options(options, checkpoint=checkpoint)
    capture = strategy_requests.CapturedStrategy(strategy_requests._encode(checked,strategy_requests.STRATEGY_BYTES,checkpoint))
    # Random-date runs keep formula values and reasons, not step traces.
    executor = scalar_execution.Executor(capture, view, source, writer.evidence, record_bytes=writer.record_bytes,
                                         checkpoint=checkpoint, explain=mode != 'random')
    requested = checked['selection']['rank_to']-checked['selection']['rank_from']+1
    diagnostics.note(pool=checked['pool'],conditions=len(checked['selection']['conditions']))
    sink = TrialSink(writer, requested)
    started = time.perf_counter()
    selection = dict(strategy=options['strategy'])
    producer = dict(engine='original',label='Original')
    if mode in ('latest','january'):
        return prepared(executor,source,mode,options,writer,view,producer=producer,checkpoint=checkpoint)
    if mode == 'random':
        with diagnostics.stage('plan'):
            sessions = [date.fromisoformat(row[0]) for row in db.execute('SELECT day FROM sessions ORDER BY day')]
            if planned is None:
                planned = calendar_requests.plan(sessions,options,checkpoint=checkpoint)
            else:
                strategy_requests.validate_recorded(options,planned)
                planned = calendar_requests.validate_plan(sessions,planned,checkpoint=checkpoint)
        check_size(writer, executor, sum(len(sample) for sample in planned['samples']))
        if configuration:configuration(planned)
        summaries = []; execution = {}
        for number,result,stats in book_batch.evaluate_trials(db,planned,progress,book_selection=executor,trial_sink=sink):
            # The recorded plan retains its original labels; this trial retains
            # the new submission's exact capture after a presentation-only edit.
            result['options'] = selection
            summaries.append(robustness.summarize(result,number,planned['samples'][number-1],period_counts=sink.counts))
            writer.end_trial(result)
            execution = dict(stats)
        if len(summaries) != planned['requested']:
            raise ValueError('Completed scalar trial count differs from its recorded plan.')
        summary = robustness.summarize_trials(planned,summaries,started)
        summary.update(execution=execution,producer=producer)
        diagnostics.note(trials=len(summaries),periods=sum(row['periods'] for row in summaries),execution=execution)
        return summary
    if mode != 'custom':raise ValueError('Unsupported scalar execution mode.')
    if 'months' in options and 'calendar' not in options and 'dates' not in options:
        sessions = [date.fromisoformat(row[0]) for row in db.execute('SELECT day FROM sessions ORDER BY day')]
        check_size(writer, executor, len(schedules.schedule(options['start'], options['end'], options['months'], sessions)))
    sink.start_trial(1)
    evaluator = schedules.backtest_calendar if 'calendar' in options else schedules.backtest_dates if 'dates' in options else schedules.backtest
    summary = evaluator(db,book_selection=executor,emit_period=sink.period,**options)
    summary['producer'] = producer
    diagnostics.note(periods=sink.counts[0])
    writer.end_trial(summary)
    return summary


def reduce_periods(pairs,select,emit,options,metadata,*,common_start=None,checkpoint=lambda:None):
    """One scalar financial reducer; scope production and publication stay outside."""
    started=time.perf_counter()
    summary=portfolio_results.evaluate_into(pairs,select,emit,common_start=common_start,
        checkpoint=checkpoint,contract=2)
    summary.update(metadata,options=options,seconds=time.perf_counter()-started)
    return summary


def prepared(executor,source,mode,options,writer,view,*,producer,checkpoint=lambda:None):
    """Read authoritative stored scopes; no dated-book reconstruction occurs."""
    requested=executor.capture['selection']['rank_to']-executor.capture['selection']['rank_from']+1
    started=time.perf_counter()
    if mode == 'latest':
        asof = view.bounds['latest_date']
        with diagnostics.stage('selection'):
            stocks = executor.select(source,None,date.fromisoformat(asof),latest=True,owner_scope=dict(kind='prepared',book=0))
        for stock in stocks:writer.screen(stock)
        return dict(asof=asof,requested=requested,names=len(stocks),options=options,producer=producer)
    if mode == 'january':
        first,last = options.get('first',1996),options.get('last',2026)
        if any(type(v) is not int for v in (first,last)) or not 1996 <= first <= last <= 2026:
            raise ValueError('Choose increasing integer years within 1996–2026.')
        rows = source.execute('SELECT year,entry,exit,spy FROM periods WHERE year BETWEEN ? AND ? ORDER BY year',(first,last)).fetchall()
        if not rows or [row[0] for row in rows] != list(range(first,last+1)):
            raise ValueError('Complete requested January periods are unavailable.')
        pairs = [(date.fromisoformat(row[1]),date.fromisoformat(row[2])) for row in rows]
        by_entry = {row[1]:row for row in rows}
        def select(entry,exit_day):
            row = by_entry[str(entry)]
            with diagnostics.stage('selection'):
                holdings = executor.select(source,row[0],entry,exit_day,owner_scope=dict(kind='prepared',book=row[0]))
            return dict(entry=str(entry),exit=str(exit_day),spy=row[3],holdings=holdings)
        diagnostics.note(periods=len(pairs))
        writer.start_trial(1)
        summary = reduce_periods(pairs,select,writer.period,options,{},checkpoint=checkpoint)
        summary.update(options=options,first=first,last=last,seconds=time.perf_counter()-started,producer=producer)
        writer.end_trial(summary)
        return summary
