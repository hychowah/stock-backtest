const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'website/dist/index.html'),'utf8');
const dataset=JSON.parse(html.match(/<script id="screening-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
const engine=require('../website/screener.js');
const cases=[
 {first:2015,last:2020},
 {first:2015,last:2020,rank_to:100},
 {first:2015,last:2020,rank_from:10,rank_to:20},
 {first:2015,last:2020,pool:'cached',min_cap:500e6,max_cap:5e9,min_yield:.15,rank_to:100},
 {first:2015,last:2020,pool:'cached',sector:'Technology',exchange:'NASDAQ',max_multiple:8,rank_to:10},
 {first:2015,last:2020,sector:'No matching sector'},
 {first:1996,last:1996,rank_to:100},
 {first:2026,last:2026,rank_from:10,rank_to:10},
];
if(!process.argv[2])throw Error('Run python3 tests/check_screener.py to generate independent SQLite expectations.');
const expected=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
for(let i=0;i<cases.length;i++){
 const result=engine.screen(dataset,cases[i]);
 const actual=result.years.flatMap(y=>y.holdings), reference=expected[i];
 assert.deepStrictEqual(actual.map(h=>[h.year,h.symbol,h.rank]),reference.map(h=>[h.year,h.symbol,h.rank]),'SQL/browser selected stocks differ, case '+i);
 for(let j=0;j<actual.length;j++)for(const key of ['market_cap','enterprise_value','ebitda_yield','ev_ebitda','return_value'])assert.equal(actual[j][key],reference[j][key],key);
 for(const y of result.years){
  const rows=reference.filter(h=>h.year===y.year);
  assert.equal(y.names,rows.length);
  if(rows.length)assert(Math.abs(y.portfolio-rows.reduce((s,h)=>s+h.return_value,0)/rows.length)<1e-12);
  else assert.equal(y.portfolio,null);
 }
 assert.equal(result.spy_growth,result.years.reduce((w,y)=>w*(1+dataset.periods[y.year].spy),1));
 if(!actual.length){assert.equal(result.cagr,null);assert.equal(result.growth,null);assert.equal(result.empty_years.length,6);}
}
assert.equal(engine.screen(dataset,{first:1996,last:1996,rank_to:100}).years[0].names,61);
assert.deepStrictEqual(engine.screen(dataset,{first:1996,last:1996,rank_to:100}).short_years,[1996]);
assert.throws(()=>engine.screen(dataset,{min_cap:1e9,max_cap:100}),/Maximum market cap/);
assert.throws(()=>engine.screen(dataset,{rank_from:20,rank_to:10}),/increasing ranks/);
assert.throws(()=>engine.screen(dataset,{min_yield:NaN}),/non-negative/);
console.log('Passed: browser/SQLite parity across 8 screens, exact holdings and valuations, empty and short years, SPY periods, and invalid inputs.');
