/* Typed-formula editor. The server reads, checks and draws the formula; this
   module keeps the session, suggestions and the step destination. */
const VariableWorkspace=(()=>{
  const copy=v=>JSON.parse(JSON.stringify(v)),node=id=>document.getElementById(id);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
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
  const displayNames={number:'Number',multiple:'Multiple (×)',percent:'Percent (%)',percentage_points:'Percentage points',usd:'US dollars',usd_million:'$ million',usd_per_share:'$ per share',shares:'Shares'};
  const displayName=value=>displayNames[value]||value;
  const unitNames={scalar:'ratio',USD:'US dollars','USD/share':'US dollars per share',share:'shares'};
  const fold=text=>text.replace(/\s+/g,' ').toLowerCase();
  // Edits are checked after a short pause; Use and Save check first when needed.
  const CHECK_DELAY=400;
  let callbacks={},catalog=null,entries=[],words=[],editor=null,role=null,draftRevision=0,generation=0,validation=0,edits=0,returnFocus=null,checkTimer=null,suggestions=null;
  function message(text,error=false){node('variable-message').textContent=text;node('variable-message').className=error?'backtest-failed':'hint';}
  async function request(path,body){
    const response=await fetch('/api/variables'+path,{cache:'no-store',...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
    const value=await response.json();if(!response.ok){const error=Object.assign(Error(value.error||'Variable operation failed.'),value,{status:response.status});throw error;}return value;
  }
  // Session: base is what opened the formula. Unchanged text keeps it exactly.
  const blank=()=>({name:'',variable_id:'local:'+Array.from(crypto.getRandomValues(new Uint8Array(8)),b=>b.toString(16).padStart(2,'0')).join(''),text:'',display:null,base:null,entry:null,checked:null,issue:null});
  function showCheck(state,text){
    node('variable-check').dataset.state=state;node('variable-check-text').textContent=text;
    node('variable-display-label').hidden=true;node('variable-fixes').innerHTML='';
    if(state!=='pending')node('variable-picture').innerHTML='';
  }
  // Text, name and display edits all make a new check.
  function edited(){
    edits++;validation++;editor.checked=null;clearTimeout(checkTimer);checkTimer=null;
    if(!editor.text.trim()){showCheck('empty','Type a formula');return;}
    showCheck('pending','Checking…');
    const local=generation;
    checkTimer=setTimeout(()=>{checkTimer=null;if(local===generation)validate();},CHECK_DELAY);
  }
  // Returns the checked formula, or null after it shows why there is none.
  async function validate(){
    clearTimeout(checkTimer);checkTimer=null;
    if(!editor.text.trim()){showCheck('empty','Type a formula');return null;}
    const local=generation,number=++validation;
    showCheck('pending','Checking…');
    try{
      catalog??=await request('/catalog');
      const checked=await request('/validate',{formula:{text:editor.text,display:editor.display},name:editor.name,variable_id:editor.variable_id,...(editor.base?{base:editor.base}:{})});
      if(local!==generation||number!==validation)return null;
      editor.checked=checked;editor.display=checked.output.display;ready(checked);return checked;
    }catch(failure){if(local===generation&&number===validation)fail(failure);return null;}
  }
  function ready(checked){
    const unit=checked.output.unit,displays=catalog.displays[unit];
    showCheck('ready','✓ Ready · Result: '+unitNames[unit]);
    node('variable-display').innerHTML=displays.map(value=>`<option value="${esc(value)}">${esc(displayName(value))}</option>`).join('');
    node('variable-display').value=checked.output.display;node('variable-display-label').hidden=displays.length<2;
    node('variable-picture').innerHTML=draw(checked.picture);
  }
  // The caret never moves on its own; the message names the bad part instead.
  function fail(failure){
    const issue=failure.errors?.[0]||{message:failure.message,suggestions:[]};
    const bad=issue.end>issue.start?editor.text.slice(issue.start,issue.end).trim():'';
    showCheck('error','✗ '+issue.message+(bad&&!issue.message.includes(bad)?' (“'+bad+'”)':''));
    editor.issue=issue;
    node('variable-fixes').innerHTML=issue.suggestions.map((item,index)=>`<button type="button" data-fix="${index}">${esc(item.label)}</button>`).join('');
  }
  // Draws the server's layout. No precedence or grammar lives here.
  function draw(part){
    const html=part.name!==undefined?`<span class="variable-picture-name">${esc(part.name)}</span>`
      :part.number!==undefined?esc(part.number)+(part.unit?' '+esc(part.unit):'')
      :part.fn?`<span title="${esc(part.hint)}">${esc(part.fn)}(${part.args.map(draw).join(', ')})</span>`
      :part.op==='/'?`<span class="variable-picture-fraction"><span>${draw(part.top)}</span><span${part.positive?' title="Divides only by a value above zero"':''}>${draw(part.bottom)}${part.positive?' <small>&gt; 0</small>':''}</span></span>`
      :part.op==='neg'?'−'+draw(part.arg)
      :draw(part.left)+' '+{'+':'+','-':'−','*':'×'}[part.op]+' '+draw(part.right);
    return part.parens?'('+html+')':html;
  }
  // Insertion goes through the browser's own editing, so native undo keeps it.
  function insert(text,start,end){
    const field=node('variable-formula');field.focus();field.setSelectionRange(start,end);
    document.execCommand('insertText',false,text);
  }
  function choices(){
    const labels=new Map(catalog.builtins.map(item=>[item.id,item.label])),plain=text=>fold(text.replace(/\s*\([^)]*\)$/,'')).replace(/ /g,'');
    // A linked step label shows only where it says something the name does not.
    const detail=item=>{const step=labels.get(item.builtins[0]);return step&&plain(step)!==plain(item.name)?step:displayName(item.display);};
    return [...entries.map(item=>({name:item.name,text:item.text,detail:'My variable'})),
      ...catalog.vocabulary.filter(item=>item.term).map(item=>({name:item.name,text:item.text,detail:detail(item)})),
      ...catalog.functions.map(item=>({name:item.name,text:item.text,detail:item.hint}))];
  }
  // The longest partial name that ends at the caret and starts a word.
  function suggest(){
    const field=node('variable-formula'),before=field.value.slice(0,field.selectionStart);suggestions=null;
    if(field.selectionStart===field.selectionEnd)for(let at=0;at<before.length;at++){
      if(!/[a-z]/i.test(before[at])||/\w/.test(before[at-1]||''))continue;
      const partial=fold(before.slice(at)),items=words.filter(word=>(' '+fold(word.name)).includes(' '+partial));
      if(!items.length)continue;
      items.sort((a,b)=>fold(b.name).startsWith(partial)-fold(a.name).startsWith(partial));
      if(items.length>1||fold(items[0].name)!==partial)suggestions={start:at,items:items.slice(0,8),active:0};
      break;
    }
    renderSuggestions();
  }
  function renderSuggestions(){
    const field=node('variable-formula'),list=node('variable-suggestions');
    list.hidden=!suggestions;field.setAttribute('aria-expanded',String(!!suggestions));field.setAttribute('aria-activedescendant',suggestions?'variable-suggestion-'+suggestions.active:'');
    list.innerHTML=suggestions?suggestions.items.map((item,index)=>`<div role="option" id="variable-suggestion-${index}" data-suggestion="${index}" aria-selected="${index===suggestions.active}"><span>${esc(item.name)}</span><small>${esc(item.detail)}</small></div>`).join(''):'';
  }
  const hide=()=>{suggestions=null;renderSuggestions();};
  function take(index){const {start,items}=suggestions;hide();insert(items[index].text,start,node('variable-formula').selectionStart);}
  function renderInputs(){
    const button=item=>`<button type="button" data-insert="${esc(item.text)}">${esc(item.name)}</button>`;
    const group=(title,items)=>items.length?`<h3>${esc(title)}</h3><div>${items.map(button).join('')}</div>`:'';
    const categories=new Map();for(const item of catalog.vocabulary.filter(item=>item.term))categories.set(item.category,[...categories.get(item.category)||[],item]);
    node('variable-input-list').innerHTML=group('Favourites',entries.filter(item=>item.favourite))+group('My variables',entries)+[...categories].map(([title,items])=>group(title,items)).join('');
  }
  function renderEntry(){
    const saved=!!editor.entry&&!editor.entry.deleted;
    for(const id of ['variable-favourite','variable-delete'])node(id).hidden=!saved;
    node('variable-favourite').textContent=editor.entry?.favourite?'★ Favourite':'☆ Favourite';node('variable-favourite').setAttribute('aria-pressed',String(!!editor.entry?.favourite));
    node('variable-save').textContent=saved?'Save changes':'Save to My variables';node('variable-save-new').hidden=!saved;
  }
  async function refresh(){
    const local=generation,list=await request('');if(local!==generation)return;
    entries=list.entries;words=choices();renderInputs();
  }
  // role is fixed for one open window: a step ID, or the kind of a new step.
  async function open(selectedRole){
    const draft=callbacks.draft.read(),selected=callbacks.draft.source(selectedRole);
    const captured=selected?.kind==='formula'?draft.detached.find(capture=>capture.program.bundle.definitions.some(item=>item.variable_id===selected.variable_id&&item.revision===selected.revision)):null;
    role=selectedRole;draftRevision=draft.revision;returnFocus=document.activeElement;const local=++generation,opened=edits;
    editor=blank();hide();
    node('variable-dialog-title').textContent=callbacks.draft.describe(role).title;node('variable-apply').textContent=callbacks.draft.describe(role).use;
    node('variable-name').value='';node('variable-formula').value='';showCheck('empty','Type a formula');message('');renderEntry();
    node('variable-dialog').showModal?.();if(!node('variable-dialog').open)node('variable-dialog').setAttribute('open','');
    node('variable-formula').focus();
    try{
      catalog??=await request('/catalog');
      const [list,formula]=await Promise.all([request(''),captured?request('/detached',{root:{variable_id:selected.variable_id,revision:selected.revision},capture:captured}):null]);
      if(local!==generation)return;
      entries=list.entries;words=choices();renderInputs();
      if(formula&&opened===edits){
        const definition=formula.authored.find(item=>item.variable_id===formula.selected.variable_id&&item.revision===formula.selected.revision).definition;
        Object.assign(editor,{name:formula.name,variable_id:formula.selected.variable_id,text:formula.text,display:definition.output.display,base:{root:formula.selected,capture:formula.capture},
          entry:entries.find(entry=>entry.variable_id===formula.selected.variable_id)||null});
        node('variable-name').value=editor.name;node('variable-formula').value=editor.text;renderEntry();await validate();
      }
    }catch(failure){if(local===generation)message(failure.message,true);}
  }
  function ended(){generation++;clearTimeout(checkTimer);checkTimer=null;hide();returnFocus?.focus?.();}
  // Close discards unsaved edits.
  function close(){node('variable-dialog').close?.();node('variable-dialog').removeAttribute('open');ended();}
  async function apply(){
    const local=generation,checked=editor.checked||await validate();if(!checked||local!==generation)return;
    callbacks.draft.patch({role,source:{kind:'formula',...checked.root},capture:checked.capture,authored:checked.authored},draftRevision);close();
  }
  async function save(asNew){
    const local=generation,checked=editor.checked||await validate();if(!checked||local!==generation)return;
    const definition=checked.authored.find(item=>item.variable_id===checked.root.variable_id&&item.revision===checked.root.revision).definition;
    const existing=editor.entry&&!asNew&&!editor.entry.deleted;
    const saved=await request(existing?'/'+editor.entry.variable_id+'/save':'',{name:checked.name,definition,...(existing?{version:editor.entry.version}:{})});
    if(local!==generation)return;
    // The step then uses the saved variable itself.
    editor.entry=saved;editor.variable_id=saved.variable_id;renderEntry();edited();
    message('Saved “'+saved.name+'” to My variables.');
    await refresh();
  }
  async function metadata(action){
    const local=generation,entry=editor.entry;
    const result=await request('/'+entry.variable_id+'/'+action,{version:entry.version,...(action==='favourite'?{favourite:!entry.favourite}:{})});
    if(local!==generation)return;
    editor.entry=result;renderEntry();message(action==='delete'?'Deleted from My variables. Strategies that already use it keep their own copy.':result.favourite?'Added to favourites.':'Removed from favourites.');
    await refresh();
  }
  // Every step shares the library and the formula-only inputs.
  async function sources(){
    catalog??=await request('/catalog');
    const library=await request('');
    return {library:library.entries.filter(entry=>!entry.deleted),inputs:catalog.vocabulary.filter(item=>item.term&&!item.builtins.length)};
  }
  // One list choice becomes an exact checked source, as Use in the window would.
  // expected fences the draft revision.
  async function useSource(target,choice,expected){
    let checked;
    if(choice.kind==='library'){
      const snapshot=await request('/authored',{variable_id:choice.variable_id,revision:choice.revision});
      checked={root:snapshot.selected,capture:snapshot.capture,authored:snapshot.authored};
    }else{
      catalog??=await request('/catalog');
      const input=catalog.vocabulary.find(item=>item.id===choice.id);
      checked=await request('/validate',{formula:{text:input.text,display:input.display},variable_id:'local:'+input.id,name:input.name});
    }
    callbacks.draft.patch({role:target,source:{kind:'formula',...checked.root},capture:checked.capture,authored:checked.authored},expected);
  }
  function attempt(work){
    const local=generation;
    Promise.resolve().then(work).catch(failure=>{if(local===generation)message(failure.message,true);});
  }
  function init(options){
    callbacks=options;
    const field=node('variable-formula');
    node('variable-close').addEventListener('click',close);node('variable-dialog').addEventListener('cancel',ended);
    field.addEventListener('input',()=>{editor.text=field.value;edited();suggest();});
    field.addEventListener('keydown',event=>{
      const key=event.key;
      if(suggestions&&(key==='ArrowDown'||key==='ArrowUp')){event.preventDefault();const count=suggestions.items.length;suggestions.active=(suggestions.active+(key==='ArrowDown'?1:count-1))%count;renderSuggestions();}
      else if(suggestions&&(key==='Enter'||key==='Tab')){event.preventDefault();take(suggestions.active);}
      else if(key==='Enter')event.preventDefault();
      else if(suggestions&&key==='Escape'){event.preventDefault();hide();}
      else if(['ArrowLeft','ArrowRight','Home','End'].includes(key))hide();
    });
    // A moved caret ends the list; typing starts it again.
    field.addEventListener('blur',hide);field.addEventListener('click',hide);
    // Choosing with the pointer keeps the caret in the formula.
    node('variable-suggestions').addEventListener('mousedown',event=>{event.preventDefault();const option=event.target.closest('[data-suggestion]');if(option)take(+option.dataset.suggestion);});
    node('variable-fixes').addEventListener('click',event=>{const button=event.target.closest('[data-fix]');if(button)insert(editor.issue.suggestions[+button.dataset.fix].text,editor.issue.start,editor.issue.end);});
    node('variable-input-list').addEventListener('click',event=>{const button=event.target.closest('[data-insert]');if(button)insert(button.dataset.insert,field.selectionStart,field.selectionEnd);});
    node('variable-name').addEventListener('input',()=>{editor.name=node('variable-name').value;edited();});
    node('variable-display').addEventListener('change',()=>{editor.display=node('variable-display').value;edited();});
    node('variable-apply').addEventListener('click',()=>attempt(apply));node('variable-save').addEventListener('click',()=>attempt(()=>save(false)));node('variable-save-new').addEventListener('click',()=>attempt(()=>save(true)));
    node('variable-favourite').addEventListener('click',()=>attempt(()=>metadata('favourite')));node('variable-delete').addEventListener('click',()=>attempt(()=>metadata('delete')));
  }
  return {init,open,request,content,sources,useSource,displayName,displays:unit=>[...catalog?.displays?.[unit]||[]],builtin:id=>copy(catalog?.builtins.find(item=>item.id===id)??null)};
})();
if(typeof module!=='undefined')module.exports=VariableWorkspace;
