"""Candidate-owned scalar scopes over genuine numerical complete books.

The session or worker owns inputs and financial/source lifetime. This owner closes
its borrowed observation view, formula evaluator and private numerical workspace
before that attachment. Calendar and return meaning stay with shared owners.
"""
from copy import deepcopy
from datetime import date
import time

from backtest import calendar_requests, portfolio_results
from backtest.application import scalar_execution, scalar_runs, strategy_requests
from backtest.engines.numerical import checkpoints, formulas
from backtest.engines.numerical.numba import NumbaExecutor
from backtest.engines.numerical.portfolio import NumericalPortfolio, validate_book
from backtest.engines.numerical.workspace import stage_book
from backtest.runtime import backtest_control
from backtest.variables import evaluation

PRODUCER=dict(engine='experimental',label='New engine — experimental')


def resources(provider_limits):
    """Split the existing per-provider workspace; allocate no larger total.

    Half remains numerical-book workspace. One quarter pays formula buffers and
    tapes; the remaining quarter pays scalar selection metadata. Matrix cache
    keeps its separately declared allowance. These are managed estimates, not RSS.
    """
    book=deepcopy(provider_limits)
    workspace=book.get('workspace_bytes',64*1024**2)
    if type(workspace) is not int or workspace<4:raise ValueError('Scalar workspace is unavailable.')
    book['workspace_bytes']=workspace//2
    formula=min(evaluation.CEILINGS['retained_bytes'],workspace//4)
    metadata=min(scalar_execution.MAX_METADATA_BYTES,workspace//4)
    return dict(book=book,formula=formula,metadata=metadata,
        formula_cache=min(4*1024**2,formula//4))


class Resources:
    """One worker/session's bounded compiler and optional complete-book provider."""
    def __init__(self,inputs,provider_limits,*,checkpoint=backtest_control.checkpoint,warm=False):
        self.inputs,self.checkpoint=inputs,checkpoint
        self.limits=resources(provider_limits)
        self.provider=self.portfolio=self.view=self.evaluator=None
        try:
            self.evaluator=formulas.Evaluator(cache_bytes=self.limits['formula_cache'])
            if warm:self.evaluator.warm(checkpoint)
            self.view=inputs.observations()
        except BaseException:
            self.close();raise

    def books(self):
        if self.provider is None:
            self.provider=NumbaExecutor.__new__(NumbaExecutor)
            NumbaExecutor.__init__(self.provider,self.inputs,limits=self.limits['book'])
            self.portfolio=NumericalPortfolio.__new__(NumericalPortfolio)
            NumericalPortfolio.__init__(self.portfolio,self.inputs,self.provider)
        return self.portfolio

    def executor(self,capture,writer,*,number=1,trials=1):
        return scalar_execution.Executor(capture,self.view,writer.evidence,
            record_bytes=writer.record_bytes,checkpoint=self.checkpoint,
            evaluate=self.evaluator.evaluate,scope_prefix='trial:'+str(number)+':',
            evaluation_limits=dict(retained_bytes=self.limits['formula']),aggregate_trials=trials,
            metadata_bytes=self.limits['metadata'])

    def evaluate_periods(self,options,writer,*,number=1,trials=1):
        """Produce a complete scalar trial without owning its outer seal."""
        capture=strategy_requests.from_wire(options['strategy'])
        executor=self.executor(capture,writer,number=number,trials=trials)
        portfolio=self.books()
        pairs,first,selection,metadata=calendar_requests.periods(portfolio._calendar().sessions,
            options,checkpoint=self.checkpoint)
        checked=capture.to_dict()
        fields=[item['storage']['field'] for item in checked['builtins'] if item['storage']['kind']=='filter']
        self.provider.begin(dict(options={}),required_fields=fields)
        def select(entry,exit_day):
            self.checkpoint()
            requested=(str(entry),str(exit_day),checked['pool'])
            response=self.provider.evaluate([requested])
            if type(response) is not list or len(response)!=1:raise ValueError('Numerical book count differs.')
            book=response[0];validate_book(book,requested,self.provider.limits)
            period=stage_book(portfolio.db,book,checked['pool'])
            rows=executor.select(portfolio.db,period,entry,exit_day)
            portfolio.db.commit()
            return dict(entry=str(entry),exit=str(exit_day),spy=book['period'][2],holdings=rows)
        return scalar_runs.reduce_periods(pairs,select,writer.period,selection,metadata,
            common_start=first,checkpoint=self.checkpoint)

    def prepared(self,mode,options,writer):
        capture=strategy_requests.from_wire(options['strategy'])
        executor=self.executor(capture,writer)
        with self.inputs.prepared_scopes() as source:
            summary=scalar_runs.prepared(executor,source.db,mode,options,writer,self.view,
                producer=PRODUCER,checkpoint=self.checkpoint)
            source.validate();self.view.validate()
        return summary

    def measurements(self):
        return dict(formula=dict(self.evaluator.stats) if self.evaluator is not None else {},
            scalar_resources=deepcopy(self.limits),provider_constructions=int(self.provider is not None),
            provider=dict(self.provider.stats) if self.provider is not None else {})

    def close(self):
        # Drop formula/observation borrowers before provider workspace and inputs.
        for name in ('evaluator','view','portfolio','provider'):
            value=getattr(self,name,None)
            if value is not None:value.close();setattr(self,name,None)

    def __enter__(self):return self
    def __exit__(self,*unused):self.close()


class TrialEvaluator:
    """A typed recorded scalar trial; no sampling, checkpoint or user-store I/O."""
    def __init__(self,resources,*,calculation_identity):
        self.resources,self.identity=resources,calculation_identity

    def produce(self,spec,stream,*,limits):
        from backtest import scalar_result_evidence
        from backtest.engines.numerical import trial
        value=trial._specification(spec);limits=trial._limits(limits)
        if value['version']!=2 or value['calculation_identity']!=self.identity:
            raise ValueError('Scalar task differs from its recorded binding.')
        writer=scalar_result_evidence.SingleTrialWriter(stream,number=value['number'],
            metadata=dict(mode='random',options=value['options'],specification=value['sha256']),
            checkpoint=self.resources.checkpoint,**limits)
        try:
            summary=self.resources.evaluate_periods(dict(**value['request'],**value['options']),writer,
                number=value['number'],trials=value['requested'])
            trial._summary(summary,value)
            view=writer.finish(summary)
            return dict(version=2,number=value['number'],calculation_identity=self.identity,
                specification=value['sha256'],start=view.start,end=view.end,sha256=view.sha256,limits=limits)
        except BaseException:
            writer.failed=True;raise
