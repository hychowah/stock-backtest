/* Navigation changes visibility, never the lifetime of the draft or result. A
   view change starts at the top of the page.
   The queue tray borrows the existing mounted queue panel and its owner, then
   returns it to the top of Runs, above the Saved backtests rows. */
const Workspaces=(()=>{
  const node=id=>document.getElementById(id);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let active='builder',section='overview',rendered='latest',queue={records:[],available:false,paused:false};
  function closeQueue(){if(node('workspace-queue-tray').open)node('workspace-queue-tray').close();}
  function show(view){
    closeQueue();
    for(const name of ['builder','runs','review'])node('workspace-'+name).hidden=name!==view;
    // Showing the same view again does not move the page.
    if(view!==active)scrollTo(0,0);
    active=view;
    document.querySelectorAll('#workspace-nav [data-workspace]').forEach(button=>button.setAttribute('aria-current',button.dataset.workspace===view?'page':'false'));
    // Scalar latest screens and dated evidence share the existing explanation
    // presenter. Restore its artifact when returning to the other workspace.
    const artifact=ResultArtifacts.forView(view==='review'?'custom':'latest');
    if(view==='review'&&artifact&&rendered!=='custom'){
      ScheduleView.show(artifact);rendered='custom';
      node('workspace-evidence').append(node('scalar-evidence-view'));
    }else if(view==='builder'&&viewKey()==='latest'&&artifact?.version===4&&rendered!=='latest'){
      EvidenceResults.show(artifact);rendered='latest';
      node('workspace-builder').append(node('scalar-evidence-view'));
    }
    if(view==='review')reviewSection(section);
  }
  function reviewSection(next){
    // The tab row stays at the top of the window while the page scrolls. A tab change in that state
    // brings the start of the new content to just under the row; otherwise the page does not move.
    const tabs=node('workspace-review-tabs'),stuck=tabs.getBoundingClientRect().top<1;
    section=next;node('workspace-review').dataset.section=next;
    // A block lists its tabs. A name such as random-returns or fixed-overview
    // shows it on that tab for that kind of result only.
    const random=ResultArtifacts.forView('custom')?.kind==='random',names=[next,(random?'random-':'fixed-')+next];
    node('workspace-review').querySelectorAll('[data-review-panel]').forEach(panel=>panel.hidden=!panel.dataset.reviewPanel.split(' ').some(name=>names.includes(name)));
    document.querySelectorAll('[data-review]').forEach(button=>button.setAttribute('aria-current',button.dataset.review===next?'page':'false'));
    const loaded=next==='selection'?SectorView.load():null;
    if(next==='returns'&&random)ScheduleView.inspectOriginal();
    if(stuck){
      const start=()=>{let first=tabs.nextElementSibling;while(first&&!first.getClientRects().length)first=first.nextElementSibling;first?.scrollIntoView();};
      // The sector view gets its height after its read. The page is set again then.
      start();loaded?.then(start);
    }
  }
  // note: one line about how this result was opened, kept with the recorded notes.
  function published(artifact,name,note=''){
    const scalar=node('scalar-evidence-view');
    if(artifact.kind==='latest'){
      rendered='latest';
      if(scalar){scalar.hidden=artifact.version!==4;node('workspace-builder').append(scalar);}
      return;
    }
    rendered='custom';
    if(scalar)node('workspace-evidence').append(scalar);
    node('workspace-result-title').textContent=name||'Backtest result';
    // Plain wording first; the exact recorded text waits in a closed disclosure.
    const description=BacktestComparison.describe(artifact),exact=description.parameters.filter(row=>row.exact);
    const list=(rows,key)=>'<dl>'+rows.map(row=>'<div><dt>'+escape(row.label)+'</dt><dd>'+escape(row[key])+'</dd></div>').join('')+'</dl>';
    node('workspace-parameters').innerHTML=list(description.parameters,'display')+(exact.length?'<details><summary>Exact recorded values</summary>'+list(exact,'exact')+'</details>':'');
    // The headline always shows the original result. An Explore selection never changes it.
    // The colour of the difference follows its sign on screen; a shown 0.00 has none.
    node('workspace-headline').innerHTML=description.headline.map(row=>{
      const tone=row.key==='difference'&&{'+':'up','-':'down'}[row.display[0]];
      return '<div'+(tone?' data-tone="'+tone+'"':'')+'><dt>'+escape(row.label)+'</dt><dd>'+escape(row.display)+'</dd></div>';
    }).join('');
    // The coverage line (short and empty periods, cash days) of a fixed result is a
    // recorded note. It shows below the headline when a headline value is
    // unavailable, because it gives the reason. For random dates it describes the
    // inspected trial and stays with that trial.
    const home=artifact.kind==='random'?'schedule-trial':description.headline.some(row=>row.display==='Unavailable')?'workspace-headline-note':'workspace-recorded-context';
    node(home).append(node('schedule-coverage'));
    // A recorded warning stays above the tabs. Every other note waits in the closed disclosure.
    const presentation=artifact.presentation||{},notice=presentation.notice||{},warning=notice.severity==='warning'&&notice.text||'';
    node('workspace-recorded-notice').textContent=warning;
    node('workspace-recorded-notice').hidden=!warning;
    node('workspace-recorded-notice').className='screen-message'+(warning?' warning':'');
    const notes=[['workspace-opened-note',note],['workspace-recorded-info',warning?'':notice.text],['workspace-recorded-coverage',presentation.coverage],['workspace-recorded-range',presentation.rangeNote],['workspace-recorded-period',presentation.periodLabel]];
    for(const [id,text] of notes){node(id).textContent=text||'';node(id).hidden=!text;}
    // The disclosure hides only when it holds no note, no coverage line and no producer line.
    const producer=node('result-producer');
    node('workspace-recorded-context').hidden=!(home==='workspace-recorded-context'||notes.some(([,text])=>text)||!producer.hidden&&producer.textContent);
    const window=description.observationWindow;
    node('workspace-result-window').textContent=(window.start??'Not recorded')+' → '+(window.end??'Not recorded')+' · '+(artifact.kind==='random'?'Random dates':artifact.kind==='january'?'Saved January books':'Fixed schedule');
    node('workspace-no-result').hidden=true;
    SectorView.show(artifact);section='overview';show('review');
  }
  // The status bar speaks for the queue: every dated test runs there.
  function status(){
    const running=queue.records.find(row=>['running','stopping'].includes(row.state));
    const waiting=queue.records.filter(row=>['queued','held'].includes(row.state)).length;
    let title='Idle',detail=queue.available?'No active backtest.':'Connecting to the queue…';
    if(running){
      title=(running.state==='stopping'?'Stopping':'Running')+' · '+running.name;
      const event=running.progress;
      detail=event?.type==='waiting'?event.message:event?event.completed+' / '+event.total+' trials complete':'Backtest is running on the server.';
    }
    node('workspace-run-state').textContent=title;node('workspace-run-detail').textContent=detail;
    node('workspace-waiting').textContent=(queue.paused?'Queue paused · ':'')+waiting+' waiting';
    node('workspace-queue-count').textContent=String(queue.records.filter(row=>['queued','held','running','stopping'].includes(row.state)).length);
  }
  function init(){
    document.querySelectorAll('[data-workspace]').forEach(button=>button.addEventListener('click',event=>{event.preventDefault();show(button.dataset.workspace);}));
    document.querySelectorAll('[data-review]').forEach(button=>button.addEventListener('click',()=>reviewSection(button.dataset.review)));
    node('workspace-run-open').addEventListener('click',()=>show('runs'));
    node('workspace-edit-copy').addEventListener('click',()=>{
      const artifact=ResultArtifacts.forView('custom');
      if(artifact){try{copySavedBacktestSettings(artifact);}catch(error){node('schedule-message').textContent=error.message;}}
    });
    const tray=node('workspace-queue-tray');
    node('workspace-queue-open').addEventListener('click',()=>{node('workspace-queue-content').append(node('queue-panel'));tray.showModal();});
    node('workspace-queue-close').addEventListener('click',()=>tray.close());
    tray.addEventListener('close',()=>node('workspace-runs').prepend(node('queue-panel')));
    const scalar=node('scalar-evidence-view');if(scalar)node('workspace-builder').append(scalar);
    SectorView.init(()=>active==='review'&&section==='selection');show('builder');status();
  }
  return {init,show,published,reviewSection,active:()=>active,queueStatus:value=>{queue=value;status();}};
})();
