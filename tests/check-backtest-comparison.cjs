const assert=require('node:assert/strict'),Comparison=require('../website/browser/backtest-comparison.js');
const artifact=(settings={},result={},kind='custom')=>({version:2,kind,settings:{mode:kind,start:'2015-01-01',end:'2020-12-31',months:12,...settings},result:{start:'2015-01-02',end:'2020-12-31',cagr:.12,spy_cagr:.08,growth:2,...result},catalog:{metrics:{ev_ebitda:{label:'Original EBITDA multiple'}},filters:{fcf:{label:'Original free cash flow'}}}});
const describe=Comparison.describe,compare=(a,b)=>Comparison.compare(describe(a),describe(b));
const a=artifact(),legacy=JSON.stringify(a);Object.freeze(a.settings);Object.freeze(a);
const b=artifact({calendar:{version:1,start:'2015-01-01',end:'2020-12-31',interval:{unit:'month',count:12}},selection_order:'filter_first',engine:'original'});delete b.settings.start;delete b.settings.end;delete b.settings.months;
assert(compare(a,b).parameters.every(row=>!row.different),'Legacy and current calendar/defaults should compare equal');assert.equal(JSON.stringify(a),legacy);
const week=structuredClone(b);week.settings.calendar.interval={unit:'week',count:4};assert(compare(b,week).parameters.find(row=>row.key==='interval').different);
const conditions=[{field:'fcf',op:'gt',value:-2},{field:'market_cap',op:'lt',value:123.00000000001}];
const filtered=artifact({filters:conditions}),reordered=artifact({filters:[conditions[1],conditions[0],conditions[0]]});
assert(!compare(filtered,reordered).parameters.find(row=>row.key==='filters').different);
assert(describe(filtered).parameters.find(row=>row.key==='filters').display.includes('Original free cash flow > -2'));
const strict=artifact({filters:[{...conditions[0],op:'lt'},conditions[1]]});assert(compare(filtered,strict).parameters.find(row=>row.key==='filters').different);
const exact=artifact({filters:[conditions[0],{...conditions[1],value:123}]});assert(compare(filtered,exact).parameters.find(row=>row.key==='filters').different);
assert(compare(a,artifact({min_cap:null})).parameters.find(row=>row.key==='min_cap').different,'Explicit null is not an omission default');
assert(compare(a,artifact({rank_to:0})).parameters.find(row=>row.key==='rank_to').different);
const unknown=artifact({future_setting:{z:1,a:[null,'x']}});assert(describe(unknown).parameters.find(row=>row.key==='setting.future_setting').display==='{"a":[null,"x"],"z":1}');
assert(compare(a,unknown).parameters.find(row=>row.key==='setting.future_setting').different);
assert(describe(a).parameters.find(row=>row.key==='producer').display.includes('Unidentified'));
const produced=artifact({engine:'experimental'},{producer:{engine:'original',label:'Original source'}});const projection=describe(produced);
assert.equal(projection.parameters.find(row=>row.key==='engine').value,'experimental');assert.equal(projection.parameters.find(row=>row.key==='producer').value.engine,'original');
assert.equal(projection.parameters.find(row=>row.key==='producer').display,'Original source (original)');
assert.equal(describe(artifact({},{producer:{engine:'original',label:'Original'}})).parameters.find(row=>row.key==='producer').display,'Original');
const random=artifact({trials:2},{completed:2,valid:1,incomplete:1,configuration:{seed:42,window_start:'2015-01-02',window_end:'2020-12-31'},distributions:{cagr:{mean:.15,median:.14,p10:.03,p90:.22},spy_cagr:{mean:.08}}},'random');
const randomDescription=describe(random);assert(randomDescription.notices.some(text=>text.includes('not one portfolio')));assert.equal(randomDescription.parameters.find(row=>row.key==='actual_seed').value,42);
assert.equal(randomDescription.parameters.find(row=>row.key==='seed_policy').display,'Fresh dates each run');
const repeated=structuredClone(random);repeated.settings.seed=42;assert(compare(random,repeated).parameters.find(row=>row.key==='seed_policy').different);
assert.equal(randomDescription.performance.find(row=>row.key==='cagr.p90').value,.22);assert(!('result' in randomDescription));
const unavailable=artifact({},{cagr:null});assert.equal(describe(unavailable).performance.find(row=>row.key==='cagr').display,'Unavailable');
const v3=structuredClone(random);v3.version=3;v3.evidence={id:'a'.repeat(32)};assert.deepEqual(describe(v3),randomDescription);
const changedWindow=artifact({start:'2016-01-01'},{start:'2016-01-04'});assert(compare(a,changedWindow).notices.some(text=>text.includes('requested date')));assert(compare(a,changedWindow).notices.some(text=>text.includes('observation')));
assert(compare(a,random).notices.some(text=>text.includes('different test types')));
assert.throws(()=>describe({}),/cannot be compared/);
console.log('Passed: stored parameter projection, calendars/defaults, AND filters, exact values, unknown settings, requested engines/recorded producers, seeds, stored distributions and comparability notices.');
const captured={selection:{ranking:{source:{kind:'builtin',id:'metric:ev_ebitda:yield'},direction:'highest'},rank_from:1,rank_to:50,selection_order:'filter_first',conditions:[]},bounds:{min_cap:null,min_ev:null},pool:'cached',variables:null,builtins:[{id:'metric:ev_ebitda:yield',label:'Captured EBITDA yield'}]};
const oldScalar=artifact({strategy:captured,first:2015,last:2015},{},'january');
const explicitScalar=structuredClone(oldScalar);explicitScalar.settings.engine='original';
assert(!compare(oldScalar,explicitScalar).parameters.find(row=>row.key==='engine').different);
explicitScalar.settings.engine='experimental';
assert(compare(oldScalar,explicitScalar).parameters.find(row=>row.key==='engine').different);
assert(describe(oldScalar).parameters.find(row=>row.key==='producer').display.includes('Unidentified'));
console.log('Passed: scalar January requested-engine defaults remain distinct from recorded producer evidence.');
// A chain capture describes its universe and every ordered step from the record.
const chain={format:'strategy-capture',version:2,universe:{pool:'cached'},variables:{presentation:[{variable_id:'variable:a',revision:'sha256:'+'a'.repeat(64),name:'Recorded margin'}]},builtins:[{id:'metric:ev_ebitda:yield',label:'Recorded EBITDA yield'}],
 steps:[{kind:'rank',source:{kind:'formula',variable_id:'variable:a',revision:'sha256:'+'a'.repeat(64)},direction:'lowest',rank_from:1,rank_to:200},{kind:'filter',source:{kind:'field',field:'sector'},op:'eq',threshold:'Energy'},
  {kind:'filter',source:{kind:'builtin',id:'metric:ev_ebitda:yield'},op:'ge',threshold:{value:'0.02',unit:'scalar'},submitted_threshold:{value:'2',unit:'percent'},comparison_value:.02,storage_comparison_value:.02},
  {kind:'rank',source:{kind:'builtin',id:'metric:ev_ebitda:yield'},direction:'highest',rank_from:20,rank_to:40}]};
