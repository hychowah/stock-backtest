"""Complete native financial policy, checked buffers and immutable build proof.

All inputs are fictional private SQLite fixtures. Compiler discovery is explicit;
platform release evidence must run these tests with a native compiler, not skip.
"""
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.financial import books as financial_books
from copy import deepcopy
from datetime import date
import io
import json
import os
from pathlib import Path
import shutil
import sys
from threading import Event,Thread
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tools'),str(ROOT/'tests'),str(ROOT)]
import numpy as np
from backtest.runtime import backtest_control as backtest_control
from backtest.engines.numerical import candidates as candidates
from backtest.engines.numerical import rust as rust
from backtest.engines.numerical import rust_codegen as codegen
from backtest.engines.numerical.books import PythonExecutor
from backtest.engines.numerical.numba import NumbaExecutor
from backtest.engines.numerical.portfolio import NumericalPortfolio, compare_results
from backtest.engines.numerical.execution import ExecutionPolicy
from backtest.engines.numerical import random as numerical_random
from backtest.engines.numerical import session as numerical_session
from backtest.engines.numerical import trial as numerical_trial
from backtest.engines.numerical.trial_pool import TrialPool
from backtest.engines.numerical.workspace import RequestWorkspace
from backtest import result_evidence as result_evidence
from backtest.engines.original import robustness as robustness
from backtest.engines.numerical import checkpoints as trial_checkpoints
import test_bench_candidates as source_tests
import test_bench_candidates_numba as numba_tests
import test_numerical_generation as generations

try:rust.numerical_toolchain.inspect_toolchain();AVAILABLE=True
except ImportError:AVAILABLE=False

def expected_identity(inputs,limits):return rust.identity(inputs,limits['threads'])


