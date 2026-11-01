const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(process.argv[3]||path.join(root,'website/local'),'index.html'),'utf8');
const dataset=JSON.parse(html.match(/<script id="screening-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
const engine=require('../website/browser/screener.js');
const cases=[
 {first:2015,last:2020,filters:[{field:'pe',op:'lt',value:20}]},
 {first:2015,last:2020,pool:'cached',filters:[{field:'roe',op:'gt',value:10},{field:'debt_equity',op:'lt',value:1}]},
 {first:2015,last:2020},
 {first:2015,last:2020,rank_to:100},
 {first:2015,last:2020,rank_from:10,rank_to:20},
 {first:2015,last:2020,pool:'cached',min_cap:500e6,max_cap:5e9,min_yield:.15,rank_to:100},
 {first:2015,last:2020,pool:'cached',sector:'Technology',exchange:'NASDAQ',max_multiple:8,rank_to:10},
 {first:2015,last:2020,sector:'No matching sector'},
 {first:1996,last:1996,rank_to:100},
 {first:2026,last:2026,rank_from:10,rank_to:10},
 {first:2015,last:2020,pool:'cached',metric:'ev_ebitda_3y',max_multiple:8},
 {first:2015,last:2020,pool:'cached',filters:[{field:'return_1y',op:'gt',value:-10},{field:'return_3y',op:'lt',value:100},{field:'ev_ebitda',op:'lt',value:10}]},
 {first:2015,last:2020,filters:[{field:'market_cap',op:'gt',value:500},{field:'market_cap',op:'lt',value:500}]},
 {first:2015,last:2020,pool:'cached',filters:[{field:'operating_yield_spread_3y',op:'gt',value:5}]},
 {first:2015,last:2020,filters:[{field:'operating_yield_spread_3y',op:'lt',value:0}]},
];
cases.push(...cases.map(options=>({...options,selection_order:'rank_first'})));
if(!process.argv[2])throw Error('Run python3 tests/check_screener.py to generate independent SQLite expectations.');
const references=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const expected=references.historical;
for(let i=0;i<cases.length;i++){
 const result=engine.screen(dataset,cases[i]);
 const actual=result.years.flatMap(y=>y.holdings), reference=expected[i];
 assert.deepStrictEqual(actual.map(h=>[h.year,h.symbol,h.rank]),reference.map(h=>[h.year,h.symbol,h.rank]),'SQL/browser selected stocks differ, case '+i);
 for(let j=0;j<actual.length;j++)for(const key of ['market_cap','enterprise_value','ebitda_yield','ev_ebitda','metric_multiple','metric_yield','return_value'])assert.equal(actual[j][key],reference[j][key],key);
 for(const y of result.years){
  const rows=reference.filter(h=>h.year===y.year);
  assert.equal(y.names,rows.length);
  if(rows.length)assert(Math.abs(y.portfolio-rows.reduce((s,h)=>s+h.return_value,0)/rows.length)<1e-12);
  else assert.equal(y.portfolio,null);
 }
 assert.equal(result.spy_growth,result.years.reduce((w,y)=>w*(1+dataset.periods[y.year].spy),1));
 if(!actual.length){assert.equal(result.cagr,null);assert.equal(result.growth,null);assert.equal(result.empty_years.length,cases[i].last-cases[i].first+1);}
}
const firstYearCount=expected[8].length;
assert(firstYearCount>0&&firstYearCount<100,'SQL fixture needs a nonempty underfilled first year');
assert.equal(engine.screen(dataset,{first:1996,last:1996,rank_to:100}).years[0].names,firstYearCount);
assert.deepStrictEqual(engine.screen(dataset,{first:1996,last:1996,rank_to:100}).short_years,[1996]);
assert.throws(()=>engine.screen(dataset,{min_cap:1e9,max_cap:100}),/Maximum market cap/);
assert.throws(()=>engine.screen(dataset,{rank_from:20,rank_to:10}),/increasing ranks/);
assert.throws(()=>engine.screen(dataset,{min_yield:NaN}),/non-negative/);
console.log(`Passed: browser/SQLite parity across ${cases.length} screens, including combined filters, exact holdings, empty and short years, SPY periods, and invalid inputs.`);

const latestCases=[{}, {pool:'cached',rank_to:100},{pool:'cached',min_cap:500e6,max_cap:5e9,min_yield:.15},{pool:'cached',sector:'Technology',exchange:'NASDAQ',max_multiple:8},{rank_from:10,rank_to:20},{sector:'No matching sector'},{pool:'cached',metric:'ev_ebitda_3y',rank_to:100,max_multiple:8}];
latestCases.push({pool:'cached',filters:[{field:'fcf_yield',op:'gt',value:5}]});
latestCases.push({pool:'cached',filters:[{field:'return_1y',op:'gt',value:-10},{field:'return_3y',op:'lt',value:100}]});
latestCases.push({pool:'cached',filters:[{field:'operating_yield_spread_3y',op:'gt',value:5}]});
latestCases.push(...latestCases.map(options=>({...options,selection_order:'rank_first'})));
for(let i=0;i<latestCases.length;i++){
 const result=engine.latestScreen(dataset,latestCases[i]),expected=references.latest[i];
 assert.deepStrictEqual(result.stocks.map(h=>[h.symbol,h.rank]),expected.map(h=>[h.symbol,h.rank]));
 for(let j=0;j<expected.length;j++)for(const k of ['price_date','price','fiscal','known','market_cap','enterprise_value','ebitda_yield','ev_ebitda','metric_multiple','metric_yield'])assert.equal(result.stocks[j][k],expected[j][k]);
 assert(result.stocks.every(h=>h.price_date===result.asof && h.known<result.asof && !('return_value' in h)));
}
console.log(`Passed: browser/SQLite latest-date parity across ${latestCases.length} screens, prices, valuations, combined filters and no future returns.`);
// Latest selection is independent of historical year controls.
assert.deepStrictEqual(engine.latestScreen(dataset,{first:2030,last:1900}).stocks,engine.latestScreen(dataset,{}).stocks);
assert.throws(()=>engine.screen(dataset,{first:2030,last:1900}),/year range/);
for(const select of [engine.screen,engine.latestScreen]){
 assert.throws(()=>select(dataset,{rank_to:1.5}),/whole numbers/);
 assert.throws(()=>select(dataset,{min_cap:1e9,max_cap:100}),/Maximum market cap/);
 assert.throws(()=>select(dataset,{min_yield:NaN}),/non-negative/);
}
// Consumers accept an arbitrary prepared signal, without formula knowledge.
const custom=JSON.parse(JSON.stringify(dataset));
custom.metrics.test_signal={label:'Test signal'};
for(const values of Object.values(custom.metric_values))values.test_signal=[7,.125];
assert(engine.latestScreen(custom,{metric:'test_signal',pool:'cached'}).stocks.length>0);
assert(engine.latestScreen(custom,{metric:'test_signal',pool:'cached'}).stocks.every(h=>h.metric_multiple===7 && h.metric_yield===.125));
assert(engine.screen(custom,{metric:'test_signal',pool:'cached',first:2015,last:2015}).years[0].holdings.every(h=>h.metric_multiple===7 && h.metric_yield===.125));

// Nonempty financial input fixtures exercise threshold values, missing data and ties.
const financial=JSON.parse(JSON.stringify(dataset));
financial.filter_values={};
const selected=engine.latestScreen(financial,{pool:'cached',rank_to:2}).stocks;
assert.equal(selected.length,2);
for (const [i,h] of selected.entries()) {
 const key='latest:cached:0:'+h.symbol;
 financial.filter_values[key]??={};
 Object.assign(financial.filter_values[key],{pe:10+i,roe:20,fcf_yield:-5});
}
const financialOptions={pool:'cached',filters:[{field:'pe',op:'lt',value:11},{field:'roe',op:'gt',value:10},{field:'fcf_yield',op:'lt',value:0}]};
assert.deepStrictEqual(engine.latestScreen(financial,financialOptions).stocks.map(h=>h.symbol),[selected[0].symbol]);
assert.equal(engine.latestScreen(financial,{pool:'cached',filters:[{field:'pe',op:'lt',value:10}]}).stocks.length,0);
console.log('Passed: populated financial filter values, strict thresholds, signed cash flow and missing-data exclusion.');
