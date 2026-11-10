'use strict';
// One Additional filters list: the real picker and form owners, with a
// controlled variable service. Built-in and variable sources share the rows.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const nodes=new Map(),opened=[],chosen=[];
function node(id){
  if(!nodes.has(id))nodes.set(id,{id,value:'',checked:false,tagName:'INPUT',options:[],textContent:'',innerHTML:'',className:'',disabled:false,hidden:false,dataset:{},attributes:{},handlers:{},
    add(){},setAttribute(key,value){this.attributes[key]=String(value);},querySelector:()=>null,querySelectorAll:()=>[],addEventListener(type,handler){(this.handlers[type]??=[]).push(handler);},
    focus(){document.activeElement=this;},select(){},closest(){return null;}});
  return nodes.get(id);
}
const document={getElementById:node,querySelector:node,querySelectorAll:()=>[],activeElement:null};
node('screening-data').textContent=JSON.stringify({metrics:{ev_ebitda:{label:'EV/EBITDA'}},filter_catalog:{pe:{label:'P/E (×)',available:true},roe:{label:'Return on average equity (%)',available:false}},companies:{},latest:{metadata:{asof:'2015-01-05'}}});
const defaults={selection_order:'filter_first',metric:'ev_ebitda',pool:'legacy',min_cap:100e6,max_cap:null,min_ev:50e6,min_yield:0,max_multiple:null,sector:null,exchange:null};
const builtins={'filter:pe':{id:'filter:pe',label:'P/E (×)',unit:'scalar',display:'multiple'},'filter:roe':{id:'filter:roe',label:'Return on average equity (%)',unit:'scalar',display:'percent'}};
const revenue={variable_id:'local:annual.revenue',revision:'sha256:'+'b'.repeat(64)};
const capture={program:{bundle:{definitions:[{...revenue,definition:{}}]},definitions:[{...revenue,unit:'USD',display:'usd_million'}]},presentation:[{...revenue,name:'Revenue'}]};
let sourcesFailure=true,useFailure=null;
const workspace={
  builtin:id=>builtins[id]?structuredClone(builtins[id]):null,displays:unit=>({USD:['usd','usd_million']}[unit]||[]),
  displayName:value=>({multiple:'Multiple (×)',usd:'US dollars',usd_million:'$ million'}[value]||value),
  open:async role=>{opened.push(role);},content:()=>({submitted:[],labels:[]}),
  sources:async()=>{if(sourcesFailure)throw Error('offline');return {library:[{variable_id:'variable:saved',revision:'sha256:'+'c'.repeat(64),name:'Saved margin',favourite:true}],measures:[{id:'gross_margin',name:'Gross margin',display:'percent',description:'Gross margin'}],parameters:[{id:'adapter.test',kind:'adapter',name:'Policy adapter',unit:'scalar'},{id:'annual.revenue',name:'Revenue',note:'',unit:'USD',source:{endpoint:'income-statement'}}]};},
  useSource:async(role,choice,expected)=>{chosen.push({role,choice});if(useFailure)throw useFailure;vm.runInContext('StrategyDraft',context).patch({role,source:{kind:'formula',...revenue},capture,authored:capture.program.bundle.definitions},expected);}
};
const context=vm.createContext({console,data:[],document,StockScreener:{defaults},
  CalendarSettings:{read:()=>({}),restore(){},decode:v=>v},EngineControls:{fields:()=>({engine:'original'}),sync(){}},
  ResultArtifacts:{forView:()=>null,matches:()=>false},ScheduleView:{isRunning:()=>false},SavedBacktests:{update(){}},BacktestQueue:{isManaging:()=>false},
  VariableWorkspace:workspace,localStorage:{getItem:()=>null,setItem(){}},crypto:require('node:crypto').webcrypto,Uint8Array,setTimeout,clearTimeout});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/filter-picker.js'),'utf8'),context);
