"""Protocol-7 synthetic storage, actual comparison owners and live handlers.

Storage discovery is explicitly bound. These checks do not qualify ordinary
preparation, current schema-8 capture, real benchmark admission or capacity.
"""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
from concurrent.futures import Future,ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from threading import Event
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench_source_service_fixture import FictionalWorkspace,sha,MIB,_retained_workspaces
from bench_service_fixture import SyntheticService,expanded_fixture
import test_bench_execution as execution_fixture
from bench_combined_service_fixture import MeasurementOutput,measurement,command,STEP_COSTS,COSTS
import tools.experiments.bench_execution_inputs as inputs
import tools.experiments.bench_execution_supervisor as supervisor
from tools.experiments.bench_comparison import ComparisonError,digest,STEPS,STEP_COSTS as PHASES


class ProtocolWorkspace(FictionalWorkspace):
    """Reuse strong dependency closure around the explicit protocol-7 fixture.

    No source declaration or ordinary prepared generation is relabeled. The
    existing fixture writes only its declared synthetic rows and metadata.
    """
    def __init__(self):
        self.base=execution_fixture.ExecutionTests('runTest')
        self.base.setUp()
        self.request,self.scale=expanded_fixture(self.base)
        fixture=self.base.fixture
        self.fixture=fixture
        self.temporary=fixture.temporary
        self.root,self.source,self.sources=fixture.root,fixture.source,fixture.sources
        self.native_components_bytes=0
        self._owners=[]
        self.closed=False
        # Read-only strict observation needs the normal coordination files.
        from website import runtime_access
        from backtest.runtime.cache_access import WorkspaceAccess
        with runtime_access.ownership(self.source,timeout=0), \
                WorkspaceAccess(self.source/'data/website-data-0.lock').hold(timeout=0):pass


