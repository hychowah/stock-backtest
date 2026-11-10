"""Synthetic legacy SQL/browser/scalar parity; no financial cache is read."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from copy import deepcopy
import json
import math
import subprocess
import unittest
from backtest import screening, selection
from backtest.financial import metrics
from website.rendering import data
import book_store_fixture as store

ROOT=Path(__file__).resolve().parents[1]


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.db=store.connection();self.addCleanup(self.db.close)
        # Two dated books and the latest book; stored() writes them through the book store once.
        self.content={key:({},{},{}) for key in (2015,2016,'latest')}
        self.books=[];self.latest=None
        self.rows=[]
        for symbol,score,cap,rank,sector in [('A',.4,200e6,None,'Energy'),('B',.4,300e6,2,'Technology'),
            ('C',.4,400e6,2,'Technology'),('D',.2,500e6,4,'Energy'),('N',-.1,500e6,5,'Energy'),
            ('Z',-0.,500e6,6,'Energy'),('Y',0.,500e6,None,None),('M',.9,500e6,1,'Technology')]:
            store.company(self.db,symbol,sector=sector)
            self.rows.append(dict(symbol=symbol,score=score,cap=cap,candidate_rank=rank,sector=sector))
            for pool in ('legacy','cached'):
                for year in (2015,2016):
                    self.content[year][0].setdefault(pool,{})[symbol]=dict(candidate_rank=rank,fiscal='2014-06-30',known='2014-09-28',
                        entry=f'{year}-01-02',price=10.,exit=f'{year+1}-01-02',market_cap=cap,enterprise_value=200e6,
                        ebitda=20e6,ebitda_yield=score,ev_ebitda=9.,spread=score-.02,return_value=.1,status='Scheduled exit')
                self.content['latest'][0].setdefault(pool,{})[symbol]=dict(candidate_rank=rank,fiscal='2016-06-30',known='2016-09-28',
                    entry='2017-01-03',price=10.,market_cap=cap,enterprise_value=200e6,ebitda=20e6,ebitda_yield=score,
                    ev_ebitda=9.,spread=score-.02)
                for _,pairs,values in self.content.values():
                    if symbol!='M':
                        # Pair members intentionally are not reciprocals.
                        pairs.setdefault(pool,{})[symbol]={metric:(17. if metric=='ev_ebitda' else 29.,
                                                                   score if metric=='ev_ebitda' else score/2) for metric in metrics.METRICS}
                    if symbol in ('B','C','D'):
                        values.setdefault(pool,{})[symbol]={field:10. if symbol=='B' else 20. if symbol=='C' else -5.
                                                            for field in metrics.FILTERS}

    def stored(self):
        if not self.books:
            for year in (2015,2016):
                self.books.append(store.book(self.db,f'{year}-01-02',f'{year+1}-01-02',spy=.1,candidates=8,
                                             rows=self.content[year][0],metrics=self.content[year][1],values=self.content[year][2]))
            self.latest=store.book(self.db,'2017-01-03',None,candidates=8,rows=self.content['latest'][0],
                                   metrics=self.content['latest'][1],values=self.content['latest'][2])

    def dataset(self):
        self.stored()
        return data.load_screening_data(self.db)

    def browser(self,payload):
        code="""
const fs=require('fs'),assert=require('assert'),engine=require(process.argv[1]);
const p=JSON.parse(fs.readFileSync(0,'utf8')),answer={};
if(p.cases)answer.cases=p.cases.map(o=>{
 const saved=JSON.stringify(o),l=engine.latestScreen(p.dataset,o);
 assert.equal(JSON.stringify(o),saved);
 return {latest:l.stocks.map(x=>[x.symbol,x.rank,x.metric_multiple,x.metric_yield]),matches:l.matches};
});
if(p.scalar)answer.scalar=p.scalar.map(c=>engine.selectValues(c.rows,c.specification));
process.stdout.write(JSON.stringify(answer));
"""
        output=subprocess.run(['node','-e',code,str(ROOT/'website/browser/screener.js')],
            input=json.dumps(payload,allow_nan=False),text=True,capture_output=True,check=True)
        return json.loads(output.stdout)

    def sql(self,options,latest=False):
        compact=lambda group:[[h['symbol'],h['rank'],h['metric_multiple'],h['metric_yield']] for h in group]
        self.stored()
        if latest:return compact(screening.latest(self.db,**options))
        return [compact(screening.select(self.db,book=book,**options)) for book in self.books]

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
        for _,_,values in self.content.values():
            for pool in values:values[pool]['B']['profit_margin']=high
        options=dict(filters=[dict(field='profit_margin',op='gt',value=low)])
        expected=[['B',1,17.,.4],['C',2,17.,.4]]
        self.assertEqual(self.sql(options,True),expected)
        result=self.browser(dict(dataset=self.dataset(),cases=[options]))['cases'][0]
        self.assertEqual(result['latest'],expected)

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
        store.company(self.db,'BIG')
        # More than 8,192 rows across one prepared pool, beyond callable limits.
        for i in range(8200):
            symbol=f'P{i:05d}'
            store.company(self.db,symbol)
            self.content['latest'][0]['cached'][symbol]=dict(candidate_rank=i+10,fiscal='2016-06-30',known='2016-09-28',
                      entry='2017-01-03',price=10.,market_cap=200e6,enterprise_value=200e6,ebitda_yield=.3,ev_ebitda=4.,spread=.2)
            self.content['latest'][1]['cached'][symbol]={'ev_ebitda':(4.,.3)}
        options=dict(pool='cached',rank_to=1)
        self.assertEqual(self.sql(options,True),[['A',1,17.,.4]])
        actual=self.browser(dict(dataset=self.dataset(),cases=[options]))['cases'][0]
        self.assertEqual(actual['latest'],[['A',1,17.,.4]])
        self.assertEqual(actual['matches'],8206)

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
        for case,result in zip(cases,actual):
            checked=selection.validate(case['specification'])
            self.assertEqual(result,selection.execute(case['rows'],selection.steps(checked),
                count_selected=checked['selection_order']=='rank_first'))
        self.assertEqual([rows[item['index']]['symbol'] for item in actual[0]['selected']],['D','E','A'])
        self.assertEqual([rows[item['index']]['symbol'] for item in actual[2]['selected']],['C','A','E'])


if __name__=='__main__':unittest.main()
