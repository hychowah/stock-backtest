const assert=require('assert');
const {analyze,pie}=require('../website/browser/contributions.js');
const stock=(symbol,return_value)=>({symbol,name:symbol+' Company',return_value});
const close=(a,b)=>assert(Math.abs(a-b)<1e-12,`${a} != ${b}`);
const inputs=[stock('A',.5),stock('B',.4),stock('C',.3),stock('D',.2),stock('E',.1),stock('F',0),stock('G',-.1),stock('H',-.2),stock('I',-.3),stock('J',-.4)];
const original=JSON.stringify(inputs),mixed=analyze(inputs);
assert.equal(JSON.stringify(inputs),original);
assert.equal(mixed.top_count,10);assert.equal(mixed.top[0].symbol,'A');
close(mixed.top[0].contribution,.05);close(mixed.gains,.15);close(mixed.losses,.1);close(mixed.net,.05);
close(mixed.top_total+mixed.other_total,mixed.net);
close(mixed.gain_slices.reduce((s,r)=>s+r.value,0),mixed.gains);
close(mixed.loss_slices.reduce((s,r)=>s+r.value,0),mixed.losses);
assert.equal(mixed.gain_slices[1].label,'B');assert(mixed.loss_slices.every(s=>!s.other));
const larger=analyze(Array.from({length:20},(_,i)=>stock(String(i).padStart(2,'0'),i/20-.3)));
assert(larger.gain_slices.some(s=>s.label==='Other gainers'));
assert(larger.loss_slices.some(s=>s.label==='Other losers'));
close(larger.gain_slices.reduce((s,r)=>s+r.value,0),larger.gains);
close(larger.loss_slices.reduce((s,r)=>s+r.value,0),larger.losses);
for(const [n,k] of [[1,1],[10,10],[11,10],[50,10],[61,10],[100,10]]){
 const result=analyze(Array.from({length:n},(_,i)=>stock(String(i).padStart(3,'0'),i/100)));
 assert.equal(result.top_count,k);assert.equal(result.top.length,k);
 close(result.top[0].return_value,(n-1)/100);
 close(result.top_total+result.other_total,result.net);
}
const losses=analyze([stock('Z',-.8),stock('A',-.1)]);
assert.equal(losses.top[0].symbol,'A');assert.equal(losses.gain_slices.length,0);
close(losses.losses,.45);close(losses.net,-.45);close(losses.top_total,-.45);
const zero=analyze([stock('B',0),stock('A',0)]);
assert.equal(zero.top[0].symbol,'A');assert.equal(zero.gain_slices.length,0);assert.equal(zero.loss_slices.length,0);
assert.equal(analyze([]).top_count,0);
close(analyze([stock('BANKRUPT',-1),stock('GAIN',.2)]).losses,.5);
console.log('Passed: top-10 stock limit, signed ranking, equal weights, gain/loss reconciliation, deterministic ties, empty/zero/all-loss books, and no input mutation.');
// Gains and losses pies are normalized separately and never show negative slices.
const gainPie=pie(mixed.gain_slices,mixed.gains,1),lossPie=pie(mixed.loss_slices,mixed.losses,-1);
assert(gainPie.includes('<h4>Gains</h4>')&&gainPie.includes('conic-gradient(')&&gainPie.includes('A · 33.3% · +5.00 pp'));
assert(lossPie.includes('<h4>Losses</h4>')&&lossPie.includes('J · 40.0% · -4.00 pp')&&!/· -\d/.test(lossPie.replace(/· -\d+\.\d+ pp/g,'')));
assert(pie([],0,1).includes('No gains this year.')&&!pie([],0,1).includes('conic-gradient'));
assert(pie([{label:'<b>',value:1,contribution:1,other:false}],1,1).includes('&lt;b&gt;'));
console.log('Passed: gain and loss pies, separate normalization, empty pies and escaped labels.');
