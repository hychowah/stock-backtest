"""Artifact-backed factor comparisons against ordinary source calculators."""
from datetime import date
import importlib.util
import inspect
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_numerical_generation as fixtures
import test_bench_candidates as candidate_tests
from numerical_factors import FactorEvaluator
from numerical_policy import PolicyProgram, FACTOR_VERSION, _schema_tree
import numpy as np


class FactorTests(unittest.TestCase):
    setUp = fixtures.GenerationTests.setUp
    prepare = fixtures.GenerationTests.prepare
    attach = fixtures.GenerationTests.attach

    def make(self, **limits):
        candidate_tests.CandidateTests.rich_financials(self)
        self.prepare()
        inputs = self.attach()
        evaluator = FactorEvaluator(inputs, **limits)
        self.addCleanup(evaluator.close)
        return inputs, evaluator

    def compare_source(self, inputs, evaluator, days=(date(2015,1,2), date(2016,2,29))):
        counts = {field: 0 for field in self.s.metrics.FILTERS}
        maximum_absolute = maximum_relative = 0.
        history = self.s.histories(self.db)
        for pool, book in zip(('cached','legacy'), history, strict=True):
            for day, batch in zip(days, evaluator.evaluate([d.toordinal() for d in days], pool), strict=True):
                for row, (sid, report_id) in enumerate(zip(batch.symbols, batch.reports, strict=True)):
                    symbol = inputs.symbols[int(sid)]
                    statement = self.s.financial_books.run.latest_statement(book.get(symbol, []), day)
                    self.assertEqual(inputs.report_rows[int(report_id)], statement)
                    lookup = lambda target,column,forward=False,slack=None: self.s.price(self.db,symbol,target,column,forward,slack)
                    ordinary = self.s.financial_books.snapshot(statement,day,date(2016,12,30),lookup,False)
                    self.assertEqual(bool(batch.valuation_valid[row]), ordinary is not None)
                    if ordinary is None: continue
                    fiscal,buy,sell,cap,ev,ebitda,yield_value,multiple,ret,status = ordinary
                    observation = dict(fiscal=fiscal,market_cap=cap,enterprise_value=ev,
                                       ev_ebitda=multiple,ebitda_yield=yield_value)
                    pairs = self.s.metrics.evaluate(observation, inputs.histories[symbol])
                    thresholds = self.s.metrics.filter_values(observation,pairs,day,lookup,inputs.financials.get(symbol,{}))
                    np.testing.assert_allclose(batch.valuation[row], [cap,ev,ebitda],rtol=1e-12,atol=1e-12)
                    for name, values in batch.pairs.items():
                        self.assertEqual(bool(batch.pair_valid[name][row]), name in pairs)
                        if name in pairs: np.testing.assert_allclose(values[row],pairs[name],rtol=1e-12,atol=1e-12)
                    for name, values in batch.thresholds.items():
                        self.assertEqual(bool(batch.threshold_valid[name][row]), name in thresholds, (symbol,str(day),name))
                        if name not in thresholds: continue
                        expected, actual = thresholds[name], float(values[row])
                        self.assertTrue(np.isclose(actual,expected,rtol=1e-12,atol=1e-12),(name,actual,expected))
                        maximum_absolute=max(maximum_absolute,abs(actual-expected))
                        maximum_relative=max(maximum_relative,abs(actual-expected)/max(1.,abs(expected)))
                        counts[name]+=1
        return counts,maximum_absolute,maximum_relative

    def test_full_catalog_both_pools_and_leap_day(self):
        inputs,evaluator=self.make()
        counts,absolute,relative=self.compare_source(inputs,evaluator)
        self.assertTrue(all(counts.values()),counts)
        self.assertEqual(set(json.loads(evaluator.catalog)['metrics']),set(self.s.metrics.METRICS))
        self.assertEqual(set(json.loads(evaluator.catalog)['thresholds']),set(self.s.metrics.FILTERS))
        result=evaluator.evaluate([date(2015,1,2).toordinal()])[0]
        self.assertTrue(any(result.thresholds['fcf'][result.threshold_valid['fcf']]<0))
        self.assertTrue(any(result.thresholds['profit_margin'][result.threshold_valid['profit_margin']]<0))
        self.assertNotIn('adjusted_exit',inputs.policy.dependencies(evaluator.outputs))
        self.assertNotIn('bankruptcy',inputs.policy.dependencies(evaluator.outputs))
        self.assertNotIn('treasury',inputs.policy.dependencies(evaluator.outputs))
        print(json.dumps(dict(check='factor-catalog',coverage=counts,maximum_absolute=absolute,
            maximum_relative=relative,result_payload_bytes=result.payload_bytes,stats=evaluator.stats)),flush=True)

    def test_missing_years_variants_and_unrequested_missing_values(self):
        self.db.execute("INSERT INTO statements VALUES('A','2014-09-30','2014-12-29',160000000,190000000,70000000,0.3684210526315789)")
        self.db.execute("DELETE FROM statements WHERE symbol='A' AND fiscal='2013-06-30'")
        self.db.execute("DELETE FROM financial_inputs WHERE symbol='A' AND fiscal='2013-06-30'")
        self.db.commit()
        inputs,evaluator=self.make()
        self.compare_source(inputs,evaluator)
        day=date(2015,1,2).toordinal()
        ordinary=evaluator.evaluate([day],threshold_fields=[])[0]
        missing=evaluator.evaluate([day],threshold_fields=['pb','peg','roe'])[0]
        self.assertEqual(ordinary.thresholds,{})
        np.testing.assert_array_equal(ordinary.valuation_valid,missing.valuation_valid)
        np.testing.assert_array_equal(ordinary.pairs['ev_ebitda'],missing.pairs['ev_ebitda'])
        pos=list(missing.symbols).index(inputs.symbol_ids['A'])
        self.assertFalse(missing.pair_valid['ev_ebitda_3y'][pos])
        self.assertFalse(missing.threshold_valid['peg'][pos])
        self.assertFalse(missing.threshold_valid['roe'][pos])

    def test_currency_conflicts_and_denominators_keep_independent_validity(self):
        import financial_inputs
        raw=self.root/'annual';ledger={}
        rows=[dict(symbol='A',date='2014-06-30',period='FY',reportedCurrency=currency,
                   netIncome=income,epsDiluted=5.,revenue=100e6,ebit=40e6,interestExpense=0.)
              for currency,income in [('USD',30e6),('USD',31e6),('EUR',90e6)]]
        financial_inputs.publish(raw,'A','income-statement',rows,ledger,raw/'coverage.json')
        values=financial_inputs.history(raw,'A')['2014-06-30']
        self.assertNotIn('netIncome',values)
        values.update(totalStockholdersEquity=-10e6,totalCurrentAssets=90e6,totalCurrentLiabilities=0.,totalDebt=60e6,freeCashFlow=-20e6)
        self.db.execute("UPDATE financial_inputs SET values_json=? WHERE symbol='A' AND fiscal='2014-06-30'",(json.dumps(values),))
        self.db.commit()
        inputs,evaluator=self.make()
        # make enriches common fields; restore the actual normalized conflict inputs
        # before creating the final immutable generation.
        self.db.execute("UPDATE financial_inputs SET values_json=? WHERE symbol='A' AND fiscal='2014-06-30'",(json.dumps(values),));self.db.commit()
        evaluator.close();inputs.close();self.binding['revision']='conflict';self.prepare()
        inputs=self.attach();evaluator=FactorEvaluator(inputs);self.addCleanup(evaluator.close)
        self.compare_source(inputs,evaluator)
        batch=evaluator.evaluate([date(2015,1,2).toordinal()])[0]
        row=list(batch.symbols).index(inputs.symbol_ids['A'])
        for field in ('pe','pb','roe','peg','current_ratio','interest_coverage','debt_equity','price_fcf'):
            self.assertFalse(batch.threshold_valid[field][row],field)
        self.assertTrue(batch.threshold_valid['fcf'][row])
        self.assertLess(batch.thresholds['fcf'][row],0)

    def test_source_mean_rounding_and_trailing_gap_boundaries(self):
        # math.fsum/3 and ordinary chained sum/3 differ for this positive history.
        values=(1e16,1.,1.)
        for year,value in zip((2012,2013,2014),values,strict=True):
            self.db.execute("UPDATE statements SET ebitda=?,ebitda_yield=? WHERE symbol='A' AND fiscal=?",(value,value/180e6,f'{year}-06-30'))
        # The leap-day 3-year anniversary is 2013-02-28. Make the nearest
        # earlier observation exactly seven calendar days away.
        self.db.execute("DELETE FROM prices WHERE symbol='A' AND day>'2013-02-21' AND day<='2013-02-28'")
        self.db.commit()
        inputs,evaluator=self.make()
        self.compare_source(inputs,evaluator)
        rows=inputs.histories['A']
        report=next(i for i,r in enumerate(inputs.report_rows) if inputs.symbols[int(inputs.report_symbol[i])]=='A' and r['fiscal']==date(2014,6,30))
        self.assertEqual(inputs.average_3y[report],self.s.metrics.annual_average(rows,'2014-06-30',3))
        batch=evaluator.evaluate([date(2016,2,29).toordinal()])[0]
        pos=list(batch.symbols).index(inputs.symbol_ids['A']);self.assertTrue(batch.threshold_valid['return_3y'][pos])
        evaluator.close();inputs.close()
        self.db.execute("DELETE FROM prices WHERE symbol='A' AND day='2013-02-21'");self.db.commit()
        self.binding['revision']='trailing-eight-days';self.prepare()
        inputs=self.attach();evaluator=FactorEvaluator(inputs);self.addCleanup(evaluator.close)
        self.compare_source(inputs,evaluator)
        batch=evaluator.evaluate([date(2016,2,29).toordinal()])[0]
        pos=list(batch.symbols).index(inputs.symbol_ids['A']);self.assertFalse(batch.threshold_valid['return_3y'][pos])

    def test_entry_calendar_tolerances_do_not_require_an_exit(self):
        candidate_tests.CandidateTests.rich_financials(self)
        for case,(fiscal_day,entry_day,expected) in enumerate([
                ('2014-06-23','2015-01-06',True),
                ('2014-06-22','2015-01-06',False),
                ('2014-06-23','2015-01-07',False)]):
            self.db.execute("DELETE FROM prices WHERE symbol='A' AND day BETWEEN '2014-06-22' AND '2014-06-30'")
            self.db.execute("DELETE FROM prices WHERE symbol='A' AND day BETWEEN '2015-01-02' AND '2015-01-07'")
            self.db.executemany('INSERT INTO prices VALUES(?,?,?,?)',[('A',fiscal_day,10.,10.),('A',entry_day,12.,12.)])
            self.db.commit();self.binding['revision']=case;self.prepare()
            inputs=self.attach();evaluator=FactorEvaluator(inputs)
            try:
                self.compare_source(inputs,evaluator,days=(date(2015,1,2),))
                batch=evaluator.evaluate([date(2015,1,2).toordinal()])[0]
                pos=list(batch.symbols).index(inputs.symbol_ids['A'])
                self.assertEqual(bool(batch.valuation_valid[pos]),expected)
            finally:evaluator.close();inputs.close()

    def test_cache_bounds_duplicates_detached_results_and_closure(self):
        inputs,evaluator=self.make(cache_bytes=10000)
        a,b=date(2015,1,2).toordinal(),date(2016,2,29).toordinal()
        first=evaluator.evaluate([a,a],threshold_fields=['pb','pe','pb'])
        again=evaluator.evaluate([a],threshold_fields=['pe','pb'])[0]
        self.assertEqual(first[0].identity,again.identity)
        self.assertEqual(evaluator.stats['hits'],2)
        self.assertIsNot(first[0].valuation,first[1].valuation)
        with self.assertRaises(ValueError):first[0].valuation.flags.writeable=True
        with self.assertRaises(TypeError):first[0].thresholds['new']=np.array([])
        evaluator.evaluate([b],threshold_fields=['pe','pb'])
        self.assertLessEqual(evaluator.stats['retained_bytes'],10000)
        self.assertEqual(evaluator.stats['retained_entries'],1)
        evaluator.close();self.assertEqual(evaluator.stats['retained_bytes'],0)
        inputs.close();self.assertTrue(np.isfinite(first[0].valuation).any())
        with self.assertRaises(ValueError):evaluator.evaluate([a])
        inputs=self.attach();uncached=FactorEvaluator(inputs,cache_bytes=0);self.addCleanup(uncached.close)
        uncached.evaluate([a,a]);self.assertEqual(uncached.stats['retained_entries'],0)
        self.assertEqual(uncached.stats['misses'],2)

    def test_invalid_requests_contracts_and_work_bounds(self):
        inputs,evaluator=self.make()
        with patch.object(evaluator.temporal,'select_reports',side_effect=AssertionError('native entered')):
            for days,kwargs in [([[1]],{}),([True],{}),([0],{}),([1.5],{}),([1],{}),([2015],dict(pool='unknown')),
                ([736000],dict(threshold_fields=['unknown'])),([736000],dict(threshold_fields='pe')),
                ([736000]*100000,{})]:
                with self.subTest(days=str(days)[:40],kwargs=kwargs),self.assertRaises(ValueError):evaluator.evaluate(days,**kwargs)
        self.assertEqual(evaluator.evaluate(np.array([],dtype=np.int32)),[])
        for version in (None,True,2):
            with patch.object(inputs,'factor_version',version),self.assertRaises(ValueError):FactorEvaluator(inputs)
        with patch.object(inputs,'field_schema','f'*64),self.assertRaises(ValueError):FactorEvaluator(inputs)
        inputs.close()
        with self.assertRaises(ValueError):evaluator.evaluate([date(2015,1,2).toordinal()])

    def test_factor_binding_versions_and_policy_only_imports(self):
        import ast
        function=ast.parse('def sample():\n    return 1\n').body[0]
        baseline=_schema_tree(function)
        # Model the extra ordinary-function metadata introduced by Python 3.12.
        function._fields=(*function._fields,*(('type_params',) if 'type_params' not in function._fields else ()))
        function.type_params=[]
        self.assertEqual(_schema_tree(function),baseline)
        for version in (None,True,2):
            self.binding['factor_version']=version
            with self.subTest(version=version),self.assertRaisesRegex(ValueError,'factor'):self.prepare()
        self.binding['factor_version']=FACTOR_VERSION
        self.binding['field_schema']=True
        with self.assertRaisesRegex(ValueError,'factor'):self.prepare()
        code="import sys;sys.path.insert(0,sys.argv[1]);import numerical_policy;assert 'numpy' not in sys.modules and 'numba' not in sys.modules"
        p=subprocess.run([sys.executable,'-I','-B','-c',code,str(Path(fixtures.ng.__file__).parent)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)

    def test_entry_source_guard_mutation_is_not_a_holding_exit(self):
        path=self.root/'changed_books.py'
        text=inspect.getsource(self.s.financial_books.snapshot).replace('ev<=0 or cap<=0','ev<=0 or cap<=160000000')
        path.write_text(text)
        spec=importlib.util.spec_from_file_location('changed_books',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.object(self.s.financial_books,'snapshot',module.snapshot):
            policy=PolicyProgram(self.s)
            self.binding.update(policy=policy.signature,field_schema=policy.field_schema)
            inputs,evaluator=self.make()
            self.compare_source(inputs,evaluator)
            result=evaluator.evaluate([date(2015,1,2).toordinal()])[0]
            pos=list(result.symbols).index(inputs.symbol_ids['A'])
            self.assertFalse(result.valuation_valid[pos])
        evaluator.close();inputs.close()


if __name__=='__main__':unittest.main()
