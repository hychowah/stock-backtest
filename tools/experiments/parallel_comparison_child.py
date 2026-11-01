"""Fixed private comparison entry; source ownership precedes financial imports."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from threading import Event, Thread

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from website import runtime_access
def main(request_path):
    # Only trusted task-owned JSON, never an import/factory supplied by a case.
    request=json.loads(Path(request_path).read_text(encoding='utf-8'))
    response=Path(request['response']);cancel=Path(request['cancel'])
    if response.parent!=ROOT/'comparison': raise ValueError('Comparison response is outside owned evidence.')
    if cancel.parent!=response.parent or cancel.stem!=response.stem:raise ValueError('Invalid cancellation marker.')
    with runtime_access.ownership(ROOT,timeout=0):
        from backtest.inputs import daily
        import tools.experiments.parallel_comparison as comparison
        declaration=comparison.validate_declaration(comparison.read(ROOT/'comparison/declaration.json'))
        comparison.assert_sources(ROOT,declaration['source_sha256'])
        from backtest.financial import rules
        from backtest.inputs import market, fmp_download, cache_assets
        from backtest.engines.reference import legacy
        fmp_download.KEY_PATH=ROOT/'comparison'/'nonexistent-key'
        from backtest.runtime import backtest_control as backtest_control
        from backtest.runtime import cache_access as cache_access
        from backtest.application import preparation as numerical_preparation
        from backtest.engines.original import schedules as schedules
        from backtest.engines.numerical.runtime import NumericalRuntime
        from backtest.application.calculations import Selectable
        record=dict(status='failed',operation=request['operation'],started_at=time.time(),pid=os.getpid(),
                    resources_before=comparison.observe(ROOT),cleanup_owner=declaration['cleanup_owner'])
        comparison.write(response,record)
        cancellation=backtest_control.cancel_when(cancel.exists)
        cancellation.__enter__()

        def binding():
            pointer=comparison.read(ROOT/'data/numerical/current.json')
            return dict(declaration_sha256=comparison.digest(declaration),generation=pointer['current'],
                report_sha256=comparison.file_hash(ROOT/'results/summary-exits.txt'),
                financial_inventory=numerical_preparation.Preparation(ROOT).common_inventory())

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
            from backtest.runtime.process_owner import windows_processes
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
                preparation=numerical_preparation.Preparation(ROOT,profile=request['payload'].get('profile',numerical_preparation.DEFAULT_PROFILE))
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
                profile=request['payload']['profile']
                if case['backend']!='original' and case['backend']!=profile:
                    raise ValueError('Request backend differs from its preparation profile.')
                preparation=numerical_preparation.Preparation(ROOT,profile=profile)
                status=preparation.status()
                if status.get('state')!='current':raise ValueError('Private preparation is not current.')
                record['readiness']=dict(profile=profile,rust_required=status['dependencies']['rust_required'],
                    inventory=status['inventory'],receipt_sha256=comparison.file_hash(preparation.path))
                options=deepcopy(case.get('request',declaration['request']))
                if case['state']=='interrupted_application' and case['interrupt_after']>=options['trials']:
                    raise ValueError('Interrupted qualification must leave missing trials.')
                with cache_access.access():
                    db=daily.connect()
                    try:
                        from backtest.engines.original import robustness as robustness
                        plan=robustness.plan(db,**options)
                        if case['backend']=='original' and case['state']=='fresh_application':
                            # Exact task-owned derived tables only; retain daily
                            # prices, sessions, companies, input metadata.
                            with db:
                                for table in ('filter_values','screening_metrics','snapshots','period_pools','periods'):
                                    db.execute('DELETE FROM '+table)
                        books_before=db.execute('SELECT COUNT(*) FROM periods').fetchone()[0]
                        from backtest.engines.original import book_batch as book_batch
                        original_books=book_batch.plan(db,plan) if case['backend']=='original' else None
                        if case['state'] in ('original_reuse','original_prepared_books') and original_books['jobs']:
                            raise ValueError('Original reuse has missing required books.')
                    finally:db.close()
                checkpoint=ROOT/'comparison'/('checkpoints-'+case['checkpoint']+'.sqlite')
                if case['state'] in ('full_recovery','partial_recovery'):
                    previous=comparison.read(ROOT/'comparison'/(case['repeat_of']+'.json'))
                    expected_status='complete' if case['state']=='full_recovery' else 'qualified_interruption'
                    if previous.get('status')!=expected_status:raise ValueError('Recovery predecessor is incomplete.')
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
                    adapter_boundary=('initialized NumericalRuntime.calculate' if case['state']=='initialized_fresh'
                        else 'normal Selectable.calculate'),
                    timing_scope=('elapsed: requested direct calculate only; excludes startup, warmup and final closure; total_session includes all'
                        if case['state']=='initialized_fresh' else 'elapsed: normal adapter calculate through complete result and confirmed closure'),
                    books_before=books_before,checkpoint_path=str(checkpoint),filesystem_cache='Unflushed host cache',
                    state_notes='Fresh checkpoint; retained immutable prepared inputs and filesystem pages' if case['state']=='fresh_application'
                    else 'Declared reuse/initialization only; not a cold-storage claim')
                record['original_book_plan']=original_books
                runtimes=[];samples=comparison.Samples();stop=Event()
                def factory():
                    value=ObservedRuntime(source_root=ROOT,scratch=ROOT/'tmp'/('comparison-'+case['label']+'-'+str(len(runtimes))),
                        python=sys.executable,checkpoint_path=checkpoint,coordinator=cache_access.workspace,
                        preparation_profile=profile,
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
                    if (case['state']=='interrupted_application' and isinstance(event,dict)
                            and event.get('type')=='progress' and event.get('completed',0)>=case['interrupt_after']):
                        record['interrupted_after_completed']=event['completed']
                        raise backtest_control.Cancelled()
                def configured(value):
                    if value!=plan:raise ValueError('Application changed recorded plan.')
                dependency_before=numerical_preparation.measurements()
                began_total=time.perf_counter();watcher.start()
                try:
                    if case['backend']=='original':
                        adapter=Selectable(preparation)
                        began=time.perf_counter()
                        result=adapter.calculate('random',dict(options,engine='original'),observed,configured,planned=plan,details=True)
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
                        adapter=Selectable(preparation)
                        began=time.perf_counter()
                        result=adapter.calculate('random',dict(options,engine='experimental'),observed,configured,planned=plan,details=True)
                        adapter.close();elapsed=time.perf_counter()-began
                except BaseException as error:
                    record['primary_error_type']=type(error).__name__;raise
                finally:
                    try:comparison.close_observation(adapter,runtime,runtimes,stop,watcher,record)
                    finally:
                        record['total_session_seconds']=time.perf_counter()-began_total
                        record['sampling']=samples.evidence();record['progress']=progress
                if case['state']=='interrupted_application':
                    raise ValueError('Expected interruption did not occur.')
                if case['state']=='full_recovery':
                    stats=runtimes[-1].last_stats
                    if (stats.get('trial_pool') is not None or stats.get('provider_constructions')!=0
                            or stats.get('factor_kernel_compilation_requests')!=0):
                        raise ValueError('Full recovery constructed calculation workers/provider.')
                if case['state']=='partial_recovery' and result.get('execution',{}).get('recovered_trials',0)<previous['interrupted_after_completed']:
                    raise ValueError('Partial recovery lost committed trial work.')
                with cache_access.access():
                    db=daily.connect()
                    try:
                        record['books_after']=db.execute('SELECT COUNT(*) FROM periods').fetchone()[0]
                        if case['backend']=='original':
                            record['original_book_plan_after']=book_batch.plan(db,plan)
                            if case['state'] in ('original_reuse','original_prepared_books') and (record['books_after']!=books_before or
                                result.get('execution',{}).get('missing_books',0)!=0):
                                raise ValueError('Original reuse prepared missing books.')
                    finally:db.close()
                result_path=ROOT/'comparison'/(case['label']+'.result.json')
                serialize=time.perf_counter();comparison.write(result_path,result)
                record.update(status='complete',elapsed_seconds=elapsed,result_path=str(result_path),
                    result_sha256=comparison.file_hash(result_path),evidence_serialization_seconds=time.perf_counter()-serialize,
                    resources_after=comparison.observe(ROOT),storage=comparison.storage(ROOT))
                record['preparation_dependency_checks']={key:value-dependency_before[key]
                    for key,value in numerical_preparation.measurements().items()}
            else:raise ValueError('Unknown fixed comparison operation.')
            comparison.assert_sources(ROOT,declaration['source_sha256'])
        except BaseException as error:
            interrupted=(isinstance(error,backtest_control.Cancelled) and record.get('case',{}).get('state')=='interrupted_application'
                and record.get('interrupted_after_completed',0)>=record['case']['interrupt_after'])
            closed=all(row.get('closure',{}).get('state')=='closed' for row in record.get('runtime_observations',[]))
            if interrupted and closed and record.get('runtime_observations'):
                record.update(status='qualified_interruption',elapsed_seconds=record['total_session_seconds'],error_type=type(error).__name__)
            else:record.update(status='failed',error_type=type(error).__name__)
            # Private local diagnostic only; no requests/key access is possible.
            import traceback
            traceback.print_exc()
        finally:
            cancellation.__exit__(None,None,None)
            comparison.write(response,record)
        return 0 if record['status'] in ('complete','qualified_interruption') else 1


if __name__=='__main__':sys.exit(main(sys.argv[1]))
