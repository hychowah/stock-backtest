'use strict';
const assert=require('assert'),Artifacts=require('../website/browser/result-artifacts.js');
const result={periods:[{entry:'2015-01-02',exit:'2015-04-01',names:1,portfolio:.1234567890123456,spy:.01,holdings:[{symbol:'SAVED',return_value:.1234567890123456}]}],cagr:.1234567890123456};
const catalog={metrics:{ev_ebitda:{label:'Original metric'}},filters:{pe:{label:'Original P/E',available:true}}};
const settings={mode:'custom',start:'2015-01-02',end:'2015-04-01',months:3,metric:'ev_ebitda',filters:[{field:'pe',op:'lt',value:10}]};
const presentation={coverage:'Original coverage',notice:{text:'Original warning',severity:'warning'},rangeNote:'Original range',periodLabel:'2015'};
const artifact=Artifacts.create(settings,result,catalog,presentation);
Artifacts.publish(artifact);
settings.filters[0].value=99;catalog.metrics.ev_ebitda.label='Current metric';
const completed=Artifacts.forView('custom');
assert.equal(completed.settings.filters[0].value,10);assert.equal(completed.catalog.metrics.ev_ebitda.label,'Original metric');
assert.equal(completed.result,result);assert.equal(completed.result.periods[0].holdings[0].return_value,.1234567890123456);
assert.throws(()=>completed.result.periods[0].holdings[0].return_value=9,TypeError);
assert.throws(()=>completed.catalog.metrics.ev_ebitda.label='Changed',TypeError);
assert(Artifacts.matches(completed,{...completed.settings}));assert(!Artifacts.matches(completed,{...completed.settings,end:'2020-01-01'}));
assert(Artifacts.matches(completed,{...completed.settings,selection_order:'filter_first'}));
assert(!Artifacts.matches(completed,{...completed.settings,selection_order:'rank_first'}));
const rankFirst=Artifacts.create({...completed.settings,selection_order:'rank_first'},result,catalog,presentation);
assert(Artifacts.matches(rankFirst,{...rankFirst.settings}));
assert(!Artifacts.matches(rankFirst,{...completed.settings}));
const legacy={version:1,kind:'custom',settings:{...completed.settings},result,catalog:completed.catalog,captured_at:'2026-10-26T00:00:00Z',context:{notes:[['screen-coverage','Old coverage','hint'],['screen-status','Old warning','screen-message warning'],['range-note','Old dates','hint']],pill:'Old period'}};
const raw=JSON.stringify(legacy),decoded=Artifacts.decode(legacy);
assert.equal(decoded.version,2);assert.equal(decoded.captured_at,legacy.captured_at);
assert.deepEqual(decoded.presentation,{coverage:'Old coverage',notice:{text:'Old warning',severity:'warning'},rangeNote:'Old dates',periodLabel:'Old period'});
assert.equal(JSON.stringify(legacy),raw);assert(!JSON.stringify(decoded).includes('screen-status'));assert(!('context' in decoded));assert(!('record' in decoded));
const random=Artifacts.create({mode:'random',start:'2015-01-01',trials:2},{configuration:{seed:42},trials:[],trial_results:[]},catalog,presentation);
Artifacts.publish(random);assert.equal(Artifacts.forView('custom').kind,'random');
assert(Artifacts.matches(random,{...random.settings}));assert(Artifacts.matches(random,{...random.settings,seed:42}));assert(!Artifacts.matches(random,{...random.settings,seed:43}));
assert.throws(()=>Artifacts.decode({...legacy,version:3}),/Unsupported/);
console.log('Passed: one immutable result per view, original labels and precision, version-1 decoding, semantic display context, pending edits and exact random-seed reopening.');
// Saved January results of versions 1 and 2 open in the dated view. Their book
// years become periods at read time; the stored record is never rewritten.
const book=(year,names,portfolio,spy,holdings)=>({year,names,portfolio,spy,median_market_cap:null,holdings});
const years=[book(2015,2,.375,.1,[{year:2015,symbol:'A',rank:1,return_value:.5,entry:'2015-01-02',exit:'2016-01-04'},{year:2015,symbol:'B',rank:2,return_value:.25,entry:'2015-01-02',exit:'2016-01-04'}]),
  book(2016,0,null,-.05,[]),book(2017,1,.5,.2,[{year:2017,symbol:'C',rank:1,return_value:.5,entry:'2017-01-03',exit:'2017-10-20'}])];
