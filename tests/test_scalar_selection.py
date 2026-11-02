"""Finite scalar selection policy and unchanged survivor/empty portfolio rules."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import copy
from datetime import date
import math
import unittest
from backtest import selection as s, portfolio_results
from test_portfolio_results import holding


def spec(direction='highest', order='filter_first', **changes):
    return dict(ranking=dict(lane='x', direction=direction), selection_order=order, **changes)


def candidate(symbol, value, rank=None, **values):
    return dict(symbol=symbol, candidate_rank=rank, values=dict(x=value, **values))


class ScalarTests(unittest.TestCase):
    def test_both_directions_ties_null_original_ranks_signed_zero(self):
        rows = [candidate('Z', 0., 1), candidate('B', -0.), candidate('A', 0.),
                candidate('L', -2., 4), candidate('H', 2., 5)]
        for direction, expected in [('highest', ['H','A','B','Z','L']), ('lowest', ['L','A','B','Z','H'])]:
            chosen = s.select(rows, spec(direction))['selected']
            self.assertEqual([rows[h['index']]['symbol'] for h in chosen], expected)
            self.assertEqual([h['rank'] for h in chosen], list(range(1,6)))
            zero = next(h['value'] for h in chosen if rows[h['index']]['symbol']=='B')
            self.assertEqual(math.copysign(1, zero), -1)

    def test_no_rounding_adjacent_binary64_and_integer_cast(self):
        rows = [candidate('A', 1.), candidate('B', math.nextafter(1., math.inf))]
        self.assertEqual(s.select(rows, spec(rank_to=1))['selected'][0]['index'], 1)
        rows = [candidate('B', 2**53+1), candidate('A', 2**53)]
        self.assertEqual([h['index'] for h in s.select(rows, spec())['selected']], [1,0])

    def test_rank_first_no_replacement_and_original_ranks(self):
        rows = [candidate('A', 3., 1, y=None), candidate('B', 2., 2, y=1.), candidate('C', 1., 3, y=1.)]
        conditions = [dict(lane='y',op='gt',value=0.)]
        self.assertEqual(s.select(rows,spec(rank_to=2,conditions=conditions))['selected'],
                         [dict(index=1,rank=1,value=2.),dict(index=2,rank=2,value=1.)])
        chosen=s.select(rows,spec(order='rank_first',rank_to=2,conditions=conditions))
        self.assertEqual(chosen,dict(selected=[dict(index=1,rank=2,value=2.)],matches=1))
        self.assertEqual(s.select(rows,spec(order='rank_first',rank_to=1,conditions=conditions))['selected'],[])

    def test_missing_ranking_excludes_and_missing_inactive_lanes_do_not(self):
        rows=[candidate(str(i),value) for i,value in enumerate([None,float('nan'),float('inf'),True,10**1000,-3.,0.])]
        chosen=s.select(rows,spec())['selected']
        self.assertEqual([h['index'] for h in chosen],[6,5])
        self.assertEqual(s.select(rows,spec(conditions=[dict(lane='absent',op='lt',value=1.)]))['selected'],[])

    def test_strict_inclusive_and_metadata_comparisons(self):
        values=dict(x=8.,sector='Energy')
        for op,expected in [('lt',False),('gt',False),('le',True),('ge',True)]:
            self.assertEqual(s.passes(values,[dict(lane='x',op=op,value=8.)]),expected)
        self.assertTrue(s.passes(values,[dict(lane='sector',op='eq',value='Energy')]))
        self.assertFalse(s.passes(values,[dict(lane='exchange',op='eq',value='NYSE')]))
        high=math.nextafter(1.,math.inf)
        self.assertTrue(s.passes(dict(x=high),[dict(lane='x',op='gt',value=1.)]))

    def test_validation_input_detachment_and_cancellation(self):
        for invalid in ({},{'ranking':{'lane':'x'}},spec(direction=None),spec(rank_from=True),spec(rank_to=5001),
                        spec(conditions=[dict(lane='x',op='gt',value=float('inf'))]),spec(conditions=[dict(lane='x',op='eq',value=None)])):
            with self.assertRaises(s.SelectionError):s.select([],invalid)
        with self.assertRaises(s.SelectionError):s.select([candidate('A',1.)]*2,spec())
        rows=[candidate('A',1.)];before=copy.deepcopy(rows)
        s.select(rows,spec());self.assertEqual(rows,before)
        error=RuntimeError('fixture cancellation')
        def stop():raise error
        with self.assertRaises(RuntimeError) as caught:s.select(rows,spec(),stop)
        self.assertIs(caught.exception,error)

    def test_survivor_weights_and_empty_period_preserve_existing_reducer(self):
        rows=[holding('A',1,.5),holding('B',2,-.1),holding('C',3,.3)]
        candidates=[candidate(row['symbol'],3-i,row['candidate_rank'],gate=0. if i==0 else 1.) for i,row in enumerate(rows)]
        selected=s.select(candidates,spec(order='rank_first',rank_to=2,conditions=[dict(lane='gate',op='gt',value=.5)]))['selected']
        survivors=[dict(rows[h['index']],rank=h['rank']) for h in selected]
        a,b,c=date(2020,1,2),date(2020,2,3),date(2020,3,2)
        result=portfolio_results.evaluate([(a,b),(b,c)],lambda entry,exit_day:dict(entry=str(entry),exit=str(exit_day),holdings=survivors if entry==a else [],spy=.1))
        self.assertEqual(result['periods'][0]['holdings'][0]['weight'],1.)
        self.assertEqual(result['periods'][0]['holdings'][0]['rank'],2)
        self.assertEqual(result['periods'][0]['portfolio'],-.1)
        self.assertEqual(result['periods'][1]['names'],0)
        self.assertIsNone(result['growth']);self.assertIsNone(result['cagr'])
        self.assertEqual(rows[1]['rank'],2)

    def test_condition_and_candidate_count_ceilings(self):
        condition=dict(lane='x',op='ge',value=0.)
        self.assertEqual(len(s.validate(spec(conditions=[condition]*s.MAX_CONDITIONS))['conditions']),57)
        with self.assertRaises(s.SelectionError):s.validate(spec(conditions=[condition]*(s.MAX_CONDITIONS+1)))
        with self.assertRaises(s.SelectionError):s.select([candidate(str(i),1.) for i in range(s.MAX_CANDIDATES+1)],spec())


if __name__=='__main__':unittest.main()
