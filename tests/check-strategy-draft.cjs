'use strict';
// Execute the current form/draft owner before its page bootstrap. UI and async
// transport are controlled; the draft implementation is loaded from source.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const nodes=new Map(),requests=[],ids=[],posted=[],storage=new Map();
const node=id=>{if(!nodes.has(id))nodes.set(id,{id,value:'',checked:false,tagName:'INPUT',options:[],textContent:'',innerHTML:'',disabled:false,hidden:false,add(){},setAttribute(){},querySelectorAll:()=>[]});return nodes.get(id);};
node('screening-data').textContent=JSON.stringify({metrics:{ev_ebitda:{label:'EV/EBITDA'}},filter_catalog:{pe:{label:'P/E'}},companies:{},choices:{sector:[],exchange:[]},bounds:{first:'1996-01-01',last:'2015-01-05'},latest:{metadata:{asof:'2015-01-05'}}});
const prepared=JSON.parse(node('screening-data').textContent);prepared.markets={hk:{...prepared,market:'hk',choices:{sector:['Finance'],exchange:['HKSE']},bounds:{first:'2002-01-02',last:'2015-01-05'}},jp:{...prepared,market:'jp',choices:{sector:['Industry'],exchange:['JPX']},bounds:{first:'2005-01-04',last:'2015-01-05'}}};node('screening-data').textContent=JSON.stringify(prepared);
const defaults={selection_order:'filter_first',metric:'ev_ebitda',pool:'legacy',min_cap:100e6,max_cap:null,min_ev:50e6,min_yield:0,max_multiple:null,sector:null,exchange:null};
let release=null,pause=false,useWire=false;
const wireOrigin=process.argv[2]==='--wire'?process.argv[3]:null;
const wire=wireOrigin?JSON.parse(fs.readFileSync(0,'utf8')):null;
const builtins={pe:{display:'multiple'},operating_yield_spread_3y:{display:'percentage_points'}};
const workspaceModule={exports:{}};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../website/browser/variable-workspace.js'),'utf8'),{module:workspaceModule});
const catalogBuiltins=[{id:'metric:ev_ebitda:yield',label:'EV/EBITDA yield',unit:'scalar',display:'percent',storage:{kind:'metric',metric:'ev_ebitda',component:'yield',scale:0}},...Object.entries(builtins).map(([id,item])=>({id:'filter:'+id,label:id,...item}))];
const complete=input=>input.original||({format:'strategy-capture',version:1,selection:{...input.intent.selection,conditions:input.intent.selection.conditions.map(item=>({...item,submitted_threshold:item.submitted_threshold||item.threshold,storage_comparison_value:Number(item.threshold.value)}))},pool:input.intent.pool,bounds:input.intent.bounds,variables:input.submitted?.length?{program:{bundle:{definitions:input.submitted},definitions:input.submitted.map(entry=>({...entry,...entry.definition.output}))},presentation:input.labels}:null,builtins:catalogBuiltins,limits:{bytes:196608}});
const context=vm.createContext({console,data:[],document:{getElementById:node,querySelector:node,querySelectorAll:()=>[]},StockScreener:{defaults},
 CalendarSettings:{read:()=>({start:'2015-01-02',end:'2015-01-05',months:12}),restore(){},decode:v=>v},EngineControls:{fields:()=>({engine:node('backtest-engine').value||'original'}),sync(){}},
 ResultArtifacts:{forView:()=>null,matches:()=>false},ScheduleView:{isRunning:()=>false},SavedBacktests:{update(){}},BacktestQueue:{isManaging:()=>false},Workspaces:{show(){}},
 VariableWorkspace:{content:workspaceModule.exports.content,displays:unit=>({scalar:['number','multiple','percent','percentage_points']}[unit]||[]),builtin:id=>useWire?wire.builtins.find(item=>item.id===id):builtins[id.slice(7)],request:async(route,input)=>{if(route==='/catalog')return {builtins:catalogBuiltins};assert(['/capture','/detached'].includes(route));requests.push(structuredClone(input));if(pause)await new Promise(resolve=>release=resolve);if(useWire){const body=JSON.stringify(input);assert(Buffer.byteLength(body)<=256*1024);const response=await fetch(wireOrigin+'/api/variables'+route,{method:'POST',headers:{'Content-Type':'application/json'},body});const value=await response.json();assert(response.ok,JSON.stringify(value));return value;}return route==='/detached'?{authored:input.capture.program.bundle.definitions}:{strategy:complete(input)};}},
 localStorage:{get length(){return storage.size;},key:i=>[...storage.keys()][i],getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
 crypto:{getRandomValues(bytes){ids.push(1);bytes.fill(ids.length);return bytes;}},Uint8Array,Date,AbortController,setTimeout,clearTimeout,
 fetch:async(url,options)=>{posted.push(JSON.parse(options.body));return {ok:true,json:async()=>({state:'complete',evidence:{manifest:{periods:1}}})};}
});
const source=fs.readFileSync(path.join(__dirname,'../website/browser/range.js'),'utf8');
vm.runInContext(source.slice(0,source.indexOf('\ninitializeFilters();')),context);
vm.runInContext('updateResultsState=()=>{};setModeVisibility=()=>{};renderConditions=()=>{};',context);
vm.runInContext("const autoRun=document.getElementById('auto-run');",context);
context.ResultArtifacts.decode=require('../website/browser/result-artifacts.js').decode;
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/backtest-runs.js'),'utf8'),context);
const run=code=>vm.runInContext(code,context),copy=value=>JSON.parse(JSON.stringify(value)),tick=()=>new Promise(resolve=>setImmediate(resolve));
for(const [key,id] of Object.entries({selection_order:'selection-order',metric:'ranking-metric',pool:'stock-pool',min_cap:'min-cap',max_cap:'max-cap',min_ev:'min-ev',min_yield:'min-yield',max_multiple:'max-multiple',sector:'sector-filter',exchange:'exchange-filter'}))node(id).value=defaults[key]===null?'':String(key==='min_cap'||key==='min_ev'?defaults[key]/1e6:defaults[key]);
node('rank-from').value='3';node('rank-to').value='12';node('date-testing').value='single';
const exact={kind:'formula',variable_id:'variable:archived',revision:'sha256:'+'a'.repeat(64)};
const detached={presentation:[{...exact,name:'Original submitted label'}],program:{bundle:{definitions:[{...exact,definition:{expression:{op:'constant',value:'1',unit:'scalar'},output:{unit:'scalar',display:'percent'}}}]},definitions:[{...exact,unit:'scalar',display:'percent'}]}};
context.source=exact;context.detached=detached;context.authored=detached.program.bundle.definitions;
if(process.argv[2]==='--builtins-parity'){
 const table=JSON.parse(fs.readFileSync(0,'utf8'));
 context.VariableWorkspace.request=async(route,input)=>route==='/catalog'?{builtins:table.builtins}:{strategy:input.intent};
 Promise.all(table.cases.map(async options=>{
   try{return {intent:(await run('StrategyDraft.captureBuiltins')(options)).strategy};}
   catch(error){return {error:error.message};}
 })).then(rows=>process.stdout.write(JSON.stringify(rows))).catch(error=>{console.error(error);process.exitCode=1;});
}else (async()=>{
 // Inclusive legacy constraints must be resolved explicitly, without losing draft.
 node('min-yield').value='2';const before=run('StrategyDraft.read().revision');
 assert.throws(()=>run('StrategyDraft.patch({role:"ranking",source,capture:detached,authored},StrategyDraft.read().revision)'),/inclusive/);
 assert.equal(run('StrategyDraft.isScalar()'),false);assert.equal(node('min-yield').value,'2');assert.equal(run('StrategyDraft.read().revision'),before);
 node('min-yield').value='0';run('filterConditions=[{field:"pe",op:"lt",value:12}];StrategyDraft.patch({role:"ranking",source,capture:detached,authored},StrategyDraft.read().revision)');
 assert.equal(run('StrategyDraft.isScalar()'),true);assert.equal(run('StrategyDraft.read().settings.strategy.selection.conditions[0].source.id'),'filter:pe');
 assert(node('strategy-heading').textContent.startsWith('Highest Original submitted label'));assert(node('legacy-yield-control').hidden);assert(node('legacy-multiple-control').hidden);assert(!node('ranking-source').disabled);assert(node('auto-run').disabled);assert(node('auto-run-note').textContent.includes('paused'));assert(!node('min-cap').required);
 // The moved built-in filter left the offline list, so one list stays current.
 assert.equal(run('filterConditions.length'),0);assert.equal(run('StrategyDraft.filterRows()[0].label'),'P/E');assert.equal(run('StrategyDraft.filterRows()[0].units'),null);
 const token=run('StrategyDraft.read().revision');run('StrategyDraft.patch({direction:"lowest"},StrategyDraft.read().revision)');
 assert(node('strategy-heading').textContent.startsWith('Lowest Original submitted label'));assert(node('strategy-ranking-help').textContent.includes('lowest available selected value'));
 assert.throws(()=>run(`StrategyDraft.patch({role:'ranking',source,capture:detached,authored},${token})`),/draft changed/);
 // Snapshot is taken before await; later draft changes do not alter submitted intent.
 node('backtest-engine').value='experimental';pause=true;const pending=run('StrategyDraft.prepareSubmission()');await tick();assert.equal(ids.length,0);
 const submitted=copy(requests.at(-1));node('backtest-engine').value='original';node('min-cap').value='750';run('StrategyDraft.patch({direction:"highest"},StrategyDraft.read().revision)');
 release();pause=false;const prepared=await pending;
 assert.equal(prepared.engine,'experimental');assert.equal(run('StrategyDraft.read().settings.engine'),'original');
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
 context.settings.market='hk';run('StrategyDraft.restore(settings)');
 assert.equal(node('stock-market').value,'hk');assert(node('exchange-filter').innerHTML.includes('HKSE'));assert.equal(node('trade-start').min,'2002-01-02');assert.equal((await run('StrategyDraft.prepareSubmission()')).market,'hk');
 delete context.settings.market;run('StrategyDraft.restore(settings)');assert.equal(node('stock-market').value,'us');
 // Null size floors restore exactly; the normal captured path handles old/deleted sources.
 context.settings.strategy.bounds.min_cap=null;context.settings.strategy.bounds.min_ev=null;
 run('StrategyDraft.restore(settings)');assert.equal(node('min-cap').value,'');assert.equal(run('StrategyDraft.read().settings.strategy.bounds.min_cap'),null);
 for(const mode of ['latest','custom','random']){
  context.settings={...context.settings,mode,engine:'experimental',trials:1,seed:42};run('StrategyDraft.restore(settings)');
  const value=await run('StrategyDraft.prepareSubmission()');assert.equal(value.mode,mode);assert.equal(value.engine,'experimental');assert.equal(node('backtest-engine').value,'experimental');assert.equal(value.strategy.selection.ranking.source.revision,exact.revision);
 }
 // Saved January settings restore the strategy for a dated run. Their book
 // years never become a calendar, and no January submission is prepared.
 let calendarRestores=0;const restoreCalendar=context.CalendarSettings.restore;context.CalendarSettings.restore=()=>{calendarRestores++;};
 node('date-testing').value='single';context.january={...context.settings,mode:'january',first:2015,last:2015};delete context.january.trials;delete context.january.seed;
 run('StrategyDraft.restore(january)');
 const january=await run('StrategyDraft.prepareSubmission()');assert.equal(january.mode,'custom');assert.equal(calendarRestores,0);
 assert(!('first' in january)&&!('last' in january));assert.equal(january.strategy.selection.ranking.source.revision,exact.revision);
 context.CalendarSettings.restore=restoreCalendar;
 // Copying a detached scalar result keeps exact captured content editable.
 const copiedSettings={...context.settings,engine:'experimental'};
 context.savedCopy={version:4,kind:'random',settings:copiedSettings,result:{configuration:{seed:321}},catalog:{metrics:{},filters:{}},evidence:{id:'a'.repeat(32),format_version:2,trials:1,periods:1,holdings:1}};
 const copyBytes=JSON.stringify(context.savedCopy),requestsBeforeCopy=requests.length;
 node('auto-run').checked=true;run('copySavedBacktestSettings(savedCopy)');
 assert.equal(node('auto-run').checked,false);assert.equal(storage.get('backtest-auto-run'),'false');
 assert.equal(node('random-seed').value,'321');assert.equal(node('backtest-engine').value,'experimental');
 assert.equal(requests.length,requestsBeforeCopy);assert.equal(JSON.stringify(context.savedCopy),copyBytes);
 assert.deepEqual(copy((await run('StrategyDraft.prepareSubmission()')).strategy),copiedSettings.strategy);
 run('StrategyDraft.patch({direction:"lowest"},StrategyDraft.read().revision)');
 assert.equal(run('StrategyDraft.read().settings.strategy.selection.ranking.direction'),'lowest');
 assert.equal(JSON.stringify(context.savedCopy),copyBytes);
 // New and replaced filter sources start in the source's own display unit.
 run('StrategyDraft.patch({legacy:true},StrategyDraft.read().revision);filterConditions=[{field:"pe",op:"lt",value:""}]');node('min-cap').value='100';node('min-ev').value='50';
 run('StrategyDraft.patch({role:"condition",source,capture:detached,authored},StrategyDraft.read().revision)');
 const rows=()=>run('StrategyDraft.filterRows()');
 assert.equal(rows()[0].value,'');assert.equal(rows()[1].value,'');assert.equal(rows()[1].unit,'percent');assert.equal(rows()[1].formula,true);assert(rows()[1].units.includes('number'));
 await assert.rejects(run('StrategyDraft.prepareSubmission()'),/Enter a value for each added filter/);
 run('StrategyDraft.condition(1,"value","15");StrategyDraft.condition(1,"unit","number");StrategyDraft.condition(0,"value","12")');
 run('StrategyDraft.patch({role:1,source:{kind:"builtin",id:"filter:operating_yield_spread_3y"}},StrategyDraft.read().revision)');
 assert.equal(rows()[1].unit,'percentage_points');assert.equal(rows()[1].value,'15');assert.equal(rows()[1].formula,false);
 run('StrategyDraft.patch({role:1,source,capture:detached,authored},StrategyDraft.read().revision)');assert.equal(rows()[1].unit,'percentage_points','A fitting chosen unit stays');
 // Returning to built-in controls keeps built-in filters and drops variables.
 run('StrategyDraft.patch({role:"condition",source,capture:detached,authored},StrategyDraft.read().revision);StrategyDraft.patch({legacy:true},StrategyDraft.read().revision)');
 assert.equal(run('StrategyDraft.isScalar()'),false);assert.deepEqual(copy(run('filterConditions')),[{field:'pe',op:'lt',value:'12'}]);
 // Repeated selection retains one complete exact capture, not editing history.
 for(let i=0;i<30;i++)run('StrategyDraft.patch({role:"ranking",source,capture:detached,authored},StrategyDraft.read().revision)');
 assert.equal(run('StrategyDraft.read().detached.length'),1);
 // Captured built-in labels remain visible even without the current descriptor.
 const recordedBuiltin={mode:'latest',strategy:{format:'strategy-capture',version:1,selection:{ranking:{source:{kind:'builtin',id:'filter:retired'},direction:'lowest'},rank_from:1,rank_to:50,selection_order:'filter_first',conditions:[]},pool:'legacy',bounds:{min_cap:100e6,max_cap:null,min_ev:50e6,sector:null,exchange:null},variables:null,builtins:[{id:'filter:retired',label:'Recorded parameter label',storage:{kind:'filter',field:'retired'}}],limits:{bytes:196608}}};
 context.recordedBuiltin=recordedBuiltin;const previous=copy(await run('StrategyDraft.prepareSubmission()'));
 run('StrategyDraft.restore(recordedBuiltin)');
 assert(node('ranking-source').innerHTML.includes('Recorded parameter label'));assert(node('ranking-source').innerHTML.includes('disabled'));
 assert.deepEqual(copy((await run('StrategyDraft.prepareSubmission()')).strategy),recordedBuiltin.strategy);
 context.previous=previous;run('StrategyDraft.restore(previous)');
 // Generic ranking controls retain exact deleted revisions and saved labels.
 assert.equal(node('ranking-source').value,JSON.stringify(exact));
 assert(node('ranking-source').innerHTML.includes('Original submitted label'));
 assert.equal(node('legacy-pool-note').hidden,false);
 node('stock-pool').value='cached';run('StrategyDraft.render()');assert.equal(node('legacy-pool-note').hidden,true);
 node('stock-pool').value='legacy';
 // A parameter source and direction use the same patch path; no bound keys leak.
 run('StrategyDraft.patch({role:"ranking",source:{kind:"builtin",id:"filter:pe"}},StrategyDraft.read().revision)');
 assert.equal(run('StrategyDraft.read().settings.strategy.selection.ranking.source.id'),'filter:pe');
 assert.equal(node('legacy-yield-control').hidden,true);assert.equal(node('min-yield').required,false);
 assert(!('min_yield' in run('StrategyDraft.read().settings.strategy.bounds')));
 run('StrategyDraft.patch({direction:"lowest"},StrategyDraft.read().revision)');
 assert.equal(node('variable-direction').value,'lowest');assert.equal(node('legacy-pool-note').hidden,false);
 run('StrategyDraft.patch({role:"ranking",source:{kind:"builtin",id:"metric:ev_ebitda:multiple"}},StrategyDraft.read().revision)');
 assert.equal(node('legacy-pool-note').hidden,false);assert.equal(node('max-multiple').disabled,true);
 run('StrategyDraft.patch({direction:"highest"},StrategyDraft.read().revision);StrategyDraft.patch({role:"ranking",source:{kind:"builtin",id:"metric:ev_ebitda:yield"}},StrategyDraft.read().revision)');
 assert.equal(node('legacy-yield-control').hidden,false);assert.equal(node('max-multiple').disabled,false);
 assert.deepEqual(copy(run('({scalar:StrategyDraft.isScalar(),metric:readOptions().metric,filters:readOptions().filters,autoRunDisabled:document.getElementById("auto-run").disabled})')),{scalar:false,metric:'ev_ebitda',filters:[{field:'pe',op:'lt',value:12}],autoRunDisabled:false});
 node('min-yield').value='2';node('max-multiple').value='50';
 const bounded=await run('StrategyDraft.prepareSubmission()');context.bounded=bounded;
 assert.equal(bounded.strategy.bounds.min_yield,.02);assert.equal(bounded.strategy.bounds.max_multiple,50);
 const boundedBytes=JSON.stringify(bounded);run('StrategyDraft.restore(bounded)');
 assert.deepEqual(copy((await run('StrategyDraft.prepareSubmission()')).strategy),copy(bounded.strategy));
 for(const change of [{direction:'lowest'},{role:'ranking',source:{kind:'builtin',id:'filter:pe'}}]){
  context.change=change;const revision=run('StrategyDraft.read().revision');
  assert.throws(()=>run('StrategyDraft.patch(change,StrategyDraft.read().revision)'),/inclusive/);
  assert.equal(run('StrategyDraft.read().revision'),revision);assert.equal(node('min-yield').value,'2');
 }
 assert.equal(JSON.stringify(bounded),boundedBytes);
 node('min-yield').value='0';node('max-multiple').value='';
 run('StrategyDraft.patch({direction:"lowest"},StrategyDraft.read().revision)');
 assert(!('min_yield' in run('StrategyDraft.read().settings.strategy.bounds')));assert(!('max_multiple' in run('StrategyDraft.read().settings.strategy.bounds')));
 // Built-in dated forms capture without switching their controls to formula mode.
 context.builtinSettings={...defaults,mode:'custom',start:'2015-01-02',end:'2015-01-05',months:12,rank_from:3,rank_to:12,min_yield:.02,max_multiple:50,filters:[{field:'pe',op:'lt',value:12}]};
 run('StrategyDraft.restore(builtinSettings)');
 const builtinBefore=JSON.stringify(context.builtinSettings),builtinPrepared=await run('StrategyDraft.prepareSubmission()');
 assert.equal(builtinPrepared.strategy.bounds.min_yield,.02);assert.equal(builtinPrepared.strategy.bounds.max_multiple,50);
 assert.equal(builtinPrepared.strategy.selection.ranking.source.id,'metric:ev_ebitda:yield');assert.equal(builtinPrepared.strategy.selection.conditions[0].threshold.unit,'multiple');
 assert(!('filters' in builtinPrepared)&&!('metric' in builtinPrepared));assert.equal(run('StrategyDraft.isScalar()'),false);
 assert.equal(node('min-yield').disabled,false);assert.equal(node('max-multiple').disabled,false);
 assert.deepEqual(copy(run('currentSettings().strategy')),copy(builtinPrepared.strategy));
 const capturesBeforeRepeat=requests.length;assert.deepEqual(copy((await run('StrategyDraft.prepareSubmission()')).strategy),copy(builtinPrepared.strategy));assert.equal(requests.length,capturesBeforeRepeat);
 context.builtinCaptured=builtinPrepared;run('StrategyDraft.restore(builtinCaptured)');
 assert.equal(run('StrategyDraft.isScalar()'),false);assert.equal(node('min-yield').value,'2');assert.equal(node('max-multiple').value,'50');
 assert.deepEqual(copy((await run('StrategyDraft.prepareSubmission()')).strategy),copy(builtinPrepared.strategy));
 node('max-multiple').value='40';run('StrategyDraft.touch()');
 assert.equal((await run('StrategyDraft.prepareSubmission()')).strategy.bounds.max_multiple,40);
 const beforeLatest=requests.length;run("screeningMode='latest'");const latest=await run('StrategyDraft.prepareSubmission()');
 assert(!('strategy' in latest));assert.equal(latest.min_yield,.02);assert.equal(requests.length,beforeLatest);
 assert.equal(JSON.stringify(context.builtinSettings),builtinBefore);
 // Adding a formula filter keeps active bounds when the ranking still supports them.
 run('StrategyDraft.restore(builtinSettings);StrategyDraft.patch({role:"condition",source,capture:detached,authored},StrategyDraft.read().revision)');
 assert.equal(node('legacy-yield-control').hidden,false);assert.equal(node('max-multiple').value,'50');
 run('StrategyDraft.condition(1,"value","0")');
 const withFormulaFilter=await run('StrategyDraft.prepareSubmission()');
 assert.equal(withFormulaFilter.strategy.bounds.min_yield,.02);assert.equal(withFormulaFilter.strategy.bounds.max_multiple,50);
 assert.equal(withFormulaFilter.strategy.selection.conditions[1].source.revision,exact.revision);
 run('StrategyDraft.remove(1)');
 assert.deepEqual(copy(run('({scalar:StrategyDraft.isScalar(),metric:readOptions().metric,min_yield:readOptions().min_yield,max_multiple:readOptions().max_multiple,filters:readOptions().filters,autoRunDisabled:document.getElementById("auto-run").disabled})')),{scalar:false,metric:'ev_ebitda',min_yield:.02,max_multiple:50,filters:[{field:'pe',op:'lt',value:12}],autoRunDisabled:false});
 // The conversion owns its pre-await copy, including dates and engine.
 pause=true;context.convertInput={...context.builtinSettings,filters:[],engine:'experimental'};
 const converting=run('StrategyDraft.captureBuiltins(convertInput)');await tick();context.convertInput.min_yield=.9;context.convertInput.engine='original';
 release();pause=false;const converted=await converting;assert.equal(converted.strategy.bounds.min_yield,.02);assert.equal(converted.engine,'experimental');
 if(wire){
  useWire=true;run('StrategyDraft.restore(builtinSettings)');
  const wiredBuiltin=await run('StrategyDraft.prepareSubmission()');
  assert.equal(wiredBuiltin.strategy.format,'strategy-capture');assert.equal(wiredBuiltin.strategy.bounds.min_yield,.02);assert.equal(wiredBuiltin.strategy.bounds.max_multiple,50);
  assert.equal(wiredBuiltin.strategy.selection.conditions[0].storage_comparison_value,12);
  context.wiredBuiltin=wiredBuiltin;run('StrategyDraft.restore(wiredBuiltin)');assert.deepEqual(copy((await run('StrategyDraft.prepareSubmission()')).strategy),copy(wiredBuiltin.strategy));
  context.settings={mode:'latest',strategy:wire.large};run('StrategyDraft.restore(settings)');
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
  // Added filters start empty; the user enters each threshold.
  for(let i=1;i<wire.shared.references.length;i++)run('StrategyDraft.condition('+(i-1)+',"value","0")');
  const shared=await run('StrategyDraft.prepareSubmission()');assert.deepEqual(copy(shared.strategy),wire.shared.strategy);
  assert.equal(requests.at(-1).submitted.length,9);assert.equal(requests.at(-1).labels.length,9);assert(!('detached' in requests.at(-1)));assert(!('original' in requests.at(-1)));
 }
 console.log('Passed: actual StrategyDraft transition, one filter owner per mode, empty thresholds, unit resets, built-in filters kept on return, inclusive legacy refusal, strict filters, stale Apply, snapshot-before-await, capture-before-ID, payload copy, held protection, detached null floors and all four modes.');
})().catch(error=>{console.error(error);process.exitCode=1;});
