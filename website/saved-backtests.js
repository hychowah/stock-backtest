/* The library stores complete results on the local service, never browser quota. */
const SavedBacktests=(()=>{
  const node=id=>document.getElementById(id);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let current=()=>null,isRunning=()=>false,openRecord=()=>{};
  let queueRefresh=false;
  const disclosures=new Map();
  let comparisonIds=['',''],comparison=null,comparisonLoading=false,comparisonGeneration=0;
  let records=[],limit=100,sorting='newest',renaming=null,busy=false,available=false,pendingDelete=null,operation=0,mutation=0,refreshNumber=0,feedback=0;
  function message(text,error=false){node('saved-message').textContent=text;node('saved-message').className=error?'backtest-failed':'hint';}
  function defaultName(snapshot){
    if(snapshot.kind==='january')return 'January '+snapshot.settings.first+'–'+snapshot.settings.last;
    return (snapshot.kind==='random'?'Random dates':'Fixed dates')+' '+(snapshot.settings.calendar?.start??snapshot.settings.start)+' → '+(snapshot.settings.calendar?.end??snapshot.settings.end);
  }
  function complete(snapshot){return snapshot && snapshot.kind!=='latest' && (snapshot.version===3 || snapshot.kind!=='random' || snapshot.result.trial_results?.length===snapshot.result.completed);}
  function update(){
    const snapshot=current();
    node('save-backtest').disabled=busy||!available||isRunning()||!complete(snapshot)||records.length>=limit;
    node('saved-count').textContent=records.length+' / '+limit;
    node('refresh-backtests').disabled=busy||!available;
    node('saved-compare').disabled=busy||!available||comparisonLoading||comparisonIds.some(id=>!id)||comparisonIds[0]===comparisonIds[1];
    node('saved-compare-clear').disabled=!comparisonLoading&&!comparison&&comparisonIds.every(id=>!id);
    node('save-backtest-hint').textContent=!snapshot||snapshot.kind==='latest'?'Run a historical backtest to save its settings, traded stocks and returns.':!complete(snapshot)?'This random result has no complete stock details. Run it with the updated server before saving.':records.length>=limit?'All '+limit+' slots are used. Delete a saved backtest to make room.':'Saves the displayed result and the settings used to run it. Pending setting changes are not included.';
  }
  // List order uses stored summary values only. Missing performance stays last.
  function ordered(){
    const tie=(a,b)=>String(b.created_at).localeCompare(String(a.created_at))||a.id.localeCompare(b.id);
    return [...records].sort((a,b)=>{
      if(sorting==='newest')return tie(a,b);
      const knownA=Number.isFinite(a.cagr),knownB=Number.isFinite(b.cagr);
      if(knownA!==knownB)return knownA?-1:1;
      return (knownA?(a.cagr-b.cagr)*(sorting==='performance-asc'?1:-1):0)||tie(a,b);
    });
  }
  function render(){
    for(const id of disclosures.keys())if(!records.some(record=>record.id===id))disclosures.delete(id);
    const focused=document.activeElement,focusId=focused?.id,start=focused?.selectionStart,end=focused?.selectionEnd;
    node('saved-list').innerHTML=ordered().map(record=>{
      const kind={january:'January',custom:'Fixed dates',random:'Random dates'}[record.kind]||'Backtest';
      const cagr=record.cagr===null||record.cagr===undefined?'—':(record.cagr*100).toFixed(2)+'%';
      const description=kind+' · '+record.start+' → '+record.end+' · '+(record.kind==='random'?'Mean trial CAGR ':'CAGR ')+cagr;
      const actions=renaming?.id===record.id?'<label class="saved-rename">New name<input id="saved-rename-'+escape(record.id)+'" data-rename-input="'+escape(record.id)+'" value="'+escape(renaming.name)+'" maxlength="120"></label><button type="button" data-save-name="'+escape(record.id)+'">Save name</button><button type="button" data-cancel-name="'+escape(record.id)+'">Cancel</button>':pendingDelete===record.id?'<span>Delete this saved backtest?</span> <button type="button" data-confirm="'+escape(record.id)+'">Delete record</button> <button type="button" data-keep="'+escape(record.id)+'">Keep</button>':'<button type="button" data-open="'+escape(record.id)+'">Open</button> <button type="button" data-rename="'+escape(record.id)+'">Rename</button> <button type="button" data-delete="'+escape(record.id)+'">Delete</button>';
      return '<li><div><strong>'+escape(record.name)+'</strong><span>'+escape(description)+'</span><small>Saved '+escape(new Date(record.created_at).toLocaleString())+'</small><small class="saved-id">ID: '+escape(record.id)+'</small>'+parameterDisclosure(record.id)+'</div><div class="saved-actions">'+actions+'</div></li>';
    }).join('')||'<li>No saved backtests yet.</li>';
    node('saved-list').querySelectorAll('button,input').forEach(control=>control.disabled=busy);
    renderComparison();
    if(focusId&&!busy){const restored=node(focusId);restored?.focus?.({preventScroll:true});if(start!==null&&start!==undefined)restored?.setSelectionRange?.(start,end);}
    update();
  }
  // Disclosures reuse stored-artifact descriptions and retain parameter rows
  // only. They own no artifact, evidence reader, form or main-result lifetime.
  function parameterDisclosure(id){
    const state=disclosures.get(id);
    const content=state?.rows?'<dl>'+state.rows.map(row=>'<dt>'+escape(row.label)+'</dt><dd>'+escape(row.display)+'</dd>').join('')+'</dl>':
      state?.loading?'<p role="status">Loading recorded parameters…</p>':state?.error?'<p role="status">'+escape(state.error)+'</p><button type="button" data-parameters-retry="'+escape(id)+'">Retry parameters</button>':'<p>Expand to read the settings and filters used for this saved test.</p>';
    return '<details class="saved-parameters" data-parameters-id="'+escape(id)+'"'+(state?.open?' open':'')+'><summary id="saved-parameters-toggle-'+escape(id)+'">All parameters</summary>'+content+'</details>';
  }
  async function loadParameters(id){
    const state=disclosures.get(id);
    if(!state||state.loading)return;
    const generation=state.generation=(state.generation||0)+1;
    state.loading=true;state.error=null;render();
    try{
      const description=await describeSaved(id);
      if(disclosures.get(id)===state&&state.generation===generation)state.rows=description.parameters;
    }catch(error){
      if(disclosures.get(id)===state&&state.generation===generation)state.error=error.message||'Could not load recorded parameters. Retry when the service is available.';
    }finally{
      if(disclosures.get(id)===state&&state.generation===generation){state.loading=false;render();}
    }
  }
  function comparisonMessage(text,error=false){
    node('saved-compare-message').textContent=text;node('saved-compare-message').className=error?'backtest-failed':'hint';
  }
  function renderComparison(){
    if(comparisonIds.some(id=>id&&!records.some(record=>record.id===id))){
      comparisonGeneration++;comparisonLoading=false;comparison=null;
      comparisonIds=comparisonIds.map(id=>records.some(record=>record.id===id)?id:'');
      comparisonMessage('A selected saved test was deleted. Choose two saved tests again.');
    }
    for(const [index,id] of ['saved-compare-left','saved-compare-right'].entries()){
      const select=node(id);
      select.innerHTML='<option value="">Choose a saved test</option>'+ordered().map(record=>'<option value="'+escape(record.id)+'">'+escape(record.name)+' · '+escape(record.id)+'</option>').join('');
      select.value=comparisonIds[index];select.disabled=busy||!available;
    }
    const panel=node('saved-comparison');panel.hidden=!comparison;
    if(!comparison){panel.innerHTML='';return;}
    const selected=comparisonIds.map(id=>records.find(record=>record.id===id));
    const table=(title,rows)=>'<h3>'+title+'</h3><table><caption>'+title+' for the two selected saved tests</caption><thead><tr><th scope="col">Measure / parameter</th>'+selected.map((record,index)=>'<th scope="col">Test '+(index+1)+': '+escape(record.name)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr'+(row.different?' class="comparison-different"':'')+'><th scope="row">'+escape(row.label)+(row.different?'<span class="comparison-difference">Different</span>':'')+'</th><td>'+escape(row.left)+'</td><td>'+escape(row.right)+'</td></tr>').join('')+'</tbody></table>';
    panel.innerHTML='<div class="comparison-identities">'+selected.map((record,index)=>'<div><strong>Test '+(index+1)+': '+escape(record.name)+'</strong><small>ID: '+escape(record.id)+'</small></div>').join('')+'</div>'+comparison.notices.map(text=>'<p class="comparison-notice">'+escape(text)+'</p>').join('')+'<div class="saved-comparison-scroll" tabindex="0" role="region" aria-label="Saved test comparison">'+table('Recorded performance',comparison.performance)+table('Parameters',comparison.parameters)+'</div>';
  }
  function chooseComparison(index,value){
    comparisonIds[index]=value;comparisonGeneration++;comparison=null;comparisonLoading=false;
    comparisonMessage(comparisonIds[0]&&comparisonIds[0]===comparisonIds[1]?'Choose two different saved tests.':'Choose two saved tests, then select Compare.');
    render();
  }
  async function describeSaved(id){
    let artifact=null,acquisitionId=null;
    try{
      try{artifact=(await request('/'+encodeURIComponent(id))).snapshot;}
      catch(error){
        if(!error.requires_reader)throw error;
        // Keep the requested reader identity even if its response is lost, so
        // a failed acquisition can release its independently owned display.
        acquisitionId=Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
        artifact=await ResultArtifacts.acquire({kind:'saved',id},{},acquisitionId);
      }
      return BacktestComparison.describe(artifact);
    }finally{
      if(acquisitionId)ResultArtifacts.release(artifact||{version:3,evidence:{id:acquisitionId}});
    }
  }
  async function compareSelected(){
    if(busy||comparisonIds.some(id=>!id)||comparisonIds[0]===comparisonIds[1])return;
    const generation=++comparisonGeneration,ids=[...comparisonIds],descriptions=[];
    comparisonLoading=true;comparison=null;comparisonMessage('Loading the two saved tests…');render();
    try{
      for(const id of ids){
        descriptions.push(await describeSaved(id));
        if(generation!==comparisonGeneration)return;
      }
      comparison=BacktestComparison.compare(...descriptions);
      comparisonMessage('Comparison ready. Highlighted rows marked Different show recorded differences. The main results are unchanged.');
    }catch(error){if(generation===comparisonGeneration)comparisonMessage(error.message||'Could not compare these saved tests. Their records were kept.',true);}
    finally{if(generation===comparisonGeneration){comparisonLoading=false;render();}}
  }
  function clearComparison(){
    comparisonGeneration++;comparisonIds=['',''];comparison=null;comparisonLoading=false;
    comparisonMessage('Comparison cleared. The main results are unchanged.');render();
  }
  async function request(path='',options={}){
    const response=await fetch('/api/backtests'+path,options);
    let value;try{value=await response.json();}catch(_){throw Error('The saved-backtest service is unavailable. Start the updated website and reload this page.');}
    if(!response.ok){const error=Error(value.error||'Could not access saved backtests.');error.requires_reader=value.requires_reader;throw error;}
    return value;
  }
  async function refresh(){
    const number=++refreshNumber,revision=mutation;
    const value=await request();
    if(!Array.isArray(value.records))throw Error('The saved-list response is invalid.');
    if(number===refreshNumber&&revision===mutation){records=value.records;if(Number.isInteger(value.limit)&&value.limit>0)limit=value.limit;render();}
  }
  async function perform(action){
    if(busy)return;
    const ticket=++feedback;busy=true;render();
    try{await action(ticket);}catch(error){message(error.message||'Could not reach the local service. Your saved records were kept.',true);}
    finally{busy=false;render();if(queueRefresh)changed();}
  }
  // Reconciliation cannot turn an acknowledged mutation into a failed mutation.
  // Ignore stale reads and feedback if a newer library action has started.
  async function reconcile(success,ticket){
    try{await refresh();}
    catch(_){if(ticket===feedback)message(success+' The saved list could not be refreshed. Select Refresh saved list to try again.');}
  }
  async function save(){
    const snapshot=current();
    if(!complete(snapshot)||isRunning())return;
    const name=node('saved-name').value.trim()||defaultName(snapshot);
    // Serialize before awaiting: a new run or changed settings cannot change this save.
    const body=JSON.stringify(snapshot.version===3?{name,reader:snapshot.evidence.id}:{name,snapshot});
    await perform(async ticket=>{
      message('Saving complete backtest results…');
      const record=await request('',{method:'POST',headers:{'Content-Type':'application/json'},body});
      mutation++;records=[record,...records.filter(item=>item.id!==record.id)];render();node('saved-name').value='';
      const success='Saved “'+record.name+'”. Its complete results are available below.';message(success);
      void reconcile(success,ticket);
    });
  }
  async function open(id){
    const number=++operation,isCurrent=ResultArtifacts.opening();
    await perform(async()=>{
      message('Opening saved backtest…');
      let record;
      try{record=await request('/'+encodeURIComponent(id));}
      catch(error){if(!error.requires_reader)throw error;record={name:records.find(r=>r.id===id)?.name||'Backtest',snapshot:await ResultArtifacts.acquire({kind:'saved',id})};}
      if(number!==operation||!isCurrent()){ResultArtifacts.release(record.snapshot);return;}
      try{openRecord(record.snapshot);}catch(error){ResultArtifacts.release(record.snapshot);throw error;}
      message('Opened “'+record.name+'”. Original settings, traded stocks and returns were restored without rerunning.');
    });
  }
  async function remove(id){
    await perform(async ticket=>{
      message('Deleting saved record…');
      await request('/'+encodeURIComponent(id),{method:'DELETE'});
      mutation++;records=records.filter(record=>record.id!==id);pendingDelete=null;render();
      const success='Saved backtest deleted. The displayed results remain available.';message(success);
      void reconcile(success,ticket);
    });
  }
  async function rename(id){
    if(renaming?.id!==id)return;
    const name=renaming.name.trim();
    if(!name||name.length>120){message('Use a backtest name with 1–120 characters.',true);return;}
    await perform(async ticket=>{
      const record=await request('/'+encodeURIComponent(id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
      mutation++;records=records.map(item=>item.id===id?record:item);renaming=null;render();
      const success='Renamed to “'+record.name+'”. Its ID and stored results are unchanged.';message(success);
      void reconcile(success,ticket);
    });
  }
  function changed(){
    // Queue completion is an external mutation. Reconcile after an active local
    // mutation so its stale-read fence cannot discard the only notification.
    queueRefresh=true;
    if(busy||renaming||!available)return;
    queueRefresh=false;void perform(refresh);
  }
  function init(access){
    current=access.current;isRunning=access.isRunning;openRecord=access.open;
    node('saved-compare-left').addEventListener('change',()=>chooseComparison(0,node('saved-compare-left').value));
    node('saved-compare-right').addEventListener('change',()=>chooseComparison(1,node('saved-compare-right').value));
    node('saved-compare').addEventListener('click',compareSelected);
    node('saved-compare-clear').addEventListener('click',clearComparison);
    node('save-backtest').addEventListener('click',save);
    node('refresh-backtests').addEventListener('click',()=>perform(async()=>{await refresh();message('Saved list refreshed.');}));
    node('saved-sort').addEventListener('change',()=>{sorting=node('saved-sort').value;render();});
    // Native toggle does not bubble. Capture it on the persistent list. An open
    // disclosure recreated by rendering cannot restart a pending/cached load.
    node('saved-list').addEventListener('toggle',event=>{
      const id=event.target.dataset?.parametersId;
      if(!id||!records.some(record=>record.id===id))return;
      let state=disclosures.get(id);
      if(!state){state={open:false,loading:false,rows:null,error:null};disclosures.set(id,state);}
      state.open=event.target.open;
      if(state.open&&!state.loading&&!state.rows&&!state.error)return loadParameters(id);
    },true);
    node('saved-list').addEventListener('input',event=>{
      if(renaming?.id===event.target.dataset.renameInput)renaming.name=event.target.value;
    });
    node('saved-list').addEventListener('keydown',event=>{
      if(!renaming||renaming.id!==event.target.dataset.renameInput)return;
      if(event.key==='Enter'){event.preventDefault();return rename(renaming.id);}
      if(event.key==='Escape'){event.preventDefault();renaming=null;render();if(queueRefresh)changed();}
    });
    node('saved-list').addEventListener('click',event=>{
      if(busy)return;
      const data=event.target.dataset;
      if(data.parametersRetry)return loadParameters(data.parametersRetry);
      if(data.saveName)return rename(data.saveName);
      if(data.rename){renaming={id:data.rename,name:records.find(record=>record.id===data.rename).name};pendingDelete=null;render();node('saved-rename-'+data.rename)?.focus?.();return;}
      if(data.cancelName){renaming=null;render();if(queueRefresh)changed();return;}
      if(data.open)return open(data.open);
      if(data.confirm)return remove(data.confirm);
      if(data.delete){pendingDelete=data.delete;render();}
      if(data.keep){pendingDelete=null;render();}
    });
    available=typeof fetch==='function' && typeof location!=='undefined' && location.protocol!=='file:';
    if(available)perform(refresh);
    else message('Saved backtests use the local website service opened by backtest-web.cmd.');
    update();
  }
  return {init,update,changed};
})();
