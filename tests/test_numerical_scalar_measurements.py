"""Finite private synthetic qualification workloads, selected explicitly.

Receipts print after fixture closure. Whole-call clocks include Selectable
admission/readiness, Candidate startup, work, transfer and confirmed retirement.
Preparation, evaluator-only work, comparison and exports have separate clocks.
Memory samples are per-process high water/current samples, never aggregate peaks.
"""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import io
import json
import os
import subprocess
import time
import unittest

from backtest.application import scalar_execution,strategy_requests
from backtest.engines.numerical import formulas
from backtest.variables import library,definitions,reference
from backtest.runtime import backtest_control
from guarded_numerical_entries import install
from scalar_qualification import (Scenario,program,compare_artifacts,compare_blocks,
    receipt_environment,digest)

ROOT=Path(__file__).resolve().parents[1]


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        if sys.platform=='win32':
            before,original_null=subprocess.Popen,os.devnull
            install(ROOT)
            self.addCleanup(setattr,subprocess,'Popen',before)
            self.addCleanup(setattr,os,'devnull',original_null)
        self.receipt=dict(environment=receipt_environment(),memory_scope=
            'Current/high-water samples belong to each named process. Parent high water includes prior test work; samples are not an aggregate peak.')

    def emit(self,name):
        print('SCALAR_QUALIFICATION_RECEIPT '+json.dumps(dict(name=name,**self.receipt),sort_keys=True),flush=True)

    def scenario_receipt(self,scenario):
        return dict(companies=scenario.companies,first=scenario.first,last=scenario.last,
            input_sha256=scenario.input_sha256,input_files=len(scenario.raw_manifest),
            preparation_seconds=scenario.preparation_seconds,
            formula_program=scenario.capture.to_dict()['variables']['program'],
            generation=scenario.fixture.receipt['identity'],
            synthetic_preparation='Established private fixture report verifier; full execution compared independently afterwards',
            cache_state='Saved synthetic raw/prepared inputs; no installed/native market cache')

    def test_repeated_shared_formulas_multiple_chunks(self):
        with Scenario(companies=300,first=2015,last=2016) as scenario:
            self.receipt.update(scenario=self.scenario_receipt(scenario))
            capture=scenario.capture.to_dict()
            captured=library.VariableCapture(definitions.canonical(capture['variables'])).program
            roots=[dict(symbol=f'Q{i:04d}',pool='cached',mode='historical',date='2016-01-04') for i in range(300)]
            plans=scalar_execution._plans(captured,roots,8*1024**2,lambda:None)
            self.assertGreater(len(plans),1)
            timings=[]
            with scenario.fixture.store.open_current() as inputs,inputs.observations() as view,formulas.Evaluator() as evaluator:
                for repeat in range(3):
                    began=time.perf_counter();expected=[reference.evaluate(plan,view).to_dict() for plan in plans]
                    reference_seconds=time.perf_counter()-began
                    began=time.perf_counter();actual=[evaluator.evaluate(plan,view).to_dict() for plan in plans]
                    numerical_seconds=time.perf_counter()-began
                    compare_blocks(expected,actual)
                    timings.append(dict(repeat=repeat+1,reference_seconds=reference_seconds,numerical_seconds=numerical_seconds,
                        formula=dict(evaluator.stats)))
                self.assertEqual(evaluator.stats['kernel_compilations'],1)
                self.assertGreater(evaluator.stats['tape_hits'],0)
                self.receipt.update(evaluator_only=timings,requests=300,chunks=len(plans),
                    operations=sum(len(block['operations']) for block in actual),
                    ordered_roots=capture['variables']['program']['bundle']['roots'])
            options=scenario.options('custom')
            left,a,_=scenario.run_backend('original','custom',options)
            right,b,_=scenario.run_backend('experimental','custom',options)
            compared=compare_artifacts(left,right)
            self.assertGreater(compared['holdings'],0)
            self.receipt.update(complete_calls=[a,b],comparison=compared)
        self.emit('repeated-shared-300')

    def test_long_window_complete_application(self):
        with Scenario(companies=64,first=1996,last=2026,capture=program(shared=False)) as scenario:
            self.receipt.update(scenario=self.scenario_receipt(scenario))
            options=scenario.options('custom')
            left,a,_=scenario.run_backend('original','custom',options)
            right,b,_=scenario.run_backend('experimental','custom',options)
            comparison=compare_artifacts(left,right)
            self.assertEqual(comparison['periods'],31)
            self.assertGreater(comparison['holdings'],0)
            self.receipt.update(complete_calls=[a,b],comparison=comparison)
        self.emit('long-window-1996-2026-64')

    def test_seeded_random_interrupted_partial_and_complete_recovery(self):
        captured=program().to_dict();captured['selection']['rank_to']=50
        with Scenario(companies=64,first=2015,last=2019,workers=2,
                capture=strategy_requests.from_wire(captured)) as scenario:
            self.receipt.update(scenario=self.scenario_receipt(scenario))
            options=scenario.options('random')
            left,a,_=scenario.run_backend('original','random',options)
            plan=a['plan'];stop=[]
            def interrupt(event):
                if event and event.get('calculated_trials')==1:
                    stop.append(time.perf_counter());raise backtest_control.Cancelled()
            _,interrupted,_=scenario.run_backend('experimental','random',options,planned=plan,
                progress=interrupt,expected_cancel=True)
            self.assertEqual(len(stop),1)
            interrupted.update(cancellation_seconds=time.perf_counter()-stop[0],
                cancellation_stage='after one committed trial',stage_limit='Progress callback cancellation; earlier completed trial remains durable')
            right,b,bytes_b=scenario.run_backend('experimental','random',options,planned=plan)
            comparison=compare_artifacts(left,right)
            self.assertEqual(right.manifest['summary']['execution']['recovered_trials'],1)
            self.assertEqual(right.manifest['summary']['execution']['calculated_trials'],3)
            repeated,c,bytes_c=scenario.run_backend('experimental','random',options,planned=plan)
            self.assertEqual(repeated.manifest['summary']['execution']['recovered_trials'],4)
            self.assertEqual(repeated.manifest['summary']['execution']['calculated_trials'],0)
            self.assertEqual(repeated.manifest['summary']['execution']['workers'],0)
            self.assertIsNone(c['runtime']['trial_pool'])
            self.assertEqual(c['runtime']['provider_constructions'],0)
            compare_artifacts(right,repeated)
            # Framing includes current recovery diagnostics. Each completed
            # backend export nevertheless remains exactly its original bytes.
            from backtest.application import result_exports
            for reader,stream in ((right,bytes_b),(repeated,bytes_c)):
                export=result_exports.prepare(reader,'evidence')
                self.assertEqual(b''.join(export.chunks()),stream.getvalue())
            self.receipt.update(complete_calls=[a,interrupted,b,c],comparison=comparison,
                plan_sha256=digest(plan),recovery='One retained trial, three missing trials, then full evidence hit without workers/providers')
        self.emit('random-64-top50-four-trials-two-workers-recovery')

    def test_cancellation_during_compile_formula_and_evidence(self):
        with Scenario(companies=12,first=2015,last=2016) as scenario:
            self.receipt.update(scenario=self.scenario_receipt(scenario))
            cancelled=[]
            for stage in ('compile','formula','evidence'):
                receipt=scenario.cancel_at(stage)
                self.assertEqual(receipt['closure']['state'],'closed')
                self.assertTrue(receipt['cancelled'])
                if stage=='compile':self.assertTrue(receipt['probe']['kernel_returned'])
                elif stage=='formula':self.assertGreater(receipt['probe']['native_chunks'],0)
                cancelled.append(receipt)
            self.receipt.update(cancellations=cancelled)
        self.emit('cancellation-compile-formula-evidence')


