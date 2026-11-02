"""Private real preparation/attachment fixture for numerical scalar qualification."""
from contextlib import ExitStack
from pathlib import Path
import json
from unittest.mock import patch

from backtest.inputs import daily, research, financial_inputs
from backtest.runtime import cache_access
from backtest.engines.numerical import generation
import test_observation_inputs


class Inputs:
    def __init__(self):
        self.context=ExitStack()
        self.fixture=test_observation_inputs.ProjectionTests('test_real_preparation_through_immutable_generation_and_pending_guard')
        try:
            self.fixture.setUp()
            self.context.callback(self.fixture.doCleanups)
            self.root=self.fixture.source.parent.parent
            research.signature.return_value['historical_through']='2015-10-20'
            raw=research.RAW
            (raw/'spy-div.json').write_text(json.dumps([dict(date=day,adjClose=value) for day,value in [
                ('2015-01-02',100),('2015-04-02',103),('2015-07-02',108),('2015-10-20',110)]]))
            path=raw/'px/TEST.json';payload=json.loads(path.read_text())
            payload['div'].extend([dict(date='2015-04-02',adjClose=21),dict(date='2015-07-02',adjClose=19)])
            path.write_text(json.dumps(payload))
            financial_inputs.publish(raw,'TEST','income-statement',[
                dict(date=f'{year}-06-30',reportedCurrency='USD',revenue=100e6,operatingIncome=value)
                for year,value in ((2012,10e6),(2013,-5e6),(2014,20e6))],{},raw/'coverage.json')
            self.fixture.prepare()
            self.owner=cache_access.WorkspaceAccess(self.root/'scalar-fixture.lock')
            ordinary_daily,ordinary_research=daily.connect,research.connect
            self.context.enter_context(patch.object(cache_access,'workspace',self.owner))
            self.context.enter_context(patch.object(daily,'connect',side_effect=lambda:ordinary_daily(self.fixture.path,self.fixture.source)))
            self.context.enter_context(patch.object(research,'connect',side_effect=lambda path=self.fixture.source,**kw:ordinary_research(path,**kw)))
            self.store=generation.GenerationStore(self.root/'scalar-numerical',self.owner)
            self.receipt=self.store.prepare()
        except BaseException:
            self.close();raise

    def close(self):self.context.close()
    def __enter__(self):return self
    def __exit__(self,*unused):self.close()


class WireSession(__import__('backtest.engines.numerical.session',fromlist=['Session']).Session):
    """Actual child protocol with explicitly supplied private synthetic inputs."""
    def __init__(self,configuration):
        from backtest.engines.numerical import session
        from numerical_runtime_fixture import FixtureStore
        self.fixture_context=ExitStack()
        self.fixture_fault=configuration.get('scalar_fault')
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
        except BaseException as error:
            if not getattr(error,'numerical_session',None):self.fixture_context.close()
            raise

    def close(self):
        super().close()
        self.fixture_context.close()

    def calculate_into(self,*args,**kwargs):
        if self.fixture_fault=='formula':
            from backtest.variables.definitions import FormulaError
            raise FormulaError(errors=[dict(code='WORK_LIMIT',path='/fixture/expression',
                message='The private scalar task exceeded its declared work.')])
        return super().calculate_into(*args,**kwargs)
