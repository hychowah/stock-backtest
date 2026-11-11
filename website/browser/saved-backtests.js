/* The library stores complete results on the local service, never browser quota.
   Its records are the Saved backtests rows of Runs. Details of a row shows the
   settings of that test in place. The panel above the rows compares the ticked
   rows. Both read one description per saved id that the user ticked or opened. */
const SavedBacktests=(()=>{
  const node=id=>document.getElementById(id);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let current=()=>null,isRunning=()=>false,openRecord=()=>{},copySettings=()=>{};
  let queueRefresh=false;
  // Descriptions reuse stored-artifact descriptions and keep their rows only. They
  // own no artifact, evidence reader, form or main-result lifetime. viewed holds
  // the rows whose open Details waits for its description. failures holds the
  // reason of a failed read, shown in that row until Retry or a new tick. An id
  // that leaves the list leaves all of them.
  const ticked=new Set(),viewed=new Set(),descriptions=new Map(),failures=new Map();
  let loading=false,refocus=null,allOpen=false;
  const headings={name:'Name',cagr:'CAGR',saved:'Saved'},directions={name:1,cagr:-1,saved:-1};
  let records=[],limit=100,sorting={key:'saved',direction:-1},renaming=null,busy=false,available=false,pendingDelete=null,operation=0,mutation=0,refreshNumber=0,feedback=0;
  // Save reports beside its button in Result review. Every list action reports above the Saved backtests rows.
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
    node('save-backtest-hint').textContent=!snapshot||snapshot.kind==='latest'?'Run a historical backtest to save its settings, traded stocks and returns.':!complete(snapshot)?'This random result has no complete stock details. Run it with the updated server before saving.':records.length>=limit?'All '+limit+' slots are used. Delete a saved backtest in Runs & saved to make room.':'Saves the original completed result and its submitted settings. Exploration summaries and pending settings are not included.';
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
  // The Details of a row: one line with the market, the test type, the window and
  // the interval, then every other setting in plain wording, the headline, the
  // saved ID and the exact recorded text in a closed disclosure. Before the read
  // it says so. After a failed read it gives the reason and Retry.
  function settings(record,exactOpen){
    const id=escape(record.id),description=descriptions.get(record.id),line=text=>'<p>'+escape(text)+'</p>';
    if(failures.has(record.id))return '<p class="backtest-failed" role="status">'+escape(failures.get(record.id))+' <button type="button" id="saved-do-retry-'+id+'" data-retry="'+id+'">Retry</button></p>';
    if(!description)return '<p role="status">Reading the saved settings…</p>';
    const shown=key=>description.parameters.find(row=>row.key===key)?.display,first=['mode','market','currency','start','end','interval','first','last','trials'];
    const rows=description.parameters.filter(row=>!first.includes(row.key)),exact=rows.filter(row=>row.exact);
    return line([shown('market'),shown('currency'),shown('mode')+(shown('trials')?' · '+shown('trials')+' trials':''),shown('first')?shown('first')+'–'+shown('last'):shown('start')&&shown('start')+' → '+shown('end'),shown('interval')&&'every '+shown('interval')].filter(Boolean).join(' · '))+
      rows.map(row=>line(row.label+': '+row.display)).join('')+line(description.headline.map(row=>row.label+' '+row.display).join(' · '))+'<p class="saved-id">Saved ID: '+id+'</p>'+
      (exact.length?'<details data-exact="'+id+'"'+(exactOpen?' open':'')+'><summary id="saved-exact-'+id+'">Exact recorded values</summary>'+exact.map(row=>line(row.label+': '+row.exact)).join('')+'</details>':'');
  }
  // One line per test in the columns that the In progress rows use. The name opens
  // the result. Details opens the settings and the other actions below the row.
  // Every control has a stable id, so the focus returns to it when the list is
  // drawn again; an open Details and its open exact values stay open.
  function render(){
    const list=node('saved-list'),known=new Set(records.map(record=>record.id));
    for(const kept of [ticked,viewed,descriptions,failures])for(const id of [...kept.keys()])if(!known.has(id))kept.delete(id);
    const opened=name=>new Set([...list.querySelectorAll('details[open][data-'+name+']')].map(control=>control.dataset[name]));
    const open=opened('menu'),exactOpen=opened('exact'),focused=document.activeElement;
    // An open Details always gets its description, also when the list is drawn again before its toggle arrives.
    for(const id of open)if(known.has(id)&&!descriptions.has(id)&&!failures.has(id))viewed.add(id);
    if(focused?.id)refocus={id:focused.id,start:focused.selectionStart,end:focused.selectionEnd};
    else if(focused&&focused!==document.body)refocus=null;
    list.innerHTML=ordered().map(record=>{
      const id=escape(record.id),name=escape(record.name);
      const kind={january:'January',custom:'Fixed dates',random:'Random'+(record.trials?' · '+escape(record.trials)+' trials':' dates')}[record.kind]||'Backtest';
      const cagr=record.cagr===null||record.cagr===undefined?'—':(record.cagr*100).toFixed(2)+'%';
      const button=(key,label)=>'<button type="button" id="saved-do-'+key+'-'+id+'" data-'+key+'="'+id+'">'+label+'</button>';
      const actions=renaming?.id===record.id?'<label class="saved-rename">New name<input id="saved-rename-'+id+'" data-rename-input="'+id+'" value="'+escape(renaming.name)+'" maxlength="120"></label>'+button('save-name','Save name')+button('cancel-name','Cancel'):pendingDelete===record.id?'<span>Delete this saved backtest?</span>'+button('confirm','Delete record')+button('keep','Keep'):button('copy','Tune')+button('rename','Rename')+button('delete','Delete');
      return '<li class="run-row"><input type="checkbox" id="saved-tick-'+id+'" data-tick="'+id+'" aria-label="Compare '+name+'"'+(ticked.has(record.id)?' checked':'')+'><button type="button" class="run-name" id="saved-open-'+id+'" data-open="'+id+'" title="Open the result of '+name+'"><span>'+name+'</span></button><span class="run-status"><span class="queue-state">Saved</span></span><span class="run-type">'+kind+'</span><span class="run-window">'+escape(record.start+' → '+record.end)+'</span><span class="run-cagr"'+(record.kind==='random'?' title="Mean trial CAGR"':'')+'>'+cagr+'</span><span class="run-time" title="'+escape(new Date(record.created_at).toLocaleString())+'">'+escape(when(record.created_at))+'</span><details class="run-menu" data-menu="'+id+'"'+(open.has(record.id)||renaming?.id===record.id||pendingDelete===record.id?' open':'')+'><summary id="saved-menu-'+id+'" aria-label="Details of '+name+'">Details</summary>'+settings(record,exactOpen.has(record.id))+'<div class="run-actions">'+actions+'</div></details></li>';
    }).join('')||'<li class="run-empty">No saved backtests yet.</li>';
    // Ticks stay usable while a list action runs.
    list.querySelectorAll('button,input:not([type=checkbox])').forEach(control=>control.disabled=busy);
    renderPanel();
    // A control that is disabled while the list is busy gets its focus back afterwards.
    const target=refocus&&node(refocus.id);
    if(!target)refocus=null;
    else if(!target.disabled){target.focus?.({preventScroll:true});if(refocus.start!==null&&refocus.start!==undefined)target.setSelectionRange?.(refocus.start,refocus.end);refocus=null;}
    update();
    if(viewed.size)void load();
  }
  const menu=id=>node('saved-menu-'+id)?.focus?.({preventScroll:true});
  // The panel compares the ticked tests whose descriptions are read: one column
  // per test in list order, with the requested settings that differ, then the
  // headlines, then every measure and setting in a closed disclosure. Only
  // setting rows carry the difference marker. One tick shows the top line only.
  // While another description is read, the panel keeps what it shows and its top
  // line says so. A redraw keeps the open disclosure and the sideways scroll.
  function renderPanel(){
    const panel=node('saved-comparison'),chosen=ordered().filter(record=>ticked.has(record.id)),ready=chosen.filter(record=>descriptions.has(record.id));
    const [disclosure]=panel.querySelectorAll('details'),scrolled=[...panel.querySelectorAll('.comparison-scroll')].map(box=>box.scrollLeft);
    if(disclosure)allOpen=disclosure.open;
    panel.hidden=!chosen.length;
    if(!chosen.length){panel.innerHTML='';return;}
    const reading=chosen.length-ready.length;
    let body='';
    if(ready.length>1){
      // Recorded facts, such as a fresh random date set, are not requested settings: they show in the full list only.
      const compared=BacktestComparison.compare(ready.map(record=>descriptions.get(record.id))),differing=compared.parameters.filter(row=>row.different&&!row.recorded);
      const group=(title,rows,marked)=>'<tbody><tr class="comparison-group"><th scope="rowgroup" colspan="'+(ready.length+1)+'">'+title+'</th></tr>'+rows.map(row=>'<tr'+(marked&&row.different?' class="comparison-different"':'')+'><th scope="row">'+escape(row.label)+(marked&&row.different?'<span class="comparison-difference">Different</span>':'')+'</th>'+row.cells.map(cell=>'<td>'+escape(cell)+'</td>').join('')+'</tr>').join('')+'</tbody>';
      // Each table keeps the same column widths; many ticked tests scroll sideways inside the panel.
      const table=(caption,groups)=>'<div class="comparison-scroll"><table style="min-width:'+(170+140*ready.length)+'px"><caption>'+caption+'</caption><thead><tr><td></td>'+ready.map(record=>'<th scope="col" title="'+escape(record.name)+'"><span>'+escape(record.name)+'</span></th>').join('')+'</tr></thead>'+groups+'</table></div>';
      body=compared.notices.map(text=>'<p class="comparison-notice">'+escape(text)+'</p>').join('')+table('Comparison of '+ready.length+' ticked tests',group(differing.length?'Settings that differ':'Same settings',differing)+group('Headline',compared.headline))+
        '<details'+(allOpen?' open':'')+'><summary>All measures and settings</summary>'+table('All measures and settings of the ticked tests',group('Measures',compared.performance)+group('Settings',[{label:'Saved ID',cells:ready.map(record=>record.id)},...compared.parameters],true))+'</details>';
    }
    const note=chosen.length===1?'Tick another to compare.':reading?'Reading '+(reading>1?reading+' stored results':'1 stored result')+'…':'';
    panel.innerHTML='<div class="comparison-bar"><strong>'+(chosen.length>1?chosen.length+' tests ticked':'1 test ticked.')+'</strong><span role="status">'+note+'</span><button type="button" id="saved-clear" data-clear>Clear</button></div>'+body;
    panel.querySelectorAll('.comparison-scroll').forEach((box,at)=>{box.scrollLeft=scrolled[at]||0;});
  }
  // One loader reads the description of each row that the user ticked or opened,
  // one at a time and one time. A row that nobody ticked or opened is never read.
  // A failed read is not kept: the Details of that row gives the reason with
  // Retry, and a ticked row loses its tick with the reason in the status line.
  // The temporary evidence reader closes when the description is read.
  async function load(){
    if(loading)return;
    loading=true;
    try{
      for(let id;(id=[...ticked,...viewed].find(id=>!descriptions.has(id)&&!failures.has(id)));){
        try{
          const used=await ResultArtifacts.use({kind:'saved',id},artifact=>BacktestComparison.describe(artifact));
          if(!used.consumed)throw Error('Its stored result was not read.');
          if(records.some(record=>record.id===id))descriptions.set(id,used.value);else ticked.delete(id);
        }catch(error){
          const record=records.find(record=>record.id===id),reason=error.message||'The local service did not answer.';
          if(record)failures.set(id,'Could not read the saved settings. '+reason);
          if(ticked.delete(id)&&record)message('Could not read “'+record.name+'”. '+reason,true);
        }
        viewed.delete(id);
        // An active rename keeps its input. Its row shows the new text when the rename ends.
        if(renaming)renderPanel();else render();
      }
    }finally{loading=false;}
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
    catch(_){if(ticket===feedback)report(success+' The saved list could not be refreshed. Select Refresh in Runs & saved to try again.');}
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
      const success='Saved “'+record.name+'”. Its complete results are under Saved backtests in Runs & saved.';saveMessage(success);
      void reconcile(success,ticket,saveMessage);
    },saveMessage);
  }
  async function open(id){
    const number=++operation,isCurrent=ResultArtifacts.opening();
    await perform(async()=>{
      message('Opening saved backtest…');
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
    // The one Refresh of Runs also reads the Saved backtests rows again.
    node('queue-refresh').addEventListener('click',()=>available?perform(async()=>{await refresh();message('Saved backtests refreshed.');}):undefined);
    node('saved-head').addEventListener('click',event=>{
      const key=event.target.dataset.sort;if(!key)return;
      sorting={key,direction:sorting.key===key?-sorting.direction:directions[key]};render();
    });
    // The panel compares 8 tests at most. Clear removes every tick. A new tick reads a failed row again.
    node('saved-list').addEventListener('change',event=>{
      const id=event.target.dataset.tick;if(!id)return;
      if(event.target.checked&&ticked.size>=8){event.target.checked=false;message('Untick a test first. The panel compares 8 tests at most.');return;}
      if(event.target.checked){ticked.add(id);failures.delete(id);}else ticked.delete(id);
      renderPanel();return load();
    });
    // Native toggle does not bubble: capture it on the list. Opening Details reads that row's
    // description once. A list that is drawn again with an open Details starts no second read.
    node('saved-list').addEventListener('toggle',event=>{
      const id=event.target.dataset?.menu;if(!id)return;
      if(!event.target.open){viewed.delete(id);return;}
      if(descriptions.has(id)||failures.has(id)||!records.some(record=>record.id===id))return;
      viewed.add(id);return load();
    },true);
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
      if(data.retry){failures.delete(data.retry);viewed.add(data.retry);const reading=load();render();return reading;}
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
    else message('Saved backtests use the local website service opened by backtest-web.cmd.');
    update();
  }
  return {init,update,changed};
})();
