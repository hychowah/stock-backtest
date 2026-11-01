"""Scoped CB-19 copied-input comparison; historical benchmark admission stays shut.

Run with the target platform's numerical Python. A declaration names a fresh
private destination, immutable completed capture and exact source contents.
Only this tool's fixed child may prepare or calculate in the private export.
No live source/cache discovery, download, deployment or host-cache flush exists.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
from collections import deque

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = '920453aba4fe10efb9dc6b81e189bf50ed711d6eb9d71e8b199a0610510cf819'
FOLDERS = ('scripts', 'website', 'tools', 'tests')
SUFFIXES = {'.py', '.js', '.cjs', '.mjs', '.html', '.css', '.json', '.txt', '.csv', '.rs', '.cmd'}
EXCLUDED = {'local', 'dist', '__pycache__', 'node_modules'}
SCHEMA = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024*1024), b''): value.update(part)
    return value.hexdigest()


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix+'.pending')
    pending.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    pending.replace(path)


def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))


def sources(root):
    root = Path(root)
    files = []
    for folder in FOLDERS:
        files.extend(path for path in (root/folder).rglob('*') if path.is_file()
                     and path.suffix in SUFFIXES and not EXCLUDED.intersection(path.relative_to(root).parts))
    files.extend(root/name for name in ('requirements.txt', 'requirements-numerical.txt', 'start.cmd', 'backtest-web.cmd')
                 if (root/name).is_file())
    return {path.relative_to(root).as_posix(): file_hash(path) for path in sorted(files)}


def assert_sources(root, expected):
    if sources(root) != expected: raise ValueError('Declared source contents changed.')


def validate_declaration(value):
    value = deepcopy(value)
    required = {'version', 'base_commit', 'source_root', 'source_sha256', 'capture',
                'capture_manifest_sha256', 'destination', 'copy_max_bytes', 'storage_max_bytes',
                'request', 'cleanup_owner', 'scope'}
    if set(value) != required or value['version'] != SCHEMA: raise ValueError('Invalid comparison declaration.')
    if value['capture_manifest_sha256'] != CAPTURE: raise ValueError('Undeclared completed capture.')
    if not value['source_sha256'] or not value['base_commit'] or not value['cleanup_owner']:
        raise ValueError('Missing comparison binding.')
    for key in ('copy_max_bytes', 'storage_max_bytes'):
        if type(value[key]) is not int or value[key] <= 0: raise ValueError('Invalid storage allowance.')
    if value['storage_max_bytes'] <= value['copy_max_bytes']: raise ValueError('No prepared storage allowance.')
    origin, destination, capture = (Path(value[k]).absolute() for k in ('source_root','destination','capture'))
    if any(a == b or a in b.parents or b in a.parents for a,b in ((origin,destination),(capture,destination))):
        raise ValueError('Private destination overlaps protected source/capture.')
    if not isinstance(value['request'],dict) or value['request'].get('trials',0) < 1:
        raise ValueError('Choose a concrete random workload.')
    return value


def observe(root):
    sys.path.insert(0, str(ROOT/'scripts'))
    from numerical_execution import observe_resources
    result = observe_resources()
    result['disk'] = dict(zip(('total_bytes','used_bytes','free_bytes'), shutil.disk_usage(root)))
    result['platform'] = sys.platform; result['python'] = sys.version; result['interpreter'] = sys.executable
    return result


def storage(root):
    groups = {}
    for path in Path(root).rglob('*'):
        if path.is_file():
            group = path.relative_to(root).parts[0]
            groups[group] = groups.get(group,0)+path.stat().st_size
    return dict(logical_bytes=sum(groups.values()), groups=groups)


class Samples:
    """Bound observer memory; keep a tail and aggregate every sampled peak."""
    def __init__(self, maximum=256, max_bytes=4*1024**2):
        self.maximum=maximum;self.max_bytes=max_bytes;self.rows=deque();self.bytes=0;self.total=0;self.dropped=0
        self.peaks={}

    def add(self, row):
        self.total+=1
        processes=row.get('processes',{})
        totals=dict(processes=len(processes),threads=sum(p.get('threads',0) for p in processes.values()),
            working_set_bytes=sum(p.get('working_set',p.get('working_set_bytes',0)) for p in processes.values()),
            private_bytes=sum(p.get('private_bytes',0) for p in processes.values()),
            provisional_artifact_bytes=row.get('provisional_artifact_bytes',0),
            runtime_scratch_bytes=row.get('runtime_scratch_bytes',0),
            current_checkpoint_bytes=row.get('current_checkpoint_bytes',0))
        for name,value in totals.items():self.peaks[name]=max(value,self.peaks.get(name,0))
        size=len(json.dumps(row,separators=(',',':')).encode())
        if size>self.max_bytes:self.dropped+=1;return
        while self.rows and (len(self.rows)>=self.maximum or self.bytes+size>self.max_bytes):
            old,old_size=self.rows.popleft();self.bytes-=old_size;self.dropped+=1
        self.rows.append((row,size));self.bytes+=size

    def evidence(self):
        return dict(samples=[row for row,unused in self.rows],total_samples=self.total,dropped_samples=self.dropped,
            retained_bytes=self.bytes,max_samples=self.maximum,max_bytes=self.max_bytes,sampled_peaks=self.peaks,
            limitation='Half-second samples can miss short peaks; summed working sets include shared mappings.')


def sampled_storage(scratch_roots, checkpoint):
    files=[path for root in scratch_roots for path in Path(root).rglob('*') if path.is_file()]
    return dict(runtime_scratch_bytes=sum(path.stat().st_size for path in files),
        provisional_artifact_bytes=sum(path.stat().st_size for path in files
            if path.parent.name=='trial-pool' and path.name.startswith('slot-') and path.suffix=='.evidence'),
        current_checkpoint_bytes=sum(path.stat().st_size for path in Path(checkpoint).parent.glob(Path(checkpoint).name+'*')
            if path.is_file()))


def close_observation(adapter,runtime,runtimes,stop,watcher,record):
    """Retain cleanup evidence even when an owner reports uncertain closure."""
    errors=[];began=time.perf_counter()
    try:
        if adapter is not None:
            try:
                if hasattr(adapter,'retire'):adapter.retire()
            except BaseException as error:errors.append(error)
            try:adapter.close()
            except BaseException as error:errors.append(error)
        if runtime is not None:
            try:runtime.close()
            except BaseException as error:errors.append(error)
    finally:
        record['final_close_seconds']=time.perf_counter()-began
        record['cleanup_error_types']=[type(error).__name__ for error in errors]
        stop.set();watcher.join()
        record['sampler_stopped']=not watcher.is_alive()
        observations=[]
        for value in runtimes:
            row=dict(stats=deepcopy(value.last_stats),clocks=deepcopy(value.clocks),diagnostics=deepcopy(value.diagnostics))
            try:row['closure']=value.closure()
            except BaseException as error:row['closure']=dict(confirmed=False,error_type=type(error).__name__)
            observations.append(row)
        record['runtime_observations']=observations
    if errors:raise errors[0]


def launch(workspace, operation, payload, label):
    """One fixed child; stdout goes to a task-owned log, never a provider URL."""
    root = Path(workspace); evidence = root/'comparison'
    request = evidence/(label+'.request.json'); response = evidence/(label+'.json')
    if request.exists() or response.exists(): raise ValueError('Comparison label already used; retain its evidence.')
    cancel=evidence/(label+'.cancel')
    write(request,dict(operation=operation, payload=payload, response=str(response),cancel=str(cancel)))
    command=[sys.executable,'-I','-B',str(root/'tools'/'parallel_comparison_child.py'),str(request)]
    began=time.perf_counter()
    with (evidence/(label+'.log')).open('xb') as output:
        process=subprocess.Popen(command,stdout=output,stderr=subprocess.STDOUT)
        try: code=process.wait()
        except BaseException:
            # Request cooperative stop and keep the child owner until cleanup.
            # A cancelled attempt never becomes a successful latency sample.
            cancel.write_text('cancel',encoding='ascii')
            process.wait()
            raise
    result=read(response) if response.exists() else dict(status='failed',error_type='MissingChildReceipt')
    result.update(child_exit=code,child_elapsed_seconds=time.perf_counter()-began,command=command)
    write(response,result)
    if code or result.get('status')!='complete': raise RuntimeError('Comparison child failed; retained '+str(response))
    return result


def prepare(declaration):
    declaration=validate_declaration(declaration)
    source=Path(declaration['source_root']); destination=Path(declaration['destination'])
    assert_sources(source,declaration['source_sha256'])
    if destination.exists(): raise ValueError('Comparison preparation needs a fresh task-owned destination.')
    parent=destination.parent;parent.mkdir(parents=True,exist_ok=True)
    before=observe(parent)
    if before['disk']['free_bytes'] < declaration['storage_max_bytes']:
        raise ValueError('Declared preparation allowance exceeds observed free disk.')
    sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'scripts'),str(ROOT/'website')]
    from offline_input_copy import materialize_inputs
    attempt=destination.with_name(destination.name+'.comparison-attempt.json')
    if attempt.exists():raise ValueError('Preparation attempt already exists; retain its evidence.')
    attempt_record=dict(status='started',declaration=declaration,resources=before,started_at=time.time())
    write(attempt,attempt_record)
    began=time.perf_counter()
    try:
        copied=materialize_inputs(declaration['capture'],destination,
            expected_manifest_sha256=declaration['capture_manifest_sha256'],max_bytes=declaration['copy_max_bytes'])
        attempt_record.update(status=copied.get('status'),copier_outcome=copied)
    except BaseException as error:
        attempt_record.update(status='failed',error_type=type(error).__name__);raise
    finally:
        materialize_seconds=time.perf_counter()-began
        attempt_record['materialization_seconds']=materialize_seconds;write(attempt,attempt_record)
    if copied.get('status')!='materialized': raise ValueError('Private materialization failed; receipt retained by copier.')
    evidence=destination/'comparison'; evidence.mkdir()
    write(evidence/'declaration.json',declaration)
    write(evidence/'materialization.json',dict(receipt=copied,seconds=materialize_seconds,resources=before))
    for name, expected in declaration['source_sha256'].items():
        target=destination/name; target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists(): raise ValueError('Source export overlaps captured financial input.')
        shutil.copy2(source/name,target)
        if file_hash(target)!=expected: raise ValueError('Source export content differs.')
    assert_sources(source,declaration['source_sha256']); assert_sources(destination,declaration['source_sha256'])
    result=launch(destination,'prepare',{},'preparation')
    after=storage(destination)
    if after['logical_bytes']>declaration['storage_max_bytes']: raise ValueError('Prepared storage exceeds declaration.')
    write(evidence/'workspace.json',dict(version=SCHEMA,declaration_sha256=digest(declaration),
        materialization=copied,preparation=result,storage=after,resources=observe(destination)))
    return read(evidence/'workspace.json')


def validate_workspace(root):
    root=Path(root); declaration=validate_declaration(read(root/'comparison/declaration.json'))
    if root.absolute()!=Path(declaration['destination']).absolute(): raise ValueError('Workspace path differs.')
    receipt=read(root/'comparison/workspace.json')
    if receipt['declaration_sha256']!=digest(declaration): raise ValueError('Workspace declaration differs.')
    assert_sources(root,declaration['source_sha256'])
    return declaration,receipt


def validate_case(case):
    case=deepcopy(case)
    required={'label','backend','workers','threads','state','checkpoint','repeat_of','purpose'}
    if set(case)-{'request'}!=required:
        raise ValueError('Invalid comparison case.')
    if 'request' in case and (not isinstance(case['request'],dict) or not case['request']):
        raise ValueError('A scoped workload override must be an explicit request.')
    if case['backend'] not in ('original','numba','numba_compiled','rust'):
        raise ValueError('Unknown comparison backend.')
    if case['state'] not in ('fresh_application','initialized_fresh','full_recovery','original_reuse'):
        raise ValueError('Unknown starting state.')
    for name in ('label','checkpoint'):
        if not isinstance(case[name],str) or not case[name] or not all(c.isalnum() or c in '-_' for c in case[name]):
            raise ValueError('Comparison path token is invalid.')
    for name in ('workers','threads'):
        if type(case[name]) is not int or case[name]<1: raise ValueError('Invalid comparison layout.')
    if case['backend']=='original' and case['state'] not in ('fresh_application','original_reuse'):
        raise ValueError('Original does not use experimental trial checkpoints.')
    if case['backend']!='original' and case['state']=='original_reuse': raise ValueError('Invalid reuse classification.')
    if case['state']=='full_recovery' and not case['repeat_of']: raise ValueError('Recovery requires a completed matching case.')
    return case


def run_case(workspace, case):
    declaration,receipt=validate_workspace(workspace); case=validate_case(case)
    observation=launch(workspace,'case',dict(case=case,prepared=receipt['preparation']['binding']),case['label'])
    assert_sources(workspace,declaration['source_sha256'])
    return observation


def financial_payload(value):
    """Remove explicit timing/execution telemetry only; preserve every stock field."""
    if isinstance(value,dict):
        return {key:financial_payload(item) for key,item in value.items() if key not in ('seconds','execution')}
    if isinstance(value,list):return [financial_payload(item) for item in value]
    return value


def compare(observations):
    if not observations or any(row.get('status')!='complete' for row in observations):
        raise ValueError('Only completed observations can support comparison.')
    # Reuse the current complete financial validator, without entering any
    # historical benchmark bootstrap/admission route.
    sys.path.insert(0,str(ROOT/'scripts'))
    from numerical_portfolio import compare_results
    first=observations[0]; evidence=financial_payload(read(first['result_path']))
    bindings={digest(row['binding']) for row in observations}
    if len(bindings)!=1: raise ValueError('Comparison financial/source binding differs.')
    agreement=[]
    for row in observations:
        path=Path(row['result_path'])
        if file_hash(path)!=row['result_sha256']: raise ValueError('Completed result evidence changed.')
        verdict=compare_results(evidence,financial_payload(read(path)))
        if not verdict['exact']: raise ValueError('Complete financial disagreement: '+json.dumps(verdict))
        agreement.append(dict(label=row['case']['label'],**verdict))
    groups={}
    for row in observations:
        c=row['case']; key=':'.join((c['backend'],str(c['workers'])+'x'+str(c['threads']),c['state']))
        groups.setdefault(key,[]).append(row['elapsed_seconds'])
    return dict(binding=first['binding'],agreement=agreement,timings={key:dict(raw_seconds=values,
        median_seconds=statistics.median(values),minimum_seconds=min(values),maximum_seconds=max(values))
        for key,values in groups.items()},scope='Whole request through complete holdings and confirmed closure; no host cache flush.')


def decide(comparison, *, backend, workers, threads, rationale, limitations, g_handoff):
    if backend not in ('numba','numba_compiled','rust') or not rationale or not g_handoff:
        raise ValueError('Decision requires a supported backend and explicit reasoning/handoff.')
    key=backend+':'+str(workers)+'x'+str(threads)+':fresh_application'
    if key not in comparison['timings'] or len(comparison['timings'][key]['raw_seconds'])<2:
        raise ValueError('Selected complete-request layout lacks comparable repetitions.')
    if not comparison['agreement'] or not all(row['exact'] for row in comparison['agreement']):
        raise ValueError('Decision lacks complete financial agreement.')
    return dict(selected=dict(backend=backend,workers=workers,threads=threads),rationale=rationale,
        limitations=limitations,g_handoff=g_handoff,comparison_sha256=digest(comparison),original_remains_default=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='operation',required=True)
    p=sub.add_parser('prepare');p.add_argument('declaration')
    p=sub.add_parser('run');p.add_argument('workspace');p.add_argument('case')
    p=sub.add_parser('compare');p.add_argument('workspace');p.add_argument('labels',nargs='+')
    args=parser.parse_args()
    if args.operation=='prepare':result=prepare(read(args.declaration))
    elif args.operation=='run':result=run_case(args.workspace,read(args.case))
    else:
        rows=[read(Path(args.workspace)/'comparison'/(label+'.json')) for label in args.labels]
        result=compare(rows);write(Path(args.workspace)/'comparison/comparison.json',result)
    print(json.dumps(result,allow_nan=False),flush=True)


if __name__=='__main__':main()
