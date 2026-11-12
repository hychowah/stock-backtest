'use strict';
// The real typed-formula window with a controlled service. No copied editor logic.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ownerCatalog=JSON.parse(require('node:child_process').execFileSync('python3',['-c','import json; from backtest.application.variable_authoring import catalog; print(json.dumps(catalog()))'],{encoding:'utf8'}));
const nodes=new Map(),calls=[],applied=[];
function node(id){
 if(!nodes.has(id))nodes.set(id,{id,value:'',textContent:'',innerHTML:'',hidden:false,open:false,handlers:{},dataset:{},attributes:{},selectionStart:0,selectionEnd:0,
  addEventListener(k,f){this.handlers[k]=f;},setAttribute(k,v){this.attributes[k]=v;},removeAttribute(){},focus(){document.activeElement=this;},
  setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;},showModal(){this.open=true;},close(){this.open=false;}});
 return nodes.get(id);
}
const formula=node('variable-formula');
// Inserting text edits the focused field and fires input, as the browser does.
const document={getElementById:node,activeElement:node('opener'),execCommand(command,ui,text){
 const field=document.activeElement;assert.equal(command,'insertText');
 const start=field.selectionStart;field.value=field.value.slice(0,start)+text+field.value.slice(field.selectionEnd);field.selectionStart=field.selectionEnd=start+text.length;
 field.handlers.input({target:field});return true;}};
