'use strict';
// Real workspace handlers with controlled transport. No copied editor logic.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ownerCatalog=JSON.parse(require('node:child_process').execFileSync('python3',['-c','import json; from backtest.application.variable_authoring import catalog; print(json.dumps(catalog()))'],{encoding:'utf8'}));
const nodes=new Map(),calls=[],applied=[],errors=[];
function node(id){if(!nodes.has(id))nodes.set(id,{id,value:'',textContent:'',innerHTML:'',hidden:false,open:false,handlers:{},dataset:{},addEventListener(k,f){this.handlers[k]=f;},focus(){document.activeElement=this;},showModal(){this.open=true;},close(){this.open=false;},setAttribute(){},removeAttribute(){}});return nodes.get(id);}
const document={getElementById:node,querySelector:node,activeElement:node('opener')};
const exact={variable_id:'variable:one',revision:'sha256:'+'1'.repeat(64)};
const definition={format:'variable-definition',version:1,parameter_catalog:'financial-parameters/1',temporal_policy:'annual-lag90/1',expression:{op:'constant',value:'2',unit:'scalar'},output:{unit:'scalar',display:'number'}};
const entry={...exact,name:'Saved source',version:1,favourite:false,deleted:false};
const capture={program:{bundle:{definitions:[{...exact,definition}]},definitions:[{...exact,unit:'scalar',display:'number'}]},presentation:[{...exact,name:entry.name}]};
let revision=3,draftSources={},draftDetached=[],emptyLibrary=false,validationWait=null,saveWait=null,authoredWait=null,authoredFailure=false,captureWait=null,coverageWait=null,previewCount=0,conflict=false,patchFailure=null,useWire=false,lastWireValidation=null;
const wireOrigin=process.argv[2]==='--wire'?process.argv[3]:null,wire=wireOrigin?JSON.parse(fs.readFileSync(0,'utf8')):null;
const timers=new Map();let timerId=0;
const response=(value,status=200)=>({ok:status<400,status,json:async()=>structuredClone(value)});
const context=vm.createContext({console,document,AbortController,setTimeout:callback=>{timers.set(++timerId,callback);return timerId;},clearTimeout:id=>timers.delete(id),VariableEvidence:{preview:value=>{assert.equal(value.population,'explicit-request-scopes');return '<p>3 requested samples; not complete-pool coverage</p>';}},crypto:require('node:crypto').webcrypto,Uint8Array,fetch:async(url,options={})=>{
 const body=options.body?JSON.parse(options.body):null;calls.push({url,body,signal:options.signal});
 if(useWire){
  if(options.body)assert(Buffer.byteLength(options.body)<=256*1024);
  if(url.endsWith('/authored')){const item=wire.shared.references.find(item=>item.source.variable_id===body.variable_id&&item.source.revision===body.revision);assert(item);return response(item.snapshot);}
  if(url==='/api/variables')return response({entries:wire.shared.references.map(item=>item.snapshot.entry)});
  const reply=await fetch(wireOrigin+url,options),value=await reply.json();if(url.endsWith('/validate'))lastWireValidation=value;return response(value,reply.status);
 }
 if(url.endsWith('/catalog'))return response(ownerCatalog);
 if(url==='/api/variables')return response(body?{...entry,name:body.name,version:2}:{entries:emptyLibrary?[]:[entry]});
 if(url.endsWith('/detached')){assert.deepEqual(body.root,exact);return response({selected:exact,name:'Original detached name',authored:[{...exact,definition}],capture});}
 if(url.endsWith('/authored')){if(authoredWait)await authoredWait();if(authoredFailure)throw Error('Cannot read authored fixture');return response({entry,selected:exact,authored:[{...exact,definition}],capture});}
 if(url.endsWith('/validate')){if(body.upgrade)body.definition={...body.definition,version:3,parameter_catalog:ownerCatalog.current_parameter_catalog,temporal_policy:ownerCatalog.current_temporal_policy};if(validationWait)await validationWait();return response({root:{variable_id:body.variable_id,revision:exact.revision},output:{unit:body.definition.output.unit,display:body.definition.output.display},requirements:[],capture,authored:[...(body.submitted||[]),{variable_id:body.variable_id,revision:exact.revision,definition:body.definition}]});}
 if(url.endsWith('/save')){if(saveWait)await saveWait();return conflict?response({error:'Entry changed',code:'VERSION_CONFLICT'},409):response({...entry,name:body.name,version:2});}
 if(url.endsWith('/favourite'))return response({...entry,version:2,favourite:true});
 if(url.endsWith('/capture')){if(captureWait)await captureWait();return response({strategy:{selection:body.intent.selection,bounds:{}}});}
 if(url==='/api/variable-coverage/scopes')return response({generation:'a'.repeat(64),scopes:[{mode:'latest',context_date:'2015-01-05',pool:'cached',book:0},{mode:'historical',context_date:'2015-01-02',pool:'cached',book:2015}]});
 if(url==='/api/variable-coverage/inspect'){if(coverageWait)await coverageWait();return response({generation:body.scope.generation,projection:{content:'b'.repeat(64)},scope:body.scope,population:4,outputs:[{...exact,valid:4,unavailable:0,reasons:{}}]});}
 if(url==='/api/variable-preview'){previewCount++;return response({population:'explicit-request-scopes',roots:body.roots});}
 throw Error('Unexpected route '+url);
}});
vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../website/browser/variable-workspace.js'),'utf8'),context);
const run=code=>vm.runInContext(code,context),tick=()=>new Promise(resolve=>setImmediate(resolve));
const event=(id,type,target=node(id))=>node(id).handlers[type]({target,stopPropagation(){}});
const click=id=>{event(id,'click');return tick();};
// Run the debounced automatic check, as a pause after typing would.
const flush=()=>{for(const [id,callback] of [...timers]){timers.delete(id);callback();}};
const check=async()=>{flush();await tick();await tick();};
// Roles are browser step IDs, or the kind of a new step.
const describe=role=>({s1:{title:'Step 1 · Rank',use:'Update step 1'},s2:{title:'Step 2 · Filter',use:'Update step 2'},filter:{title:'New filter',use:'Add as filter'}}[role]);
context.draft={read:()=>({revision,detached:draftDetached}),source:role=>draftSources[role]??null,describe,patch:(change,expected)=>{if(patchFailure)throw Error(patchFailure);assert.equal(expected,revision,'Stale picker apply');applied.push(structuredClone(change));revision++;}};
run("VariableWorkspace.init({draft,asof:'2015-01-05',pool:()=> 'cached'})");
(async()=>{
 await run("VariableWorkspace.open('s1')");
 assert(node('variable-dialog').open);assert.equal(document.activeElement.id,'variable-search');
 assert(node('variable-tree').innerHTML.includes('market.enterprise_value'));
 const pickerParameterCount=()=>[...node('variable-picker').innerHTML.matchAll(/data-parameter=/g)].length;
 const measureDisabled=()=>/\bdisabled\b/.test(node('variable-picker').innerHTML.match(/<button[^>]*data-measure="gross_margin"[^>]*>/)[0]);
 assert.equal(pickerParameterCount(),ownerCatalog.expanded_parameters.length);assert.equal(measureDisabled(),false);
 // Compose a quotient through the actual canvas, toolbar and picker handlers.
 const selectTerm=path=>event('variable-equation','click',{dataset:{equationPath:path},closest(){return this;}});
 const operate=action=>event('variable-equation-tools','click',{dataset:{equationAction:action},closest(){return this;}});
 const parameter=id=>event('variable-picker','click',{dataset:{parameter:id},closest(){return this;}});
 const current=()=>JSON.parse(node('variable-json').value);
 parameter('annual.operating_income');operate('div');
 assert.equal(current().left.id,'annual.operating_income');assert.equal(current().right.id,'');
 assert(node('variable-equation').innerHTML.includes('＋ Parameter'));
 parameter('annual.revenue');
 assert.deepEqual(current(),{op:'div',left:{op:'parameter',id:'annual.operating_income'},right:{op:'parameter',id:'annual.revenue'}});
 assert(node('variable-equation').innerHTML.includes('Operating income'));
 selectTerm('left');operate('mul');operate('constant');
 event('variable-tree','input',{dataset:{path:'left.right',field:'value'},value:'2.50'});
 assert.equal(current().left.right.value,'2.50');assert(node('variable-equation').innerHTML.includes('2.50'));
 assert.equal(current().right.id,'annual.revenue','Editing a numerator must preserve the denominator');
 operate('undo');assert.equal(current().left.right.value,'1');operate('redo');assert.equal(current().left.right.value,'2.50');
 operate('remove');assert.deepEqual(current().left,{op:'parameter',id:'annual.operating_income'});
 operate('undo');assert.equal(current().left.right.value,'2.50');
 selectTerm('');operate('remove');assert.deepEqual(current(),{op:'parameter',id:''});
 operate('undo');assert.equal(current().left.right.value,'2.50');
 selectTerm('right');operate('source');parameter('annual.revenue');
 assert.equal(current().left.right.value,'2.50','Insert parameter targets the selected term');
 // Saved references insert at the selected position and keep exact dependencies.
 selectTerm('right');operate('source');
 event('variable-picker','click',{dataset:{library:exact.variable_id,revision:exact.revision},closest(){return this;}});await tick();await tick();
 assert.deepEqual(current().right,{op:'ref',...exact});assert.equal(current().left.right.value,'2.50');
 operate('undo');assert.equal(current().right.id,'annual.revenue');operate('redo');
 assert.equal(node('variable-check').dataset.state,'pending');
 await check();assert.equal(node('variable-check').dataset.state,'ready');assert(calls.at(-1).body.submitted.some(item=>item.variable_id===exact.variable_id&&item.revision===exact.revision));
 const expression={op:'div',left:{op:'mul',left:{op:'parameter',id:'annual.revenue'},right:{op:'annual',stat:'mean',count:3,parameter:'annual.operating_margin'}},right:{op:'parameter',id:'market.enterprise_value'}};
 // Advanced JSON remains local before validation, so even malformed numeric
 // fields must be escaped when the real visual renderer displays them.
 for(const malformed of [{op:'annual',stat:'mean',count:'" onfocus="unsafe',parameter:'annual.operating_margin'},{op:'lookback',months:'" onfocus="unsafe',arg:{op:'parameter',id:'annual.operating_margin'}}]){
  node('variable-json').value=JSON.stringify(malformed);await click('variable-accept-json');assert(node('variable-tree').innerHTML.includes('&quot; onfocus=&quot;unsafe'));assert(!node('variable-tree').innerHTML.includes('value="" onfocus="unsafe'));
 }
 node('variable-json').value=JSON.stringify(expression);await click('variable-accept-json');
 assert.deepEqual(JSON.parse(node('variable-json').value),expression);assert(node('variable-equation').innerHTML.includes('aria-label="Numerator"'));assert(node('variable-equation').innerHTML.includes('aria-label="Denominator"'));
 await check();assert.deepEqual(calls.at(-1).body.definition.expression,expression);assert.equal(node('variable-check').dataset.state,'ready');assert(node('variable-explanation').textContent.includes('Results shown as'));
 node('variable-display').value='multiple';event('variable-display','change');assert.equal(node('variable-check').dataset.state,'pending');assert(!node('variable-explanation').textContent.includes('Results shown as'));
 // A late validation cannot relabel new edits as checked.
 let release;validationWait=()=>new Promise(resolve=>release=resolve);flush();await tick();
 node('variable-name').value='Newer local name';event('variable-name','input');release();validationWait=null;await tick();assert.equal(node('variable-check').dataset.state,'pending');assert(!node('variable-explanation').textContent.includes('Results shown as'));
 node('variable-preview-symbols').value=Array(17).fill('A').join(',');await click('variable-preview');assert.equal(previewCount,0);assert(node('variable-errors').textContent.includes('1–16'));
 node('variable-preview-symbols').value='A0000,A0001,UNKNOWN';node('variable-preview-mode').value='historical';await click('variable-preview');await tick();
 assert.equal(previewCount,1);assert.equal(calls.at(-1).body.engine,'original');assert.equal(calls.at(-1).body.roots.length,3);assert.deepEqual(Object.keys(calls.at(-1).body.roots[0]).sort(),['date','mode','pool','symbol']);assert(node('variable-preview-result').innerHTML.includes('not complete-pool coverage'));
 // Exact library selection remains explicit. Save conflict preserves raw text.
 const pick={dataset:{library:exact.variable_id,revision:exact.revision},closest(){return this;}};
 event('variable-picker','click',pick);await tick();assert.equal(applied.length,0);assert.equal(node('variable-selected').textContent,'Saved in My variables');assert(node('variable-selected').title.includes(exact.revision));
 assert.equal(node('variable-save').textContent,'Save changes');assert.equal(node('variable-save-new').hidden,false);assert.equal(node('variable-favourite').hidden,false);
 assert.equal(pickerParameterCount(),ownerCatalog.parameters.length,'Loading v1 must refresh choices without a search');assert.equal(measureDisabled(),true);
 await click('variable-start-new');assert.equal(pickerParameterCount(),ownerCatalog.expanded_parameters.length,'New v3 must restore expanded choices');assert.equal(measureDisabled(),false);
 event('variable-picker','click',pick);await tick();assert.equal(pickerParameterCount(),ownerCatalog.parameters.length);assert.equal(measureDisabled(),true);

 node('variable-name').value='My unsaved name';event('variable-name','input');conflict=true;await click('variable-save');assert.equal(node('variable-name').value,'My unsaved name');assert(node('variable-errors').textContent.includes('Entry changed'));conflict=false;
 // An acknowledged save cannot overwrite edits made while publication waits.
 saveWait=()=>new Promise(resolve=>release=resolve);event('variable-save','click');await tick();
 node('variable-name').value='Edited while saving';event('variable-name','input');release();saveWait=null;await tick();await tick();assert.equal(node('variable-name').value,'Edited while saving');assert(node('variable-message').textContent.includes('newer local edits'));
 await click('variable-favourite');assert.equal(node('variable-favourite').textContent,'★ Remove from favourites');
 await click('variable-apply');assert.equal(applied.length,1);assert.equal(applied[0].source.revision,exact.revision);assert(!node('variable-dialog').open);assert.equal(document.activeElement.id,'opener');
 await run("VariableWorkspace.open('filter')");event('variable-dialog','cancel');assert.equal(document.activeElement.id,'opener');
 await run("VariableWorkspace.open('s1')");authoredWait=()=>new Promise(resolve=>release=resolve);event('variable-picker','click',pick);await tick();await click('variable-start-new');release();authoredWait=null;await tick();assert.equal(node('variable-selected').textContent,'New variable · not saved');
 // Ordinary edits also fence a pending replacement read, without closing or
 // replacing the editor session. Validate reads the retained local model.
 for(const field of ['name','expression']){
  node('variable-json').value=JSON.stringify({op:'constant',value:'7',unit:'scalar'});await click('variable-accept-json');
  authoredWait=()=>new Promise(resolve=>release=resolve);event('variable-picker','click',pick);await tick();
  if(field==='name'){node('variable-name').value='Name edited during read';event('variable-name','input');}
  else event('variable-tree','input',{dataset:{path:'',field:'value'},value:'9'});
  release();authoredWait=null;await tick();await check();
  if(field==='name')assert.equal(calls.at(-1).body.name,'Name edited during read');
  else assert.equal(calls.at(-1).body.definition.expression.value,'9');
  assert.equal(node('variable-selected').textContent,'New variable · not saved');
 }
 revision++;const builtin={dataset:{builtin:'filter:pe'},closest(){return this;}};event('variable-picker','click',builtin);await tick();assert.equal(applied.length,1);assert(node('variable-dialog').open);assert(node('variable-errors').textContent.includes('Stale picker apply'));
 // A restored exact source opens from checked captured content, with no archive.
 emptyLibrary=true;draftSources={s1:{kind:'formula',...exact}};draftDetached=[capture];
 const authoredBefore=calls.filter(call=>call.url.endsWith('/authored')).length;
 await run("VariableWorkspace.open('s1')");assert.equal(node('variable-name').value,'Original detached name');assert.equal(node('variable-selected').textContent,'Used by this strategy · not in My variables');assert(node('variable-favourite').disabled);assert.equal(calls.filter(call=>call.url.endsWith('/authored')).length,authoredBefore);
 assert.deepEqual(JSON.parse(node('variable-json').value),definition.expression);assert(!node('variable-upgrade').hidden);await click('variable-upgrade');assert(calls.at(-1).body.upgrade);assert(node('variable-upgrade').hidden);assert(node('variable-message').textContent.includes('User-defined references'));await click('variable-apply');assert.equal(applied.length,2);assert.equal(applied.at(-1).source.revision,exact.revision);
 // Inspection must be fenced before validation or capture can yield.
 draftSources={};draftDetached=[];
 await run("VariableWorkspace.open('s1')");await click('variable-coverage-scopes');
 const inspections=()=>calls.filter(call=>call.url==='/api/variable-coverage/inspect');
 for(const stage of ['validation','capture']){
  node('variable-coverage-scope').value='0';event('variable-coverage-scope','change');
  const before=inspections().length;
  const wait=()=>new Promise(resolve=>release=resolve);
  if(stage==='validation')validationWait=wait;else captureWait=wait;
  event('variable-coverage-inspect','click');await tick();
  node('variable-coverage-scope').value='1';event('variable-coverage-scope','change');
  release();validationWait=null;captureWait=null;await tick();await tick();
  assert.equal(inspections().length,before,'Scope change during '+stage+' must prevent inspection');
  assert.equal(node('variable-coverage-result').textContent,'');
 }
 // An uncooperative fetch can finish after abort. Its response must stay stale.
 coverageWait=()=>new Promise(resolve=>release=resolve);
 event('variable-coverage-inspect','click');await tick();const pendingInspection=inspections().at(-1);
 node('variable-coverage-scope').value='0';event('variable-coverage-scope','change');
 assert.equal(pendingInspection.signal.aborted,true);release();coverageWait=null;await tick();await tick();
 assert.equal(node('variable-coverage-result').textContent,'');
 await click('variable-coverage-inspect');await tick();assert(node('variable-coverage-result').textContent.includes('latest, 2015-01-05, cached'));
 // Rediscovery also supersedes the operation while formula validation waits.
 validationWait=()=>new Promise(resolve=>release=resolve);const beforeDiscovery=inspections().length;
 event('variable-coverage-inspect','click');await tick();await click('variable-coverage-scopes');release();validationWait=null;await tick();await tick();
 assert.equal(inspections().length,beforeDiscovery);
 assert.equal(node('variable-coverage-result').textContent,'Select a recorded scope to inspect.');
 // Applying while the source picker is pending applies the whole formula.
 const beforePendingApply=applied.length,pendingExpression=current();operate('source');await click('variable-apply');
 assert.equal(applied.length,beforePendingApply+1);assert.equal(applied.at(-1).role,'s1');
 assert.deepEqual(calls.at(-1).body.definition.expression,pendingExpression);
 // Insertion mode must not hide rejected Apply or change its destination.
 for(const destination of ['s1','filter','s2']){
  await run('VariableWorkspace.open('+JSON.stringify(destination)+')');
  const before=current(),count=applied.length;operate('source');
  assert.equal(node('variable-apply').textContent,describe(destination).use);assert.equal(node('variable-dialog-title').textContent,describe(destination).title);
  if(destination==='s1')revision++;else patchFailure='Finish editing the held draft first';
  await click('variable-apply');patchFailure=null;
  assert.equal(applied.length,count);assert(node('variable-dialog').open);
  assert(node('variable-errors').textContent.includes(destination==='s1'?'Stale picker apply':'Finish editing the held draft first'));
  assert(!node('variable-message').textContent.includes('Formula validated'));
  assert.deepEqual(current(),before);
  await click('variable-start-new');operate('source');parameter('annual.operating_margin');await click('variable-apply');
  if(destination==='s1')assert.equal(applied.length,count,'A stale session still cannot apply');
  else {assert.equal(applied.length,count+1);assert.equal(applied.at(-1).role,destination);}
 }
 // A cancelled source read cannot overwrite another selected term or report
 // its old failure into the current insertion. A current failure is visible.
 await run("VariableWorkspace.open('s1')");
 node('variable-json').value=JSON.stringify(expression);await click('variable-accept-json');
 for(const replacement of ['selection','insertion']){
  selectTerm('right');operate('source');const before=current();
  authoredWait=()=>new Promise(resolve=>release=resolve);event('variable-picker','click',pick);await tick();
  if(replacement==='selection')selectTerm('left');else {selectTerm('left');operate('source');authoredFailure=true;}
  release();authoredWait=null;await tick();await tick();authoredFailure=false;assert.deepEqual(current(),before);assert.equal(node('variable-errors').textContent,'');
 }
 authoredFailure=true;event('variable-picker','click',pick);await tick();authoredFailure=false;
 assert(node('variable-errors').textContent.includes('Cannot read authored fixture'));
 // Source selection during validation does not discard a valid Apply.
 let validationRelease;validationWait=()=>new Promise(resolve=>validationRelease=resolve);
 event('variable-apply','click');await tick();operate('source');validationRelease();validationWait=null;await tick();await tick();
 assert.equal(applied.at(-1).role,'s1');assert(!node('variable-dialog').open);
 // An unfinished formula says what is missing and asks the service nothing.
 await run("VariableWorkspace.open('s1')");await check();
 assert.equal(node('variable-check').dataset.state,'ready');assert.equal(node('variable-save').textContent,'Save to My variables');assert.equal(node('variable-save-new').hidden,true);assert.equal(node('variable-favourite').hidden,true);
 operate('div');assert.equal(node('variable-check').dataset.state,'incomplete');const beforeEmpty=calls.length;await check();assert.equal(calls.length,beforeEmpty);
 const emptyApply=applied.length;await click('variable-apply');assert.equal(applied.length,emptyApply);assert(node('variable-errors').textContent.includes('empty box'));
 parameter('annual.revenue');assert.equal(node('variable-check').dataset.state,'pending');
 // A closed dialog never checks in the background.
 event('variable-close','click');const beforeClosed=calls.length;await check();assert.equal(calls.length,beforeClosed);
 // List choices become exact checked sources for one filter row.
 if(!wire){
  emptyLibrary=false;const listed=await run('VariableWorkspace.sources()');
  assert.equal(listed.library.length,1);assert(listed.parameters.length>0);assert.equal(listed.parameters.length,77);assert.equal(listed.parameters.length,ownerCatalog.expanded_parameters.length);assert.equal(listed.measures.length,ownerCatalog.measures.length);
  const choose=async choice=>{context.choice=choice;await run("VariableWorkspace.useSource('s2',choice,draft.read().revision)");return applied.at(-1);};
  let chosen=await choose({kind:'parameter',id:'annual.revenue',label:'Revenue'});
  assert.equal(calls.at(-1).body.variable_id,'local:annual.revenue');assert.deepEqual(calls.at(-1).body.definition.output,{unit:'USD',display:'usd_million'});assert.deepEqual(calls.at(-1).body.definition.expression,{op:'parameter',id:'annual.revenue'});
  assert.equal(chosen.role,'s2');assert.equal(chosen.source.kind,'formula');assert.equal(chosen.source.variable_id,'local:annual.revenue');
  const measure=ownerCatalog.measures.find(item=>item.id==='gross_margin');
  chosen=await choose({kind:'measure',id:'gross_margin'});
  assert.equal(calls.at(-1).body.variable_id,measure.root.variable_id);assert.equal(calls.at(-1).body.name,measure.name);assert(!calls.at(-1).body.submitted.some(item=>item.variable_id===measure.root.variable_id));
  chosen=await choose({kind:'library',...exact});
  assert(calls.at(-2).url.endsWith('/authored'));assert.equal(calls.at(-1).body.variable_id,exact.variable_id);assert.equal(chosen.source.revision,exact.revision);
  context.choice={kind:'library',...exact};await run("VariableWorkspace.useSource('s1',choice,draft.read().revision)");
  assert.equal(applied.at(-1).role,'s1');assert.equal(applied.at(-1).source.revision,exact.revision);
  for(const parameter of listed.parameters.filter(item=>item.kind==='adapter')){
   context.choice={kind:'parameter',id:parameter.id};await run("VariableWorkspace.useSource('s1',choice,draft.read().revision)");
   assert.equal(applied.at(-1).role,'s1');assert.equal(calls.at(-1).body.definition.expression.id,parameter.id);
  }
  context.stale=context.draft.read().revision-1;
  await assert.rejects(run("VariableWorkspace.useSource(0,{kind:'parameter',id:'annual.revenue'},stale)"),/Stale picker apply/);
 }
 if(wire){
  useWire=true;draftSources={s1:wire.shared.editor_source};draftDetached=[wire.shared.editor_expected.capture];
  await run("VariableWorkspace.open('s1')");
  // Insert all eight references through the real picker handlers. Authored
  // snapshots are fixture bytes produced by the real owner, without an archive.
  const paths=['left.left.left','left.left.right','left.right.left','left.right.right','right.left.left','right.left.right','right.right.left','right.right.right'];
  for(let i=0;i<paths.length;i++){
   event('variable-tree','click',{dataset:{reference:paths[i]}});
   const source=wire.shared.references[i].source;event('variable-picker','click',{dataset:{library:source.variable_id,revision:source.revision},closest(){return this;}});await tick();await tick();
  }
  await check();const deadline=Date.now()+10000;while(!lastWireValidation&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,5));assert(lastWireValidation?.capture,JSON.stringify(lastWireValidation));assert.deepEqual(lastWireValidation,wire.shared.editor_expected);
  assert.equal(calls.at(-1).body.submitted.length,9);assert.equal(calls.at(-1).body.labels.length,9);assert(!('detached' in calls.at(-1).body));
 }
 assert(!calls.some(call=>call.url.includes('/api/backtest-')));assert.equal(errors.length,0);
 console.log('Passed: automatic checks, empty-term guidance, plain save state, direct list sources, editable equation composition, term selection, parameter insertion, exact decimal edits, removal, undo/redo, tree/JSON round trip, grouping, stale validation, exact picker, explicit bounded preview, optimistic conflict, save race, favourite, apply and keyboard focus; no jobs.');
})().catch(error=>{console.error(error);process.exitCode=1;});
