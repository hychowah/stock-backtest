"""Original scalar orchestration over existing dated books and financial reduction.

The caller owns admitted connections, borrowed observation view and output writer.
Calendar sampling, trial book publication and portfolio arithmetic remain delegated
owners. This module never owns a library lookup. A large random-date run whose
books are all stored evaluates its trials in worker processes (stored_trials).
"""
from collections import deque
from concurrent.futures import ProcessPoolExecutor, TimeoutError
from contextlib import closing, contextmanager
from datetime import date
from functools import partial
import multiprocessing
import time

from backtest import selection, calendar_requests
from backtest.application import scalar_execution, strategy_requests
from backtest.inputs import daily, fact_view, facts
from backtest.variables import definitions
from backtest.runtime import diagnostics
from backtest.engines.original import schedules, robustness, book_batch, curves


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


TRIAL_WORKERS = 8
MIN_PARALLEL_PERIODS = 96
_worker = None


def initialize_worker(path, research, expected, market, capture, record_bytes, configuration):
    """Give a trial worker its own reader, view and executor of the parent's admitted inputs."""
    global _worker
    book_batch.follow_parent()
    db = book_batch.open_reader(path, research, expected)
    # The parent holds cache ownership and checks freshness at the end of the operation.
    view = fact_view.View(db, lambda: None, lambda: None, market=market)
    _worker = db, configuration, scalar_execution.Executor(capture, view, None, record_bytes=record_bytes, explain=False)


def worker_trial(number, scopes):
    """Evaluate one whole trial; return its result and its evidence and period records in order.

    scopes is the number of scopes of the earlier trials: the executor numbers
    scopes across the run. Nothing is written.
    """
    db, configuration, executor = _worker
    records = []
    executor.number = scopes
    executor.sink = lambda record: records.append((True, record))
    result = book_batch.evaluate_trial(db, configuration, configuration['samples'][number - 1], book_selection=executor,
                                       emit_period=lambda period: records.append((False, period)))
    return result, records


@contextmanager
def stored_trials(db, planned, capture, market, writer, sink, checkpoint):
    """Yield the worker count and the results of stored-book trials, in trial order.

    Each worker evaluates whole trials with the serial code and writes
    nothing. The parent replays a trial's records into the writer and the sink
    in their original order, so the stream equals the serial stream. A trial
    has one scope for each date of its sample. At most twice the worker count
    of trials is in flight. A Stop waits for the running trials.
    """
    workers = min(TRIAL_WORKERS, len(planned['samples']))
    pool = ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn'),
        initializer=initialize_worker, initargs=(book_batch.database_path(db), book_batch.database_path(db, 'research'),
            daily.binding(db), market, capture, writer.record_bytes, planned))
    pending = deque(); remaining = enumerate(planned['samples'], 1); scopes = 0
    def submit():
        nonlocal scopes
        number, dates = next(remaining, (None, ()))
        if number is not None:
            pending.append(pool.submit(worker_trial, number, scopes)); scopes += len(dates)
    def ordered():
        for unused in range(2 * workers): submit()
        number = 0
        while pending:
            future = pending.popleft(); number += 1
            with diagnostics.stage('trials'):
                while True:
                    try: result, records = future.result(timeout=.25); break
                    except TimeoutError: checkpoint()
                submit()
                sink.start_trial(number)
                for evidence, record in records:
                    (writer.evidence if evidence else sink.period)(record)
            yield result
    results = ordered()
    try:
        yield workers, results
    finally:
        results.close()
        for future in pending: future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)