@unittest.skipUnless(AVAILABLE,'An explicit native Rust compiler is required.')
class RustCandidates(source_tests.CandidateTests):
    @staticmethod
    def factory(inputs,policy=None,limits=None):return rust.RustExecutor(inputs,policy,limits)

    def setUp(self):
        super().setUp()
        self.enterContext(patch.dict(os.environ,BACKTEST_RUST_BUILDS=str(self.root/'native-builds')))
        self.enterContext(patch.object(rust,'_build_root',return_value=self.root/'native-builds'))

    mutation=numba_tests.CompiledCandidateTests.mutation
    test_supported_source_mutations_change_identity_and_complete_behavior=numba_tests.CompiledCandidateTests.test_supported_source_mutations_change_identity_and_complete_behavior
    test_uncovered_source_structure_and_dependencies_fail_attachment=numba_tests.CompiledCandidateTests.test_uncovered_source_structure_and_dependencies_fail_attachment
    test_source_guard_syntax_does_not_require_compiled_translation=numba_tests.CompiledCandidateTests.test_source_guard_syntax_does_not_require_compiled_translation

    def test_compiled_candidates_bypass_python_guards_and_encoder_and_agree_numba(self):
        self.rich_financials();inputs,native=self.make()
        compiled=NumbaExecutor(inputs,limits=dict(threads=2,request_plan=True,candidate_assembly='compiled'))
        self.addCleanup(compiled.close)
        source=PythonExecutor(inputs);self.addCleanup(source.close)
        books=[('2015-01-02','2016-01-04',pool) for pool in ('cached','legacy')]
        options=self.all_fields();expected=source.evaluate(books,options)
        with patch.object(inputs.policy,'_snapshot',side_effect=AssertionError('No Python snapshot')), \
             patch.object(financial_books,'eligible',side_effect=AssertionError('No Python eligibility')), \
             patch.object(inputs.policy,'_current',side_effect=AssertionError('No Python pair')), \
             patch.object(inputs.policy,'_three',side_effect=AssertionError('No Python three-year pair')), \
             patch.object(PythonExecutor,'_encode_candidate',side_effect=AssertionError('No source encoding')):
            for provider in (native,compiled):
                self.assertTrue(source_tests.baseline.compare(expected,provider.evaluate(books,options))['exact'])
        self.assertTrue(compiled.stats['nopython_signatures']['materialize'])
        self.assertIn('typed candidate',native.stats['coverage'])

    def test_checked_shapes_dtypes_ranges_aliases_capacities_zero_and_abi(self):
        inputs,provider=self.make();kernel=provider.kernel
        valid=np.ones((1,len(inputs.policy.input_names)))
        for bad in (valid.astype(np.float32),valid[:,::-1],valid[:,1:],valid.reshape(-1)):
            with self.subTest(shape=bad.shape),self.assertRaises(ValueError):kernel.calculate(bad)
        self.assertEqual(kernel.calculate(np.empty((0,valid.shape[1]))).shape,(0,len(inputs.policy.output_names)))
        for entries in (np.array([2**40]),np.array([0],dtype=np.int32),np.array([1],dtype='>i4')):
            with self.assertRaises(ValueError):kernel.reports(entries)
        symbols=np.array([0],dtype=np.int32);days=np.array([date(2015,1,2).toordinal()],dtype=np.int32)
        columns=np.zeros(1,dtype=np.int8);directions=np.zeros(1,dtype=np.bool_)
        for args in ((symbols.astype(np.int64),days,columns,directions),
                     (symbols,days,columns,np.zeros(1,dtype=np.uint8)),
                     (np.array([len(inputs.symbols)],dtype=np.int32),days,columns,directions),
                     (symbols,days,np.array([2],dtype=np.int8),directions),
                     (symbols,days[:0],columns,directions)):
            with self.assertRaises(ValueError):kernel.resolve(*args)
        with patch.dict(inputs.pool_offsets,{'cached':np.array([-1]*len(inputs.pool_offsets['cached']),dtype=np.int64)}):
            with self.assertRaises(ValueError):kernel.reports(days)
        out=np.empty((1,len(inputs.policy.output_names)))
        # Safe bridge rejects output capacity and writable aliases before any
        # partial result can escape; native independently checks element counts.
        with self.assertRaises(ValueError):kernel._call('candidate_factors',(1,1),[valid],[out[:,:1]])
        aliased=np.zeros(max(valid.size,out.size))
        with self.assertRaisesRegex(ValueError,'overlap'):
            kernel._call('candidate_factors',(1,1),[aliased[:valid.size].reshape(valid.shape)],
                [aliased[:out.size].reshape(out.shape)])
        meta=np.zeros((0,6),dtype=np.int32)
        batch=kernel.materialize(np.empty((0,7),dtype=np.int32),np.empty((0,7)),
            np.empty((0,len(inputs.policy.output_names))),meta,np.empty((0,valid.shape[1])),
            np.ones(len(inputs.policy.filter_order),dtype=np.uint8))
        self.assertEqual(batch.count,0);self.assertEqual(batch.validate(0,inputs.policy).size,0)
        with self.assertRaises(ValueError):kernel.materialize(np.zeros((1,7),dtype=np.int32),np.ones((1,7)),out,
            np.ones((1,6),dtype=np.int32),valid,np.ones(len(inputs.policy.filter_order),dtype=np.uint8),2**63)
        with patch.object(rust,'ABI',rust.ABI+1):
            with self.assertRaisesRegex(ValueError,'ABI'):rust.NativeKernel(inputs,provider.compiler,provider.limits)

    def test_build_identity_artifact_integrity_failure_and_library_close(self):
        inputs,provider=self.make();expected=provider.compiler
        self.assertEqual(expected,rust.identity(inputs,provider.stats['threads']))
        with patch.object(codegen,'ABI',codegen.ABI+1):
            # Rust ABI version in generated source is source-bound even if the
            # loaded module's checked version remains unchanged.
            self.assertNotEqual(expected,rust.identity(inputs,provider.stats['threads']))
        other=rust.RustExecutor(inputs,limits=provider.limits);self.addCleanup(other.close)
        self.assertTrue(other.kernel.stats['build_reused'])
        self.assertEqual(other.compiler,expected)
        kernel=other.kernel;other.close();other.close()
        self.assertIsNone(other.inputs);self.assertIsNone(other.policy)
        with self.assertRaises(ValueError):kernel.calculate(np.ones((1,len(inputs.policy.input_names))))
        record=provider.kernel.stats;library=Path(os.environ['BACKTEST_RUST_BUILDS'])/record['directory']/('kernel.dll' if os.name=='nt' else 'kernel.so')
        # A retained source receipt is checked too, without modifying a mapped
        # DLL on Windows. Replacement fails before attachment or recompilation.
        source=library.with_name('kernel.rs');source.write_bytes(source.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'integrity'):rust.RustExecutor(inputs,limits=provider.limits)
        receipt=Path(os.environ['BACKTEST_RUST_BUILDS'])/(expected['signature']+'.json')
        saved=json.loads(receipt.read_text());saved['source_sha256']=rust._sha(source)
        receipt.write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError,'integrity'):rust.RustExecutor(inputs,limits=provider.limits)
        if os.name=='nt':
            provider.close();renamed=library.with_name('released.dll');library.rename(renamed);renamed.rename(library)

    def test_failed_compilation_and_attachment_leave_no_loaded_provider(self):
        from types import SimpleNamespace
        inputs=source_tests.core.NumericInputs(self.reader,source_tests.s);self.addCleanup(inputs.close)
        expected=rust.identity(inputs,1)
        failed=SimpleNamespace(poll=lambda:1,returncode=1)
        with patch.object(rust.subprocess,'Popen',return_value=failed):
            with self.assertRaisesRegex(RuntimeError,'compilation failed'):rust.NativeKernel(inputs,expected,dict(threads=1))
        root=Path(os.environ['BACKTEST_RUST_BUILDS'])
        self.assertFalse(list(root.glob('build-*')))
        with patch.object(rust.ctypes,'CDLL',side_effect=RuntimeError('fixture attachment')):
            with self.assertRaisesRegex(RuntimeError,'fixture attachment'):rust.NativeKernel(inputs,expected,dict(threads=1))
        self.assertFalse(list(root.glob('build-*')))

    def test_repeated_load_call_close_with_live_python_caller(self):
        inputs=source_tests.core.NumericInputs(self.reader,source_tests.s);self.addCleanup(inputs.close)
        for repeat in range(8):
            provider=rust.RustExecutor(inputs,limits=dict(threads=2));self.addCleanup(provider.close)
            kernel=provider.kernel;called,release=Event(),Event();errors=[]
            def run():
                try:
                    kernel.calculate(np.ones((8,len(inputs.policy.input_names))))
                    called.set()
                    if not release.wait(10):raise AssertionError('Caller release gate was not opened')
                except BaseException as error:errors.append(error);called.set()
            worker=Thread(target=run);worker.start()
            try:
                self.assertTrue(called.wait(10));self.assertFalse(errors)
                # The synchronous native call is over, but its Python caller
                # remains alive. Library closure must not leave TLS callbacks
                # that will execute unloaded code when that caller later exits.
                provider.close();self.assertIsNone(provider.inputs)
            finally:
                release.set();worker.join(10)
            self.assertFalse(worker.is_alive());self.assertFalse(errors)
        print(json.dumps(dict(check='repeated-rust-call-close',repeats=8,caller_lifetime='Held alive after ABI return through provider close')),flush=True)

    def test_native_tls_destructors_complete_before_abi_returns(self):
        policy=source_tests.core.PolicyProgram()
        source=self.root/'tls-proof.rs';source.write_bytes(codegen.source(policy).encode('utf-8'))
        binary=self.root/('tls-proof.exe' if os.name=='nt' else 'tls-proof')
        descriptor=rust.numerical_toolchain.inspect_toolchain()
        command=rust._Command([descriptor['compiler'],'--edition=2021','--test',str(source),'-o',str(binary),
            '-C','linker='+str(Path(descriptor['directory'])/descriptor['linker']['path'])],descriptor)
        rust._run_compiler(command)
        result=rust._run_compiler([str(binary),'--exact','lifetime_tests::tls_destructors_finish_before_return','--nocapture'])
        self.assertIn(b'test result: ok',result)
        # The same controlled ABI test must reject the original automatic-join
        # pattern, rather than merely observing a scheduler-dependent delay.
        old=codegen.source(policy).replace('for handle in handles {okay=handle.join().is_ok() && okay;}', 'drop(handles);')
        self.assertNotEqual(old,codegen.source(policy))
        source.write_bytes(old.encode('utf-8'))
        rust._run_compiler(command)
        with self.assertRaisesRegex(RuntimeError,'operation failed'):rust._run_compiler([str(binary),'--exact',
            'lifetime_tests::tls_destructors_finish_before_return','--nocapture'])

    def test_fresh_build_rejects_changed_generated_source_before_publication(self):
        inputs=source_tests.core.NumericInputs(self.reader,source_tests.s);self.addCleanup(inputs.close)
        expected=rust.identity(inputs,1);original=rust._run_compiler
        def run(command):
            result=original(command)
            if '--crate-name' in command:
                path=Path(command[-3]);path.write_bytes(path.read_bytes()+b'\n// altered fixture source\n')
            return result
        with patch.object(rust,'_run_compiler',side_effect=run):
            with self.assertRaisesRegex(ValueError,'integrity'):rust._build(inputs,expected)
        root=Path(os.environ['BACKTEST_RUST_BUILDS'])
        self.assertFalse(list(root.glob('*.json')))
        self.assertFalse(list(root.glob('build-*')))
        self.assertFalse(list(root.glob('library-*')))

    def test_compiler_metadata_and_build_cancellation_drains_children(self):
        inputs=source_tests.core.NumericInputs(self.reader,source_tests.s);self.addCleanup(inputs.close)
        expected=rust.identity(inputs,1)
        original=rust.subprocess.Popen
        for phase in ('build',):
            with self.subTest(phase=phase):
                marker=self.root/(phase+'-ready');children=[]
                command=[sys.executable,'-c',
                    'import pathlib,time; pathlib.Path('+repr(str(marker))+').write_text("ready"); time.sleep(30)']
                def launch(actual,**options):
                    self.assertEqual('-vV' in actual,phase=='metadata')
                    child=original(command,**options);children.append(child);return child
                def checkpoint():
                    if marker.exists():raise backtest_control.Cancelled()
                with patch.object(rust.subprocess,'Popen',side_effect=launch), \
                     patch.object(backtest_control,'checkpoint',side_effect=checkpoint):
                    with self.assertRaises(backtest_control.Cancelled):
                        if phase=='metadata':rust.identity(inputs,1)
                        else:rust._build(inputs,expected)
                self.assertEqual(len(children),1)
                self.assertIsNotNone(children[0].poll(),'Cancelled compiler child must already be drained')
                self.assertTrue(marker.exists(),'Cancellation must occur after child startup')
                self.assertFalse(list(Path(os.environ['BACKTEST_RUST_BUILDS']).glob('build-*')))
                print(json.dumps(dict(check='compiler-cancellation',phase=phase,pid=children[0].pid,
                    exit=children[0].returncode,drained=True)),flush=True)

    def test_cancellation_between_bounded_native_calls_and_concurrent_close(self):
        inputs,provider=self.make();kernel=provider.kernel
        kernel.chunk_rows=1
        with patch.object(backtest_control,'checkpoint',side_effect=RuntimeError('cancelled fixture')):
            with self.assertRaisesRegex(RuntimeError,'cancelled'):kernel.resolve(np.array([0],dtype=np.int32),
                np.array([1],dtype=np.int32),np.zeros(1,dtype=np.int8),np.zeros(1,dtype=np.bool_))
        entered,release,closed=Event(),Event(),Event()
        original=kernel._library.candidate_factors
        def delayed(*args):entered.set();self.assertTrue(release.wait(5));return original(*args)
        matrix=np.ones((1,len(inputs.policy.input_names)));errors=[]
        with patch.object(kernel._library,'candidate_factors',side_effect=delayed):
            def calculate():
                try:kernel.calculate(matrix)
                except BaseException as error:errors.append(error)
            worker=Thread(target=calculate);worker.start();self.assertTrue(entered.wait(5))
            closer=Thread(target=lambda:(kernel.close(),closed.set()));closer.start()
            self.assertFalse(closed.wait(.05));release.set();worker.join(5);closer.join(5)
        self.assertFalse(errors);self.assertTrue(closed.is_set());kernel.close()


