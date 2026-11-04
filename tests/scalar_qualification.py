"""Private scenarios and complete semantic receipts for scalar qualification.

Only explicit backend/source identities, producer diagnostics, elapsed clocks
and chunk-local identifiers may differ. Context, operation and observation links
are resolved before comparison. No evaluation or unavailable candidate is dropped.
The application runner uses the ordinary pinned Selectable and Candidate lifetime.
"""
from collections import defaultdict
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

from backtest import result_evidence
from backtest.application import calculations, strategy_requests
from backtest.inputs import daily, research
from backtest.variables import definitions
from backtest.runtime.process_owner import process_metrics
from backtest.runtime import backtest_control
from numerical_scalar_fixture import Inputs
from prepared_inputs_fixture import history
from test_numerical_scalar_process import ScalarCandidateTests
import test_strategy_requests as intent
import test_variable_definitions as language

ROOT = Path(__file__).resolve().parents[1]
LIMITS = dict(max_bytes=256*1024**2, piece_bytes=1024*1024, record_bytes=8*1024**2)


def digest(value):
    return hashlib.sha256(definitions.canonical(value).encode()).hexdigest()


def program(*, shared=True):
    """Ordered exact revisions with shared temporal annual evidence."""
    base = language.entry(language.definition(dict(op='annual',stat='mean',count=3,
        parameter='annual.operating_income'),'USD','usd_million'),'qualification:annual')
    signal = language.entry(language.definition(language.binary('div',language.reference(base),
        dict(op='parameter',id='market.enterprise_value')),'scalar','percent'),'qualification:yield')
    if not shared:
        value = intent.intent(intent.formula(signal)); value['pool']='cached'
        return strategy_requests.capture_strategy(value,submitted=[base,signal])
    change = language.entry(language.definition(language.binary('sub',language.reference(signal),
        dict(op='lookback',months=12,arg=language.reference(signal))),'scalar','percentage_points'),'qualification:change')
    revenue = language.entry(language.definition(dict(op='parameter',id='annual.revenue'),'USD','usd_million'),'qualification:revenue')
    value = intent.intent(intent.formula(signal),[
        intent.condition(intent.formula(change),'-100','percentage_points'),
        intent.condition(intent.formula(revenue),'0','usd_million')],rank_to=20)
    value['pool']='cached'
    return strategy_requests.capture_strategy(value,submitted=[base,signal,change,revenue])


