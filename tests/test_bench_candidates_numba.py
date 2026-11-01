"""Differential source-policy proof with compiled reports, prices and factors."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
from contextlib import contextmanager
from datetime import date
import inspect
import unittest
from unittest.mock import patch

import numpy as np

import test_bench_candidates as source_tests
from backtest.engines.numerical.numba import NumbaExecutor


class NumbaCandidateTests(source_tests.CandidateTests):
    factory = NumbaExecutor

    def test_real_nopython_kernels_and_strict_arithmetic(self):
        inputs,executor = self.make()
        self.assertFalse(executor.stats['fastmath'])
        self.assertFalse(executor.stats['compiler_cache'])
        self.assertLessEqual(executor.stats['threads'],4)
        for name in ('reports','prices','factors'):
            self.assertTrue(executor.stats['nopython_signatures'][name])


class CompiledCandidateTests(NumbaCandidateTests):
    @staticmethod
    def factory(inputs, policy=None, limits=None):
        return NumbaExecutor(inputs,policy=policy,
            limits=dict(limits or {},candidate_assembly='compiled'))

    def test_decision_kernels_are_nopython_and_signature_is_warmed(self):
        inputs,executor = self.make()
        signature = inputs.policy.signature
        self.assertEqual(executor.compiler['fields']['candidate_decisions'],
                         inputs.policy.decisions.signature)
        self.assertEqual(inputs.policy.signature,signature)
        self.assertIs(inputs.policy.decisions,inputs.policy.decisions)
        signatures = tuple(executor._decide.nopython_signatures)
        for name in ('snapshot','eligible','current','three','decisions'):
            self.assertTrue(executor.stats['nopython_signatures'][name])
        executor.evaluate([('2015-01-02','2016-01-04','cached')],self.all_fields())
        executor.limits['request_plan'] = True
        executor.begin(dict(options=self.all_fields()))
        executor.evaluate([('2015-01-02','2016-01-04','legacy')])
        self.assertEqual(tuple(executor._decide.nopython_signatures),signatures)
        self.assertGreater(executor.stats['decision_seconds'],0.)
        self.assertGreaterEqual(executor.stats['assembly_seconds'],executor.stats['decision_seconds'])
        self.assertGreater(executor.stats['encoding_seconds'],0.)

    @contextmanager
    def mutation(self,module,name,old,new):
        original = getattr(module,name)
        source = inspect.getsource(original)
        self.assertIn(old,source)
        source = source.replace(old,new,1)
        path = self.root / ('mutated_'+name+'.py')
        path.write_text(source,encoding='utf-8')
        namespace = dict(original.__globals__)
        exec(compile(source,str(path),'exec'),namespace)
        with patch.object(module,name,namespace[name]):
            yield

    def test_supported_source_mutations_change_identity_and_complete_behavior(self):
        base_inputs,base = self.make()
        batch = [('2015-01-02','2016-01-04',pool) for pool in ('cached','legacy')]
        original = base.evaluate(batch,self.all_fields())
        mutations = (
            (source_tests.financial_books,'entry_valuation','ev<=0 or cap<=0','ev<=0 or cap<=160000000'),
            (source_tests.financial_books,'snapshot',"'Scheduled exit'","'Changed source exit'"),
            (source_tests.financial_books,'eligible','cap>0','cap>200000000'),
            (source_tests.metrics,'three_year_multiple','average<=0','average<=1000000000'))
        for module,name,old,new in mutations:
            with self.subTest(function=name,change=new),self.mutation(module,name,old,new):
                inputs,compiled = self.make()
                source = source_tests.core.PythonExecutor(inputs)
                self.addCleanup(source.close)
                expected = source.evaluate(batch,self.all_fields())
                actual = compiled.evaluate(batch,self.all_fields())
                self.assertNotEqual(inputs.policy.signature,base_inputs.policy.signature)
                self.assertNotEqual(original,actual)
                self.assertTrue(source_tests.baseline.compare(expected,actual)['exact'])

    def test_uncovered_source_structure_and_dependencies_fail_attachment(self):
        mutations = (
            ('    return [str(statement', '    for unexpected in (1,):\n        status="hidden"\n    return [str(statement'),
            ('if ev<=0 or cap<=0:', 'if unknown_dependency(ev) or cap<=0:'),
            ("lookup(statement['fiscal'],'price',False,7)", "lookup(exit_day,'adjusted',False,7)"),
            ('if ev<=0 or cap<=0:', "if 'aaa' < 'bbb':"),
            ('if ev<=0 or cap<=0:', 'if entry_day < 100:'),
            ('if ev<=0 or cap<=0:', "if '' :"),
            ("str(statement['fiscal'])", 'str(cap)'),
            ("    fiscal_px=lookup(statement['fiscal'],'price',False,7)\n", '' ),
            ("    fiscal_px=lookup(statement['fiscal'],'price',False,7)\n    entry_px=lookup(entry_day,'price',True,4)\n    if fiscal_px is None or entry_px is None:\n        return None\n", "    entry_px=lookup(entry_day,'price',True,4)\n"))
        for old,new in mutations:
            with self.subTest(change=new),self.mutation(source_tests.financial_books,'entry_valuation' if ('ev<=0' in old or 'fiscal_px=lookup' in old or 'lookup(statement' in old) else 'snapshot',old,new):
                with self.assertRaisesRegex(ValueError,'Unsupported ((candidate|entry) policy|source entry valuation)'):
                    source_tests.core.PolicyProgram().decisions
        original_inputs,original = self.make()
        batch = [('2015-01-02','2016-01-04','legacy')]
        original_book = original.evaluate(batch,self.all_fields())
        with patch.object(source_tests.financial_books.run,'MIN_MARKET_CAP',200000000):
            changed_inputs,changed = self.make()
            source = source_tests.core.PythonExecutor(changed_inputs)
            self.addCleanup(source.close)
            actual = changed.evaluate(batch,self.all_fields())
            self.assertTrue(source_tests.baseline.compare(source.evaluate(batch,self.all_fields()),actual)['exact'])
            self.assertNotEqual(original_book,actual)
        self.assertNotEqual(changed_inputs.policy.signature,original_inputs.policy.signature)

    def test_source_guard_syntax_does_not_require_compiled_translation(self):
        batch = [('2015-01-02','2016-01-04',pool) for pool in ('legacy','cached')]
        with self.mutation(source_tests.financial_books, 'eligible',
                           'cap>0', 'all((cap>0,))'):
            inputs = source_tests.core.NumericInputs(self.reader, source_tests.s)
            self.addCleanup(inputs.close)
            signature = inputs.policy.signature
            source = NumbaExecutor(inputs)
            self.addCleanup(source.close)
            for book, actual in zip(batch,source.evaluate(batch,self.all_fields()),strict=True):
                self.assertTrue(source_tests.baseline.compare(self.reference(inputs,book),actual)['exact'])
            with self.assertRaisesRegex(ValueError,'Unsupported candidate policy'):
                self.factory(inputs)
            self.assertEqual(inputs.policy.signature,signature)
            self.assertNotIn('decisions',vars(inputs.policy))

    def test_resolved_slot_boundaries_match_source_decisions_exactly(self):
        inputs,executor = self.make()
        policy = inputs.policy
        entry,exit_day,fiscal = date(2015,1,2),date(2016,1,4),date(2014,6,30)
        base_days = [fiscal.toordinal(),entry.toordinal(),entry.toordinal(),exit_day.toordinal(),0,0,0]
        cases = []
        # Both sides and the exact fiscal, raw-entry, adjusted-entry and exit tolerances.
        for slot,tolerance,direction in ((0,7,-1),(1,4,1),(2,4,1),(3,10,-1),(3,100000,-1)):
            for delta in (tolerance-1,tolerance,tolerance+1):
                days = base_days.copy()
                days[slot] += direction*delta
                cases.append((days,150e6,180e6,20e6,False))
        for slot in range(4):
            days = base_days.copy();days[slot] = 0
            cases.append((days,150e6,180e6,20e6,True))
        for average in (np.nan,0.,-1.,20e6):
            cases.append((base_days.copy(),150e6,180e6,average,False))
        for cap,ev in ((1.,1.),(100e6-1,50e6),(100e6,50e6),(100e6+1,50e6),(-1.,50e6),(150e6,-1.)):
            cases.append((base_days.copy(),cap,ev,20e6,False))
        days = base_days.copy();days[2] = exit_day.toordinal()
        cases.append((days,150e6,180e6,20e6,False))
        days = base_days.copy();days[3] = entry.toordinal()-1
        cases.append((days,150e6,180e6,20e6,False))
        days = base_days.copy();days[3] -= 11
        cases.append((days,150e6,180e6,20e6,True))
        for pool in ('cached','legacy'):
            matrix = np.ones((len(cases),len(policy.input_names)),dtype=np.float64)
            metadata = np.tile(np.array([fiscal.toordinal(),entry.toordinal(),exit_day.toordinal(),
                                        entry.year,exit_day.year,int(pool=='legacy')],dtype=np.int32),(len(cases),1))
            prices = np.full((len(cases),7),10.,dtype=np.float64)
            days = np.asarray([case[0] for case in cases],dtype=np.int32)
            for row,(_,cap,ev,average,bankrupt) in enumerate(cases):
                for name,value in (('report_cap',cap),('report_enterprise',ev),('report_yield',.25),
                                   ('average_3y',average),('bankruptcy',bankrupt)):
                    matrix[row,policy.input_index[name]] = value
                for name in source_tests.core.LOOKUP_FIELDS:matrix[row,policy.input_index[name]] = 10.
            numeric = executor.calculate(matrix)
            actual = executor._decide(days,prices,numeric,metadata,matrix)
            expected = np.zeros_like(actual)
            for row,(_,cap,ev,average,bankrupt) in enumerate(cases):
                def lookup(target,column,forward=False,slack=None):
                    slot = (1 if forward else 0) if column=='price' else 2 if forward else 3
                    resolved = int(days[row,slot])
                    if not resolved or abs(resolved-target.toordinal())>slack:return None
                    return date.fromordinal(resolved),float(prices[row,slot])
                observation = policy._snapshot(dict(fiscal=fiscal),entry,exit_day,lookup,bankrupt,numeric[row])
                if observation is None or not source_tests.financial_books.eligible(pool,observation[3],observation[4]):continue
                metric_observation = dict(fiscal=str(fiscal),enterprise_value=observation[4],
                                           ev_ebitda=observation[7],ebitda_yield=observation[6])
                pair = policy._three(metric_observation,numeric[row],None if np.isnan(average) else average)
                expected[row] = (1,*(date.fromisoformat(day).toordinal() for day in observation[:3]),
                                 policy.decisions.statuses.index(observation[-1])+1,1,int(pair is not None))
            np.testing.assert_array_equal(actual,expected)



if __name__=='__main__':
    unittest.main()
