'use strict';
// Real acquisition owner and all opening consumers; no recreated cleanup logic.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const nodes=new Map(),acquired=[],released=[],events={};let lost=false,malformed=false,wrong=false,wait=null,resume=null,refuse=false,afterPublish=false;
let inline=false,responseBytes=null;
const saved='a'.repeat(32),queued='b'.repeat(32),runId='c'.repeat(32);
const settings={mode:'custom',start:'2015-01-02',end:'2015-05-01',months:1,rank_to:5},screen={mode:'latest',strategy:{}};
const artifact={version:3,kind:'custom',settings,result:{periods:[],cagr:.1},catalog:{metrics:{},filters:{}},presentation:{}};
const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',innerHTML:'',textContent:'',hidden:false,handlers:{},querySelectorAll:()=>[],setAttribute(){},addEventListener(k,f){this.handlers[k]=f;}});return nodes.get(id);};
const response=(value,status=200)=>({ok:status<400,status,headers:{get:()=>responseBytes},json:async()=>structuredClone(value)});
const context=vm.createContext({console,Date,Uint8Array,crypto:require('node:crypto').webcrypto,AbortController,
 document:{getElementById:node},location:{protocol:'http:'},addEventListener:(event,fn)=>events[event]=fn,
 setInterval:()=>1,sourceCatalog:()=>artifact.catalog,scheduledPresentation:()=>artifact.presentation,
 EngineControls:{label:()=> 'Original'},CalendarSettings:{decode:()=>settings,label:()=> 'Annual'},
 BacktestRuns:{create:options=>({id:runId,mode:'latest',options,submitted:Date.now()}),follow:async()=>({state:'complete',evidence:{manifest:{periods:0}}})},
 async fetch(url,options={}){
  const id=url.split('/')[3],method=options.method||'GET';
  if(url.includes('/reader')){
   if(method==='DELETE'){released.push(id);return response({released:true});}
   acquired.push(id);
   if(wait){const callback=wait;wait=null;await callback();}
   if(lost)throw Error('Lost acquisition response');
   if(malformed)return {ok:true,json:async()=>{throw Error('Invalid JSON');}};
   return response({...artifact,evidence:{id:wrong?'f'.repeat(32):id,format_version:1,trials:1,periods:1,holdings:1}});
  }
  if(!id)return response({limit:100,records:[{id:saved,name:'Saved',kind:'custom',mode:'custom',options:settings,state:'complete',created_at:'2026-11-01'},{id:queued,name:'Queued',mode:'custom',options:settings,state:'complete'}]});
  if(inline)return response({id,snapshot:{...artifact,version:2}});
  return response({error:'Requires reader',requires_reader:true},409);
 }
});
for(const file of ['result-artifacts.js','backtest-comparison.js','saved-backtests.js','queue.js','result-explorer.js','evidence-results.js','schedule.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser',file),'utf8'),context);
const exec=code=>vm.runInContext(code,context),tick=()=>new Promise(resolve=>setImmediate(resolve));
context.open=artifact=>{if(refuse)throw Error('Save or cancel queued edit');exec('ResultArtifacts.publish')(artifact);if(afterPublish)throw Error('Presentation failed');};
context.publishResult=context.open;
(async()=>{
 exec('SavedBacktests.init({open})');
 exec("BacktestQueue.init({open,libraryChanged(){},metricLabel:()=> 'Original',filterLabel:String})");await tick();
 const savedOpen=()=>node('saved-list').handlers.click({target:{dataset:{open:saved}}});
 const queueOpen=()=>exec(`BacktestQueue.action('open','${queued}')`);
 context.screen=screen;const freshOpen=()=>exec('ScheduleView.runPrepared(screen)');
 for(const consumer of [savedOpen,queueOpen,freshOpen]){
  lost=true;await consumer();lost=false;
  assert.equal(released.at(-1),acquired.at(-1));
  malformed=true;await consumer();malformed=false;
  assert.equal(released.at(-1),acquired.at(-1));
  wrong=true;await consumer();wrong=false;
  assert.equal(released.at(-1),acquired.at(-1));assert(!released.includes('f'.repeat(32)));
 }
 refuse=true;for(const consumer of [savedOpen,queueOpen]){await consumer();assert.equal(released.at(-1),acquired.at(-1));}refuse=false;
 // A published acquisition stays view-owned even if later presentation fails.
 afterPublish=true;await savedOpen();afterPublish=false;const retained=acquired.at(-1);assert(!released.includes(retained));
 await queueOpen();assert(released.includes(retained));const displayed=acquired.at(-1);assert(!released.includes(displayed));
 // Page exit knows pending IDs before acquisition JSON has arrived.
 wait=()=>new Promise(resolve=>resume=resolve);const pending=savedOpen();await tick();const inflight=acquired.at(-1);
 events.pagehide();assert(released.includes(inflight));assert(released.includes(displayed));
 resume();await pending;assert.equal(exec("ResultArtifacts.forView('custom').evidence.id"),displayed);
 // Eager identity uses actual publication, never equality of missing reader IDs.
 context.eager={...artifact,version:2};
 exec('const one=ResultArtifacts.publish(eager);const two=ResultArtifacts.publish({...eager});');
 assert(!exec('ResultArtifacts.current(one)'));assert(exec('ResultArtifacts.current(two)'));
 // Inline saved/queue reads admit 40 MiB and the exact 128 MiB boundary.
 inline=true;
 for(const kind of ['saved','queue']){
  for(const bytes of [40*1024**2,128*1024**2]){
   responseBytes=String(bytes);let consumed=false;
   const used=await exec('ResultArtifacts.use')({kind,id:saved},()=>{consumed=true;});
   assert(used.consumed&&consumed);
  }
  responseBytes=String(128*1024**2+1);
  await assert.rejects(exec('ResultArtifacts.use')({kind,id:saved},()=>assert.fail('Oversize result must not open')),/128 MiB save and open limit/);
 }
 inline=false;responseBytes=String(40*1024**2);
 await assert.rejects(exec('ResultArtifacts.use')({kind:'run',id:runId},()=>assert.fail('Evidence keeps its existing bound')),/Evidence response exceeds its byte limit/);
 responseBytes=null;
 console.log('Passed: real saved/queue/fresh evidence scopes, lost/malformed/wrong-ID replies, refused restoration, publication transfer, in-flight page exit and eager publication identity.');
})().catch(error=>{console.error(error);process.exitCode=1;});
