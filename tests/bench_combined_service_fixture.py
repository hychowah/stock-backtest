"""Full fictional generation through existing capture and measurement owners.

This declaration qualifies only the named fictional workload and recorded
platform capabilities. It does not enlarge public fixture limits, admit real
execution or establish production capacity.
"""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
from tools.experiments.bench_comparison import ComparisonProtocol,digest

MIB=1024**2
COSTS=dict(attachment=45.,clone=32.,setup=180.,proof=60.,request=80.,
           collection=20.,shutdown=20.,finalization=20.)
# Allocate setup by execution role before execution. Reference controls receive
# 15 seconds each; both Numba steps receive 75. Aggregate setup remains 180.
SETUP_SECONDS=dict(control_before=15.,numba_source=75.,numba_compiled=75.,control_after=15.)
STEP_COSTS={step:{key:(setup if key=='setup' else COSTS[key]/4)
                 for key in ('clone','setup','proof','request','collection','shutdown')}
            for step,setup in SETUP_SECONDS.items()}


class MeasurementOutput:
    """Own a separate fixture destination; only explicit closure removes it."""
    def __init__(self):
        self.root=None
        self.closed=False

    def create(self):
        if self.closed or self.root is not None:raise ValueError('Measurement destination is single-use.')
        self.root=Path(tempfile.mkdtemp(prefix='cb02-combined-output-'))
        return self

    @property
    def path(self):
        if self.root is None or self.closed:raise ValueError('Measurement destination is inactive.')
        return self.root/'measurement'

    def inventory(self):
        files=[p for p in self.root.rglob('*') if p.is_file()]
        assert not any(p.is_symlink() for p in self.root.rglob('*'))
        return dict(files=len(files),logical_bytes=sum(p.stat().st_size for p in files))

    def close(self):
        if not self.closed:
            if self.root is not None:shutil.rmtree(self.root)
            self.closed=True


def measurement(workspace,capture,output,*,storage=False,cancel=None):
    """Build an ordinary measured-execution specification from truthful capture.

    The capture producer's limits remain in its manifest. This operation's
    separate bounds and frozen ordinary samples belong to its own protocol.
    """
    import tools.experiments.bench_execution as execution
    import tools.experiments.bench_execution_supervisor as supervisor
    manifest=json.loads((capture/'capture.json').read_bytes())
    from backtest.engines.original import robustness as robustness
    with closing(sqlite3.connect(capture/'schedules.sqlite')) as db:
        db.row_factory=sqlite3.Row
        configuration=robustness.plan(db,start='2015-01-01',end='2016-12-30',months=12,
                                      trials=5,seed=42,pool='cached',rank_to=4)
    lifetime=(dict(memory_bytes=2304*MIB,tasks=96,cpu_percent=25) if sys.platform=='linux'
        else dict(kind='windows-job',committed_bytes=2304*MIB,processes=16,
                  cpu_percent=25,user_cpu_seconds=180.))
    envelope=execution.ExecutionEnvelope(64*MIB,256*MIB,2*1024**3,480.,2,120.,
        close_seconds=15.,lifetime=lifetime,
        storage_bytes=256*MIB if storage else None,evidence_bytes=272*MIB if storage else None)
    protocol=ComparisonProtocol.freeze(configuration=configuration,
        binding=dict(capture_id=manifest['capture_id'],financial_generation=manifest['financial_generation'],
                     sources=digest(manifest['originals']['sources'])),
        environment=execution.environment(envelope),costs=COSTS,
        step_costs=STEP_COSTS,
        whole_seconds=480.,max_control_drift=1000.,max_bracket_seconds=450.)
    owner=execution.MeasurementExecution(capture,workspace.source,output.path,protocol,envelope,
        coordinated_observation_root=workspace.source,cancel=cancel)
    controlled=workspace.own(supervisor.ComparisonSupervisor(supervisor.specification(owner),cancel=cancel))
    return controlled,owner