const source=fs.readFileSync(path.join(__dirname,'../website/browser/range.js'),'utf8');
vm.runInContext(source.slice(0,source.indexOf('\ninitializeFilters();')),context);
vm.runInContext('updateResultsState=()=>{};',context);
// The page's own list listeners, including the picker binding.
vm.runInContext(source.slice(source.indexOf("document.getElementById('add-filter').addEventListener"),source.indexOf('\nconst autoRun=')),context);
for(const [key,id] of Object.entries({selection_order:'selection-order',metric:'ranking-metric',pool:'stock-pool',min_cap:'min-cap',max_cap:'max-cap',min_ev:'min-ev',min_yield:'min-yield',max_multiple:'max-multiple',sector:'sector-filter',exchange:'exchange-filter'}))node(id).value=defaults[key]===null?'':String(key==='min_cap'||key==='min_ev'?defaults[key]/1e6:defaults[key]);
node('rank-from').value='1';node('rank-to').value='50';
const run=code=>vm.runInContext(code,context),tick=()=>new Promise(resolve=>setImmediate(resolve)),later=()=>new Promise(resolve=>setTimeout(resolve,5));
const list=node('filter-conditions');
const fire=(type,target,extra={})=>{for(const handler of list.handlers[type]||[])handler({target,preventDefault(){},stopPropagation(){},...extra});};
const button=dataset=>({dataset,closest(){return this;}});
const add=()=>{for(const handler of node('add-filter').handlers.click)handler({});};
const search=key=>{const input=node('filter-search-'+key);input.dataset.filterSearch=key;input.dataset.label??='';return input;};
const options=key=>node('filter-options-'+key).innerHTML;
const type=(key,text)=>{const input=search(key);input.value=text;fire('input',input);};
const press=(key,name)=>fire('keydown',search(key),{key:name});
const edit=(index,key,value,event='change')=>fire(event,{dataset:{index:String(index),key},value});
const rows=()=>JSON.parse(JSON.stringify(run('StrategyDraft.filterRows()')));
(async()=>{
 // Without the local service, built-ins remain and the list says why.
 add();assert(list.innerHTML.includes('id="filter-search-new"'));assert(list.innerHTML.includes('data-filter-cancel'));assert.equal(document.activeElement.id,'filter-search-new');
 fire('focusin',search('new'));assert.equal(node('filter-options-new').hidden,false);
 assert(options('new').includes('Built-in filters'));assert(options('new').includes('Loading saved variables'));
 await tick();await tick();
 assert(options('new').includes('need the local service'));assert(options('new').includes('P/E'));assert(!options('new').includes('Create a new variable'));
 press('new','Escape');assert.equal(node('filter-options-new').hidden,true);
 // Opening again retries; every source then appears in one list.
 sourcesFailure=false;node('elsewhere').focus();fire('focusout',search('new'));await later();
 search('new').focus();fire('focusin',search('new'));await tick();await tick();
 // Re-rendering removes the focused field (focusout) and refocuses its successor.
 fire('focusout',search('new'));run('renderConditions()');await later();assert.equal(node('filter-options-new').hidden,false);
 for(const text of ['My variables','★ Saved margin','Measures','Gross margin','Financial parameters','Revenue','income-statement','＋ Create a new variable…'])assert(options('new').includes(text),'Missing '+text);
 assert(/aria-disabled="true"><span>Return on average equity/.test(options('new')),'Unavailable built-ins stay visible but cannot be chosen');
 // Rank by uses a native grouped list, including adapters hidden from filters.
 run('syncCatalogControls()');
 assert.deepEqual(Array.from(node('ranking-source').innerHTML.matchAll(/<optgroup label="([^"]+)"/g),item=>item[1]),['EV/EBITDA metrics','Built-in parameters','Financial parameters','Measures','My variables']);
 for(const label of ['Policy adapter','Saved margin','Gross margin','Revenue','EV/EBITDA yield','P/E (×)'])assert(node('ranking-source').innerHTML.includes(label));
 assert(!options('new').includes('Policy adapter'));
 // Typing filters by every word; Escape restores the row's label.
 type('new','reve');assert(options('new').includes('Revenue'));assert(!options('new').includes('P/E'));assert(options('new').includes('Create a new variable'));
 type('new','no such filter');assert(options('new').includes('Nothing matches'));
 press('new','Escape');assert.equal(node('filter-options-new').hidden,true);assert.equal(search('new').value,'');
 // A built-in choice stays offline and waits for a value before running.
 fire('focusin',search('new'));type('new','p/e');press('new','Enter');
 assert.deepEqual(JSON.parse(JSON.stringify(run('filterConditions'))),[{field:'pe',op:'gt',value:''}]);assert.equal(run('StrategyDraft.isScalar()'),false);
 assert(list.innerHTML.includes('value="P/E (×)"'));assert(!list.innerHTML.includes('filter-search-new'));assert.equal(document.activeElement.id,'filter-value-0');
 edit(0,'value','12');assert.equal(run('readOptions().filters[0].value'),12);
 // A disabled choice is skipped by the keyboard and refused by the pointer.
 add();fire('focusin',search('new'));type('new','equity');press('new','Enter');assert.equal(run('filterConditions.length'),1);
 const disabled={dataset:{option:'0'},closest:selector=>selector==='.filter-options'?{}:disabled};fire('mousedown',disabled);assert.equal(run('filterConditions.length'),1);
 press('new','Escape');
 // A parameter moves the strategy to variables; both rows stay in one list.
 type('new','revenue');assert(options('new').includes('aria-selected="true"><span>Revenue'));
 press('new','ArrowDown');assert(options('new').includes('aria-selected="true"><span>＋ Create'));press('new','ArrowUp');press('new','Enter');await tick();
 assert.equal(chosen.at(-1).role,'condition');assert.equal(chosen.at(-1).choice.kind,'parameter');assert.equal(run('StrategyDraft.isScalar()'),true);
 assert.equal(run('filterConditions.length'),0);assert(!list.innerHTML.includes('filter-search-new'));
 assert(list.innerHTML.includes('value="P/E (×)"'));assert(list.innerHTML.includes('value="Revenue"'));assert(list.innerHTML.includes('data-edit="1"'));assert(!list.innerHTML.includes('data-edit="0"'));
 assert(list.innerHTML.includes('>$ million</option>'));assert(list.innerHTML.includes('>US dollars</option>'));
 assert.equal(document.activeElement.id,'filter-value-1');
 edit(1,'value','500','input');edit(1,'unit','usd');
 assert.equal(rows()[1].value,'500');assert.equal(rows()[1].unit,'usd');assert.equal(rows()[0].value,'12');
 // A built-in choice replaces a variable row in place.
 fire('focusin',search('1'));type('1','p/e');press('1','Enter');await tick();
 assert.equal(rows()[1].label,'P/E (×)');assert.equal(rows()[1].formula,false);assert.equal(rows()[1].value,'500');
 // Edit formula and Create open the editor for the same row.
 fire('click',button({edit:'1'}));assert.equal(opened.at(-1),1);
 add();fire('focusin',search('new'));type('new','create');press('new','Enter');assert.equal(opened.length,1,'Typing never selects an action');
 press('new','ArrowDown');press('new','Enter');assert.equal(opened.at(-1),'condition');
 fire('click',button({filterCancel:''}));assert(!list.innerHTML.includes('filter-search-new'));
 // A failed choice reports itself and leaves the strategy unchanged.
 const before=JSON.stringify(rows());
 useFailure=Object.assign(Error('stale'),{code:'STALE_DRAFT'});
 fire('focusin',search('0'));type('0','revenue');press('0','Enter');await tick();await tick();
 assert(node('filter-message').textContent.includes('changed while Revenue was loading'));assert.equal(node('filter-message').className,'error');assert.equal(JSON.stringify(rows()),before);
 useFailure=null;
 fire('click',button({remove:'0'}));assert.equal(rows().length,1);assert.equal(node('filter-message').textContent,'');
 // The ranking list reuses the exact same source application and stale fences.
 await run("chooseRanking({kind:'library',variable_id:'variable:saved',revision:'sha256:'+ 'c'.repeat(64)})");
 assert.equal(chosen.at(-1).role,'ranking');assert.equal(chosen.at(-1).choice.kind,'library');
 assert.equal(run('StrategyDraft.read().settings.strategy.selection.ranking.source.variable_id'),revenue.variable_id);
 assert.equal(node('legacy-pool-note').hidden,false);assert.equal(node('legacy-yield-control').hidden,true);
 await run("chooseRanking({direction:'lowest'})");assert.equal(node('variable-direction').value,'lowest');assert.equal(run('StrategyDraft.ranking().direction'),'lowest');
 useFailure=Object.assign(Error('The strategy draft changed.'),{code:'STALE_DRAFT'});
 const rankingBefore=JSON.stringify(run('StrategyDraft.ranking()'));
 await run("chooseRanking({kind:'parameter',id:'annual.revenue'})");
 assert.equal(JSON.stringify(run('StrategyDraft.ranking()')),rankingBefore);assert(node('screen-error').textContent.includes('draft changed'));
 useFailure=null;
 console.log('Passed: one filter list for built-in, saved, measure and parameter sources; word search, keyboard choice, disabled options, offline note and retry, variable switch, units, edit/create, failures and removal.');
})().catch(error=>{console.error(error);process.exitCode=1;});
