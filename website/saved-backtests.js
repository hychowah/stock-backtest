/* The library stores complete results on the local service, never browser quota. */
const SavedBacktests=(()=>{
  const node=id=>document.getElementById(id);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const captures=new Map();
  let records=[],busy=false,available=false,pendingDelete=null,operation=0;
  function message(text,error=false){node('saved-message').textContent=text;node('saved-message').className=error?'backtest-failed':'hint';}
  function defaultName(snapshot){
    if(snapshot.kind==='january')return 'January '+snapshot.settings.first+'–'+snapshot.settings.last;
    return (snapshot.kind==='random'?'Random dates':'Fixed dates')+' '+snapshot.settings.start+' → '+snapshot.settings.end;
  }
  function capture(settings,result,context,catalog){
    if(!result || settings.mode==='latest')return;
    captures.set(viewKey(),{version:1,kind:settings.mode,settings,result,context,catalog,captured_at:new Date().toISOString()});
    update();
  }
  function current(){return captures.get(viewKey());}
  function complete(snapshot){return snapshot && (snapshot.kind!=='random' || snapshot.result.trial_results?.length===snapshot.result.completed);}
  function update(){
    const snapshot=current();
    node('save-backtest').disabled=busy||!available||ScheduleView.isRunning()||!complete(snapshot)||records.length>=20;
    node('saved-count').textContent=records.length+' / 20';
    node('refresh-backtests').disabled=busy||!available;
    node('save-backtest-hint').textContent=!snapshot?'Run a historical backtest to save its settings, traded stocks and returns.':!complete(snapshot)?'This random result has no complete stock details. Run it with the updated server before saving.':records.length>=20?'All 20 slots are used. Delete a saved backtest to make room.':'Saves the displayed result and the settings used to run it. Pending setting changes are not included.';
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
    if(!response.ok)throw Error(value.error||'Could not access saved backtests.');
    return value;
  }
  async function refresh(){
    const value=await request();records=value.records;render();
  }
  async function perform(action){
    if(busy)return;
    busy=true;render();
    try{await action();}catch(error){message(error.message||'Could not reach the local service. Your saved records were kept.',true);}
    finally{busy=false;render();}
  }
  async function save(){
    const snapshot=current();
    if(!complete(snapshot)||ScheduleView.isRunning())return;
    const name=node('saved-name').value.trim()||defaultName(snapshot);
    // Serialize before awaiting: a new run or changed settings cannot change this save.
    const body=JSON.stringify({name,snapshot});
    await perform(async()=>{
      message('Saving complete backtest results…');
      const record=await request('',{method:'POST',headers:{'Content-Type':'application/json'},body});
      await refresh();node('saved-name').value='';message('Saved “'+record.name+'”. Its complete results are available below.');
    });
  }
  async function open(id){
    const number=++operation;
    await perform(async()=>{
      message('Opening saved backtest…');
      const record=await request('/'+encodeURIComponent(id));
      if(number!==operation)return;
      restoreSavedBacktest(record.snapshot);
      message('Opened “'+record.name+'”. Original settings, traded stocks and returns were restored without rerunning.');
    });
  }
  async function remove(id){
    await perform(async()=>{
      message('Deleting saved record…');
      await request('/'+encodeURIComponent(id),{method:'DELETE'});
      pendingDelete=null;await refresh();message('Saved backtest deleted. The displayed results remain available.');
    });
  }
  function init(){
    node('save-backtest').addEventListener('click',save);
    node('refresh-backtests').addEventListener('click',()=>perform(refresh));
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
  return {init,capture,update,current};
})();
