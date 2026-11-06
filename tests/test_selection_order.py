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
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
from backtest.inputs import daily
from backtest.inputs import research as r
from website.rendering import data as dataset


def dated(db, *, first=2015, last=2015, **options):
    """Select the dated book rows of period ids first through last."""
    return screening.select(db, period=(first, last), **options)


class SelectionOrderTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close);self.db.executescript(r.SCHEMA+daily.DATED_SCHEMA)
        self.db.execute('INSERT INTO metadata VALUES(?,?)',('latest',json.dumps(dict(asof='2017-01-03'))))
        for year in (2015,2016):
            self.db.execute('INSERT INTO periods VALUES(?,?,?,?,?,?,?)',(year,f'{year}-01-02',f'{year+1}-01-02',.1,.02,6,6))
        # B/C tie on yield and candidate rank; symbol resolves the tie. M has
        # no selected metric, so it cannot consume a rank in either policy.
        for symbol,score,cap,candidate,sector in [('A',.5,100e6,None,'Energy'),('B',.4,200e6,2,'Technology'),('C',.4,300e6,2,'Technology'),('D',.2,400e6,4,'Energy'),('M',.9,500e6,1,'Technology')]:
            self.db.execute('INSERT INTO companies VALUES(?,?,?,?)',(symbol,symbol,'NYSE',sector))
            for pool in ('legacy','cached'):
                for year in (2015,2016):
                    self.db.execute('INSERT INTO snapshots VALUES('+','.join('?'*15)+')',
                                    (pool,year,symbol,candidate,'2014-06-30',f'{year}-01-02',f'{year+1}-01-02',cap,200e6,score*200e6,score,1/score,score-.02,.1,'Scheduled exit'))
                self.db.execute('INSERT INTO latest_snapshots VALUES('+','.join('?'*12)+')',
                                (pool,symbol,candidate,'2016-06-30','2016-09-28','2017-01-03',10,cap,200e6,score,1/score,score-.02))
                for mode,years in [('historical',(2015,2016)),('latest',(0,))]:
                    for year in years:
                        if symbol!='M':
                            self.db.execute('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',(mode,pool,year,symbol,'ev_ebitda',1/score,score))
                        if symbol in ('B','C'):
                            self.db.execute('INSERT INTO filter_values VALUES(?,?,?,?,?,?)',(mode,pool,year,symbol,'pe',10))

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
        self.assertEqual([(h['year'],h['symbol'],h['rank']) for h in rows],[(2015,'B',2),(2016,'B',2)])
        self.assertEqual(self.ids(screening.latest,rank_from=2,rank_to=3,selection_order='rank_first'),[('B',2),('C',3)])

    def test_browser_sql_latest_parity_in_both_pools_orders_and_ranges(self):
        def copy_connection():
            db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
            self.db.backup(db);return db
        self.db.commit()
        with patch.object(dataset,'connect',side_effect=copy_connection):prepared=dataset.load_screening_data()
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