class Scenario(unittest.TestCase):
    candidate = ScalarCandidateTests.candidate

    def __init__(self, *, companies=1, first=2015, last=2015, capture=None, workers=1):
        super().__init__('runTest')
        began=time.perf_counter()
        self.fixture=Inputs(configure=history(companies,first,last));self.addCleanup(self.fixture.close)
        self.capture=capture or program()
        self.first,self.last,self.companies,self.workers=first,last,companies,workers
        self.context=ExitStack();self.addCleanup(self.context.close)
        self.context.enter_context(patch.object(research,'DATABASE',self.fixture.fixture.source))
        self.preparation_seconds=time.perf_counter()-began
        self.through=json.loads((research.RAW/'spy-div.json').read_bytes())[-1]['date']
        self.raw_manifest={path.relative_to(research.RAW).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(research.RAW.rglob('*')) if path.is_file()}
        self.input_sha256=digest(self.raw_manifest)
        self.owner,self.created=self.candidate()
        factory=self.owner.preparation._runtime.side_effect
        def runtime():
            value=factory()
            value.configuration['session_options']['execution']=dict(workers=workers,
                threads_per_worker=1,lane_budget=workers,
                **(dict(private_memory_budget_bytes=2*1024**3) if workers>1 else {}))
            return value
        self.owner.preparation._runtime.side_effect=runtime
        self.selectable=calculations.Selectable(self.owner.preparation)
        self.selectable.experimental=self.owner
        self.addCleanup(self.selectable.retire);self.addCleanup(self.selectable.close)

    def options(self, mode, **changes):
        value=dict(strategy=self.capture.to_dict())
        if mode=='january':value.update(first=self.first,last=self.last)
        elif mode in ('custom','random'):
            value.update(start=f'{self.first}-01-02',end=self.through,months=12)
            if mode=='random':value.update(trials=4,seed=42)
        value.update(changes)
        return value

    def run_backend(self, engine, mode, options, *, planned=None, progress=None, expected_cancel=False):
        output=io.BytesIO();plans=[]
        before=process_metrics();began=time.perf_counter()
        cancelled=False
        try:
            self.selectable.calculate_into(mode,dict(options,engine=engine),output,progress,plans.append,
                planned=planned,**LIMITS)
        except backtest_control.Cancelled:
            if not expected_cancel:raise
            cancelled=True
        seconds=time.perf_counter()-began
        self.assertEqual(cancelled,expected_cancel)
        if cancelled:
            with self.assertRaises(ValueError):result_evidence.open_reader(output,**LIMITS)
            reader=None
        else:
            reader=result_evidence.open_reader(output,**LIMITS)
            self.assertEqual(reader.metadata['producer']['engine'],engine)
        self.assertIsNone(self.owner.runtime)
        runtime=self.created[-1] if engine=='experimental' else None
        if runtime is not None:self.assertEqual(runtime.closure()['state'],'closed')
        receipt=dict(engine=engine,mode=mode,seconds=seconds,options=deepcopy(options),
            plan=plans[0] if plans else planned,bytes=len(output.getvalue()),
            sha256=hashlib.sha256(output.getvalue()).hexdigest(),manifest=deepcopy(reader.manifest) if reader else None,
            cancelled=cancelled,
            parent_before=before,parent_after=process_metrics(),
            runtime=deepcopy(runtime.last_stats) if runtime else None,
            closure=runtime.closure() if runtime else dict(financial_closed=True),
            compiler_reuse='within-call only; Candidate retires each child' if runtime else 'Original parent interpreter')
        return reader,receipt,output

    def cancel_at(self,stage):
        """Measure observed stop through complete retirement at a declared stage."""
        marker=self.fixture.root/('probe-'+stage+'.json')
        marker.unlink(missing_ok=True)
        factory=self.owner.preparation._runtime.side_effect
        def runtime():
            value=factory();value.configuration['session_options']['scalar_probe']=stage
            return value
        self.owner.preparation._runtime.side_effect=runtime
        requested=[]
        def cancel():
            if marker.exists():
                if not requested:requested.append(time.perf_counter())
                return True
            return False
        try:
            with backtest_control.cancel_when(cancel):
                _,receipt,_=self.run_backend('experimental','custom',self.options('custom'),
                    expected_cancel=True)
            finished=time.perf_counter()
            self.assertEqual(len(requested),1)
            receipt.update(cancellation_stage=stage,cancellation_seconds=finished-requested[0],
                probe=json.loads(marker.read_bytes()),
                stage_limit='compiler call itself has before/after checkpoints' if stage=='compile'
                    else 'deterministic hold after native work; measures observation-to-retirement, not uninterrupted throughput')
            return receipt
        finally:self.owner.preparation._runtime.side_effect=factory

    def __enter__(self):return self
    def __exit__(self,*unused):
        if not self.doCleanups():raise AssertionError('Private scenario cleanup failed.')


