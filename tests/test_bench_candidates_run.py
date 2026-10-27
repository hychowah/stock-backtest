"""Complete portfolio parity and containment for the common candidate adapter."""
from contextlib import closing, ExitStack, nullcontext
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sqlite3
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import test_bench_methods as shared
from bench_candidates import NumericInputs, PythonExecutor
import bench_candidates_run as runner
from bench_candidates_process import OwnedProcess


def valid_resources():
    return dict(supported=True, samples=1, error=None,
                sampled_tree_peaks=dict(private_bytes=1024, working_set=2048))


def agreed_method(requests):
    return dict(status='complete', financial_agreement=True, process_exit_code=0,
        owned_descendants_closed=True, resources_closed=True, source_unchanged=True,
        setup=dict(wall_seconds=1., resources=valid_resources()),
        intermediate_proof=dict(comparison=dict(exact=True)),
        cases=[dict(id=case['id'],kind=case['kind'],status='matched',
            comparison=dict(exact=True),summary_comparison=dict(exact=True),
            replay_comparison=dict(exact=True),
            measurement=dict(wall_seconds=1.,resources=valid_resources())) for case in requests])


class SourceInventoryTests(unittest.TestCase):
    def test_extracted_policy_mutation_rejects_before_database_or_executor_access(self):
        for relative in ('tools/bench_policy_program.py', 'scripts/numerical_policy.py', 'scripts/numerical_decisions.py', 'scripts/numerical_temporal.py', 'scripts/numerical_generation.py'):
            with self.subTest(implementation=relative): self.check_mutation(relative)

    def check_mutation(self, relative):
        with tempfile.TemporaryDirectory(prefix='cb02-policy-source-') as temporary:
            root = Path(temporary)
            tools = root / 'tools'; tools.mkdir()
            for name in ('bench_methods_arrays.py', 'bench_generation.py', 'bench_policy_program.py'):
                shutil.copy2(ROOT / 'tools' / name, tools / name)
            scripts = root / 'scripts'; scripts.mkdir()
            for name in ('numerical_policy.py', 'numerical_decisions.py', 'numerical_temporal.py', 'numerical_generation.py'):
                shutil.copy2(ROOT / 'scripts' / name, scripts / name)
            implementation = root / relative
            with patch.object(runner, 'ROOT', root):
                files = runner.source_files()
                self.assertIn(implementation, files)
                frozen = runner.hashes(files)
                specification = root / 'specification.json'
                shared.baseline.publish(specification, dict(staging='all', candidate_assembly='source',
                    source_hashes=frozen))
                implementation.write_bytes(implementation.read_bytes() + b'\n# owned mutation\n')
                changed = runner.hashes(runner.source_files())
                self.assertEqual(set(changed), set(frozen))
                self.assertEqual({name for name in changed if changed[name] != frozen[name]},
                                 {implementation.name})
                args = SimpleNamespace(worker='python', runtime=root, workdir=root,
                    specification=specification, result=root / 'result.json', staging='all',
                    candidate_assembly='source')
                with patch.object(runner.admission, 'require_execution'), \
                     patch.object(runner.sys, 'stdin', io.StringIO('GO\n')), \
                     patch.dict(os.environ), patch.object(runner.baseline, 'bootstrap'), \
                     patch.object(runner, 'emit'), \
                     patch.object(runner.sqlite3, 'connect', side_effect=AssertionError('Database accessed')) as connect, \
                     patch('bench_candidates.NumericInputs', side_effect=AssertionError('Inputs constructed')) as inputs, \
                     patch('bench_candidates.PythonExecutor', side_effect=AssertionError('Executor constructed')) as executor:
                    with self.assertRaisesRegex(ValueError, 'Candidate source changed before attachment'):
                        runner.worker(args)
                connect.assert_not_called()
                inputs.assert_not_called()
                executor.assert_not_called()
                self.assertFalse(args.result.exists())


