"""Affine numerical resources for one persistent source/financial session.

This is a calculation capability. Application jobs and queue records stay with
backtest_jobs and backtest_queue. The bootstrap owns source then financial access.
"""
from copy import deepcopy
import robustness

import backtest_control
from numerical_generation import GenerationStore
from numerical_numba import NumbaExecutor
from numerical_portfolio import NumericalPortfolio
import numerical_calendar
import numerical_random
from numerical_matrix import retained_size
import schedules
import trial_checkpoints
import result_evidence
from process_owner import process_metrics
from collections import OrderedDict


def _validate_submitted(options, plan):
    """Keep recorded settings exact, accepting the legacy omitted order only.

    The recorded plan remains unchanged. Comparing defaults must not resample
    dates or allow a different explicit financial setting to use the plan.
    """
    submitted = {'selection_order':'filter_first', **plan['options']}
    submitted.update(numerical_calendar.request_fields(plan),
                     trials=plan['requested'], seed=plan['seed'])
    for key, value in {'selection_order':'filter_first', **options}.items():
        if key not in submitted or value != submitted[key]:
            raise ValueError('Submitted settings differ from the recorded random plan.')


class Session:
    def __init__(self, configuration):
        self.configuration = configuration
        self.inputs = self.provider = self.portfolio = self.checkpoints = None
        self.loaded_source = numerical_random.source_identity()
        self.results = OrderedDict()
        self.result_bytes = configuration.get('result_cache_bytes',16*1024**2)
        self.result_workspace_bytes = configuration.get('result_workspace_bytes',256*1024**2)
        if (type(self.result_bytes) is not int or self.result_bytes < 0
                or type(self.result_workspace_bytes) is not int or self.result_workspace_bytes <= 0):
            raise ValueError('Invalid runtime result budgets.')
        self.store = GenerationStore(schedules, configuration['generation_path'])
        self.closed = False
        self.stats = dict(result_hits=0,result_misses=0,result_retained_bytes=0,attached_generations=0,
                          peak_result_graph_bytes=0,result_workspace_bytes=self.result_workspace_bytes)
        try:
            self.checkpoints = trial_checkpoints.Store(configuration['checkpoint_path'],
                max_payload_bytes=configuration.get('checkpoint_payload_bytes',trial_checkpoints.DEFAULT_PAYLOAD_BYTES))
            self.validate()
        except BaseException as error:
            try: self.close()
            except BaseException:
                error.numerical_session = self
            raise

    def _close_attachment(self):
        # Borrowers must drop their views before mappings and generation lease.
        for name in ('portfolio','provider','inputs'):
            value = getattr(self,name)
            if value is not None:
                value.close()
                setattr(self,name,None)
        self.results.clear()
        self.stats['result_retained_bytes'] = 0

    def validate(self):
        backtest_control.checkpoint()
        if self.closed: raise ValueError('Numerical session is closed.')
        if numerical_random.source_identity() != self.loaded_source:
            self.results.clear()
            raise ValueError('Loaded calculation source changed. Close this runtime and start a new process.')
        pointer = self.store._pointer()
        identity = pointer['current'] if pointer else None
        if self.inputs is not None and identity != self.inputs.signature:
            raise ValueError('Numerical generation changed. Close this runtime and start a new process.')
        if self.inputs is None:
            self.inputs = self.store.open_current()
            self.provider = NumbaExecutor(self.inputs, limits=dict(
                threads=self.configuration['threads'],request_plan=True,candidate_assembly='source',
                matrix_cache_bytes=self.configuration.get('matrix_cache_bytes',16*1024**2),
                workspace_bytes=self.configuration.get('workspace_bytes',64*1024**2),
                chunk_rows=self.configuration.get('chunk_rows',1024)))
            self.portfolio = NumericalPortfolio(self.inputs,self.provider,result_workspace_bytes=self.result_workspace_bytes)
            self.stats['attached_generations'] = 1
        self.inputs.validate()
        backtest_control.checkpoint()

    def plan(self, options):
        # The private SQL workspace contains immutable sessions. Use the ordinary
        # planner, including its fresh default seed and exact envelope.
        configuration,selection,_=numerical_calendar.decode_request(options)
        selection.pop('trials',None);selection.pop('seed',None)
        self.portfolio.validate_selection(selection)
        if 'calendar' in options:
            return numerical_calendar.plan(self.portfolio._calendar().sessions,options,
                checkpoint=backtest_control.checkpoint)
        return robustness.plan(self.portfolio.db,**deepcopy(options))

    def calculate(self, mode, options, progress, configuration, *, planned=None, capture=None):
        self.validate()  # Always before result/checkpoint lookup, even a full hit.
        if mode == 'random':
            plan = self.plan(options) if planned is None else numerical_random.validate_configuration(self.portfolio,planned)
            if planned is not None:
                _validate_submitted(options, plan)
            count = min(len(self.inputs.symbols),plan['options'].get('rank_to',50)-plan['options'].get('rank_from',1)+1)
            estimate = sum(len(dates) for dates in plan['samples'])*(16384+4096*count)
            if estimate > self.result_workspace_bytes:
                raise ValueError('Random result exceeds the runtime result workspace bound.')
            configuration(deepcopy(plan))
            experiment = self.checkpoints.open(numerical_random.checkpoint_binding(self.portfolio,plan))
            details = []
            graph_bytes = 0
            def observed(number,result):
                nonlocal graph_bytes
                graph_bytes += retained_size(result)+4096
                self.stats['peak_result_graph_bytes'] = max(self.stats['peak_result_graph_bytes'],graph_bytes)
                if graph_bytes > self.result_workspace_bytes:
                    raise ValueError('Random result exceeds the runtime result workspace bound.')
                details.append(result)
                if capture is not None: capture(number,result)
            result = numerical_random.run(self.portfolio,plan,experiment,progress,capture=observed)['result']
            result['trial_results'] = details
        elif mode == 'custom':
            _, selection, _ = numerical_calendar.decode_request(options)
            selection.pop('dates', None)
            self.portfolio.validate_selection(selection)
            key = (self.inputs.signature, trial_checkpoints.canonical(options))
            if key in self.results:
                result = self.results.pop(key); self.results[key] = result
                self.stats['result_hits'] += 1
                result = deepcopy(result)
            else:
                self.stats['result_misses'] += 1
                evaluate = (self.portfolio.backtest_calendar if 'calendar' in options else
                            self.portfolio.backtest_dates if 'dates' in options else self.portfolio.backtest)
                result = evaluate(**options)['result']
                if retained_size(OrderedDict([(key,result)])) <= self.result_bytes:
                    self.results[key] = deepcopy(result)
                    while retained_size(self.results) > self.result_bytes: self.results.popitem(last=False)
            self.stats['result_retained_bytes'] = retained_size(self.results) if self.results else 0
        else: raise ValueError('Expected backtest mode and options.')
        size = retained_size(result)
        self.stats['peak_result_graph_bytes'] = max(self.stats['peak_result_graph_bytes'],size)
        if size > self.result_workspace_bytes:
            raise ValueError('Complete result exceeds the runtime result workspace bound.')
        backtest_control.checkpoint()
        return result

    def calculate_into(self, mode, options, stream, progress, configuration, *, planned=None,
                       max_bytes, piece_bytes, record_bytes):
        """Produce complete evidence without retaining previous periods.

        The caller owns output storage and publication. This explicit operation
        has no complete-trial observer and changes no eager admission guard.
        """
        self.validate()
        if mode not in ('custom','random'):raise ValueError('Expected backtest mode and options.')
        if planned is not None and mode!='random':raise ValueError('A recorded plan requires random mode.')
        plan=None
        if mode=='random':
            plan=self.plan(options) if planned is None else numerical_random.validate_configuration(self.portfolio,planned)
            if planned is not None:
                _validate_submitted(options, plan)
            configuration(deepcopy(plan))
        writer=result_evidence.Writer(stream,trials=plan['requested'] if plan else 1,
            metadata=dict(mode=mode,options=deepcopy(options),configuration=plan,
                          generation=self.inputs.signature,source=self.loaded_source),
            max_bytes=max_bytes,piece_bytes=piece_bytes,record_bytes=record_bytes,
            checkpoint=backtest_control.checkpoint)
        if plan is not None:
            experiment=self.checkpoints.open(numerical_random.checkpoint_binding(self.portfolio,plan))
            numerical_random.run_into(self.portfolio,plan,experiment,writer,progress)
        else:
            writer.start_trial(1)
            result=self.portfolio.backtest_calendar_into(writer.period,**options)['result']
            writer.end_trial(result);writer.finish(result)
        backtest_control.checkpoint()

    def measurements(self):
        return dict(**self.stats,**process_metrics(),generation=self.inputs.signature,
            compiler_identity=deepcopy(self.provider.compiler),
            matrix=deepcopy(self.provider._calculate.stats),
            provider=deepcopy(self.provider.stats),checkpoints=self.checkpoints.measurements())

    def close(self):
        if self.closed: return
        if self.checkpoints is not None:
            self.checkpoints.close(); self.checkpoints = None
        self._close_attachment()
        self.closed = True
