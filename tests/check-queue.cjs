const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,handlers:{},addEventListener(type,fn){this.handlers[type]=fn},scrollIntoView(){}});return nodes.get(id)}
const copy=value=>JSON.parse(JSON.stringify(value));
let records=[],paused=false,requests=[],loaded=null,opened=null,failList=false,loseAcknowledgement=false,holdList=false,releaseList,preparations=0,endedEdits=0;
let settings={mode:'custom',start:'2015-01-01',end:'2016-12-30',months:3,rank_from:1,rank_to:50,pool:'legacy',metric:'ev_ebitda',min_cap:100e6,max_cap:null,min_ev:50e6,min_yield:0,max_multiple:null,filters:[{field:'market_cap',op:'gt',value:100}]};
const snapshot={version:2,kind:'custom',settings:copy(settings),catalog:{metrics:{},filters:{}},presentation:{},result:{periods:[]}};
const storage=new Map();
const context=vm.createContext({console,crypto:require('node:crypto').webcrypto,Uint8Array,Date,location:{protocol:'http:'},document:{getElementById:node},localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},setInterval(){},async fetch(url,options={}){
  requests.push({url,...options});const method=options.method||'GET',parts=url.split('/').slice(3),id=parts[0],action=parts[1];
  let value,status=200;const body=options.body?JSON.parse(options.body):{};
  if(method==='GET'&&!id){
    if(failList)throw Error('List disconnected');
    value={records:copy(records),paused,limit:100};
    if(holdList){holdList=false;await new Promise(resolve=>releaseList=resolve);}
  }else if(method==='POST'&&!id){
    let record=records.find(item=>item.id===body.id);
    if(!record){record={id:body.id,name:body.name,mode:body.mode,options:copy(body.options),state:'queued',position:records.length+1,revision:1,cagr:null};records.push(record);}
    value=copy(record);
    if(loseAcknowledgement){loseAcknowledgement=false;throw Error('Submission connection lost');}
  }else if(method==='POST'&&id==='pause'){paused=body.paused;value={paused};}
  else{
    const record=records.find(item=>item.id===id);
    if(!record){status=404;value={error:'Not found'};}
    else if(method==='GET')value={...copy(record),snapshot};
    else if(body.revision!==record.revision){status=409;value={error:'This test changed in another browser. Refresh the queue.'};}
    else if(method==='DELETE'){records=records.filter(item=>item.id!==id);value={id,deleted:true};}
    else{
      record.revision++;
      if(action==='hold')record.state='held';
      if(action==='release')record.state='queued';
      if(action==='update')Object.assign(record,{name:body.name,options:copy(body.options),mode:body.mode,state:'queued'});
      if(action==='stop')record.state='stopping';
      if(action==='move'){
        const waiting=records.filter(item=>['queued','held'].includes(item.state)).sort((a,b)=>a.position-b.position),index=waiting.indexOf(record),other=waiting[index+body.direction];
        if(other){[record.position,other.position]=[other.position,record.position];other.revision++;}
      }
      value=copy(record);
    }
  }
  return {ok:status<400,status,json:async()=>copy(value)};
}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/queue.js'),'utf8'),context);
const call=source=>vm.runInContext(source,context),settle=()=>new Promise(resolve=>setImmediate(resolve));
context.config={beginEdit:id=>({id,restore:value=>{settings=copy(value);loaded=copy(value)},end:()=>endedEdits++}),settings:()=>copy(settings),catalog:()=>({metrics:{ev_ebitda:{label:'Valuation'}},filters:{}}),presentation:value=>({periodLabel:value.start+' → '+value.end}),prepare:()=>preparations++,restore:value=>{settings=copy(value);loaded=copy(value)},open:value=>opened=value,metricLabel:()=> 'EV/EBITDA',filterLabel:value=>value};
(async()=>{
  call('BacktestQueue.init(config)');await settle();assert(!node('queue-add').disabled);
  node('queue-name').value='<First & strategy>';await call('BacktestQueue.add()');
  settings.rank_to=25;node('queue-name').value='Second';await call('BacktestQueue.add()');
  assert.equal(records.length,2);assert.equal(records[0].options.rank_to,50);assert.equal(records[1].options.rank_to,25);
  assert.equal(preparations,2,'Queue additions keep parameter setup manual between fast cached tests');
  assert(node('queue-list').innerHTML.includes('&lt;First &amp; strategy&gt;'));assert(!node('queue-list').innerHTML.includes('<First & strategy>'));
  assert.equal(call('BacktestQueue.isManaging()'),true,'Queue construction must suspend automatic immediate runs');
  const first=records[0].id,second=records[1].id;context.first=first;context.second=second;
  await call('BacktestQueue.action("edit",first)');assert.equal(loaded.rank_to,50);assert.equal(call('BacktestQueue.isEditing()'),true);
  settings.rank_to=10;assert.equal(records[0].options.rank_to,50,'Form edits do not mutate submitted settings');
  await call('BacktestQueue.add()');assert.equal(records.find(item=>item.id===first).options.rank_to,10);assert.equal(call('BacktestQueue.isEditing()'),false);
  assert.equal(endedEdits,1,'A confirmed save ends the form session');
  await call('BacktestQueue.action("edit",first)');settings.rank_to=99;
  await node('queue-cancel-edit').handlers.click();assert.equal(records.find(item=>item.id===first).options.rank_to,10);assert.equal(call('BacktestQueue.isEditing()'),false);
  assert.equal(endedEdits,2,'A confirmed cancel ends the form session');
  await call('BacktestQueue.action("up",second)');assert(records.find(item=>item.id===second).position<records.find(item=>item.id===first).position);
  await node('queue-pause').handlers.click();assert(paused);assert.equal(node('queue-pause').textContent,'Resume queue');
  await node('queue-pause').handlers.click();assert(!paused);
  await call('BacktestQueue.action("copy",first)');assert.equal(loaded.rank_to,10);assert(node('queue-name').value.endsWith('copy'));
  const beforeDelete=requests.length;await call('BacktestQueue.action("delete",second)');assert.equal(requests.length,beforeDelete);
  assert(node('queue-list').innerHTML.includes('Delete this test and its result?'));
  await call('BacktestQueue.action("keep",second)');assert.equal(records.length,2);
  await call('BacktestQueue.action("confirm",second)');assert.equal(records.length,1);assert.equal(records[0].id,first);

  records[0].state='running';await call('BacktestQueue.refresh()');await call('BacktestQueue.action("stop",first)');assert.equal(records[0].state,'stopping');
  records[0].state='complete';records[0].cagr=.125;await call('BacktestQueue.refresh()');
  const beforeOpen=requests.length;await call('BacktestQueue.action("open",first)');assert.equal(opened.settings.rank_to,50);
  assert.equal(requests[beforeOpen].method,undefined);assert(node('queue-list').innerHTML.includes('12.50%'));

  // An acknowledged submission remains successful if list reconciliation fails.
  failList=true;node('queue-name').value='Confirmed';await call('BacktestQueue.add()');failList=false;
  assert.equal(records.length,2);assert(node('queue-status').textContent.includes('Test added'));
  assert(node('queue-status').textContent.includes('could not be refreshed'));assert.equal(node('queue-status').className,'hint');

  // A lost acknowledgement retries the original ID and immutable parameters.
  loseAcknowledgement=true;settings.rank_to=13;node('queue-name').value='Retry once';await call('BacktestQueue.add()');
  const queued=copy(records.at(-1));assert(storage.has('backtest-queue-submission'));
  settings.rank_to=77;await call('BacktestQueue.add()');assert.equal(records.length,3);assert.equal(records.at(-1).id,queued.id);
  assert.equal(records.at(-1).options.rank_to,13);assert(!storage.has('backtest-queue-submission'));

  // A delayed list may not restore an item after an acknowledged deletion.
  holdList=true;const old=call('BacktestQueue.refresh()');await settle();context.last=queued.id;
  await call('BacktestQueue.action("confirm",last)');releaseList();await old;
  assert(!node('queue-list').innerHTML.includes(queued.id));

  // A stale editor cannot overwrite changes acknowledged in another browser.
  records.find(item=>item.id===first).state='queued';await call('BacktestQueue.refresh()');
  await call('BacktestQueue.action("edit",first)');records.find(item=>item.id===first).revision++;settings.rank_to=88;
  await call('BacktestQueue.add()');assert(node('queue-status').textContent.includes('changed in another browser'));
  assert.notEqual(records.find(item=>item.id===first).options.rank_to,88);
  assert.equal(endedEdits,2,'An unconfirmed save must retain its form session');
  console.log('Passed: parameter snapshots, held edits/cancel, order, pause/resume, Stop, copying, explicit deletion, stored-result opening, lost acknowledgements and stale-read/editor protection.');
})().catch(error=>{console.error(error);process.exitCode=1});