class CandidateRequestTests(unittest.TestCase):
    def setUp(self):
        self.fixture=shared.SharedMethodsTests('test_empty_trials_remain_visible_and_excluded_from_distributions')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.inputs=NumericInputs(self.fixture.reader,shared.s)
        self.addCleanup(self.inputs.close)
        self.executor=PythonExecutor(self.inputs,limits=dict(capture=False))
        self.addCleanup(self.executor.close)

    def test_batched_requests_preserve_complete_source_evidence_and_replay(self):
        for pool in ('legacy','cached'):
            for profile in ('F0','F1','F2'):
                for metric in shared.s.metrics.METRICS:
                    config=self.fixture.configuration(pool,profile,metric=metric)
                    reference,summary=self.fixture.reference(config)
                    counts={}
                    for staging in runner.STAGING:
                        with self.subTest(pool=pool,profile=profile,metric=metric,staging=staging):
                            path=self.fixture.root/f'{pool}-{profile}-{metric}-{staging}.sqlite'
                            freshness=Mock()
                            actual=dict.fromkeys(('snapshots','screening_metrics','filter_values'),0)
                            original=runner.stage_book
                            def observed(db,book,pool,**kwargs):
                                result=original(db,book,pool,**kwargs)
                                for table in actual:
                                    actual[table]+=db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                                return result
                            with patch.object(runner,'stage_book',side_effect=observed), \
                                    patch.object(self.executor,'evaluate',wraps=self.executor.evaluate) as evaluate:
                                measured,picks=runner.run_candidate(self.inputs,self.executor,config,
                                    self.fixture.reader,path,freshness=freshness,budget_seconds=10.,staging=staging)
                            freshness.assert_called_once_with()
                            self.assertTrue(shared.baseline.compare(reference,picks)['exact'])
                            self.assertTrue(shared.baseline.compare(summary,measured['summary'])['exact'])
                            self.assertTrue(shared.baseline.compare(picks,shared.methods.replay(path))['exact'])
                            self.assertEqual(measured['committed_trials'],3)
                            self.assertTrue(any(len(call.args[0])>1 for call in evaluate.call_args_list))
                            self.assertEqual(measured['staging'],staging)
                            self.assertEqual(measured['staged_rows'],actual)
                            self.assertGreater(actual['snapshots'],0)
                            self.assertEqual(actual['filter_values']>0,profile!='F0')
                            with closing(sqlite3.connect(path)) as store:
                                binding=json.loads(store.execute('SELECT value FROM binding').fetchone()[0])
                            self.assertEqual(binding['identity']['staging'],staging)
                            counts[staging]=actual
                    self.assertEqual(counts['all']['snapshots'],counts['requested']['snapshots'])
                    self.assertEqual(counts['all']['filter_values'],counts['requested']['filter_values'])
                    self.assertGreater(counts['all']['screening_metrics'],counts['requested']['screening_metrics'])

    def test_interruption_keeps_only_completed_trials_and_fresh_retry_works(self):
        config=self.fixture.configuration()
        reference,_=self.fixture.reference(config)
        def stop(event):
            if event['completed']==1:
                raise RuntimeError('Stop after one durable trial')
        for staging in runner.STAGING:
            path=self.fixture.root/f'batch-interrupted-{staging}.sqlite'
            with self.assertRaisesRegex(RuntimeError,'one durable trial'):
                runner.run_candidate(self.inputs,self.executor,config,self.fixture.reader,path,
                    freshness=lambda:None,budget_seconds=10.,progress=stop,staging=staging)
            self.assertTrue(shared.baseline.compare(reference[:1],shared.methods.replay(path))['exact'])
            self.assertEqual(self.executor.last_request['committed_trials'],1)
            self.assertEqual(self.executor.last_request['staging'],staging)
            self.assertGreater(self.executor.last_request['staged_rows']['snapshots'],0)
            _,retry=runner.run_candidate(self.inputs,self.executor,config,self.fixture.reader,
                self.fixture.root/f'batch-retry-{staging}.sqlite',freshness=lambda:None,
                budget_seconds=10.,staging=staging)
            self.assertTrue(shared.baseline.compare(reference,retry)['exact'])

    def test_real_filter_fixture_definitions_are_separate_from_primary_manifest(self):
        records=runner.smoke_requests(self.fixture.db,end='2016-12-30')
        self.assertEqual(len(records),6)
        self.assertEqual({row['configuration']['options']['pool'] for row in records},{'legacy','cached'})
        self.assertTrue(all(row['configuration']['requested']==2 for row in records))
        mixed=[row for row in records if row['id'].endswith('mixed')]
        self.assertTrue(all(row['configuration']['options']['metric']=='ev_ebitda_3y' for row in mixed))

    def test_existing_result_store_is_preserved_on_rejected_fresh_request(self):
        config=self.fixture.configuration()
        path=self.fixture.root/'existing.sqlite'
        path.write_bytes(b'preserve existing evidence')
        with self.assertRaisesRegex(ValueError,'new result store'):
            runner.run_candidate(self.inputs,self.executor,config,self.fixture.reader,path,
                freshness=lambda:None,budget_seconds=10.)
        self.assertEqual(path.read_bytes(),b'preserve existing evidence')

    def test_staging_projection_preserves_selection_missing_pairs_and_complete_books(self):
        for pool in ('legacy','cached'):
            self.executor.begin(dict(options=shared.baseline.options(pool,'F0')))
            original=self.executor.evaluate([('2015-01-02','2016-01-04',pool)],
                shared.baseline.options(pool,'F0'))[0]
            for metric in shared.s.metrics.METRICS:
                for missing in ('none','one','all'):
                    book=deepcopy(original)
                    if missing!='none':
                        book['metrics']=[row for row in book['metrics']
                            if not (row[1]==metric and (missing=='all' or row[0]=='A'))]
                    preserved=deepcopy(book)
                    with closing(runner.memory_workspace(self.fixture.reader,shared.s)) as complete, \
                            closing(runner.memory_workspace(self.fixture.reader,shared.s)) as projected:
                        for db in (complete,projected):
                            db.execute("UPDATE companies SET sector='Technology',exchange='Nasdaq' WHERE symbol='A'")
                        counts=dict.fromkeys(('snapshots','screening_metrics','filter_values'),0)
                        self.assertEqual(runner.stage_book(complete,book,pool),1)
                        self.assertEqual(runner.stage_book(projected,book,pool,
                            ranking_metric=metric,staged_rows=counts),1)
                        for table,count in counts.items():
                            self.assertEqual(count,projected.execute('SELECT COUNT(*) FROM '+table).fetchone()[0])
                        self.assertEqual(counts['snapshots'],len(book['snapshots']))
                        self.assertEqual(counts['screening_metrics'],sum(row[1]==metric for row in book['metrics']))
                        changes=({},dict(rank_from=2,rank_to=3),dict(min_cap=130e6,max_cap=180e6),
                            dict(min_ev=150e6,min_yield=.1,max_multiple=10.),
                            dict(sector='Technology',exchange='Nasdaq'),dict(sector='__MISSING__'),
                            dict(rank_from=100,rank_to=110),dict(min_cap=1e100))
                        for extra in changes:
                            options=dict(dict(period=(1,1),pool=pool,metric=metric,min_cap=0.,min_ev=0.),**extra)
                            selected=shared.s.r._select(complete,**options)
                            self.assertEqual(selected,shared.s.r._select(projected,**options))
                            if missing=='all':self.assertEqual(selected,[])
                            if missing=='one':self.assertNotIn('A',{row['symbol'] for row in selected})
                        self.assertEqual(book,preserved)
                        runner.stage_book(projected,book,pool,ranking_metric='invalid')
                        with self.assertRaisesRegex(ValueError,'valid ranking metric'):
                            shared.s.r._select(projected,period=(1,1),metric='invalid')

    def test_projection_does_not_hide_malformed_pairs_or_changed_book_identity(self):
        self.executor.begin(dict(options=shared.baseline.options('legacy','F0')))
        book=self.executor.evaluate([('2015-01-02','2016-01-04','legacy')])[0]
        book['metrics'].append(('A','unused',1.))
        with closing(runner.memory_workspace(self.fixture.reader,shared.s)) as db:
            for metric in (None,'ev_ebitda'):
                with self.assertRaises(ValueError):
                    runner.stage_book(db,book,'legacy',ranking_metric=metric)
        evaluate=self.executor.evaluate
        def changed(*args,**kwargs):
            books=evaluate(*args,**kwargs)
            books[0]['pool']='changed'
            return books
        for staging in runner.STAGING:
            with patch.object(self.executor,'evaluate',side_effect=changed):
                with self.assertRaisesRegex(ValueError,'book identity'):
                    runner.run_candidate(self.inputs,self.executor,self.fixture.configuration(),
                        self.fixture.reader,self.fixture.root/f'changed-{staging}.sqlite',
                        freshness=lambda:None,budget_seconds=10.,staging=staging)

    def test_request_default_is_complete_and_invalid_variant_fails(self):
        self.assertEqual(runner.parser().parse_args(['--runtime','runtime','--workdir','work']).staging,'all')
        for staging in runner.STAGING:
            self.assertEqual(runner.parser().parse_args([
                '--runtime','runtime','--workdir','work','--staging',staging]).staging,staging)
        config=self.fixture.configuration()
        measured,_=runner.run_candidate(self.inputs,self.executor,config,self.fixture.reader,
            self.fixture.root/'default-staging.sqlite',freshness=lambda:None,budget_seconds=10.)
        self.assertEqual(measured['staging'],'all')
        with self.assertRaisesRegex(ValueError,'all or requested'):
            runner.run_candidate(self.inputs,self.executor,config,self.fixture.reader,
                self.fixture.root/'invalid-staging.sqlite',freshness=lambda:None,
                budget_seconds=10.,staging='invalid')

    def test_worker_uses_frozen_staging_in_report_and_durable_binding(self):
        config=self.fixture.configuration('cached','F2',metric='ev_ebitda_3y')
        reference,summary=self.fixture.reference(config)
        runtime=self.fixture.root/'runtime'
        (runtime/'data').mkdir(parents=True)
        shutil.copyfile(self.fixture.path,runtime/'data/schedules.sqlite')
        for staging in runner.STAGING:
            workdir=self.fixture.root/('worker-'+staging)
            workdir.mkdir()
            reference_file=workdir/'reference.json'
            shared.baseline.publish(reference_file,reference)
            specification=workdir/'specification.json'
            shared.baseline.publish(specification,dict(staging=staging,candidate_assembly='source',
                source_hashes=runner.hashes(runner.source_files()),input_identity_sha256='fixture',
                setup_budget=600.,request_budget=10.,smoke_budget=10.,requests=[dict(id='fixture',kind='untimed_correctness',
                    configuration=config,evidence_file=str(reference_file),summary=summary)]))
            args=SimpleNamespace(worker='python',runtime=runtime,workdir=workdir,
                specification=specification,result=workdir/'result.json',staging=staging,candidate_assembly='source')
            with patch.object(runner.sys,'stdin',io.StringIO('GO\n')), \
                    patch.dict(os.environ),patch.object(runner.baseline,'bootstrap'), \
                    patch.object(runner,'intermediate_proof',return_value=dict(comparison=dict(exact=True))), \
                    patch.object(runner,'emit'):
                runner.worker(args)
            report=shared.baseline.load(args.result)
            self.assertEqual(report['status'],'complete')
            self.assertTrue(report['financial_agreement'])
            self.assertEqual(report['staging'],staging)
            self.assertEqual(report['candidate_assembly'],'source')
            case=report['cases'][0]
            self.assertEqual(case['staging'],staging)
            self.assertEqual(case['correctness']['staging'],staging)
            self.assertGreater(case['correctness']['staged_rows']['snapshots'],0)
            with closing(sqlite3.connect(workdir/case['result_store_file'])) as store:
                identity=json.loads(store.execute('SELECT value FROM binding').fetchone()[0])['identity']
            self.assertEqual(identity['staging'],staging)
            self.assertEqual(identity['candidate_assembly'],'source')
            self.assertTrue(case['comparison']['exact'])
            self.assertTrue(case['summary_comparison']['exact'])
            self.assertTrue(case['replay_comparison']['exact'])

    def test_parent_freezes_variant_before_launch_and_records_it(self):
        config=self.fixture.configuration()
        reference,summary=self.fixture.reference(config)
        case=dict(id='fixture')
        def connect(*args,**kwargs):
            db=sqlite3.connect(self.fixture.path)
            db.row_factory=sqlite3.Row
            return db
        for staging,assembly in (('all','source'),('requested','source'),('all','compiled')):
            args=runner.parser().parse_args(['--runtime',str(self.fixture.root),
                '--workdir',str(self.fixture.root/('parent-'+staging+'-'+assembly)),
                '--methods','numba','--staging',staging,'--candidate-assembly',assembly,'--case','fixture'])
            def isolated(arguments,method,specification,result):
                frozen=shared.baseline.load(specification)
                self.assertEqual(frozen['staging'],staging)
                self.assertEqual(arguments.staging,staging)
                self.assertEqual(frozen['candidate_assembly'],assembly)
                self.assertEqual(arguments.candidate_assembly,assembly)
                self.assertEqual(frozen['setup_budget'],arguments.setup_budget)
                return dict(agreed_method(frozen['requests']),staging=staging,candidate_assembly=assembly)
            with ExitStack() as stack:
                stack.enter_context(patch.object(runner,'os',SimpleNamespace(name='nt',environ=os.environ)))
                stack.enter_context(patch.dict(os.environ))
                stack.enter_context(patch.object(runner.baseline,'bootstrap'))
                stack.enter_context(patch.object(runner.baseline,'assert_workdir'))
                stack.enter_context(patch.object(runner.baseline,'load',wraps=shared.baseline.load))
                stack.enter_context(patch.object(runner.baseline,'validate_manifest'))
                stack.enter_context(patch.object(runner.baseline,'identity',return_value=dict(fixture=True)))
                stack.enter_context(patch.object(runner.baseline,'configuration',return_value=config))
                stack.enter_context(patch.object(runner.baseline,'request',return_value=(
                    dict(summary=summary,wall_seconds=2.),reference)))
                stack.enter_context(patch.object(runner.baseline.coordinator,'access',return_value=nullcontext()))
                stack.enter_context(patch.object(shared.s.r,'connect',side_effect=connect))
                stack.enter_context(patch.object(shared.s,'connect',side_effect=connect))
                stack.enter_context(patch.object(runner,'smoke_requests',return_value=[]))
                stack.enter_context(patch.object(runner,'reference_smokes',return_value=[]))
                stack.enter_context(patch.object(runner,'run_isolated',side_effect=isolated))
                stack.enter_context(patch.object(runner,'emit'))
                args.manifest=self.fixture.root/'manifest.json'
                shared.baseline.publish(args.manifest,dict(primary_cases=[case],sha256='fixture'))
                runner.parent(args)
            report=shared.baseline.load(args.workdir/'comparison.json')
            self.assertEqual(report['staging'],staging)
            self.assertEqual(report['runs'][0]['staging'],staging)
            self.assertEqual(report['candidate_assembly'],assembly)
            self.assertEqual(report['runs'][0]['candidate_assembly'],assembly)


