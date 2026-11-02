"""Synthetic legacy SQL/browser/scalar parity; no financial cache is read."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from copy import deepcopy
import json
import math
import sqlite3
import subprocess
import unittest
from unittest.mock import patch
from backtest import screening, selection
from backtest.financial import metrics
from backtest.inputs import research
from website.rendering import data

ROOT=Path(__file__).resolve().parents[1]


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close);self.db.executescript(research.SCHEMA)
        self.db.execute('INSERT INTO metadata VALUES(?,?)',('latest',json.dumps(dict(asof='2017-01-03'))))
        for year in (2015,2016):
            self.db.execute('INSERT INTO periods VALUES(?,?,?,?,?,?,?)',(year,f'{year}-01-02',f'{year+1}-01-02',.1,.02,8,8))
        self.rows=[]
        for symbol,score,cap,rank,sector in [('A',.4,200e6,None,'Energy'),('B',.4,300e6,2,'Technology'),
            ('C',.4,400e6,2,'Technology'),('D',.2,500e6,4,'Energy'),('N',-.1,500e6,5,'Energy'),
            ('Z',-0.,500e6,6,'Energy'),('Y',0.,500e6,None,None),('M',.9,500e6,1,'Technology')]:
            self.db.execute('INSERT INTO companies VALUES(?,?,?,?)',(symbol,symbol,'NYSE',sector))
            self.rows.append(dict(symbol=symbol,score=score,cap=cap,candidate_rank=rank,sector=sector))
            for pool in ('legacy','cached'):
                for year in (2015,2016):
                    self.db.execute('INSERT INTO snapshots VALUES('+','.join('?'*15)+')',
                        (pool,year,symbol,rank,'2014-06-30',f'{year}-01-02',f'{year+1}-01-02',cap,200e6,20e6,score,9.,score-.02,.1,'Scheduled exit'))
                self.db.execute('INSERT INTO latest_snapshots VALUES('+','.join('?'*12)+')',
                    (pool,symbol,rank,'2016-06-30','2016-09-28','2017-01-03',10.,cap,200e6,score,9.,score-.02))
                for mode,years in [('historical',(2015,2016)),('latest',(0,))]:
                    for year in years:
                        for metric in metrics.METRICS:
                            if symbol!='M':
                                # Pair members intentionally are not reciprocals.
                                self.db.execute('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',
                                    (mode,pool,year,symbol,metric,17. if metric=='ev_ebitda' else 29.,score if metric=='ev_ebitda' else score/2))
                        for field in metrics.FILTERS:
                            if symbol in ('B','C','D'):
                                self.db.execute('INSERT INTO filter_values VALUES(?,?,?,?,?,?)',
                                    (mode,pool,year,symbol,field,10. if symbol=='B' else 20. if symbol=='C' else -5.))

    def dataset(self):
        self.db.commit()
        def connect():
            db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row;self.db.backup(db);return db
        with patch.object(data,'connect',side_effect=connect):return data.load_screening_data()

    def browser(self,payload):
        code="""
