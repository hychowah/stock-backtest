'use strict';
// Real workspace handlers with controlled transport. No copied editor logic.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),calls=[],applied=[],errors=[];
function node(id){if(!nodes.has(id))nodes.set(id,{id,value:'',textContent:'',innerHTML:'',hidden:false,open:false,handlers:{},dataset:{},addEventListener(k,f){this.handlers[k]=f;},focus(){document.activeElement=this;},showModal(){this.open=true;},close(){this.open=false;},setAttribute(){},removeAttribute(){}});return nodes.get(id);}
const document={getElementById:node,querySelector:node,activeElement:node('opener')};
const exact={variable_id:'variable:one',revision:'sha256:'+'1'.repeat(64)};
const definition={format:'variable-definition',version:1,parameter_catalog:'financial-parameters/1',temporal_policy:'annual-lag90/1',expression:{op:'constant',value:'2',unit:'scalar'},output:{unit:'scalar',display:'number'}};
const entry={...exact,name:'Saved source',version:1,favourite:false,deleted:false};
const capture={program:{bundle:{definitions:[{...exact,definition}]},definitions:[{...exact,unit:'scalar',display:'number'}]},presentation:[{...exact,name:entry.name}]};
let revision=3,draftSettings=null,draftDetached=[],emptyLibrary=false,validationWait=null,saveWait=null,authoredWait=null,previewCount=0,conflict=false,useWire=false,lastWireValidation=null;
const wireOrigin=process.argv[2]==='--wire'?process.argv[3]:null,wire=wireOrigin?JSON.parse(fs.readFileSync(0,'utf8')):null;
const response=(value,status=200)=>({ok:status<400,status,json:async()=>structuredClone(value)});
const context=vm.createContext({console,document,VariableEvidence:{preview:value=>{assert.equal(value.population,'explicit-request-scopes');return '<p>3 requested samples; not complete-pool coverage</p>';}},crypto:require('node:crypto').webcrypto,Uint8Array,fetch:async(url,options={})=>{
 const body=options.body?JSON.parse(options.body):null;calls.push({url,body});
 if(useWire){
  if(options.body)assert(Buffer.byteLength(options.body)<=256*1024);
  if(url.endsWith('/authored')){const item=wire.shared.references.find(item=>item.source.variable_id===body.variable_id&&item.source.revision===body.revision);assert(item);return response(item.snapshot);}
  if(url==='/api/variables')return response({entries:wire.shared.references.map(item=>item.snapshot.entry)});
  const reply=await fetch(wireOrigin+url,options),value=await reply.json();if(url.endsWith('/validate'))lastWireValidation=value;return response(value,reply.status);
 }
 if(url.endsWith('/catalog'))return response({parameters:['annual.revenue','annual.operating_income','annual.operating_margin','market.enterprise_value'].map(id=>({id,description:id,unit:id.endsWith('margin')?'scalar':'USD'})),builtins:[{id:'filter:pe',label:'P/E',unit:'scalar',display:'multiple'}]});
 if(url==='/api/variables')return response(body?{...entry,name:body.name,version:2}:{entries:emptyLibrary?[]:[entry]});
 if(url.endsWith('/detached')){assert.deepEqual(body.root,exact);return response({selected:exact,name:'Original detached name',authored:[{...exact,definition}],capture});}
 if(url.endsWith('/authored')){if(authoredWait)await authoredWait();return response({entry,selected:exact,authored:[{...exact,definition}],capture});}
 if(url.endsWith('/validate')){if(validationWait)await validationWait();return response({root:{variable_id:body.variable_id,revision:exact.revision},output:{unit:body.definition.output.unit,display:body.definition.output.display},requirements:[],capture,authored:[...(body.submitted||[]),{variable_id:body.variable_id,revision:exact.revision,definition:body.definition}]});}
 if(url.endsWith('/save')){if(saveWait)await saveWait();return conflict?response({error:'Entry changed',code:'VERSION_CONFLICT'},409):response({...entry,name:body.name,version:2});}
 if(url.endsWith('/favourite'))return response({...entry,version:2,favourite:true});
 if(url.endsWith('/capture'))return response({strategy:{selection:body.intent.selection,bounds:{}}});
 if(url==='/api/variable-preview'){previewCount++;return response({population:'explicit-request-scopes',roots:body.roots});}
 throw Error('Unexpected route '+url);
}});
vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../website/browser/variable-workspace.js'),'utf8'),context);
const run=code=>vm.runInContext(code,context),tick=()=>new Promise(resolve=>setImmediate(resolve));
const event=(id,type,target=node(id))=>node(id).handlers[type]({target,stopPropagation(){}});
const click=id=>{event(id,'click');return tick();};
context.draft={read:()=>({revision,settings:draftSettings,detached:draftDetached}),patch:(change,expected)=>{assert.equal(expected,revision,'Stale picker apply');applied.push(structuredClone(change));revision++;}};
run("VariableWorkspace.init({draft,asof:'2015-01-05',pool:()=> 'cached'})");
(async()=>{
 await run("VariableWorkspace.open('ranking')");
 assert(node('variable-dialog').open);assert.equal(document.activeElement.id,'variable-search');
 assert(node('variable-tree').innerHTML.includes('market.enterprise_value'));
 const expression={op:'div',left:{op:'mul',left:{op:'parameter',id:'annual.revenue'},right:{op:'annual',stat:'mean',count:3,parameter:'annual.operating_margin'}},right:{op:'parameter',id:'market.enterprise_value'}};
 // Advanced JSON remains local before validation, so even malformed numeric
 // fields must be escaped when the real visual renderer displays them.
 for(const malformed of [{op:'annual',stat:'mean',count:'" onfocus="unsafe',parameter:'annual.operating_margin'},{op:'lookback',months:'" onfocus="unsafe',arg:{op:'parameter',id:'annual.operating_margin'}}]){
  node('variable-json').value=JSON.stringify(malformed);await click('variable-accept-json');assert(node('variable-tree').innerHTML.includes('&quot; onfocus=&quot;unsafe'));assert(!node('variable-tree').innerHTML.includes('value="" onfocus="unsafe'));
 }
 node('variable-json').value=JSON.stringify(expression);await click('variable-accept-json');
 assert.deepEqual(JSON.parse(node('variable-json').value),expression);assert(node('variable-tree').innerHTML.includes('Numerator'));assert(node('variable-tree').innerHTML.includes('Denominator'));
 await click('variable-validate');assert.deepEqual(calls.at(-1).body.definition.expression,expression);assert(node('variable-explanation').textContent.includes(exact.revision));
 node('variable-display').value='multiple';event('variable-display','change');assert(!node('variable-explanation').textContent.includes(exact.revision));assert(node('variable-explanation').textContent.includes('need validation'));
 // A late validation cannot relabel new edits as checked.
 let release;validationWait=()=>new Promise(resolve=>release=resolve);event('variable-validate','click');await tick();
 node('variable-name').value='Newer local name';event('variable-name','input');release();validationWait=null;await tick();assert(!node('variable-explanation').textContent.includes(exact.revision));
 node('variable-preview-symbols').value=Array(17).fill('A').join(',');await click('variable-preview');assert.equal(previewCount,0);assert(node('variable-errors').textContent.includes('1–16'));
 node('variable-preview-symbols').value='A0000,A0001,UNKNOWN';node('variable-preview-mode').value='historical';await click('variable-preview');await tick();
 assert.equal(previewCount,1);assert.equal(calls.at(-1).body.engine,'original');assert.equal(calls.at(-1).body.roots.length,3);assert.deepEqual(Object.keys(calls.at(-1).body.roots[0]).sort(),['date','mode','pool','symbol']);assert(node('variable-preview-result').innerHTML.includes('not complete-pool coverage'));
 // Exact library selection remains explicit. Save conflict preserves raw text.
 const pick={dataset:{library:exact.variable_id,revision:exact.revision},closest(){return this;}};
 event('variable-picker','click',pick);await tick();assert.equal(applied.length,0);assert(node('variable-selected').textContent.includes(exact.revision));
 node('variable-name').value='My unsaved name';event('variable-name','input');conflict=true;await click('variable-save');assert.equal(node('variable-name').value,'My unsaved name');assert(node('variable-errors').textContent.includes('Entry changed'));conflict=false;
 // An acknowledged save cannot overwrite edits made while publication waits.
 saveWait=()=>new Promise(resolve=>release=resolve);event('variable-save','click');await tick();
 node('variable-name').value='Edited while saving';event('variable-name','input');release();saveWait=null;await tick();await tick();assert.equal(node('variable-name').value,'Edited while saving');assert(node('variable-message').textContent.includes('newer local edits'));
 await click('variable-favourite');assert.equal(node('variable-favourite').textContent,'Remove favourite');
 await click('variable-apply');assert.equal(applied.length,1);assert.equal(applied[0].source.revision,exact.revision);assert(!node('variable-dialog').open);assert.equal(document.activeElement.id,'opener');
 await run("VariableWorkspace.open('condition')");event('variable-dialog','cancel');assert.equal(document.activeElement.id,'opener');
 await run("VariableWorkspace.open('ranking')");authoredWait=()=>new Promise(resolve=>release=resolve);event('variable-picker','click',pick);await tick();await click('variable-start-new');release();authoredWait=null;await tick();assert(node('variable-selected').textContent.includes('Unsaved local variable'));
 // Ordinary edits also fence a pending replacement read, without closing or
 // replacing the editor session. Validate reads the retained local model.
 for(const field of ['name','expression']){
  node('variable-json').value=JSON.stringify({op:'constant',value:'7',unit:'scalar'});await click('variable-accept-json');
  authoredWait=()=>new Promise(resolve=>release=resolve);event('variable-picker','click',pick);await tick();
  if(field==='name'){node('variable-name').value='Name edited during read';event('variable-name','input');}
  else event('variable-tree','input',{dataset:{path:'',field:'value'},value:'9'});
  release();authoredWait=null;await tick();await click('variable-validate');
  if(field==='name')assert.equal(calls.at(-1).body.name,'Name edited during read');
  else assert.equal(calls.at(-1).body.definition.expression.value,'9');
  assert(node('variable-selected').textContent.includes('Unsaved local variable'));
 }
 revision++;const builtin={dataset:{builtin:'filter:pe'},closest(){return this;}};event('variable-picker','click',builtin);await tick();assert.equal(applied.length,1);assert(node('variable-dialog').open);assert(node('variable-errors').textContent.includes('Stale picker apply'));
 // A restored exact source opens from checked captured content, with no archive.
 emptyLibrary=true;draftSettings={strategy:{selection:{ranking:{source:{kind:'formula',...exact}},conditions:[]}}};draftDetached=[capture];
 const authoredBefore=calls.filter(call=>call.url.endsWith('/authored')).length;
 await run("VariableWorkspace.open('ranking')");assert.equal(node('variable-name').value,'Original detached name');assert(node('variable-selected').textContent.includes('Captured exact selection'));assert(node('variable-favourite').disabled);assert.equal(calls.filter(call=>call.url.endsWith('/authored')).length,authoredBefore);
 assert.deepEqual(JSON.parse(node('variable-json').value),definition.expression);await click('variable-apply');assert.equal(applied.length,2);assert.equal(applied.at(-1).source.revision,exact.revision);
 if(wire){
  useWire=true;draftSettings={strategy:{selection:{ranking:{source:wire.shared.editor_source},conditions:[]},variables:wire.shared.editor_expected.capture}};draftDetached=[];
  await run("VariableWorkspace.open('ranking')");
  // Insert all eight references through the real picker handlers. Authored
  // snapshots are fixture bytes produced by the real owner, without an archive.
  const paths=['left.left.left','left.left.right','left.right.left','left.right.right','right.left.left','right.left.right','right.right.left','right.right.right'];
  for(let i=0;i<paths.length;i++){
   event('variable-tree','click',{dataset:{reference:paths[i]}});
   const source=wire.shared.references[i].source;event('variable-picker','click',{dataset:{library:source.variable_id,revision:source.revision},closest(){return this;}});await tick();await tick();
  }
  await click('variable-validate');const deadline=Date.now()+10000;while(!lastWireValidation&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,5));assert(lastWireValidation?.capture,JSON.stringify(lastWireValidation));assert.deepEqual(lastWireValidation,wire.shared.editor_expected);
  assert.equal(calls.at(-1).body.submitted.length,9);assert.equal(calls.at(-1).body.labels.length,9);assert(!('detached' in calls.at(-1).body));
 }
 assert(!calls.some(call=>call.url.includes('/api/backtest-')));assert.equal(errors.length,0);
 console.log('Passed: actual tree/JSON round trip, grouping, stale validation, exact picker, explicit bounded preview, optimistic conflict, save race, favourite, apply and keyboard focus; no jobs.');
})().catch(error=>{console.error(error);process.exitCode=1;});
