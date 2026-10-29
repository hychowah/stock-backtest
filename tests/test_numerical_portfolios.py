"""Offline numerical/ordinary full-result parity on fictional owned inputs."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import test_bench_methods as shared
import test_numerical_generation as generations
from bench_candidates import NumericInputs, PythonExecutor
from bench_candidates_numba import NumbaExecutor
from numerical_portfolios import NumericalPortfolio, compare_results

s=shared.s


class NumericalPortfolioTests(unittest.TestCase):
    setUp=shared.SharedMethodsTests.setUp

    def evaluator(self, factory=NumbaExecutor, **limits):
        inputs=NumericInputs(self.reader,s)
        self.addCleanup(inputs.close)
        provider=factory(inputs,limits=dict(threads=2,request_plan=True,**limits))
        self.addCleanup(provider.close)
        result=NumericalPortfolio(inputs,provider)
        self.addCleanup(result.close)
        return inputs,provider,result

    def test_full_matrix_complete_rows_options_schema_nulls_and_order(self):
        cases=0;maximum_absolute=maximum_relative=0.
        for factory,limits in ((PythonExecutor,{}),(NumbaExecutor,{'candidate_assembly':'compiled'})):
            inputs,provider,adapter=self.evaluator(factory,**limits)
            for pool in ('legacy','cached'):
                for metric in s.metrics.METRICS:
                    for rank_from,rank_to in ((1,50),(1,100),(51,100),(2,3)):
                        for filters in ([],[dict(field='pe',op='lt',value=20.)],
                                        [dict(field='return_1y',op='gt',value=0.)]):
                            options=dict(pool=pool,metric=metric,rank_from=rank_from,rank_to=rank_to,
                                         min_cap=0.,min_ev=0.,filters=filters)
                            for months in (1,3,6,12,24):
                                request=dict(start='2015-01-02',end='2016-12-30',months=months,**options)
                                expected=s.backtest(self.db,**request)
                                envelope=adapter.backtest(**request)
                                self.assertEqual(set(envelope),{'contract_version','result'})
                                self.assertEqual(envelope['contract_version'],1)
                                agreement=compare_results(expected,envelope['result'])
                                self.assertTrue(agreement['exact'],(request,agreement))
                                maximum_absolute=max(maximum_absolute,agreement['maximum_absolute'])
                                maximum_relative=max(maximum_relative,agreement['maximum_relative'])
                                cases+=1
                            for weeks in (1,2):
                                configuration=dict(version=1,start='2015-01-02',end='2016-12-30',
                                                   interval=dict(unit='week',count=weeks))
                                calendar=adapter._calendar()
                                dates=[str(a) for a,b in calendar.fixed(configuration)][1:]
                                request=dict(dates=dates,start=configuration['start'],end=configuration['end'],**options)
                                expected=s.backtest_dates(self.db,**request)
                                # Explicit evaluation is independent of nominal planning.
                                with patch.object(s,'schedule',side_effect=AssertionError('No nominal reconstruction')):
                                    actual=adapter.backtest_dates(**request)['result']
                                agreement=compare_results(expected,actual)
                                self.assertTrue(agreement['exact'],(request,agreement))
                                self.assertGreater(actual['cash_days'],0)
                                maximum_absolute=max(maximum_absolute,agreement['maximum_absolute'])
                                maximum_relative=max(maximum_relative,agreement['maximum_relative'])
                                self.assertTrue(compare_results(actual,json.loads(json.dumps(actual)))['exact'])
                                cases+=1
            self.assertLessEqual(adapter.db.execute('SELECT COUNT(*) FROM periods').fetchone()[0],1)
            self.assertEqual(adapter.db.execute('SELECT COUNT(*) FROM prices').fetchone()[0],0)
            self.assertEqual(adapter.db.execute('SELECT COUNT(*) FROM statements').fetchone()[0],0)
        self.assertEqual(cases,672)
        print(json.dumps(dict(check='portfolio-complete-result-matrix',cases=cases,
              maximum_absolute=maximum_absolute,maximum_relative=maximum_relative,tolerance=1e-12)),flush=True)

    def test_delayed_adjusted_entry_is_excluded_before_rank_and_replaced(self):
        # A has the best score. Its actual adjusted entry reaches the first exit.
        for pool in ('legacy','cached'):
            inputs,provider,adapter=self.evaluator(candidate_assembly='compiled')
            long_book=adapter.backtest(start='2015-01-02',end='2015-01-06',rank_to=1,pool=pool)['result']
            self.assertEqual([h['symbol'] for h in long_book['periods'][0]['holdings']],['A'])
            request=dict(start='2015-01-02',end='2015-01-05',rank_to=1,pool=pool)
            actual=adapter.backtest(**request)['result']
            expected=s.backtest(self.db,**request)
            self.assertTrue(compare_results(expected,actual)['exact'])
            self.assertEqual([h['symbol'] for h in actual['periods'][0]['holdings']],['STOP'])
            self.assertEqual(actual['periods'][0]['holdings'][0]['rank'],1)
            self.assertNotIn('A',[row[0] for row in adapter.db.execute('SELECT symbol FROM snapshots')])

    def test_complete_trailing_mixed_short_and_empty_source_guard_matrix(self):
        # Coverage expectations are part of the scenario. Matching empty results
        # cannot qualify the complete trailing supplement.
        trailing=[dict(field=name,op='gt',value=0.) for name in ('return_1y','return_3y')]
        mixed=trailing+[dict(field='pe',op='lt',value=20.)]
        inputs,provider,adapter=self.evaluator(candidate_assembly='source')
        cases=[];maximum_absolute=maximum_relative=0.
        for pool in ('legacy','cached'):
            for metric in s.metrics.METRICS:
                for ranks in ((1,50),(1,100),(2,3),(51,100)):
                    for label,filters in [('trailing',trailing),('mixed',mixed)]:
                        for months in (1,3,6,12,24):
                            request=dict(start='2015-01-05',end='2016-12-30',months=months,
                                pool=pool,metric=metric,rank_from=ranks[0],rank_to=ranks[1],
                                min_cap=0.,min_ev=0.,filters=filters)
                            expected=s.backtest(self.db,**request)
                            actual=adapter.backtest(**request)['result']
                            agreement=compare_results(expected,actual)
                            self.assertTrue(agreement['exact'],(request,agreement))
                            counts=[len(p['holdings']) for p in actual['periods']]
                            self.assertTrue(all(n<ranks[1]-ranks[0]+1 for n in counts) if ranks!=(2,3) else True)
                            if ranks[0]==51:
                                self.assertTrue(all(n==0 for n in counts));self.assertIsNone(actual['cagr'])
                            else:
                                self.assertTrue(all(n>0 for n in counts),(request,counts))
                                self.assertIsNotNone(actual['cagr'])
                            maximum_absolute=max(maximum_absolute,agreement['maximum_absolute'])
                            maximum_relative=max(maximum_relative,agreement['maximum_relative'])
                            cases.append(dict(options=request,counts=counts))
        # Each condition changes membership independently on owned fictional data.
        adapter.close();provider.close();inputs.close()
        with self.db:
            self.db.execute("UPDATE prices SET adjusted=adjusted*2 WHERE symbol='A' AND day BETWEEN '2014-01-01' AND '2014-12-31'")
            self.db.execute("UPDATE prices SET adjusted=adjusted*2 WHERE symbol='C' AND day BETWEEN '2012-01-01' AND '2012-12-31'")
        inputs,provider,adapter=self.evaluator(candidate_assembly='source')
        selected=[]
        for filters in ([],trailing[:1],trailing[1:],trailing,mixed):
            options=dict(start='2015-01-05',end='2015-02-27',rank_to=100,
                         min_cap=0.,min_ev=0.,filters=filters)
            actual=adapter.backtest(**options)['result']
            agreement=compare_results(s.backtest(self.db,**options),actual)
            self.assertTrue(agreement['exact'])
            maximum_absolute=max(maximum_absolute,agreement['maximum_absolute'])
            maximum_relative=max(maximum_relative,agreement['maximum_relative'])
            selected.append({h['symbol'] for h in actual['periods'][0]['holdings']})
        self.assertIn('A',selected[0]-selected[1])
        self.assertIn('C',selected[0]-selected[2])
        self.assertEqual(selected[3],selected[1]&selected[2])
        self.assertIn('B',selected[3]-selected[4])
        print(json.dumps(dict(check='complete-trailing-mixed-source',cases=cases,
            selective_membership=[sorted(v) for v in selected],maximum_absolute=maximum_absolute,
            maximum_relative=maximum_relative,tolerance=1e-12)),flush=True)

    def test_bankruptcy_stopped_exits_final_mark_and_empty_following_full(self):
        with patch.object(s.r.revalue,'BANKRUPT',{(2016,'STOP')}):
            inputs,provider,adapter=self.evaluator(candidate_assembly='compiled')
            request=dict(start='2016-01-04',end='2016-12-30',rank_to=50)
            expected=s.backtest(self.db,**request)
            actual=adapter.backtest(**request)['result']
            self.assertTrue(compare_results(expected,actual)['exact'])
            stopped=next(h for h in actual['periods'][0]['holdings'] if h['symbol']=='STOP')
            self.assertEqual((stopped['return_value'],stopped['status']),(-1.,'Bankruptcy'))
            self.assertEqual(stopped['exit'],'2016-05-31')
            self.assertTrue(actual['periods'][-1]['is_final_period'])
            empty=adapter.backtest(**dict(request,filters=[dict(field='pe',op='lt',value=.0001)]))['result']
            self.assertEqual(empty['periods'][0]['holdings'],[])
            self.assertIsNone(empty['growth']);self.assertIsNone(empty['cagr'])
            self.assertTrue(compare_results(s.backtest(self.db,**dict(request,filters=[dict(field='pe',op='lt',value=.0001)])),empty)['exact'])
        inputs,provider,adapter=self.evaluator()
        ordinary_stop=adapter.backtest(start='2016-01-04',end='2016-12-30')['result']
        self.assertEqual(next(h for h in ordinary_stop['periods'][0]['holdings'] if h['symbol']=='STOP')['status'],'Last available price')

    def test_provider_errors_validation_cancellation_rollback_and_closure(self):
        inputs,provider,adapter=self.evaluator(PythonExecutor)
        request=dict(start='2015-01-02',end='2016-12-30')
        original=provider.evaluate
        for mutate in (lambda books:[],lambda books:books+books,
                       lambda books:[dict(books[0],entry='2015-01-05')],
                       lambda books:[dict(books[0],pool='cached')],
                       lambda books:[dict(books[0],snapshots=[('broken',)])],
                       lambda books:[dict(books[0],period=('2015-01-05',*books[0]['period'][1:]))]):
            with patch.object(provider,'evaluate',side_effect=lambda *args,m=mutate:m(original(*args))):
                with self.assertRaises(ValueError):adapter.backtest(**request)
            self.assertFalse(adapter.db.in_transaction)
        with patch.object(provider,'evaluate',side_effect=RuntimeError('fictional provider failure')):
            with self.assertRaises(RuntimeError):adapter.backtest(**request)
        for options in (dict(rank_from=0),dict(metric='unknown'),dict(filters=[dict(field='pe',op='lt',value=float('nan'))]),dict(unknown=True)):
            with patch.object(provider,'evaluate',side_effect=AssertionError('invalid request must precede provider')):
                with self.assertRaises(ValueError):adapter.backtest(**request,**options)
        with patch.object(provider,'evaluate',side_effect=AssertionError('invalid periods must precede provider')):
            with self.assertRaises(ValueError):adapter.backtest_periods([])
        with patch.object(s.backtest_control,'checkpoint',side_effect=RuntimeError('fictional cancel')):
            with self.assertRaises(RuntimeError):adapter.backtest(**request)
        self.assertFalse(adapter.db.in_transaction)
        before=[tuple(row) for row in adapter.db.execute('SELECT * FROM snapshots')]
        staged=0
        import numerical_portfolios
        original_stage=numerical_portfolios.stage_book
        def stage(*args,**kwargs):
            nonlocal staged
            result=original_stage(*args,**kwargs);staged+=1
            return result
        def cancel_between_books():
            if staged:raise RuntimeError('fictional between-book cancel')
        with patch.object(s.backtest_control,'checkpoint',side_effect=cancel_between_books), \
                patch('numerical_portfolios.stage_book',side_effect=stage), \
                patch.object(provider,'evaluate',wraps=original) as called:
            with self.assertRaisesRegex(RuntimeError,'between-book'):
                adapter.backtest_periods([(date(2015,1,2),date(2016,1,4)),
                                          (date(2016,1,4),date(2016,12,30))])
        self.assertEqual(called.call_count,1)
        self.assertFalse(adapter.db.in_transaction)
        self.assertEqual([tuple(row) for row in adapter.db.execute('SELECT * FROM snapshots')],before)
        self.assertTrue(compare_results(s.backtest(self.db,**request),adapter.backtest(**request)['result'])['exact'])
        adapter.close();adapter.close()
        self.assertFalse(inputs.closed)
        self.assertTrue(provider.evaluate([('2015-01-02','2016-01-04','legacy')]))
        with self.assertRaises(sqlite3.ProgrammingError):adapter.db.execute('SELECT 1')
        with self.assertRaises(ValueError):adapter.backtest(**request)
        with self.assertRaises(RuntimeError):
            with NumericalPortfolio(inputs,provider) as temporary:
                raise RuntimeError('fictional caller failure')
        self.assertTrue(temporary.closed)


class AttachedPortfolioTests(unittest.TestCase):
    def test_fresh_attachment_lazy_records_complete_results_and_closure(self):
        fixture=generations.GenerationTests('test_export_values_order_missingness_and_mutable_books_reuse')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.prepare();inputs=fixture.attach()
        for assembly in ('source','compiled'):
            provider=NumbaExecutor(inputs,limits=dict(threads=2,request_plan=True,candidate_assembly=assembly))
            try:
                with NumericalPortfolio(inputs,provider) as adapter:
                    for pool in ('cached','legacy'):
                        request=dict(start='2015-01-02',end='2016-12-30',months=3,pool=pool)
                        self.assertTrue(compare_results(s.backtest(fixture.db,**request),adapter.backtest(**request)['result'])['exact'])
                    fixture.binding['prices']={'fictional_revision':1}
                    with self.assertRaisesRegex(ValueError,'stale'):adapter.backtest(**request)
                    fixture.binding['prices']={}
                self.assertTrue(adapter.closed)
                self.assertFalse(inputs.closed)
            finally:provider.close()
        inputs.close();self.assertTrue(inputs.closed)


class ComparisonTests(unittest.TestCase):
    def test_structural_category_null_array_order_and_numeric_diagnostics(self):
        original=dict(seconds=2.,rows=[dict(symbol='A',rank=1,value=1.,candidate_rank=None),dict(symbol='B',rank=2,value=2.)])
        actual=deepcopy(original);actual['seconds']=99.;actual['rows'][0]['value']+=5e-13
        agreement=compare_results(original,actual)
        self.assertTrue(agreement['exact']);self.assertGreater(agreement['maximum_absolute'],0.)
        actual['rows'][0]['value']=1.1
        agreement=compare_results(original,actual)
        self.assertFalse(agreement['exact']);self.assertFalse(agreement['structural']);self.assertTrue(agreement['numeric'])
        actual=deepcopy(original);actual['rows'].reverse()
        self.assertTrue(compare_results(original,actual)['structural'])
        for mutate in (lambda r:r['rows'][0].pop('candidate_rank'),lambda r:r['rows'][0].update(candidate_rank=0),
                       lambda r:r['rows'][0].update(rank=1.),lambda r:r.update(extra=True)):
            actual=deepcopy(original);mutate(actual)
            self.assertTrue(compare_results(original,actual)['structural'])
        actual=deepcopy(original);actual['rows'][0]['value']=float('nan')
        self.assertEqual(compare_results(original,actual)['numeric'][0]['reason'],'nonfinite')


if __name__=='__main__':unittest.main()
