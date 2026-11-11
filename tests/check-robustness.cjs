const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',value:'',hidden:true,handlers:{},addEventListener(k,fn){this.handlers[k]=fn}});return nodes.get(id)}
let csv='',download='';
const ctx=vm.createContext({document:{getElementById:node,createElement:()=>({click(){download=this.download}})},console,Blob:class{constructor(parts){this.parts=parts}},URL:{createObjectURL(blob){csv=blob.parts.join('');return 'blob:test'},revokeObjectURL(){}}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/robustness.js'),'utf8'),ctx);
const call=code=>vm.runInContext(code,ctx);
const stats={n:2,mean:.15,median:.15,p10:.11,p25:.125,p75:.175,p90:.19,min:.1,max:.2,stddev:.05};
const batch={kind:'random_dates',completed:2,valid:2,incomplete:0,unique_schedules:2,beat_spy:1,configuration:{seed:42,months:24,options:{metric:'ev_ebitda'}},note:'试验 dates vary.',distributions:Object.fromEntries(['cagr','spy_cagr','excess_cagr','total_return','growth'].map(k=>[k,stats])),trials:[{trial:1,start:'2015-01-02',first_trade:'2015-03-02',end:'2020-01-02',dates:['2015-03-02','2017-07-03'],periods:2,cagr:.1,spy_cagr:.09,excess_cagr:.01,empty_periods:0,short_periods:1}]};
(async()=>{
 ctx.batch=batch;let inspected;
 // This context has no browser storage: showing a result stores nothing.
 ctx.inspect=index=>inspected=index;call('RobustnessView.init(inspect,()=>batch)');
 // The date-set box takes the number of the shown result. A ticked Repeat keeps the number that the user set.
 node('repeat-random').checked=true;node('random-seed').value='321';call('RobustnessView.render(batch)');
 assert.equal(node('random-seed').value,'321');node('repeat-random').checked=false;call('RobustnessView.render(batch)');
 assert.equal(node('robustness-results').hidden,false);assert.equal(node('robustness-mean').textContent,'15.00%');
 assert.equal(node('random-seed').value,'42');assert(node('robustness-distribution').innerHTML.includes('Strategy CAGR'));
 assert(node('robustness-chart').innerHTML.includes('<rect'));
 assert(!node('robustness-chart').innerHTML.includes('NaN'));
 assert(node('robustness-chart-note').textContent.includes('Seed 42'));
 // The summary line stays short; the sampling rules of the result wait under How to read this.
 assert.equal(node('robustness-description').textContent,'2 trials · 2 complete, 0 incomplete · 2 distinct schedules · 1/2 complete trials beat paired SPY.');
 assert.equal(node('robustness-note').textContent,'试验 dates vary.');assert(node('robustness-scope').hidden&&!node('robustness-scope').textContent);
 batch.trials.push({...batch.trials[0],trial:2,cagr:.2,total_return:2,excess_cagr:.03}, {...batch.trials[0],trial:3,cagr:null,total_return:999});
 batch.trials[0].total_return=1;batch.trials[0].spy_growth=1.5;
 call('RobustnessView.render(batch)');
 assert(node('robustness-chart').innerHTML.includes('<path'));
 assert(node('robustness-chart').innerHTML.includes('Paired SPY'));
 assert(node('robustness-chart').innerHTML.includes('mean 9.00%'));
 assert(!node('robustness-chart').innerHTML.includes('NaN'));
 assert(node('robustness-chart-note').textContent.includes('2 complete trials'));
 // A redraw keeps the trial that the user chose; a new result starts at its first trial.
 node('robustness-trial').value='1';call('RobustnessView.preview(batch)');assert.equal(node('robustness-trial').value,'1');
 call('RobustnessView.render(batch)');assert.equal(node('robustness-trial').value,'0');
 node('robustness-measure').value='total_return';node('robustness-measure').handlers.change();
 assert(node('robustness-chart').innerHTML.includes('Total return'));
 assert(node('robustness-chart').innerHTML.includes('mean 50.00%'));
 node('robustness-measure').value='excess_cagr';node('robustness-measure').handlers.change();
 assert(!node('robustness-chart').innerHTML.includes('Paired SPY'));
 assert(node('robustness-chart').innerHTML.includes(' pp'));

 batch.trials=[];call('RobustnessView.render(batch)');
 assert(node('robustness-chart').innerHTML.includes('No complete trials'));
 batch.trials=[{trial:1,start:'2015-01-02',first_trade:'2015-03-02',dates:['2015-03-02','2017-07-03'],cagr:.1}];
 call('RobustnessView.render(batch)');
 ctx.preview={...batch,configuration:{...batch.configuration,seed:999},trials:[{...batch.trials[0],cagr:.9}]};
 call('RobustnessView.preview(preview)');
 node('robustness-measure').value='cagr';node('robustness-measure').handlers.change();
 assert(node('robustness-chart').innerHTML.includes('mean 90.00%'));
 assert.equal(node('random-seed').value,'42','An Explore preview keeps the date-set number of the original result');
 // A previewed selection says which window and ranks the chart and tables show.
 ctx.selection={start:'2016-01-04',end:'2019-01-02',rank_from:5,rank_to:10};call('RobustnessView.preview(preview,selection)');
 assert(!node('robustness-scope').hidden&&node('robustness-scope').textContent.startsWith('Explore selection: 2016-01-04 → 2019-01-02 · ranks 5–10.'));
 call('RobustnessView.preview(preview)');assert(node('robustness-scope').hidden&&!node('robustness-scope').textContent);
 call('RobustnessView.render(batch)');assert(node('robustness-scope').hidden);
 node('robustness-download').handlers.click();assert(csv.includes('2015-03-02;2017-07-03'));assert(csv.includes('"42"'));assert.equal(download,'random-dates-seed-42.csv');
 // Inspect names the chosen trial by its place in the list; the dated view decides what it can show.
 node('robustness-trial').value='0';node('robustness-inspect').handlers.click();assert.equal(inspected,0);
 console.log('Passed: no browser storage, the date-set number of the shown result, distribution rendering, reproducible CSV and trial inspection.');
})().catch(error=>{console.error(error);process.exitCode=1});
