"""Artifact-backed differential temporal checks using private fictional inputs."""
from datetime import date, timedelta
import json
import time
import unittest
from unittest.mock import patch

import test_numerical_generation as fixtures
import numerical_generation as ng
from numerical_temporal import TemporalEvaluator, _reports, _resolve
import numpy as np


class TemporalTests(unittest.TestCase):
    setUp = fixtures.GenerationTests.setUp
    prepare = fixtures.GenerationTests.prepare
    attach = fixtures.GenerationTests.attach

    def evaluator(self):
        self.prepare()
        inputs = self.attach()
        evaluator = TemporalEvaluator(inputs)
        self.addCleanup(evaluator.close)
        return inputs, evaluator

    def test_price_matrix_matches_sql_including_gaps_and_separate_series(self):
        # An independent valuation-only date and an adjusted-only date.
        self.db.execute("INSERT INTO prices VALUES('A','2015-01-03',12,NULL)")
        self.db.execute("UPDATE prices SET price=NULL WHERE symbol='A' AND day='2015-01-05'")
        self.db.execute("DELETE FROM prices WHERE symbol='B' AND day BETWEEN '2015-01-05' AND '2015-01-15'")
        self.db.commit()
        inputs, evaluator = self.evaluator()
        requests = [(sid, day, column, forward)
            for sid in [-1, *range(len(inputs.symbols))]
            for day in ('2010-01-01','2014-06-29','2014-06-30','2015-01-02',
                        '2015-01-03','2015-01-04','2015-01-05','2015-01-10',
                        '2016-05-31','2016-06-01','2017-01-01')
            for column in (0,1) for forward in (False,True)]
        symbols = np.array([r[0] for r in requests], dtype=np.int64)
        targets = np.array([date.fromisoformat(r[1]).toordinal() for r in requests],dtype=np.int64)
        columns = np.array([r[2] for r in requests],dtype=np.int64)
        forwards = np.array([r[3] for r in requests],dtype=np.bool_)
        began = time.perf_counter()
        actual, values = evaluator.resolve(symbols, targets, columns, forwards)
        first = time.perf_counter()-began
        began = time.perf_counter()
        evaluator.resolve(symbols, targets, columns, forwards)
        warm = time.perf_counter()-began
        for i,(sid,day,column,forward) in enumerate(requests):
            expected = None if sid<0 else self.s.price(self.db,inputs.symbols[sid],date.fromisoformat(day),
                ('price','adjusted')[column],forward=forward)
            if expected is None:
                self.assertEqual(actual[i],0); self.assertTrue(np.isnan(values[i]))
            else:
                self.assertEqual(actual[i],expected[0].toordinal())
                self.assertEqual(values[i],expected[1])
            for slack in (0,4,7,10):
                observed = None if actual[i]==0 or abs(int(actual[i])-int(targets[i]))>slack else (date.fromordinal(int(actual[i])),float(values[i]))
                expected_slack = None if sid<0 else self.s.price(self.db,inputs.symbols[sid],date.fromisoformat(day),
                    ('price','adjusted')[column],forward=forward,slack=slack)
                self.assertEqual(observed,expected_slack)
        self.assertTrue(_resolve.nopython_signatures)
        print(json.dumps(dict(check='temporal-prices',queries=len(requests),first_seconds=first,
                             warm_seconds=warm,maximum_absolute=0.,maximum_relative=0.)))

    def test_reports_strict_known_inclusive_age_variants_pools_and_order(self):
        # Relax only the fixture constraint to exercise stable equal-date variants.
        self.db.executescript("CREATE TABLE variants AS SELECT * FROM statements; DROP TABLE statements; ALTER TABLE variants RENAME TO statements;")
        # Interleave original order with alphabetical order and same-date variants.
        for symbol in ('ZZLAST','AAFIRST'):
            self.db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',
                (symbol,'2014-06-30','2014-09-28',150e6,180e6,60e6,1/3))
        self.db.execute("INSERT INTO statements VALUES('ZZLAST','2014-06-30','2014-09-28',150000000,180000000,90000000,0.5)")
        self.db.execute("INSERT INTO prices VALUES('PRICEONLY','2015-01-02',10,10)")
        self.db.commit()
        inputs,evaluator = self.evaluator()
        self.assertNotEqual(list(inputs.symbols), sorted(inputs.symbols))
        self.assertEqual([inputs.symbols[i] for i in inputs.symbol_sort],sorted(inputs.symbols))
        days = sorted({date(2000,1,1),date(2030,1,1)} | {
            anchor+timedelta(days=delta) for row in inputs.report_rows
            for anchor in (row['known'],row['fiscal']+self.s.financial_books.run.MAX_AGE)
            for delta in (-1,0,1)})
        selected = evaluator.select_reports(np.array([d.toordinal() for d in days],dtype=np.int32))
        books = self.s.histories(self.db)
        for matrix, book in zip(selected,books,strict=True):
            for i,day in enumerate(days):
                for sid,symbol in enumerate(inputs.symbols):
                    expected = self.s.financial_books.run.latest_statement(book.get(symbol,[]),day)
                    identity = int(matrix[i,sid])
                    if expected is None:self.assertEqual(identity,-1)
                    else:self.assertEqual(inputs.report_rows[identity],expected)
        self.assertTrue(_reports.nopython_signatures)

    def test_snapshot_calendar_limits_and_short_intervals_match_source(self):
        inputs,evaluator = self.evaluator()
        entry=date(2015,1,2)
        statement=self.s.financial_books.run.latest_statement(self.s.histories(self.db)[0]['A'],entry)
        def native(day,column,forward,slack):
            ds,vs=evaluator.resolve(np.array([inputs.symbol_ids['A']],dtype=np.int32),
                np.array([day.toordinal()],dtype=np.int32),np.array([int(column=='adjusted')],dtype=np.int8),
                np.array([forward],dtype=np.bool_))
            return None if ds[0]==0 or abs(int(ds[0])-day.toordinal())>slack else (date.fromordinal(int(ds[0])),float(vs[0]))
        sql=lambda day,column,forward,slack:self.s.price(self.db,'A',day,column,forward,slack)
        for exit_day in (entry,entry+timedelta(days=1),date(2015,1,5),date(2015,1,6),date(2016,1,4)):
            for bankruptcy in (False,True):
                expected=self.s.financial_books.snapshot(statement,entry,exit_day,sql,bankruptcy)
                actual=self.s.financial_books.snapshot(statement,entry,exit_day,native,bankruptcy)
                self.assertEqual(actual,expected)
        for name,array in inputs._arrays.items():self.assertFalse(array.flags.writeable,name)

    def test_bad_requests_fail_before_native_indexing(self):
        inputs,evaluator=self.evaluator()
        valid=[np.array([0],dtype=np.int32),np.array([date(2015,1,2).toordinal()],dtype=np.int32),
               np.array([0],dtype=np.int8),np.array([True])]
        cases=[(0,[-2]),(0,[len(inputs.symbols)]),(0,[2**63]),(0,[0.5]),(0,[[0]]),
               (1,[0]),(1,[date.max.toordinal()+1]),(1,[float('nan')]),(2,[-1]),(2,[2]),
               (2,[False]),(3,[1]),(3,[[True]]),(1,np.array([],dtype=np.int32))]
        with patch('numerical_temporal._resolve',side_effect=AssertionError('native entered')):
            for slot,bad in cases:
                args=valid.copy();args[slot]=bad
                with self.subTest(slot=slot,bad=bad),self.assertRaises(ValueError):evaluator.resolve(*args)
        with patch('numerical_temporal._reports',side_effect=AssertionError('native entered')):
            for entries in ([[1]],np.array([0]),np.array([1.1]),np.array([True])):
                with self.assertRaises(ValueError):evaluator.select_reports(entries)
        days,values=evaluator.resolve(*(np.array([],dtype=d) for d in (np.int32,np.int32,np.int8,np.bool_)))
        self.assertEqual(len(days),0);self.assertEqual(len(values),0)
        self.assertEqual(evaluator.select_reports(np.array([],dtype=np.int32))[0].shape,(0,len(inputs.symbols)))

    def test_version_and_lifetime_rejection(self):
        inputs,evaluator=self.evaluator()
        for version in (None,2,True):
            with patch.object(inputs,'temporal_version',version),self.assertRaisesRegex(ValueError,'version'):
                TemporalEvaluator(inputs)
        evaluator.close();evaluator.close()
        self.assertFalse(inputs.closed)
        with self.assertRaisesRegex(ValueError,'closed'):evaluator.select_reports(np.array([1],dtype=np.int32))
        evaluator=TemporalEvaluator(inputs)
        inputs.close()
        with self.assertRaisesRegex(ValueError,'closed'):evaluator.select_reports(np.array([1],dtype=np.int32))
        evaluator.close()
        with self.assertRaisesRegex(ValueError,'closed'):TemporalEvaluator(inputs)

    def test_loader_close_is_rejected_without_borrowing_empty_buffers(self):
        inputs=fixtures.NumericInputs(self.fixture.reader,self.s)
        evaluator=TemporalEvaluator(inputs)
        inputs.close()
        try:
            with self.assertRaisesRegex(ValueError,"closed"):
                evaluator.select_reports(np.array([1],dtype=np.int32))
        finally:evaluator.close()

    def test_artifact_missing_or_unsupported_temporal_contract_is_rejected(self):
        self.binding.pop('temporal_version')
        with self.assertRaisesRegex(ValueError,'temporal'):self.prepare()
        for version in (None,2,True):
            self.binding['temporal_version']=version
            with self.subTest(version=version),self.assertRaisesRegex(ValueError,'temporal'):
                self.prepare()


if __name__=='__main__':unittest.main()
