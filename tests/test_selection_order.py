"""Filter/rank ordering, shortlist ranks and SQL/browser agreement. Offline only."""

import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0,str(_PackagePath(__file__).resolve().parents[1]))
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest import screening
from pathlib import Path
import json
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
from backtest.inputs import book_store
from website.rendering import data as dataset
sys.path.insert(0,str(ROOT/'tests'))
import book_store_fixture as store


def dated(db, *, first=2015, last=2015, **options):
    """Select the rows of the dated books that enter in years first through last, book by book."""
    pool=options.get('pool','legacy')
    return [row for year in range(first,last+1)
            for row in screening.select(db,book=book_store.find(db,f'{year}-01-02',f'{year+1}-01-02',pool),**options)]


class SelectionOrderTests(unittest.TestCase):
    def setUp(self):
        self.db=store.connection();self.addCleanup(self.db.close)
        content={key:({},{},{}) for key in (2015,2016,'latest')}
        # B/C tie on yield and candidate rank; symbol resolves the tie. M has
        # no selected metric, so it cannot consume a rank in either policy.
        for symbol,score,cap,candidate,sector in [('A',.5,100e6,None,'Energy'),('B',.4,200e6,2,'Technology'),('C',.4,300e6,2,'Technology'),('D',.2,400e6,4,'Energy'),('M',.9,500e6,1,'Technology')]:
            store.company(self.db,symbol,sector=sector)
            for pool in ('legacy','cached'):
                for year in (2015,2016):
                    content[year][0].setdefault(pool,{})[symbol]=dict(candidate_rank=candidate,fiscal='2014-06-30',known='2014-09-28',
                              entry=f'{year}-01-02',price=10.,exit=f'{year+1}-01-02',market_cap=cap,enterprise_value=200e6,
                              ebitda=score*200e6,ebitda_yield=score,ev_ebitda=1/score,spread=score-.02,return_value=.1,
                              status='Scheduled exit')
                content['latest'][0].setdefault(pool,{})[symbol]=dict(candidate_rank=candidate,fiscal='2016-06-30',known='2016-09-28',
                          entry='2017-01-03',price=10,market_cap=cap,enterprise_value=200e6,ebitda=score*200e6,
                          ebitda_yield=score,ev_ebitda=1/score,spread=score-.02)
                for _,pairs,values in content.values():
                    if symbol!='M':
                        pairs.setdefault(pool,{})[symbol]={'ev_ebitda':(1/score,score)}
                    if symbol in ('B','C'):
                        values.setdefault(pool,{})[symbol]={'pe':10}
        for year in (2015,2016):
            store.book(self.db,f'{year}-01-02',f'{year+1}-01-02',spy=.1,candidates=6,rows=content[year][0],
                       metrics=content[year][1],values=content[year][2])
        store.book(self.db,'2017-01-03',None,candidates=6,rows=content['latest'][0],metrics=content['latest'][1],
                   values=content['latest'][2])

    def ids(self,select,**options):
        if select is dated:options=dict(first=2015,last=2015,**options)
        return [(h['symbol'],h['rank']) for h in select(self.db,**options)]

    def test_filter_first_default_and_rank_first_does_not_refill(self):
        for select in (dated,screening.latest):
            for pool in ('legacy','cached'):
                options=dict(pool=pool,rank_to=2,min_cap=150e6)
                self.assertEqual(self.ids(select,**options),[('B',1),('C',2)])
                self.assertEqual(self.ids(select,**options,selection_order='filter_first'),[('B',1),('C',2)])
                self.assertEqual(self.ids(select,**options,selection_order='rank_first'),[('B',2)])
                self.assertEqual(self.ids(select,pool=pool,rank_from=2,rank_to=3,selection_order='rank_first',min_cap=250e6),[('C',3)])

    def test_all_user_conditions_move_together_and_missing_values_fail(self):
        for select in (dated,screening.latest):
            for condition in [dict(min_cap=150e6),dict(max_cap=300e6,sector='Technology'),dict(filters=[dict(field='pe',op='lt',value=11)])]:
                self.assertEqual(self.ids(select,rank_to=1,**condition),[('B',1)])
                self.assertEqual(self.ids(select,rank_to=1,selection_order='rank_first',**condition),[])
            self.assertEqual(self.ids(select,rank_from=3,rank_to=4,selection_order='rank_first',min_yield=.3,max_multiple=3,exchange='NYSE'),[('C',3)])
            with self.assertRaisesRegex(ValueError,'filter first or rank first'):
                select(self.db,selection_order='unknown')

    def test_years_rank_independently_and_ties_are_stable(self):
        rows=dated(self.db,first=2015,last=2016,rank_to=2,min_cap=150e6,selection_order='rank_first')
        self.assertEqual([(h['entry'][:4],h['symbol'],h['rank']) for h in rows],[('2015','B',2),('2016','B',2)])
        self.assertEqual(self.ids(screening.latest,rank_from=2,rank_to=3,selection_order='rank_first'),[('B',2),('C',3)])

    def test_browser_sql_latest_parity_in_both_pools_orders_and_ranges(self):
        prepared=dataset.load_screening_data(self.db)
        self.assertEqual(prepared['latest']['metadata'],dict(asof='2017-01-03',eligible_financials=6))
        cases=[]
        for pool in ('legacy','cached'):
            for order in ('filter_first','rank_first'):
                for conditions in ({},{'min_cap':150e6},{'sector':'Technology'},{'filters':[dict(field='pe',op='lt',value=11)]},{'filters':[dict(field='pe',op='lt',value=10)]}):
                    for first,last in ((1,1),(1,2),(2,3),(3,4)):
                        options=dict(pool=pool,selection_order=order,rank_from=first,rank_to=last,**conditions)
                        cases.append(dict(options=options,latest=self.ids(screening.latest,**options)))
        code="""
const assert=require('assert'),fs=require('fs'),engine=require(process.argv[1]);
const {dataset,cases}=JSON.parse(fs.readFileSync(0,'utf8'));
for(const c of cases){
 const latest=engine.latestScreen(dataset,c.options);
 assert.deepStrictEqual(latest.stocks.map(h=>[h.symbol,h.rank]),c.latest);
 if(c.options.selection_order==='rank_first')assert.equal(latest.matches,latest.stocks.length);
}
assert.throws(()=>engine.latestScreen(dataset,{selection_order:'unknown'}),/filter first or rank first/);
"""
        subprocess.run(['node','-e',code,str(ROOT/'website'/'browser'/'screener.js')],
                       input=json.dumps(dict(dataset=prepared,cases=cases)),text=True,check=True)


if __name__=='__main__':unittest.main()