class CombinedServiceTests(unittest.TestCase):
    def setUp(self):
        self.workspace=ProtocolWorkspace()
        self.addCleanup(self.workspace.close)
        self.output=self.workspace.own(MeasurementOutput()).create()
        self.capture=self.workspace.fixture.capture
        self.manifest=json.loads((self.capture/'capture.json').read_bytes())

    def service(self,**scenario):
        w=self.workspace
        return w.own(SyntheticService(w.fixture,w.request,**scenario)).start()

    def immutable(self):
        w=self.workspace
        paths=[w.source/name for name in w.sources]
        paths+=list((w.source/'raw').rglob('*.json'))+[w.source/'raw/metrics.jsonl']
        paths+=list((w.source/'results').rglob('*'))+list(self.capture.iterdir())
        return {str(p):sha(p) for p in paths if p.is_file()}

    def run_owner(self,owner,scenario=None):
        try:
            with patch.object(supervisor.admission,'require_execution'), \
                    patch.object(owner,'_helper_command',side_effect=lambda p:command('helper',p,scenario or {})):
                owner.run()
        except BaseException as error:
            try:self.failure_evidence(owner,error)
            except Exception:pass
            raise
        return owner.result

    def failure_evidence(self,owner,error):
        """Emit bounded existing failure and closure evidence before cleanup.
        Collection never changes the exception, result or ownership state.
        """
        spec=owner.specification;protocol=spec['protocol']
        value=dict(error_type=type(error).__name__[:128],reason=str(getattr(error,'reason','unexpected'))[:128],
            protocol=digest(protocol),step_costs=protocol.get('step_costs'),closed=owner.closed,
            lifetime_closed=getattr(owner.lifetime,'closed',None),receipts=[])
        try:value['closure']=owner.owned.closure() if owner.owned else None
        except Exception as missing:value['closure_unavailable']=type(missing).__name__
        if spec['envelope'].get('storage_bytes') is not None:
            value['receipt_scope']='strict_storage_uses_existing_evidence_owner'
        else:
            for index,path in enumerate(self.output.path.glob('workspace-*/comparison.json')):
                if index==4:break
                receipt=dict(name=path.relative_to(self.output.path).as_posix())
                try:
                    if path.is_symlink():raise ValueError('Unexpected receipt link')
                    with path.open('rb') as stream:raw=stream.read(1024**2+1)
                    if len(raw)>1024**2:receipt['status']='oversized'
                    else:
                        saved=json.loads(raw)
                        receipt.update({key:saved.get(key) for key in ('status','reason','error_type','costs')})
                        receipt['step_costs']={step:{key:saved.get('step_costs',{}).get(step,{}).get(key)
                            for key in PHASES} for step in STEPS}
                        receipt['events']=[{key:event.get(key) for key in ('event','step','elapsed','reason')}
                                           for event in saved.get('events',[])[-8:]]
                except Exception as missing:receipt['unavailable']=type(missing).__name__
                value['receipts'].append(receipt)
        if len(json.dumps(value,allow_nan=False).encode())>31*1024:
            value=dict(error_type=value['error_type'],reason=value['reason'],closed=owner.closed,
                       diagnostic='truncated')
        self.report('combined_failure_evidence',**value)

    def owner(self,**kw):return measurement(self.workspace,self.capture,self.output,**kw)

    def options(self):return dict(start='2015-01-01',end='2016-12-30',months=12,pool='cached',rank_to=4)

    def delivery(self,service):
        page=service.request('GET','/');panel=service.request('GET','/data.html')
        self.assertIn(b'Disposable static delivery fixture',page)
        self.assertIn(b'<html',panel.lower())
        return dict(page_bytes=len(page),panel_bytes=len(panel))

    def financial(self,service):
        result=service.request('POST','/api/schedule',self.options())
        self.assertEqual(len(result['periods']),2)
        self.assertEqual({len(p['holdings']) for p in result['periods']},{4})
        return result

    def marker(self,phase,experiment):
        """Wait for one known checkpoint without traversing financial inputs.
        Cache its workspace path. Propagate a finished experiment's failure.
        """
        relative={'attachment':'joint-attachment','publication':'joint-publication',
            'setup':'numba_source/joint-setup','observation':'control_before/joint-observation',
            'calculation':'control_before/joint-calculation'}[phase]
        until=time.monotonic()+180.;workspace=self.output.path if phase=='attachment' else None
        while time.monotonic()<until:
            if experiment.done():
                experiment.result()
                self.fail('Experiment completed before its checkpoint.')
            if workspace is None:
                candidates=[p for p in self.output.path.glob('workspace-*') if p.is_dir()]
                self.assertTrue(all(not p.is_symlink() and re.fullmatch(r'workspace-[0-9a-f]{32}',p.name)
                                    for p in candidates),'Invalid fixture workspace identity.')
                self.assertLessEqual(len(candidates),1,'Ambiguous fixture workspace.')
                if candidates:workspace=candidates[0]
            if workspace is not None:
                path=workspace/relative
                try:json.loads(path.read_text())
                except (FileNotFoundError,json.JSONDecodeError):pass
                else:return path
            time.sleep(.05)
        self.fail('Actual combined-operation checkpoint was not reached: '+phase)

    def report(self,check,**values):print(json.dumps(dict(check=check,platform=sys.platform,**values)),flush=True)

    def closed_failure(self,owner):
        self.assertTrue(owner.closed);self.assertTrue(owner.lifetime.closed)
        closure=owner.owned.closure()
        self.assertTrue(closure['closed']);self.assertTrue(closure['descendants_empty']);self.assertTrue(closure['eof'])
        with self.assertRaises(ComparisonError):_ = owner.result
        return closure

    def saved_pools(self):
        from website import runtime_access; from backtest.runtime import cache_access as cache_access
        source=self.workspace.source
        with runtime_access.ownership(source,timeout=0), \
                cache_access.WorkspaceAccess(source/'data/website-data-0.lock').hold(timeout=0), \
                closing(sqlite3.connect((source/'data/schedules.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
            return db.execute('SELECT count(*) FROM period_pools').fetchone()[0]

    def test_explicit_protocol7_capture_and_unchanged_public_fixture_limits(self):
        x=self.manifest;w=self.workspace
        self.assertEqual(x['metadata']['research']['version'],7)
        self.assertFalse(x['benchmark_admitted']);self.assertTrue(x['originals_unchanged'])
        self.assertEqual(x['metadata']['research']['baseline_report_sha'],sha(self.capture/'report.txt'))
        self.assertEqual(w.sources,x['originals']['sources'])
        before=self.immutable()
        with inputs.CapturedWorkspace(self.capture,w.source,self.output.path) as bound:
            self.assertEqual(bound.identity,x['financial_generation'])
        self.assertEqual(before,self.immutable())
        self.assertEqual((inputs.MAX_DATABASE_BYTES,inputs.MAX_OUTPUT_BYTES,inputs.MAX_MEMORY_BYTES,inputs.MAX_SECONDS),
                         (32*MIB,64*MIB,128*MIB,10.))
        self.report('combined_explicit_protocol7',
            preparation='synthetic_storage_binding',ordinary_preparation='unqualified',
            database_bytes=sum((self.capture/n).stat().st_size for n in ('research.sqlite','schedules.sqlite')),
            generation=x['financial_generation'])

    def test_default_measured_admission_still_rejects_before_effects(self):
        owner,bound=self.owner()
        with patch.object(supervisor.tempfile,'mkdtemp',side_effect=AssertionError('Unexpected controller effect')):
            with self.assertRaises(supervisor.admission.BenchmarkAdmissionError):owner.run()
        self.assertIsNone(owner.control);self.assertFalse(self.output.path.exists())
        self.report('combined_closed_admission',admission='unavailable')

    def complete(self,*,storage):
        s=self.service();before=self.immutable();owner,bound=self.owner(storage=storage)
        result=self.run_owner(owner)
        self.assertTrue(owner.closed);self.assertEqual(result['status'],'fixture_pair_complete')
        self.assertEqual(result['execution_admission'],'unavailable')
        self.assertEqual(before,self.immutable())
        delivery=self.delivery(s);self.financial(s)
        self.assertEqual(before,self.immutable())
        files=list(self.output.path.rglob('comparison.json'))
        if not storage:
            self.assertEqual(len(files),1)
            records=[json.loads(p.read_bytes()) for p in self.output.path.glob('workspace-*/*/result.json')]
            self.assertEqual(len(records),4)
            self.assertTrue(all(row['financial_agreement'] for row in records))
            self.assertEqual(len({row['policy_signature'] for row in records}),1)
            self.assertEqual({row['binding']['financial_generation'] for row in records},{self.manifest['financial_generation']})
            self.assertTrue(all(row['details']['response_bytes']==row['details']['received_bytes'] for row in records))
        else:
            from tools.experiments.bench_execution_storage import inspect_evidence
            archive=next(self.output.path.glob('*.evidence'))
            inspected=inspect_evidence(archive)
            self.assertFalse(inspected['header']['accepted_result'])
        self.assertLessEqual(self.output.inventory()['logical_bytes'],(272 if storage else 256)*MIB+MIB)
        self.report('combined_complete_storage' if storage else 'combined_complete',
            protocol=bound.protocol.value,costs=result['costs'],financial_agreement='within_original_tolerance',
            categories='exact',delivery=delivery,measurement_output=self.output.inventory(),source_inventory=self.workspace.inventory(),
            evidence=owner.evidence)

    def test_complete_reference_both_numba_books_summaries_replay_while_service_available(self):self.complete(storage=False)

    @unittest.skipUnless(sys.platform=='linux','Explicit WSL strict storage; native ordinary-file scope is separate')
    def test_complete_pair_inside_separately_declared_strict_storage(self):self.complete(storage=True)

    def cancelled(self,phase):
        s=self.service();before=self.immutable();cancel=Event();owner,_=self.owner(cancel=cancel.is_set)
        with ThreadPoolExecutor(max_workers=1) as workers:
            task=workers.submit(self.run_owner,owner,dict(phase=phase))
            self.marker(phase,task);self.assertFalse(task.done())
            delivery=self.delivery(s)
            cancel.set()
            with self.assertRaises(ComparisonError) as caught:task.result(timeout=30)
        self.assertEqual(caught.exception.reason,'cancelled');closure=self.closed_failure(owner)
        if phase!='publication':self.assertFalse(list(self.output.path.glob('workspace-*/numba_compiled')))
        if phase in ('attachment','calculation'):self.assertFalse(list(self.output.path.glob('workspace-*/numba_source')))
        self.financial(s);self.assertEqual(before,self.immutable())
        self.report('combined_cancel_'+phase,reason='cancelled',accepted=False,delivery=delivery,
                    source_available=True,closure=closure)

    def test_cancel_attachment_keeps_actual_page_panel_and_service(self):self.cancelled('attachment')
    def test_cancel_actual_numba_setup_keeps_service(self):self.cancelled('setup')
    def test_cancel_actual_calculation_keeps_service(self):self.cancelled('calculation')
    def test_cancel_after_provisional_publication_cannot_accept_pair(self):self.cancelled('publication')

    def live(self,phase):
        s=self.service(hold_request=True);before=self.immutable();owner,_=self.owner()
        original_pools=self.saved_pools()
        with ThreadPoolExecutor(max_workers=2) as workers:
            experiment=workers.submit(self.run_owner,owner,dict(phase=phase))
            self.marker(phase,experiment);self.assertFalse(experiment.done());delivery=self.delivery(s)
            arrival=time.monotonic();request=workers.submit(self.financial,s)
            acquired=s.wait('acquired');handoff=acquired['at']-arrival
            self.assertGreaterEqual(handoff,0.);self.assertLess(handoff,2.)
            s.wait('request_held')
            with self.assertRaises(ComparisonError) as caught:experiment.result(timeout=30)
            self.assertEqual(caught.exception.reason,'busy');closure=self.closed_failure(owner)
            self.assertFalse(list(self.output.path.glob('workspace-*/numba_*')))
            (s.control/'request_held.release').touch()
            request.result(timeout=60)
        self.assertEqual(before,self.immutable())
        saved=self.saved_pools();self.assertEqual(saved,original_pools+2)
        s.close();restarted=self.workspace.own(s.restart())
        inspection=restarted.request('POST','/api/schedule',dict(self.options(),dates=['2015-01-01','2016-01-01']))
        self.assertEqual(len(inspection['periods']),2)
        self.assertEqual(self.saved_pools(),saved)
        self.report('combined_live_'+phase,handoff_seconds=handoff,bound_seconds=2.,reason='busy',accepted=False,
                    delivery=delivery,source_restarted=True,saved_pools=saved,inspection_periods=len(inspection['periods']),closure=closure)

    def test_live_financial_arrival_interrupts_real_current_observation(self):self.live('observation')
    def test_live_financial_arrival_during_committed_private_calculation_does_not_wait(self):self.live('calculation')

    def test_fictional_source_edit_and_pending_journal_reject_without_accepted_result(self):
        s=self.service();w=self.workspace
        journal=w.source/'data/research.sqlite.publication.json';journal.write_text('{}')
        owner,_=self.owner()
        try:
            with self.assertRaises(ComparisonError) as caught:self.run_owner(owner)
            self.assertEqual(caught.exception.reason,'stale');self.assertTrue(owner.closed)
        finally:journal.unlink()
        self.financial(s)
        metrics=w.source/'raw/metrics.jsonl';original=metrics.read_bytes()
        try:
            metrics.write_bytes(original+b'\n')
            other=w.own(MeasurementOutput()).create();owner,_=measurement(w,self.capture,other)
            with self.assertRaises(ComparisonError) as caught:self.run_owner(owner)
            self.assertEqual(caught.exception.reason,'stale');self.assertTrue(owner.closed)
            self.delivery(s)
        finally:metrics.write_bytes(original)
        self.report('combined_stale_and_journal',accepted=False,controlled_changes=['publication_journal','metrics_content_and_mtime'])

    def test_failed_comparison_close_retains_both_roots_after_service_closed_until_retry(self):
        owner,_=self.owner();root=self.workspace.root;output=self.output.root
        original=RuntimeError('Original fictional caller failure');owner.terminal_error=original
        with patch.object(owner,'close',side_effect=TimeoutError('Injected comparison close')):
            with self.assertRaises(TimeoutError):self.workspace.close()
        self.assertTrue(root.exists());self.assertTrue(output.exists())
        self.assertIn(id(self.workspace),_retained_workspaces)
        self.assertFalse(owner.closed)
        self.workspace.close()
        self.assertTrue(owner.closed);self.assertIs(owner.terminal_error,original)
        self.assertFalse(root.exists());self.assertFalse(output.exists())
        with self.assertRaises(ComparisonError):_ = owner.result
        self.report('combined_dependency_retry',retained_before_retry=True,closed_after_retry=True,accepted=False)


class FailureEvidenceTests(unittest.TestCase):
    def test_finished_experiment_propagates_original_failure_before_filesystem_discovery(self):
        error=ComparisonError('limit');experiment=Future();experiment.set_exception(error)
        case=CombinedServiceTests('test_default_measured_admission_still_rejects_before_effects')
        case.output=SimpleNamespace(path=Path('unused-fixture-checkpoint'))
        with patch.object(Path,'glob',side_effect=AssertionError('Unexpected discovery')):
            with self.assertRaises(ComparisonError) as caught:case.marker('publication',experiment)
        self.assertIs(caught.exception,error)
        finished=Future();finished.set_result(None)
        with self.assertRaisesRegex(AssertionError,'completed before'):case.marker('publication',finished)

    def test_checkpoint_excludes_metadata_and_rejects_ambiguous_workspaces_without_recursion(self):
        with tempfile.TemporaryDirectory(prefix='cb02-checkpoint-') as name:
            root=Path(name);(root/'workspace-owner.json').write_text('{}')
            folder=root/('workspace-'+'a'*32);folder.mkdir()
            checkpoint=folder/'joint-publication';checkpoint.write_text('{}')
            case=CombinedServiceTests('test_default_measured_admission_still_rejects_before_effects')
            case.output=SimpleNamespace(path=root);experiment=Future()
            with patch.object(Path,'rglob',side_effect=AssertionError('Recursive observation')):
                self.assertEqual(case.marker('publication',experiment),checkpoint)
                (root/('workspace-'+'b'*32)).mkdir()
                with self.assertRaisesRegex(AssertionError,'Ambiguous'):case.marker('publication',experiment)

    def test_preserves_failed_phase_costs_without_financial_payload_or_owner_mutation(self):
        with tempfile.TemporaryDirectory(prefix='cb02-failure-evidence-') as name:
            root=Path(name);folder=root/'workspace-fixture';folder.mkdir()
            receipt=folder/'comparison.json'
            receipt.write_text(json.dumps(dict(status='stopped',reason='limit',costs=dict(setup=39.),
                step_costs=dict(numba_compiled=dict(setup=0.)),
                events=[dict(event='stopped',elapsed=121.,reason='limit',evidence='private financial payload')],
                result='private financial payload')))
            original=receipt.read_bytes();error=ComparisonError('limit')
            owner=SimpleNamespace(closed=True,lifetime=SimpleNamespace(closed=True),owned=None,
                specification=dict(protocol=dict(step_costs=STEP_COSTS),envelope={}),
                _helper_command=lambda p:None,run=lambda:(_ for _ in ()).throw(error))
            case=CombinedServiceTests('test_default_measured_admission_still_rejects_before_effects')
            case.output=SimpleNamespace(path=root)
            with patch.object(case,'report') as report:
                with self.assertRaises(ComparisonError) as caught:case.run_owner(owner)
            self.assertIs(caught.exception,error);self.assertTrue(owner.closed)
            self.assertEqual(receipt.read_bytes(),original)
            evidence=report.call_args.kwargs
            self.assertEqual(evidence['receipts'][0]['costs'],dict(setup=39.))
            self.assertNotIn('private financial payload',json.dumps(evidence))
            self.assertEqual(sum(row['setup'] for row in STEP_COSTS.values()),COSTS['setup'])
            self.assertEqual([STEP_COSTS[s]['setup'] for s in STEPS],[15.,75.,75.,15.])

    def test_missing_oversized_or_failed_logging_never_masks_original_failure(self):
        with tempfile.TemporaryDirectory(prefix='cb02-failure-evidence-') as name:
            root=Path(name);folder=root/'workspace-fixture';folder.mkdir()
            (folder/'comparison.json').write_bytes(b' '* (1024**2+1))
            error=ComparisonError('limit')
            owner=SimpleNamespace(closed=False,lifetime=None,owned=None,
                specification=dict(protocol=dict(step_costs=STEP_COSTS),envelope={}),
                _helper_command=lambda p:None,run=lambda:(_ for _ in ()).throw(error))
            case=CombinedServiceTests('test_default_measured_admission_still_rejects_before_effects')
            case.output=SimpleNamespace(path=root)
            with patch.object(case,'report') as report:
                with self.assertRaises(ComparisonError) as caught:case.run_owner(owner)
            self.assertIs(caught.exception,error);self.assertFalse(owner.closed)
            self.assertEqual(report.call_args.kwargs['receipts'][0]['status'],'oversized')
            (folder/'comparison.json').unlink()
            with patch.object(case,'report',side_effect=OSError('Injected diagnostic failure')):
                with self.assertRaises(ComparisonError) as caught:case.run_owner(owner)
            self.assertIs(caught.exception,error);self.assertFalse(owner.closed)


if __name__=='__main__':unittest.main()
