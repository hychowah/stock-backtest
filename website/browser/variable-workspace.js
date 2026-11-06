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
  const envelope=expression=>({format:'variable-definition',version:3,parameter_catalog:'financial-parameters/3',temporal_policy:'annual-lag90/1',expression,output:{unit:'scalar',display:'percent'}});
  const defaultExpression=()=>({op:'parameter',id:'annual.operating_margin'});
  const displayNames={number:'Number',multiple:'Multiple (×)',percent:'Percent (%)',percentage_points:'Percentage points',usd:'US dollars',usd_million:'$ million',usd_per_share:'$ per share',shares:'Shares'};
  const displayName=value=>displayNames[value]||value;
  // Catalog descriptions can append caveats after a semicolon.
  const parameterName=item=>String(item.description).split(';')[0].trim();
  const opNames={parameter:'Parameter',constant:'Constant',add:'Add (+)',sub:'Subtract (−)',mul:'Multiply (×)',div:'Divide (÷)',positive_div:'Divide by a positive value',neg:'Negate (−)',annual:'Annual statistic',at:'Value at date',lookback:'Value months earlier',ref:'Exact saved reference'};
  let callbacks={},catalog=null,entries=[],editor=null,role='ranking',draftRevision=0,generation=0,mutation=0,listRequest=0,validation=0,preview=0,editRevision=0,returnFocus=null,sourceSelection=null,authoredRequest=0,coverageAbort=null,coverageVersion=0,coverageScopes=null,checkTimer=null;
  // Edits are checked after a short pause; Use and Save always check first.
  const CHECK_DELAY=400;
  function message(text,error=false){node('variable-message').textContent=text;node('variable-message').className=error?'backtest-failed':'hint';}
  async function request(path,body){
    const response=await fetch('/api/variables'+path,{cache:'no-store',...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
    const value=await response.json();if(!response.ok){const error=Object.assign(Error(value.error||'Variable operation failed.'),value,{status:response.status});throw error;}return value;
  }
  function error(error){node('variable-errors').textContent=(error.errors||[{path:error.path||'',message:error.message}]).map(issue=>(issue.path?issue.path+': ':'')+issue.message).join('\n');message(error.message,true);}
  function showCheck(state,title){
    node('variable-check').dataset.state=state;node('variable-check-title').textContent=title;
    node('variable-check-chip').dataset.state=state;node('variable-check-chip').textContent={ready:'✓ Ready',pending:'Checking…',incomplete:'Formula incomplete',error:'Needs attention'}[state];
  }
  function emptyTerm(expression,depth=0){
    if(!expression||typeof expression!=='object'||depth>32)return false;
    if(expression.op==='parameter')return !expression.id;
    if(expression.op==='ref')return !expression.variable_id;
    return ['arg','left','right'].some(key=>emptyTerm(expression[key],depth+1));
  }
  function scheduleCheck(){
    clearTimeout(checkTimer);checkTimer=null;
    if(!editor)return;
    if(emptyTerm(editor.definition.expression)){showCheck('incomplete','Choose a parameter for each empty box (＋ Parameter) to finish the formula.');return;}
    showCheck('pending','Checking the formula…');
    if(!catalog||!node('variable-dialog').open)return;
    const local=generation;
    checkTimer=setTimeout(()=>{checkTimer=null;if(local===generation&&node('variable-dialog').open)validate().catch(failure=>{if(local===generation)error(failure);});},CHECK_DELAY);
  }
  function invalidate(){validation++;preview++;editRevision++;coverageVersion++;coverageAbort?.abort();if(editor){editor.checked=null;node('variable-explanation').textContent=describe(editor.definition.expression);}node('variable-errors').textContent='';node('variable-preview-result').textContent='';node('variable-coverage-result').textContent='';scheduleCheck();}
  function describe(expression){
    if(!expression||typeof expression!=='object')return 'Invalid expression';
    const op=expression.op;
    if(op==='parameter')return parameters().find(p=>p.id===expression.id)?.description||expression.id||'Choose a parameter';
    if(op==='constant')return expression.value+' '+expression.unit;
    if(op==='ref')return 'Reference '+expression.variable_id+' @ '+expression.revision;
    if(op==='annual')return expression.stat+' of '+expression.count+' consecutive annual '+expression.parameter+' observations';
    if(op==='at')return '('+describe(expression.arg)+') available at '+expression.date;
    if(op==='lookback')return '('+describe(expression.arg)+') available '+expression.months+' calendar months earlier';
    if(op==='neg')return '−('+describe(expression.arg)+')';
    return '('+describe(expression.left)+' '+({add:'+',sub:'−',mul:'×',div:'÷'}[op]||op)+' '+describe(expression.right)+')';
  }
  function getAt(path){return path?path.split('.').reduce((v,key)=>v?.[key],editor.definition.expression):editor.definition.expression;}
  function replaceAt(path,value){if(!path)editor.definition.expression=value;else{const parts=path.split('.'),key=parts.pop();getAt(parts.join('.'))[key]=value;}}
  const selectedPath=()=>editor.selectedPath||'';
  function remember(){(editor.undo??=[]).push(copy({expression:editor.definition.expression,content:editor.content,selectedPath:selectedPath()}));if(editor.undo.length>50)editor.undo.shift();editor.redo=[];}
  function restore(direction){
    const from=editor[direction];if(!from?.length)return;
    cancelSource();
    (editor[direction==='undo'?'redo':'undo']??=[]).push(copy({expression:editor.definition.expression,content:editor.content,selectedPath:selectedPath()}));
    const previous=from.pop();editor.definition.expression=previous.expression;editor.content=previous.content;editor.selectedPath=previous.selectedPath;invalidate();renderEditor();
  }
  // role is the stable Use destination. Insertion owns only a term path and
  // authored-read freshness; it never changes the workspace session generation.
  function cancelSource(){authoredRequest++;if(sourceSelection){sourceSelection=null;renderPicker();}}
  function chooseSource(path){
    authoredRequest++;sourceSelection={path};renderPicker();message('Choose a parameter, measure or saved variable to replace the selected term.');node('variable-search').focus();
  }
  function equationAction(action){
    if(action==='undo'||action==='redo'){restore(action);return;}
    const path=selectedPath(),term=getAt(path);
    if(action==='source'){chooseSource(path);return;}
    cancelSource();
    remember();
    if(action==='remove'){
      if(path){const parts=path.split('.'),key=parts.pop(),parentPath=parts.join('.'),parent=getAt(parentPath);replaceAt(parentPath,parent.arg||parent[key==='left'?'right':'left']);editor.selectedPath=parentPath;}
      else replaceAt('',{op:'parameter',id:''});
    }else{
      replaceAt(path,fresh(action,term));
      if(['add','sub','mul','div'].includes(action)){
        getAt(path).right={op:'parameter',id:''};editor.selectedPath=path?path+'.right':'right';
      }
    }
    invalidate();renderEditor();focusEquation();
    if(action==='constant'){const input=node('variable-tree').querySelector?.('[data-field="value"]');input?.focus();input?.select();}
  }
  function focusEquation(){node('variable-equation').querySelector?.('[aria-pressed="true"]')?.focus();}
  function equation(expression,path='',depth=0){
    if(depth>32)return '<span>Expression too deep. Use Advanced JSON.</span>';
    if(!expression||typeof expression!=='object')return '<span>Invalid term. Use Advanced JSON.</span>';
    const op=expression.op,child=key=>equation(expression[key],path?path+'.'+key:key,depth+1);
    const button=(label,kind='term',title=describe(expression))=>`<button type="button" class="variable-equation-${kind}" data-equation-path="${esc(path)}" aria-pressed="${selectedPath()===path}" title="${esc(title)}">${label}</button>`;
    if(op==='parameter'){
      const parameter=parameters().find(item=>item.id===expression.id);
      return button(`<span>${esc(parameter?.description||expression.id||'＋ Parameter')}</span>${parameter?`<small>${esc(parameter.unit)}</small>`:''}`,expression.id?'term':'empty');
    }
    if(op==='constant')return button(`<span>${esc(expression.value)}</span><small>${esc(expression.unit)}</small>`);
    if(op==='ref'){
      const label=editor.content.labels.find(item=>item.variable_id===expression.variable_id&&item.revision===expression.revision)?.name;
      return button(esc(label||expression.variable_id||'Choose saved variable'),'term');
    }
    if(op==='annual'){
      const parameter=parameters().find(item=>item.id===expression.parameter);
      return button(`<span>${esc(expression.stat)}<sub>${esc(expression.count)} years</sub> (${esc(parameter?.description||expression.parameter)})</span>`);
    }
    if(op==='at'||op==='lookback')return `<span class="variable-equation-group">${button(esc(op==='at'?'At '+expression.date:expression.months+' months earlier'),'function')}<span class="variable-equation-bracket">(</span>${child('arg')}<span class="variable-equation-bracket">)</span></span>`;
    if(op==='neg')return `<span class="variable-equation-group">${button('−','operator')}<span class="variable-equation-bracket">(</span>${child('arg')}<span class="variable-equation-bracket">)</span></span>`;
    if(op==='div'||op==='positive_div')return `<span class="variable-equation-fraction"><span class="variable-equation-numerator" aria-label="Numerator">${child('left')}</span>${button(`<span class="variable-equation-sr">Select ${op==='positive_div'?'positive-denominator division':'division'} group</span>`,'bar')}${op==='positive_div'?'<small class="variable-equation-policy">denominator &gt; 0</small>':''}<span class="variable-equation-denominator" aria-label="Denominator">${child('right')}</span></span>`;
    if(['add','sub','mul'].includes(op))return `<span class="variable-equation-group"><span class="variable-equation-bracket">(</span>${child('left')}${button({add:'+',sub:'−',mul:'×'}[op],'operator')}${child('right')}<span class="variable-equation-bracket">)</span></span>`;
    return button('Unsupported term');
  }
  function renderEquation(){
    node('variable-equation').innerHTML=equation(editor.definition.expression);
    node('variable-equation-undo').disabled=!editor.undo?.length;node('variable-equation-redo').disabled=!editor.redo?.length;
    node('variable-json').value=JSON.stringify(editor.definition.expression,null,2);
  }
  function parameters(){return editor?.definition.parameter_catalog==='financial-parameters/3'?(catalog?.expanded_parameters||[]):editor?.definition.parameter_catalog==='financial-parameters/2'?(catalog?.version2_parameters||[]):(catalog?.parameters||[]);}
  function options(items,selected){
    const groups=new Map();for(const item of items){const group=item.kind==='adapter'?'Existing policy adapters':item.source?.endpoint||'Financial inputs';if(!groups.has(group))groups.set(group,[]);groups.get(group).push(item);}
    return (selected?'':'<option value="" selected>Choose a parameter</option>')+[...groups].map(([group,values])=>`<optgroup label="${esc(group)}">${values.map(p=>`<option value="${esc(p.id)}" ${selected===p.id?'selected':''}>${esc(p.description)} (${esc(p.unit)})</option>`).join('')}</optgroup>`).join('');
  }
  function fresh(op,old){
    if(op==='parameter')return old?.op==='annual'?{op,id:old.parameter}:old?.op==='parameter'?copy(old):defaultExpression();
    if(op==='constant')return {op,value:'1',unit:'scalar'};
    if(op==='annual')return {op,stat:'mean',count:3,parameter:old?.op==='parameter'&&old.id.startsWith('annual.')?old.id:old?.parameter||'annual.operating_margin'};
    if(op==='ref')return {op,variable_id:'',revision:''};
    if(op==='at')return {op,date:node('variable-preview-date').value||'2025-01-02',arg:old||defaultExpression()};
    if(op==='lookback')return {op,months:12,arg:old||defaultExpression()};
    if(op==='neg')return {op,arg:old||defaultExpression()};
    return {op,left:old||defaultExpression(),right:{op:'constant',value:'1',unit:'scalar'}};
  }
  function termSettings(expression,path=''){
    const op=expression.op,field=(key,label,html)=>`<label>${label} ${html.replace('data-field=',`data-path="${esc(path)}" data-field=`)}</label>`;
    let html=`<fieldset data-node="${esc(path)}"><legend>${esc(opNames[op]||'Expression')}</legend><label>Term type / operation <select data-path="${esc(path)}" data-op>${(catalog?.operations||[]).filter(value=>value!=='positive_div'||editor.definition.version>=3).map(value=>`<option value="${esc(value)}" ${op===value?'selected':''}>${esc(opNames[value]||value)}</option>`).join('')}</select></label><button type="button" data-reference="${esc(path)}">Choose source for this term</button>`;
    if(op==='parameter'){const p=parameters().find(item=>item.id===expression.id);html+=field('id','Financial parameter',`<select data-field="id">${options(parameters(),expression.id)}</select>`);if(p)html+=`<p>${esc(p.description)} · ${esc(p.source?`${p.source.endpoint} / ${p.source.field}`:p.adapter||'Existing policy')} · ${esc(p.unit)} · ${esc((p.contexts||[]).join(', '))}</p>`;}
    if(op==='constant')html+=field('value','Exact decimal',`<input data-field="value" inputmode="decimal" value="${esc(expression.value)}">`)+field('unit','Canonical unit',`<select data-field="unit">${Object.keys(catalog?.units||{scalar:1,USD:1,'USD/share':1}).filter(v=>v!=='share'||editor.definition.version>=2).map(v=>`<option ${v===expression.unit?'selected':''}>${v}</option>`).join('')}</select>`);
    if(op==='annual'){const p=parameters().find(item=>item.id===expression.parameter);const stats=p?.history?.statistics||(editor.definition.version>=2?['mean','min','max','growth','cagr']:['mean','min','max']);html+=field('stat','Statistic',`<select data-field="stat">${stats.filter(v=>editor.definition.version>=2||!['growth','cagr'].includes(v)).map(v=>`<option ${expression.stat===v?'selected':''}>${v}</option>`).join('')}</select>`)+field('count','Consecutive fiscal years',`<input data-field="count" type="number" min="${['growth','cagr'].includes(expression.stat)?2:1}" max="${p?.counts?.maximum||10}" value="${esc(expression.count)}">`)+field('parameter','Annual parameter',`<select data-field="parameter">${options(parameters().filter(p=>p.id.startsWith('annual.')&&(!p.history||p.history.statistics.length)),expression.parameter)}</select>`);}
    if(op==='at')html+=field('date','Observation date',`<input data-field="date" type="date" value="${esc(expression.date)}">`);
    if(op==='lookback')html+=field('months','Calendar months earlier',`<input data-field="months" type="number" min="1" max="120" value="${esc(expression.months)}">`);
    if(op==='ref')html+=`<p>${esc(expression.variable_id)} @ ${esc(expression.revision)}</p><button type="button" data-reference="${esc(path)}">Choose exact reference</button>`;
    if(['add','sub','mul','div','positive_div','neg'].includes(op))html+='<p class="hint">Select a term in the equation to edit it. Operations keep the displayed grouping.</p>';
    return html+'</fieldset>';
  }
  function renderEditor(){
    node('variable-name').value=editor.name;node('variable-output-unit').value=editor.definition.output.unit;
    const displays=catalog?.displays?.[editor.definition.output.unit];if(displays)node('variable-display').innerHTML=displays.map(v=>`<option value="${esc(v)}">${esc(displayName(v))}</option>`).join('');node('variable-display').value=editor.definition.output.display;
    if(!getAt(selectedPath()))editor.selectedPath='';
    renderEquation();node('variable-tree').innerHTML=termSettings(getAt(selectedPath()),selectedPath());
    node('variable-explanation').textContent=editor.checked?editor.summary:describe(editor.definition.expression);
    renderIdentity();
    node('variable-upgrade').hidden=editor.definition.version===3&&editor.definition.parameter_catalog==='financial-parameters/3';
    node('variable-dialog-title').textContent=role==='ranking'?'Ranking variable':role==='condition'?'New filter':'Filter '+(role+1);
    node('variable-apply').textContent=useLabel();
  }
  // role is fixed for one open dialog, so the main action names its destination.
  const useLabel=()=>role==='ranking'?'Use for ranking':role==='condition'?'Add as filter':'Update filter '+(role+1);
  // State in words. The exact identity stays available as a tooltip.
  function renderIdentity(){
    const entry=editor.entry,saved=!!entry&&!entry.deleted;
    const changed=saved&&!!editor.checked&&(editor.checked.root.revision!==editor.selectedRevision||!editor.detachedSelection&&editor.name!==entry.name);
    const state=node('variable-selected');
    state.textContent=entry?.deleted?'Deleted from My variables':saved?(changed?'Saved in My variables · unsaved changes':'Saved in My variables'):editor.detachedSelection?'Used by this strategy · not in My variables':'New variable · not saved';
    state.title=editor.variable_id+(editor.selectedRevision?' @ '+editor.selectedRevision:'');
    for(const id of ['variable-favourite','variable-delete']){node(id).hidden=!saved;node(id).disabled=!saved;}
    node('variable-favourite').textContent=entry?.favourite?'★ Remove from favourites':'☆ Add to favourites';
    node('variable-edit-selected').hidden=!saved||!!editor.detachedSelection;
    node('variable-save').textContent=saved?'Save changes':'Save to My variables';
    node('variable-save-new').hidden=!saved;
  }
  function startNew(keepGeneration=false){if(!keepGeneration)generation++;cancelSource();invalidate();editor={name:'Operating margin',variable_id:'local:'+Array.from(crypto.getRandomValues(new Uint8Array(8)),b=>b.toString(16).padStart(2,'0')).join(''),definition:envelope(defaultExpression()),content:content()};scheduleCheck();renderEditor();renderPicker();}
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
    const item=entry=>`<button type="button" data-library="${esc(entry.variable_id)}" data-revision="${esc(entry.revision)}" title="${esc(entry.variable_id+' @ '+entry.revision)}">${esc(entry.name)}${entry.favourite?' ★':''}<small>Saved variable</small></button>`;
    const params=parameters().filter(matches),categories=new Map();for(const p of params){const group=p.kind==='adapter'?'Existing policy adapters':p.source?.endpoint||'Financial inputs';if(!categories.has(group))categories.set(group,[]);categories.get(group).push(p);}
    const sources=[...categories].map(([name,values])=>group(esc(name),values.map(p=>`<button type="button" data-parameter="${esc(p.id)}" title="${esc((p.source?`${p.source.endpoint} / ${p.source.field}`:p.adapter||'Existing policy')+' · '+(p.contexts||[]).join(', '))}">${esc(p.description)}<small>${esc(p.unit==='scalar'?'ratio':p.unit)}</small></button>`))).join('');
    node('variable-picker').innerHTML=group('Favourites',entries.filter(e=>e.favourite&&matches(e)).map(item))+group('My variables',entries.filter(matches).map(item))+sources+group('Measures',(catalog?.measures||[]).filter(matches).map(e=>`<button type="button" data-measure="${esc(e.id)}" ${editor?.definition.version<3?'disabled title="Use expanded inputs first"':''}>${esc(e.name)}<small>${esc(displayName(e.display))} · ${esc(e.missing)}${e.history?' · annual history: '+esc(e.history):''}</small></button>`))+group('Built-ins',(sourceSelection?[]:catalog?.builtins||[]).filter(matches).map(e=>`<button type="button" data-builtin="${esc(e.id)}">${esc(e.label)}<small>Built-in · ${esc(displayName(e.display))}</small></button>`));
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
      catalog??=await request('/catalog');if(local!==generation)return;renderEditor();scheduleCheck();
      if(captured&&openedEdit===editRevision){
        const snapshot=await request('/detached',{root:{variable_id:selected.variable_id,revision:selected.revision},capture:copy(captured)});
        if(local!==generation)return;
        if(openedEdit===editRevision){
          const definition=snapshot.authored.find(item=>item.variable_id===selected.variable_id&&item.revision===selected.revision).definition;
          editor={name:snapshot.name,variable_id:selected.variable_id,selectedRevision:selected.revision,definition:copy(definition),content:dependencies(snapshot,selected),detachedSelection:true};invalidate();renderEditor();renderPicker();
        }
      }
      await refresh();if(local===generation){message(editor.detachedSelection?'This is the variable the strategy uses now. Edit it, then select '+useLabel()+'. Saving is optional.':'Choose a starting point on the left, or edit the formula below. Select '+useLabel()+' when it is ready.');node('variable-search').focus();}
    }
    catch(failure){if(local===generation)error(failure);}
  }
  function close(){cancelSource();generation++;invalidate();node('variable-dialog').close?.();node('variable-dialog').removeAttribute('open');returnFocus?.focus?.();}
  async function loadExact(variable_id,revision){
    const selection=sourceSelection,number=++authoredRequest;
    if(!selection)generation++;
    const local=generation;invalidate();const edited=editRevision;
    const current=()=>local===generation&&edited===editRevision&&number===authoredRequest&&selection===sourceSelection;
    message('Reading exact authored content…');
    try{
      const snapshot=await request('/authored',{variable_id,revision});if(!current())return;
      if(selection){remember();sourceSelection=null;replaceAt(selection.path,{op:'ref',variable_id,revision});editor.selectedPath=selection.path;editor.content=content(editor.content,{submitted:snapshot.authored,labels:snapshot.capture.presentation});invalidate();renderEditor();renderPicker();focusEquation();message('Inserted “'+snapshot.entry.name+'” into the formula.');return;}
      const definition=snapshot.authored.find(item=>item.variable_id===variable_id&&item.revision===revision).definition;
      editor={name:snapshot.entry.name,variable_id,selectedRevision:revision,definition:copy(definition),entry:snapshot.entry,content:dependencies(snapshot,{variable_id,revision}),checked:null};scheduleCheck();renderEditor();renderPicker();message('Loaded “'+snapshot.entry.name+'” from My variables. Select '+useLabel()+' to use it, or edit it first.');
    }catch(failure){if(current())error(failure);}
  }
  function editorRequest(){return {definition:copy(editor.definition),variable_id:editor.variable_id,name:node('variable-name').value.trim()||editor.variable_id,...content(editor.content)};}
  function summary(definition,checked){
    const uses=[...new Set(checked.requirements.map(r=>{const parameter=parameters().find(p=>p.id===r.parameter),name=parameter?parameterName(parameter):r.parameter;return r.count>1?name+' × '+r.count+' years':name;}))];
    return describe(definition.expression)+' · Results shown as '+displayName(checked.output.display)+(uses.length?' · Uses '+uses.join(', '):'')+'. Some companies may still lack these inputs.';
  }
  async function validate(){
    clearTimeout(checkTimer);checkTimer=null;
    if(emptyTerm(editor.definition.expression))throw Error('Choose a parameter for each empty box (＋ Parameter) first.');
    const local=generation,number=++validation,input=editorRequest();
    showCheck('pending','Checking the formula…');
    let checked;
    try{checked=await request('/validate',input);}
    catch(failure){if(local===generation&&number===validation)showCheck('error','Fix the formula before using it');throw failure;}
    if(local!==generation||number!==validation)return null;
    editor.checked=checked;editor.name=input.name;
    editor.content=dependencies(checked,checked.root);editor.summary=summary(input.definition,checked);
    node('variable-errors').textContent='';node('variable-explanation').textContent=editor.summary;
    showCheck('ready','✓ Ready to use');renderIdentity();return checked;
  }
  async function apply(){
    cancelSource();
    const local=generation,checked=await validate();if(!checked||local!==generation)return;
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
    if(edited===editRevision){editor.name=saved.name;scheduleCheck();renderEditor();message('Saved “'+saved.name+'” to My variables. Select '+useLabel()+' to use it in this strategy.');}
    else message('The submitted version was saved. Your newer local edits are kept and need another save.');
    try{await refresh();}catch(_){message('Variable saved. The list could not refresh; use Refresh variables to retry.');}
  }
  async function metadata(action){
    if(!editor.entry)return;const local=generation,entry=copy(editor.entry);mutation++;
    const result=await request('/'+entry.variable_id+'/'+action,{version:entry.version,...(action==='favourite'?{favourite:!entry.favourite}:{})});mutation++;
    if(local!==generation)return;editor.entry=result;renderEditor();message(action==='delete'?'Deleted from My variables. Strategies that already use it keep their own copy.':result.favourite?'Added to favourites.':'Removed from favourites.');
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
  async function coverageCall(path,body,signal){const response=await fetch('/api/variable-coverage/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal});const value=await response.json();if(!response.ok)throw Object.assign(Error(value.error),value);return value;}
  async function discoverCoverage(){
    coverageAbort?.abort();coverageAbort=new AbortController();const number=++coverageVersion,local=generation;
    const value=await coverageCall('scopes',{},coverageAbort.signal);if(number!==coverageVersion||local!==generation)return;
    coverageScopes=value;node('variable-coverage-scope').innerHTML=value.scopes.map((s,i)=>`<option value="${i}">${esc(s.mode)} · ${esc(s.context_date)} · ${esc(s.pool)} · book ${esc(s.book)}</option>`).join('');
    node('variable-coverage-result').textContent='Select a recorded scope to inspect.';
  }
  async function inspectCoverage(){
    if(!coverageScopes)throw Error('Find recorded scopes first.');
    const selected=coverageScopes.scopes[Number(node('variable-coverage-scope').value)];if(!selected)throw Error('Select a recorded scope.');
    coverageAbort?.abort();const controller=new AbortController();coverageAbort=controller;
    const number=++coverageVersion,local=generation,discoveredGeneration=coverageScopes.generation;
    const current=()=>number===coverageVersion&&local===generation&&!controller.signal.aborted;
    try{
      const checked=await validate();if(!checked||!current())return;
      const prepared=await request('/capture',{intent:{format:'strategy-intent',version:1,selection:{ranking:{source:{kind:'formula',...checked.root},direction:'highest'},rank_from:1,rank_to:50,selection_order:'filter_first',conditions:[]},pool:selected.pool,bounds:{}},detached:[checked.capture]});
      if(!current())return;
      const value=await coverageCall('inspect',{strategy:prepared.strategy,scope:{generation:discoveredGeneration,...selected}},controller.signal);if(!current())return;
      node('variable-coverage-result').textContent=`Generation ${value.generation}; projection ${value.projection.content}; ${value.scope.mode}, ${value.scope.context_date}, ${value.scope.pool}, book ${value.scope.book}. Snapshot denominator: ${value.population} rows before availability, ranking and filters. Provider admission: ${value.provider_admitted} admitted, ${value.provider_unavailable} unavailable; reasons ${JSON.stringify(value.provider_reasons)}. Formula results count the first unavailable reason for each row: `+value.outputs.map(o=>`${o.variable_id} @ ${o.revision}: ${o.valid} valid, ${o.unavailable} unavailable; ${JSON.stringify(o.reasons)}`).join(' · ');
    }catch(failure){if(current())throw failure;}
  }
  // The page's filter list offers the same sources as the picker. Policy
  // adapters are left out there: built-in filters already provide them.
  async function sources(){
    catalog??=await request('/catalog');
    const library=await request('');
    return {library:library.entries.filter(entry=>!entry.deleted),measures:catalog.measures,
      parameters:catalog.expanded_parameters.filter(item=>item.kind!=='adapter').map(item=>({...item,name:parameterName(item),note:String(item.description).split(';').slice(1).join(';').trim()}))};
  }
  // One list choice becomes an exact checked source, exactly as opening it in
  // the editor and selecting Use would. expected fences the draft revision.
  async function useSource(target,choice,expected){
    catalog??=await request('/catalog');
    let input;
    if(choice.kind==='library'){
      const root={variable_id:choice.variable_id,revision:choice.revision},snapshot=await request('/authored',root);
      input={definition:copy(snapshot.authored.find(item=>exact(item)===exact(root)).definition),variable_id:root.variable_id,name:snapshot.entry.name,...dependencies(snapshot,root)};
    }else if(choice.kind==='measure'){
      const measure=catalog.measures.find(item=>item.id===choice.id);
      input={definition:copy(measure.submitted.find(item=>exact(item)===exact(measure.root)).definition),variable_id:measure.root.variable_id,name:measure.name,...content({submitted:measure.submitted.filter(item=>exact(item)!==exact(measure.root)),labels:measure.labels})};
    }else{
      const parameter=catalog.expanded_parameters.find(item=>item.id===choice.id);
      const output={unit:parameter.unit,display:parameter.unit==='USD'?'usd_million':catalog.displays[parameter.unit][0]};
      input={definition:{...envelope({op:'parameter',id:parameter.id}),output},variable_id:'local:'+parameter.id,name:parameterName(parameter),submitted:[],labels:[]};
    }
    const checked=await request('/validate',input);
    callbacks.draft.patch({role:target,source:{kind:'formula',...checked.root},capture:checked.capture,authored:checked.authored},expected);
  }
  function attempt(work){
    Promise.resolve().then(()=>{
      let pending;
      try{pending=work();}catch(failure){if(failure.name!=='AbortError')error(failure);return;}
      // Start the operation before capturing its session: opening or replacing
      // an editor may establish a new generation synchronously.
      const local=generation;
      return Promise.resolve(pending).catch(failure=>{if(local===generation&&failure.name!=='AbortError')error(failure);});
    });
  }
  function init(options){
    callbacks=options;node('variable-preview-date').value=options.asof;
    const controls=document.querySelector('.variable-controls');
    controls.addEventListener('input',event=>event.stopPropagation());controls.addEventListener('change',event=>event.stopPropagation());
    node('variable-rank').addEventListener('click',()=>attempt(()=>open('ranking')));node('variable-new').addEventListener('click',()=>attempt(()=>open('ranking')));
    node('variable-legacy').addEventListener('click',()=>callbacks.draft.patch({legacy:true},callbacks.draft.read().revision));
    node('variable-direction').addEventListener('change',()=>callbacks.draft.patch({direction:node('variable-direction').value},callbacks.draft.read().revision));
    node('variable-close').addEventListener('click',close);node('variable-dialog').addEventListener('cancel',()=>{cancelSource();generation++;invalidate();returnFocus?.focus?.();});
    node('variable-search').addEventListener('input',renderPicker);node('variable-refresh').addEventListener('click',()=>attempt(refresh));node('variable-start-new').addEventListener('click',()=>startNew());
    node('variable-edit-selected').addEventListener('click',()=>attempt(()=>loadExact(editor.variable_id,editor.selectedRevision)));
    node('variable-picker').addEventListener('click',event=>{const target=event.target.closest('button');if(!target)return;if(target.dataset.library)attempt(()=>loadExact(target.dataset.library,target.dataset.revision));else if(target.dataset.measure||target.dataset.parameter){const measure=target.dataset.measure?catalog.measures.find(item=>item.id===target.dataset.measure):null;const expression=measure?{op:'ref',...measure.root}:{op:'parameter',id:target.dataset.parameter};remember();const path=sourceSelection?.path??selectedPath();cancelSource();replaceAt(path,expression);editor.selectedPath=path;if(measure)editor.content=content(editor.content,measure);invalidate();renderEditor();renderPicker();focusEquation();message('Inserted into the formula.');}else if(target.dataset.builtin)attempt(()=>{callbacks.draft.patch({role,source:{kind:'builtin',id:target.dataset.builtin}},draftRevision);close();});});
    node('variable-upgrade').addEventListener('click',()=>{editor.definition.version=3;editor.definition.parameter_catalog='financial-parameters/3';invalidate();renderEditor();renderPicker();message('Expanded inputs enabled. The formula is checked again.');});
    node('variable-equation-tools').addEventListener('click',event=>{const action=event.target.closest('button')?.dataset.equationAction;if(action)equationAction(action);});
    node('variable-equation').addEventListener('click',event=>{const target=event.target.closest('[data-equation-path]');if(!target)return;cancelSource();editor.selectedPath=target.dataset.equationPath;editRevision++;renderEditor();focusEquation();});
    node('variable-equation').addEventListener('keydown',event=>{const action={'+':'add','-':'sub','*':'mul','/':'div',Delete:'remove',Backspace:'remove'}[event.key];if(action&&!event.ctrlKey&&!event.metaKey&&!event.altKey){event.preventDefault();const target=event.target.closest('[data-equation-path]');if(target)editor.selectedPath=target.dataset.equationPath;equationAction(action);}});
    node('variable-tree').addEventListener('change',event=>{const target=event.target;if(target.dataset.op!==undefined){cancelSource();remember();replaceAt(target.dataset.path,fresh(target.value,getAt(target.dataset.path)));invalidate();renderEditor();}else if(target.dataset.field){cancelSource();const path=target.dataset.path,field=target.dataset.field;const value=['count','months'].includes(field)?Number(target.value):target.value;if(target.tagName!=='SELECT'&&getAt(path)[field]===value)return;if(getAt(path)[field]!==value){remember();getAt(path)[field]=value;}invalidate();renderEditor();node('variable-tree').querySelector?.('[data-field="'+field+'"]')?.focus();}});
    node('variable-tree').addEventListener('input',event=>{const target=event.target;if(target.dataset.field){cancelSource();const value=['count','months'].includes(target.dataset.field)?Number(target.value):target.value;if(getAt(target.dataset.path)[target.dataset.field]!==value){remember();getAt(target.dataset.path)[target.dataset.field]=value;}invalidate();renderEquation();}});
    node('variable-tree').addEventListener('click',event=>{if(event.target.dataset.reference!==undefined)chooseSource(event.target.dataset.reference);});
    node('variable-name').addEventListener('input',()=>{invalidate();editor.name=node('variable-name').value;});
    for(const [id,key] of [['variable-output-unit','unit'],['variable-display','display']])node(id).addEventListener('change',()=>{editor.definition.output[key]=node(id).value;if(key==='unit')editor.definition.output.display=catalog.displays[editor.definition.output.unit][0];invalidate();renderEditor();});
    node('variable-accept-json').addEventListener('click',()=>attempt(()=>{const parsed=JSON.parse(node('variable-json').value);if(!parsed||typeof parsed!=='object'||Array.isArray(parsed))throw Error('Expression JSON must be an object.');remember();editor.definition.expression=parsed;editor.selectedPath='';cancelSource();invalidate();renderEditor();}));
    node('variable-apply').addEventListener('click',()=>attempt(apply));node('variable-save').addEventListener('click',()=>attempt(()=>save(false)));node('variable-save-new').addEventListener('click',()=>attempt(()=>save(true)));node('variable-favourite').addEventListener('click',()=>attempt(()=>metadata('favourite')));node('variable-delete').addEventListener('click',()=>attempt(()=>metadata('delete')));node('variable-preview').addEventListener('click',()=>attempt(previewSamples));
    node('variable-coverage-scopes').addEventListener('click',()=>attempt(discoverCoverage));node('variable-coverage-inspect').addEventListener('click',()=>attempt(inspectCoverage));node('variable-coverage-scope').addEventListener('change',()=>{coverageVersion++;coverageAbort?.abort();node('variable-coverage-result').textContent='';});
  }
  return {init,open,describe,request,copy,exact,content,sources,useSource,displayName,displays:unit=>[...catalog?.displays?.[unit]||[]],builtin:id=>copy(catalog?.builtins.find(item=>item.id===id)??null)};
})();
if(typeof module!=='undefined')module.exports=VariableWorkspace;