// Summaries read plain wording. The exact field keeps the recorded id, revision,
// unit and canonical value; a row whose plain wording is exact has none.
const chainRows=Comparison.scalarRows(chain);
assert.deepEqual(chainRows.map(row=>row.label+': '+row.display),['Stock pool: All stocks with cached prices','Step 1 · Rank: Recorded margin · lowest first · ranks 1–200','Step 2 · Filter: Sector = Energy',
 'Step 3 · Filter: Recorded EBITDA yield ≥ 2%','Step 4 · Rank: Recorded EBITDA yield · highest first · ranks 20–40']);
assert.deepEqual(chainRows.map(row=>row.exact),['cached','Recorded margin @ sha256:'+'a'.repeat(64)+' lowest first · ranks 1–200',undefined,
 'Recorded EBITDA yield (metric:ev_ebitda:yield) ≥ 2 percent (canonical 0.02 scalar)','Recorded EBITDA yield (metric:ev_ebitda:yield) highest first · ranks 20–40']);
assert.deepEqual(chainRows.map(row=>row.value),['cached',...chain.steps],'Plain wording never changes the compared value');
const dollarStep=(value,unit)=>Comparison.scalarRows({...chain,steps:[{kind:'filter',source:{kind:'field',field:'market_cap'},op:'ge',threshold:{value:'1',unit:'USD'},submitted_threshold:{value,unit}}]})[1];
assert.equal(dollarStep('100','usd_million').display,'Market cap ≥ $100M');assert.equal(dollarStep('100','usd_million').exact,'Market cap (USD) ≥ 100 usd_million (canonical 1 USD)');
assert.equal(dollarStep('-2.5','usd').display,'Market cap ≥ -$2.5');assert.equal(dollarStep('3','future_unit').display,'Market cap ≥ 3 future_unit');
assert.deepEqual({...Comparison.finalRank({strategy:chain})},chain.steps[3]);
assert.deepEqual({...Comparison.finalRank({strategy:captured})},{source:captured.selection.ranking.source,direction:'highest',rank_from:1,rank_to:50});
assert.deepEqual({...Comparison.finalRank({rank_to:7})},{rank_from:1,rank_to:7});
const left=artifact({strategy:chain}),right=artifact({strategy:{...structuredClone(chain),steps:chain.steps.map((step,i)=>i===3?{...step,rank_to:30}:step)}});
const differences=compare(left,right).parameters.filter(row=>row.different).map(row=>row.key);
assert.deepEqual(differences,['step.3']);
// Flat settings read plain too; performance shows 2 decimals, or 2 significant digits below 0.01.
const flat=describe(artifact({min_cap:250e6,min_ev:1234567,min_yield:.07,pool:'cached'},{growth:2.345678})),shown=key=>flat.parameters.find(row=>row.key===key);
assert.deepEqual([shown('min_cap').display,shown('min_cap').exact,shown('min_cap').value],['$250M','250000000',250e6]);assert.equal(shown('min_ev').display,'$1,234,567');
assert.equal(shown('min_yield').display,'7%');assert.equal(shown('max_cap').display,'No limit');assert.deepEqual([shown('pool').display,shown('pool').exact],['All stocks with cached prices','cached']);
assert.deepEqual([shown('metric').display,shown('metric').exact],['Original EBITDA multiple','Original EBITDA multiple (ev_ebitda)']);
assert.equal(flat.performance.find(row=>row.key==='growth').display,'2.35×');assert.equal(flat.performance.find(row=>row.key==='cagr').display,'12.00%');
const spread=describe(artifact({trials:2},{completed:2,valid:2,incomplete:0,configuration:{seed:1},distributions:{cagr:{mean:.000082208838},excess_cagr:{mean:-.005837653252144099,min:-.00004},growth:{mean:1.23456}}},'random')).performance;
assert.deepEqual(['cagr.mean','excess_cagr.mean','excess_cagr.min','growth.mean'].map(key=>spread.find(row=>row.key===key).display),['0.0082%','-0.58 pp','-0.0040 pp','1.23×']);
// A value below 0.000001 in its unit shows 0.00, never exponent notation.
const tiny=describe(artifact({},{cagr:5.55e-17,spy_cagr:-2e-9,growth:1.2e-6})).performance.map(row=>row.display);assert.deepEqual(tiny,['0.00%','0.00%','0.0000012×']);
assert.equal(spread.find(row=>row.key==='excess_cagr.mean').value,-.005837653252144099);
console.log('Passed: chain captures list the universe and ordered steps in plain wording with exact text kept, compare by step, the last Rank sets the recorded range, and on-screen values are rounded.');
// The headline is the short answer of one result. Every test type starts with the
// same three keys; each value is a stored summary field or their difference.
const lines=description=>description.headline.map(row=>row.key+'|'+row.label+'|'+row.display);
assert.deepEqual(lines(describe(a)),['cagr|Strategy CAGR|12.00%','spy_cagr|SPY CAGR|8.00%','difference|Difference vs SPY|+4.00 pp','growth|Growth of $1|$2.00']);
assert.deepEqual(lines(describe(oldScalar)),lines(describe(a)),'A January result reads like a fixed schedule');
assert.deepEqual(lines(describe(artifact({},{cagr:.05,spy_cagr:.08,growth:null}))).slice(2),['difference|Difference vs SPY|-3.00 pp','growth|Growth of $1|Unavailable']);
assert.deepEqual(lines(describe(unavailable)).filter(line=>line.endsWith('Unavailable')),['cagr|Strategy CAGR|Unavailable','difference|Difference vs SPY|Unavailable']);
const trials=artifact({trials:6},{completed:6,valid:5,incomplete:1,beat_spy:2,configuration:{seed:7},distributions:{cagr:{mean:.15,min:-.02,max:.31},spy_cagr:{mean:.08},excess_cagr:{mean:.07}},trial_results:[{cagr:9,spy_cagr:1}]},'random');
// The count covers complete trials only; the display says so when some trials are incomplete.
assert.deepEqual(lines(describe(trials)),['cagr|Mean strategy CAGR|15.00%','spy_cagr|Mean SPY CAGR|8.00%','difference|Mean difference vs SPY|+7.00 pp','beat_spy|Trials beating SPY|2/5 complete','worst|Worst trial CAGR|-2.00%','best|Best trial CAGR|31.00%']);
const allComplete=structuredClone(trials);Object.assign(allComplete.result,{valid:6,incomplete:0});assert.equal(lines(describe(allComplete))[3],'beat_spy|Trials beating SPY|2/6');
// The sign of a difference follows the rounded number on screen: a shown 0.00 has no sign.
const difference=(cagr,spy_cagr)=>describe(artifact({},{cagr,spy_cagr})).headline[2].display;
assert.deepEqual([difference(.1+.2,.3),difference(.3,.3+1e-12),difference(.3,.3),difference(.30004,.3),difference(.3,.30004)],['0.00 pp','0.00 pp','0.00 pp','+0.0040 pp','-0.0040 pp']);
assert.deepEqual(describe(trials).headline.map(row=>row.value),[.15,.08,.07,2,-.02,.31]);
// A stored result that lacks a value shows Unavailable; nothing is derived from trials or holdings.
assert.deepEqual(lines(randomDescription).map(line=>line.split('|')[2]),['15.00%','8.00%','Unavailable','Unavailable','Unavailable','Unavailable']);
assert.deepEqual(describe(a).headline.slice(0,3).map(row=>row.key),describe(trials).headline.slice(0,3).map(row=>row.key));
console.log('Passed: one headline per result with shared keys, stored trial statistics and counts, and unavailable values left unavailable.');
