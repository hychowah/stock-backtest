/* One expression-tree editor and exact-source picker. Draft and transport
   owners retain strategy sessions and retry identity. This module never runs. */
const VariableWorkspace=(()=>{
  const copy=v=>JSON.parse(JSON.stringify(v)),node=id=>document.getElementById(id);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const exact=s=>s.variable_id+'@'+s.revision;
  function content(...groups){
    const entries=new Map(),labels=new Map(),key=value=>JSON.stringify([value.variable_id,value.revision]);
    for(const group of groups){
      for(const entry of group?.submitted||[])entries.set(key(entry),entry);
      for(const label of group?.labels||[])labels.set(key(label),{variable_id:label.variable_id,revision:label.revision,name:label.name});
    }
    // These are opaque owner-produced raw projections. Decimal conversion,
    // reachability, identities and validation remain with the definition owner.
    return copy({submitted:[...entries.values()],labels:[...labels].filter(([id])=>entries.has(id)).map(([,label])=>label)});
  }
  const dependencies=(snapshot,root)=>content({submitted:snapshot.authored.filter(item=>exact(item)!==exact(root)),labels:snapshot.capture.presentation});
  const envelope=expression=>({format:'variable-definition',version:1,parameter_catalog:'financial-parameters/1',temporal_policy:'annual-lag90/1',expression,output:{unit:'scalar',display:'percent'}});
  const defaultExpression=()=>({op:'parameter',id:'annual.operating_margin'});
  const operators=['parameter','constant','add','sub','mul','div','neg','annual','at','lookback','ref'];
  const opNames={parameter:'Parameter',constant:'Constant',add:'Add (+)',sub:'Subtract (−)',mul:'Multiply (×)',div:'Divide (÷)',neg:'Negate (−)',annual:'Annual statistic',at:'Value at date',lookback:'Value months earlier',ref:'Exact saved reference'};
  let callbacks={},catalog=null,entries=[],editor=null,role='ranking',draftRevision=0,generation=0,mutation=0,listRequest=0,validation=0,preview=0,editRevision=0,returnFocus=null,referenceParent=null;
  function message(text,error=false){node('variable-message').textContent=text;node('variable-message').className=error?'backtest-failed':'hint';}
  async function request(path,body){
    const response=await fetch('/api/variables'+path,{cache:'no-store',...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
    const value=await response.json();if(!response.ok){const error=Object.assign(Error(value.error||'Variable operation failed.'),value,{status:response.status});throw error;}return value;
  }
  function error(error){node('variable-errors').textContent=(error.errors||[{path:error.path||'',message:error.message}]).map(issue=>(issue.path?issue.path+': ':'')+issue.message).join('\n');message(error.message,true);}
  function invalidate(){validation++;preview++;editRevision++;if(editor){editor.checked=null;node('variable-explanation').textContent=describe(editor.definition.expression)+' · Changes need validation.';}node('variable-errors').textContent='';node('variable-preview-result').textContent='';}
  function describe(expression){
    if(!expression||typeof expression!=='object')return 'Invalid expression';
    const op=expression.op;
    if(op==='parameter')return catalog?.parameters.find(p=>p.id===expression.id)?.description||expression.id;
    if(op==='constant')return expression.value+' '+expression.unit;
    if(op==='ref')return 'Reference '+expression.variable_id+' @ '+expression.revision;
    if(op==='annual')return expression.stat+' of '+expression.count+' consecutive annual '+expression.parameter+' observations';
    if(op==='at')return '('+describe(expression.arg)+') available at '+expression.date;
    if(op==='lookback')return '('+describe(expression.arg)+') available '+expression.months+' calendar months earlier';
    if(op==='neg')return '−('+describe(expression.arg)+')';
    return '('+describe(expression.left)+' '+({add:'+',sub:'−',mul:'×',div:'÷'}[op]||op)+' '+describe(expression.right)+')';
  }
  function getAt(path){return path?path.split('.').reduce((v,key)=>v[key],editor.definition.expression):editor.definition.expression;}
  function replaceAt(path,value){if(!path)editor.definition.expression=value;else{const parts=path.split('.'),key=parts.pop();getAt(parts.join('.'))[key]=value;}}
  function fresh(op,old){
    if(op==='parameter')return defaultExpression();
    if(op==='constant')return {op,value:'1',unit:'scalar'};
    if(op==='annual')return {op,stat:'mean',count:3,parameter:'annual.operating_margin'};
    if(op==='ref')return {op,variable_id:'',revision:''};
    if(op==='at')return {op,date:node('variable-preview-date').value||'2025-01-02',arg:old||defaultExpression()};
    if(op==='lookback')return {op,months:12,arg:old||defaultExpression()};
    if(op==='neg')return {op,arg:old||defaultExpression()};
    return {op,left:old||defaultExpression(),right:{op:'constant',value:'1',unit:'scalar'}};
  }
  function tree(expression,path='',depth=0){
    if(depth>32)return '<p>Expression is too deep to edit. Use Advanced JSON to reduce its depth.</p>';
    const op=expression.op,field=(key,label,html)=>`<label>${label} ${html.replace('data-field=',`data-path="${esc(path)}" data-field=`)}</label>`;
    let html=`<fieldset data-node="${esc(path)}"><legend>${path?esc(path):'Expression group'}</legend><label>Operation <select data-path="${esc(path)}" data-op>${operators.map(value=>`<option value="${value}" ${op===value?'selected':''}>${opNames[value]}</option>`).join('')}</select></label>`;
    if(op==='parameter')html+=field('id','Financial parameter',`<select data-field="id">${(catalog?.parameters||[]).map(p=>`<option value="${p.id}" ${expression.id===p.id?'selected':''}>${esc(p.description)} (${esc(p.unit)})</option>`).join('')}</select>`);
    if(op==='constant')html+=field('value','Exact decimal',`<input data-field="value" inputmode="decimal" value="${esc(expression.value)}">`)+field('unit','Canonical unit',`<select data-field="unit">${['scalar','USD','USD/share'].map(v=>`<option ${v===expression.unit?'selected':''}>${v}</option>`).join('')}</select>`);
    if(op==='annual')html+=field('stat','Statistic',`<select data-field="stat">${['mean','min','max'].map(v=>`<option ${expression.stat===v?'selected':''}>${v}</option>`).join('')}</select>`)+field('count','Consecutive fiscal years',`<input data-field="count" type="number" min="1" max="10" value="${esc(expression.count)}">`)+field('parameter','Annual parameter',`<select data-field="parameter">${(catalog?.parameters||[]).filter(p=>p.id.startsWith('annual.')).map(p=>`<option value="${p.id}" ${expression.parameter===p.id?'selected':''}>${esc(p.description)}</option>`).join('')}</select>`);
    if(op==='at')html+=field('date','Observation date',`<input data-field="date" type="date" value="${esc(expression.date)}">`);
    if(op==='lookback')html+=field('months','Calendar months earlier',`<input data-field="months" type="number" min="1" max="120" value="${esc(expression.months)}">`);
    if(op==='ref')html+=`<p>${esc(expression.variable_id)} @ ${esc(expression.revision)}</p><button type="button" data-reference="${esc(path)}">Choose exact reference</button>`;
    for(const key of ['left','right','arg'])if(expression[key])html+=`<div class="variable-node-children"><strong>${{left:op==='div'?'Numerator':'Left term',right:op==='div'?'Denominator':'Right term',arg:'Grouped expression'}[key]}</strong>${tree(expression[key],path?path+'.'+key:key,depth+1)}</div>`;
    return html+'</fieldset>';
  }
  function renderEditor(){
    node('variable-name').value=editor.name;node('variable-output-unit').value=editor.definition.output.unit;node('variable-display').value=editor.definition.output.display;
    node('variable-tree').innerHTML=tree(editor.definition.expression);node('variable-json').value=JSON.stringify(editor.definition.expression,null,2);
    node('variable-explanation').textContent=describe(editor.definition.expression);
    node('variable-selected').textContent=editor.entry?editor.entry.name+' · selected '+editor.variable_id+' @ '+editor.selectedRevision+' · current entry version '+editor.entry.version+(editor.entry.deleted?' · deleted archive':''):editor.detachedSelection?'Captured exact selection · '+editor.variable_id+' @ '+editor.selectedRevision+' · archive lookup is not required':'Unsaved local variable · '+editor.variable_id;
    node('variable-favourite').disabled=!editor.entry||editor.entry.deleted;node('variable-delete').disabled=!editor.entry||editor.entry.deleted;
    node('variable-favourite').textContent=editor.entry?.favourite?'Remove favourite':'Favourite';
    node('variable-apply').textContent=typeof role==='object'?'Apply to reference':role==='ranking'?'Apply to ranking':'Apply to filter';
  }
  function startNew(keepGeneration=false){if(!keepGeneration)generation++;if(referenceParent)role=referenceParent.role;referenceParent=null;invalidate();editor={name:'Operating margin',variable_id:'local:'+Array.from(crypto.getRandomValues(new Uint8Array(8)),b=>b.toString(16).padStart(2,'0')).join(''),definition:envelope(defaultExpression()),content:content()};renderEditor();}
  async function refresh(){
    const requestNumber=++listRequest,version=mutation,local=generation;
    const value=await request('');if(requestNumber!==listRequest||version!==mutation||local!==generation)return;
    entries=value.entries;
    if(editor?.detachedSelection){editor.entry=entries.find(entry=>entry.variable_id===editor.variable_id);renderEditor();}
    renderPicker();
  }
  function renderPicker(){
    const query=node('variable-search').value.trim().toLowerCase();
    const matches=value=>!query||JSON.stringify(value).toLowerCase().includes(query);
    const group=(name,rows)=>'<h3>'+name+'</h3>'+rows.join('');
    const item=entry=>`<button type="button" data-library="${esc(entry.variable_id)}" data-revision="${esc(entry.revision)}">${esc(entry.name)}${entry.favourite?' ★':''}<small>${esc(entry.revision)}</small></button>`;
    node('variable-picker').innerHTML=group('Favourites',entries.filter(e=>e.favourite&&matches(e)).map(item))+group('My variables',entries.filter(matches).map(item))+group('Built-ins',(typeof role==='object'?[]:catalog?.builtins||[]).filter(matches).map(e=>`<button type="button" data-builtin="${esc(e.id)}">${esc(e.label)}<small>${esc(e.unit)} · ${esc(e.display)}</small></button>`));
  }
  async function open(selectedRole='ranking'){
    const draft=callbacks.draft.read(),selection=draft.settings?.strategy?.selection;
    const selected=selectedRole==='ranking'?selection?.ranking.source:typeof selectedRole==='number'?selection?.conditions[selectedRole]?.source:null;
    const captured=selected?.kind==='formula'?[draft.settings?.strategy?.variables,...(draft.detached||[])].find(capture=>capture?.program.bundle.definitions.some(item=>item.variable_id===selected.variable_id&&item.revision===selected.revision)):null;
    role=selectedRole;draftRevision=draft.revision;returnFocus=document.activeElement;generation++;const local=generation;
    node('variable-dialog').showModal?.();if(!node('variable-dialog').open)node('variable-dialog').setAttribute('open','');
    startNew(true);message('Loading saved variables and supported parameters…');
    const openedEdit=editRevision;
    try{
      catalog??=await request('/catalog');if(local!==generation)return;renderEditor();
      if(captured&&openedEdit===editRevision){
        const snapshot=await request('/detached',{root:{variable_id:selected.variable_id,revision:selected.revision},capture:copy(captured)});
        if(local!==generation)return;
        if(openedEdit===editRevision){
          const definition=snapshot.authored.find(item=>item.variable_id===selected.variable_id&&item.revision===selected.revision).definition;
          editor={name:snapshot.name,variable_id:selected.variable_id,selectedRevision:selected.revision,definition:copy(definition),content:dependencies(snapshot,selected),detachedSelection:true};invalidate();renderEditor();
        }
      }
      await refresh();if(local===generation){message(editor.detachedSelection?'The selected captured revision is open. Editing and Apply need no archive. Save uses the available library and may report missing dependencies.':'Choose an exact revision, or edit a new variable. Nothing runs until you explicitly submit.');node('variable-search').focus();}
    }
    catch(failure){if(local===generation)error(failure);}
  }
  function close(){generation++;invalidate();node('variable-dialog').close?.();node('variable-dialog').removeAttribute('open');returnFocus?.focus?.();}
  async function loadExact(variable_id,revision){
    const local=++generation;invalidate();const edited=editRevision;message('Reading exact authored content…');
    try{
      const snapshot=await request('/authored',{variable_id,revision});if(local!==generation||edited!==editRevision)return;
      if(typeof role==='object'&&referenceParent){const selection=role;editor=referenceParent.editor;role=referenceParent.role;referenceParent=null;replaceAt(selection.path,{op:'ref',variable_id,revision});editor.content=content(editor.content,{submitted:snapshot.authored,labels:snapshot.capture.presentation});invalidate();renderEditor();message('Exact reference inserted.');return;}
      const definition=snapshot.authored.find(item=>item.variable_id===variable_id&&item.revision===revision).definition;
      editor={name:snapshot.entry.name,variable_id,selectedRevision:revision,definition:copy(definition),entry:snapshot.entry,content:dependencies(snapshot,{variable_id,revision}),checked:null};renderEditor();message('Exact authored revision loaded. Refreshing the library never changes this selection.');
    }catch(failure){if(local===generation&&edited===editRevision)error(failure);}
  }
  function editorRequest(){return {definition:copy(editor.definition),variable_id:editor.variable_id,name:node('variable-name').value.trim()||editor.variable_id,...content(editor.content)};}
  async function validate(){
    const local=generation,number=++validation,input=editorRequest();
    const checked=await request('/validate',input);if(local!==generation||number!==validation)return null;
    editor.checked=checked;editor.name=input.name;
    editor.content=dependencies(checked,checked.root);
    node('variable-errors').textContent='';node('variable-explanation').textContent=describe(input.definition.expression)+' · Output '+checked.output.unit+' / '+checked.output.display+' · '+checked.requirements.map(r=>r.parameter+' ('+r.count+' annual observations)').join(', ')+' · '+checked.root.revision;
    message('Formula validated. Required input support does not guarantee sample availability.');return checked;
  }
  async function apply(){
    const local=generation,checked=await validate();if(!checked||local!==generation)return;
    if(typeof role==='object'){
      replaceAt(role.path,{op:'ref',...checked.root});editor.content=content(editor.content,{submitted:checked.authored,labels:checked.capture.presentation});invalidate();renderEditor();return;
    }
    callbacks.draft.patch({role,source:{kind:'formula',...checked.root},capture:checked.capture,authored:checked.authored},draftRevision);close();
  }
  async function save(asNew=false){
    const local=generation,input=editorRequest(),checked=await validate();if(!checked||local!==generation)return;
    const edited=editRevision;
    const existing=editor.entry&&!asNew&&!editor.entry.deleted;
    mutation++;const saved=await request(existing?'/'+editor.entry.variable_id+'/save':'',{name:input.name,definition:input.definition,...(existing?{version:editor.entry.version}:{})});mutation++;
    // A committed mutation remains successful even if the list refresh fails.
    if(local!==generation)return;
    editor.entry=saved;editor.variable_id=saved.variable_id;editor.selectedRevision=saved.revision;editor.checked=null;
    if(edited===editRevision){editor.name=saved.name;renderEditor();message('Variable saved. Apply explicitly to change the strategy.');}
    else message('The submitted version was saved. Your newer local edits are kept and need another save.');
    try{await refresh();}catch(_){message('Variable saved. The list could not refresh; use Refresh variables to retry.');}
  }
  async function metadata(action){
    if(!editor.entry)return;const local=generation,entry=copy(editor.entry);mutation++;
    const result=await request('/'+entry.variable_id+'/'+action,{version:entry.version,...(action==='favourite'?{favourite:!entry.favourite}:{})});mutation++;
    if(local!==generation)return;editor.entry=result;renderEditor();message(action==='delete'?'Variable deleted from the active library. Captured strategies keep their original content.':'Favourite updated. The strategy did not change.');
    try{await refresh();}catch(_){message('Change saved. The list could not refresh; use Refresh variables.');}
  }
  async function previewSamples(){
    const local=generation,checked=await validate();if(!checked||local!==generation)return;
    const symbols=node('variable-preview-symbols').value.split(',').map(s=>s.trim()).filter(Boolean);
    if(symbols.length<1||symbols.length>16)throw Error('Preview needs 1–16 explicit company symbols.');
    const number=++preview,rootDate=node('variable-preview-date').value,mode=node('variable-preview-mode').value;
    const prepared=await request('/capture',{intent:{format:'strategy-intent',version:1,selection:{ranking:{source:{kind:'formula',...checked.root},direction:'highest'},rank_from:1,rank_to:50,selection_order:'filter_first',conditions:[]},pool:callbacks.pool?.()||'legacy',bounds:{}},detached:[checked.capture]});
    if(local!==generation||number!==preview)return;
    const roots=symbols.map((symbol,index)=>({symbol,pool:callbacks.pool?.()||'legacy',mode,date:rootDate}));
    const response=await fetch('/api/variable-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({strategy:prepared.strategy,roots,engine:'original'})});const value=await response.json();if(!response.ok)throw Object.assign(Error(value.error),value);
    if(local!==generation||number!==preview)return;
    node('variable-preview-result').innerHTML=VariableEvidence.preview(value);
  }
  function attempt(work){const local=generation;Promise.resolve().then(work).catch(failure=>{if(local===generation)error(failure);});}
  function init(options){
    callbacks=options;node('variable-preview-date').value=options.asof;
    const controls=document.querySelector('.variable-controls');
    controls.addEventListener('input',event=>event.stopPropagation());controls.addEventListener('change',event=>event.stopPropagation());
    node('variable-rank').addEventListener('click',()=>attempt(()=>open('ranking')));node('variable-new').addEventListener('click',()=>attempt(()=>open('ranking')));node('variable-condition').addEventListener('click',()=>attempt(()=>open('condition')));
    node('variable-legacy').addEventListener('click',()=>callbacks.draft.patch({legacy:true},callbacks.draft.read().revision));
    node('variable-direction').addEventListener('change',()=>callbacks.draft.patch({direction:node('variable-direction').value},callbacks.draft.read().revision));
    node('variable-close').addEventListener('click',close);node('variable-dialog').addEventListener('cancel',()=>{generation++;invalidate();returnFocus?.focus?.();});
    node('variable-search').addEventListener('input',renderPicker);node('variable-refresh').addEventListener('click',()=>attempt(refresh));node('variable-start-new').addEventListener('click',()=>startNew());
    node('variable-edit-selected').addEventListener('click',()=>{if(editor.detachedSelection)message('The exact captured revision is already open for editing.');else if(editor.entry)attempt(()=>loadExact(editor.variable_id,editor.selectedRevision));});
    node('variable-picker').addEventListener('click',event=>{const target=event.target.closest('button');if(!target)return;if(target.dataset.library)attempt(()=>loadExact(target.dataset.library,target.dataset.revision));else if(target.dataset.builtin)attempt(()=>{callbacks.draft.patch({role,source:{kind:'builtin',id:target.dataset.builtin}},draftRevision);close();});});
    node('variable-tree').addEventListener('change',event=>{const target=event.target;if(target.dataset.op!==undefined){replaceAt(target.dataset.path,fresh(target.value,getAt(target.dataset.path)));invalidate();renderEditor();}else if(target.dataset.field){getAt(target.dataset.path)[target.dataset.field]=['count','months'].includes(target.dataset.field)?Number(target.value):target.value;invalidate();node('variable-json').value=JSON.stringify(editor.definition.expression,null,2);node('variable-explanation').textContent=describe(editor.definition.expression);}});
    node('variable-tree').addEventListener('input',event=>{const target=event.target;if(target.dataset.field){getAt(target.dataset.path)[target.dataset.field]=['count','months'].includes(target.dataset.field)?Number(target.value):target.value;invalidate();}});
    node('variable-tree').addEventListener('click',event=>{if(event.target.dataset.reference!==undefined){const path=event.target.dataset.reference;const candidates=entries.map(e=>e.name+' '+e.revision).join('\n');message('Choose a saved variable in the picker to insert its exact reference. '+candidates);referenceParent={editor,role};role={path};renderPicker();node('variable-search').focus();}});
    node('variable-name').addEventListener('input',()=>{invalidate();editor.name=node('variable-name').value;});
    for(const [id,key] of [['variable-output-unit','unit'],['variable-display','display']])node(id).addEventListener('change',()=>{editor.definition.output[key]=node(id).value;invalidate();});
    node('variable-accept-json').addEventListener('click',()=>attempt(()=>{const parsed=JSON.parse(node('variable-json').value);if(!parsed||typeof parsed!=='object'||Array.isArray(parsed))throw Error('Expression JSON must be an object.');editor.definition.expression=parsed;invalidate();renderEditor();}));
    node('variable-validate').addEventListener('click',()=>attempt(validate));node('variable-apply').addEventListener('click',()=>attempt(apply));node('variable-save').addEventListener('click',()=>attempt(()=>save(false)));node('variable-save-new').addEventListener('click',()=>attempt(()=>save(true)));node('variable-favourite').addEventListener('click',()=>attempt(()=>metadata('favourite')));node('variable-delete').addEventListener('click',()=>attempt(()=>metadata('delete')));node('variable-preview').addEventListener('click',()=>attempt(previewSamples));
  }
  return {init,open,describe,request,copy,exact,content,builtin:id=>copy(catalog?.builtins.find(item=>item.id===id)??null)};
})();
if(typeof module!=='undefined')module.exports=VariableWorkspace;