def command(role,request,scenario,*,tools=None):
    return [sys.executable,'-X','utf8','-I','-B','-c',
        'import sys;sys.path[:0]=sys.argv[1:3];from bench_combined_service_fixture import dispatch;dispatch(sys.argv[3],sys.argv[4],sys.argv[5])',
        str(ROOT/'tests'),str(tools or ROOT),role,str(request),json.dumps(scenario)]


def dispatch(role,request_path,scenario_text):
    """Test-only interception around existing operations; never alternate results.

    Nothing shipped accepts this harness's admission patches or phase barriers.
    Every financial call and current observation still reaches actual code.
    """
    from unittest.mock import patch
    scenario=json.loads(scenario_text)
    path=Path(request_path)
    if role=='helper':
        import tools.experiments.bench_execution_supervisor_worker as helper
        def controller(owner,request):return command('controller',request,scenario)
        sys.argv=['fixture',str(ROOT),str(path)]
        with patch.object(helper.admission,'require_execution'), \
                patch.object(helper._ApplicationSupervisor,'_command',controller):
            raise SystemExit(helper.main())
    if role=='controller':
        import tools.experiments.bench_execution as execution
        import tools.experiments.bench_execution_controller as controller
        def worker(owner,request):return command('worker',request,scenario,tools=owner._tools)
        if scenario.get('phase')=='attachment':
            original=execution.inputs._manifest
            def manifest(*args,**kwargs):
                result=original(*args,**kwargs)
                spec=json.loads(path.read_bytes())
                barrier(Path(spec['output'])/'joint-attachment')
                return result
            execution.inputs._manifest=manifest
        if scenario.get('phase')=='publication':
            original=execution.MeasurementExecution._persist
            def persist(owner,status,error=None):
                result=original(owner,status,error)
                if status=='complete':barrier(owner._workspace._folder/'joint-publication')
                return result
            execution.MeasurementExecution._persist=persist
        sys.argv=['fixture',str(ROOT),str(path)]
        with patch.object(controller.admission,'require_execution'), \
                patch.object(execution.MeasurementExecution,'_command',worker):
            raise SystemExit(controller.main())
    if role!='worker':raise AssertionError('Unknown combined fixture role.')
    import tools.experiments.bench_execution_worker as worker
    phase=scenario.get('phase')
    original_bind=worker._bind
    def binding(request):
        # Validate and attach private source before importing any engine or
        # numerical interception. Controller/support imports stay in their role.
        s,robust,baseline=original_bind(request)
        if phase=='observation':
            import tools.experiments.bench_execution_observation as observations
            original=observations.signature
            def scanning(research,checkpoint):
                barrier(path.parent/'joint-observation',checkpoint=checkpoint)
                return original(research,checkpoint)
            observations.signature=scanning
        elif phase=='setup':
            from tools.experiments.bench_candidates import NumericInputs
            original=NumericInputs.__init__
            def initializing(owner,*args,**kwargs):
                result=original(owner,*args,**kwargs)
                barrier(path.parent/'joint-setup')
                return result
            NumericInputs.__init__=initializing
        elif phase=='calculation':
            original=robust.run
            def calculating(db,configuration,progress=None,**kwargs):
                def committed(value):
                    if progress:progress(value)
                    if value['type']=='progress' and value['completed']==1:
                        barrier(path.parent/'joint-calculation')
                return original(db,configuration,progress=committed,**kwargs)
            robust.run=calculating
        return s,robust,baseline
    worker._bind=binding
    sys.argv=['fixture',str(path)]
    with patch.object(worker.admission,'require_execution'):worker.main()


def barrier(path,*,checkpoint=lambda:None):
    path.write_text(json.dumps(dict(at=time.monotonic())),encoding='utf-8')
    until=time.monotonic()+30.
    while not path.with_name(path.name+'.release').exists():
        checkpoint()
        if time.monotonic()>until:raise TimeoutError('Combined fixture barrier expired.')
        time.sleep(.005)
