/* The library stores complete results on the local service, never browser quota. */
const SavedBacktests=(()=>{
  const node=id=>document.getElementById(id);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let current=()=>null,isRunning=()=>false,openRecord=()=>{};
  let records=[],busy=false,available=false,pendingDelete=null,operation=0,mutation=0,refreshNumber=0,feedback=0;
  function message(text,error=false){node('saved-message').textContent=text;node('saved-message').className=error?'backtest-failed':'hint';}
  function defaultName(snapshot){
    if(snapshot.kind==='january')return 'January '+snapshot.settings.first+'–'+snapshot.settings.last;
    return (snapshot.kind==='random'?'Random dates':'Fixed dates')+' '+(snapshot.settings.calendar?.start??snapshot.settings.start)+' → '+(snapshot.settings.calendar?.end??snapshot.settings.end);
  }
  function complete(snapshot){return snapshot && snapshot.kind!=='latest' && (snapshot.version===3 || snapshot.kind!=='random' || snapshot.result.trial_results?.length===snapshot.result.completed);}
  function update(){
    const snapshot=current();
    node('save-backtest').disabled=busy||!available||isRunning()||!complete(snapshot)||records.length>=20;
    node('saved-count').textContent=records.length+' / 20';
    node('refresh-backtests').disabled=busy||!available;
    node('save-backtest-hint').textContent=!snapshot||snapshot.kind==='latest'?'Run a historical backtest to save its settings, traded stocks and returns.':!complete(snapshot)?'This random result has no complete stock details. Run it with the updated server before saving.':records.length>=20?'All 20 slots are used. Delete a saved backtest to make room.':'Saves the displayed result and the settings used to run it. Pending setting changes are not included.';
  }
  function render(){
    node('saved-list').innerHTML=records.map(record=>{
      const kind={january:'January',custom:'Fixed dates',random:'Random dates'}[record.kind]||'Backtest';
      const cagr=record.cagr===null||record.cagr===undefined?'—':(record.cagr*100).toFixed(2)+'%';
      const description=kind+' · '+record.start+' → '+record.end+' · '+(record.kind==='random'?'Mean trial CAGR ':'CAGR ')+cagr;
      const actions=pendingDelete===record.id?'<span>Delete this saved backtest?</span> <button type="button" data-confirm="'+escape(record.id)+'">Delete record</button> <button type="button" data-keep="'+escape(record.id)+'">Keep</button>':'<button type="button" data-open="'+escape(record.id)+'">Open</button> <button type="button" data-delete="'+escape(record.id)+'">Delete</button>';
      return '<li><div><strong>'+escape(record.name)+'</strong><span>'+escape(description)+'</span><small>Saved '+escape(new Date(record.created_at).toLocaleString())+'</small></div><div class="saved-actions">'+actions+'</div></li>';
    }).join('')||'<li>No saved backtests yet.</li>';
    node('saved-list').querySelectorAll('button').forEach(button=>button.disabled=busy);
    update();
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
    if(number===refreshNumber&&revision===mutation){records=value.records;render();}
  }
  async function perform(action){
    if(busy)return;
    const ticket=++feedback;busy=true;render();
    try{await action(ticket);}catch(error){message(error.message||'Could not reach the local service. Your saved records were kept.',true);}
    finally{busy=false;render();}
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
  function init(access){
    current=access.current;isRunning=access.isRunning;openRecord=access.open;
    node('save-backtest').addEventListener('click',save);
    node('refresh-backtests').addEventListener('click',()=>perform(async()=>{await refresh();message('Saved list refreshed.');}));
    node('saved-list').addEventListener('click',event=>{
      const data=event.target.dataset;
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
  return {init,update};
})();
