const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,handlers:{},addEventListener(type,fn){this.handlers[type]=fn},scrollIntoView(){}});return nodes.get(id)}
const CalendarSettings=require('../website/browser/calendar-settings.js');
const copy=value=>JSON.parse(JSON.stringify(value));
let records=[],paused=false,requests=[],loaded=null,opened=null,failList=false,loseAcknowledgement=false,holdList=false,releaseList,preparations=0,endedEdits=0,loseEditAcknowledgement=null,rejectEditOnce=false,libraryChanges=0;
const editReceipts=new Map();
let settings={selection_order:'rank_first',mode:'custom',start:'2015-01-01',end:'2016-12-30',months:3,rank_from:1,rank_to:50,pool:'legacy',metric:'ev_ebitda',min_cap:100e6,max_cap:null,min_ev:50e6,min_yield:0,max_multiple:null,filters:[{field:'market_cap',op:'gt',value:100}]};
const snapshot={version:2,kind:'custom',settings:copy(settings),catalog:{metrics:{},filters:{}},presentation:{},result:{periods:[]}};
const storage=new Map();
let allocated=0;
const context=vm.createContext({CalendarSettings,console,crypto:{getRandomValues(bytes){allocated++;return require('node:crypto').webcrypto.getRandomValues(bytes);}},Uint8Array,Date,location:{protocol:'http:'},document:{getElementById:node},localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},setInterval(){},async fetch(url,options={}){
  requests.push({url,...options});const method=options.method||'GET',parts=url.split('/').slice(3),id=parts[0],action=parts[1];
  let value,status=200;const body=options.body?JSON.parse(options.body):{};
  if(method==='GET'&&!id){
    if(failList)throw Error('List disconnected');
    value={records:copy(records.filter(record=>record.state!=='archived')),paused,limit:100,library_revision:records.filter(record=>record.state==='archived').length};
    if(holdList){holdList=false;await new Promise(resolve=>releaseList=resolve);}
  }else if(method==='POST'&&!id){
    let record=records.find(item=>item.id===body.id);
    if(!record){record={id:body.id,name:body.name,mode:body.mode,options:copy(body.options),state:'queued',position:records.length+1,revision:1,cagr:null,edit:null};records.push(record);}
    value=copy(record);
    if(loseAcknowledgement){loseAcknowledgement=false;throw Error('Submission connection lost');}
  }else if(method==='POST'&&id==='pause'){paused=body.paused;value={paused};}
  else{
    const record=records.find(item=>item.id===id);
    if(!record){status=404;value={error:'Not found'};}
    else if(method==='GET')value={...copy(record),snapshot};
    else if(action==='update'&&rejectEditOnce){rejectEditOnce=false;status=400;value={error:'Fix the settings'};}
    else if(action==='hold'&&record.edit?.id===body.edit_id)value=copy(record);
    else if(['update','release'].includes(action)&&body.edit_id&&
      (record.edit?.id!==body.edit_id||record.edit?.revision!==body.edit_revision)){
      status=409;value={error:'This edit has ended or was replaced. Refresh the queue.'};
    }else if(['update','release'].includes(action)&&body.edit_id&&record.edit.state!=='active'){
      if(editReceipts.get(body.edit_id)===JSON.stringify({action,body}))value=copy(record);
      else {status=409;value={error:'This edit has already ended.'};}
    }else if(!(['update','release'].includes(action)&&body.edit_id)&&body.revision!==record.revision){status=409;value={error:'This test changed in another browser. Refresh the queue.'};}
    else if(method==='DELETE'){records=records.filter(item=>item.id!==id);value={id,deleted:true};}
    else{
      record.revision++;
      if(action==='hold'){record.state='held';record.edit={id:body.edit_id,revision:record.revision,state:'active'};}
      if(action==='release')record.state='queued';
      if(action==='update')Object.assign(record,{name:body.name,options:copy(body.options),mode:body.mode,state:'queued'});
      if(['update','release'].includes(action)){
        record.edit.state=action==='update'?'saved':'cancelled';editReceipts.set(body.edit_id,JSON.stringify({action,body}));
      }
      if(action==='stop')record.state='stopping';
      if(action==='move'){
        const waiting=records.filter(item=>['queued','held'].includes(item.state)).sort((a,b)=>a.position-b.position),index=waiting.indexOf(record),other=waiting[index+body.direction];
        if(other){[record.position,other.position]=[other.position,record.position];other.revision++;}
      }
      value=copy(record);
      if(loseEditAcknowledgement?.action===action){
        const loss=loseEditAcknowledgement;loseEditAcknowledgement=null;
        if(loss.state)record.state=loss.state;
        if(loss.disconnectList)failList=true;
        throw Error('Edit response lost');
      }
    }
  }
  return {ok:status<400,status,json:async()=>copy(value)};
}});
context.ResultArtifacts={opening:()=>()=>true,release:()=>{},async use(source,consume){const response=await context.fetch((source.kind==='saved'?'/api/backtests/':'/api/backtest-queue/')+source.id);const record=await response.json();if(record.state==='archived')return {consumed:false,record};if(!record.snapshot)throw Error('This result is not ready yet.');return {consumed:true,value:consume(record.snapshot),record};}};
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/engine-controls.js'),'utf8'),context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/backtest-comparison.js'),'utf8'),context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/queue.js'),'utf8'),context);
const call=source=>vm.runInContext(source,context),settle=()=>new Promise(resolve=>setImmediate(resolve));
context.config={libraryChanged:()=>libraryChanges++,beginEdit:id=>({id,restore:value=>{settings=copy(value);loaded=copy(value)},end:()=>endedEdits++}),settings:()=>copy(settings),catalog:()=>({metrics:{ev_ebitda:{label:'Valuation'}},filters:{}}),presentation:value=>({periodLabel:value.start+' → '+value.end}),prepare:()=>preparations++,restore:value=>{settings=copy(value);loaded=copy(value)},open:value=>opened=value,metricLabel:()=> 'EV/EBITDA',filterLabel:value=>value};
(async()=>{
  call('BacktestQueue.init(config)');await settle();assert(!node('queue-add').disabled);
  node('queue-name').value='<First & strategy>';await call('BacktestQueue.add()');
  settings.rank_to=25;settings.selection_order='filter_first';node('queue-name').value='Second';await call('BacktestQueue.add()');
  assert.equal(records.length,2);assert.equal(records[0].options.rank_to,50);assert.equal(records[1].options.rank_to,25);
  assert.equal(records[0].options.selection_order,'rank_first');assert.equal(records[1].options.selection_order,'filter_first');
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

  // Moving this test or its neighbor leaves the held settings version valid.
  records.find(item=>item.id===first).state='queued';await call('BacktestQueue.refresh()');
  await call('BacktestQueue.action("edit",first)');
  await call('BacktestQueue.action("down",first)');context.neighbor=records.find(item=>item.id!==first).id;await call('BacktestQueue.action("up",neighbor)');
  settings.rank_to=17;await call('BacktestQueue.add()');
  assert.equal(records.find(item=>item.id===first).options.rank_to,17);assert(!call('BacktestQueue.isEditing()'));

  // A lost hold response is recovered by its stable identity.
  loseEditAcknowledgement={action:'hold'};await call('BacktestQueue.action("edit",first)');
  assert(call('BacktestQueue.isEditing()'));assert(node('queue-status').textContent.includes('recovered'));
  await node('queue-cancel-edit').handlers.click();

  // A hold with both responses lost retries the same identity before editing.
  loseEditAcknowledgement={action:'hold',disconnectList:true};await call('BacktestQueue.action("edit",first)');
  const heldToken=records.find(item=>item.id===first).edit.id;
  assert.equal(node('queue-add').textContent,'Retry edit request');
  failList=false;await call('BacktestQueue.add()');
  assert.equal(records.find(item=>item.id===first).edit.id,heldToken);
  assert.equal(node('queue-add').textContent,'Save queued test');
  rejectEditOnce=true;settings.rank_to=15;await call('BacktestQueue.add()');
  assert.equal(node('queue-add').textContent,'Save queued test');assert(!node('queue-cancel-edit').disabled);
  settings.rank_to=16;await call('BacktestQueue.add()');
  assert.equal(records.find(item=>item.id===first).options.rank_to,16);

  // Lost Save/Cancel responses close the local draft even after execution starts.
  for(const action of ['update','release']){
    records.find(item=>item.id===first).state='queued';await call('BacktestQueue.refresh()');
    await call('BacktestQueue.action("edit",first)');settings.rank_to=19;
    const before=endedEdits;
    loseEditAcknowledgement={action,state:'running'};
    if(action==='update')await call('BacktestQueue.add()');else await node('queue-cancel-edit').handlers.click();
    assert(!call('BacktestQueue.isEditing()'));assert.equal(endedEdits,before+1);
    assert.equal(settings.rank_to,19,'Reconciliation preserves the current form instead of replacing it');
    assert(node('queue-status').textContent.includes('edit has ended'));
  }

  // If both acknowledgement and list are lost, retry the original immutable Save.
  records.find(item=>item.id===first).state='queued';await call('BacktestQueue.refresh()');
  await call('BacktestQueue.action("edit",first)');settings.rank_to=23;
  loseEditAcknowledgement={action:'update',state:'complete',disconnectList:true};
  await call('BacktestQueue.add()');assert(call('BacktestQueue.isEditing()'));
  assert.equal(node('queue-add').textContent,'Retry save');
  settings.rank_to=99;failList=false;await call('BacktestQueue.add()');
  assert(!call('BacktestQueue.isEditing()'));assert.equal(records.find(item=>item.id===first).options.rank_to,23);

  // A Cancel with both responses lost remains retryable after execution finishes.
  records.find(item=>item.id===first).state='queued';await call('BacktestQueue.refresh()');
  await call('BacktestQueue.action("edit",first)');
  loseEditAcknowledgement={action:'release',state:'complete',disconnectList:true};
  await node('queue-cancel-edit').handlers.click();assert(call('BacktestQueue.isEditing()'));
  assert.equal(node('queue-cancel-edit').textContent,'Retry cancel');assert(node('queue-add').disabled);
  failList=false;await node('queue-cancel-edit').handlers.click();assert(!call('BacktestQueue.isEditing()'));

  // An externally ended or replaced hold releases the form, without saving its draft.
  for(const external of ['release','replace','delete']){
    if(!records.some(item=>item.id===first))break;
    records.find(item=>item.id===first).state='queued';await call('BacktestQueue.refresh()');
    await call('BacktestQueue.action("edit",first)');settings.rank_to=88;
    const target=records.find(item=>item.id===first),before=endedEdits;
    if(external==='delete')records=records.filter(item=>item.id!==first);
    else if(external==='replace')target.edit.id='f'.repeat(32);
    else {target.state='running';target.edit.state='cancelled';}
    await call('BacktestQueue.refresh()');
    assert(!call('BacktestQueue.isEditing()'));assert.equal(endedEdits,before+1);assert.equal(settings.rank_to,88);
  }
  // Full and failed publication remain complete, with clear retry labels.
  records=[{id:'c'.repeat(32),name:'Waiting for slot',mode:'custom',options:copy(settings),state:'complete',position:1,revision:1,cagr:.1,transfer:{state:'pending',error:'full'}}];
  await call('BacktestQueue.refresh()');
  assert(node('queue-list').innerHTML.includes('Completed — waiting for saved slot'));
  assert(node('queue-list').innerHTML.includes('Open result'));
  records[0].transfer.error='retry';await call('BacktestQueue.refresh()');
  assert(node('queue-list').innerHTML.includes('Saving failed. Results are kept here'));
  records[0].transfer.state='reserved';await call('BacktestQueue.refresh()');
  assert(node('queue-list').innerHTML.includes('Moving to Saved backtests'));
  assert(!node('queue-list').innerHTML.includes('data-action="delete"'));
  // A stale Open click explains that transfer finished and refreshes the library.
  records[0].state='archived';records[0].transfer={state:'archived',saved_id:'d'.repeat(32)};
  const beforeMoved=libraryChanges;
  await call('BacktestQueue.action("open","'+records[0].id+'")');
  assert(node('queue-status').textContent.includes('moved to Saved backtests'));
  assert(libraryChanges>beforeMoved);assert(!node('queue-list').innerHTML.includes('Waiting for slot'));
  // A lost enqueue acknowledgement retries the same archived receipt without
  // placing it back in the list, even when list reconciliation fails.
  settings={...settings,mode:'custom'};loseAcknowledgement=true;
  await call('BacktestQueue.add()');
  const submission=JSON.parse(storage.get('backtest-queue-submission'));
  const accepted=records.find(record=>record.id===submission.id);accepted.state='archived';
  accepted.transfer={state:'archived',saved_id:'e'.repeat(32)};failList=true;
  const beforeRetry=libraryChanges;await call('BacktestQueue.add()');
  assert(!storage.has('backtest-queue-submission'));assert(libraryChanges>beforeRetry);
  assert(!node('queue-list').innerHTML.includes(accepted.id));assert(node('queue-status').textContent.includes('already moved'));
  failList=false;
  // Scalar preparation snapshots before awaiting, and finishes before identity.
  const scalar={format:'strategy-capture',version:1,pool:'legacy',bounds:{min_cap:100e6,max_cap:null,min_ev:50e6,sector:null,exchange:null},selection:{ranking:{source:{kind:'builtin',id:'filter:pe'},direction:'lowest'},rank_from:2,rank_to:8,selection_order:'rank_first',conditions:[]},builtins:[{id:'filter:pe',label:'Original P/E'}],variables:null};
  settings={mode:'custom',start:'2015-01-02',end:'2015-01-05',months:12,strategy:scalar};
  let releaseCapture,captures=0;
  context.config.prepareSubmission=async()=>{const submitted=copy(settings);captures++;await new Promise(resolve=>releaseCapture=resolve);return submitted;};
  node('queue-name').value='Captured name';const idsBefore=allocated,requestsBefore=requests.filter(r=>r.method==='POST'&&r.url==='/api/backtest-queue').length;
  const adding=call('BacktestQueue.add()');await settle();assert.equal(allocated,idsBefore);assert.equal(requests.filter(r=>r.method==='POST'&&r.url==='/api/backtest-queue').length,requestsBefore);
  settings.strategy.selection.rank_to=99;node('queue-name').value='Later name';loseAcknowledgement=true;releaseCapture();await adding;
  const scalarPending=JSON.parse(storage.get('backtest-queue-submission'));assert.equal(scalarPending.options.strategy.selection.rank_to,8);assert.equal(scalarPending.name,'Captured name');
  settings.strategy.selection.rank_to=77;await call('BacktestQueue.add()');assert.equal(captures,1);assert(!storage.has('backtest-queue-submission'));
  const scalarRecord=records.find(record=>record.id===scalarPending.id);assert.equal(scalarRecord.options.strategy.selection.rank_to,8);assert(node('queue-list').innerHTML.includes('Original P/E'));
  context.scalarId=scalarRecord.id;await call('BacktestQueue.action("edit",scalarId)');settings.strategy.selection.rank_to=6;
  const saving=call('BacktestQueue.add()');await settle();settings.strategy.selection.rank_to=31;
  loseEditAcknowledgement={action:'update',disconnectList:true};releaseCapture();await saving;
  const captureCount=captures;failList=false;await call('BacktestQueue.add()');assert.equal(captures,captureCount);assert.equal(scalarRecord.options.strategy.selection.rank_to,6);assert.equal(settings.strategy.selection.rank_to,31);
  await call('BacktestQueue.action("edit",scalarId)');settings.strategy.selection.rank_to=4;
  const updatesBefore=requests.filter(request=>request.url.endsWith('/update')).length,endedBefore=endedEdits;
  const abandoned=call('BacktestQueue.add()');await settle();
  scalarRecord.state='running';scalarRecord.edit.state='cancelled';await call('BacktestQueue.refresh()');assert.equal(endedEdits,endedBefore+1);
  releaseCapture();await abandoned;assert.equal(requests.filter(request=>request.url.endsWith('/update')).length,updatesBefore);assert.equal(settings.strategy.selection.rank_to,4);
  console.log('Passed: snapshots, order-independent edit sessions, lost hold/save/cancel acknowledgements, immutable retry after execution, external hold reconciliation, queue controls and stale-read protection.');
})().catch(error=>{console.error(error);process.exitCode=1});
