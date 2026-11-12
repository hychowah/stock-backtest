'use strict';
// One ordered step list: the real picker, draft and list listeners, with a
// controlled variable service. Rank and Filter steps share one source list.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const nodes=new Map(),opened=[],chosen=[];
function node(id){
  if(!nodes.has(id))nodes.set(id,{id,value:'',checked:false,tagName:'INPUT',options:[],textContent:'',innerHTML:'',className:'',disabled:false,hidden:false,dataset:{},attributes:{},handlers:{},
    add(){},setAttribute(key,value){this.attributes[key]=String(value);},querySelector:()=>null,querySelectorAll:()=>[],addEventListener(type,handler){(this.handlers[type]??=[]).push(handler);},
    focus(){document.activeElement=this;},select(){},closest(){return null;}});
  return nodes.get(id);
}
const document={getElementById:node,querySelector:node,querySelectorAll:()=>[],activeElement:null};
node('screening-data').textContent=JSON.stringify({metrics:{ev_ebitda:{label:'EV/EBITDA'}},filter_catalog:{pe:{label:'P/E (×)',available:true},roe:{label:'Return on average equity (%)',available:false}},companies:{},choices:{sector:['Energy','Finance'],exchange:['NYSE']},bounds:{first:'1996-01-01'},latest:{metadata:{asof:'2015-01-05'}}});
const builtins={'filter:pe':{id:'filter:pe',label:'P/E (×)',unit:'scalar',display:'multiple'},'filter:roe':{id:'filter:roe',label:'Return on average equity (%)',unit:'scalar',display:'percent'}};
const revenue={variable_id:'local:annual.revenue',revision:'sha256:'+'b'.repeat(64)};
const capture={program:{bundle:{definitions:[{...revenue,definition:{}}]},definitions:[{...revenue,unit:'USD',display:'usd_million'}]},presentation:[{...revenue,name:'Revenue'}]};
let sourcesFailure=true,useFailure=null;
const workspace={
  builtin:id=>builtins[id]?structuredClone(builtins[id]):null,displays:unit=>({USD:['usd','usd_million']}[unit]||[]),
  displayName:value=>({multiple:'Multiple (×)',usd:'US dollars',usd_million:'$ million',percent:'Percent (%)'}[value]||value),
  open:async(role,base)=>{opened.push(JSON.parse(JSON.stringify({role,base})));},content:()=>({submitted:[],labels:[]}),
  sources:async()=>{if(sourcesFailure)throw Error('offline');return {library:[{variable_id:'variable:saved',revision:'sha256:'+'c'.repeat(64),name:'Saved margin',favourite:true}],inputs:[{id:'measure:gross_margin',name:'Gross margin',category:'Margins and returns'},{id:'annual.revenue',name:'Revenue',category:'Income statement'}]};},
  useSource:async(role,choice,expected)=>{chosen.push({role,choice});if(useFailure)throw useFailure;vm.runInContext('StrategyDraft',context).patch({role,source:{kind:'formula',...revenue},capture,authored:capture.program.bundle.definitions},expected);}
};
const context=vm.createContext({console,document,StockScreener:require('../website/browser/screener.js'),
  CalendarSettings:{read:()=>({}),restore(){},decode:v=>v},EngineControls:{fields:()=>({engine:'original'}),sync(){}},
  ResultArtifacts:{forView:()=>null,matches:()=>false},
  VariableWorkspace:workspace,localStorage:{getItem:()=>null,setItem(){}},crypto:require('node:crypto').webcrypto,Uint8Array,setTimeout,clearTimeout});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/filter-picker.js'),'utf8'),context);