class TerminalEvidenceTests(unittest.TestCase):
    setUp = CandidateRequestTests.setUp

    def worker_case(self, label, *, kind='untimed_correctness', setup_budget=600.):
        config = self.fixture.configuration('cached','F2')
        reference, summary = self.fixture.reference(config)
        runtime = self.fixture.root / ('runtime-'+label)
        (runtime/'data').mkdir(parents=True)
        shutil.copyfile(self.fixture.path,runtime/'data/schedules.sqlite')
        workdir = self.fixture.root / ('worker-'+label); workdir.mkdir()
        evidence = workdir/'reference.json'; shared.baseline.publish(evidence,reference)
        requests = [dict(id=label+'-'+str(i),kind=kind,configuration=config,
                         evidence_file=str(evidence),summary=summary) for i in range(2)]
        specification = workdir/'specification.json'
        shared.baseline.publish(specification,dict(staging='all',candidate_assembly='source',
            source_hashes=runner.hashes(runner.source_files()),input_identity_sha256='fixture',
            setup_budget=setup_budget,request_budget=10.,smoke_budget=10.,requests=requests))
        args = SimpleNamespace(worker='python',runtime=runtime,workdir=workdir,
            specification=specification,result=workdir/'result.json',staging='all',candidate_assembly='source')
        return args, reference

    def worker_context(self):
        stack = ExitStack()
        stack.enter_context(patch.object(runner.sys,'stdin',io.StringIO('GO\n')))
        stack.enter_context(patch.dict(os.environ))
        stack.enter_context(patch.object(runner.baseline,'bootstrap'))
        return stack

    def assert_worker_stopped(self, args, expected_cases):
        report = shared.baseline.load(args.result)
        self.assertEqual(report['status'],'failed')
        self.assertFalse(report['financial_agreement'])
        self.assertTrue(report['resources_closed'])
        self.assertTrue(report['source_unchanged'])
        self.assertEqual(len(report['cases']),expected_cases)
        return report

    def test_failed_proof_stops_before_requests_and_preserves_comparison(self):
        for label, proof in (('returned',dict(comparison=dict(exact=False,maximum_absolute=1e-15))),
                             ('raised',ValueError('Proof failed'))):
            with self.subTest(label=label):
                args,_ = self.worker_case('proof-'+label)
                kwargs = dict(side_effect=proof) if isinstance(proof,Exception) else dict(return_value=proof)
                with self.worker_context(), patch.object(runner,'intermediate_proof',**kwargs), \
                        patch.object(runner,'run_candidate') as request, patch.object(runner,'emit'), \
                        patch.object(PythonExecutor,'close',autospec=True,side_effect=PythonExecutor.close) as close:
                    runner.worker(args)
                request.assert_not_called(); close.assert_called_once()
                report = self.assert_worker_stopped(args,0)
                self.assertEqual(report['intermediate_proof']['status'],'failed')
                if label=='returned':
                    self.assertEqual(report['intermediate_proof']['comparison'],proof['comparison'])

    def test_unagreed_holdings_summary_or_replay_is_terminal_with_completed_evidence(self):
        original_compare = shared.baseline.compare
        for label, target in (('holdings',1),('summary',2),('replay',3),('exception',1)):
            with self.subTest(label=label):
                args, reference = self.worker_case(label)
                comparisons = 0
                def compare(*values):
                    nonlocal comparisons
                    comparisons += 1
                    result = original_compare(*values)
                    if comparisons==target:
                        if label=='exception':raise ValueError('Synthetic comparison failure')
                        result.update(exact=False,maximum_absolute=1e-15)
                    return result
                with self.worker_context(), patch.object(runner,'intermediate_proof',return_value=dict(comparison=dict(exact=True))), \
                        patch.object(runner,'run_candidate',wraps=runner.run_candidate) as request, \
                        patch.object(runner.baseline,'compare',side_effect=compare), patch.object(runner,'emit'):
                    runner.worker(args)
                request.assert_called_once()
                report = self.assert_worker_stopped(args,1)
                case = report['cases'][0]
                self.assertEqual(case['status'],'failed')
                self.assertEqual(case['committed_trials'],3)
                self.assertTrue(case['partial_comparison']['exact'])
                self.assertTrue(original_compare(reference,shared.baseline.load(args.workdir/case['evidence_file']))['exact'])
                self.assertTrue(original_compare(reference,shared.methods.replay(args.workdir/case['result_store_file']))['exact'])
                if label!='exception':
                    field = dict(holdings='comparison',summary='summary_comparison',replay='replay_comparison')[label]
                    self.assertFalse(case[field]['exact'])
                    self.assertEqual(case[field]['maximum_absolute'],1e-15)

    def test_request_exception_retains_committed_prefix_and_closes_every_connection(self):
        args, reference = self.worker_case('interrupted')
        original_run = runner.run_candidate
        original_connect = sqlite3.connect
        connections = []
        def connect(*values,**kwargs):
            db = original_connect(*values,**kwargs);connections.append(db);return db
        def interrupted(*values,**kwargs):
            def stop(event):
                if event['completed']==1:raise RuntimeError('Stop after durable trial')
            kwargs['progress'] = stop
            return original_run(*values,**kwargs)
        with self.worker_context(), patch.object(runner,'intermediate_proof',return_value=dict(comparison=dict(exact=True))), \
                patch.object(runner,'run_candidate',side_effect=interrupted) as request, \
                patch.object(sqlite3,'connect',side_effect=connect), patch.object(runner,'emit'), \
                patch.object(PythonExecutor,'close',autospec=True,side_effect=PythonExecutor.close) as executor_close, \
                patch.object(NumericInputs,'close',autospec=True,side_effect=NumericInputs.close) as inputs_close:
            runner.worker(args)
        request.assert_called_once();executor_close.assert_called_once();inputs_close.assert_called_once()
        for db in connections:
            with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')
        report = self.assert_worker_stopped(args,1)
        case = report['cases'][0]
        self.assertEqual(case['committed_trials'],1)
        self.assertTrue(case['partial_comparison']['exact'])
        self.assertTrue(shared.baseline.compare(reference[:1],shared.methods.replay(args.workdir/case['result_store_file']))['exact'])

    def test_invalid_setup_stops_before_proof_or_request(self):
        for label in ('time','memory','sampling','sampling-start'):
            with self.subTest(label=label):
                args,_ = self.worker_case('setup-'+label,setup_budget=1e-30 if label=='time' else 600.)
                resources = valid_resources()
                if label=='memory':resources['sampled_tree_peaks']['working_set'] = 2*1024**3+1
                if label=='sampling':resources['error'] = 'SyntheticSamplerFailure'
                sampler = Mock();sampler.finish.return_value = resources
                if label=='sampling-start':sampler.start.side_effect = OSError('Synthetic sampler start failure')
                with self.worker_context(), patch.object(runner.baseline,'Resources',return_value=sampler), \
                        patch.object(runner,'intermediate_proof') as proof, \
                        patch.object(runner,'run_candidate') as request,patch.object(runner,'emit'):
                    runner.worker(args)
                proof.assert_not_called();request.assert_not_called()
                self.assert_worker_stopped(args,0)

    def test_invalid_primary_stops_before_next_request_and_keeps_full_evidence(self):
        original_run = runner.run_candidate
        for label in ('time','memory','sampling'):
            with self.subTest(label=label):
                args, reference = self.worker_case('primary-'+label,kind='primary')
                def invalid(*values,**kwargs):
                    measured,picks = original_run(*values,**kwargs)
                    measured['resources'] = valid_resources()
                    if label=='time':measured['wall_seconds'] = 11.
                    if label=='memory':measured['resources']['sampled_tree_peaks']['private_bytes'] = 2*1024**3+1
                    if label=='sampling':measured['resources']['error'] = 'SyntheticSamplerFailure'
                    return measured,picks
                with self.worker_context(), patch.object(runner,'intermediate_proof',return_value=dict(comparison=dict(exact=True))), \
                        patch.object(runner,'run_candidate',side_effect=invalid) as request,patch.object(runner,'emit'), \
                        patch.object(shared.s,'connect',side_effect=lambda:sqlite3.connect(self.fixture.path)):
                    runner.worker(args)
                request.assert_called_once()
                report = self.assert_worker_stopped(args,1)
                case = report['cases'][0]
                self.assertEqual(case['committed_trials'],len(reference))
                self.assertTrue(case['partial_comparison']['exact'])
                self.assertIn('measurement',case)

    def test_cleanup_failure_still_closes_inputs_and_source_and_invalidates_report(self):
        args,_ = self.worker_case('closure')
        with self.worker_context(), patch.object(runner,'intermediate_proof',return_value=dict(comparison=dict(exact=False))), \
                patch.object(PythonExecutor,'close',side_effect=RuntimeError('Synthetic close failure')), \
                patch.object(NumericInputs,'close',autospec=True,side_effect=NumericInputs.close) as close,patch.object(runner,'emit'):
            runner.worker(args)
        close.assert_called_once()
        report = shared.baseline.load(args.result)
        self.assertEqual(report['status'],'failed')
        self.assertFalse(report['resources_closed'])
        self.assertEqual(report['closure_errors'][0]['error_type'],'RuntimeError')

    def test_parent_stops_invalid_child_before_any_following_control_or_method(self):
        config = self.fixture.configuration()
        reference,summary = self.fixture.reference(config)
        scenarios = ('failed','incomplete','unagreed','proof','holdings','summary','replay',
                     'missing-case','exit','descendants','closure','source','setup-time','primary-time',
                     'setup-memory','primary-memory','sampling','missing-samples',
                     'control-holdings','control-summary','input-drift','source-drift','method-raises')
        for label in scenarios:
            with self.subTest(label=label):
                args = runner.parser().parse_args(['--runtime',str(self.fixture.root),
                    '--workdir',str(self.fixture.root/('parent-stops-'+label)),
                    '--methods','python','numba','--case','fixture'])
                args.manifest = self.fixture.root/'manifest.json'
                shared.baseline.publish(args.manifest,dict(primary_cases=[dict(id='fixture')],sha256='fixture'))
                connections = []
                method_called = False
                def connect(*values,**kwargs):
                    db = sqlite3.connect(self.fixture.path);db.row_factory=sqlite3.Row
                    connections.append(db);return db
                def isolated(arguments,method,specification,result):
                    nonlocal method_called
                    method_called = True
                    if label=='method-raises':raise RuntimeError('Synthetic process closure failure')
                    report = agreed_method(shared.baseline.load(specification)['requests'])
                    case = report['cases'][0]
                    if label in ('failed','incomplete'):report['status'] = label
                    if label=='unagreed':report['financial_agreement'] = False
                    if label=='proof':report['intermediate_proof']['comparison']['exact'] = False
                    if label in ('holdings','summary','replay'):
                        case[dict(holdings='comparison',summary='summary_comparison',replay='replay_comparison')[label]]['exact'] = False
                    if label=='missing-case':report['cases'] = []
                    if label=='exit':report['process_exit_code'] = 1
                    if label=='descendants':report['owned_descendants_closed'] = False
                    if label=='closure':report['resources_closed'] = False
                    if label=='source':report['source_unchanged'] = False
                    measured = report['setup'] if label.startswith('setup-') else case['measurement']
                    if label.endswith('-time'):measured['wall_seconds'] = 10000.
                    if label.endswith('-memory'):measured['resources']['sampled_tree_peaks']['private_bytes'] = 2*1024**3+1
                    if label=='sampling':measured['resources']['error'] = 'SyntheticSamplerFailure'
                    if label=='missing-samples':measured['resources']['samples'] = 0
                    return report
                original_hashes = runner.hashes
                def hashes(files):
                    values = original_hashes(files)
                    if label=='source-drift' and method_called:values['changed'] = 'synthetic'
                    return values
                original_compare = shared.baseline.compare
                comparisons = 0
                def compare(*values):
                    nonlocal comparisons
                    comparisons += 1
                    result = original_compare(*values)
                    if ((label=='control-holdings' and comparisons==1)
                            or (label=='control-summary' and comparisons==2)):
                        result['exact'] = False
                    return result
                with ExitStack() as stack:
                    stack.enter_context(patch.object(runner,'os',SimpleNamespace(name='nt',environ=os.environ)))
                    stack.enter_context(patch.dict(os.environ))
                    for name in ('bootstrap','assert_workdir','validate_manifest'):
                        stack.enter_context(patch.object(runner.baseline,name))
                    stack.enter_context(patch.object(runner.baseline,'identity',side_effect=lambda unused:
                        dict(fixture=not (label=='input-drift' and method_called))))
                    stack.enter_context(patch.object(runner,'hashes',side_effect=hashes))
                    stack.enter_context(patch.object(runner.baseline,'compare',side_effect=compare))
                    stack.enter_context(patch.object(runner.baseline,'configuration',return_value=config))
                    controls = stack.enter_context(patch.object(runner.baseline,'request',return_value=(dict(summary=summary,wall_seconds=2.),reference)))
                    stack.enter_context(patch.object(runner.baseline.coordinator,'access',return_value=nullcontext()))
                    stack.enter_context(patch.object(shared.s.r,'connect',side_effect=connect))
                    stack.enter_context(patch.object(shared.s,'connect',side_effect=connect))
                    stack.enter_context(patch.object(runner,'smoke_requests',return_value=[]))
                    stack.enter_context(patch.object(runner,'reference_smokes',return_value=[]))
                    methods = stack.enter_context(patch.object(runner,'run_isolated',side_effect=isolated))
                    stack.enter_context(patch.object(runner,'emit'))
                    with self.assertRaises((ValueError,RuntimeError)):runner.parent(args)
                methods.assert_called_once()
                self.assertEqual(controls.call_count,2 if label.startswith('control-') else 1)
                report = shared.baseline.load(args.workdir/'comparison.json')
                self.assertEqual(report['status'],'stopped')
                self.assertEqual(len(report['runs']),0 if label=='method-raises' else 1)
                self.assertEqual(len(report['controls']),controls.call_count)
                self.assertEqual(report['source_unchanged'],label!='source-drift')
                self.assertEqual(report['production_unchanged'],label!='input-drift')
                self.assertTrue(report['source_closed'])
                for db in connections:
                    with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')


