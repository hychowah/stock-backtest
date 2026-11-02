'use strict';
// Execute the current form/draft owner before its page bootstrap. UI and async
// transport are controlled; the draft implementation is loaded from source.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const nodes=new Map(),requests=[],ids=[],posted=[],storage=new Map();
const node=id=>{if(!nodes.has(id))nodes.set(id,{id,value:'',checked:false,tagName:'INPUT',options:[],textContent:'',innerHTML:'',disabled:false,hidden:false,add(){},setAttribute(){},querySelectorAll:()=>[]});return nodes.get(id);};
node('screening-data').textContent=JSON.stringify({metrics:{ev_ebitda:{label:'EV/EBITDA'}},filter_catalog:{pe:{label:'P/E'}},companies:{},latest:{metadata:{asof:'2015-01-05'}}});
const defaults={selection_order:'filter_first',metric:'ev_ebitda',pool:'legacy',min_cap:100e6,max_cap:null,min_ev:50e6,min_yield:0,max_multiple:null,sector:null,exchange:null};
let release=null,pause=false,useWire=false;
const wireOrigin=process.argv[2]==='--wire'?process.argv[3]:null;
const wire=wireOrigin?JSON.parse(fs.readFileSync(0,'utf8')):null;
const builtins={pe:{display:'multiple'},operating_yield_spread_3y:{display:'percentage_points'}};
const workspaceModule={exports:{}};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../website/browser/variable-workspace.js'),'utf8'),{module:workspaceModule});
const complete=input=>input.original||({format:'strategy-capture',version:1,selection:input.intent.selection,pool:input.intent.pool,bounds:input.intent.bounds,variables:input.submitted?.length?{program:{bundle:{definitions:input.submitted},definitions:input.submitted.map(entry=>({...entry,...entry.definition.output}))},presentation:input.labels}:null,builtins:[],limits:{bytes:196608}});
const context=vm.createContext({console,data:[],document:{getElementById:node,querySelector:node,querySelectorAll:()=>[]},StockScreener:{defaults},
 CalendarSettings:{read:()=>({start:'2015-01-02',end:'2015-01-05',months:12}),restore(){},decode:v=>v},EngineControls:{fields:()=>({engine:'original'}),sync(){}},
 ResultArtifacts:{forView:()=>null,matches:()=>false},ScheduleView:{isRunning:()=>false},SavedBacktests:{update(){}},BacktestQueue:{isManaging:()=>false},
 VariableWorkspace:{content:workspaceModule.exports.content,builtin:id=>useWire?wire.builtins.find(item=>item.id===id):builtins[id.slice(7)],request:async(route,input)=>{assert(['/capture','/detached'].includes(route));requests.push(structuredClone(input));if(pause)await new Promise(resolve=>release=resolve);if(useWire){const body=JSON.stringify(input);assert(Buffer.byteLength(body)<=256*1024);const response=await fetch(wireOrigin+'/api/variables'+route,{method:'POST',headers:{'Content-Type':'application/json'},body});const value=await response.json();assert(response.ok,JSON.stringify(value));return value;}return route==='/detached'?{authored:input.capture.program.bundle.definitions}:{strategy:complete(input)};}},
 localStorage:{get length(){return storage.size;},key:i=>[...storage.keys()][i],getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
 crypto:{getRandomValues(bytes){ids.push(1);bytes.fill(ids.length);return bytes;}},Uint8Array,Date,AbortController,setTimeout,clearTimeout,
 fetch:async(url,options)=>{posted.push(JSON.parse(options.body));return {ok:true,json:async()=>({state:'complete',evidence:{manifest:{periods:1}}})};}
});
const source=fs.readFileSync(path.join(__dirname,'../website/browser/range.js'),'utf8');
vm.runInContext(source.slice(0,source.indexOf('\ninitializeFilters();')),context);
vm.runInContext('updateResultsState=()=>{};setModeVisibility=()=>{};renderConditions=()=>{};',context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/backtest-runs.js'),'utf8'),context);
const run=code=>vm.runInContext(code,context),copy=value=>JSON.parse(JSON.stringify(value)),tick=()=>new Promise(resolve=>setImmediate(resolve));
for(const [key,id] of Object.entries({selection_order:'selection-order',metric:'ranking-metric',pool:'stock-pool',min_cap:'min-cap',max_cap:'max-cap',min_ev:'min-ev',min_yield:'min-yield',max_multiple:'max-multiple',sector:'sector-filter',exchange:'exchange-filter'}))node(id).value=defaults[key]===null?'':String(key==='min_cap'||key==='min_ev'?defaults[key]/1e6:defaults[key]);
node('rank-from').value='3';node('rank-to').value='12';node('from-year').value='2015';node('to-year').value='2015';node('schedule-kind').value='custom';node('date-testing').value='single';
const exact={kind:'formula',variable_id:'variable:archived',revision:'sha256:'+'a'.repeat(64)};
const detached={presentation:[{...exact,name:'Original submitted label'}],program:{bundle:{definitions:[{...exact,definition:{expression:{op:'constant',value:'1',unit:'scalar'},output:{unit:'scalar',display:'percent'}}}]},definitions:[{...exact,unit:'scalar',display:'percent'}]}};
context.source=exact;context.detached=detached;context.authored=detached.program.bundle.definitions;
(async()=>{
 // Inclusive legacy constraints must be resolved explicitly, without losing draft.
 node('min-yield').value='2';const before=run('StrategyDraft.read().revision');
 assert.throws(()=>run('StrategyDraft.patch({role:"ranking",source,capture:detached,authored},StrategyDraft.read().revision)'),/inclusive/);
 assert.equal(run('StrategyDraft.isScalar()'),false);assert.equal(node('min-yield').value,'2');assert.equal(run('StrategyDraft.read().revision'),before);
 node('min-yield').value='0';run('filterConditions=[{field:"pe",op:"lt",value:12}];StrategyDraft.patch({role:"ranking",source,capture:detached,authored},StrategyDraft.read().revision)');
 assert.equal(run('StrategyDraft.isScalar()'),true);assert.equal(run('StrategyDraft.read().settings.strategy.selection.conditions[0].source.id'),'filter:pe');
 assert(node('strategy-heading').textContent.startsWith('Highest Original submitted label'));assert(node('legacy-yield-control').hidden);assert(node('legacy-multiple-control').hidden);assert(node('ranking-metric').disabled);assert(node('auto-run').disabled);assert(node('auto-run-note').textContent.includes('suspended'));assert(!node('min-cap').required);
 const token=run('StrategyDraft.read().revision');run('StrategyDraft.patch({direction:"lowest"},StrategyDraft.read().revision)');
 assert(node('strategy-heading').textContent.startsWith('Lowest Original submitted label'));assert(node('strategy-ranking-help').textContent.includes('lowest available selected variable'));
 assert.throws(()=>run(`StrategyDraft.patch({role:'ranking',source,capture:detached,authored},${token})`),/draft changed/);
 // Snapshot is taken before await; later draft changes do not alter submitted intent.
 pause=true;const pending=run('StrategyDraft.prepareSubmission()');await tick();assert.equal(ids.length,0);
 const submitted=copy(requests.at(-1));node('min-cap').value='750';run('StrategyDraft.patch({direction:"highest"},StrategyDraft.read().revision)');
 release();pause=false;const prepared=await pending;
 assert.equal(prepared.strategy.bounds.min_cap,100e6);assert.equal(prepared.strategy.selection.ranking.direction,'lowest');assert.equal(requests.at(-1).intent.bounds.min_cap,submitted.intent.bounds.min_cap);
 assert.equal(run('StrategyDraft.read().settings.strategy.selection.ranking.direction'),'highest');
 // Capture completes before retry ID allocation; uncertain start uses exact content.
 const fresh=await run('StrategyDraft.prepareSubmission()');context.prepared=fresh;
 assert.equal(ids.length,0);const actual=run('{const {mode,...options}=prepared;BacktestRuns.create(mode,options)}');assert.equal(ids.length,1);
 fresh.strategy.bounds.min_cap=1;assert.equal(actual.options.strategy.bounds.min_cap,750e6);
 await run('BacktestRuns.follow(BacktestRuns.pending(),()=>{})');assert.equal(posted[0].options.strategy.bounds.min_cap,750e6);
 assert.equal(run('StrategyDraft.read().settings.strategy.variables.presentation[0].name'),'Original submitted label');
 // Held sessions block ordinary replacement and invalidate pickers at both ends.
 context.settings={mode:'custom',start:'2015-01-02',end:'2015-01-05',months:12,strategy:complete(requests.at(-1))};
 run("const held=StrategyDraft.beginQueuedEdit('queued');held.restore(settings)");
 const heldToken=run('StrategyDraft.read().revision');assert.throws(()=>run('StrategyDraft.restore(settings)'),/Save or cancel/);
 run('held.end()');assert.throws(()=>run(`StrategyDraft.patch({role:'ranking',source,capture:detached,authored},${heldToken})`),/draft changed/);
 // Null size floors restore exactly; the normal captured path handles old/deleted sources.
 context.settings.strategy.bounds.min_cap=null;context.settings.strategy.bounds.min_ev=null;
 run('StrategyDraft.restore(settings)');assert.equal(node('min-cap').value,'');assert.equal(run('StrategyDraft.read().settings.strategy.bounds.min_cap'),null);
 for(const mode of ['latest','january','custom','random']){
  context.settings={...context.settings,mode,first:2015,last:2015,trials:1,seed:42};run('StrategyDraft.restore(settings)');
  const value=await run('StrategyDraft.prepareSubmission()');assert.equal(value.mode,mode);assert.equal(value.strategy.selection.ranking.source.revision,exact.revision);
 }
 // Repeated selection retains one complete exact capture, not editing history.
 for(let i=0;i<30;i++)run('StrategyDraft.patch({role:"ranking",source,capture:detached,authored},StrategyDraft.read().revision)');
 assert.equal(run('StrategyDraft.read().detached.length'),1);
 if(wire){
  useWire=true;context.settings={mode:'january',first:2015,last:2015,strategy:wire.large};run('StrategyDraft.restore(settings)');
  const restored=await run('StrategyDraft.prepareSubmission()');assert.deepEqual(copy(restored.strategy),wire.large);assert(!('detached' in requests.at(-1)));assert('original' in requests.at(-1));
  run('StrategyDraft.patch({direction:"lowest"},StrategyDraft.read().revision)');
  const changed=await run('StrategyDraft.prepareSubmission()');assert(!('original' in requests.at(-1)));assert(!('detached' in requests.at(-1)));assert.equal(requests.at(-1).submitted.length,1);assert.equal(changed.strategy.selection.ranking.direction,'lowest');assert.deepEqual(copy(changed.strategy.variables.presentation),wire.large.variables.presentation);
  context.settings.strategy=wire.large;run('StrategyDraft.restore(settings)');context.largeSource=wire.large.selection.ranking.source;context.largeCapture=wire.large.variables;
  for(let i=0;i<30;i++)run('StrategyDraft.patch({role:"ranking",source:largeSource,capture:largeCapture},StrategyDraft.read().revision)');
  assert.equal(run('StrategyDraft.read().detached.length'),1);assert.deepEqual(copy((await run('StrategyDraft.prepareSubmission()')).strategy),wire.large);
  // Two selected revisions survive compaction; labels remain those selected.
  context.settings.strategy=wire.two;run('StrategyDraft.restore(settings)');context.source2=wire.small.selection.ranking.source;context.capture2=wire.small.variables;
  for(let i=0;i<30;i++)run('StrategyDraft.patch({role:"ranking",source:source2,capture:capture2},StrategyDraft.read().revision)');
  const two=await run('StrategyDraft.prepareSubmission()');assert.equal(two.strategy.variables.program.bundle.definitions.length,2);assert.equal(two.strategy.variables.presentation.length,2);assert.equal(two.strategy.selection.conditions[0].source.revision,wire.two.selection.conditions[0].source.revision);
  // Transition reads percentage-point spelling from the authoritative catalog.
  run('StrategyDraft.patch({legacy:true},StrategyDraft.read().revision);filterConditions=[{field:"operating_yield_spread_3y",op:"gt",value:8}];StrategyDraft.patch({role:"ranking",source:source2,capture:capture2},StrategyDraft.read().revision)');
  const spread=await run('StrategyDraft.prepareSubmission()');const condition=spread.strategy.selection.conditions[0];assert.equal(condition.submitted_threshold.unit,'percentage_points');assert.equal(condition.threshold.value,'0.08');assert.equal(condition.comparison_value,.08);assert.equal(condition.storage_comparison_value,8);
  // Distinct roots share a large dependency. Owner-produced raw projections
  // travel once per exact identity, even though the local captures overlap.
  run('StrategyDraft.patch({legacy:true},StrategyDraft.read().revision);filterConditions=[]');
  for(let i=0;i<wire.shared.references.length;i++){
   context.choice=wire.shared.references[i];context.role=i?'condition':'ranking';
   run('StrategyDraft.patch({role,source:choice.source,capture:choice.capture,authored:choice.authored},StrategyDraft.read().revision)');
  }
  const shared=await run('StrategyDraft.prepareSubmission()');assert.deepEqual(copy(shared.strategy),wire.shared.strategy);
  assert.equal(requests.at(-1).submitted.length,9);assert.equal(requests.at(-1).labels.length,9);assert(!('detached' in requests.at(-1)));assert(!('original' in requests.at(-1)));
 }
 console.log('Passed: actual StrategyDraft transition, inclusive legacy refusal, strict filters, stale Apply, snapshot-before-await, capture-before-ID, payload copy, held protection, detached null floors and all four modes.');
})().catch(error=>{console.error(error);process.exitCode=1;});