const source=fs.readFileSync(path.join(__dirname,'../website/browser/range.js'),'utf8');
vm.runInContext(source.slice(0,source.indexOf('\ninitializeFilters();')),context);
vm.runInContext("updateResultsState=()=>{};initializeFilters();",context);
// The page's own step-list listeners, including the picker binding.
vm.runInContext(source.slice(source.indexOf("for(const kind of ['filter','rank'])"),source.indexOf('\nconst autoRun=')),context);
const run=code=>vm.runInContext(code,context),tick=()=>new Promise(resolve=>setImmediate(resolve)),later=()=>new Promise(resolve=>setTimeout(resolve,5));
const list=node('strategy-steps');
const fire=(type,target,extra={})=>{for(const handler of list.handlers[type]||[])handler({target,preventDefault(){},stopPropagation(){},...extra});};
const button=dataset=>({dataset,closest(){return this;}});
const add=kind=>{for(const handler of node('add-'+kind).handlers.click)handler({});};
const search=key=>{const input=node('filter-search-'+key);input.dataset.filterSearch=key;input.dataset.label??='';return input;};
const options=key=>node('filter-options-'+key).innerHTML;
const type=(key,text)=>{const input=search(key);input.value=text;fire('input',input);};
const press=(key,name)=>fire('keydown',search(key),{key:name});
const edit=(step,key,value,event='change')=>fire(event,{dataset:{step,key},value});
const rows=()=>JSON.parse(JSON.stringify(run('StrategyDraft.view()')));
const ids=()=>rows().map(row=>row.id);
(async()=>{
 const [cap,ev,rank]=ids();
 // A step's compact buttons keep their ids and full accessible names, and
 // selecting a rendered button still moves its step.
 const rendered=id=>{const tag=list.innerHTML.match(new RegExp('<button[^>]*\\bid="'+id+'"[^>]*>'));assert(tag,'Missing button '+id);return Object.fromEntries([...tag[0].matchAll(/([\w-]+)="([^"]*)"/g)].map(([,key,value])=>[key,value]));};
 const select=id=>{const tag=rendered(id);fire('click',button({action:tag['data-action'],step:tag['data-step']}));};
 assert.deepEqual([rendered('step-down-'+cap)['aria-label'],rendered('step-up-'+ev)['aria-label'],rendered('step-remove-'+rank)['aria-label']],['Move down step 1 · filter','Move up step 2 · filter','Remove step 3 · rank']);
 select('step-down-'+cap);assert.deepEqual(ids(),[ev,cap,rank]);assert.equal(rendered('step-up-'+cap)['aria-label'],'Move up step 2 · filter');
 select('step-up-'+cap);assert.deepEqual(ids(),[cap,ev,rank]);
 // Without the local service, built-in sources remain and the list says why.
 add('filter');assert(list.innerHTML.includes('id="filter-search-new"'));assert(list.innerHTML.includes('New filter'));assert(list.innerHTML.includes('data-action="cancel"'));assert.equal(document.activeElement.id,'filter-search-new');
 fire('focusin',search('new'));assert.equal(node('filter-options-new').hidden,false);
 for(const group of ['Size and listing','EV/EBITDA metrics','Built-in values'])assert(options('new').includes(group),'Missing '+group);
 assert(options('new').includes('Loading saved variables'));
 await tick();await tick();
 assert(options('new').includes('need the local service'));assert(options('new').includes('P/E'));assert(!options('new').includes('Create a new variable'));
 press('new','Escape');assert.equal(node('filter-options-new').hidden,true);
 // Opening again retries; every source then appears in one list.
 sourcesFailure=false;node('elsewhere').focus();fire('focusout',search('new'));await later();
 search('new').focus();fire('focusin',search('new'));await tick();await tick();
 // Re-rendering removes the focused field (focusout) and refocuses its successor.
 fire('focusout',search('new'));run('renderSteps()');await later();assert.equal(node('filter-options-new').hidden,false);
 for(const text of ['My variables','★ Saved margin','Financial inputs','Gross margin','Revenue','Income statement','EV/EBITDA yield','EV/EBITDA multiple','Market cap','Sector','＋ Create a new variable…'])assert(options('new').includes(text),'Missing '+text);
 assert(/aria-disabled="true"><span>Return on average equity/.test(options('new')),'Unavailable built-ins stay visible but cannot be chosen');
 // Typing filters by every word; Escape restores the row's label.
 type('new','reve');assert(options('new').includes('Revenue'));assert(!options('new').includes('P/E'));assert(options('new').includes('Create a new variable'));
 type('new','no such filter');assert(options('new').includes('Nothing matches'));
 press('new','Escape');assert.equal(node('filter-options-new').hidden,true);assert.equal(search('new').value,'');
 // A built-in choice stays offline, joins before the last Rank and waits for a value.
 fire('focusin',search('new'));type('new','p/e');press('new','Enter');
 const pe=ids()[2];assert.deepEqual(ids(),[cap,ev,pe,rank]);assert.equal(rows()[2].label,'P/E (×)');assert.equal(rows()[2].value,'');assert.equal(rows()[2].unit,'multiple');
 assert(list.innerHTML.includes('value="P/E (×)"'));assert(!list.innerHTML.includes('filter-search-new'));assert.equal(document.activeElement.id,'step-value-'+pe);
 edit(pe,'value','12','input');assert.equal(rows()[2].value,'12');assert.deepEqual(JSON.parse(JSON.stringify(run('StrategyDraft.flat().filters'))),[{field:'pe',op:'gt',value:12}]);
 // A disabled choice is skipped by the keyboard and refused by the pointer.
 add('filter');fire('focusin',search('new'));type('new','equity');press('new','Enter');assert.equal(ids().length,4);
 const disabled={dataset:{option:'0'},closest:selector=>selector==='.filter-options'?{}:disabled};fire('mousedown',disabled);assert.equal(ids().length,4);
 press('new','Escape');
 // A financial input makes a variable step; built-in and variable steps share the list.
 type('new','revenue');assert(options('new').includes('aria-selected="true"><span>Revenue'));
 press('new','ArrowDown');assert(options('new').includes('aria-selected="true"><span>＋ Create'));press('new','ArrowUp');press('new','Enter');await tick();
 assert.equal(chosen.at(-1).role,'filter');assert.equal(chosen.at(-1).choice.kind,'input');
 const variable=ids()[3];assert.deepEqual(ids(),[cap,ev,pe,variable,rank]);assert(!list.innerHTML.includes('filter-search-new'));
 assert(list.innerHTML.includes('value="P/E (×)"'));assert(list.innerHTML.includes('value="Revenue"'));assert(list.innerHTML.includes('id="step-edit-'+variable+'"'));assert(!list.innerHTML.includes('id="step-edit-'+pe+'"'));
 assert(list.innerHTML.includes('>$ million</option>'));assert(list.innerHTML.includes('>US dollars</option>'));
 assert.equal(document.activeElement.id,'step-value-'+variable);
 edit(variable,'value','500','input');edit(variable,'unit','usd');
 assert.equal(rows()[3].value,'500');assert.equal(rows()[3].unit,'usd');assert.equal(rows()[2].value,'12');assert.equal(run('StrategyDraft.flat()'),null,'A variable leaves the offline shape');
 // A built-in choice replaces a variable step in place.
 fire('focusin',search(variable));type(variable,'p/e');press(variable,'Enter');await tick();
 assert.equal(rows()[3].label,'P/E (×)');assert.equal(rows()[3].formula,false);assert.equal(rows()[3].value,'500');assert.equal(rows()[3].id,variable);
 // Edit formula and Create open the editor for the same step.
 fire('focusin',search(variable));type(variable,'revenue');press(variable,'Enter');await tick();
 fire('click',button({action:'edit',step:variable}));assert.deepEqual(opened.at(-1),{role:variable,base:{root:revenue,capture}});
 add('filter');fire('focusin',search('new'));type('new','create');press('new','Enter');assert.equal(opened.length,1,'Typing never selects an action');
 press('new','ArrowDown');press('new','Enter');assert.deepEqual(opened.at(-1),{role:'filter',base:null});
 fire('click',button({action:'cancel'}));assert(!list.innerHTML.includes('filter-search-new'));
 fire('focusin',search(variable));type(variable,'revenue');press(variable,'ArrowDown');press(variable,'Enter');assert.deepEqual(opened.at(-1),{role:variable,base:null},'Create on a formula step opens empty');
 // A failed choice reports itself and leaves the strategy unchanged.
 const before=JSON.stringify(rows());
 useFailure=Object.assign(Error('stale'),{code:'STALE_DRAFT'});
 fire('focusin',search(pe));type(pe,'revenue');press(pe,'Enter');await tick();await tick();
 assert(node('filter-message').textContent.includes('changed while Revenue was loading'));assert.equal(node('filter-message').className,'error');assert.equal(JSON.stringify(rows()),before);
 useFailure=null;
 // Sector and exchange filters use equality with the market's choices.
 add('filter');fire('focusin',search('new'));type('new','sector');press('new','Enter');
 const sector=ids()[4];assert.equal(rows()[4].text,true);assert(list.innerHTML.includes('<option value="Finance" >Finance</option>'));assert.equal(document.activeElement.id,'step-value-'+sector);
 edit(sector,'value','Finance');assert.equal(rows()[4].value,'Finance');
 // Move buttons keep focus on the moved step; Remove clears the message.
 select('step-up-'+sector);assert.equal(ids()[3],sector);assert.equal(document.activeElement.id,'step-up-'+sector);
 select('step-down-'+sector);assert.equal(ids()[4],sector);assert.equal(document.activeElement.id,'step-down-'+sector);
 node('filter-message').textContent='old';select('step-remove-'+sector);assert(!ids().includes(sector));assert.equal(node('filter-message').textContent,'');assert.equal(document.activeElement.id,'step-remove-'+rank);
 // A Rank uses the same list without size and listing fields, and keeps its own order and range.
 add('rank');assert(list.innerHTML.includes('New rank'));fire('focusin',search('new'));
 assert(!options('new').includes('Size and listing'));assert(options('new').includes('EV/EBITDA metrics'));assert(options('new').includes('Gross margin'));
 type('new','saved margin');press('new','Enter');await tick();
 assert.equal(chosen.at(-1).role,'rank');assert.equal(chosen.at(-1).choice.kind,'library');
 const second=ids().at(-1);assert.equal(rows().at(-1).kind,'rank');assert.equal(document.activeElement.id,'step-direction-'+second);
 edit(second,'direction','lowest');assert.equal(rows().at(-1).direction,'lowest');
 edit(second,'rank_from','60');assert.deepEqual([rows().at(-1).rank_from,rows().at(-1).rank_to],[60,60],'A committed first rank above the last moves the last');
 edit(second,'rank_to','20');assert.deepEqual([rows().at(-1).rank_from,rows().at(-1).rank_to],[20,20]);
 assert(list.innerHTML.includes('id="step-rank_from-'+second+'"'));assert(list.innerHTML.includes('Highest first'));
 console.log('Passed: one ordered step list for built-in, field, saved and financial-input sources; word search, keyboard choice, disabled options, offline note and retry, insertion before the last Rank, units, equality choices, moves with focus, edit/create, failures, removal and Rank ranges.');
})().catch(error=>{console.error(error);process.exitCode=1;});