def canonical_block(block):
    """Resolve every root/context/task/observation identifier by semantic keys."""
    if set(block)!={'calculation_identity','format','identity','observations','operations',
            'plan_revision','program','requests','results','version'}:
        raise AssertionError('Unexpected evaluation block fields.')
    observed=block['observations'];roots={}
    if set(observed)!={'contexts','format','generation','projection','provider_policy','results','roots','version'}:
        raise AssertionError('Unexpected observation block fields.')
    for item in observed['roots']:
        scope = definitions.canonical(item['owner_scope']) if 'owner_scope' in item else None
        roots[item['root']]=(item['symbol'],item['pool'],item['mode'],item['date'],scope)
    context_counts=defaultdict(int);contexts={}
    for item in observed['contexts']:
        if set(item) not in ({'id','root','date'}, {'id','root','date','owner_scope'}):raise AssertionError('Unexpected temporal context fields.')
        root=roots[item['root']];ordinal=context_counts[root];context_counts[root]+=1
        contexts[item['id']]=(root,ordinal,item['date'])
    observation_counts=defaultdict(int);observations={}
    for item in observed['results']:
        context=contexts[item['context']];ordinal=observation_counts[context];observation_counts[context]+=1
        observations[item['id']]=(context,ordinal)
    tasks={item['id']:(contexts[item['context']],item['node']) for item in block['operations']}
    root_rows=[]
    for item in observed['roots']:
        row=deepcopy(item);row['root']=roots[item['root']];root_rows.append(row)
    context_rows=[]
    for item in observed['contexts']:
        row=deepcopy(item);row['id']=contexts[item['id']];row['root']=roots[item['root']]
        context_rows.append(row)
    observation_rows=[]
    for item in observed['results']:
        row=deepcopy(item);row['id']=observations[item['id']];row['context']=contexts[item['context']]
        row['root']=roots[item['root']];observation_rows.append(row)
    operations=[]
    for item in block['operations']:
        row=deepcopy(item);row['id']=tasks[item['id']];row['context']=contexts[item['context']]
        row['operands']=[tasks[key] for key in item['operands']]
        if 'observation' in item:row['observation']=observations[item['observation']]
        operations.append(row)
    results=[]
    for item in block['results']:
        row=deepcopy(item);row['request']=block['requests'][item['request']]
        row['root']=roots[item['root']]
        row['evidence']['admission']=roots[item['evidence']['admission']]
        row['evidence']['operation']=tasks[item['evidence']['operation']]
        results.append(row)
    # Only these documented identity paths differ between arithmetic backends
    # and SQLite versus immutable-generation observation adapters. Their common
    # provider/language/arithmetic/projection bindings still compare exactly.
    identity=block['identity'];policy=identity['policy']
    if set(identity)!={'bundle','generation','plan','policy','projection'}:
        raise AssertionError('Unexpected evaluation identity fields.')
    expected_policy={'backend','version','definitions','evaluation','provider','arithmetic'}
    if policy['backend']=='reference-formulas':expected_policy|={'reference'}
    elif policy['backend']=='numba-formulas':expected_policy|={'formulas','compiler_source','compiler','native','capabilities'}
    else:raise AssertionError('Unexpected arithmetic backend.')
    if set(policy)!=expected_policy:raise AssertionError('Unexpected arithmetic policy fields.')
    common_policy={key:policy[key] for key in ('version','definitions','evaluation','provider','arithmetic')}
    return dict(format=block['format'],version=block['version'],program=block['program'],
        bundle=identity['bundle'],projection=identity['projection'],policy=common_policy,
        requests=block['requests'],roots=root_rows,contexts=context_rows,
        observations=observation_rows,operations=operations,results=results,
        provider_policy=observed['provider_policy'],observation_version=observed['version'])


def compare_blocks(left, right):
    """Compare complete chunks without relying on backend chunk boundaries."""
    def collect(blocks):
        result=dict(program=None,roots=[],contexts=[],observations=[],operations=[],results=[],requests=[])
        common=None
        for block in blocks:
            value=canonical_block(block)
            constant={key:content for key,content in value.items() if key not in result or key=='program'}
            if common is None:common=constant
            elif constant!=common:raise AssertionError('A chunk changed shared program/policy/projection meaning.')
            result['program']=value['program']
            for key in ('roots','contexts','observations','operations','results','requests'):result[key].extend(value[key])
        return common,result
    if definitions.canonical(collect(left))!=definitions.canonical(collect(right)):raise AssertionError('Complete scalar evaluation meaning differs.')


def _summary(value):
    """Only explicit completed-summary diagnostics may differ by backend."""
    result=deepcopy(value)
    for key in ('seconds','producer','execution'):result.pop(key,None)
    if isinstance(result.get('trials'),list):
        for item in result['trials']:item.pop('seconds',None)
    return result