class RandomMeasurementTests(unittest.TestCase):
    """Select the distinct bounded native random workload in a fresh process."""
    setUp=MeasurementTests.setUp
    emit=MeasurementTests.emit
    scenario_receipt=MeasurementTests.scenario_receipt
    test_seeded_random_interrupted_partial_and_complete_recovery=MeasurementTests.test_seeded_random_interrupted_partial_and_complete_recovery


class RepeatedMeasurementTests(unittest.TestCase):
    setUp=MeasurementTests.setUp
    emit=MeasurementTests.emit
    scenario_receipt=MeasurementTests.scenario_receipt
    test_repeated_shared_formulas_multiple_chunks=MeasurementTests.test_repeated_shared_formulas_multiple_chunks


class LongWindowMeasurementTests(unittest.TestCase):
    setUp=MeasurementTests.setUp
    emit=MeasurementTests.emit
    scenario_receipt=MeasurementTests.scenario_receipt
    test_long_window_complete_application=MeasurementTests.test_long_window_complete_application


class CancellationMeasurementTests(unittest.TestCase):
    setUp=MeasurementTests.setUp
    emit=MeasurementTests.emit
    scenario_receipt=MeasurementTests.scenario_receipt
    test_cancellation_during_compile_formula_and_evidence=MeasurementTests.test_cancellation_during_compile_formula_and_evidence


def load_tests(loader,tests,pattern):
    return loader.loadTestsFromTestCase(MeasurementTests)


if __name__=='__main__':unittest.main()