const exact={variable_id:'variable:one',revision:'sha256:'+'1'.repeat(64)};
const saved={...exact,name:'debt/EV',text:'debt/EV',version:1,favourite:false,deleted:false};
const capture={program:{bundle:{definitions:[{...exact,definition:{}}]},definitions:[{...exact,unit:'scalar',display:'percent'}]},presentation:[{...exact,name:saved.name}]};
const openedText='Total debt / Enterprise value';
let revision=3,openedName='debt/EV',validationWait=null,useWire=false,lastWireValidation=null;
const wireOrigin=process.argv[2]==='--wire'?process.argv[3]:null,wire=wireOrigin?JSON.parse(fs.readFileSync(0,'utf8')):null;
const timers=new Map();let timerId=0;
const response=(value,status=200)=>({ok:status<400,status,json:async()=>structuredClone(value)});
function checked(body){
 const text=body.formula.text,unchanged=body.base&&text.replace(/\s+/g,' ').trim()===openedText;
 const root={variable_id:body.variable_id,revision:unchanged?body.base.root.revision:'sha256:'+String(text.length).padStart(64,'0')};
 return {root,output:{unit:'scalar',display:body.formula.display||'percent'},requirements:[],capture,authored:[{...root,definition:{expression:text}}],
  picture:{op:'/',top:{name:'Total debt'},bottom:{name:'Enterprise value'},positive:false},name:body.name||text};
}
const context=vm.createContext({console,document,setTimeout:callback=>{timers.set(++timerId,callback);return timerId;},clearTimeout:id=>timers.delete(id),crypto:require('node:crypto').webcrypto,Uint8Array,fetch:async(url,options={})=>{
 const body=options.body?JSON.parse(options.body):null;calls.push({url,body});
 if(useWire){
  if(options.body)assert(Buffer.byteLength(options.body)<=256*1024);
  if(url==='/api/variables')return response({entries:[]});
  const reply=await fetch(wireOrigin+url,options),value=await reply.json();if(url.endsWith('/validate'))lastWireValidation=value;return response(value,reply.status);
 }
 if(url.endsWith('/catalog'))return response(ownerCatalog);
 if(url==='/api/variables')return response(body?{...saved,variable_id:'variable:new',name:body.name}:{entries:[saved]});
 if(url.endsWith('/detached')){assert.deepEqual(body.root,exact);return response({selected:exact,name:openedName,authored:[{...exact,definition:{output:{unit:'scalar',display:'multiple'}}}],capture,text:openedText});}
 if(url.endsWith('/authored'))return response({entry:saved,selected:exact,authored:[{...exact,definition:{}}],capture});
 if(url.endsWith('/validate')){
  if(validationWait)await validationWait();
  const at=body.formula.text.indexOf('Revnue');
  if(at>=0)return response({error:'“Revnue” is not an input or a saved variable.',errors:[{start:at,end:at+6,code:'UNKNOWN_NAME',message:'“Revnue” is not an input or a saved variable.',suggestions:[{text:'Revenue',label:'Revenue'}]}]},400);
  return response(checked(body));
 }
 if(url.endsWith('/save'))return response({...saved,name:body.name,version:2});
 if(url.endsWith('/favourite'))return response({...saved,version:2,favourite:body.favourite});
 if(url.endsWith('/delete'))return response({...saved,version:3,deleted:true});
 throw Error('Unexpected route '+url);
}});
vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../website/browser/variable-workspace.js'),'utf8'),context);
const run=code=>vm.runInContext(code,context),tick=async()=>{for(let i=0;i<4;i++)await new Promise(resolve=>setImmediate(resolve));};
const click=async(id,target=node(id))=>{node(id).handlers.click({target:{closest:()=>target,...target}});await tick();};
// Run the debounced automatic check, as a pause after typing would.
const pause=async()=>{for(const [id,callback] of [...timers]){timers.delete(id);callback();}await tick();};
const type=text=>{formula.value=text;formula.selectionStart=formula.selectionEnd=text.length;formula.handlers.input({target:formula});};
const press=key=>{let prevented=false;formula.handlers.keydown({key,preventDefault(){prevented=true;}});return prevented;};
const shown=()=>node('variable-suggestions').hidden?'':node('variable-suggestions').innerHTML;
const checkLine=()=>node('variable-check-text').textContent;
const validations=()=>calls.filter(call=>call.url.endsWith('/validate'));
const describe=role=>({s1:{title:'Step 1 · Rank',use:'Update step 1'},filter:{title:'New filter',use:'Add as filter'}}[role]);
context.draft={read:()=>({revision}),describe,patch:(change,expected)=>{assert.equal(expected,revision,'Stale apply');applied.push(structuredClone(change));revision++;}};
run("VariableWorkspace.init({draft})");
(async()=>{
 if(!wire){
  // A new variable starts empty and asks the service nothing until typed.
  await run("VariableWorkspace.open('filter')");
  assert(node('variable-dialog').open);assert.equal(document.activeElement.id,'variable-formula');
  assert.equal(formula.value,'');assert.equal(node('variable-name').value,'');assert.equal(checkLine(),'Type a formula');assert.equal(validations().length,0);
  assert.equal(node('variable-apply').textContent,'Add as filter');assert.equal(node('variable-dialog-title').textContent,'New filter');
  assert(node('variable-favourite').hidden);assert(node('variable-delete').hidden);assert(node('variable-save-new').hidden);
  // No built-ins: the window lists inputs and saved variables only.
  const list=node('variable-input-list').innerHTML;
  assert(list.includes('>Enterprise value<'));assert(list.includes('>debt/EV<'));assert(!list.includes('P/S 3-year average'));assert(!/data-builtin|filter:/.test(list));
  // Suggestions follow the partial name at the caret; Enter inserts the spelling.
  type('Total debt / Enter');assert(shown().includes('<span>Enterprise value</span>'));assert.equal(checkLine(),'Checking…');
  assert(press('Enter'));assert.equal(formula.value,'Total debt / Enterprise value');assert.equal(shown(),'');
  assert(press('Enter'),'Enter never adds a line');assert.equal(formula.value,'Total debt / Enterprise value');
  // A linked step's own label shows beside its plain name; step-only names never show.
  type('Net mar');assert(shown().includes('<span>Net margin</span><small>Net profit margin (%)</small>'));
  type('P/S 3');assert.equal(shown(),'');
  type('Total debt / Enterprise value');
  // The automatic check runs after the pause and shows the result unit and display.
  await pause();assert.equal(validations().length,1);
  assert.deepEqual(validations()[0].body.formula,{text:'Total debt / Enterprise value',display:null});assert(!('base' in validations()[0].body));
  assert.equal(checkLine(),'✓ Ready · Result: ratio');assert.equal(node('variable-display-label').hidden,false);assert.equal(node('variable-display').value,'percent');
  assert(node('variable-picture').innerHTML.includes('variable-picture-fraction'));
  // A late reply for older text never relabels newer text.
  let release;validationWait=()=>new Promise(resolve=>release=resolve);type('Total debt / Enterprise value * 2');await pause();
  type('Total debt * 3');release();validationWait=null;await tick();assert.equal(checkLine(),'Checking…');
  // A saved variable is suggested and inserted by its typed name.
  type('Total debt * deb');assert(shown().includes('<span>debt/EV</span><small>My variable</small>'));
  press('Escape');assert.equal(shown(),'');type('Total debt * deb');
  while(!/aria-selected="true"><span>debt\/EV/.test(shown()))press('ArrowDown');
  press('Tab');assert.equal(formula.value,'Total debt * debt/EV');
  // An error names its bad part; its suggestion replaces exactly that span.
  type('Revnue / Total assets');await pause();assert(checkLine().startsWith('✗ “Revnue”'));assert.equal(node('variable-picture').innerHTML,'');
  assert.equal(formula.selectionStart,formula.value.length,'The check never moves the caret');
  await click('variable-fixes',{dataset:{fix:'0'}});assert.equal(formula.value,'Revenue / Total assets');assert.equal(checkLine(),'Checking…');
  // Clicking an input inserts it at the caret.
  formula.selectionStart=formula.selectionEnd=7;await click('variable-input-list',{dataset:{insert:' * Gross margin'}});assert.equal(formula.value,'Revenue * Gross margin / Total assets');
  // Save keeps a revision; the window then offers Favourite and Delete.
  node('variable-name').value='Margin mix';node('variable-name').handlers.input();
  await click('variable-save');const created=calls.find(call=>call.url==='/api/variables'&&call.body);
  assert.equal(created.body.name,'Margin mix');assert.equal(created.body.definition.expression,'Revenue * Gross margin / Total assets');
  assert.equal(node('variable-favourite').hidden,false);assert.equal(node('variable-delete').hidden,false);assert.equal(node('variable-save').textContent,'Save changes');
  await click('variable-favourite');assert.equal(node('variable-favourite').textContent,'★ Favourite');
  await click('variable-delete');assert(node('variable-favourite').hidden);assert.equal(node('variable-save').textContent,'Save to My variables');
  // Use checks the current text and applies it to the step, then closes.
  await click('variable-apply');assert.equal(applied.length,1);assert.equal(applied[0].role,'filter');assert.equal(applied[0].source.variable_id,'variable:new');
  assert(!node('variable-dialog').open);assert.equal(document.activeElement.id,'opener');
  // Edit formula opens the step's capture; using it unchanged keeps its revision.
  context.base={root:exact,capture};
  await run("VariableWorkspace.open('s1',base)");assert.equal(formula.value,openedText);assert.equal(node('variable-name').value,'debt/EV');
  assert.deepEqual(validations().at(-1).body.base,{root:exact,capture});assert.equal(validations().at(-1).body.formula.display,'multiple');
  assert.equal(node('variable-apply').textContent,'Update step 1');
  await click('variable-apply');assert.deepEqual(applied.at(-1).source,{kind:'formula',...exact});
  // Create on a formula step opens an empty formula.
  const detachedCount=calls.filter(call=>call.url.endsWith('/detached')).length;
  await run("VariableWorkspace.open('s1',null)");assert.equal(formula.value,'');assert.equal(node('variable-name').value,'');
  assert.equal(calls.filter(call=>call.url.endsWith('/detached')).length,detachedCount);assert.equal(node('variable-apply').textContent,'Update step 1');
  // A name that only repeats the formula is the automatic one: the field stays empty after the check.
  openedName=openedText;await run("VariableWorkspace.open('s1',base)");openedName='debt/EV';
  assert.equal(checkLine(),'✓ Ready · Result: ratio');assert.equal(node('variable-name').value,'');assert.equal(validations().at(-1).body.name,'');
  // Close discards edits and never checks in the background.
  await run("VariableWorkspace.open('s1',base)");type('Total debt');await click('variable-close');const before=calls.length;await pause();assert.equal(calls.length,before);assert.equal(applied.length,2);
  // Step list choices: formula-only inputs and saved variables.
  const listed=await run('VariableWorkspace.sources()');
  assert(listed.inputs.some(item=>item.name==='Revenue'));assert(!listed.inputs.some(item=>item.name==='Enterprise value'||item.name==='P/S'));
  context.choice={kind:'input',id:'annual.revenue'};await run("VariableWorkspace.useSource('s1',choice,draft.read().revision)");
  assert.deepEqual(validations().at(-1).body,{formula:{text:'Revenue',display:'usd_million'},variable_id:'local:annual.revenue',name:'Revenue'});
  context.choice={kind:'library',...exact};const count=validations().length;await run("VariableWorkspace.useSource('s1',choice,draft.read().revision)");
  assert.equal(validations().length,count);assert.deepEqual(applied.at(-1).source,{kind:'formula',...exact});assert.deepEqual(applied.at(-1).capture,capture);
  context.stale=revision-1;await assert.rejects(run("VariableWorkspace.useSource('s1',choice,stale)"),/Stale apply/);
 }else{
  // Over the wire: a large step capture opens as text and is used unchanged.
  useWire=true;const {kind,...root}=wire.shared.editor_source;context.base={root,capture:wire.shared.editor_capture};
  await run("VariableWorkspace.open('s1',base)");
  assert(formula.value.length>0);assert.deepEqual(lastWireValidation.root,{variable_id:wire.shared.editor_source.variable_id,revision:wire.shared.editor_source.revision});
  assert.deepEqual(lastWireValidation.capture,wire.shared.editor_capture);
  await click('variable-apply');assert.deepEqual(applied.at(-1).source,wire.shared.editor_source);
 }
 assert(!calls.some(call=>call.url.includes('/api/backtest-')));
 console.log('Passed: empty start, suggestions and saved names by typed spelling, linked step labels, no built-ins, automatic and stale checks, error suggestion spans, input insertion, save, favourite, delete, use, unchanged reopen, empty create on a formula step, no automatic name, close and list sources; no jobs.');
})().catch(error=>{console.error(error);process.exitCode=1;});