class RustSourceTests(unittest.TestCase):
    def test_unknown_nonpython_resource_fails_source_closure(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'unknown.rs').write_text('fn main() {}')
            with self.assertRaisesRegex(ValueError,'source resource'):
                numerical_random._source_closure(root,['unknown.rs'])

    def test_rejected_source_syntax_and_lowered_representation(self):
        from types import SimpleNamespace
        import ast
        program=SimpleNamespace(trees={'eligible':ast.parse('def f(numeric,pool):\n return eval("unknown")').body[0]})
        with self.assertRaisesRegex(ValueError,'Unsupported validated'):codegen.DecisionLowering(program).source()
        self.assertNotIn('bench_candidates',Path(rust.__file__).read_text())
        policy=source_tests.core.PolicyProgram()
        from types import SimpleNamespace
        with self.assertRaisesRegex(ValueError,'compiled provider'):
            PythonExecutor(SimpleNamespace(policy=policy),limits=dict(candidate_assembly='compiled'))
        text=codegen.source(policy)
        self.assertNotIn('__',text);self.assertIn('fn decision_snapshot',text)
        self.assertEqual(set(policy.decisions.trees),{'snapshot','eligible','current','three'})
        self.assertIn('backtest/engines/numerical/rust_kernel.rs',numerical_random.source_identity())