const fs=require('fs'),assert=require('assert'),engine=require(process.argv[1]);
const p=JSON.parse(fs.readFileSync(0,'utf8')),answer={};
if(p.cases)answer.cases=p.cases.map(o=>{
 const saved=JSON.stringify(o),h=engine.screen(p.dataset,{first:2015,last:2016,...o}),l=engine.latestScreen(p.dataset,o);
 assert.equal(JSON.stringify(o),saved);
 return {historical:h.years.map(y=>y.holdings.map(x=>[x.symbol,x.rank,x.metric_multiple,x.metric_yield])),latest:l.stocks.map(x=>[x.symbol,x.rank,x.metric_multiple,x.metric_yield]),matches:l.matches,growth:h.growth,cagr:h.cagr,empty:h.empty_years};
});
if(p.scalar)answer.scalar=p.scalar.map(c=>engine.selectValues(c.rows,c.specification));
process.stdout.write(JSON.stringify(answer));
"""
        output=subprocess.run(['node','-e',code,str(ROOT/'website/browser/screener.js')],
            input=json.dumps(payload,allow_nan=False),text=True,capture_output=True,check=True)
        return json.loads(output.stdout)

    def sql(self,options,latest=False):
        rows=screening.latest(self.db,**options) if latest else screening.historical(self.db,first=2015,last=2016,**options)
        compact=lambda group:[[h['symbol'],h['rank'],h['metric_multiple'],h['metric_yield']] for h in group]
        return compact(rows) if latest else [compact([h for h in rows if h['year']==year]) for year in (2015,2016)]

    def expected(self,options):
        # Characterize the pre-adapter contract independently of its translation.
        o=dict(rank_from=1,rank_to=50,metric='ev_ebitda',min_cap=100e6,min_ev=50e6,min_yield=0.,
            max_cap=None,max_multiple=None,sector=None,exchange=None,filters=None,selection_order='filter_first',**{})
        o.update(options)
        multiple=17. if o['metric']=='ev_ebitda' else 29.
        def passing(row):
            score=row['score'] if o['metric']=='ev_ebitda' else row['score']/2
            if not (row['cap']>=o['min_cap'] and 200e6>=o['min_ev'] and score>=o['min_yield']):return False
            if o['max_cap'] is not None and row['cap']>o['max_cap']:return False
            if o['max_multiple'] is not None and multiple>o['max_multiple']:return False
            if o['sector'] is not None and row['sector']!=o['sector']:return False
            if o['exchange'] is not None and o['exchange']!='NYSE':return False
            for c in o['filters'] or []:
                value={'B':10.,'C':20.,'D':-5.}.get(row['symbol'])
                if value is None or not (value<c['value'] if c['op']=='lt' else value>c['value']):return False
            return True
        rows=[row for row in self.rows if row['symbol']!='M']
        if o['selection_order']=='filter_first':rows=[row for row in rows if passing(row)]
        rows=sorted(rows,key=lambda row:(-row['score'],row['candidate_rank'] is not None,row['candidate_rank'] or 0,row['symbol']))
        selected=[(rank,row) for rank,row in enumerate(rows,1) if o['rank_from']<=rank<=o['rank_to']]
        if o['selection_order']=='rank_first':selected=[item for item in selected if passing(item[1])]
        return [[row['symbol'],rank,multiple,row['score'] if o['metric']=='ev_ebitda' else row['score']/2] for rank,row in selected]

    def test_every_filter_metric_pool_order_and_mode_preserves_original_values(self):
        conditions=[{},dict(min_cap=300e6),dict(max_cap=300e6),dict(min_ev=200e6),dict(min_yield=.2),
            dict(max_multiple=17.),dict(sector='Technology'),dict(exchange='Unknown')]
        conditions += [dict(filters=[dict(field=field,op=op,value=value)]) for field in metrics.FILTERS
                       for op,value in [('gt',10.),('lt',10.),('gt',-6.)]]
        cases=[dict(pool=pool,metric=metric,selection_order=order,rank_from=first,rank_to=last,**condition)
               for pool in ('legacy','cached') for metric in metrics.METRICS for order in ('filter_first','rank_first')
               for first,last in ((1,2),(2,4)) for condition in conditions]
        before=deepcopy(cases);actual=self.browser(dict(dataset=self.dataset(),cases=cases))['cases']
        for options,result in zip(cases,actual):
            expected=self.expected(options)
            self.assertEqual(self.sql(options),[expected,expected],options)
            self.assertEqual(result['historical'],[expected,expected],options)
            self.assertEqual(self.sql(options,True),expected,options)
            self.assertEqual(result['latest'],expected,options)
            if options['selection_order']=='rank_first':self.assertEqual(result['matches'],len(expected))
        self.assertEqual(cases,before)

    def test_default_inclusive_bounds_signed_zero_ties_and_missing_pairs(self):
        self.assertEqual(self.sql({},True),self.expected({}))
        self.assertEqual([row[:2] for row in self.sql({},True)],[['A',1],['B',2],['C',3],['D',4],['Y',5],['Z',6]])
        self.assertEqual(self.sql(dict(rank_to=1,selection_order='rank_first',sector='Technology'),True),[])
        self.assertEqual([row[:2] for row in self.sql(dict(rank_to=1,sector='Technology'),True)],[['B',1]])
        self.assertEqual([row[:2] for row in self.sql(dict(rank_from=2,rank_to=3,selection_order='rank_first',min_cap=400e6),True)],[['C',3]])
        self.assertEqual(self.sql(dict(min_cap=300e6,max_cap=300e6,min_ev=200e6,min_yield=.4,max_multiple=17.),True),[['B',1,17.,.4]])

    def test_strict_display_threshold_keeps_adjacent_binary64_values(self):
        low,high=13.501116090704034,13.501116090704036
        self.assertGreater(high,low);self.assertEqual(high/100,low/100)
        self.db.execute("UPDATE filter_values SET value=? WHERE field='profit_margin' AND symbol='B'",(high,))
        options=dict(filters=[dict(field='profit_margin',op='gt',value=low)])
        expected=[['B',1,17.,.4],['C',2,17.,.4]]
        self.assertEqual(self.sql(options,True),expected)
        result=self.browser(dict(dataset=self.dataset(),cases=[options]))['cases'][0]
        self.assertEqual(result['latest'],expected)
        self.assertEqual(result['historical'],[expected,expected])

    def test_maximum_legacy_predicates_and_long_metadata_remain_accepted(self):
        filters=[dict(field='pe',op='gt',value=0.)]*50
        options=dict(max_cap=400e6,max_multiple=17.,sector='Technology',exchange='NYSE',filters=filters)
        self.assertEqual(len(screening.legacy_specification(**options)['conditions']),57)
        cases=[options,dict(sector='x'*1024),dict(exchange='x'*1024),dict(min_cap=None)]
        result=self.browser(dict(dataset=self.dataset(),cases=cases))['cases']
        self.assertEqual(result[0]['latest'],[['B',1,17.,.4],['C',2,17.,.4]])
        self.assertEqual(self.sql(options,True),result[0]['latest'])
        for options,actual in zip(cases[1:3],result[1:3]):
            self.assertEqual(self.sql(options,True),[]);self.assertEqual(actual['latest'],[])
        # SQL NULL comparisons and the browser's existing null-to-zero behavior
        # stay with each legacy validator/runtime; neither becomes a new error.
        self.assertEqual(self.sql(cases[-1],True),[])
        self.assertTrue(result[-1]['latest'])

    def test_legacy_populations_are_not_limited_by_callable_candidate_ceiling(self):
        self.db.execute('INSERT INTO companies VALUES(?,?,?,?)',('BIG','BIG','NYSE','Energy'))
        # More than 8,192 rows across one prepared pool, beyond callable limits.
        for i in range(8200):
            symbol=f'P{i:05d}'
            self.db.execute('INSERT INTO companies VALUES(?,?,?,?)',(symbol,symbol,'NYSE','Energy'))
            self.db.execute('INSERT INTO latest_snapshots VALUES('+','.join('?'*12)+')',('cached',symbol,i+10,'2016-06-30','2016-09-28','2017-01-03',10.,200e6,200e6,.3,4.,.2))
            self.db.execute('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',('latest','cached',0,symbol,'ev_ebitda',4.,.3))
        options=dict(pool='cached',rank_to=1)
        self.assertEqual(self.sql(options,True),[['A',1,17.,.4]])
        actual=self.browser(dict(dataset=self.dataset(),cases=[options]))['cases'][0]
        self.assertEqual(actual['latest'],[['A',1,17.,.4]])
        self.assertEqual(actual['matches'],8206)

    def test_empty_years_keep_unavailable_full_period_growth(self):
        options=dict(filters=[dict(field='pe',op='gt',value=1000.)])
        actual=self.browser(dict(dataset=self.dataset(),cases=[options]))['cases'][0]
        self.assertEqual(self.sql(options),[[],[]]);self.assertEqual(actual['historical'],[[],[]])
        self.assertEqual(actual['empty'],[2015,2016]);self.assertIsNone(actual['growth']);self.assertIsNone(actual['cagr'])

    def test_browser_scalar_lanes_match_python_both_directions_and_orders(self):
        rows=[dict(symbol=symbol,candidate_rank=rank,values=dict(x=value,y=gate)) for symbol,rank,value,gate in
            [('A',None,-0.,1.),('B',None,0.,None),('C',1,-2.,1.),('D',2,math.nextafter(1.,math.inf),1.),('E',3,1.,1.),('M',4,None,1.)]]
        cases=[]
        for direction in ('highest','lowest'):
            for order in ('filter_first','rank_first'):
                specification=dict(ranking=dict(lane='x',direction=direction),rank_from=1,rank_to=3,selection_order=order,
                    conditions=[dict(lane='y',op='gt',value=0.)])
                cases.append(dict(rows=rows,specification=specification))
        actual=self.browser(dict(scalar=cases))['scalar']
        for case,result in zip(cases,actual):self.assertEqual(result,selection.select(case['rows'],case['specification']))
        self.assertEqual([rows[item['index']]['symbol'] for item in actual[0]['selected']],['D','E','A'])
        self.assertEqual([rows[item['index']]['symbol'] for item in actual[2]['selected']],['C','A','E'])


if __name__=='__main__':unittest.main()
