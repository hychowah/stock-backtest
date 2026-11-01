"""Report-index proof and complete financial evidence for the indexed pilot."""
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.inputs import research
from backtest.financial import rules, books as financial_books, metrics
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import test_bench_methods as shared
import bench_methods_indexed as indexed

s, robust, baseline, methods = shared.s, shared.robust, shared.baseline, shared.methods


class ReportIndexTests(unittest.TestCase):
    def statement(self, fiscal, *, cap=200e6, ev=250e6, yield_value=.25, **extra):
        day = date.fromisoformat(fiscal)
        return dict(fiscal=day,known=day+rules.LAG,
                    market_cap=cap,enterprise=ev,ebitda=ev*yield_value,
                    **{'yield':yield_value},**extra)

    def check_day(self, books, index, day):
        expected, expected_ranks = financial_books.candidates(books,day)
        actual, actual_ranks = index.at(day)
        self.assertEqual(actual,expected)
        self.assertEqual(list(actual),list(expected))
        for pool in expected:
            self.assertEqual(list(actual[pool]),list(expected[pool]))
            for symbol in expected[pool]:
                self.assertIs(actual[pool][symbol],expected[pool][symbol])
        self.assertEqual(list(actual_ranks.items()),list(expected_ranks.items()))
        return actual,actual_ranks

    def test_every_availability_and_age_boundary_for_both_pools(self):
        broad = {
            'Z': [self.statement('2011-06-30'),self.statement('2012-06-30')],
            'A': [self.statement('2011-06-30'),
                  self.statement('2012-06-30',cap=50e6),
                  self.statement('2012-12-31',yield_value=.4)],
            'EMPTY': [],
            'STALE': [self.statement('2008-06-30')],
        }
        books = financial_books.pools(broad)
        index = indexed.ReportIndex(books,rules)
        days = {date(2000,1,1),date(2020,1,1)}
        for rows in broad.values():
            for row in rows:
                for anchor in (row['known'],row['fiscal']+rules.MAX_AGE):
                    days.update(anchor+timedelta(days=offset) for offset in (-1,0,1))
        for day in sorted(days):
            with self.subTest(day=day):
                self.check_day(books,index,day)
        chosen,_ = self.check_day(books,index,date(2012,11,1))
        self.assertEqual(chosen['cached']['A']['fiscal'],date(2012,6,30))
        self.assertEqual(chosen['legacy']['A']['fiscal'],date(2011,6,30))

    def test_original_buffer_ties_keep_insertion_order_before_price_coverage(self):
        broad = {f'S{number:03}':[self.statement('2014-06-30')]
                 for number in reversed(range(rules.BUFFER+5))}
        books = financial_books.pools(broad)
        index = indexed.ReportIndex(books,rules)
        statements,ranks = self.check_day(books,index,date(2015,1,2))
        self.assertEqual(list(ranks),list(broad)[:rules.BUFFER])
        # Cached-price membership is deliberately absent at this boundary.
        # Missing-price leaders still occupy original-buffer ranks.
        self.assertEqual(len(statements['cached']),rules.BUFFER+5)

    def test_repeated_fiscal_dates_and_same_year_reports_keep_last_row(self):
        rows = [self.statement('2014-06-30',variant=1),
                self.statement('2014-06-30',variant=2),
                self.statement('2014-09-30',variant=3)]
        books = financial_books.pools({'A':rows})
        index = indexed.ReportIndex(books,rules)
        for day in (date(2014,10,1),date(2015,1,2)):
            chosen,_ = self.check_day(books,index,day)
            self.assertIs(chosen['cached']['A'],rows[1 if day.year==2014 else 2])

    def test_invalid_order_is_rejected_instead_of_changing_source_semantics(self):
        first,second = self.statement('2013-06-30'),self.statement('2014-06-30')
        with self.assertRaisesRegex(ValueError,'ordered fiscal'):
            indexed.ReportIndex(({'A':[second,first]},{}),rules)
        second = dict(second,known=first['known']-timedelta(days=1))
        with self.assertRaisesRegex(ValueError,'ordered fiscal'):
            indexed.ReportIndex(({'A':[first,second]},{}),rules)
        with self.assertRaisesRegex(ValueError,'date objects'):
            indexed.ReportIndex(({'A':[dict(first,fiscal=str(first['fiscal']))]},{}),
                                rules)

    def test_policy_constants_are_supplied_and_empty_histories_are_valid(self):
        policy = Mock(MAX_AGE=timedelta(days=100),BUFFER=1)
        books = ({'Z':[self.statement('2014-06-30')],
                  'A':[self.statement('2014-06-30')]},
                 {'Z':[self.statement('2014-06-30')],
                  'A':[self.statement('2014-06-30')]})
        index = indexed.ReportIndex(books,policy)
        self.assertEqual(list(index.at(date(2014,10,1))[1]),['Z'])
        self.assertEqual(index.at(date(2014,10,10)),({'cached':{},'legacy':{}},{}))
        empty = indexed.ReportIndex(({},{}),policy)
        self.assertEqual(empty.at(date(2015,1,1)),({'cached':{},'legacy':{}},{}))


