'use strict';
// Exercise the actual artifact and schedule owners with deliberately late pages.
const assert=require('assert'),fs=require('fs'),path=require('path'),vm=require('vm');
const els=new Map(),pending=[],requests=[],downloads=[];
function node(id){if(!els.has(id))els.set(id,{value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,handlers:{},addEventListener(k,f){this.handlers[k]=f;}});return els.get(id);}
const document={getElementById:node,createElement:()=>({click(){downloads.push(this.href);}})};
let deferred=false,holdingCount=180;
const summary={start:'2015-01-02',end:'2015-05-01',months:1,options:{rank_to:180},cagr:.1,spy_cagr:.05,growth:1.1,coverage:'Original coverage',seconds:0};
const holdings=Array.from({length:180},(_,i)=>({rank:i+1,symbol:'S'+String(i).padStart(3,'0'),name:'Original',return_value:(i%7-3)/100,metric_multiple:3,market_cap:1e8,enterprise_value:2e8,contribution_pp:(i%7-3)/180}));
const response=value=>({ok:true,headers:{get:()=>null},json:async()=>value});
const ctx=vm.createContext({document,console,AbortController,Uint8Array,crypto:require('crypto').webcrypto,CalendarSettings:{init(){},label:()=> 'Monthly'},metricLabel:()=> 'Original metric',money:String,RobustnessView:{init(){},render(){}},fetch:async(url,options={})=>{
  requests.push([url,options.method]);
  if(options.method==='DELETE')return response({released:true});
  const parts=url.split('/'),id=parts[3],op=parts[6],trial=+parts[7];
  let value;
  if(op==='trial')value={summary,periods:70,empty:0,short:0};
  else if(op==='curve')value={available:false};
  else if(op==='periods'){
    const cursor=+parts[8],end=Math.min(70,cursor+64);
    value={rows:Array.from({length:end-cursor},(_,i)=>({number:cursor+i+1,value:{entry:'2015-01-02',exit:'2015-02-02',names:holdingCount,portfolio:.1,spy:.05}})),cursor,next:end<70?end:null,total:70};
  }else{
    const cursor=+parts[9],end=Math.min(holdingCount,cursor+64);
    value={rows:holdings.slice(cursor,end),cursor,next:end<holdingCount?end:null,total:holdingCount};
  }
  value={identity:id,...value};
  if(deferred)return new Promise(resolve=>pending.push({url,resolve:()=>resolve(response(value))}));
  return response(value);
}});
for(const file of ['engine-controls.js','result-artifacts.js','backtest-comparison.js','contributions.js','result-explorer.js','asset-curve.js','evidence-results.js','schedule.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser',file),'utf8'),ctx);
const run=code=>vm.runInContext(code,ctx),tick=()=>new Promise(resolve=>setImmediate(resolve));
function artifact(id){return {version:3,kind:'custom',settings:{mode:'custom'},result:summary,catalog:{metrics:{},filters:{}},presentation:{periodLabel:'Original'},extension:{keep:null},evidence:{id:id.repeat(32),format_version:1,trials:1,periods:70,holdings:12600}};}
(async()=>{
  ctx.input=artifact('a');run('const first=ResultArtifacts.publish(input);ScheduleView.init();ScheduleView.show(first)');await tick();await tick();
  assert.equal((node('schedule-stock-body').innerHTML.match(/<tr>/g)||[]).length,64);
  assert.equal(requests.filter(([url])=>url.includes('/page/holdings/')).length,1,'Closed attribution reads only the displayed stock page.');
  node('schedule-attribution-disclosure').open=true;node('schedule-attribution-disclosure').handlers.toggle();await tick();await tick();
  assert(node('schedule-attribution').innerHTML.includes('all 180 selected stocks'));
  const holdingRequests=()=>requests.filter(([url,method])=>!method&&url.includes('/page/holdings/'));
  // First page is shared; subsequent pages preserve both ordered passes.
  assert.equal(holdingRequests().filter(([url])=>url.endsWith('/0')).length,1);
  assert.equal(holdingRequests().filter(([url])=>url.endsWith('/64')).length,2);
  assert.equal(holdingRequests().filter(([url])=>url.endsWith('/128')).length,2);
  run('document.getElementById("schedule-holdings-next").handlers.click()');await tick();
  assert(node('schedule-stock-body').innerHTML.includes('S064'));assert(!node('schedule-stock-body').innerHTML.includes('S000'));
  run('document.getElementById("schedule-holdings-next").handlers.click()');await tick();
  assert(node('schedule-stock-body').innerHTML.includes('S179'));assert(node('schedule-holdings-next').disabled);
  run('document.getElementById("schedule-period-next").handlers.click()');await tick();await tick();
  assert(node('schedule-period-page').textContent.includes('65–70'));assert.equal((node('schedule-rows').innerHTML.match(/<tr>/g)||[]).length,6);
  run('document.getElementById("schedule-download-holdings").handlers.click()');assert(downloads[0].endsWith('/export/holdings/1'));
  // Both passes must retain the eager addition order, including ties and zeros.
  ctx.holdings=holdings;
  for(const count of [0,1,5,180]){
    ctx.count=count;
    const equal=await run('(async()=>{const rows=holdings.slice(0,count),a=ReturnContributions.analyze(rows),b=await ReturnContributions.analyzeStored(count,async visit=>{for(let n=0;n<rows.length;n+=64)rows.slice(n,n+64).forEach(visit);});return JSON.stringify(a)===JSON.stringify(b);})()');assert(equal);
  }
  deferred=true;
  run('document.getElementById("schedule-period-back").handlers.click()');await tick();
  ctx.input=artifact('b');run('const second=ResultArtifacts.publish(input);ScheduleView.show(second)');await tick();
  // Reply to obsolete requests even after their AbortSignal has fired.
  const obsolete=pending.filter(p=>p.url.includes('/'+ 'a'.repeat(32)+'/'));
  obsolete.forEach(p=>p.resolve());await tick();assert.equal(node('schedule-rows').innerHTML,'');
  assert(requests.some(([url,method])=>url.includes('a'.repeat(32))&&method==='DELETE'));
  deferred=false;
  pending.filter(p=>!obsolete.includes(p)).forEach(p=>p.resolve());await tick();await tick();
  assert(run('ResultArtifacts.current(second)'));assert(!run('ResultArtifacts.current(first)'));
  assert.equal(node('screen-error').textContent,'');
  const ticket=run('ResultArtifacts.opening()');run('ResultArtifacts.publish(second)');assert(!ticket());
  run('const originalAnalyzeStored=ReturnContributions.analyzeStored;ReturnContributions.analyzeStored=async(...args)=>{const group=await originalAnalyzeStored(...args);globalThis.lastGroup=group;return group;};');
  for(const count of [0,1,50,180]){
    holdingCount=count;const before=holdingRequests().length;ctx.input=artifact('b');
    run('ScheduleView.show(input)');await tick();await tick();
    const current=holdingRequests().slice(before);
    assert.equal(current.filter(([url])=>url.endsWith('/0')).length,1);
    assert.equal(current.length,1+2*Math.max(0,Math.ceil(count/64)-1));
    ctx.expected=holdings.slice(0,count);
    assert(run('JSON.stringify(lastGroup)===JSON.stringify(ReturnContributions.analyze(expected))'));
  }
  console.log('Passed: bounded periods/holdings, complete ordered attribution, attachment navigation, artifact fences and obsolete pages.');
})().catch(error=>{console.error(error);process.exitCode=1;});
