"""Fixed private comparison entry; source ownership precedes financial imports."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from threading import Event, Thread

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'website'))
import runtime_access


def main(request_path):
    # Only trusted task-owned JSON, never an import/factory supplied by a case.
    request=json.loads(Path(request_path).read_text(encoding='utf-8'))
    response=Path(request['response']);cancel=Path(request['cancel'])
    if response.parent!=ROOT/'comparison': raise ValueError('Comparison response is outside owned evidence.')
    if cancel.parent!=response.parent or cancel.stem!=response.stem:raise ValueError('Invalid cancellation marker.')
    with runtime_access.ownership(ROOT,timeout=0):
        sys.path[:0]=[str(ROOT/name) for name in ('scripts','website','tools')]
        import parallel_comparison as comparison
        declaration=comparison.validate_declaration(comparison.read(ROOT/'comparison/declaration.json'))
        comparison.assert_sources(ROOT,declaration['source_sha256'])
        import run
        run.KEY_PATH=ROOT/'comparison'/'nonexistent-key'
        import backtest_control
        import cache_access
        import numerical_preparation
        import schedules
        from numerical_runtime import NumericalRuntime
        from candidate_calculations import Candidate
        from original_calculations import Original
        record=dict(status='failed',operation=request['operation'],started_at=time.time(),pid=os.getpid(),
                    resources_before=comparison.observe(ROOT),cleanup_owner=declaration['cleanup_owner'])
        comparison.write(response,record)
        cancellation=backtest_control.cancel_when(cancel.exists)
        cancellation.__enter__()

        def binding():
            pointer=comparison.read(ROOT/'data/numerical/current.json')
            return dict(declaration_sha256=comparison.digest(declaration),generation=pointer['current'],
                report_sha256=comparison.file_hash(ROOT/'results/summary-exits.txt'),
                preparation_inventory=numerical_preparation.Preparation(ROOT).inventory())

        class ObservedRuntime(NumericalRuntime):
            def __init__(self,**kwargs):
                super().__init__(**kwargs);self.clocks=[]
            def _diagnostic(self,event):
                self.clocks.append(dict(time=time.perf_counter(),stage=event.get('stage')))
                super()._diagnostic(event)
            def start(self,**kwargs):
                began=time.perf_counter()
                try:return super().start(**kwargs)
                finally:self.clocks.append(dict(stage='runtime-start-returned',seconds=time.perf_counter()-began))
            def calculate(self,*args,**kwargs):
                began=time.perf_counter()
                try:return super().calculate(*args,**kwargs)
                finally:self.clocks.append(dict(stage='runtime-calculate-returned',seconds=time.perf_counter()-began))
            def close(self):
                began=time.perf_counter()
                try:return super().close()
                finally:self.clocks.append(dict(stage='runtime-close-returned',seconds=time.perf_counter()-began))

        def sample_processes():
            from process_owner import windows_processes
            if os.name=='nt':return windows_processes()
            parents={}
            for path in Path('/proc').glob('[0-9]*/stat'):
                try:parents[int(path.parent.name)]=int(path.read_text().rsplit(')',1)[1].split()[1])
                except (OSError,ValueError,IndexError):pass
            pids={os.getpid()}
            while True:
                expanded=pids|{pid for pid,parent in parents.items() if parent in pids}
                if expanded==pids:break
                pids=expanded
            values={}
            for pid in pids:
                try:
                    lines=dict(line.split(':',1) for line in Path('/proc',str(pid),'status').read_text().splitlines() if ':' in line)
                    values[str(pid)]=dict(working_set_bytes=int(lines['VmRSS'].split()[0])*1024,
                        threads=int(lines['Threads']))
                except (OSError,ValueError,KeyError):pass
            return values

        try:
            if request['operation']=='prepare':
                began=time.perf_counter();stages=[]
                preparation=numerical_preparation.Preparation(ROOT)
                def progress(**event):
                    stages.append(dict(seconds=time.perf_counter()-began,**event))
                    comparison.write(ROOT/'comparison/preparation-progress.json',stages)
                try:report=preparation.prepare(progress=progress,cancelled=cancel.exists)
                finally:preparation.close()
                record.update(status='complete',elapsed_seconds=time.perf_counter()-began,stages=stages,
                    preparation=report,binding=binding(),storage=comparison.storage(ROOT))
            elif request['operation']=='case':
                case=comparison.validate_case(request['payload']['case']); record['case']=case
                expected=request['payload']['prepared'];current=binding()
                if current!=expected:raise ValueError('Prepared input/source binding changed.')
                preparation=numerical_preparation.Preparation(ROOT)
                if preparation.status().get('state')!='current':raise ValueError('Private preparation is not current.')
                options=deepcopy(case.get('request',declaration['request']))
                with cache_access.access():
                    db=schedules.connect()
                    try:
                        import robustness
                        plan=robustness.plan(db,**options)
                        if case['backend']=='original' and case['state']=='fresh_application':
                            # Exact task-owned derived tables only; retain daily
                            # prices, sessions, companies, input metadata.
                            with db:
                                for table in ('filter_values','screening_metrics','snapshots','period_pools','periods'):
                                    db.execute('DELETE FROM '+table)
                        books_before=db.execute('SELECT COUNT(*) FROM periods').fetchone()[0]
                        import book_batch
                        original_books=book_batch.plan(db,plan) if case['backend']=='original' else None
                        if case['state']=='original_reuse' and original_books['jobs']:
                            raise ValueError('Original reuse has missing required books.')
                    finally:db.close()
                checkpoint=ROOT/'comparison'/('checkpoints-'+case['checkpoint']+'.sqlite')
                if case['state']=='full_recovery':
                    previous=comparison.read(ROOT/'comparison'/(case['repeat_of']+'.json'))
                    if previous.get('status')!='complete':raise ValueError('Recovery predecessor is incomplete.')
                    for key in ('backend','workers','threads','checkpoint'):
                        if previous['case'][key]!=case[key]:raise ValueError('Recovery execution identity differs.')
                    if previous['binding']!=dict(**current,plan_sha256=comparison.digest(plan)):
                        raise ValueError('Recovery financial plan differs.')
                    if not checkpoint.is_file():raise ValueError('Recovery checkpoint is missing.')
                elif case['backend']!='original' and checkpoint.exists():
                    raise ValueError('Fresh work cannot inherit a checkpoint.')
                if case['state']=='original_reuse':
                    previous=comparison.read(ROOT/'comparison'/(case['repeat_of']+'.json'))
                    if previous.get('status')!='complete' or previous['case']['backend']!='original':
                        raise ValueError('Original reuse needs completed Original evidence.')
                    if previous['binding']!=dict(**current,plan_sha256=comparison.digest(plan)):
                        raise ValueError('Original reuse financial plan differs.')
                record.update(binding=dict(**current,plan_sha256=comparison.digest(plan)),plan=plan,
                    books_before=books_before,checkpoint_path=str(checkpoint),filesystem_cache='Unflushed host cache',
                    state_notes='Fresh checkpoint; retained immutable prepared inputs and filesystem pages' if case['state']=='fresh_application'
                    else 'Declared reuse/initialization only; not a cold-storage claim')
                record['original_book_plan']=original_books
                runtimes=[];samples=comparison.Samples();stop=Event()
                def factory():
                    value=ObservedRuntime(source_root=ROOT,scratch=ROOT/'tmp'/('comparison-'+case['label']+'-'+str(len(runtimes))),
                        python=sys.executable,checkpoint_path=checkpoint,coordinator=cache_access.workspace,
                        session_options=dict(execution=dict(backend=case['backend'],workers=case['workers'],
                            threads_per_worker=case['threads'],start_seconds=300.)),start_seconds=300.)
                    runtimes.append(value);return value
                preparation._runtime=factory
                def sampler():
                    while not stop.wait(.5):
                        try:
                            samples.add(dict(time=time.perf_counter(),processes=sample_processes(),
                                **comparison.sampled_storage([value.scratch for value in runtimes],checkpoint)))
                        except (OSError,ValueError,AttributeError):pass
                watcher=Thread(target=sampler,daemon=True)
                progress=[];adapter=None;runtime=None
                def observed(event):
                    progress.append(dict(time=time.perf_counter(),event=event))
                def configured(value):
                    if value!=plan:raise ValueError('Application changed recorded plan.')
                began_total=time.perf_counter();watcher.start()
                try:
                    if case['backend']=='original':
                        adapter=Original()
                        began=time.perf_counter()
                        result=adapter.calculate('random',options,observed,configured,planned=plan,details=True)
                        adapter.close();elapsed=time.perf_counter()-began
                    elif case['state']=='initialized_fresh':
                        runtime=factory();initialized=time.perf_counter();runtime.start()
                        record['runtime_initialization_seconds']=time.perf_counter()-initialized
                        warmup=deepcopy(options);warmup['seed']=(options['seed']+12345)%4294967296
                        initialized=time.perf_counter()
                        runtime.calculate('random',warmup,lambda event:None,lambda value:None)
                        record['warmup_seconds']=time.perf_counter()-initialized
                        record['warmup_seed']=warmup['seed']
                        record['warmup_stats']=deepcopy(runtime.last_stats)
                        began=time.perf_counter()
                        result=runtime.calculate('random',options,observed,configured,planned=plan)
                        elapsed=time.perf_counter()-began
                    else:
                        adapter=Candidate(preparation)
                        began=time.perf_counter()
                        result=adapter.calculate('random',options,observed,configured,planned=plan,details=True)
                        adapter.close();elapsed=time.perf_counter()-began
                except BaseException as error:
                    record['primary_error_type']=type(error).__name__;raise
                finally:
                    try:comparison.close_observation(adapter,runtime,runtimes,stop,watcher,record)
                    finally:
                        record['total_session_seconds']=time.perf_counter()-began_total
                        record['sampling']=samples.evidence();record['progress']=progress
                if case['state']=='full_recovery':
                    stats=runtimes[-1].last_stats
                    if stats.get('trial_pool') is not None or stats.get('provider',{}).get('books')!=0:
                        raise ValueError('Full recovery constructed calculation workers/provider.')
                with cache_access.access():
                    db=schedules.connect()
                    try:
                        record['books_after']=db.execute('SELECT COUNT(*) FROM periods').fetchone()[0]
                        if case['backend']=='original':
                            record['original_book_plan_after']=book_batch.plan(db,plan)
                            if case['state']=='original_reuse' and (record['books_after']!=books_before or
                                result.get('execution',{}).get('missing_books',0)!=0):
                                raise ValueError('Original reuse prepared missing books.')
                    finally:db.close()
                result_path=ROOT/'comparison'/(case['label']+'.result.json')
                serialize=time.perf_counter();comparison.write(result_path,result)
                record.update(status='complete',elapsed_seconds=elapsed,result_path=str(result_path),
                    result_sha256=comparison.file_hash(result_path),evidence_serialization_seconds=time.perf_counter()-serialize,
                    resources_after=comparison.observe(ROOT),storage=comparison.storage(ROOT))
            else:raise ValueError('Unknown fixed comparison operation.')
            comparison.assert_sources(ROOT,declaration['source_sha256'])
        except BaseException as error:
            record.update(status='failed',error_type=type(error).__name__)
            # Private local diagnostic only; no requests/key access is possible.
            import traceback
            traceback.print_exc()
        finally:
            cancellation.__exit__(None,None,None)
            comparison.write(response,record)
        return 0 if record['status']=='complete' else 1


if __name__=='__main__':sys.exit(main(sys.argv[1]))