def check_size(writer, executor, periods, days):
    """Refuse, before any work, a result that would exceed the writer's byte bound.

    The estimate is an upper bound from record sizes measured on the real cache
    (2026-11-05): about 8 KB per screen date, 3.2 KB per holding and, for each
    explained holding, 300 B plus 350 B per formula node and 600 B per observed
    member. days is the number of curve rows: the sessions after each trial's
    first trade, through its end (curves.days). A row is an ISO day and two
    full-precision numbers, at most 70 B. The writer's bound still applies
    during the run.
    """
    first, last = selection.rank_range(dict(strategy=executor.capture))
    ranks = last - first + 1
    trace = 0
    if executor.formulas is not None and executor.explain:
        nodes = executor.formulas.projection['nodes']
        members = sum(node.get('count', 1) for node in nodes if node['op'] in ('parameter', 'annual'))
        trace = 300 + 350 * len(nodes) + 600 * members
    step_bytes = len(executor.capture['steps']) * 512 if executor.capture['version'] == 2 else 0
    estimate = periods * (8 * 1024 + ranks * (3200 + trace + step_bytes)) + days * 70
    if estimate > writer.max_bytes:
        raise definitions.FormulaError('WORK_LIMIT', '/execution',
            f'This test would store about {estimate / 1e6:.0f} MB of results, above the '
            f'{writer.max_bytes / 1e6:.0f} MB limit. Use fewer trials, dates or ranks.')


def execute(db, mode, options, writer, view, configuration, *, planned=None, progress=None, checkpoint=lambda:None):
    checked = strategy_requests.check_options(options, checkpoint=checkpoint)
    capture = strategy_requests.CapturedStrategy(strategy_requests._encode(checked,strategy_requests.STRATEGY_BYTES,checkpoint))
    # Random-date runs keep formula values and reasons, not formula operation traces.
    executor = scalar_execution.Executor(capture, view, writer.evidence, record_bytes=writer.record_bytes,
                                         checkpoint=checkpoint, explain=mode != 'random')
    first, last = selection.rank_range(options)
    requested = last - first + 1
    diagnostics.note(pool=strategy_requests.pool(checked))
    sink = TrialSink(writer, requested)
    started = time.perf_counter()
    result_options = {key:options[key] for key in ('strategy','market') if key in options}
    producer = dict(engine='original',label='Original')
    if mode == 'latest':
        # The stored open book of the book store; no dated-book reconstruction occurs.
        asof = view.bounds['latest_date']
        with diagnostics.stage('selection'):
            stocks = executor.select(db,view.open_book,date.fromisoformat(asof),latest=True)
        for stock in stocks:writer.screen(stock)
        return dict(asof=asof,requested=requested,names=len(stocks),options=options,producer=producer)
    if mode == 'random':
        with diagnostics.stage('plan'):
            sessions = facts.sessions(db,options.get('market','us'))
            if planned is None:
                planned = calendar_requests.plan(sessions,options,checkpoint=checkpoint)
            else:
                strategy_requests.validate_recorded(options,planned)
                planned = calendar_requests.validate_plan(sessions,planned,checkpoint=checkpoint)
        end = date.fromisoformat(planned['window_end'])
        periods = sum(len(sample) for sample in planned['samples'])
        check_size(writer, executor, periods,
                   sum(len(curves.days(sessions, date.fromisoformat(sample[0]), end)) for sample in planned['samples']))
        if configuration:configuration(planned)
        summaries = []; execution = {}
        parallel = len(planned['samples']) >= 2 and periods >= MIN_PARALLEL_PERIODS
        trials = book_batch.evaluate_trials(db,planned,progress,book_selection=executor,trial_sink=sink,
            stored_trials=partial(stored_trials,db,planned,capture,view.market,writer,sink,checkpoint) if parallel else None)
        # Closing the trials joins their workers before the caller releases the inputs.
        with closing(trials):
            for number,result,stats in trials:
                # The recorded plan retains its original labels; this trial retains
                # the new submission's exact capture after a presentation-only edit.
                result['options'] = result_options
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
        sessions = facts.sessions(db,options.get('market','us'))
        periods = calendar_requests.periods(sessions, {key: options[key] for key in ('start', 'end', 'months')},
                                            checkpoint=checkpoint)[0]
        check_size(writer, executor, len(periods), len(curves.days(sessions, periods[0][0], periods[-1][1])))
    sink.start_trial(1)
    evaluator = schedules.backtest_calendar if 'calendar' in options else schedules.backtest_dates if 'dates' in options else schedules.backtest
    summary = evaluator(db,book_selection=executor,emit_period=sink.period,**options)
    summary['producer'] = producer
    diagnostics.note(periods=sink.counts[0])
    writer.end_trial(summary)
    return summary

