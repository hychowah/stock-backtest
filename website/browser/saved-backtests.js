/* The library stores complete results on the local service, never browser quota.
   Its records are the Finished rows of Runs. The panel above the rows is derived
   from the ticked rows and one description per ticked saved id. */
const SavedBacktests=(()=>{
  const node=id=>document.getElementById(id);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let current=()=>null,isRunning=()=>false,openRecord=()=>{},copySettings=()=>{};
  let queueRefresh=false;
  // Descriptions reuse stored-artifact descriptions and keep their rows only. They
  // own no artifact, evidence reader, form or main-result lifetime. An id that
  // leaves the list leaves the ticks and the descriptions.
  const ticked=new Set(),descriptions=new Map(),opened={};
  let loading=false,refocus=null;
  const headings={name:'Name',cagr:'CAGR',saved:'Saved'},directions={name:1,cagr:-1,saved:-1};
  let records=[],limit=100,sorting={key:'saved',direction:-1},renaming=null,busy=false,available=false,pendingDelete=null,operation=0,mutation=0,refreshNumber=0,feedback=0;
  // Save reports beside its button in Result review. Every list action reports above the Finished rows.
  const say=id=>(text,error=false)=>{node(id).textContent=text;node(id).className=error?'backtest-failed':'hint';};
  const message=say('saved-status'),saveMessage=say('saved-message');
  const when=value=>new Date(value).toLocaleString(undefined,{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
  function defaultName(snapshot){
    if(snapshot.kind==='january')return 'January '+snapshot.settings.first+'–'+snapshot.settings.last;
    return (snapshot.kind==='random'?'Random dates':'Fixed dates')+' '+(snapshot.settings.calendar?.start??snapshot.settings.start)+' → '+(snapshot.settings.calendar?.end??snapshot.settings.end);
  }
  function complete(snapshot){return snapshot && snapshot.kind!=='latest' && ([3,4].includes(snapshot.version) || snapshot.kind!=='random' || snapshot.result.trial_results?.length===snapshot.result.completed);}
  function update(){
    const snapshot=current();
    node('save-backtest').disabled=busy||!available||isRunning()||!complete(snapshot)||records.length>=limit;
    node('saved-count').textContent=records.length+' / '+limit;
    for(const [key,label] of Object.entries(headings))node('saved-sort-'+key).textContent=label+(sorting.key!==key?'':sorting.direction>0?' ↑':' ↓');
    node('save-backtest-hint').textContent=!snapshot||snapshot.kind==='latest'?'Run a historical backtest to save its settings, traded stocks and returns.':!complete(snapshot)?'This random result has no complete stock details. Run it with the updated server before saving.':records.length>=limit?'All '+limit+' slots are used. Delete a finished test in Runs to make room.':'Saves the original completed result and its submitted settings. Exploration summaries and pending settings are not included.';
  }
  // List order uses stored summary values only. Names sort with their numbers in
  // number order. A missing CAGR stays last in both directions. Equal values show
  // the newest saved first, then the lower id.
  function ordered(){
    const tie=(a,b)=>String(b.created_at).localeCompare(String(a.created_at))||a.id.localeCompare(b.id),{key,direction}=sorting;
    return [...records].sort((a,b)=>{
      if(key==='saved')return -direction*tie(a,b);
      if(key==='name')return direction*String(a.name).localeCompare(String(b.name),undefined,{numeric:true})||tie(a,b);
      const knownA=Number.isFinite(a.cagr),knownB=Number.isFinite(b.cagr);
      if(knownA!==knownB)return knownA?-1:1;
      return (knownA?(a.cagr-b.cagr)*direction:0)||tie(a,b);
    });
  }
  // One line per test in the columns that the In progress rows use. The name opens
  // the result; the other actions wait in the row control. Every control has a
  // stable id, so the focus returns to it when the list is drawn again.
  function render(){
    const list=node('saved-list'),known=new Set(records.map(record=>record.id));
    for(const kept of [ticked,descriptions])for(const id of [...kept.keys()])if(!known.has(id))kept.delete(id);
    const open=new Set([...list.querySelectorAll('details[open]')].map(control=>control.dataset.menu)),focused=document.activeElement;
    if(focused?.id)refocus={id:focused.id,start:focused.selectionStart,end:focused.selectionEnd};
    else if(focused&&focused!==document.body)refocus=null;
    list.innerHTML=ordered().map(record=>{
      const id=escape(record.id),name=escape(record.name);
      const kind={january:'January',custom:'Fixed dates',random:'Random'+(record.trials?' · '+escape(record.trials)+' trials':' dates')}[record.kind]||'Backtest';
      const cagr=record.cagr===null||record.cagr===undefined?'—':(record.cagr*100).toFixed(2)+'%';
      const button=(key,label)=>'<button type="button" id="saved-do-'+key+'-'+id+'" data-'+key+'="'+id+'">'+label+'</button>';
      const actions=renaming?.id===record.id?'<label class="saved-rename">New name<input id="saved-rename-'+id+'" data-rename-input="'+id+'" value="'+escape(renaming.name)+'" maxlength="120"></label>'+button('save-name','Save name')+button('cancel-name','Cancel'):pendingDelete===record.id?'<span>Delete this finished test?</span>'+button('confirm','Delete test')+button('keep','Keep'):button('copy','Tune')+button('rename','Rename')+button('delete','Delete');
      return '<li class="run-row"><input type="checkbox" id="saved-tick-'+id+'" data-tick="'+id+'" aria-label="Compare '+name+'"'+(ticked.has(record.id)?' checked':'')+'><button type="button" class="run-name" id="saved-open-'+id+'" data-open="'+id+'" title="Open the result of '+name+'"><span>'+name+'</span></button><span class="run-status"><span class="queue-state">Finished</span></span><span class="run-type">'+kind+'</span><span class="run-window">'+escape(record.start+' → '+record.end)+'</span><span class="run-cagr"'+(record.kind==='random'?' title="Mean trial CAGR"':'')+'>'+cagr+'</span><span class="run-time" title="'+escape(new Date(record.created_at).toLocaleString())+'">'+escape(when(record.created_at))+'</span><details class="run-menu" data-menu="'+id+'"'+(open.has(record.id)||renaming?.id===record.id||pendingDelete===record.id?' open':'')+'><summary id="saved-menu-'+id+'" aria-label="Actions for '+name+'" title="Actions">⋯</summary><div class="run-actions">'+actions+'</div></details></li>';
    }).join('')||'<li class="run-empty">No finished tests yet.</li>';
    // Ticks stay usable while a list action runs.
    list.querySelectorAll('button,input:not([type=checkbox])').forEach(control=>control.disabled=busy);
    renderPanel();
    // A control that is disabled while the list is busy gets its focus back afterwards.
    const target=refocus&&node(refocus.id);
    if(!target)refocus=null;
    else if(!target.disabled){target.focus?.({preventScroll:true});if(refocus.start!==null&&refocus.start!==undefined)target.setSelectionRange?.(refocus.start,refocus.end);refocus=null;}
    update();
  }
  const menu=id=>node('saved-menu-'+id)?.focus?.({preventScroll:true});
  // The panel shows the ticked tests whose descriptions are read. One test shows
  // its headline, its saved ID and every setting in plain wording, with the exact
  // recorded text in a closed disclosure. More tests show one column per test in
  // list order: the requested settings that differ, then the headlines, then
  // every measure and setting in a closed disclosure. Only setting rows carry the
  // difference marker. While another description is read, the panel keeps what it
  // shows and its top line says so. A redraw keeps the open disclosure and the
  // sideways scroll.
  function renderPanel(){
    const panel=node('saved-comparison'),chosen=ordered().filter(record=>ticked.has(record.id)),ready=chosen.filter(record=>descriptions.has(record.id));
    const [disclosure]=panel.querySelectorAll('details'),scrolled=[...panel.querySelectorAll('.comparison-scroll')].map(box=>box.scrollLeft);
    if(disclosure)opened[disclosure.dataset.kind]=disclosure.open;
    panel.hidden=!chosen.length;
    if(!chosen.length){panel.innerHTML='';return;}
    const reading=chosen.length-ready.length,described=ready.map(record=>descriptions.get(record.id)),notes=notices=>notices.map(text=>'<p class="comparison-notice">'+escape(text)+'</p>').join('');
    const fold=(kind,title,content)=>'<details data-kind="'+kind+'"'+(opened[kind]?' open':'')+'><summary>'+title+'</summary>'+content+'</details>';
    let body='';
    if(ready.length===1){
      const list=(name,rows,key='display')=>'<dl class="'+name+'">'+rows.map(row=>'<div><dt>'+escape(row.label)+'</dt><dd>'+escape(row[key])+'</dd></div>').join('')+'</dl>',exact=described[0].parameters.filter(row=>row.exact);
      body='<h4>'+escape(ready[0].name)+'<small class="saved-id">Saved ID: '+escape(ready[0].id)+'</small></h4>'+list('comparison-headline',described[0].headline)+notes(described[0].notices)+list('comparison-settings',described[0].parameters)+
        (exact.length?fold('exact','Exact recorded values',list('comparison-settings',exact,'exact')):'');
    }else if(ready.length){
      // Recorded facts, such as a fresh random date set, are not requested settings: they show in the full list only.
      const compared=BacktestComparison.compare(described),differing=compared.parameters.filter(row=>row.different&&!row.recorded);
      const group=(title,rows,marked)=>'<tbody><tr class="comparison-group"><th scope="rowgroup" colspan="'+(ready.length+1)+'">'+title+'</th></tr>'+rows.map(row=>'<tr'+(marked&&row.different?' class="comparison-different"':'')+'><th scope="row">'+escape(row.label)+(marked&&row.different?'<span class="comparison-difference">Different</span>':'')+'</th>'+row.cells.map(cell=>'<td>'+escape(cell)+'</td>').join('')+'</tr>').join('')+'</tbody>';
      // Each table keeps the same column widths; many ticked tests scroll sideways inside the panel.
      const table=(caption,groups)=>'<div class="comparison-scroll"><table style="min-width:'+(170+140*ready.length)+'px"><caption>'+caption+'</caption><thead><tr><td></td>'+ready.map(record=>'<th scope="col" title="'+escape(record.name)+'"><span>'+escape(record.name)+'</span></th>').join('')+'</tr></thead>'+groups+'</table></div>';
      body=notes(compared.notices)+table('Comparison of '+ready.length+' ticked tests',group(differing.length?'Settings that differ':'Same settings',differing)+group('Headline',compared.headline))+
        fold('all','All measures and settings',table('All measures and settings of the ticked tests',group('Measures',compared.performance)+group('Settings',[{label:'Saved ID',cells:ready.map(record=>record.id)},...compared.parameters],true)));
    }
    panel.innerHTML='<div class="comparison-bar"><strong>'+chosen.length+(chosen.length>1?' tests ticked':' test ticked')+'</strong><span role="status">'+(reading?'Reading '+(reading>1?reading+' stored results':'1 stored result')+'…':'')+'</span><button type="button" id="saved-clear" data-clear>Clear</button></div>'+body;
    panel.querySelectorAll('.comparison-scroll').forEach((box,at)=>{box.scrollLeft=scrolled[at]||0;});
  }
  // One loader reads the descriptions of the ticked rows, one at a time. A row
  // that nobody ticked is never read. A failed read is not kept: the row loses
  // its tick and the status line gives the reason. The temporary evidence reader
  // closes when the description is read.
  async function load(){
    if(loading)return;
    loading=true;
    try{
      for(let id;(id=[...ticked].find(id=>!descriptions.has(id)));){
        try{
          const used=await ResultArtifacts.use({kind:'saved',id},artifact=>BacktestComparison.describe(artifact));
          if(!used.consumed)throw Error('Its stored result was not read.');
          if(records.some(record=>record.id===id))descriptions.set(id,used.value);else ticked.delete(id);
          renderPanel();
        }catch(error){
          const record=records.find(record=>record.id===id);
          if(ticked.delete(id)&&record)message('Could not read “'+record.name+'”. '+(error.message||'Tick it again when the service is available.'),true);
          render();
        }
      }
    }finally{loading=false;}
  }
  async function request(path='',options={}){
    const response=await fetch('/api/backtests'+path,options);
    let value;try{value=await response.json();}catch(_){throw Error('The saved-backtest service is unavailable. Start the updated website and reload this page.');}
    if(!response.ok){const error=Error(value.error||'Could not access the finished tests.');error.requires_reader=value.requires_reader;throw error;}
    return value;
  }
  async function refresh(){
    const number=++refreshNumber,revision=mutation;
    const value=await request();
    if(!Array.isArray(value.records))throw Error('The saved-list response is invalid.');
    if(number===refreshNumber&&revision===mutation){records=value.records;if(Number.isInteger(value.limit)&&value.limit>0)limit=value.limit;render();}
  }
  async function perform(action,report=message){
    if(busy)return;
    const ticket=++feedback;busy=true;render();
    try{await action(ticket);}catch(error){report(error.message||'Could not reach the local service. Your saved records were kept.',true);}
    finally{busy=false;render();if(queueRefresh)changed();}
  }
  // Reconciliation cannot turn an acknowledged mutation into a failed mutation.
  // Ignore stale reads and feedback if a newer library action has started.
  async function reconcile(success,ticket,report=message){
    try{await refresh();}
    catch(_){if(ticket===feedback)report(success+' The Finished list could not be refreshed. Select Refresh in Runs to try again.');}
  }
  async function save(){
    const snapshot=current();
    if(!complete(snapshot)||isRunning())return;
    const name=node('saved-name').value.trim()||defaultName(snapshot);
    // Serialize before awaiting: a new run or changed settings cannot change this save.
    // A saved January result is saved again as its stored record.
    const body=JSON.stringify([3,4].includes(snapshot.version)?{name,reader:snapshot.evidence.id}:{name,snapshot:snapshot.record??snapshot});
    await perform(async ticket=>{
      saveMessage('Saving complete backtest results…');
      const record=await request('',{method:'POST',headers:{'Content-Type':'application/json'},body});
      mutation++;records=[record,...records.filter(item=>item.id!==record.id)];render();node('saved-name').value='';
      const success='Saved “'+record.name+'”. Its complete results are under Finished in Runs.';saveMessage(success);
      void reconcile(success,ticket,saveMessage);
    },saveMessage);
  }
  async function open(id){
    const number=++operation,isCurrent=ResultArtifacts.opening();
    await perform(async()=>{
      message('Opening the stored result…');
      const used=await ResultArtifacts.use({kind:'saved',id},(artifact,record)=>openRecord(artifact,record?.name||records.find(row=>row.id===id)?.name),{current:()=>number===operation&&isCurrent()});
      if(used.consumed)message('Opened “'+(used.record?.name||records.find(r=>r.id===id)?.name||'Backtest')+'” without rerunning it.');
    });
  }
  async function copy(id){
    await perform(async()=>{
      message('Loading saved settings…');
      const used=await ResultArtifacts.use({kind:'saved',id},artifact=>copySettings(artifact));
      if(used.consumed)message('Copied settings from “'+(used.record?.name||records.find(r=>r.id===id)?.name||'Backtest')+'”. Adjust the strategy controls, then select Run backtest or Add to queue. Auto-run is off.');
    });
  }
  async function remove(id){
    await perform(async ticket=>{
      message('Deleting the finished test…');
      await request('/'+encodeURIComponent(id),{method:'DELETE'});
      mutation++;records=records.filter(record=>record.id!==id);pendingDelete=null;render();
      const success='Finished test deleted. The displayed results remain available.';message(success);
      void reconcile(success,ticket);
    });
  }
  async function rename(id){
    if(renaming?.id!==id)return;
    const name=renaming.name.trim();
    if(!name||name.length>120){message('Use a backtest name with 1–120 characters.',true);return;}
    await perform(async ticket=>{
      const record=await request('/'+encodeURIComponent(id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
      mutation++;records=records.map(item=>item.id===id?record:item);renaming=null;render();menu(id);
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
    current=access.current;isRunning=access.isRunning;openRecord=access.open;copySettings=access.copy;
    node('save-backtest').addEventListener('click',save);
    // The one Refresh of Runs also reads the Finished rows again.
    node('queue-refresh').addEventListener('click',()=>available?perform(async()=>{await refresh();message('Finished tests refreshed.');}):undefined);
    node('saved-head').addEventListener('click',event=>{
      const key=event.target.dataset.sort;if(!key)return;
      sorting={key,direction:sorting.key===key?-sorting.direction:directions[key]};render();
    });
    // The panel compares 8 tests at most. Clear removes every tick.
    node('saved-list').addEventListener('change',event=>{
      const id=event.target.dataset.tick;if(!id)return;
      if(event.target.checked&&ticked.size>=8){event.target.checked=false;message('Untick a test first. The panel compares 8 tests at most.');return;}
      if(event.target.checked)ticked.add(id);else ticked.delete(id);
      renderPanel();return load();
    });
    node('saved-comparison').addEventListener('click',event=>{if('clear' in event.target.dataset){ticked.clear();render();}});
    node('saved-list').addEventListener('input',event=>{
      if(renaming&&renaming.id===event.target.dataset.renameInput)renaming.name=event.target.value;
    });
    node('saved-list').addEventListener('keydown',event=>{
      if(!renaming||renaming.id!==event.target.dataset.renameInput)return;
      if(event.key==='Enter'){event.preventDefault();return rename(renaming.id);}
      if(event.key==='Escape'){event.preventDefault();const id=renaming.id;renaming=null;render();menu(id);if(queueRefresh)changed();}
    });
    node('saved-list').addEventListener('click',event=>{
      if(busy)return;
      const data=event.target.dataset;
      if(data.saveName)return rename(data.saveName);
      if(data.rename){renaming={id:data.rename,name:records.find(record=>record.id===data.rename).name};pendingDelete=null;render();node('saved-rename-'+data.rename)?.focus?.();return;}
      if(data.cancelName){renaming=null;render();menu(data.cancelName);if(queueRefresh)changed();return;}
      if(data.open)return open(data.open);
      if(data.copy)return copy(data.copy);
      if(data.confirm)return remove(data.confirm);
      if(data.delete){pendingDelete=data.delete;render();}
      if(data.keep){pendingDelete=null;render();menu(data.keep);}
    });
    available=typeof fetch==='function' && typeof location!=='undefined' && location.protocol!=='file:';
    if(available)perform(refresh);
    else message('Finished tests use the local website service opened by backtest-web.cmd.');
    update();
  }
  return {init,update,changed};
})();
