"""Affine numerical resources for one persistent source/financial session.

This is a calculation capability. Application jobs and queue records stay with
backtest_jobs and backtest_queue. The bootstrap owns source then financial access.
"""

# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))
from copy import deepcopy
import robustness

import backtest_control
from numerical_generation import GenerationStore
from numerical_numba import NumbaExecutor as attach_provider
from numerical_identity import compiler_identity
from numerical_portfolio import NumericalPortfolio
from numerical_workspace import RequestWorkspace
from backtest import calendar_requests as numerical_calendar
import numerical_random
from numerical_matrix import retained_size
import schedules
import trial_checkpoints
import result_evidence
from process_owner import process_metrics
from collections import OrderedDict
from numerical_execution import ExecutionPolicy


from backtest.calendar_requests import validate_submitted as _validate_submitted


class Session:
    def __init__(self, configuration):
        self.configuration = configuration
        self.inputs = self.provider = self.portfolio = self.checkpoints = None
        self.trial_pool = self.workspace = None
        self.expected_compiler = None
        self.execution_policy = ExecutionPolicy.from_configuration(configuration)
        if configuration.get('preparation_status') and configuration.get('preparation_profile') is None:
            raise ValueError('A prepared request requires its execution profile.')
        if configuration.get('preparation_profile') not in (None,self.execution_policy.backend):
            raise ValueError('Session execution differs from its preparation profile.')
        self.loaded_source = numerical_random.source_identity()
        self.results = OrderedDict()
        self.result_bytes = configuration.get('result_cache_bytes',16*1024**2)
        self.result_workspace_bytes = configuration.get('result_workspace_bytes',256*1024**2)
        if (type(self.result_bytes) is not int or self.result_bytes < 0
                or type(self.result_workspace_bytes) is not int or self.result_workspace_bytes <= 0):
            raise ValueError('Invalid runtime result budgets.')
        self.store = GenerationStore(schedules, configuration['generation_path'])
        self.closed = False
        self.stats = dict(provider_constructions=0,result_hits=0,result_misses=0,result_retained_bytes=0,attached_generations=0,
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
        if self.trial_pool is not None:
            self.trial_pool.close()
            self.trial_pool = None
        for name in ('portfolio','workspace','provider','inputs'):
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
            self.workspace = RequestWorkspace(self.inputs,result_workspace_bytes=self.result_workspace_bytes)
            self.expected_compiler = compiler_identity(self.inputs,self.execution_policy.provider_limits['threads'],
                decisions=self.inputs.policy.decisions)
            self.stats['attached_generations'] = 1
        self.inputs.validate()
        backtest_control.checkpoint()

    def _portfolio(self):
        """Construct the coordinator provider only for a custom calculation."""
        if self.portfolio is None:
            self.stats['provider_constructions']+=1
            self.provider = attach_provider(self.inputs,limits=self.execution_policy.provider_limits)
            if self.provider.compiler != self.expected_compiler:
                raise ValueError('Coordinator provider differs from its expected compiler identity.')
            self.portfolio = NumericalPortfolio(self.inputs,self.provider,result_workspace_bytes=self.result_workspace_bytes)
        return self.portfolio

    def verify_provider(self):
        """Exercise the genuine selected provider without calculating a market book."""
        self._portfolio()
        profile=self.execution_policy.backend
        signatures=self.provider.stats.get('nopython_signatures',{})
        if not all(signatures.get(name) for name in ('reports','prices','factors','decisions','materialize')):
            raise ValueError('Compiled provider preparation is incomplete.')
        return dict(verified=True,profile=profile,rust_required=False,compiler=self.expected_compiler['signature'])

    def _binding(self,plan):
        execution=numerical_random.provider_execution(self.inputs,self.execution_policy.provider_limits,self.expected_compiler)
        execution['trial_pool']=self.execution_policy.execution_identity(self.expected_compiler)
        return numerical_random.checkpoint_binding(self.workspace,plan,execution=execution)

    def pool(self):
        """Lazily own persistent workers after complete checkpoint inspection."""
        self.validate()
        if self.trial_pool is None:
            from numerical_trial_pool import TrialPool
            self.trial_pool = TrialPool(source_root=self.configuration['source_root'],
                scratch=self.configuration['scratch']+'/trial-pool',
                reference=self.inputs.worker_reference(), source_identity=self.loaded_source,
                compiler_identity=self.expected_compiler, policy=self.execution_policy)
        return self.trial_pool

    def plan(self, options):
        # The private SQL workspace contains immutable sessions. Use the ordinary
        # planner, including its fresh default seed and exact envelope.
        configuration,selection,_=numerical_calendar.decode_request(options)
        selection.pop('trials',None);selection.pop('seed',None)
        self.workspace.validate_selection(selection)
        if 'calendar' in options:
            return numerical_calendar.plan(self.workspace._calendar().sessions,options,
                checkpoint=backtest_control.checkpoint)
        return robustness.plan(self.workspace.db,**deepcopy(options))

    def calculate(self, mode, options, progress, configuration, *, planned=None, capture=None):
        self.validate()  # Always before result/checkpoint lookup, even a full hit.
        if mode == 'random':
            plan = self.plan(options) if planned is None else numerical_random.validate_configuration(self.workspace,planned)
            if planned is not None:
                _validate_submitted(options, plan)
            count = min(len(self.inputs.symbols),plan['options'].get('rank_to',50)-plan['options'].get('rank_from',1)+1)
            estimate = sum(len(dates) for dates in plan['samples'])*(16384+4096*count)
            if estimate > self.result_workspace_bytes:
                raise ValueError('Random result exceeds the runtime result workspace bound.')
            configuration(deepcopy(plan))
            binding=self._binding(plan)
            experiment = self.checkpoints.open(binding)
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
            result = numerical_random.run(self.workspace,plan,experiment,progress,capture=observed,execution=self.pool,binding=binding)['result']
            result['trial_results'] = details
        elif mode == 'custom':
            self._portfolio()
            _, selection, _ = numerical_calendar.decode_request(options)
            selection.pop('dates', None)
            self.workspace.validate_selection(selection)
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
            plan=self.plan(options) if planned is None else numerical_random.validate_configuration(self.workspace,planned)
            if planned is not None:
                _validate_submitted(options, plan)
            configuration(deepcopy(plan))
        writer=result_evidence.Writer(stream,trials=plan['requested'] if plan else 1,
            metadata=dict(mode=mode,options=deepcopy(options),configuration=plan,
                          generation=self.inputs.signature,source=self.loaded_source),
            max_bytes=max_bytes,piece_bytes=piece_bytes,record_bytes=record_bytes,
            checkpoint=backtest_control.checkpoint)
        if plan is not None:
            binding=self._binding(plan)
            experiment=self.checkpoints.open(binding)
            numerical_random.run_into(self.workspace,plan,experiment,writer,progress,execution=self.pool,binding=binding)
        else:
            self._portfolio()
            writer.start_trial(1)
            result=self.portfolio.backtest_calendar_into(writer.period,**options)['result']
            writer.end_trial(result);writer.finish(result)
        backtest_control.checkpoint()

    def measurements(self):
        import numerical_preparation,numerical_matrix
        return dict(**self.stats,**process_metrics(),generation=self.inputs.signature,
            factor_kernel_compilation_requests=numerical_matrix.compilation_requests(),
            preparation_dependency_checks=numerical_preparation.measurements(),
            compiler_identity=deepcopy(self.expected_compiler),
            matrix=deepcopy(self.provider._calculate.stats) if self.provider is not None else {},
            provider=deepcopy(self.provider.stats) if self.provider is not None else dict(books=0,threads=self.execution_policy.provider_limits['threads']),checkpoints=self.checkpoints.measurements(),
            execution_policy=self.execution_policy.diagnostics(),
            trial_pool=self.trial_pool.measurements() if self.trial_pool is not None else None)

    def close(self):
        if self.closed: return
        if self.trial_pool is not None:
            self.trial_pool.close(); self.trial_pool = None
        if self.checkpoints is not None:
            self.checkpoints.close(); self.checkpoints = None
        self._close_attachment()
        self.closed = True