def artifact_meaning(reader):
    """Resolve local evidence links while retaining every semantic record."""
    records=list(reader.records())
    metadata=deepcopy(reader.metadata)
    expected={'mode','options','configuration','input','projection','producer'}
    if metadata['producer']['engine']=='experimental':expected|={'generation','source'}
    if set(metadata)!=expected:raise AssertionError('Unexpected scalar header fields: '+str(set(metadata)^expected))
    metadata['options'].pop('engine',None)
    for key in ('input','producer','generation','source'):metadata.pop(key,None)
    scopes={};current_trial=0;ordinal=0
    for record in records:
        if record['type']=='trial':current_trial=record['number'];ordinal=0
        if record['type']=='scope':
            value=record['value'];ordinal+=1
            scopes[value['id']]=(current_trial,ordinal,value['mode'],value['pool'],value['date'],value['exit'])
    blocks=defaultdict(list)
    for record in records:
        if record['type']=='evaluation':blocks[record['value']['scope']].append(record['value']['block'])
    links={}
    for scope,values in blocks.items():
        for chunk,block in enumerate(values):
            normalized=canonical_block(block)
            operations={item['id']:normalized['operations'][i]['id'] for i,item in enumerate(block['operations'])}
            roots={item['root']:normalized['roots'][i]['root'] for i,item in enumerate(block['observations']['roots'])}
            for request,root in enumerate(block['requests']):
                links[scope,chunk,request]=dict(request=root,operations=operations,roots=roots)
    def evidence(value):
        value=deepcopy(value);scope=value['scope'];value['scope']=scopes[scope]
        if 'chunk' in value:
            key=links[scope,value.pop('chunk'),value.pop('request')]
            value['request']=key['request']
            value['evidence']['admission']=key['roots'][value['evidence']['admission']]
            value['evidence']['operation']=key['operations'][value['evidence']['operation']]
        return value
    normalized=[];trial=0
    for record in records:
        kind=record['type'];row=deepcopy(record)
        if kind=='header':continue
        if kind=='trial':trial=row['number']
        if kind=='evaluation':continue
        if kind=='scope':
            value=row['value'];value['id']=scopes[value['id']]
            # These identify backend-local prepared rows and work reservations.
            # The full provider roots/values and selected rows compare below.
            for key in ('input','prepared_period','digest','work'):value.pop(key)
            normalized.append(row)
            values=blocks.get(record['value']['id'],[])
            collected={key:[] for key in ('requests','roots','contexts','observations','operations','results')};common=None
            for block in values:
                value=canonical_block(block)
                fixed={key:content for key,content in value.items() if key not in collected}
                if common is None:common=fixed
                elif common!=fixed:raise AssertionError('Changed complete chunk policy.')
                for key in collected:collected[key].extend(value[key])
            normalized.append(dict(type='complete_evaluations',scope=scopes[record['value']['id']],common=common,**collected))
            continue
        if kind in ('holding','screen'):
            value=row['value'];scope=value['scalar_evidence']['scope']
            value['scalar_evidence']=dict(scope=scopes[scope],lanes={key:evidence(item)
                for key,item in value['scalar_evidence']['lanes'].items()})
            if reader.metadata['mode'] in ('custom','random') and 'year' in value:value['year']=scopes[scope]
        elif kind=='lanes':
            row['value']['scope']=scopes[row['value']['scope']]
            row['value']['lanes']=[evidence(item) for item in record['value']['lanes']]
        elif kind=='selection':row['value']['scope']=scopes[row['value']['scope']]
        elif kind=='admission':
            row['value']['scope']=scopes[row['value']['scope']]
        elif kind=='end_trial':row['summary']=_summary(row['summary'])
        elif kind=='complete':
            row['summary']=_summary(row['summary']);row.pop('sha256');row.pop('records')
        normalized.append(row)
    return dict(metadata=metadata,records=normalized)


def compare_artifacts(left,right):
    """Whole meanings must agree; each backend's framed bytes remain its own."""
    a,b=artifact_meaning(left),artifact_meaning(right)
    if definitions.canonical(a)!=definitions.canonical(b):
        if definitions.canonical(a['metadata'])!=definitions.canonical(b['metadata']):raise AssertionError('Complete artifact metadata differs.')
        for number,(x,y) in enumerate(zip(a['records'],b['records'])):
            if definitions.canonical(x)!=definitions.canonical(y):raise AssertionError('Complete artifact record '+str(number)+' differs: '+str(x.get('type')))
        raise AssertionError('Complete artifact record count differs.')
    return dict(trials=left.manifest['trials'],periods=left.manifest['periods'],
        holdings=left.manifest['holdings'],semantic_sha256=digest(a),
        evaluations=sum(record['type']=='evaluation' for record in left.records()),
        operations=sum(len(record['value']['block']['operations']) for record in left.records() if record['type']=='evaluation'))


def receipt_environment():
    """Exact product/test hashes, without invoking Git under the native guard."""
    if sys.platform=='win32':
        manifest=json.loads((ROOT.parent/'control/wsl-product-test-manifest.json').read_bytes())
    else:
        names=set()
        for arguments in (['git','ls-files','-z'],['git','ls-files','--others','--exclude-standard','-z']):
            names.update(subprocess.check_output(arguments,cwd=ROOT).decode().split('\0'))
        manifest={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sorted(names-{''})
            if not name.startswith(('raw/','data/','website/dist/','tmp/')) and
            (name.startswith(('backtest/','scripts/','tests/','tools/','website/')) or name=='requirements-numerical.txt') and (ROOT/name).is_file()}
    from importlib.metadata import version
    return dict(platform=sys.platform,python=sys.version,interpreter=sys.executable,
        dependencies={name:version(name) for name in ('numpy','numba','llvmlite')},
        product_test_files=len(manifest),product_test_sha256=digest(manifest),
        native_variances=['guarded-c/runpy entry translation','private discarded-output sink instead of Windows NUL'] if sys.platform=='win32' else [],
        native_cache_coverage='unknown')