@unittest.skipUnless(AVAILABLE,'An explicit native Rust compiler is required.')
class RustTrials(unittest.TestCase):
    def setUp(self):
        self.fixture=generations.GenerationTests('test_export_values_order_missingness_and_mutable_books_reuse')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups);self.fixture.prepare()
        self.inputs=self.fixture.attach()
        self.enterContext(patch.dict(os.environ,BACKTEST_RUST_BUILDS=str(self.fixture.root/'native-builds')))
        self.enterContext(patch.object(rust,'_build_root',return_value=self.fixture.root/'native-builds'))

    def test_complete_period_trial_both_orders_metrics_calendars_and_stream_artifacts(self):
        providers=[NumbaExecutor(self.inputs,limits=dict(threads=2,request_plan=True,candidate_assembly=assembly)) for assembly in ('source','compiled')]
        providers.append(rust.RustExecutor(self.inputs,limits=dict(threads=2,request_plan=True)))
        portfolios=[]
        for provider in providers:
            self.addCleanup(provider.close);portfolio=NumericalPortfolio(self.inputs,provider)
            self.addCleanup(portfolio.close);portfolios.append(portfolio)
        cases=0;maximum=0.
        for pool in ('legacy','cached'):
            for order in ('filter_first','rank_first'):
                for metric in self.fixture.s.metrics.METRICS:
                    for calendar in (dict(unit='month',count=3),dict(unit='week',count=2)):
                        config=numerical_random.numerical_calendar.plan(portfolios[0]._calendar().sessions,
                            dict(trials=2,seed=42,
                            calendar=dict(version=1,start='2015-01-05',end='2015-05-01',interval=calendar),pool=pool,selection_order=order,metric=metric,min_cap=0.,min_ev=0.,rank_to=5,
                            filters=[dict(field='pe',op='gt',value=-1e9)]))
                        for number in (1,2):
                            spec=numerical_trial.specification(numerical_random.checkpoint_binding(portfolios[0],config),number)
                            expected=self.fixture.s.backtest_dates(self.fixture.db,dates=spec['request']['dates'],
                                start=config['calendar']['start'],end=config['calendar']['end'],months=12,**spec['options'])
                            expected.pop('months');expected['calendar']=config['calendar']
                            for portfolio in portfolios:
                                # Each backend's evidence retains its own binding.
                                spec=numerical_trial.specification(numerical_random.checkpoint_binding(portfolio,config),number)
                                with io.BytesIO() as stream:
                                    limits=dict(max_bytes=8*1024**2,piece_bytes=127,record_bytes=16384)
                                    descriptor=numerical_trial.TrialEvaluator(portfolio,calculation_identity=spec['calculation_identity']).produce(spec,stream,limits=limits)
                                    artifact=numerical_trial.open_artifact(stream,descriptor,expected_spec=spec,limits=limits,checkpoint=backtest_control.checkpoint)
                                    actual=dict(artifact.summary,periods=list(artifact.periods()))
                                    agreement=compare_results(expected,actual);self.assertTrue(agreement['exact'],agreement)
                                    maximum=max(maximum,agreement['maximum_absolute']);cases+=1
        print(json.dumps(dict(check='complete-source-compiled-rust-trials',cases=cases,maximum_absolute=maximum,tolerance=1e-12)),flush=True)

    @unittest.skip('Historical Rust runtime selection retained in archived E/F/G comparison source; current app selects compiled Numba.')
    def test_rust_runtime_session_releases_provider_library_and_input_mappings(self):
        from backtest.engines.numerical.runtime import NumericalRuntime
        (self.fixture.root/'binding.json').write_text(json.dumps(self.fixture.binding))
        scratch=self.fixture.root/'actual-rust-runtime'
        runtime=NumericalRuntime(source_root=ROOT,scratch=scratch,generation_path=self.fixture.store.path,
            checkpoint_path=self.fixture.root/'runtime-trials.sqlite',coordinator=self.fixture.owner,threads=1,
            session_factory='numerical_runtime_fixture:Session',session_options=dict(execution=dict(backend='rust',
                workers=2,threads_per_worker=1,lane_budget=2,artifact_bytes=8*1024**2,piece_bytes=127,record_bytes=16384)))
        self.addCleanup(runtime.close)
        request=dict(start='2015-01-05',end='2016-12-30',months=12,pool='cached',selection_order='rank_first',
            min_cap=0.,min_ev=0.,rank_to=5)
        expected=self.fixture.s.backtest(self.fixture.db,**request)
        actual=runtime.calculate('custom',request)
        self.assertTrue(compare_results(expected,actual)['exact'])
        self.assertEqual(runtime.last_stats['provider']['backend'],'rust')
        plan=robustness.plan(self.fixture.db,**request,trials=3,seed=42)
        random_request=dict(request,trials=3,seed=42)
        result=runtime.calculate('random',random_request,planned=plan)
        self.assertEqual(result['completed'],3)
        self.assertEqual(runtime.last_stats['trial_pool']['started_workers'],2)
        runtime.close();runtime.close();closure=runtime.closure()
        self.assertEqual(closure["state"],"closed")
        for field in ("closed","eof","reader_stopped","streams_closed","descendants_empty","native_handles_released"):
            self.assertTrue(closure["process"][field],field)
        self.assertTrue(runtime.owner.closed)
        marker=json.loads((scratch/'fixture-state.json').read_text())
        for field in ('closed','portfolio_closed','provider_closed','mappings_closed','record_db_closed','sql_closed','workspace_sql_closed','checkpoint_db_closed'):
            self.assertTrue(marker[field],field)
        self.inputs.close()  # Release this test's independent parent attachment too.
        generation=self.fixture.store.path/self.fixture.store._pointer()['current']
        moved=generation.with_name(generation.name+'-runtime-released');generation.rename(moved);moved.rename(generation)
        # Actual DLL rename is checked after provider close by the direct native
        # test. Here the runtime owner must confirm the complete process domain.
        print(json.dumps(dict(check='actual-rust-runtime-closure',provider_backend='rust',resources=marker,
            owner_closed=runtime.owner.closed,closure=closure)),flush=True)

    def test_empty_selected_periods_preserve_complete_reducer_results(self):
        providers=[NumbaExecutor(self.inputs,limits=dict(threads=2,request_plan=True,candidate_assembly='compiled')),
                   rust.RustExecutor(self.inputs,limits=dict(threads=2,request_plan=True))]
        portfolios=[]
        for provider in providers:
            self.addCleanup(provider.close);portfolio=NumericalPortfolio(self.inputs,provider)
            self.addCleanup(portfolio.close);portfolios.append(portfolio)
        for pool in ('legacy','cached'):
            for order in ('filter_first','rank_first'):
                for end in ('2015-01-06','2015-02-27'):
                    request=dict(calendar=dict(version=1,start='2015-01-05',end=end,interval=dict(unit='week',count=1)),
                        pool=pool,selection_order=order,metric='ev_ebitda_3y',min_cap=0.,min_ev=0.,rank_to=5,
                        filters=[dict(field='pe',op='gt',value=1e9)])
                    pairs,_,selection,metadata=numerical_random.numerical_calendar.periods(portfolios[0]._calendar().sessions,request)
                    expected=self.fixture.s.backtest_periods(self.fixture.db,pairs,months=12,**selection)
                    expected.pop('months');expected.update(metadata)
                    for portfolio in portfolios:
                        actual=portfolio.backtest_calendar(**request)['result']
                        self.assertTrue(compare_results(expected,actual)['exact'])
                        self.assertTrue(all(period['holdings']==[] for period in actual['periods']))

    @unittest.skip('Historical Rust pool selection retained in archived E/F/G comparison source; current app selects compiled Numba.')
    def test_persistent_native_workers_d_recovery_without_compilation_and_mapping_release(self):
        policy=ExecutionPolicy(dict(backend='rust',workers=2,threads_per_worker=1,lane_budget=2,
            artifact_bytes=8*1024**2,piece_bytes=127,record_bytes=16384))
        began=time.perf_counter();expected=expected_identity(self.inputs,policy.provider_limits)
        compiler_probe_seconds=time.perf_counter()-began
        workspace=RequestWorkspace(self.inputs);self.addCleanup(workspace.close)
        config=robustness.plan(workspace.db,start='2015-01-05',end='2016-12-30',trials=3,seed=42,
            min_cap=0.,min_ev=0.,rank_to=5,selection_order='rank_first')
        execution=numerical_random.provider_execution(self.inputs,policy.provider_limits,expected)
        execution['trial_pool']=policy.execution_identity(expected)
        binding=numerical_random.checkpoint_binding(workspace,config,execution=execution)
        store=trial_checkpoints.Store(self.fixture.root/'native-trials.sqlite');self.addCleanup(store.close)
        experiment=store.open(binding)
        pool=TrialPool(source_root=ROOT,scratch=self.fixture.root/'pool',reference=self.inputs.worker_reference(),
            source_identity=numerical_random.source_identity(),compiler_identity=expected,policy=policy)
        self.addCleanup(pool.close);captured=[]
        with self.fixture.owner.hold():
            actual=numerical_random.run(workspace,config,experiment,execution=lambda:pool,binding=binding,
                capture=lambda number,result:captured.append(result))['result']
        self.assertEqual(actual['completed'],3)
        for spec,result in zip((numerical_trial.specification(binding,n) for n in (1,2,3)),captured,strict=True):
            self.assertTrue(compare_results(self.fixture.s.backtest_dates(self.fixture.db,**spec['request'],**spec['options']),result)['exact'])
        self.assertEqual(pool.stats['started_workers'],2)
        reused=[r['measurements']['provider']['native_build']['build_reused'] for r in pool.stats['readiness']]
        self.assertTrue(all(type(value) is bool for value in reused))
        self.assertEqual(reused[1:],[True])
        pool.close();self.assertTrue(pool.closure()['closed']);self.assertFalse(pool.scratch.exists())
        configuration=dict(threads=1,generation_path=str(self.fixture.store.path),checkpoint_path=str(store.path),
            source_root=str(ROOT),scratch=str(self.fixture.root/'session'),execution=dict(backend='rust',workers=2,
                threads_per_worker=1,lane_budget=2,artifact_bytes=8*1024**2,piece_bytes=127,record_bytes=16384))
        with patch.object(numerical_session,'GenerationStore',return_value=self.fixture.store), \
             patch.object(rust,'_build',side_effect=AssertionError('No provider compilation on recovery')):
            began=time.perf_counter();session=numerical_session.Session(configuration)
            recovery_identity_seconds=time.perf_counter()-began
            try:
                with patch.object(session,'pool',side_effect=AssertionError('No workers on full recovery')):
                    began=time.perf_counter()
                    recovered=session.calculate('random',dict(start=config['start'],end=config['end'],months=config['months'],
                        trials=3,seed=42,**config['options']),None,lambda value:None,planned=config)
                recovery_seconds=time.perf_counter()-began
                self.assertEqual(recovered['execution']['recovered_trials'],3)
                print(json.dumps(dict(check='native-recovery-without-compilation',compiler_identity_probe_seconds=compiler_probe_seconds,
                    recovery_session_identity_seconds=recovery_identity_seconds,recovery_request_seconds=recovery_seconds,
                    provider_builds=0,workers=0,trials=3,scope='fictional correctness fixture; warm compiler/build files; no performance qualification')),flush=True)
                self.assertIsNone(session.provider);self.assertIsNone(session.trial_pool)
            finally:session.close()
        workspace.close();self.inputs.close()
        generation=self.fixture.store.path/self.fixture.store._pointer()['current']
        moved=generation.with_name(generation.name+'-released');generation.rename(moved);moved.rename(generation)