class PlannedCandidateRequestTests(CandidateRequestTests):
    def setUp(self):
        super().setUp()
        self.executor.limits['request_plan'] = True

    def test_rank_slice_three_year_and_empty_requests_preserve_source_and_replay(self):
        for pool in ('legacy', 'cached'):
            for label, changes in (('slice', dict(rank_from=2, rank_to=100, metric='ev_ebitda_3y')),
                                   ('metadata', dict(sector='Energy',exchange='NYSE',
                                       max_cap=180e6,min_ev=100e6,max_multiple=10.,min_yield=.1)),
                                   ('empty', dict(min_cap=1e100))):
                config = self.fixture.configuration(pool, **changes)
                reference, summary = self.fixture.reference(config)
                for staging in runner.STAGING:
                    path = self.fixture.root / (pool + '-' + label + '-' + staging + '.sqlite')
                    measured, picks = runner.run_candidate(self.inputs, self.executor,
                        config, self.fixture.reader, path, freshness=lambda: None,
                        budget_seconds=10.,staging=staging)
                    self.assertTrue(shared.baseline.compare(reference, picks)['exact'])
                    self.assertTrue(shared.baseline.compare(summary, measured['summary'])['exact'])
                    self.assertTrue(shared.baseline.compare(picks, shared.methods.replay(path))['exact'])

    def test_request_plan_keeps_repeated_books_and_omits_only_unused_lookups(self):
        config = self.fixture.configuration()
        config['samples'][1] = list(config['samples'][0])
        self.executor.begin(config)
        plan = self.executor.request_plan
        self.executor.evaluate(plan.books)
        self.assertGreater(len(plan.books), len(set(plan.books)))
        self.assertEqual(plan.slots, (0, 1, 3))
        self.assertEqual(self.executor.stats['planned_lookup_slots'], [0, 1, 3])
        self.assertLessEqual(self.executor.stats['price_queries'],
                             self.executor.stats['candidate_rows'] * 4)

    def test_extended_real_checks_keep_all_profiles_and_add_slice_and_empty(self):
        records = runner.smoke_requests(self.fixture.db, end='2016-12-30', extended=True)
        self.assertEqual(len(records), 10)
        self.assertEqual(sum(row['id'].endswith('empty') for row in records), 2)
        self.assertEqual(sum(row['id'].endswith('rank-slice') for row in records), 2)

    def test_lookup_requirements_follow_the_policy_expression_dependencies(self):
        options = dict(shared.baseline.options('legacy', 'F0'),
                       filters=[dict(field='pe', op='gt', value=0.)])
        with patch.dict(self.inputs.policy.expression_map,
                        filter_pe=('input', 'trailing_3y')):
            self.executor.begin(dict(options=options))
            self.assertIn(6, self.executor.request_plan.slots)
        options['filters'] = [dict(field='return_1y', op='gt', value=0.)]
        with patch.dict(self.inputs.policy.expression_map,
                        filter_return_1y=('const', 2.)):
            self.executor.begin(dict(options=options))
            self.assertEqual(self.executor.request_plan.slots, (0, 1, 3))


