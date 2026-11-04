"""Private real preparation/attachment fixture for numerical scalar qualification."""
from contextlib import ExitStack
from pathlib import Path
import json
from unittest.mock import patch

from backtest.inputs import daily, research, financial_inputs
from backtest.engines.numerical import generation
from prepared_inputs_fixture import PreparedInputs


class Inputs(PreparedInputs):
    """PreparedInputs plus one published numerical generation in `store`."""
    def __init__(self, *, configure=None):
        def configured(inputs):
            raw=research.RAW
            (raw/'spy-div.json').write_text(json.dumps([dict(date=day,adjClose=value) for day,value in [
                ('2015-01-02',100),('2015-04-02',103),('2015-07-02',108),('2015-10-20',110)]]))
            path=raw/'px/TEST.json';payload=json.loads(path.read_text())
            payload['div'].extend([dict(date='2015-04-02',adjClose=21),dict(date='2015-07-02',adjClose=19)])
            path.write_text(json.dumps(payload))
            financial_inputs.publish(raw,'TEST','income-statement',[
                dict(date=f'{year}-06-30',reportedCurrency='USD',revenue=100e6,operatingIncome=value)
                for year,value in ((2012,10e6),(2013,-5e6),(2014,20e6))],{},raw/'coverage.json')
            if configure is not None:configure(inputs)
        super().__init__(configure=configured)
        try:
            self.store=generation.GenerationStore(self.root/'scalar-numerical',self.owner)
            self.receipt=self.store.prepare()
        except BaseException:
            self.close();raise


class WireSession(__import__('backtest.engines.numerical.session',fromlist=['Session']).Session):
    """Actual child protocol with explicitly supplied private synthetic inputs."""
    def __init__(self,configuration):
        from backtest.engines.numerical import session
        from numerical_runtime_fixture import FixtureStore
        self.fixture_context=ExitStack()
        self.fixture_fault=configuration.get('scalar_fault')
        self.fixture_probe=configuration.get('scalar_probe')
        self.probe_state={}
        private=Path(configuration['scalar_fixture']).resolve()
        source=Path(configuration['source_root']).resolve()
        if private==source or source in private.parents:raise ValueError('Use an external private input fixture.')
        marker=json.loads((private/'scalar-fixture.json').read_bytes())
        if marker.get('kind')!='synthetic-scalar-fixture':raise ValueError('Unknown private scalar fixture.')
        binding=json.loads((private/'binding.json').read_bytes())
        path=private/'data/research.sqlite';daily_path=private/'data/daily.sqlite'
        original_research,original_daily=research.connect,daily.connect
        self.fixture_context.enter_context(patch.object(research,'ROOT',private))
        self.fixture_context.enter_context(patch.object(research,'RAW',private/'raw'))
        self.fixture_context.enter_context(patch.object(research,'RESULTS',private/'results'))
        self.fixture_context.enter_context(patch.object(research,'signature',return_value=binding['daily']['inputs']))
        self.fixture_context.enter_context(patch.object(research,'price_sources',return_value=binding['prices']))
        self.fixture_context.enter_context(patch.object(research,'connect',side_effect=lambda location=path,**kw:original_research(location,**kw)))
        self.fixture_context.enter_context(patch.object(daily,'connect',side_effect=lambda:original_daily(daily_path,path)))
        try:
            with patch.object(session,'GenerationStore',FixtureStore):super().__init__(configuration)
            if self.fixture_probe is not None:self._install_probe(private)
        except BaseException as error:
            if not getattr(error,'numerical_session',None):self.fixture_context.close()
            raise

    def _install_probe(self,private):
        """Deterministic test-only cancellation stages; no production bypass."""
        import os,time
        from backtest.runtime import backtest_control
        from backtest.inputs.cache_assets import write_json
        from backtest.engines.numerical import formulas
        from backtest import scalar_result_evidence
        if self.fixture_probe not in ('compile','formula','evidence'):
            raise ValueError('Unknown private scalar cancellation stage.')
        def mark(stage):
            self.probe_state.update(stage=stage,pid=os.getpid(),marked_at=time.perf_counter())
            write_json(private/('probe-'+stage+'.json'),self.probe_state)
        def hold(stage):
            mark(stage)
            while True:
                backtest_control.checkpoint();time.sleep(.002)
        if self.fixture_probe=='compile':
            ordinary=formulas.njit
            def observed(*args,**kwargs):
                decorate=ordinary(*args,**kwargs)
                def compile(function):
                    kernel=decorate(function)
                    state=self.probe_state
                    class ObservedKernel:
                        def __getattr__(self,name):return getattr(kernel,name)
                        def __call__(self,*values):
                            mark('compile')
                            result=kernel(*values)
                            state['kernel_returned']=True
                            write_json(private/'probe-compile.json',state)
                            return result
                    return ObservedKernel()
                return compile
            self.fixture_context.enter_context(patch.object(formulas,'njit',observed))
        elif self.fixture_probe=='formula':
            ordinary=formulas._Execution.operations
            def observed(execution,*args,**kwargs):
                for result in ordinary(execution,*args,**kwargs):
                    self.probe_state['native_chunks']=execution.owner.stats['native_chunks']
                    hold('formula')
                    yield result
            self.fixture_context.enter_context(patch.object(formulas._Execution,'operations',observed))
        else:
            ordinary=scalar_result_evidence.Writer.evidence
            def observed(writer,record):
                result=ordinary(writer,record)
                if record['type']=='evaluation':hold('evidence')
                return result
            self.fixture_context.enter_context(patch.object(scalar_result_evidence.Writer,'evidence',observed))

    def close(self):
        super().close()
        self.fixture_context.close()

    def calculate_into(self,*args,**kwargs):
        if self.fixture_fault=='formula':
            from backtest.variables.definitions import FormulaError
            raise FormulaError(errors=[dict(code='WORK_LIMIT',path='/fixture/expression',
                message='The private scalar task exceeded its declared work.')])
        return super().calculate_into(*args,**kwargs)
