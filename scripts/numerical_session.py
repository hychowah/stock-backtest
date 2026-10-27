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
import numerical_random
from numerical_matrix import retained_size
import schedules
import trial_checkpoints
from process_owner import process_metrics
from collections import OrderedDict


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
            self.checkpoints = trial_checkpoints.Store(configuration['checkpoint_path'])
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
        return robustness.plan(self.portfolio.db,**deepcopy(options))

    def calculate(self, mode, options, progress, configuration, *, planned=None, capture=None):
        self.validate()  # Always before result/checkpoint lookup, even a full hit.
        if mode == 'random':
            plan = self.plan(options) if planned is None else numerical_random.validate_configuration(self.portfolio,planned)
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
            key = (self.inputs.signature, trial_checkpoints.canonical(options))
            if key in self.results:
                result = self.results.pop(key); self.results[key] = result
                self.stats['result_hits'] += 1
                result = deepcopy(result)
            else:
                self.stats['result_misses'] += 1
                evaluate = self.portfolio.backtest_dates if 'dates' in options else self.portfolio.backtest
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