class CompiledCandidateRequestTests(unittest.TestCase):
    def setUp(self):
        from bench_candidates_numba import NumbaExecutor
        self.fixture = shared.SharedMethodsTests('test_empty_trials_remain_visible_and_excluded_from_distributions')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.inputs = NumericInputs(self.fixture.reader,shared.s)
        self.addCleanup(self.inputs.close)
        self.executor = NumbaExecutor(self.inputs,limits=dict(capture=False,request_plan=True,
                                                              candidate_assembly='compiled'))
        self.addCleanup(self.executor.close)

    def test_complete_requests_preserve_evidence_summaries_filters_and_replay(self):
        for pool in ('legacy','cached'):
            for profile in ('F0','F1','F2','all','slice','empty'):
                for metric in shared.s.metrics.METRICS:
                    extra = dict(metric=metric)
                    if profile == 'all':extra['filters'] = [dict(field=field,op='gt',value=-999999.) for field in shared.s.metrics.FILTERS]
                    if profile == 'slice':extra.update(rank_from=2,rank_to=100)
                    if profile == 'empty':extra['min_cap'] = 1e100
                    config = self.fixture.configuration(pool,profile if profile in ('F0','F1','F2') else 'F0',**extra)
                    reference,summary = self.fixture.reference(config)
                    path = self.fixture.root / f'compiled-{pool}-{profile}-{metric}.sqlite'
                    measured,picks = runner.run_candidate(self.inputs,self.executor,config,
                        self.fixture.reader,path,freshness=lambda:None,budget_seconds=10.,
                        candidate_assembly='compiled')
                    self.assertTrue(shared.baseline.compare(reference,picks)['exact'])
                    self.assertTrue(shared.baseline.compare(summary,measured['summary'])['exact'])
                    self.assertTrue(shared.baseline.compare(picks,shared.methods.replay(path))['exact'])
                    self.assertEqual(measured['candidate_assembly'],'compiled')
                    self.assertEqual(measured['staging'],'all')
                    with closing(sqlite3.connect(path)) as store:
                        identity = json.loads(store.execute('SELECT value FROM binding').fetchone()[0])['identity']
                    self.assertEqual(identity['candidate_assembly'],'compiled')
                    self.assertEqual(identity['staging'],'all')

    def test_interruption_retains_committed_trials_and_rejects_identity_mismatch(self):
        config = self.fixture.configuration('cached','F2')
        reference,_ = self.fixture.reference(config)
        path = self.fixture.root/'interrupted-compiled.sqlite'
        def stop(event):
            if event['completed'] == 1:raise RuntimeError('Stop after durable compiled trial')
        with self.assertRaisesRegex(RuntimeError,'durable compiled'):
            runner.run_candidate(self.inputs,self.executor,config,self.fixture.reader,path,
                freshness=lambda:None,budget_seconds=10.,progress=stop,candidate_assembly='compiled')
        self.assertTrue(shared.baseline.compare(reference[:1],shared.methods.replay(path))['exact'])
        self.assertEqual(self.executor.last_request['candidate_assembly'],'compiled')
        for assembly,staging,pattern in (('source','all','differs from attached'),
                                          ('compiled','requested','complete SQL staging')):
            rejected = self.fixture.root / (assembly+'-'+staging+'.sqlite')
            with self.assertRaisesRegex(ValueError,pattern):
                runner.run_candidate(self.inputs,self.executor,config,self.fixture.reader,rejected,
                    freshness=lambda:None,budget_seconds=10.,candidate_assembly=assembly,staging=staging)
            self.assertFalse(rejected.exists())
        _,retry = runner.run_candidate(self.inputs,self.executor,config,self.fixture.reader,
            self.fixture.root/'retry-compiled.sqlite',freshness=lambda:None,budget_seconds=10.,candidate_assembly='compiled')
        self.assertTrue(shared.baseline.compare(reference,retry)['exact'])

    def test_worker_requires_frozen_assembly_and_records_new_signatures(self):
        config = self.fixture.configuration('cached','F2')
        reference,summary = self.fixture.reference(config)
        runtime = self.fixture.root/'runtime'
        (runtime/'data').mkdir(parents=True)
        shutil.copyfile(self.fixture.path,runtime/'data/schedules.sqlite')
        workdir = self.fixture.root/'compiled-worker';workdir.mkdir()
        reference_file = workdir/'reference.json';shared.baseline.publish(reference_file,reference)
        specification = workdir/'specification.json'
        frozen = dict(staging='all',candidate_assembly='source',
            source_hashes=runner.hashes(runner.source_files()),input_identity_sha256='fixture',
            setup_budget=600.,request_budget=10.,smoke_budget=10.,requests=[dict(id='fixture',kind='untimed_correctness',
                configuration=config,evidence_file=str(reference_file),summary=summary)])
        shared.baseline.publish(specification,frozen)
        args = SimpleNamespace(worker='numba',runtime=runtime,workdir=workdir,
            specification=specification,result=workdir/'result.json',staging='all',candidate_assembly='compiled')
        def context():
            stack = ExitStack()
            stack.enter_context(patch.object(runner.sys,'stdin',io.StringIO('GO\n')))
            stack.enter_context(patch.dict(os.environ))
            stack.enter_context(patch.object(runner.baseline,'bootstrap'))
            stack.enter_context(patch.object(runner,'intermediate_proof',return_value=dict(comparison=dict(exact=True))))
            stack.enter_context(patch.object(runner,'emit'))
            return stack
        with context(),self.assertRaisesRegex(ValueError,'frozen specification'):runner.worker(args)
        frozen['candidate_assembly'] = 'compiled';shared.baseline.publish(specification,frozen)
        with context():runner.worker(args)
        report = shared.baseline.load(args.result)
        self.assertEqual(report['status'],'complete')
        self.assertEqual(report['candidate_assembly'],'compiled')
        self.assertTrue(report['setup']['executor']['nopython_signatures']['decisions'])
        case = report['cases'][0]
        self.assertEqual(case['correctness']['candidate_assembly'],'compiled')
        self.assertTrue(case['comparison']['exact'])
        self.assertTrue(case['summary_comparison']['exact'])
        self.assertTrue(case['replay_comparison']['exact'])
        with closing(sqlite3.connect(workdir/case['result_store_file'])) as store:
            identity = json.loads(store.execute('SELECT value FROM binding').fetchone()[0])['identity']
        self.assertEqual(identity['candidate_assembly'],'compiled')


