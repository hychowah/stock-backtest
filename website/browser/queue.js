/* Durable queue controls. Live form edits never change submitted work. */
const BacktestQueue=(()=>{
  const node=id=>document.getElementById(id);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let callbacks={},records=[],paused=false,limit=100,available=false,busy=false,editing=null,pendingDelete=null,libraryRevision=null;
  let mutation=0,refreshNumber=0,pending=null;
  const rendered=new Map();
  const storageKey='backtest-queue-submission';
  const waiting=record=>['queued','held'].includes(record.state);
  const isManaging=()=>!!editing||records.some(record=>['queued','held','running','stopping'].includes(record.state));
  function message(text,error=false){node('queue-status').textContent=text;node('queue-status').className=error?'backtest-failed':'hint';}
  function remember(value){pending=value;try{value?localStorage.setItem(storageKey,JSON.stringify(value)):localStorage.removeItem(storageKey);}catch(_){} }
  const identifier=()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
  function endEdit(clearName=false){
    editing.draft.end();editing=null;
    if(clearName)node('queue-name').value='';
  }
  // The server edit identity, not queue position or a response arriving, owns
  // this form session. Reconciliation never replaces an already loaded draft.
  function reconcileEdit(){
    if(!editing)return;
    const record=records.find(record=>record.id===editing.id),edit=record?.edit;
    if(record?.state==='held'&&edit?.id===editing.token&&edit.state==='active'){
      if(editing.loading){
        editing.revision=edit.revision;editing.loading=false;node('queue-name').value=record.name;
        callbacks.prepare?.();editing.draft.restore({mode:record.mode,...record.options});
        node('strategy-heading').scrollIntoView?.({behavior:'smooth',block:'start'});
      }
      if(edit.revision===editing.revision)return;
    }
    // A hold with no acknowledgement may still be in flight. Retry its same
    // identity rather than abandoning a hold that can still reach the server.
    if(editing.loading&&record?.revision===editing.baseRevision)return;
    endEdit();
    message('The queued edit has ended'+(edit?.state==='saved'?' and its changes were saved':'')+'. Your current form settings are still here.');
  }
  async function acquireEdit(){
    const session=editing;
    await mutate('/'+session.id+'/hold',{revision:session.baseRevision,edit_id:session.token},
      {success:'Test held. Edit the strategy controls, then select Save queued test.'});
    reconcileEdit();
  }
  async function finishEdit(action){
    if(editing.loading)await acquireEdit();
    if(!editing)return;
    const session=editing;
    if(session.pending&&session.pending.action!==action)throw Error('Retry the pending Save or Cancel before changing this edit.');
    if(!session.pending){const spec=action==='update'?await specification():{};if(editing!==session)throw Error('This queued edit ended while its strategy was being prepared.');session.pending={action,body:{...JSON.parse(JSON.stringify(spec)),edit_id:session.token,edit_revision:session.revision}};}
    try{
      await mutate('/'+session.id+'/'+action,session.pending.body,
        {success:action==='update'?'Queued test updated. It can run with the new settings.':'Edit cancelled. Its previous settings are kept.'});
    }catch(error){
      if(error.status>=400&&error.status<500)session.pending=null;
      throw error;
    }
    if(editing===session)endEdit(true);
  }
  // The default name says what the row columns do not: the final rank, then the filters, in plain wording.
  function title(settings){
    const capture=settings.strategy,rank=BacktestComparison.finalRank(settings);
    const source=capture?BacktestComparison.plainName(capture,rank.source)+' · '+rank.direction+' first':callbacks.metricLabel(settings.metric??'ev_ebitda');
    const filters=capture?BacktestComparison.scalarRows(capture).filter(row=>row.value?.kind==='filter'||row.key.startsWith('condition.')).map(row=>row.display):[];
    return ['Ranks '+rank.rank_from+'–'+rank.rank_to,source,...filters].join(' · ').slice(0,120);
  }
  const when=value=>value?new Date(value).toLocaleString(undefined,{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):'';
  // The first line of an open row control. A captured strategy lists its pool and steps below it.
  function parameters(record){
    const o=record.options,dates=CalendarSettings.decode(o);
    return ({us:'US',hk:'Hong Kong',jp:'Japan · Tokyo'}[o.market??'us']||o.market)+` · USD · ${record.mode==='random'?'Random dates · '+(o.trials??24)+' trials':'Fixed dates'} · ${dates.start} → ${dates.end} · ${CalendarSettings.label(o)}`+
      (o.strategy?'':` · ranks ${o.rank_from??1}–${o.rank_to??50} · ${callbacks.metricLabel(o.metric??'ev_ebitda')} · ${o.pool==='cached'?'All stocks with cached prices':'Original candidate set'} · ${EngineControls.label(o.engine??'original')}`);
  }
  function renderRows(rows){
    const list=node('queue-list');
    if(!rows.length){list.innerHTML='<li class="run-empty">No test is waiting or running. Select Add to queue in Build strategy.</li>';rendered.clear();return;}
    if(!list.insertBefore){list.innerHTML=rows.map(row=>row.html).join('');return;}
    const existing=new Map([...list.querySelectorAll(':scope > li[data-queue-id]')].map(row=>[row.dataset.queueId,row]));
    for(const [index,item] of rows.entries()){
      let row=existing.get(item.id);
      if(row&&rendered.get(item.id)===item.signature)row.querySelector('.queue-progress').textContent=item.progress;
      else{
        const template=document.createElement('template');template.innerHTML=item.html;
        const next=template.content.firstElementChild;
        if(row){
          // A replaced row keeps its open control and the keyboard focus on the same control.
          const focused=row.contains(document.activeElement)?document.activeElement:null;
          next.querySelector('details').open=row.querySelector('details').open;row.replaceWith(next);
          if(focused)(next.querySelector('[data-action="'+focused.dataset.action+'"]:enabled')||next.querySelector('summary')).focus({preventScroll:true});
        }
        row=next;rendered.set(item.id,item.signature);
      }
      if(list.children[index]!==row)list.insertBefore(row,list.children[index]||null);
    }
    const wanted=new Set(rows.map(row=>row.id));
    for(const row of [...list.children])if(!wanted.has(row.dataset.queueId)){rendered.delete(row.dataset.queueId);row.remove();}
  }
  function render(){
    callbacks.changed?.({records,paused,available});
    node('queue-count').textContent=records.length+' / '+limit;
    node('queue-pause').textContent=paused?'Resume queue':'Pause queue';
    node('queue-pause').disabled=busy||!available;
    node('queue-refresh').disabled=busy;
    node('queue-add').textContent=editing?(editing.loading?'Retry edit request':editing.pending?.action==='update'?'Retry save':'Save queued test'):pending?'Retry queue submission':'Add to queue';
    node('queue-add').disabled=busy||!available||editing?.pending?.action==='release'||(!editing&&!pending&&records.length>=limit);
    node('queue-cancel-edit').hidden=!editing;node('queue-cancel-edit').disabled=busy||editing?.pending?.action==='update';
    node('queue-cancel-edit').textContent=editing?.pending?.action==='release'?'Retry cancel':'Cancel edit';
    node('queue-edit-note').hidden=!isManaging();
    node('queue-edit-note').textContent=editing?'This test is held while you edit the strategy controls. Auto-run is suspended. Save the queued test to release it, or cancel to keep its previous settings.':'Auto-run is suspended while the queue has waiting or running tests. Change the strategy controls and add another test. Run backtest still starts an immediate test.';
    const states={queued:'Waiting',held:'Held for editing',running:'Running',stopping:'Stopping',complete:'Complete',failed:'Failed',cancelled:'Stopped'};
    records=records.slice().sort((a,b)=>a.position-b.position);
    const waitingIds=records.filter(waiting).map(record=>record.id);
    // Running first, then waiting in queue order, then failed, stopped and not yet moved.
    const group=record=>['running','stopping'].includes(record.state)?0:waiting(record)?1:2;
    const rows=[...records].sort((a,b)=>group(a)-group(b)).map(record=>{
      const o=record.options,id=escape(record.id),name=escape(record.name),index=waitingIds.indexOf(record.id),dates=CalendarSettings.decode(o);
      const button=(action,label,disabled=false)=>`<button type="button" data-action="${action}" data-id="${id}" ${busy||disabled?'disabled':''}>${label}</button>`;
      let actions='';
      if(waiting(record))actions+=button('edit','Edit settings')+button('up','Move up',index===0)+button('down','Move down',index===waitingIds.length-1);
      if(record.state==='held')actions+=button('release','Release hold');
      if(['running','stopping'].includes(record.state))actions+=button('stop','Stop test',record.state==='stopping');
      if(record.state==='complete')actions+=button('open','Open result');
      actions+=button('copy','Tune');
      if(!['running','stopping'].includes(record.state)&&record.transfer?.state!=='reserved')actions+=pendingDelete===record.id?'<span>Delete this test and its result?</span>'+button('confirm','Delete test')+button('keep','Keep'):button('delete','Delete');
      const event=record.progress;
      const progress=record.state==='running'&&event?(event.type==='waiting'?event.message:`${event.completed}/${event.total} trials`+(event.total_new_books>0?` · ${event.calculated_books}/${event.total_new_books} new books`:'')):'';
      // A waiting test that names an engine this server does not run never starts.
      const blocked=record.state==='queued'&&!EngineControls.runnable(o.engine??'original')?EngineControls.label(o.engine??'original')+' cannot run on this server. Edit it to choose Original, or delete it.':'';
      // The note below the state: progress, a failure, or why a completed result is still here.
      const note=record.state==='complete'?(record.transfer?.error==='too_large'?'This inline backtest exceeds the 128 MiB save and open limit. The result stays in the queue.':record.transfer?.error==='retry'?'Saving failed. Results are kept here; the server will retry.':''):record.error||progress||blocked;
      const cagr=record.state!=='complete'?'':Number.isFinite(record.cagr)?(record.cagr*100).toFixed(2)+'%':'—';
      // The open row control lists every setting: each row's exact recorded text follows its plain wording.
      const line=(text,exact)=>'<p>'+escape(text)+(exact?'<small class="exact-setting">'+escape(exact)+'</small>':'')+'</p>';
      const detail=[`Requested engine: ${EngineControls.label(o.engine??'original')}`,`Minimum market cap: $${(o.min_cap??100e6)/1e6} million`,`Maximum market cap: ${o.max_cap==null?'no limit':'$'+o.max_cap/1e6+' million'}`,`Minimum EV: $${(o.min_ev??50e6)/1e6} million`,`Minimum yield: ${(o.min_yield??0)*100}%`,`Maximum multiple: ${o.max_multiple??'no limit'}`,`Sector: ${o.sector||'all'}`,`Exchange: ${o.exchange||'all'}`,...(o.filters||[]).map(condition=>callbacks.filterLabel(condition.field)+' '+(condition.op==='lt'?'<':'>')+' '+condition.value)].map(text=>line(text));
      if(o.strategy)detail.splice(0,detail.length,...BacktestComparison.scalarRows(o.strategy).map(row=>line(row.label+': '+row.display,row.exact)));
      if(record.mode==='random')detail.push(line('Random date set: '+(o.seed??record.configuration?.seed??'fresh seed stored on the server')));
      const state=record.state==='complete'?(record.transfer?.state==='reserved'?'Moving to Saved backtests':record.transfer?.error==='full'?'Completed — waiting for saved slot':'Completed — waiting to save'):states[record.state]||escape(record.state);
      // One line per test in the columns that the Finished rows use. Other actions and the settings wait in the row control.
      const html=`<li class="run-row" data-queue-id="${id}" data-state="${escape(record.state)}"><span class="run-name" title="${name}">${name}</span><span class="run-status"><span class="queue-state">${state}</span><span class="queue-progress">${escape(note)}</span></span><span class="run-type">${record.mode==='random'?'Random · '+escape(o.trials??24)+' trials':'Fixed dates'}</span><span class="run-window">${escape(dates.start+' → '+dates.end)}</span><span class="run-cagr"${record.mode==='random'?' title="Mean trial CAGR"':''}>${cagr}</span><span class="run-time">${escape(when(record.created_at))}</span><details class="run-menu"><summary aria-label="Actions and settings of ${name}" title="Actions and settings">⋯</summary><div class="run-actions">${actions}</div><p class="queue-summary">${escape(parameters(record))}</p>${detail.join('')}</details></li>`;
      return {id:record.id,html,progress:note,signature:JSON.stringify({record:{...record,progress:null},edges:waiting(record)?[index===0,index===waitingIds.length-1]:[],busy,deleting:pendingDelete===record.id})};
    });
    renderRows(rows);
  }
  async function request(path='',options={}){
    const response=await fetch('/api/backtest-queue'+path,{cache:'no-store',...options});
    let value;
    try{value=await response.json();}catch(_){const error=Error('The queue service is unavailable. Start the updated website and reload this page.');error.status=response.status;throw error;}
    if(!response.ok){const error=Object.assign(Error(value.error||'Could not access the queue.'),{status:response.status,requires_reader:value.requires_reader,code:value.code,path:value.path,errors:value.errors});throw error;}
    return value;
  }
  async function refresh(){
    const number=++refreshNumber,revision=mutation,value=await request();
    if(number!==refreshNumber||revision!==mutation)return;
    if(!Array.isArray(value.records))throw Error('The queue response is invalid.');
    if(Number.isInteger(value.library_revision)&&value.library_revision!==libraryRevision){libraryRevision=value.library_revision;callbacks.libraryChanged?.();}
    if(available&&JSON.stringify({records,paused,limit})===JSON.stringify({records:value.records,paused:value.paused,limit:value.limit}))return;
    records=value.records;paused=value.paused;limit=value.limit;available=true;reconcileEdit();render();
  }
  async function mutate(path,body,{method='POST',success='Queue updated.'}={}){
    mutation++;
    const value=await request(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    mutation++;
    if(value.state==='archived'){records=records.filter(record=>record.id!==value.id);callbacks.libraryChanged?.();success='This test already moved to Saved backtests.';}
    else if(value.deleted)records=records.filter(record=>record.id!==value.id);
    else if(value.id)records=[...records.filter(record=>record.id!==value.id),value];
    else if(typeof value.paused==='boolean')paused=value.paused;
    message(success);render();return value;
  }
  async function perform(task){
    if(busy)return;
    busy=true;render();
    try{
      await task();
      try{await refresh();}catch(_){message(node('queue-status').textContent+' The list could not be refreshed. Select Refresh to check progress.');}
    }catch(error){
      const session=editing,loading=session?.loading;
      if(loading&&error.status>=400&&error.status<500){endEdit();message(error.message,true);return;}
      if(session){
        try{await refresh();}catch(_){}
        if(editing!==session)return;
        if(loading&&!editing.loading){message('Test held. The lost response was recovered. You can edit its settings.');return;}
      }
      message(error.message,true);
    }
    finally{busy=false;render();}
  }
  async function specification(){
    if(node('strategy-form').reportValidity&&!node('strategy-form').reportValidity())throw Error('Complete the highlighted strategy settings before adding this test.');
    const submittedName=node('queue-name').value.trim(),held=editing&&records.find(record=>record.id===editing.id);
    // The draft keeps an unchanged held record's original selection.
    const settings=await callbacks.prepareSubmission({held:!!editing});
    if(!['custom','random'].includes(settings.mode))throw Error('Choose Historical backtest to queue a fixed or random-date test.');
    const {mode,...options}=settings;
    // A held edit keeps a typed name. A name that is still the default of the old settings follows the new settings.
    const typed=submittedName&&!(held&&submittedName===title({mode:held.mode,...held.options}));
    return {mode,options,catalog:callbacks.catalog(),presentation:callbacks.presentation(settings),name:typed?submittedName:title(settings)};
  }
  async function add(){
    await perform(async()=>{
      if(!editing&&!pending&&!['custom','random'].includes(callbacks.settings().mode)&&callbacks.configure){
        callbacks.prepare?.();callbacks.configure();
        message('Queue setup is ready. Choose fixed or random dates and adjust the settings, then select Add to queue beside Run backtest. No test has started.');
        return;
      }
      if(editing){
        if(editing.loading)await acquireEdit();else await finishEdit('update');
        return;
      }
      if(!pending){const spec=await specification();remember({id:identifier(),...spec});}
      try{
        await mutate('',pending,{success:'Test added to the queue. You can change the settings and add another.'});
        callbacks.prepare?.();
        remember(null);node('queue-name').value='';
      }catch(error){if(error.status>=400&&error.status<500)remember(null);throw error;}
    });
  }
  async function action(action,id){
    const record=records.find(record=>record.id===id);if(!record)return;
    if(action==='delete'){pendingDelete=id;render();return;}
    if(action==='keep'){pendingDelete=null;render();return;}
    await perform(async()=>{
      if(action==='open'){
        const isCurrent=ResultArtifacts.opening();
        const used=await ResultArtifacts.use({kind:'queue',id},artifact=>callbacks.open(artifact,record.name),{current:isCurrent});
        if(used.record?.state==='archived'){callbacks.libraryChanged?.();message('This result moved to Saved backtests. Open it under Finished.');return;}
        if(used.consumed)message('Opened “'+record.name+'” from its stored results.');return;
      }
      if(action==='copy'){
        callbacks.prepare?.();callbacks.restore({mode:record.mode,...record.options});node('queue-name').value='';
        message('Settings copied to the strategy controls. Change them and add a new test.');return;
      }
      if(action==='edit'){
        const draft=callbacks.beginEdit(id);
        editing={id,token:identifier(),baseRevision:record.revision,revision:null,loading:true,pending:null,draft};
        await acquireEdit();return;
      }
      if(action==='release'&&editing?.id===id){await finishEdit('release');return;}
      const options={revision:record.revision};
      if(action==='up'||action==='down')options.direction=action==='up'?-1:1;
      await mutate('/'+id+(action==='confirm'?'':'/'+(action==='up'||action==='down'?'move':action)),options,
        {method:action==='confirm'?'DELETE':'POST',success:action==='confirm'?'Selected test deleted.':action==='stop'?'Stop requested. The next test starts after cleanup.':'Queue updated.'});
      if(action==='confirm')pendingDelete=null;
      reconcileEdit();
    });
  }
  function init(config){
    callbacks=config;
    node('queue-add').addEventListener('click',add);
    // The name box sits in the strategy form. Its typing is not a settings change, and Enter adds the test.
    for(const type of ['input','change'])node('queue-name').addEventListener(type,event=>event.stopPropagation());
    node('queue-name').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();return add();}});
    node('queue-refresh').addEventListener('click',()=>perform(refresh));
    node('queue-pause').addEventListener('click',()=>perform(()=>mutate('/pause',{paused:!paused},{success:paused?'Queue resumed.':'Queue paused. The active test can finish.'})));
    node('queue-cancel-edit').addEventListener('click',()=>editing?action('release',editing.id):undefined);
    node('queue-list').addEventListener('click',event=>{const target=event.target;if(target.dataset.action)return action(target.dataset.action,target.dataset.id);});
    if(typeof location==='undefined'||location.protocol==='file:'){message('Open the local website service to use the queue.');render();return;}
    try{pending=JSON.parse(localStorage.getItem(storageKey)||'null');}catch(_){}
    refresh().then(()=>{message('Queue ready. Tests and results are saved on the server.');if(pending)void add();}).catch(error=>message(error.message,true));
    setInterval(()=>{if(!busy)refresh().catch(()=>{});},2000);
  }
  return {init,add,action,refresh,isEditing:()=>!!editing,isManaging};
})();
