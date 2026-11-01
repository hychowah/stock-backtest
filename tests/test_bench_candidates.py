"""Source differential proof for immutable inputs and candidate factor batches."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
import sys as _owner_sys
from pathlib import Path as _OwnerPath
_owner_sys.path.insert(0,str(_OwnerPath(__file__).resolve().parents[1]))
from backtest.engines.reference import legacy
from backtest.inputs import daily, research
from backtest.financial import rules, books as financial_books, metrics
from datetime import date,timedelta
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_bench_methods as shared
import tools.experiments.bench_candidates as core
import numpy as np

s,baseline = shared.s,shared.baseline


class CandidateTests(unittest.TestCase):
    factory = core.PythonExecutor
    setUp = shared.SharedMethodsTests.setUp

    def make(self,*,capture=True):
        inputs = core.NumericInputs(self.reader,s)
        self.addCleanup(inputs.close)
        executor = self.factory(inputs,limits={'capture':capture,'threads':4})
        self.addCleanup(executor.close)
        return inputs,executor

    def all_fields(self):
        return dict(filters=[dict(field=field,op='gt',value=-999999.) for field in core.PolicyProgram().fields['thresholds']])

    def test_planned_batches_preserve_all_fields_and_projected_request_results(self):
        self.rich_financials()
        inputs, executor = self.make()
        ordinary = core.PythonExecutor(inputs, limits={'capture': True})
        self.addCleanup(ordinary.close)
        executor.limits['request_plan'] = True
        for pool in ('legacy', 'cached'):
            for profile in ('all', 'F0', 'F1', 'F2'):
                options = dict(baseline.options(pool, 'F0' if profile == 'all' else profile))
                if profile == 'all': options.update(self.all_fields())
                batch = [('2015-01-02', '2016-01-04', pool),
                         ('2016-02-29', '2016-12-30', pool)]
                executor.begin(dict(options=options)); ordinary.begin(dict(options=options))
                expected = ordinary.evaluate(batch)
                observed = executor.evaluate(batch)
                self.assertTrue(baseline.compare(expected, observed)['exact'])
                if profile == 'all':
                    for key, value in ordinary.trace.items():
                        np.testing.assert_allclose(executor.trace[key], value, rtol=0, atol=0,
                                                   equal_nan=True, err_msg=key)

    def reference(self,inputs,book):
        a,b,pool = book
        return s.compute_period(self.db,date.fromisoformat(a),date.fromisoformat(b),
                                inputs.books,inputs.cached,pool)

    def rich_financials(self):
        rows = list(self.db.execute('SELECT symbol,fiscal,values_json FROM financial_inputs'))
        for symbol,fiscal,raw in rows:
            values = json.loads(raw)
            values.update(revenue=100e6,operatingIncome=40e6,totalCurrentAssets=200e6,
                          totalCurrentLiabilities=50e6,ebit=40e6,
                          interestExpense=5e6,totalDebt=30e6)
            if symbol=='A' and fiscal=='2014-06-30':values['freeCashFlow']=-20e6
            if symbol=='STOP' and fiscal=='2014-06-30':values['netIncome']=-5e6
            self.db.execute('UPDATE financial_inputs SET values_json=? WHERE symbol=? AND fiscal=?',
                            (json.dumps(values),symbol,fiscal))
        self.db.executemany('INSERT OR IGNORE INTO treasury10 VALUES(?,?)',
                            [('2014-12-31',2.),('2015-07-01',3.),('2016-07-01',0.)])
        self.db.commit()

    def test_complete_source_candidates_all_fields_both_pools_and_dates(self):
        self.rich_financials()
        inputs,executor = self.make()
        batch = [('2015-01-02','2016-01-04',pool) for pool in ('legacy','cached')]
        batch += [('2016-02-29','2016-12-30',pool) for pool in ('legacy','cached')]
        results = executor.evaluate(batch,self.all_fields())
        fields = set()
        for book,actual in zip(batch,results,strict=True):
            expected = self.reference(inputs,book)
            self.assertTrue(baseline.compare(expected,actual)['exact'])
            fields.update(row[1] for row in actual['filters'])
        self.assertEqual(fields,set(core.PolicyProgram().fields['thresholds']))
        first = results[0]
        self.assertTrue(any(field=='fcf' and value<0 for symbol,field,value in first['filters']))
        self.assertTrue(any(field=='profit_margin' and value<0 for symbol,field,value in first['filters']))
        self.assertFalse(any(symbol=='C' and field=='pb' for symbol,field,value in first['filters']))
        trace = executor.trace
        self.assertEqual(trace['numeric_outputs'].shape[1],len(inputs.policy.output_names))
        self.assertEqual(trace['lookup_days'].shape[1],7)
        self.assertEqual(len(trace['accepted']),len(trace['row_reports']))

    def test_report_identity_and_stable_ranks_at_all_temporal_boundaries(self):
        self.db.execute("INSERT INTO companies VALUES('OLD','OLD','NYSE','Energy')")
        self.db.execute("INSERT INTO statements VALUES('OLD','2014-06-30','2014-09-28',150000000,180000000,60000000,0.3333333333333333)")
        self.db.commit()
        inputs,executor = self.make()
        boundaries = {date(2000,1,1),date(2030,1,1)}
        for row in inputs.report_rows:
            for anchor in (row['known'],row['fiscal']+rules.MAX_AGE):
                boundaries.update(anchor+timedelta(days=offset) for offset in (-1,0,1))
        days = sorted(boundaries)
        broad,legacy = executor.select_reports(np.array([day.toordinal() for day in days],dtype=np.int32))
        for index,day in enumerate(days):
            expected,ranks = financial_books.candidates(inputs.books,day)
            for pool,selected in (('cached',broad),('legacy',legacy)):
                actual = {symbol:inputs.report_rows[int(selected[index,symbol_id])]
                          for symbol_id,symbol in enumerate(inputs.symbols) if selected[index,symbol_id]>=0}
                self.assertEqual(list(actual),list(expected[pool]))
                for symbol,row in actual.items():self.assertIs(row,expected[pool][symbol])

    def test_buffer_ties_precede_price_coverage_and_keep_null_cached_rank(self):
        for number in reversed(range(rules.BUFFER+5)):
            symbol = f'T{number:03}'
            self.db.execute('INSERT INTO companies VALUES(?,?,?,?)',(symbol,symbol,'NYSE','Energy'))
            self.db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',
                (symbol,'2014-06-30','2014-09-28',150e6,180e6,60e6,1/3))
            if number!=rules.BUFFER+4:
                self.db.executemany('INSERT INTO prices VALUES(?,?,?,?)',
                    [(symbol,'2014-06-30',10.,10.),(symbol,'2015-01-02',10.,10.),
                     (symbol,'2016-01-04',11.,11.)])
        self.db.commit()
        inputs,executor = self.make()
        batch = [('2015-01-02','2016-01-04',pool) for pool in ('legacy','cached')]
        actual = executor.evaluate(batch,self.all_fields())
        for book,result in zip(batch,actual,strict=True):
            self.assertTrue(baseline.compare(self.reference(inputs,book),result)['exact'])
        source_reports,source_ranks = financial_books.candidates(inputs.books,date(2015,1,2))
        for index,book in enumerate(batch):
            expected = {symbol:source_ranks.get(symbol) for symbol in inputs.symbols}
            observed = executor.trace['ranks'][index]
            self.assertEqual([int(value) or None for value in observed],list(expected.values()))
        self.assertTrue(any(row[1] is None for row in actual[1]['snapshots']))

    def test_short_period_adjusted_entry_early_stop_and_bankruptcy(self):
        with patch.object(rules,'BANKRUPT',{(2016,'STOP')}):
            inputs,executor = self.make()
            books = [('2015-01-02','2015-01-05','legacy'),
                     ('2016-02-29','2016-03-07','cached'),
                     ('2016-01-04','2016-12-30','legacy')]
            actual = executor.evaluate(books,self.all_fields())
            for book,result in zip(books,actual,strict=True):
                self.assertTrue(baseline.compare(self.reference(inputs,book),result)['exact'])
        self.assertNotIn('A',{row[0] for row in actual[0]['snapshots']})
        stopped = next(row for row in actual[-1]['snapshots'] if row[0]=='STOP')
        self.assertEqual(stopped[-2:],(-1.,'Bankruptcy'))
        self.assertEqual(inputs.bankrupt,frozenset({(2016,'STOP')}))

    def test_requested_thresholds_and_begin_reset_without_source_mutation(self):
        inputs,executor = self.make()
        batch = [('2015-01-02','2016-01-04','legacy')]
        executor.begin({'options':{'filters':[]}})
        first = executor.evaluate(batch)
        self.assertEqual(first[0]['filters'],[])
        executor.begin({'options':{'filters':[dict(field='pb',op='lt',value=3.)]}})
        second = executor.evaluate(batch)
        self.assertTrue(second[0]['filters'])
        self.assertEqual({row[1] for row in second[0]['filters']},{'pb'})
        self.assertEqual(executor.stats['books'],1)
        self.assertEqual(executor.stats['batches'],1)
        self.assertTrue(baseline.compare(first[0]['snapshots'],second[0]['snapshots'])['exact'])
        with self.assertRaises(ValueError):inputs.raw_values[0] = 0.
        with self.assertRaises(ValueError):inputs.financial_parameters[0,0] = 0.
        executor.close()
        self.assertGreater(self.reader.execute('SELECT COUNT(*) FROM prices').fetchone()[0],0)

    def test_repeated_fiscal_year_and_missing_annual_history_remain_distinct(self):
        self.db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',
            ('A','2014-09-30','2014-12-29',160e6,190e6,70e6,70/190))
        self.db.execute('INSERT INTO financial_inputs VALUES(?,?,?)',
            ('A','2014-09-30',json.dumps(dict(netIncome=30e6,totalStockholdersEquity=110e6,
                                           freeCashFlow=20e6,epsDiluted=5.))))
        self.db.commit()
        book = ('2015-01-02','2016-01-04','cached')
        inputs,executor = self.make()
        actual = executor.evaluate([book],self.all_fields())[0]
        self.assertTrue(baseline.compare(self.reference(inputs,book),actual)['exact'])
        holding = next(row for row in actual['snapshots'] if row[0]=='A')
        self.assertEqual(holding[2],'2014-09-30')
        self.assertTrue(any(row[0]=='A' and row[1]=='ev_ebitda_3y' for row in actual['metrics']))
        self.db.execute("DELETE FROM statements WHERE symbol='A' AND fiscal='2013-06-30'")
        self.db.commit()
        inputs,executor = self.make()
        actual = executor.evaluate([book],self.all_fields())[0]
        self.assertTrue(baseline.compare(self.reference(inputs,book),actual)['exact'])
        self.assertFalse(any(row[0]=='A' and row[1]=='ev_ebitda_3y' for row in actual['metrics']))
        # EBITDA history and full annual EPS history have independent missingness.
        self.assertTrue(any(row[0]=='A' and row[1]=='peg' for row in actual['filters']))

    def test_financial_missing_year_and_overflow_keep_source_validity(self):
        self.rich_financials()
        self.db.execute("DELETE FROM financial_inputs WHERE symbol='A' AND fiscal='2013-06-30'")
        self.db.commit()
        book = ('2015-01-02','2016-01-04','cached')
        inputs,executor = self.make()
        actual = executor.evaluate([book],self.all_fields())[0]
        self.assertTrue(baseline.compare(self.reference(inputs,book),actual)['exact'])
        self.assertFalse(any(row[0]=='A' and row[1] in ('roe','peg') for row in actual['filters']))
        self.assertTrue(any(row[0]=='A' and row[1]=='ev_ebitda_3y' for row in actual['metrics']))
        values = json.loads(self.db.execute("SELECT values_json FROM financial_inputs WHERE symbol='A' AND fiscal='2014-06-30'").fetchone()[0])
        values.update(netIncome=1e-310,freeCashFlow=-1e300)
        self.db.execute("UPDATE financial_inputs SET values_json=? WHERE symbol='A' AND fiscal='2014-06-30'",(json.dumps(values),))
        self.db.commit()
        inputs,executor = self.make()
        actual = executor.evaluate([book],self.all_fields())[0]
        self.assertTrue(baseline.compare(self.reference(inputs,book),actual)['exact'])
        self.assertFalse(any(row[0]=='A' and row[1]=='pe' for row in actual['filters']))
        self.assertTrue(any(row[0]=='A' and row[1]=='fcf' and row[2]<0 for row in actual['filters']))

    def test_derived_input_signature_is_content_bound(self):
        first,unused = self.make()
        signature = first.signature
        self.db.execute("UPDATE prices SET price=price+1 WHERE symbol='A' AND day='2014-06-30'")
        self.db.commit()
        second,unused = self.make()
        self.assertNotEqual(signature,second.signature)
        self.assertEqual(first.policy.signature,second.policy.signature)

    def test_policy_is_source_bound_and_rejects_unknown_catalog(self):
        policy = core.PolicyProgram()
        self.assertIn('snapshot',policy._snapshot.__name__)
        self.assertTrue({'backtest/financial/books.py','backtest/financial/metrics.py','backtest/financial/rules.py','backtest/screening.py','backtest/engines/original/schedules.py','backtest/engines/reference/legacy.py','backtest/engines/reference/revalue.py','backtest/inputs/research.py'}<=set(policy.source_hashes))
        self.assertEqual(len(policy.signature),64)
        self.assertTrue(all(node[0]!='var' for name in policy.output_names
                            for node in self.walk(policy.expanded(name))))
        with patch.dict(metrics.METRICS,{'unsupported':dict(label='unknown')}):
            with self.assertRaisesRegex(ValueError,'Unsupported ranking catalog'):
                core.PolicyProgram()

    @staticmethod
    def walk(node):
        yield node
        if node[0] not in ('input','var','const'):
            for child in node[1:]:yield from CandidateTests.walk(child)

    def test_empty_inputs_and_bad_prices_fail_without_scalar_substitution(self):
        empty = sqlite3.connect(':memory:');empty.row_factory=sqlite3.Row
        self.addCleanup(empty.close);empty.executescript(daily.SCHEMA)
        inputs = core.NumericInputs(empty,s);self.addCleanup(inputs.close)
        executor = self.factory(inputs);self.addCleanup(executor.close)
        self.assertEqual(executor.evaluate([],{'filters':[]}),[])
        self.db.execute("UPDATE prices SET price=0 WHERE symbol='A' AND day='2014-06-30'")
        self.db.commit()
        with self.assertRaisesRegex(ValueError,'strictly positive'):core.NumericInputs(self.reader,s)

    def test_declared_row_limit_fails_before_returning_partial_book(self):
        inputs,executor = self.make()
        executor.limits['max_candidate_rows']=1
        with self.assertRaisesRegex(ValueError,'row bound'):
            executor.evaluate([('2015-01-02','2016-01-04','cached')])

    def test_nonmonotonic_prepared_availability_fails_explicitly(self):
        self.db.execute("UPDATE statements SET known='2012-01-01' WHERE symbol='A' AND fiscal='2015-06-30'")
        self.db.commit()
        with self.assertRaisesRegex(ValueError,'temporally ordered'):core.NumericInputs(self.reader,s)


if __name__=='__main__':
    unittest.main()
