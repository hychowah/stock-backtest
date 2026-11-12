'use strict';
// Execute the actual form/draft owner before its page listeners. UI and async
// transport are controlled; the draft implementation is loaded from source.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const nodes=new Map(),requests=[],ids=[],posted=[],storage=new Map();
const document={getElementById:id=>node(id),querySelector:id=>node(id),querySelectorAll:()=>[],activeElement:null};
function node(id){if(!nodes.has(id))nodes.set(id,{id,value:'',checked:false,tagName:'INPUT',options:[],textContent:'',innerHTML:'',disabled:false,hidden:false,add(){},setAttribute(){},querySelectorAll:()=>[],focus(){document.activeElement=this;}});return nodes.get(id);}
const prepared={metrics:{ev_ebitda:{label:'EV/EBITDA'},ev_ebitda_3y:{label:'EV/3y EBITDA'}},filter_catalog:{pe:{label:'P/E',available:true}},companies:{},choices:{sector:['Energy'],exchange:['NYSE']},bounds:{first:'1996-01-01',last:'2015-01-05'},latest:{metadata:{asof:'2015-01-05'}}};
prepared.markets={hk:{...prepared,market:'hk',choices:{sector:['Finance'],exchange:['HKSE']},bounds:{first:'2002-01-02',last:'2015-01-05'}},jp:{...prepared,market:'jp',choices:{sector:['Industry'],exchange:['JPX']},bounds:{first:'2005-01-04',last:'2015-01-05'}}};
node('screening-data').textContent=JSON.stringify(prepared);
let release=null,pause=false,useWire=false;
const wireOrigin=process.argv[2]==='--wire'?process.argv[3]:null;
const wire=wireOrigin?JSON.parse(fs.readFileSync(0,'utf8')):null;
const builtins={pe:{display:'multiple'},operating_yield_spread_3y:{display:'percentage_points'}};
const workspaceModule={exports:{}};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../website/browser/variable-workspace.js'),'utf8'),{module:workspaceModule});
const catalogBuiltins=[{id:'metric:ev_ebitda:yield',label:'EV/EBITDA yield',unit:'scalar',display:'percent',storage:{kind:'metric',metric:'ev_ebitda',component:'yield',scale:0}},...Object.entries(builtins).map(([id,item])=>({id:'filter:'+id,label:id,...item}))];
// A controlled capture: filters gain derived threshold evidence, as the server's do.
const complete=input=>({format:'strategy-capture',version:2,universe:input.intent.universe,steps:input.intent.steps.map(step=>step.kind==='filter'&&typeof step.threshold!=='string'&&!step.submitted_threshold?{...step,submitted_threshold:step.threshold,threshold:{value:step.threshold.value,unit:'canonical'},comparison_value:Number(step.threshold.value),storage_comparison_value:Number(step.threshold.value)}:step),
  variables:input.submitted?.length?{program:{bundle:{definitions:input.submitted},definitions:input.submitted.map(entry=>({...entry,...entry.definition.output}))},presentation:input.labels}:null,builtins:catalogBuiltins,limits:{bytes:196608}});