const januaryResult={options:{first:2015,last:2017,rank_from:1,rank_to:50,metric:'ev_ebitda'},years,first:'2015-01-02',end:'2017-10-20',growth:null,spy_growth:1.254,cagr:null,spy_cagr:.08,short_years:[2015,2016,2017],empty_years:[2016]};
const january={version:1,kind:'january',settings:{mode:'january',first:2015,last:2017,rank_from:1,rank_to:50,metric:'ev_ebitda'},result:januaryResult,catalog,captured_at:'2026-10-20T00:00:00Z',context:{notes:[['screen-status','Saved January notice','screen-message']],pill:'2015 — 2017'}};
for(const stored of [january,{...january,version:2,presentation:{coverage:'Saved coverage'},context:undefined}]){
 const bytes=JSON.stringify(stored),opened=Artifacts.decode(stored);
 assert.equal(JSON.stringify(stored),bytes);
 assert.equal(opened.kind,'january');assert.equal(Artifacts.view(opened.kind),'custom');
 assert.deepEqual(opened.result.periods.map(p=>[p.entry,p.exit,p.names,p.portfolio,p.spy]),
  [['2015-01-02','2016',2,.375,.1],['2016','2017',0,null,-.05],['2017','2017-10-20',1,.5,.2]]);
 assert.deepEqual(opened.result.periods[0].holdings.map(h=>[h.symbol,h.weight,h.contribution_pp,h.entry]),[['A',.5,25,'2015-01-02'],['B',.5,12.5,'2015-01-02']]);
 assert.deepEqual([opened.result.start,opened.result.end,opened.result.cagr,opened.result.spy_cagr,opened.result.options.first],['2015-01-02','2017-10-20',null,.08,2015]);
 assert(!('years' in opened.result)&&!('first' in opened.result));
 // A repeated save sends the stored record; decoding again keeps the projection.
 assert.equal(JSON.stringify(opened.record),bytes);
 assert.equal(JSON.stringify(Artifacts.decode(opened)),JSON.stringify(opened));
 assert(!Artifacts.matches(opened,{mode:'custom',start:'2015-01-01',end:'2017-10-20',months:12}));
 Artifacts.publish(opened);assert.equal(Artifacts.forView('custom').kind,'january');
 assert.equal(Artifacts.reader(opened)!==null,true);
}
console.log('Passed: saved version-1/2 January results project book years into dated periods at read time, never rewrite the record and open in the dated view.');
const produced=Artifacts.create({mode:'custom',engine:'experimental',start:'2015-01-01'},{producer:{engine:'experimental',label:'New engine — experimental'}},catalog,presentation);
assert(Artifacts.matches(produced,{...produced.settings}));
assert(!Artifacts.matches(produced,{...produced.settings,engine:'original'}));
assert.equal(Artifacts.decode(produced).result.producer.engine,'experimental');
const unidentified=Artifacts.decode({...produced,result:{},settings:{mode:'custom',start:'2015-01-01'}});
assert(!('producer' in unidentified.result));
assert(Artifacts.matches(unidentified,{...unidentified.settings,engine:'original'}));
console.log('Passed: pinned engine comparison and recorded producer identity without legacy inference.');
for(const kind of ['latest','january']){
 const prior={version:4,kind,settings:{mode:kind,strategy:{format:'strategy-capture',version:1}},
  result:{},catalog:{},presentation:{},evidence:{id:'d'.repeat(32),format_version:2,trials:kind==='latest'?0:1,periods:kind==='latest'?0:1,holdings:1}};
 const retained=JSON.stringify(prior),decoded=Artifacts.decode(prior);
 assert(Artifacts.matches(decoded,{...prior.settings,engine:'original'}));
 assert(!Artifacts.matches(decoded,{...prior.settings,engine:'experimental'}));
 assert.equal(JSON.stringify(prior),retained);assert(!('producer' in decoded.result));
 assert.equal(Artifacts.view(kind),kind==='latest'?'latest':'custom');
 const numerical=Artifacts.decode({...prior,settings:{...prior.settings,engine:'experimental'}});
 assert(!Artifacts.matches(numerical,{...prior.settings,engine:'original'}));
}
console.log('Passed: old scalar latest/January engine omission means Original without rewriting evidence or inferring a producer; version-4 January opens in the dated view.');
// A chain capture opens unchanged; matching compares the complete captured steps.
const chainSettings={mode:'random',start:'2015-01-01',end:'2016-12-30',months:3,trials:2,engine:'original',strategy:{format:'strategy-capture',version:2,universe:{pool:'cached'},builtins:[],variables:null,limits:{bytes:196608},
 steps:[{kind:'rank',source:{kind:'builtin',id:'metric:ev_ebitda:yield'},direction:'highest',rank_from:1,rank_to:200},{kind:'filter',source:{kind:'field',field:'sector'},op:'eq',threshold:'Energy'},{kind:'rank',source:{kind:'builtin',id:'filter:pe'},direction:'lowest',rank_from:20,rank_to:40}]}};
const chainArtifact={version:4,kind:'random',settings:chainSettings,result:{configuration:{seed:9}},catalog:{},presentation:{},evidence:{id:'e'.repeat(32),format_version:2,trials:2,periods:8,holdings:40}};
const chainBytes=JSON.stringify(chainArtifact),chainDecoded=Artifacts.decode(chainArtifact);
assert.equal(chainDecoded.settings.strategy.steps.length,3);assert(Artifacts.matches(chainDecoded,structuredClone(chainSettings)));
const reordered=structuredClone(chainSettings);reordered.strategy.steps.reverse();assert(!Artifacts.matches(chainDecoded,reordered),'Step order is part of the strategy');
assert.equal(JSON.stringify(chainArtifact),chainBytes);
console.log('Passed: chain captures decode unchanged and match only the same ordered steps.');
