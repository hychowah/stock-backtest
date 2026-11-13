const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,handlers:{},querySelectorAll(){return []},addEventListener(type,fn){this.handlers[type]=fn}});return nodes.get(id)}
const CalendarSettings=require('../website/browser/calendar-settings.js');
const copy=value=>JSON.parse(JSON.stringify(value));
let records=[],paused=false,requests=[],loaded=null,opened=null,failList=false,loseAcknowledgement=false,holdList=false,releaseList,builderShown=0,endedEdits=0,loseEditAcknowledgement=null,rejectEditOnce=false,libraryChanges=0;
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
    if(!record){record={id:body.id,name:body.name.trim(),mode:body.mode,options:copy(body.options),state:'queued',position:records.length+1,revision:1,cagr:null,edit:null};records.push(record);}
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
      if(action==='update')Object.assign(record,{name:body.name.trim(),options:copy(body.options),mode:body.mode,state:'queued'});
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
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/run-markets.js'),'utf8'),context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/queue.js'),'utf8'),context);
const call=source=>vm.runInContext(source,context),settle=()=>new Promise(resolve=>setImmediate(resolve));
context.config={libraryChanged:()=>libraryChanges++,beginEdit:id=>({id,restore:value=>{settings=copy(value);loaded=copy(value)},end:()=>endedEdits++}),prepareSubmission:async()=>copy(settings),catalog:()=>({metrics:{ev_ebitda:{label:'Valuation'}},filters:{}}),presentation:value=>({periodLabel:value.start+' → '+value.end}),showBuilder:()=>builderShown++,restore:value=>{settings=copy(value);loaded=copy(value)},open:value=>opened=value,metricLabel:()=> 'EV/EBITDA',filterLabel:value=>value};
(async()=>{
  call('BacktestQueue.init(config)');await settle();assert(!node('queue-add').disabled);
  // The line beside the name box takes no space until Add, Tune or a held edit has something to say.
  assert.equal(node('queue-builder-status').hidden,true);assert.equal(node('queue-status').textContent,'Queue ready. Tests and results are saved on the server.');
  node('queue-name').value='<First & strategy>';await call('BacktestQueue.add()');
  // Add reports below the name box in Build strategy. The Runs line keeps its text.
  assert(node('queue-add-status').textContent.startsWith('Test added to the queue.'));assert.equal(node('queue-edit-note').textContent,'');
  assert.equal(node('queue-builder-status').hidden,false);assert.equal(node('queue-status').textContent,'Queue ready. Tests and results are saved on the server.');
  // The name box sits in the strategy form: typing a name is not a settings change. Enter does what a click on
  // the enabled Add button does. Enter that ends an input-method composition is left to the composition.
  let stopped=0,prevented=0;for(const type of ['input','change'])node('queue-name').handlers[type]({stopPropagation(){stopped++}});assert.equal(stopped,2);
  const enter=extra=>node('queue-name').handlers.keydown({key:'Enter',preventDefault(){prevented++},...extra});
  await node('queue-name').handlers.keydown({key:'a',preventDefault(){prevented++}});assert.equal(records.length,1);
  settings.rank_to=25;settings.selection_order='filter_first';node('queue-name').value='Second';
  await enter({isComposing:true});assert.deepEqual([records.length,prevented],[1,0]);
  await enter();assert.deepEqual([records.length,prevented],[2,1]);
  assert.equal(records.length,2);assert.equal(records[0].options.rank_to,50);assert.equal(records[1].options.rank_to,25);
  assert.equal(records[0].options.selection_order,'rank_first');assert.equal(records[1].options.selection_order,'filter_first');
  assert(node('queue-list').innerHTML.includes('&lt;First &amp; strategy&gt;'));assert(!node('queue-list').innerHTML.includes('<First & strategy>'));
  const first=records[0].id,second=records[1].id;context.first=first;context.second=second;
  // A held edit opens the builder with the settings of the test.
  await call('BacktestQueue.action("edit",first)');assert.equal(loaded.rank_to,50);assert.equal(call('BacktestQueue.isEditing()'),true);assert.equal(builderShown,1);
  settings.rank_to=10;assert.equal(records[0].options.rank_to,50,'Form edits do not mutate submitted settings');
  // The draft decides the saved format: a held save asks it to keep an
  // unchanged original selection. Here the draft returns the flat settings.
  const prepareNew=context.config.prepareSubmission;let heldRequest;context.config.prepareSubmission=async request=>{heldRequest=request;return copy(settings);};
  await call('BacktestQueue.add()');assert.equal(records.find(item=>item.id===first).options.rank_to,10);assert.equal(call('BacktestQueue.isEditing()'),false);
  assert.equal(records.find(item=>item.id===first).name,'<First & strategy>','A held edit keeps a typed name');
  context.config.prepareSubmission=prepareNew;assert.deepEqual(JSON.parse(JSON.stringify(heldRequest)),{held:true});assert(!('strategy' in records.find(item=>item.id===first).options));
  assert.equal(endedEdits,1,'A confirmed save ends the form session');
  await call('BacktestQueue.action("edit",first)');settings.rank_to=99;
  await node('queue-cancel-edit').handlers.click();assert.equal(records.find(item=>item.id===first).options.rank_to,10);assert.equal(call('BacktestQueue.isEditing()'),false);
  assert.equal(endedEdits,2,'A confirmed cancel ends the form session');
  await call('BacktestQueue.action("up",second)');assert(records.find(item=>item.id===second).position<records.find(item=>item.id===first).position);
  await node('queue-pause').handlers.click();assert(paused);assert.equal(node('queue-pause').textContent,'Resume queue');
  await node('queue-pause').handlers.click();assert(!paused);
  // Tune is a row action: it reports on Runs. The draft owner empties the name box (check-range.cjs).
  await call('BacktestQueue.action("copy",first)');assert.equal(loaded.rank_to,10);assert(node('queue-status').textContent.startsWith('Settings copied'));
  const beforeDelete=requests.length;await call('BacktestQueue.action("delete",second)');assert.equal(requests.length,beforeDelete);
  assert(node('queue-list').innerHTML.includes('Delete this test and its result?'));
  await call('BacktestQueue.action("keep",second)');assert.equal(records.length,2);
  await call('BacktestQueue.action("confirm",second)');assert.equal(records.length,1);assert.equal(records[0].id,first);

  records[0].state='running';records[0].progress={type:'trial',completed:3,total:24,calculated_books:5,total_new_books:12};await call('BacktestQueue.refresh()');
  assert(node('queue-list').innerHTML.includes('3/24 trials · 5/12 new books'),'A running row shows its progress');
  await call('BacktestQueue.action("stop",first)');assert.equal(records[0].state,'stopping');
  records[0].state='complete';records[0].cagr=.125;await call('BacktestQueue.refresh()');
  const beforeOpen=requests.length;await call('BacktestQueue.action("open",first)');assert.equal(opened.settings.rank_to,50);
  assert.equal(requests[beforeOpen].method,undefined);assert(node('queue-list').innerHTML.includes('12.50%'));

  // An acknowledged submission remains successful if list reconciliation fails.
  failList=true;node('queue-name').value='Confirmed';await call('BacktestQueue.add()');failList=false;
  assert.equal(records.length,2);assert(node('queue-add-status').textContent.includes('Test added'));
  assert(node('queue-add-status').textContent.includes('could not be refreshed'));assert.equal(node('queue-add-status').className,'hint');

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
  assert(call('BacktestQueue.isEditing()'));assert(node('queue-add-status').textContent.includes('recovered'));
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
    assert(node('queue-add-status').textContent.includes('edit has ended'));
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
  assert(node('queue-list').innerHTML.includes('Completed — waiting for saved slot'));assert(node('queue-list').innerHTML.includes('Delete a saved backtest to make room.'));
  assert(node('queue-list').innerHTML.includes('Open result'));
  records[0].transfer.error='retry';await call('BacktestQueue.refresh()');
  assert(node('queue-list').innerHTML.includes('Saving failed. Results are kept here'));
  records[0].transfer.error='too_large';await call('BacktestQueue.refresh()');
  assert(node('queue-list').innerHTML.includes('128 MiB save and open limit. The result stays in the queue.'));
  assert(!node('queue-list').innerHTML.includes('the server will retry'));
  assert(node('queue-list').innerHTML.includes('Open result'));
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
  assert(!node('queue-list').innerHTML.includes(accepted.id));assert(node('queue-add-status').textContent.includes('already moved to Saved backtests'));
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
  // An empty name says in plain wording what the row columns do not show: the last Rank first, then every
  // other step in step order. The columns show the dates and the test type.
  const chain={format:'strategy-capture',version:2,universe:{pool:'cached'},steps:[{kind:'rank',source:{kind:'builtin',id:'filter:pe'},direction:'lowest',rank_from:1,rank_to:200},
    {kind:'filter',source:{kind:'field',field:'sector'},op:'eq',threshold:'Energy'},{kind:'rank',source:{kind:'builtin',id:'filter:pe'},direction:'highest',rank_from:20,rank_to:40},
    {kind:'filter',source:{kind:'field',field:'market_cap'},op:'ge',threshold:{value:'100000000',unit:'USD'},submitted_threshold:{value:'100',unit:'usd_million'},comparison_value:100e6,storage_comparison_value:100e6}],builtins:[{id:'filter:pe',label:'Chain P/E'}],variables:null};
  const queueDefault=async next=>{settings=next;context.config.prepareSubmission=async()=>copy(settings);node('queue-name').value='';await call('BacktestQueue.add()');return records.at(-1);};
  const dated={mode:'custom',start:'2015-01-02',end:'2015-01-05'},twoRanks='Ranks 20–40 · Chain P/E · highest first · Chain P/E · lowest first · ranks 1–200 · Sector = Energy · Market cap ≥ $100M';
  const chainRecord=await queueDefault({...dated,months:12,strategy:chain});assert.equal(chainRecord.name,twoRanks);
  // The name adds the rebalance interval when it is not 12 months, and the market when it is not US.
  const oneRank={...copy(chain),steps:chain.steps.slice(2)};
  assert.equal((await queueDefault({mode:'random',trials:3,market:'hk',calendar:{version:1,start:'2015-01-02',end:'2015-01-05',interval:{unit:'week',count:2}},strategy:oneRank})).name,'Hong Kong · Ranks 20–40 · Chain P/E · highest first · every 2 weeks · Market cap ≥ $100M');
  // Sleeves are named in place of the last Rank and the steps.
  const sleeved={...copy(chain),version:3,steps:undefined,sleeves:[{name:'Energy',steps:chain.steps.slice(0,2)},{name:'P/E',steps:chain.steps.slice(2)}]};
  assert.equal((await queueDefault({...dated,months:12,strategy:sleeved})).name,'Ranks 1–221 · Sleeves Energy + P/E');
  // The row line shows the name, state, test type and dates only. The row control lists every setting in
  // plain wording. The exact recorded text waits in one closed disclosure of that control.
  const listed=node('queue-list').innerHTML,rowStart=listed.indexOf('data-queue-id="'+chainRecord.id+'"'),chainRow=listed.slice(rowStart,listed.indexOf('</li>',rowStart));
  const chainLine=chainRow.slice(0,chainRow.indexOf('<details')),[chainPlain,chainExact]=chainRow.slice(chainLine.length).split('Exact recorded values');
  for(const text of ['Waiting','Fixed dates','2015-01-02 → 2015-01-05'])assert(chainLine.includes(text),'Missing '+text);
  for(const text of ['Stock pool','Step 1','usd_million','canonical','filter:pe'])assert(!chainLine.includes(text),'The row line shows '+text);
  for(const text of ['Stock pool: All stocks with cached prices','Step 1 · Rank: Chain P/E · lowest first · ranks 1–200','Step 2 · Filter: Sector = Energy','Step 3 · Rank: Chain P/E · highest first · ranks 20–40','Step 4 · Filter: Market cap ≥ $100M'])
    assert(chainPlain.includes('<p>'+text+'</p>'),'Missing '+text);
  assert(chainPlain.includes('US · USD · Fixed dates · 2015-01-02 → 2015-01-05 · every 12 month(s)'),'The control names the market, the test type, the dates and the interval');
  for(const text of ['usd_million','canonical','filter:pe'])assert(!chainPlain.includes(text),'The plain list shows '+text);
  assert(chainPlain.endsWith('<details><summary>'),'The exact text is closed until the user opens it');
  for(const text of ['Step 1 · Rank: Chain P/E (filter:pe) lowest first · ranks 1–200','Step 3 · Rank: Chain P/E (filter:pe) highest first · ranks 20–40','Step 4 · Filter: Market cap (USD) ≥ 100 usd_million (canonical 100000000 USD)'])
    assert(chainExact.includes('<p>'+text+'</p>'),'Missing exact '+text);
  assert(!chainExact.includes('Sector = Energy'),'A setting without exact text is not listed again');
  // A held edit loads the name. A name that is still the default of the old settings follows the new
  // settings; a typed name stays.
  settings={...dated,months:12,strategy:copy(chain)};
  context.chainId=chainRecord.id;await call('BacktestQueue.action("edit",chainId)');assert.equal(node('queue-name').value,twoRanks);
  settings.strategy.steps[2].rank_to=30;await call('BacktestQueue.add()');
  assert.equal(chainRecord.name,twoRanks.replace('20–40','20–30'));assert.equal(chainRecord.options.strategy.steps[2].rank_to,30);
  await call('BacktestQueue.action("edit",chainId)');node('queue-name').value='Energy, my name';settings.strategy.steps[2].rank_to=25;await call('BacktestQueue.add()');
  assert.equal(chainRecord.name,'Energy, my name');assert.equal(chainRecord.options.strategy.steps[2].rank_to,25);
  // A capture/1 record and a flat record get the same form of default name.
  assert.equal(scalarRecord.name,'Captured name');scalar.selection.rank_to=8;assert.equal((await queueDefault({...dated,months:12,strategy:scalar})).name,'Ranks 2–8 · Original P/E · lowest first');
  assert.equal((await queueDefault({...dated,months:12,rank_to:25,metric:'ev_ebitda'})).name,'Ranks 1–25 · EV/EBITDA');
  // A waiting test that names an engine this server does not run explains how to continue.
  records.push({id:'f'.repeat(32),name:'Recorded experimental',mode:'custom',options:{start:'2015-01-01',end:'2016-12-30',months:3,engine:'experimental',pool:'cached'},state:'queued',position:records.length+1,revision:1,cagr:null,edit:null});
  await call('BacktestQueue.refresh()');
  // A flat record names its pool with the same words as a chain record.
  assert(node('queue-list').innerHTML.includes(' · EV/EBITDA · All stocks with cached prices · '));assert(!node('queue-list').innerHTML.includes('All cached stocks'));
  assert(node('queue-list').innerHTML.includes('New engine — experimental cannot run on this server. Edit it to choose Original, or delete it.'));
  // In progress shows the running test first, then the waiting tests in queue order, then the others.
  const row=(letter,state,position)=>({id:letter.repeat(32),name:'Order '+letter,mode:'custom',options:copy(snapshot.settings),state,position,revision:1,cagr:null,edit:null});
  records=[row('a','failed',1),row('b','queued',2),row('c','complete',3),row('d','running',4),row('e','held',5),row('1','queued',6)];await call('BacktestQueue.refresh()');
  assert.deepEqual([...node('queue-list').innerHTML.matchAll(/data-queue-id="(.)/g)].map(match=>match[1]),['d','b','e','1','a','c']);
  await call('BacktestQueue.action("up","'+'e'.repeat(32)+'")');assert(records.find(item=>item.id[0]==='e').position<records.find(item=>item.id[0]==='b').position,'Move up still follows the waiting order');
  // The market switch of Runs shows the tests of one market and remembers the choice. Each button counts its market.
  records.find(item=>item.id[0]==='b').options.market='hk';await call('BacktestQueue.refresh()');
  const markets=['','us','hk','jp'].map(market=>({dataset:{market},attributes:{},setAttribute(name,value){this.attributes[name]=value},querySelector(){return this.count||(this.count={textContent:''})}}));
  node('run-markets').querySelectorAll=()=>markets;call('RunMarkets.init()');
  const choose=market=>node('run-markets').handlers.click({target:{closest:()=>markets.find(button=>button.dataset.market===market)}});
  choose('hk');
  assert.deepEqual([...node('queue-list').innerHTML.matchAll(/data-queue-id="(.)/g)].map(match=>match[1]),['b']);
  assert.deepEqual(markets.map(button=>[button.attributes['aria-pressed'],button.count.textContent]),[['false',6],['false',5],['true',1],['false',0]]);
  assert.equal(storage.get('runs-market'),'hk');
  choose('jp');assert(node('queue-list').innerHTML.includes('No Tokyo test is waiting or running.'));
  choose('');assert.equal([...node('queue-list').innerHTML.matchAll(/data-queue-id=/g)].length,6);
  console.log('Passed: snapshots, default and held-edit names, Enter as the Add button, Add and held-edit messages beside the name box, one-line rows in In progress order, the market switch, exact text in one closed disclosure, order-independent edit sessions, lost hold/save/cancel acknowledgements, immutable retry after execution, external hold reconciliation, queue controls and stale-read protection.');
})().catch(error=>{console.error(error);process.exitCode=1});
