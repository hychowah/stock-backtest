const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',value:'',hidden:true,handlers:{},addEventListener(k,fn){this.handlers[k]=fn}});return nodes.get(id)}
let csv='',download='';const saved=new Map();
const ctx=vm.createContext({localStorage:{setItem:(k,v)=>saved.set(k,v),getItem:k=>saved.get(k)},document:{getElementById:node,createElement:()=>({click(){download=this.download}})},TextDecoder,console,Blob:class{constructor(parts){this.parts=parts}},URL:{createObjectURL(blob){csv=blob.parts.join('');return 'blob:test'},revokeObjectURL(){}}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/robustness.js'),'utf8'),ctx);
const call=code=>vm.runInContext(code,ctx);
const stats={n:2,mean:.15,median:.15,p10:.11,p25:.125,p75:.175,p90:.19,min:.1,max:.2,stddev:.05};
const batch={kind:'random_dates',completed:2,valid:2,incomplete:0,unique_schedules:2,beat_spy:1,configuration:{seed:42,months:24,options:{metric:'ev_ebitda'}},note:'试验 dates vary.',distributions:Object.fromEntries(['cagr','spy_cagr','excess_cagr','total_return','growth'].map(k=>[k,stats])),trials:[{trial:1,start:'2015-01-02',first_trade:'2015-03-02',end:'2020-01-02',dates:['2015-03-02','2017-07-03'],periods:2,cagr:.1,spy_cagr:.09,excess_cagr:.01,empty_periods:0,short_periods:1}]};
function response(events,{truncate=false}={}){
 const packed=Buffer.from(events.map(e=>JSON.stringify(e)).join('\n')+(truncate?'':'\n'));
 const pieces=[];for(let i=0;i<packed.length;i+=7)pieces.push(packed.subarray(i,i+7));
 let i=0;const reader={released:false,async read(){return i<pieces.length?{value:pieces[i++],done:false}:{done:true}},releaseLock(){this.released=true}};
 return {body:{getReader:()=>reader},reader};
}
(async()=>{
 const progress=[];ctx.progress=e=>progress.push(e);
 ctx.response=response([{type:'progress',completed:0,total:2},{type:'preparation',completed:0,total:2,workers:4,calculated_books:10,total_new_books:20},{type:'progress',completed:1,total:2},{type:'complete',result:batch}]);
 const result=await call('RobustnessView.read(response,progress)');
 assert.equal(result.note,batch.note);assert.deepStrictEqual(progress.map(e=>e.completed),[0,0,1]);assert.equal(progress[1].workers,4);assert.equal(progress[1].calculated_books,10);assert(ctx.response.reader.released);
 ctx.response=response([{type:'configuration',configuration:{seed:987,months:24,start:'2015-01-01',end:'2020-01-01',requested:2,options:{}}},{type:'progress',completed:1,total:2}],{truncate:true});
 await assert.rejects(()=>call('RobustnessView.read(response,progress)'),/ended before all trials completed/);assert(ctx.response.reader.released);
 assert.equal(node('random-seed').value,'987');assert.equal(node('robustness-replay').hidden,false);
 let replayed;ctx.replay=c=>replayed=c;call('RobustnessView.init(()=>{},replay)');node('robustness-replay').handlers.click();assert.equal(replayed.seed,987);assert.equal(replayed.months,24);assert.equal(JSON.parse(saved.get('backtest-experiment')).seed,987);
 node('random-seed').value='';call('RobustnessView.init(()=>{},replay)');assert.equal(node('random-seed').value,'987');
 ctx.response=response([{type:'error',message:'Calculation failed'}]);
 await assert.rejects(()=>call('RobustnessView.read(response,progress)'),/Calculation failed/);assert(ctx.response.reader.released);
 ctx.batch=batch;let inspected;
 ctx.inspect=(trial,config)=>inspected={trial,config};call('RobustnessView.init(inspect);RobustnessView.render(batch)');
 assert.equal(node('robustness-results').hidden,false);assert.equal(node('robustness-mean').textContent,'15.00%');
 assert.equal(node('random-seed').value,'42');assert(node('robustness-distribution').innerHTML.includes('Strategy CAGR'));
 node('robustness-download').handlers.click();assert(csv.includes('2015-03-02;2017-07-03'));assert(csv.includes('"42"'));assert.equal(download,'random-dates-seed-42.csv');
 node('robustness-trial').value='0';node('robustness-inspect').handlers.click();assert.equal(inspected.trial.trial,1);assert.equal(inspected.config.months,24);
 console.log('Passed: streamed trial progress, chunk/UTF-8 decoding, interrupted/error streams, distribution rendering, reproducible CSV and trial inspection.');
})().catch(error=>{console.error(error);process.exitCode=1});