class IndexedFinancialTests(shared.SharedMethodsTests):
    """Run the existing evidence/recovery suite through the indexed evaluator."""

    def setUp(self):
        super().setUp()
        self.model.close()
        self.model = indexed.open_model(self.reader,s)
        self.addCleanup(self.model.close)

    def check_configuration(self, configuration, name):
        reference,summary = self.reference(configuration)
        measurement,evidence = methods.run_request(
            self.model,self.resolver,configuration,self.root/(name+'.sqlite'))
        self.assertTrue(baseline.compare(reference,evidence)['exact'])
        self.assertTrue(baseline.compare(summary,measurement['summary'])['exact'])
        return measurement,evidence

    def test_no_threshold_request_omits_only_unused_threshold_work(self):
        configuration = self.configuration()
        reference,summary = self.reference(configuration)
        with patch.object(metrics,'filter_values',side_effect=AssertionError('Unused threshold work')):
            measurement,evidence = methods.run_request(
                self.model,self.resolver,configuration,self.root/'no-thresholds.sqlite')
        self.assertTrue(baseline.compare(reference,evidence)['exact'])
        self.assertTrue(baseline.compare(summary,measurement['summary'])['exact'])
        self.assertNotIn('threshold_seconds',measurement['stages'])
        self.assertGreater(measurement['stages']['metric_seconds'],0)
        projected_queries = self.resolver.stats['queries']
        eager = methods.Model(self.reader,s)
        self.addCleanup(eager.close)
        before = self.resolver.stats['queries']
        _,eager_evidence = methods.run_request(
            eager,self.resolver,configuration,self.root/'eager.sqlite')
        self.assertTrue(baseline.compare(evidence,eager_evidence)['exact'])
        self.assertLess(projected_queries,self.resolver.stats['queries']-before)

    def test_any_threshold_keeps_the_complete_source_calculator(self):
        configuration = self.configuration(profile='F1')
        reference,summary = self.reference(configuration)
        with patch.object(metrics,'filter_values',wraps=metrics.filter_values) as calculate:
            measurement,evidence = methods.run_request(
                self.model,self.resolver,configuration,self.root/'complete-thresholds.sqlite')
        self.assertGreater(calculate.call_count,0)
        self.assertGreater(measurement['stages']['threshold_seconds'],0)
        self.assertTrue(baseline.compare(reference,evidence)['exact'])
        self.assertTrue(baseline.compare(summary,measurement['summary'])['exact'])

    def test_mixed_thresholds_three_year_ranking_top100_and_rank_slice(self):
        conditions = [dict(field='pb',op='gt',value=0.),
                      dict(field='return_1y',op='gt',value=0.),
                      dict(field='fcf_yield',op='gt',value=-1.)]
        for pool in ('legacy','cached'):
            for first,last in ((1,100),(2,100)):
                with self.subTest(pool=pool,first=first,last=last):
                    configuration = self.configuration(
                        pool=pool,metric='ev_ebitda_3y',rank_from=first,rank_to=last,filters=conditions)
                    self.check_configuration(configuration,f'mixed-{pool}-{first}-{last}')

    def test_leap_anniversary_short_period_and_bankruptcy_match(self):
        options = dict(baseline.options('cached','F2'),min_cap=0.,min_ev=0.)
        configuration = robust.plan(self.db,start='2016-02-29',end='2016-03-02',
                                    months=1,trials=1,seed=42,**options)
        configuration['samples'] = [['2016-02-29','2016-03-01']]
        with patch.object(robust,'plan',return_value=configuration), \
                patch.object(rules,'BANKRUPT',{(2016,'A')}):
            _,evidence = self.check_configuration(configuration,'leap-short-bankruptcy')
        holdings = evidence[0]['periods'][0]['holdings']
        self.assertTrue(holdings)
        bankrupt = next(holding for holding in holdings if holding['symbol']=='A')
        self.assertEqual(bankrupt['return_value'],-1.)
        self.assertEqual(bankrupt['status'],'Bankruptcy')

    def test_actual_adjusted_entry_at_exit_is_excluded_before_ranking(self):
        configuration = self.configuration()
        configuration['samples'] = [['2015-01-02','2015-01-05']]*3
        with patch.object(robust,'plan',return_value=configuration):
            _,evidence = self.check_configuration(configuration,'entry-at-exit')
        for trial in evidence:
            self.assertNotIn('A',{holding['symbol'] for holding in trial['periods'][0]['holdings']})


if __name__ == '__main__':
    unittest.main()
