"""Independent fictional arithmetic and complete selected-book contract checks."""

# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))
from copy import deepcopy
from datetime import date, datetime
import json
from pathlib import Path
import sys
import unittest
import weakref
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest import portfolio_results as p


def holding(symbol, rank, ret, *, entry='2020-01-02', exit='2020-02-03', **extra):
    return dict(pool='cached', year=17, symbol=symbol, candidate_rank=None,
        fiscal='2019-06-30', entry=entry, exit=exit, market_cap=150e6,
        enterprise_value=180e6, ebitda=60e6, ebitda_yield=1/3,
        ev_ebitda=3., spread=.3, return_value=ret, status='Marked to date',
        name=None, sector=None, exchange='NYSE', metric_yield=1/3,
        metric_multiple=3., rank=rank, **extra)


class PortfolioTests(unittest.TestCase):
    a, b, c = date(2020,1,2), date(2020,2,3), date(2020,3,2)

    def test_order_signed_contributions_actual_count_compounding_and_detachment(self):
        rows = [holding('Z', 8, -.2), holding('A', 9, .4), holding('M', 10, .1)]
        rows[0]['extension'] = {'preserved': [None, 'value']}
        second = holding('STOP', 4, .25, entry=str(self.b), exit='2020-02-10')
        second['status'] = 'Last available price'
        books = [dict(entry=str(self.a),exit=str(self.b),holdings=rows,spy=.1),
                 dict(entry=str(self.b),exit=str(self.c),holdings=[second],spy=-.1)]
        original = deepcopy(books)
        result = p.evaluate([(self.a,self.b),(self.b,self.c)],lambda a,b:books.pop(0))
        self.assertEqual(result['growth'],(1+sum([-.2,.4,.1])/3)*1.25)
        self.assertEqual(result['spy_growth'],1.1*.9)
        self.assertEqual(result['cagr'],result['growth']**(365.25/60)-1)
        first = result['periods'][0]
        self.assertEqual([h['symbol'] for h in first['holdings']],['Z','A','M'])
        self.assertEqual([h['weight'] for h in first['holdings']],[1/3]*3)
        self.assertEqual([h['contribution_pp'] for h in first['holdings']],[-.2/3*100,.4/3*100,.1/3*100])
        self.assertEqual([v['is_final_period'] for v in result['periods']],[False,True])
        self.assertEqual(result['periods'][1]['holdings'][0]['status'],'Last available price')
        self.assertEqual(set(first['holdings'][0]),set(original[0]['holdings'][0])-{'year'}|{'weight','contribution_pp'})
        rows[0]['extension']['preserved'].clear()
        self.assertEqual(first['holdings'][0]['extension'],{'preserved':[None,'value']})
        self.assertEqual(first['holdings'][0]['candidate_rank'],None)
        self.assertEqual(json.loads(json.dumps(result)),result)

    def test_the_run_labels_only_its_final_mark(self):
        # A stored book records only how a holding exited.
        def books():
            rows = [holding('A', 1, .1), holding('B', 1, .2, entry=str(self.b), exit=str(self.c)),
                    holding('C', 2, .3, entry=str(self.b), exit='2020-02-20'),
                    holding('D', 3, -1., entry=str(self.b), exit=str(self.c))]
            for row, status in zip(rows, ('Scheduled exit', 'Scheduled exit', 'Last available price', 'Bankruptcy')):
                row['status'] = status
            return [dict(entry=str(self.a), exit=str(self.b), holdings=rows[:1], spy=.1),
                    dict(entry=str(self.b), exit=str(self.c), holdings=rows[1:], spy=.1)]
        labels = {}
        for final_mark in (False, True):
            stored = books()
            result = p.evaluate([(self.a, self.b), (self.b, self.c)], lambda a, b: stored[a == self.b], final_mark=final_mark)
            labels[final_mark] = [[h['status'] for h in period['holdings']] for period in result['periods']]
            self.assertEqual(stored, books())  # The label belongs to the run, never to the stored book.
        self.assertEqual(labels[False], [['Scheduled exit'], ['Scheduled exit', 'Last available price', 'Bankruptcy']])
        self.assertEqual(labels[True], [['Scheduled exit'], ['Marked to date', 'Last available price', 'Bankruptcy']])

    def test_common_window_cash_empty_short_and_total_loss(self):
        rows = [holding('LOSS',2,-1.)]
        rows[0]['status']='Bankruptcy'
        first=date(2019,12,30)
        result=p.evaluate([(self.a,self.b)],lambda a,b:dict(entry=str(a),exit=str(b),holdings=rows,spy=.1),common_start=first)
        self.assertEqual(result['growth'],0.)
        self.assertEqual(result['cagr'],-1.)
        self.assertEqual(result['start'],str(first))
        self.assertEqual(result['first_trade'],str(self.a))
        self.assertEqual(result['cash_days'],3)
        self.assertEqual(result['spy_cagr'],1.1**(1/((self.b-first).days/365.25))-1)
        self.assertEqual(result['periods'][0]['holdings'][0]['contribution_pp'],-100.)
        result=p.evaluate([(self.a,self.b),(self.b,self.c)],lambda a,b:dict(entry=str(a),exit=str(b),holdings=[],spy=.1))
        self.assertEqual(result['growth'],1.);self.assertEqual(result['cagr'],0.)
        self.assertEqual([v['names'] for v in result['periods']],[0,0])
        self.assertEqual([v['portfolio'] for v in result['periods']],[0.,0.])
        self.assertEqual(result['spy_growth'],1.1*1.1)

    def test_empty_middle_period_holds_cash_and_resumes_at_next_rebalance(self):
        end=date(2020,4,2)
        def book(entry,exit_day):
            ret={self.a:.1,self.c:-.05}.get(entry)
            rows=[] if ret is None else [holding('A',1,ret,entry=str(entry),exit=str(exit_day))]
            return dict(entry=str(entry),exit=str(exit_day),holdings=rows,spy=.02)
        result=p.evaluate([(self.a,self.b),(self.b,self.c),(self.c,end)],book)
        self.assertEqual([row['portfolio'] for row in result['periods']],[.1,0.,-.05])
        self.assertEqual(result['growth'],1.1*.95)
        self.assertEqual(result['cagr'],(1.1*.95)**(1/((end-self.a).days/365.25))-1)
        self.assertEqual(result['spy_growth'],1.02*1.02*1.02)

    def test_invalid_request_never_calls_provider(self):
        provider=Mock(side_effect=AssertionError('provider must not run'))
        for periods in ([],None,'2020-01-02',[(self.a,self.a)],[(self.b,self.a)],
                [(str(self.a),self.b)],[(datetime(2020,1,2),self.b)],[(self.a,)],
                [(self.a,self.b),(self.a,self.c)],[(self.a,self.b),(self.c,date(2020,4,1))]):
            with self.subTest(periods=periods),self.assertRaises(ValueError):p.evaluate(periods,provider)
        for common_start in (self.b,'2020-01-01',datetime(2020,1,1)):
            with self.assertRaises(ValueError):p.evaluate([(self.a,self.b)],provider,common_start=common_start)
        provider.assert_not_called()

    def test_provider_schema_null_order_identity_and_nonfinite_errors(self):
        good=dict(entry=str(self.a),exit=str(self.b),holdings=[holding('A',1,.1)],spy=.1)
        mutations=[lambda b:b.update(entry=str(self.b)),lambda b:b.update(exit=str(self.a)),
            lambda b:b.update(holdings=None),lambda b:b.update(spy=float('nan')),
            lambda b:b['holdings'][0].pop('fiscal'),lambda b:b['holdings'][0].update(return_value=None),
            lambda b:b['holdings'][0].update(return_value=float('inf')),
            lambda b:b['holdings'][0].update(status='Other'),lambda b:b['holdings'][0].update(rank=True),
            lambda b:b['holdings'][0].update(entry=str(self.b)),
            lambda b:b['holdings'].append(deepcopy(b['holdings'][0])),
            lambda b:b['holdings'].append(holding('B',1,.2))]
        for mutate in mutations:
            book=deepcopy(good);mutate(book)
            with self.subTest(book=book),self.assertRaises(ValueError):
                p.evaluate([(self.a,self.b)],lambda a,b:book)
        with self.assertRaises(ValueError):p.evaluate([(self.a,self.b)],lambda a,b:None)

    def test_checkpoint_and_provider_failures_propagate(self):
        provider=Mock()
        error=RuntimeError('fictional interruption')
        with self.assertRaises(RuntimeError) as raised:
            p.evaluate([(self.a,self.b)],provider,checkpoint=Mock(side_effect=error))
        self.assertIs(raised.exception,error);provider.assert_not_called()
        provider.side_effect=error
        with self.assertRaises(RuntimeError) as raised:p.evaluate([(self.a,self.b)],provider)
        self.assertIs(raised.exception,error)

    def test_incremental_reducer_matches_collector_before_sink_mutation(self):
        rows=[holding('A',1,-.2),holding('B',2,.4)]
        books=[dict(entry=str(self.a),exit=str(self.b),holdings=rows,spy=.1),
               dict(entry=str(self.b),exit=str(self.c),holdings=[],spy=-.1)]
        pairs=[(self.a,self.b),(self.b,self.c)]
        expected=p.evaluate(pairs,lambda *args:books.pop(0),common_start=date(2019,12,30))
        books=[dict(entry=str(self.a),exit=str(self.b),holdings=rows,spy=.1),
               dict(entry=str(self.b),exit=str(self.c),holdings=[],spy=-.1)]
        emitted=[]
        def emit(period):
            emitted.append(deepcopy(period))
            # Emission cannot let a sink change already computed finances.
            period['portfolio']=999.;period['spy']=999.;period['holdings'].clear()
        summary=p.evaluate_into(pairs,lambda *args:books.pop(0),emit,common_start=date(2019,12,30))
        self.assertNotIn('periods',summary)
        self.assertEqual(dict(periods=emitted,**summary),expected)

    def test_incremental_reducer_releases_previous_book_and_propagates_sink_failure(self):
        class Book(dict): pass
        previous=None;calls=[]
        def select(entry,exit_day):
            nonlocal previous
            if previous is not None:self.assertIsNone(previous())
            book=Book(entry=str(entry),exit=str(exit_day),holdings=[],spy=.1)
            previous=weakref.ref(book);calls.append(entry)
            return book
        summary=p.evaluate_into([(self.a,self.b),(self.b,self.c)],select,lambda value:None)
        self.assertEqual(calls,[self.a,self.b]);self.assertIsNone(previous())
        self.assertEqual(summary['cagr'],0.)
        calls.clear();error=OSError('fictional sink failure')
        with self.assertRaises(OSError) as raised:
            p.evaluate_into([(self.a,self.b),(self.b,self.c)],select,Mock(side_effect=error))
        self.assertIs(raised.exception,error);self.assertEqual(calls,[self.a])


if __name__=='__main__':unittest.main()