const context=vm.createContext({console,document,StockScreener:require('../website/browser/screener.js'),FilterPicker:{refresh(){}},
 CalendarSettings:{read:()=>({start:'2015-01-02',end:'2015-01-05',months:12}),restore(){},decode:v=>v},EngineControls:{fields:()=>({engine:node('backtest-engine').value||'original'}),sync(){}},
 ResultArtifacts:{forView:()=>null,matches:()=>false},Workspaces:{show(){}},
 VariableWorkspace:{content:workspaceModule.exports.content,displayName:value=>value,displays:unit=>({scalar:['number','multiple','percent','percentage_points']}[unit]||[]),sources:async()=>({library:[],measures:[],parameters:[]}),
  builtin:id=>useWire?wire.builtins.find(item=>item.id===id):builtins[id.slice(7)],
  request:async(route,input)=>{if(route==='/catalog')return {builtins:useWire?wire.builtins:catalogBuiltins};assert(['/capture','/detached'].includes(route));requests.push(structuredClone(input));if(pause)await new Promise(resolve=>release=resolve);if(useWire){const body=JSON.stringify(input);assert(Buffer.byteLength(body)<=256*1024);const response=await fetch(wireOrigin+'/api/variables'+route,{method:'POST',headers:{'Content-Type':'application/json'},body});const value=await response.json();assert(response.ok,JSON.stringify(value));return value;}return route==='/detached'?{authored:input.capture.program.bundle.definitions}:{strategy:complete(input)};}},
 localStorage:{get length(){return storage.size;},key:i=>[...storage.keys()][i],getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
 crypto:{getRandomValues(bytes){ids.push(1);bytes.fill(ids.length);return bytes;}},Uint8Array,Date,AbortController,setTimeout,clearTimeout,
 fetch:async(url,options)=>{posted.push(JSON.parse(options.body));return {ok:true,json:async()=>({state:'complete',evidence:{manifest:{periods:1}}})};}
});
const source=fs.readFileSync(path.join(__dirname,'../website/browser/range.js'),'utf8');
vm.runInContext(source.slice(0,source.indexOf('\ninitializeFilters();')),context);
vm.runInContext('initializeFilters();',context);
context.ResultArtifacts.decode=require('../website/browser/result-artifacts.js').decode;
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/backtest-runs.js'),'utf8'),context);
const run=code=>vm.runInContext(code,context),copy=value=>JSON.parse(JSON.stringify(value)),tick=()=>new Promise(resolve=>setImmediate(resolve));
const view=()=>copy(run('StrategyDraft.view()')),revision=()=>run('StrategyDraft.read().revision');
const patch=(role,value,extra='')=>{context.patchSource=value;return run(`StrategyDraft.patch({role:${JSON.stringify(role)},source:patchSource${extra}},StrategyDraft.read().revision)`);};
const edit=(id,key,value)=>run(`StrategyDraft.edit(${JSON.stringify(id)},${JSON.stringify(key)},${JSON.stringify(value)})`);
const submit=async(held=false)=>copy(await run(`StrategyDraft.prepareSubmission({held:${held}})`));
const restore=settings=>{context.restoring=settings;run('StrategyDraft.restore(restoring)');};
const shape=()=>view().map(row=>[row.kind,row.label,row.kind==='rank'?row.direction:row.op,row.kind==='rank'?row.rank_from:row.value,row.kind==='rank'?row.rank_to:row.unit]);
const builtin=id=>({kind:'builtin',id}),field=name=>({kind:'field',field:name});
const exact={kind:'formula',variable_id:'variable:archived',revision:'sha256:'+'a'.repeat(64)};
const detached={presentation:[{...exact,name:'Original submitted label'}],program:{bundle:{definitions:[{...exact,definition:{expression:{op:'constant',value:'1',unit:'scalar'},output:{unit:'scalar',display:'percent'}}}]},definitions:[{...exact,unit:'scalar',display:'percent'}]}};
context.detached=detached;context.authored=detached.program.bundle.definitions;
const formulaExtra=',capture:detached,authored';
const flatDefaults={rank_from:1,rank_to:50,selection_order:'filter_first',metric:'ev_ebitda',pool:'cached',min_cap:100e6,max_cap:null,min_ev:50e6,min_yield:0,max_multiple:null,sector:null,exchange:null,filters:[]};
if(process.argv[2]==='--builtins-parity'){
 const table=JSON.parse(fs.readFileSync(0,'utf8'));
 // The path of a copied flat test: its settings go into the builder, and the submission captures one chain.
 context.VariableWorkspace.request=async(route,input)=>route==='/catalog'?{builtins:table.builtins}:{strategy:input.intent};
 (async()=>{
   const rows=[];
   for(const options of table.cases){
     try{restore({mode:'custom',...options});rows.push({intent:(await submit()).strategy});}
     catch(error){rows.push({error:error.message});}
   }
   process.stdout.write(JSON.stringify(rows));
 })().catch(error=>{console.error(error);process.exitCode=1;});
}else (async()=>{
 // A new strategy: size floors, then EV/EBITDA yield highest, ranks 1–50. It
 // is the familiar offline shape, so latest picks and auto-run stay available.
 assert.deepEqual(shape(),[['filter','Market cap','ge','100','usd_million'],['filter','Enterprise value','ge','50','usd_million'],['rank','EV/EBITDA yield','highest',1,50]]);
 assert.deepEqual(copy(run('StrategyDraft.flat()')),flatDefaults);
 assert.deepEqual(copy(run('StockScreener.latestScreen')({...prepared,latest:{...prepared.latest,legacy:[],cached:[]},metric_values:{cached:{}}},run('StrategyDraft.flat()')).options),{...run('StockScreener.defaults'),...flatDefaults});
 assert.equal(node('strategy-heading').textContent,'Highest EV/EBITDA yield');assert.equal(node('auto-run').disabled,false);
 // The Auto-run note is a status line: empty while auto-run can work. Random-date
 // and custom-interval inputs show only while their choice is on. A new draft tests random dates.
 assert.equal(node('auto-run-note').textContent,'');
 const shownInputs=()=>[node('random-controls').hidden,node('calendar-interval').hidden,!!node('rebalance-months').disabled];
 assert.deepEqual(shownInputs(),[false,true,false]);
 node('date-testing').value='random';node('calendar-custom').checked=true;run('StrategyDraft.render()');assert.deepEqual(shownInputs(),[false,false,true]);
 node('date-testing').value='single';node('calendar-custom').checked=false;run('StrategyDraft.render()');assert.deepEqual(shownInputs(),[true,true,false]);
 run("screeningMode='backtest'");
 // The form stays valid after an out-of-range value is hidden: a hidden number
 // input is disabled, and native validation skips a disabled input.
 const ranges={'random-trials':[1,100],'random-seed':[0,4294967295],'calendar-count':[1,24]};
 const blocking=()=>Object.entries(ranges).filter(([id,[low,high]])=>!node(id).disabled&&!(+node(id).value>=low&&+node(id).value<=high)).map(([id])=>id);
 const choose=(testing,custom)=>{node('date-testing').value=testing;node('calendar-custom').checked=custom;run('StrategyDraft.render()');};
 // Path A: 52 weeks, then months (at most 24), then the custom interval off.
 node('calendar-count').value='52';choose('single',true);assert.deepEqual(blocking(),['calendar-count'],'A visible wrong value still asks for a correction');
 choose('single',false);assert.deepEqual(blocking(),[]);
 // Path B: 500 trials and a wrong repeated date set, then one fixed schedule.
 node('random-trials').value='500';node('repeat-random').checked=true;node('random-seed').value='-1';choose('random',false);assert.deepEqual(blocking(),['random-trials','random-seed']);
 choose('single',false);assert.deepEqual(blocking(),[]);assert(!('trials' in run('currentSettings()')));
 node('calendar-count').value='12';node('random-trials').value='24';node('random-seed').value='42';node('repeat-random').checked=false;choose('single',false);
 const first=await submit();
 assert.deepEqual(requests.at(-1),{intent:{format:'strategy-intent',version:2,universe:{pool:'cached'},steps:[{kind:'filter',source:field('market_cap'),op:'ge',threshold:{value:'100',unit:'usd_million'}},{kind:'filter',source:field('enterprise_value'),op:'ge',threshold:{value:'50',unit:'usd_million'}},{kind:'rank',source:builtin('metric:ev_ebitda:yield'),direction:'highest',rank_from:1,rank_to:50}]},market:'us'});
 assert.equal(first.mode,'custom');assert.equal(first.strategy.version,2);
 // The capture stays current until the draft changes; no second request.
 const before=requests.length;assert.deepEqual(copy(await submit()).strategy,copy(first.strategy));assert.equal(requests.length,before);
 assert.deepEqual(copy(run('currentSettings().strategy')),copy(first.strategy));

 // Example chain: Rank A → Filter B → Rank C → Filter D.
 let [cap,ev,rankA]=view().map(row=>row.id);
 run(`StrategyDraft.remove('${cap}');StrategyDraft.remove('${ev}')`);
 const rankC=patch('rank',builtin('metric:ev_ebitda_3y:multiple'));
 const filterB=patch('filter',builtin('filter:pe'));
 const filterD=patch('filter',exact,formulaExtra);
 assert.deepEqual(view().map(row=>row.id),[rankA,filterB,filterD,rankC],'A new filter goes before the last Rank');
 // The moved step becomes last, so its rendered Down is disabled and focus goes to Up.
 node('step-down-'+filterD).disabled=true;run(`StrategyDraft.move('${filterD}',1)`);assert.equal(document.activeElement.id,'step-up-'+filterD,'A move keeps focus on its step');node('step-down-'+filterD).disabled=false;
 edit(rankA,'rank_from','20');edit(rankA,'rank_to','40');edit(rankC,'direction','lowest');edit(filterB,'op','lt');edit(filterB,'value','12');edit(filterD,'op','ge');edit(filterD,'value','5');run('StrategyDraft.render()');
 assert.deepEqual(shape(),[['rank','EV/EBITDA yield','highest',20,40],['filter','P/E','lt','12','multiple'],['rank','EV/3y EBITDA multiple','lowest',1,50],['filter','Original submitted label','ge','5','percent']]);
 assert.equal(view()[3].title,exact.variable_id+' @ '+exact.revision);assert(view()[3].units.includes('number'));
 assert.equal(run('StrategyDraft.flat()'),null);assert.equal(node('auto-run').disabled,true);assert(node('auto-run-note').textContent.includes('paused'));
 assert.equal(node('strategy-heading').textContent,'Lowest EV/3y EBITDA multiple');
 // Latest picks for a chain outside the offline shape run on the service
 // with the captured chain; a finished result then matches the draft.
 let latestRun=null;context.ScheduleView={runPrepared:settings=>{latestRun=copy(settings);}};
 run("screeningMode='latest';StrategyDraft.render()");assert.equal(node('run-screen').disabled,false);
 run('applyRange()');await tick();
 assert.equal(latestRun.mode,'latest');assert.equal(latestRun.strategy.version,2);assert.equal(latestRun.strategy.steps.length,4);assert(!('start' in latestRun));
 assert.deepEqual(copy(run('currentSettings().strategy')),latestRun.strategy);
 run("screeningMode='backtest';StrategyDraft.render()");
 const chainA=await submit();
 assert.deepEqual(requests.at(-1).intent.steps,[{kind:'rank',source:builtin('metric:ev_ebitda:yield'),direction:'highest',rank_from:20,rank_to:40},{kind:'filter',source:builtin('filter:pe'),op:'lt',threshold:{value:'12',unit:'multiple'}},
  {kind:'rank',source:builtin('metric:ev_ebitda_3y:multiple'),direction:'lowest',rank_from:1,rank_to:50},{kind:'filter',source:exact,op:'ge',threshold:{value:'5',unit:'percent'}}]);
 assert.equal(requests.at(-1).submitted.length,1);assert.equal(requests.at(-1).labels[0].name,'Original submitted label');assert(!('detached' in requests.at(-1)));
 assert.equal(chainA.strategy.steps.length,4);

 // Stale replies: a move, removal or added step invalidates pending choices.
 let token=revision();run(`StrategyDraft.move('${rankC}',-1)`);
 assert.throws(()=>run(`StrategyDraft.patch({role:'${rankA}',source:{kind:'builtin',id:'filter:pe'}},${token})`),/draft changed/);
 token=revision();run(`StrategyDraft.remove('${rankC}')`);
 assert.throws(()=>run(`StrategyDraft.patch({role:'${rankC}',source:{kind:'builtin',id:'filter:pe'}},StrategyDraft.read().revision)`),/draft changed/,'A removed step cannot receive a late choice');
 assert.throws(()=>run(`StrategyDraft.patch({role:'filter',source:{kind:'builtin',id:'filter:pe'}},${token})`),/draft changed/);

 // Example chain: Filter, Filter, Rank, Rank, with a repeated source.
 run('StrategyDraft.reset()');
 const [,,rank1]=view().map(row=>row.id),rank2=patch('rank',builtin('metric:ev_ebitda:yield'));
 edit(rank2,'rank_to','10');
 assert.deepEqual(shape(),[['filter','Market cap','ge','100','usd_million'],['filter','Enterprise value','ge','50','usd_million'],['rank','EV/EBITDA yield','highest',1,50],['rank','EV/EBITDA yield','highest',1,10]]);
 assert.equal(run('StrategyDraft.flat()'),null,'Two Ranks are not the offline shape');
 // Moving the repeated Rank keeps focus. At the top, Up is disabled, so focus
 // moves to Down on the same step.
 run(`StrategyDraft.move('${rank2}',-1)`);assert.deepEqual(view().map(row=>row.kind),['filter','filter','rank','rank']);assert.equal(view()[2].id,rank2);assert.equal(document.activeElement.id,'step-up-'+rank2);
 run(`StrategyDraft.move('${rank2}',-1);StrategyDraft.move('${rank2}',-1)`);node('step-up-'+rank2).disabled=true;
 assert.equal(view()[0].id,rank2);run(`StrategyDraft.move('${rank2}',-1)`);assert.equal(view()[0].id,rank2,'The first step cannot move further up');
 run(`renderSteps()`);assert.match(node('strategy-steps').innerHTML,new RegExp('id="step-up-'+rank2+'"[^>]*disabled'));
 node('step-up-'+rank2).disabled=true;run(`StrategyDraft.move('${rank2}',1);StrategyDraft.move('${rank2}',-1)`);assert.equal(document.activeElement.id,'step-down-'+rank2);
 const chainB=await submit();
 assert.deepEqual(chainB.strategy.steps.map(step=>[step.kind,step.rank_to??step.op]),[['rank',10],['filter','ge'],['filter','ge'],['rank',50]]);
 run(`StrategyDraft.remove('${rank1}');StrategyDraft.remove('${rank2}')`);
 await assert.rejects(submit(),/Add a Rank step/);

 // Field and sector sources: units, equality and switching sources.
 run('StrategyDraft.reset()');[cap]=view().map(row=>row.id);
 const sector=patch('filter',field('sector'));
 let row=view().find(item=>item.id===sector);assert.equal(row.text,true);assert.deepEqual(row.choices,['Energy']);assert.equal(row.value,'');
 assert.deepEqual(view().find(item=>item.id===cap).units,['usd_million','usd']);
 await assert.rejects(submit(),/Enter a value for each filter/);
 edit(sector,'value','Energy');assert.equal(run('StrategyDraft.flat()').sector,'Energy');
 edit(cap,'unit','usd');edit(cap,'value','250000000');assert.equal(run('StrategyDraft.flat()').min_cap,250e6);
 patch(cap,field('enterprise_value'));assert.deepEqual(shape()[0],['filter','Enterprise value','ge','250000000','usd'],'A fitting unit and the typed value stay');
 patch(cap,builtin('filter:pe'));assert.deepEqual(shape()[0],['filter','P/E','ge','250000000','multiple'],'A built-in unit is fixed; the comparison stays');
 patch(sector,builtin('metric:ev_ebitda:yield'));assert.deepEqual(shape()[2],['filter','EV/EBITDA yield','gt','','percent'],'Equality becomes a numeric comparison');
 // A variable keeps a chosen unit only when it fits its output.
 patch(cap,exact,formulaExtra);assert.equal(shape()[0][4],'multiple');edit(cap,'unit','number');patch(cap,exact,formulaExtra);assert.equal(shape()[0][4],'number');
 patch(cap,field('market_cap'));assert.equal(shape()[0][4],'usd_million');patch(cap,exact,formulaExtra);assert.deepEqual(shape()[0].slice(3),['250000000','percent']);
 for(let i=0;i<30;i++)patch(cap,exact,formulaExtra);
 assert.equal(run('StrategyDraft.read().detached.length'),1,'Repeated choices keep one complete exact capture');

 // Every restore format becomes one chain. Flat filter-first, with ranks
 // 20–40, all bounds and a built-in filter; spellings convert back exactly.
 const noisyYield=.1+.2;
 const flat={mode:'custom',start:'2015-01-02',end:'2015-01-05',months:12,rank_from:20,rank_to:40,pool:'legacy',metric:'ev_ebitda_3y',selection_order:'filter_first',
  min_cap:123.4e6,max_cap:5e9,min_ev:0,min_yield:.07,max_multiple:15,sector:'Energy',exchange:'NYSE',filters:[{field:'pe',op:'lt',value:12}]};
 restore(flat);
 assert.deepEqual(shape(),[['filter','Market cap','ge','123.4','usd_million'],['filter','Market cap','le','5000','usd_million'],['filter','Sector','eq','Energy',undefined],['filter','Exchange','eq','NYSE',undefined],
  ['filter','EV/3y EBITDA yield','ge','7','percent'],['filter','EV/3y EBITDA multiple','le','15','multiple'],['filter','P/E','lt','12',undefined],['rank','EV/3y EBITDA yield','highest',20,40]]);
 const {mode:_mode,start:_start,end:_end,months:_months,...flatSelection}=flat;
 assert.deepEqual(copy(run('StrategyDraft.flat()')),flatSelection,'The offline shape converts back to the same flat settings');
 assert.deepEqual(copy(run('StrategyDraft.selection()')),flatSelection,'An unchanged copy shows its recorded settings');
 restore({...flat,filters:[{field:'pe',op:'gt',value:-20}]});assert.equal(run('StrategyDraft.flat()').filters[0].value,-20,'A negative threshold flattens');
 restore(flat);
 restore({...flat,min_yield:noisyYield,selection_order:'rank_first',min_cap:null});
 assert.equal(view()[0].kind,'rank');assert.deepEqual(shape()[1],['filter','Market cap','ge','','usd_million'],'An empty flat minimum asks for a value');
 assert.deepEqual(shape()[5].slice(3),[String(noisyYield),'number']);
 await assert.rejects(submit(),/Enter a value for each filter/);
 edit(view()[1].id,'value','1');assert.equal(run('StrategyDraft.flat()').min_yield,noisyYield);assert.equal(run('StrategyDraft.flat()').selection_order,'rank_first');
 const flatSubmission=await submit();
 // A built-in filter restored from flat settings takes its unit from the catalog.
 assert.deepEqual(requests.at(-1).intent.steps.at(-1),{kind:'filter',source:builtin('filter:pe'),op:'lt',threshold:{value:'12',unit:'multiple'}});
 assert(!('filters' in flatSubmission)&&!('metric' in flatSubmission)&&!('rank_to' in flatSubmission));
 // Capture/1 rank-first with a formula ranking, ranks 20–40 and detached labels.
 const v1={format:'strategy-capture',version:1,pool:'cached',bounds:{min_cap:100e6,max_cap:null,min_ev:50e6,sector:null,exchange:'NYSE'},
  selection:{ranking:{source:exact,direction:'lowest'},rank_from:20,rank_to:40,selection_order:'rank_first',conditions:[{source:builtin('filter:pe'),op:'lt',threshold:{value:'12',unit:'scalar'},submitted_threshold:{value:'12',unit:'multiple'},comparison_value:12,storage_comparison_value:12}]},
  variables:detached,builtins:[{id:'filter:pe',label:'Recorded P/E',unit:'scalar',display:'multiple',storage:{kind:'filter',field:'pe',scale:0}}],limits:{bytes:196608}};
 const v1Settings={mode:'random',start:'2015-01-02',end:'2015-01-05',months:12,trials:3,seed:7,engine:'experimental',market:'hk',strategy:v1};
 restore(v1Settings);
 assert.deepEqual(copy(run('StrategyDraft.selection()')),{strategy:v1},'An unchanged capture/1 copy shows its recorded settings');
 assert.deepEqual(shape(),[['rank','Original submitted label','lowest',20,40],['filter','Market cap','ge','100','usd_million'],['filter','Enterprise value','ge','50','usd_million'],['filter','Exchange','eq','NYSE',undefined],['filter','Recorded P/E','lt','12','multiple']]);
 assert.equal(node('stock-market').value,'hk');assert.equal(node('trade-start').min,'2002-01-02');assert.equal(node('random-seed').value,'7');assert.equal(node('backtest-engine').value,'experimental');
 const v1Submission=await submit();
 assert.equal(v1Submission.mode,'random');assert.equal(v1Submission.market,'hk');assert.equal(v1Submission.engine,'experimental');assert.equal(v1Submission.strategy.version,2,'A copied capture/1 runs as a chain');
 assert.deepEqual(requests.at(-1).intent.steps[0],{kind:'rank',source:exact,direction:'lowest',rank_from:20,rank_to:40});
 assert.deepEqual(requests.at(-1).intent.steps[4],{kind:'filter',...v1.selection.conditions[0]},'Recorded threshold evidence survives');
 // Capture/1 filter-first from the built-in form: pair bounds become filters.
 const pair=structuredClone(v1);pair.selection={ranking:{source:builtin('metric:ev_ebitda:yield'),direction:'highest'},rank_from:1,rank_to:50,selection_order:'filter_first',conditions:[]};
 pair.bounds={...pair.bounds,exchange:null,min_yield:.02,max_multiple:50};pair.variables=null;
 restore({mode:'custom',strategy:pair});
 assert.deepEqual(shape().map(item=>item.slice(1,4)),[['Market cap','ge','100'],['Enterprise value','ge','50'],['EV/EBITDA yield','ge','2'],['EV/EBITDA multiple','le','50'],['EV/EBITDA yield','highest',1]]);
 // Capture/2 restores directly; an unchanged copy resubmits it without a request.
 restore({mode:'custom',strategy:chainA.strategy,market:'jp'});
 assert.deepEqual(view().map(item=>item.kind),['rank','filter','rank','filter']);assert.equal(node('stock-market').value,'jp');
 let count=requests.length;assert.deepEqual(copy((await submit()).strategy),copy(chainA.strategy));assert.equal(requests.length,count);
 edit(view()[0].id,'rank_to','39');assert.equal((await submit()).strategy.steps[0].rank_to,39);
 assert.deepEqual(requests.slice(count).map(item=>Object.keys(item).sort().join()),['capture,root','intent,labels,market,submitted'],'A changed restored formula projects its exact content, then captures');
 edit(view()[0].id,'rank_to','40');count=requests.length;assert.deepEqual(copy((await submit()).strategy),copy(chainA.strategy),'Returning to the recorded settings reuses the record');assert.equal(requests.length,count);
 // Another market captures again, so Hong Kong gets the market-aware form; the recorded market reuses the record.
 node('stock-market').value='hk';await submit();assert.equal(requests.at(-1).market,'hk');
 node('stock-market').value='jp';count=requests.length;assert.deepEqual(copy((await submit()).strategy),copy(chainA.strategy));assert.equal(requests.length,count);
 // More than 50 steps refuses the copy and keeps the draft.
 const kept=JSON.stringify(view());
 assert.throws(()=>restore({...flat,filters:Array.from({length:44},()=>({field:'pe',op:'gt',value:1}))}),/more than 50 steps/);
 assert.equal(JSON.stringify(view()),kept);

 // Held queue edits: an unchanged save keeps the original payload, even after
 // an immediate run. A changed edit captures a chain. Cancel ends ownership.
 for(const original of [flat,v1Settings]){
  context.record=original;run("var held=StrategyDraft.beginQueuedEdit('queued');held.restore(record)");
  assert.throws(()=>restore(original),/Save or cancel/);
  count=requests.length;
  const saved=await submit(true),{mode,start,end,months,trials,seed,engine,market,...selection}=copy(saved);
  assert.equal(requests.length,count);
  if(original.strategy)assert.deepEqual(selection.strategy,original.strategy);else assert.deepEqual(selection,{...flatSelection,min_cap:123.4e6});
  const immediate=await submit();assert.equal(immediate.strategy.version,2,'An immediate run captures a chain');
  const savedAfterRun=await submit(true);assert.deepEqual(copy(savedAfterRun),copy(saved));
  const rank=view().find(item=>item.kind==='rank').id;edit(rank,'rank_to','30');
  const changed=await submit(true);assert.equal(changed.strategy.version,2);assert.equal(changed.strategy.steps.find(step=>step.kind==='rank').rank_to,30);
  token=revision();run('held.end()');
  assert.throws(()=>run(`StrategyDraft.patch({role:'filter',source:{kind:'builtin',id:'filter:pe'}},${token})`),/draft changed/);
  assert.throws(()=>run('held.restore(record)'),/no longer active/);
 }
 // A held edit loads every step; only a copy refuses more than 50.
 context.record={...flat,filters:Array.from({length:44},()=>({field:'pe',op:'gt',value:1}))};
 run("var big=StrategyDraft.beginQueuedEdit('big');big.restore(record)");assert.equal(view().length,51);
 assert.equal((await submit(true)).filters.length,44);run('big.end()');
 restore(flat);

 // Snapshot is taken before await; later draft changes never alter the submission.
 node('backtest-engine').value='experimental';pause=true;const pending=submit();await tick();assert.equal(ids.length,0);
 const submitted=copy(requests.at(-1));node('backtest-engine').value='original';
 edit(view().find(item=>item.kind==='rank').id,'rank_to','5');patch(view()[0].id,field('enterprise_value'));
 release();pause=false;const snapshot=await pending;
 assert.equal(snapshot.engine,'experimental');assert.deepEqual(snapshot.strategy.steps.map(step=>step.rank_to??step.source.field??step.source.id),complete(submitted).steps.map(step=>step.rank_to??step.source.field??step.source.id));
 assert.equal(snapshot.strategy.steps.at(-1).rank_to,40);
 // Capture completes before retry ID allocation; uncertain start uses exact content.
 const fresh=await submit();context.prepared=fresh;
 assert.equal(ids.length,0);const actual=run('{const {mode,...options}=prepared;BacktestRuns.create(options)}');assert.equal(ids.length,1);
 fresh.strategy.steps.at(-1).rank_to=1;assert.equal(actual.options.strategy.steps.at(-1).rank_to,5);
 context.job=actual;await run('BacktestRuns.follow(job,()=>{})');assert.equal(posted[0].options.strategy.steps.at(-1).rank_to,5);

 // Copying a saved result restores its settings without a calculation;
 // opening a result is a separate path that leaves the draft alone.
 const savedCopy={version:4,kind:'random',settings:{mode:'random',start:'2015-01-02',end:'2015-01-05',months:12,trials:1,engine:'experimental',strategy:chainA.strategy},result:{configuration:{seed:321}},catalog:{metrics:{},filters:{}},evidence:{id:'a'.repeat(32),format_version:2,trials:1,periods:1,holdings:1}};
 context.savedCopy=savedCopy;const copyBytes=JSON.stringify(savedCopy),requestsBeforeCopy=requests.length;
 // Auto-run belongs to Latest stock picks: a copy into the builder leaves it as the user set it.
 node('auto-run').checked=true;run('copySavedBacktestSettings(savedCopy)');
 assert.equal(node('auto-run').checked,true);assert.equal(storage.has('backtest-auto-run'),false);
 assert.equal(node('random-seed').value,'321');assert.equal(node('backtest-engine').value,'experimental');
 assert.equal(requests.length,requestsBeforeCopy);assert.equal(JSON.stringify(savedCopy),copyBytes);
 assert.deepEqual(copy((await submit()).strategy),chainA.strategy);
 // Saved January settings restore the strategy for a dated run. Their book
 // years never become a calendar, and no January submission is prepared.
 let calendarRestores=0;const restoreCalendar=context.CalendarSettings.restore;context.CalendarSettings.restore=()=>{calendarRestores++;};
 node('date-testing').value='single';restore({mode:'january',first:2015,last:2015,strategy:chainA.strategy});
 const january=await submit();assert.equal(january.mode,'custom');assert.equal(calendarRestores,0);assert(!('first' in january)&&!('last' in january));
 context.CalendarSettings.restore=restoreCalendar;

 if(wire){
  useWire=true;
  // Flat settings capture through the actual server as one chain.
  restore({...flat,min_yield:.02,max_multiple:50});
  const wiredFlat=await submit();
  assert.equal(wiredFlat.strategy.format,'strategy-capture');assert.equal(wiredFlat.strategy.version,2);
  const yieldStep=wiredFlat.strategy.steps.find(step=>step.op==='ge'&&step.source.id==='metric:ev_ebitda_3y:yield');
  assert.equal(yieldStep.storage_comparison_value,.02);assert.equal(yieldStep.submitted_threshold.unit,'percent');
  assert.equal(wiredFlat.strategy.steps.find(step=>step.source.id==='filter:pe').storage_comparison_value,12);
  assert.equal(wiredFlat.strategy.steps.find(step=>step.source.field==='market_cap'&&step.op==='ge').storage_comparison_value,123.4e6);
  restore({mode:'custom',strategy:wiredFlat.strategy});count=requests.length;assert.deepEqual(copy((await submit()).strategy),copy(wiredFlat.strategy));assert.equal(requests.length,count);
  // A large capture/1 is copied as a chain: exact authored content travels once.
  restore({mode:'custom',strategy:wire.large});
  const large=await submit();
  assert(!('detached' in requests.at(-1)));assert.equal(requests.at(-1).submitted.length,1);
  assert.equal(large.strategy.version,2);assert.deepEqual(large.strategy.steps.at(-1).source,wire.large.selection.ranking.source);assert.deepEqual(copy(large.strategy.variables.presentation),wire.large.variables.presentation);
  // The held original is kept unchanged without a request.
  run("var wired=StrategyDraft.beginQueuedEdit('wired')");context.record={mode:'custom',strategy:wire.large};run('wired.restore(record)');
  count=requests.length;assert.deepEqual(copy((await submit(true)).strategy),wire.large);assert.equal(requests.length,count);run('wired.end()');
  context.largeSource=wire.large.selection.ranking.source;context.largeCapture=wire.large.variables;
  const largeRank=view().at(-1).id;
  for(let i=0;i<30;i++)run(`StrategyDraft.patch({role:'${largeRank}',source:largeSource,capture:largeCapture},StrategyDraft.read().revision)`);
  assert.equal(run('StrategyDraft.read().detached.length'),1);assert.deepEqual(copy((await submit()).strategy),copy(large.strategy));
  // Two selected revisions survive compaction; labels remain those selected.
  restore({mode:'custom',strategy:wire.two});context.source2=wire.small.selection.ranking.source;context.capture2=wire.small.variables;
  const twoRank=view().at(-1).id;
  for(let i=0;i<30;i++)run(`StrategyDraft.patch({role:'${twoRank}',source:source2,capture:capture2},StrategyDraft.read().revision)`);
  const two=await submit();assert.equal(two.strategy.variables.program.bundle.definitions.length,2);assert.equal(two.strategy.variables.presentation.length,2);
  assert.equal(two.strategy.steps.find(step=>step.kind==='filter'&&step.source.kind==='formula').source.revision,wire.two.selection.conditions[0].source.revision);
  // Built-in filter units come from the authoritative catalog.
  restore({...flat,min_yield:0,max_multiple:null,filters:[{field:'operating_yield_spread_3y',op:'gt',value:8}]});
  const spread=(await submit()).strategy.steps.find(step=>step.source.id==='filter:operating_yield_spread_3y');
  assert.equal(spread.submitted_threshold.unit,'percentage_points');assert.equal(spread.threshold.value,'0.08');assert.equal(spread.comparison_value,.08);assert.equal(spread.storage_comparison_value,8);
  // Distinct roots share a large dependency. Owner-produced raw projections
  // travel once per exact identity, even though the local captures overlap.
  run('StrategyDraft.reset()');[cap,ev,rankA]=view().map(item=>item.id);run(`StrategyDraft.remove('${cap}');StrategyDraft.remove('${ev}')`);
  for(let i=0;i<wire.shared.references.length;i++){
   context.choice=wire.shared.references[i];
   const id=run(`StrategyDraft.patch({role:${JSON.stringify(i?'filter':rankA)},source:choice.source,capture:choice.capture,authored:choice.authored},StrategyDraft.read().revision)`);
   if(i)edit(id,'value','0');
  }
  const shared=await submit();assert.deepEqual(copy(shared.strategy),wire.shared.strategy);
  assert.equal(requests.at(-1).submitted.length,9);assert.equal(requests.at(-1).labels.length,9);assert(!('detached' in requests.at(-1)));
 }
 // The results line under the builder speaks for the latest picks, and only when it has something to say:
 // no picks for the settings, or changed settings. Historical backtest mode hides the line.
 const resultsLine=()=>{run('updateResultsState()');return node('results-state').textContent;};
 const stubs={...context.ResultArtifacts};
 run("screeningMode='latest'");assert.equal(resultsLine(),'No results for these settings yet. Select Screen latest.');
 Object.assign(context.ResultArtifacts,{forView:()=>({kind:'latest'}),matches:()=>true});assert.equal(resultsLine(),'','Results that match the settings need no line');
 context.ResultArtifacts.matches=()=>false;assert(resultsLine().startsWith('Settings changed — displayed results do not match the current settings.'));
 run("screeningMode='backtest';setModeVisibility()");assert.equal(node('results-state').hidden,true);
 Object.assign(context.ResultArtifacts,stubs);
 console.log('Passed: default chain and offline shape, both example chains, repeated Ranks, keyboard moves, stale replies, units and equality, flat/capture-1/capture-2 restore with ranks 20–40 and exact spellings, 50-step refusal, held save/cancel, snapshot-before-await, capture-before-ID and copy without calculation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