class AssemblyVariantTests(unittest.TestCase):
    def test_default_and_unsupported_combinations_fail_closed(self):
        args = runner.parser().parse_args(['--runtime','runtime','--workdir','work'])
        self.assertEqual(args.candidate_assembly,'source')
        for methods,staging in ((['python'],'all'),(['numba','rust'],'all'),(['numba'],'requested')):
            with self.assertRaisesRegex(ValueError,'requires Numba and complete'):
                runner.validate_assembly('compiled',methods,staging)
        with self.assertRaisesRegex(ValueError,'source or compiled'):
            runner.validate_assembly('unknown',['numba'],'all')
        runner.validate_assembly('compiled',['numba'],'all')
        runner.validate_assembly('source',list(runner.METHODS),'requested')



class ProcessContainmentTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)

    def process(self,hang):
        script=self.root/'owned.py'
        database=self.root/'evidence.sqlite'
        script.write_text('''import json,sqlite3,subprocess,sys,time
print(json.dumps(dict(event='worker_ready')),flush=True)
assert input()=='GO'
db=sqlite3.connect(sys.argv[1])
db.execute('CREATE TABLE trials(number INTEGER PRIMARY KEY)')
db.execute('INSERT INTO trials VALUES(1)');db.commit();db.close()
if sys.argv[2]=='hang':
    child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
    print(json.dumps(dict(event='committed',child=child.pid)),flush=True)
    time.sleep(60)
else:
    print(json.dumps(dict(event='committed')),flush=True)
''')
        return OwnedProcess([sys.executable,str(script),str(database),'hang' if hang else 'exit']),database

    def wait_event(self,owned,name):
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            event=owned.event()
            if event and event.get('event')==name:
                return event
        self.fail('Owned child did not emit '+name)

    def test_owned_timeout_closes_descendants_and_preserves_committed_sqlite(self):
        owned,database=self.process(True)
        with owned:
            self.wait_event(owned,'worker_ready')
            owned.start()
            self.wait_event(owned,'committed')
            owned.terminate()
        self.assertIsNotNone(owned.process.returncode)
        with closing(sqlite3.connect(database)) as db:
            self.assertEqual(db.execute('SELECT * FROM trials').fetchall(),[(1,)])
            db.execute('INSERT INTO trials VALUES(2)');db.commit()

    def test_normal_completion_waits_for_owned_process_and_closes_pipes(self):
        owned,database=self.process(False)
        with owned:
            self.wait_event(owned,'worker_ready')
            owned.start()
            self.wait_event(owned,'committed')
        self.assertEqual(owned.process.returncode,0)
        self.assertTrue(owned.process.stdout.closed)

    def test_parent_hard_timeout_collects_committed_prefix_after_group_closure(self):
        case='legacy-F0-42'
        expected=[dict(value=1.)]
        reference=self.root/'reference.json';reference.write_text(json.dumps(expected))
        specification=self.root/'specification.json'
        specification.write_text(json.dumps(dict(staging='requested',requests=[dict(id=case,evidence_file=str(reference))])))
        result=self.root/'result.json'
        result.write_text(json.dumps(dict(method='python',cases=[dict(id=case,kind='primary',status='running')])))
        store=self.root/('python-'+case+'.sqlite')
        with closing(sqlite3.connect(store)) as db:
            db.execute('CREATE TABLE trials(number INTEGER PRIMARY KEY,evidence TEXT)')
            db.execute('INSERT INTO trials VALUES(1,?)',(json.dumps(expected[0]),));db.commit()
        class FakeOwned:
            def __init__(self,*args,**kwargs):
                self.process=SimpleNamespace(wait=lambda timeout:1)
                self.events=iter([dict(event='worker_ready'),dict(event='request_start',case=case,kind='primary')])
                self.closed=False
            def __enter__(self):return self
            def __exit__(self,*args):self.closed=True
            def event(self,timeout):return next(self.events,{})
            def start(self):pass
            def terminate(self):pass
        owned=FakeOwned()
        args=SimpleNamespace(runtime=self.root,workdir=self.root,setup_budget=1.,
                             request_budget=1.,smoke_budget=1.,staging='requested',candidate_assembly='source')
        with patch.object(runner.admission,'require_execution'), \
                patch('bench_candidates_process.OwnedProcess',return_value=owned) as spawn, \
                patch.object(runner.time,'monotonic',side_effect=[0.,0.,0.,0.,100.]):
            report=runner.run_isolated(args,'python',specification,result)
        command=spawn.call_args.args[0]
        self.assertEqual(command[command.index('--staging')+1],'requested')
        self.assertEqual(command[command.index('--candidate-assembly')+1],'source')
        self.assertTrue(owned.closed)
        self.assertEqual(report['status'],'incomplete')
        self.assertTrue(report['owned_descendants_closed'])
        self.assertEqual(report['cases'][0]['status'],'hard_timeout')
        self.assertEqual(report['cases'][0]['committed_trials'],1)
        self.assertTrue(report['cases'][0]['partial_comparison']['exact'])


if __name__=='__main__':
    unittest.main()
