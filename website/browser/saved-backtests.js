/* The library stores complete results on the local service, never browser quota.
   A queue test is saved there when it finishes; this page saves nothing itself.
   Its records are the Saved backtests rows of Runs. Details of a row shows the
   settings of that test in place. The bar above the rows compares, locks or deletes
   the ticked rows; a locked row cannot be deleted. Details and Compare read one
   description per saved id. */
const SavedBacktests=(()=>{
  const node=id=>document.getElementById(id);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let openRecord=()=>{},copySettings=()=>{};
  let queueRefresh=false;
  // Descriptions reuse stored-artifact descriptions and keep their rows only. They
  // own no artifact, evidence reader, form or main-result lifetime. viewed holds
  // the rows whose open Details waits for its description. failed holds the rows
  // whose read failed, until a new tick or until Details opens again. An id that
  // leaves the list leaves all of them. A tick reads nothing until Compare.
  const ticked=new Set(),viewed=new Set(),failed=new Set(),descriptions=new Map();
  let loading=false,allOpen=false,comparing=false,confirmTicked=false;
  const headings={name:'Name',cagr:'CAGR',saved:'Saved'},directions={name:1,cagr:-1,saved:-1};
  let records=[],limit=100,sorting={key:'saved',direction:-1},renaming=null,busy=false,available=false,pendingDelete=null,operation=0,mutation=0,refreshNumber=0,feedback=0;
  // Every list action reports above the Saved backtests rows.
  function message(text,error=false){node('saved-status').textContent=text;node('saved-status').className=error?'backtest-failed':'hint';}
  const when=value=>new Date(value).toLocaleString(undefined,{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
  function update(){
    node('saved-count').textContent=records.length+' / '+limit;
    for(const [key,label] of Object.entries(headings)){
      const heading=node('saved-sort-'+key);
      heading.textContent=label+(sorting.key!==key?'':sorting.direction>0?' ↑':' ↓');heading.ariaCurrent=sorting.key===key?'true':null;
    }
  }
  // The rows of the market chosen in Runs. List order uses stored summary values
  // only. Names sort with their numbers in number order. A missing CAGR stays last
  // in both directions. Equal values show the newest saved first, then the lower id.
  function ordered(){
    const tie=(a,b)=>String(b.created_at).localeCompare(String(a.created_at))||a.id.localeCompare(b.id),{key,direction}=sorting;
    return records.filter(record=>RunMarkets.shows(record.market)).sort((a,b)=>{
      if(key==='saved')return -direction*tie(a,b);
      if(key==='name')return direction*String(a.name).localeCompare(String(b.name),undefined,{numeric:true})||tie(a,b);
      const knownA=Number.isFinite(a.cagr),knownB=Number.isFinite(b.cagr);
      if(knownA!==knownB)return knownA?-1:1;
      return (knownA?(a.cagr-b.cagr)*direction:0)||tie(a,b);
    });
  }
  // The Details of a row is a quick look at the parameters of a test: one line with
  // the market, the test type, the window and the interval, then the stock pool and
  // the steps (or the earlier bounds and conditions that hold a value) in plain
  // wording, the headline and the saved ID. A closed disclosure lists every recorded
  // row with its exact text: it adds the recorded facts and the settings that hold
  // only their documented default. Before the read the Details says so.
  function settings(record,exactOpen){
    const id=escape(record.id),description=descriptions.get(record.id),line=text=>'<p>'+escape(text)+'</p>';
    if(!description)return '<p role="status">'+(failed.has(record.id)?'The saved settings were not read. Close Details and open it again to retry.':'Reading the saved settings…')+'</p>';
    const shown=key=>description.parameters.find(row=>row.key===key)?.display,first=['mode','market','currency','start','end','interval','first','last','trials'];
    const rows=description.parameters.filter(row=>!first.includes(row.key)&&!row.recorded&&!row.quiet);
    return line([shown('market'),shown('currency'),shown('mode')+(shown('trials')?' · '+shown('trials')+' trials':''),shown('first')?shown('first')+'–'+shown('last'):shown('start')&&shown('start')+' → '+shown('end'),shown('interval')&&'every '+shown('interval')].filter(Boolean).join(' · '))+
      rows.map(row=>line(row.label+': '+row.display)).join('')+'<dl class="headline">'+description.headline.map(row=>'<div><dt>'+escape(row.label)+'</dt><dd>'+escape(row.display)+'</dd></div>').join('')+'</dl><p class="saved-id">Saved ID: '+id+'</p>'+
      '<details data-exact="'+id+'"'+(exactOpen?' open':'')+'><summary id="saved-exact-'+id+'">Exact recorded values</summary>'+description.parameters.map(row=>line(row.label+': '+(row.exact??row.display))).join('')+'</details>';
  }
  // One line per test in the columns that the In progress rows use. The name opens
  // the result. Details opens the settings and the other actions below the row.
  // A list that is drawn again keeps the focused control, an open Details and its
  // open exact values.
  function render(){
    const list=node('saved-list'),known=new Set(records.map(record=>record.id));
    for(const kept of [ticked,viewed,failed,descriptions])for(const id of [...kept.keys()])if(!known.has(id))kept.delete(id);
    if(!ticked.size)comparing=false;
    const opened=name=>new Set([...list.querySelectorAll('details[open][data-'+name+']')].map(control=>control.dataset[name]));
    const open=opened('menu'),exactOpen=opened('exact');
    const focused=document.activeElement,focusId=focused?.id,start=focused?.selectionStart,end=focused?.selectionEnd,shown=ordered();
    RunMarkets.report('saved',records.map(record=>record.market));
    node('saved-tick-all').checked=shown.length>0&&shown.every(record=>ticked.has(record.id));
    list.innerHTML=shown.map(record=>{
      const id=escape(record.id),name=escape(record.name);
      const kind={january:'January',custom:'Fixed dates',random:'Random'+(record.trials?' · '+escape(record.trials)+' trials':' dates')}[record.kind]||'Backtest';
      const cagr=record.cagr===null||record.cagr===undefined?'—':(record.cagr*100).toFixed(2)+'%';
      const button=(key,label)=>'<button type="button" id="saved-do-'+key+'-'+id+'" data-'+key+'="'+id+'">'+label+'</button>';
      const actions=renaming?.id===record.id?'<label class="saved-rename">New name<input id="saved-rename-'+id+'" data-rename-input="'+id+'" value="'+escape(renaming.name)+'" maxlength="120"></label>'+button('save-name','Save name')+button('cancel-name','Cancel'):pendingDelete===record.id?'<span>Delete this saved backtest?</span>'+button('confirm','Delete record')+button('keep','Keep'):button('copy','Tune')+button('rename','Rename')+(record.locked?'':button('delete','Delete'));
      return '<li class="run-row"'+(record.locked?' data-state="locked"':'')+'><input type="checkbox" id="saved-tick-'+id+'" data-tick="'+id+'" aria-label="Tick '+name+'"'+(ticked.has(record.id)?' checked':'')+'><button type="button" class="run-name" id="saved-open-'+id+'" data-open="'+id+'" title="Open the result of '+name+'"><span>'+name+'</span></button><span class="run-status"><span class="queue-state">'+(record.locked?'Locked':'Saved')+'</span></span><span class="run-type">'+kind+'</span><span class="run-window">'+escape(record.start+' → '+record.end)+'</span><span class="run-cagr"'+(record.kind==='random'?' title="Mean trial CAGR"':'')+'>'+cagr+'</span><span class="run-time" title="'+escape(new Date(record.created_at).toLocaleString())+'">'+escape(when(record.created_at))+'</span><details class="run-menu" data-menu="'+id+'"'+(open.has(record.id)?' open':'')+'><summary id="saved-menu-'+id+'" aria-label="Details of '+name+'">Details</summary>'+settings(record,exactOpen.has(record.id))+'<div class="run-actions">'+actions+'</div></details></li>';
    }).join('')||'<li class="run-empty">'+(RunMarkets.label()&&records.length?'No saved '+RunMarkets.label()+' backtests.':'No saved backtests yet.')+'</li>';
    // Ticks stay usable while a list action runs.
    list.querySelectorAll('button,input:not([type=checkbox])').forEach(control=>control.disabled=busy);
    renderPanel();
    if(focusId&&!busy){const restored=node(focusId);restored?.focus?.({preventScroll:true});if(start!==null&&start!==undefined)restored?.setSelectionRange?.(start,end);}
    update();
  }
  // The bar of the ticked tests: Compare, Lock ticked (Unlock ticked when every
  // ticked row is locked), Delete ticked and Clear. Delete ticked leaves the locked
  // rows. After Compare the panel below the column headings compares the ticked
  // tests whose descriptions are read: one column per test in list order, with the
  // requested settings that differ, then the headlines, then a short list of other
  // measures and every setting in a closed disclosure. Only setting rows carry the
  // difference marker. While another description is read, the panel keeps what it
  // shows and the bar says so. A redraw keeps the open disclosure.
  function renderPanel(){
    const bar=node('saved-bar'),panel=node('saved-comparison'),chosen=ordered().filter(record=>ticked.has(record.id)),ready=chosen.filter(record=>descriptions.has(record.id));
    const [disclosure]=panel.querySelectorAll('details');
    if(disclosure)allOpen=disclosure.open;
    bar.hidden=!chosen.length;
    if(!chosen.length){bar.innerHTML=panel.innerHTML='';panel.hidden=true;return;}
    const reading=comparing?chosen.length-ready.length:0,disabled=busy?' disabled':'',deletable=chosen.filter(record=>!record.locked).length,locking=deletable>0;
    let body='';
    if(comparing&&ready.length>1){
      // Recorded facts, such as a fresh random date set, are not requested settings: they show in the full list only.
      const compared=BacktestComparison.compare(ready.map(record=>descriptions.get(record.id))),differing=compared.parameters.filter(row=>row.different&&!row.recorded);
      // Only random-date tests have measures outside the headline.
      const more=compared.measures.length?'More measures and all settings':'All settings';
      const group=(title,rows,marked)=>'<tbody><tr class="comparison-group"><th scope="rowgroup" colspan="'+(ready.length+1)+'">'+title+'</th></tr>'+rows.map(row=>'<tr'+(marked&&row.different?' class="comparison-different"':'')+'><th scope="row">'+escape(row.label)+(marked&&row.different?'<span class="comparison-difference">Different</span>':'')+'</th>'+row.cells.map(cell=>'<td>'+escape(cell)+'</td>').join('')+'</tr>').join('')+'</tbody>';
      // Each table keeps the same column widths; many ticked tests scroll sideways inside the panel.
      const table=(caption,groups)=>'<div class="comparison-scroll"><table style="min-width:'+(170+140*ready.length)+'px"><caption>'+caption+'</caption><thead><tr><td></td>'+ready.map(record=>'<th scope="col" title="'+escape(record.name)+'"><span>'+escape(record.name)+'</span></th>').join('')+'</tr></thead>'+groups+'</table></div>';
      body=compared.notices.map(text=>'<p class="comparison-notice">'+escape(text)+'</p>').join('')+table('Comparison of '+ready.length+' ticked tests',group(differing.length?'Settings that differ':'Same settings',differing)+group('Headline',compared.headline))+
        '<details'+(allOpen?' open':'')+'><summary>'+more+'</summary>'+table(more+' of the ticked tests',(compared.measures.length?group('More measures',compared.measures):'')+group('Settings',[{label:'Saved ID',cells:ready.map(record=>record.id)},...compared.parameters],true))+'</details>';
    }
    const note=chosen.length===1?'Tick another to compare.':reading?'Reading '+(reading>1?reading+' stored results':'1 stored result')+'…':'';
    const count=deletable>1?deletable+' saved backtests':'1 saved backtest';
    const actions=confirmTicked?'<span>Delete '+count+'?'+(deletable<chosen.length?' Locked tests stay.':'')+'</span><button type="button" id="saved-confirm-ticked" data-confirm-ticked'+disabled+'>Delete '+count+'</button><button type="button" id="saved-keep-ticked" data-keep-ticked'+disabled+'>Keep</button>'
      :'<button type="button" id="saved-compare" data-compare'+(chosen.length<2?' disabled':disabled)+'>'+(comparing?'Hide comparison':'Compare')+'</button><button type="button" id="saved-lock-ticked" data-lock-ticked="'+locking+'"'+disabled+'>'+(locking?'Lock ticked':'Unlock ticked')+'</button><button type="button" id="saved-delete-ticked" data-delete-ticked'+(deletable?disabled:' disabled')+'>Delete ticked</button><button type="button" id="saved-clear" data-clear'+disabled+'>Clear</button>';
    bar.innerHTML='<strong>'+(chosen.length>1?chosen.length+' tests ticked':'1 test ticked.')+'</strong><span role="status">'+note+'</span>'+actions;
    panel.innerHTML=body;panel.hidden=!body;
  }
  // One loader reads the description of each row that the user compares or opened,
  // one at a time and one time. A row that nobody compares or opened is never read.
  // A failed read is not kept: the status line gives the reason and the row loses
  // its tick. A new tick or opening Details again reads again.
  // The temporary evidence reader closes when the description is read.
  async function load(){
    if(loading)return;
    loading=true;
    try{
      for(let id;(id=[...(comparing?ticked:[]),...viewed].find(id=>!descriptions.has(id)&&!failed.has(id)));){
        try{
          descriptions.set(id,(await ResultArtifacts.use({kind:'saved',id},artifact=>BacktestComparison.describe(artifact))).value);
        }catch(error){
          failed.add(id);ticked.delete(id);
          const record=records.find(record=>record.id===id);
          if(record)message('Could not read “'+record.name+'”. '+(error.message||'The local service did not answer.'),true);
        }
        viewed.delete(id);render();
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
    catch(_){if(ticket===feedback)message(success+' The saved list could not be refreshed. Select Refresh in Runs & saved to try again.');}
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
      if(used.consumed)message('Copied settings from “'+(used.record?.name||records.find(r=>r.id===id)?.name||'Backtest')+'”. Adjust the strategy controls, then select Add to queue.');
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
  // Lock ticked locks or unlocks the ticked rows one at a time.
  async function lockTicked(locked){
    const ids=ordered().filter(record=>ticked.has(record.id)&&Boolean(record.locked)!==locked).map(record=>record.id);
    await perform(async ticket=>{
      for(const id of ids){
        await request('/'+encodeURIComponent(id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({locked})});
        mutation++;records=records.map(record=>record.id===id?{...record,locked}:record);
      }
      const success=(ids.length>1?ids.length+' saved backtests':'Saved backtest')+(locked?' locked.':' unlocked.');message(success);
      void reconcile(success,ticket);
    });
  }
  // Delete ticked removes the ticked rows that are not locked, one at a time after one confirmation.
  async function removeTicked(){
    const ids=ordered().filter(record=>ticked.has(record.id)&&!record.locked).map(record=>record.id);
    confirmTicked=false;
    await perform(async ticket=>{
      for(const [index,id] of ids.entries()){
        message('Deleting saved record '+(index+1)+' of '+ids.length+'…');
        await request('/'+encodeURIComponent(id),{method:'DELETE'});
        mutation++;records=records.filter(record=>record.id!==id);
      }
      const success=(ids.length>1?ids.length+' saved backtests':'Saved backtest')+' deleted. The displayed results remain available.';message(success);
      void reconcile(success,ticket);
    });
  }
  async function rename(id){
    if(renaming?.id!==id)return;
    const name=renaming.name.trim();
    if(!name||name.length>120){message('Use a backtest name with 1–120 characters.',true);return;}
    await perform(async ticket=>{
      const record=await request('/'+encodeURIComponent(id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
      mutation++;records=records.map(item=>item.id===id?{...item,...record}:item);renaming=null;render();
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
    openRecord=access.open;copySettings=access.copy;
    // The one Refresh of Runs also reads the Saved backtests rows again.
    node('queue-refresh').addEventListener('click',()=>available?perform(async()=>{await refresh();message('Saved backtests refreshed.');}):undefined);
    node('saved-head').addEventListener('click',event=>{
      const key=event.target.dataset.sort;if(!key)return;
      sorting={key,direction:sorting.key===key?-sorting.direction:directions[key]};render();
    });
    // A tick change ends a delete confirmation. The box in the heading ticks every
    // row shown, or none. Another market clears every tick.
    const ticks=(ids,checked)=>{
      for(const id of ids)if(checked){ticked.add(id);failed.delete(id);}else ticked.delete(id);
      confirmTicked=false;
      render();return load();
    };
    node('saved-list').addEventListener('change',event=>{
      const id=event.target.dataset.tick;if(id)return ticks([id],event.target.checked);
    });
    node('saved-tick-all').addEventListener('change',event=>ticks(ordered().map(record=>record.id),event.target.checked));
    RunMarkets.changed(()=>{ticked.clear();confirmTicked=false;render();});
    // Native toggle does not bubble: capture it on the list. Opening Details reads that row's
    // description once. A list that is drawn again fires toggle for each open Details; it starts no second read.
    node('saved-list').addEventListener('toggle',event=>{
      const id=event.target.dataset?.menu;if(!id)return;
      if(!event.target.open){viewed.delete(id);failed.delete(id);return;}
      if(descriptions.has(id)||failed.has(id)||!records.some(record=>record.id===id))return;
      viewed.add(id);return load();
    },true);
    // Compare clicked below the top of Saved backtests scrolls up to the comparison.
    node('saved-bar').addEventListener('click',event=>{
      const data=event.target.dataset;if(busy)return;
      if('clear' in data){ticked.clear();confirmTicked=false;render();}
      if('compare' in data){
        comparing=!comparing;renderPanel();
        if(comparing&&node('saved-panel').getBoundingClientRect().top<0)node('saved-panel').scrollIntoView();
        return load();
      }
      if(data.lockTicked)return lockTicked(data.lockTicked==='true');
      if('deleteTicked' in data||'keepTicked' in data){confirmTicked='deleteTicked' in data;renderPanel();}
      if('confirmTicked' in data)return removeTicked();
    });
    node('saved-list').addEventListener('input',event=>{
      if(renaming&&renaming.id===event.target.dataset.renameInput)renaming.name=event.target.value;
    });
    node('saved-list').addEventListener('keydown',event=>{
      if(!renaming||renaming.id!==event.target.dataset.renameInput)return;
      if(event.key==='Enter'){event.preventDefault();return rename(renaming.id);}
      if(event.key==='Escape'){event.preventDefault();renaming=null;render();if(queueRefresh)changed();}
    });
    node('saved-list').addEventListener('click',event=>{
      if(busy)return;
      const data=event.target.dataset;
      if(data.saveName)return rename(data.saveName);
      if(data.rename){renaming={id:data.rename,name:records.find(record=>record.id===data.rename).name};pendingDelete=null;render();node('saved-rename-'+data.rename)?.focus?.();return;}
      if(data.cancelName){renaming=null;render();if(queueRefresh)changed();return;}
      if(data.open)return open(data.open);
      if(data.copy)return copy(data.copy);
      if(data.confirm)return remove(data.confirm);
      if(data.delete){pendingDelete=data.delete;render();}
      if(data.keep){pendingDelete=null;render();}
    });
    available=typeof fetch==='function' && typeof location!=='undefined' && location.protocol!=='file:';
    if(available)perform(refresh);
    else message('Saved backtests use the local website service opened by backtest-web.cmd.');
    update();
  }
  return {init,changed};
})();
