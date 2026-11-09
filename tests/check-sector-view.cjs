'use strict';
// Exercise the real sector presenter and result reader, including late replies.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const nodes=new Map(),requests=[],inspections=[];
const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',hidden:false,style:{},handlers:{},addEventListener(k,f){this.handlers[k]=f;}});return nodes.get(id);};
const row=(number,complete,sectors,cash=0)=>({number,complete,periods:1,empty:cash?1:0,cash,sectors:sectors.map(([name,mean])=>({name,mean,minimum:mean,maximum:mean,present:mean?1:0}))});
const all={complete:2,incomplete:1,cash:.25,sectors:[{name:'Energy',mean:.5,minimum:0,maximum:1,leading:1},{name:null,mean:.25,minimum:0,maximum:.5,leading:1}],trials:[row(1,true,[['Energy',1]]),row(2,true,[[null,.5]],.5),row(3,false,[['Energy',1]])]};
let pause=false,resolvePending;
const context=vm.createContext({console,AbortController,Uint8Array,selectionActive:true,crypto:require('node:crypto').webcrypto,
 document:{getElementById:node},ScheduleView:{inspectOriginal:(...args)=>inspections.push(args)},
 fetch:async(url,options={})=>{
  requests.push(url);
  if(options.method==='DELETE')return {ok:true,headers:{get:()=>null},json:async()=>({})};
  const id=url.split('/')[3],scope=url.split('/').at(-1);
  let value=scope==='all'?structuredClone(all):{trials:[all.trials[+scope-1]],periods:[{number:1,entry:'2015-01-02',exit:'2016-01-04',names:2,sectors:[{name:null,count:1,weight:.5},{name:'Energy',count:1,weight:.5}]}]};
  if(pause){pause=false;await new Promise(resolve=>resolvePending=resolve);}
  return {ok:true,headers:{get:()=>null},json:async()=>({...value,identity:id})};
 }});
for(const file of ['result-artifacts.js','sector-view.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser',file),'utf8'),context);
const run=code=>vm.runInContext(code,context),tick=()=>new Promise(resolve=>setImmediate(resolve));
const artifact=id=>({version:3,kind:'random',settings:{mode:'random'},result:{trials:[{},{},{}]},catalog:{metrics:{},filters:{}},evidence:{id:id.repeat(32),format_version:1,trials:3,periods:3,holdings:4}});
const click=data=>node('sector-view').handlers.click({target:{closest:()=>({dataset:data})}});
(async()=>{
 run('SectorView.init(()=>selectionActive)');context.input=artifact('a');run('SectorView.show(ResultArtifacts.publish(input))');
 assert.equal(requests.length,0,'Publishing does not read sectors.');await run('SectorView.load()');
 assert(node('sector-trial').innerHTML.includes('Trial 3'));assert(!node('sector-trial').innerHTML.includes('24'));
 assert(node('sector-message').textContent.includes('1 incomplete'));assert(node('sector-insight').textContent.includes('2 complete'));
 const count=requests.length;click({sectorName:'null'});await tick();assert.equal(requests.length,count);
 assert(node('sector-trials').innerHTML.includes('Unknown'));
 click({sectorInspect:'2',inspectSector:'null'});await tick();await tick();
 assert.deepEqual(inspections.at(-1),[2,1,null]);assert(node('sector-mix').innerHTML.includes('1 stock'));
 assert(!requests.some(url=>url.includes('/holdings/')),'Summary UI never downloads holding pages.');
 click({sectorInspect:'1'});await tick();await tick();
 pause=true;click({sectorInspect:'2'});await tick();
 const inspected=inspections.length;assert.equal(node('sector-legend').innerHTML,'');
 click({sectorName:'"Energy"'});
 assert.equal(inspections.length,inspected,'Pending trial cannot inspect the preceding trial detail.');
 assert.equal(node('sector-mix').innerHTML,'');resolvePending();await tick();await tick();
 assert.deepEqual(inspections.at(-1),[2,1,'Energy']);
 context.input=artifact('b');run('SectorView.show(ResultArtifacts.publish(input))');pause=true;const background=run('SectorView.load()');await tick();
 context.selectionActive=false;node('schedule-results').hidden=false;resolvePending();await background;
 assert.equal(node('schedule-results').hidden,false,'Late Selection reply must preserve the active Returns table.');
 context.selectionActive=true;await run('SectorView.load()');assert.equal(node('schedule-results').hidden,true);
 context.input=artifact('b');run('SectorView.show(ResultArtifacts.publish(input))');pause=true;const pending=run('SectorView.load()');await tick();
 context.input=artifact('c');run('SectorView.show(ResultArtifacts.publish(input))');await run('SectorView.load()');
 const displayed=node('sector-chart').innerHTML;resolvePending();await pending;
 assert.equal(node('sector-chart').innerHTML,displayed);assert.equal(node('sector-message').textContent,'2 complete trials · 1 incomplete (excluded from the combined average).');
 assert(requests.some(url=>url.includes('b'.repeat(32))&&url.endsWith('/reader')));
 console.log('Passed: on-demand sector summaries, dynamic trial count, incomplete coverage, Unknown drilldown, compact reads and replaced-response fencing.');
})().catch(error=>{console.error(error);process.exitCode=1;});
