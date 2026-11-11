/* Presents a dated result: custom dated books from the local prepared daily cache.
   Rendering consumes dated periods; it never assumes one rebalance per calendar
   year. Every dated test runs from the queue. This owner starts one kind of work:
   a latest screen for a chain that the page cannot screen offline. */
const ScheduleView=(()=>{
  let inspectedTrial=null,inspectedSector=undefined;
  function displayedResult(){
    const artifact=ResultArtifacts.forView('custom');
    return artifact?.kind==='random'?artifact.result.trial_results?.[inspectedTrial]:artifact?.result;
  }
  const node=id=>document.getElementById(id);
  const format=v=>v===null?'—':(v*100).toFixed(2)+'%';
  const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  // The Screen latest button waits while the local service screens or looks for the last screen.
  function busy(on){node('run-screen').disabled=on;node('run-screen').textContent=on?'Screening…':'Screen latest';}
  function csv(kind){
    if(EvidenceResults.download(kind))return;
    const artifact=ResultArtifacts.forView('custom');
    const result=displayedResult();
    if(!result)return;
    const market=artifact.settings.market;
    const keys=kind==='holdings'?['period_start','period_end','rank','symbol','name','exchange','sector','market_cap','enterprise_value','metric','metric_multiple','metric_yield','fiscal','entry','exit','return_value','weight','contribution_pp','status']:['entry','exit','names','portfolio','spy'];
    const observations=kind==='holdings'?result.periods.flatMap(p=>p.holdings.map(h=>({...h,period_start:p.entry,period_end:p.exit,metric:result.options.metric??'ev_ebitda'}))):result.periods;
    const producer=artifact.result.producer;
    if(producer)keys.push('engine');
    if(market!==undefined)keys.unshift('market','currency');
    const rows=[keys,...observations.map(h=>keys.map(k=>k==='market'?market:k==='currency'?'USD':k==='engine'?producer.engine:h[k]))];
    const body=rows.map(row=>row.map(v=>'"'+String(v??'').replace(/"/g,'""')+'"').join(',')).join('\r\n');
    const url=URL.createObjectURL(new Blob([body],{type:'text/csv;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='scheduled-'+kind+'-'+result.start+'-'+result.end+'.csv';link.click();URL.revokeObjectURL(url);
  }
  const chart=periods=>EvidenceResults.chart(periods);
  function stocks(){
    if(EvidenceResults.stocks())return;
    const result=displayedResult();
    if(!result)return;
    const period=result.periods[+node('schedule-period').value];
    if(!period)return;
    const metric=metricLabel(result.options.metric??'ev_ebitda',ResultArtifacts.forView('custom'));
    node('schedule-multiple-head').textContent=metric+' (×)';
    node('schedule-sector-note').textContent=inspectedSector===undefined?'Original selected stocks; ranks and weights are unchanged.':'Sector filter: '+(inspectedSector===null?'Unknown':inspectedSector)+'. Ranks and weights remain those of the whole original book.';
    node('schedule-stock-body').innerHTML=EvidenceResults.holdingRows(period.holdings.filter(h=>inspectedSector===undefined||(h.sector||null)===inspectedSector),ResultArtifacts.forView('custom'),period.names);
    const group=ReturnContributions.analyze(period.holdings);
    node('schedule-attribution').innerHTML=group.count?'<h3>Top 10 contributors</h3><div class="contribution-pies">'+ReturnContributions.pie(group.gain_slices,group.gains,1)+ReturnContributions.pie(group.loss_slices,group.losses,-1)+'</div><p>Top '+group.top_count+' stocks: '+group.top.map(h=>escape(h.symbol)+' ('+h.contribution_pp.toFixed(2)+' pp)').join(', ')+'. Contributions are stock return divided by actual stock count; pies show gains and losses separately.</p>':'<p>No stocks to attribute.</p>';
  }
  function render(){
    const result=displayedResult();
    if(!result)return;
    node('schedule-results').hidden=false;
    node('schedule-dates').textContent=result.start+' → '+result.end+' · '+(ResultArtifacts.forView('custom').kind==='january'?'January books':CalendarSettings.label(result));
    node('schedule-cagr').textContent=format(result.cagr);
    node('schedule-spy-cagr').textContent=format(result.spy_cagr);
    node('schedule-growth').textContent=result.growth===null?'—':'$'+result.growth.toFixed(2);
    const requested=(result.options.rank_to??50)-(result.options.rank_from??1)+1;
    const short=result.periods.filter(p=>p.names<requested).length,empty=result.periods.filter(p=>p.names===0).length;
    node('schedule-coverage').textContent=result.coverage+' '+StockScreener.selectionDescription(result.options)+' '+short+' short periods; '+empty+' empty periods. '+(empty?(result.growth==null?'Recorded totals are unavailable under the earlier empty-period rule. Select Apply in Explore this result for a cash-based summary. ':'Empty periods hold cash at 0%; SPY keeps its period return. '):'')+(Number.isFinite(result.seconds)?'Computed in '+result.seconds.toFixed(2)+'s; repeated periods reuse prepared books.':'')+(result.cash_days?' Both strategy and paired SPY hold cash until '+result.first_trade+' ('+result.cash_days+' days); CAGR uses the common window.':'');
    chart(result.periods);
    node('schedule-rows').innerHTML=result.periods.map(p=>'<tr>'+[p.entry,p.exit,p.names,format(p.portfolio),format(p.spy)].map(v=>'<td>'+escape(v)+'</td>').join('')+'</tr>').join('');
    node('schedule-period').innerHTML=result.periods.map((p,i)=>`<option value="${i}">${p.entry} → ${p.exit} · ${p.names} stocks</option>`).join('');
    node('schedule-period').value=String(result.periods.length-1);stocks();
    if(ResultArtifacts.forView('custom').kind!=='random')ResultExplorer.show(ResultArtifacts.forView('custom'),1,
      {summary:result,periods:result.periods.length,short,empty});
  }
  // Screen latest for a chain outside the offline shape.
  async function runPrepared(settings){
    if(typeof location==='undefined'||location.protocol==='file:'){node('screen-error').textContent='This latest screen uses the local service. Double-click start.cmd, or run python3 website/serve.py, then use the browser window it opens.';return;}
    const {mode,...options}=JSON.parse(JSON.stringify(settings));
    await follow(BacktestRuns.create(options));
  }
  // The result stays wanted until another result opens. Then this page stops asking.
  async function follow(run){
    const isCurrent=ResultArtifacts.opening();
    node('screen-error').textContent='';
    busy(true);
    try{
      const state=await BacktestRuns.follow(run,state=>{
        node('screen-error').textContent=state.state==='reconnecting'?'Connection lost. Reconnecting to the local service…':'';
      },{current:isCurrent});
      if(!state)return;
      if(state.state==='failed')throw Object.assign(Error(state.error),{code:state.code,path:state.path,errors:state.errors});
      await ResultArtifacts.use({kind:'run',id:run.id},artifact=>publishResult(artifact),{current:isCurrent,display:{catalog:sourceCatalog(),presentation:scheduledPresentation({mode:run.mode,...run.options}),captured_at:new Date().toISOString()}});
    }catch(error){node('screen-error').textContent=error.message+' The previous result remains displayed.';}
    finally{busy(false);}
  }
  function init(readContext){
    CalendarSettings.init();void EngineControls.init(readContext);
    const repeat=node('repeat-random');
    const syncSeed=()=>node('random-seed').disabled=!repeat.checked;
    repeat.checked=false;syncSeed();repeat.addEventListener('change',syncSeed);
    // A trial opens in Returns, where its period returns and stocks show.
    RobustnessView.init(index=>{
      inspect(index);Workspaces.reviewSection('returns');
      // The tab change hides the button that had focus; the trial title takes it.
      node('schedule-trial-title').focus();
    },()=>{const artifact=ResultArtifacts.forView('custom');return artifact?.kind==='random'?artifact.result:null;});
    node('schedule-period').addEventListener('change',stocks);
    node('schedule-download-holdings').addEventListener('click',()=>csv('holdings'));
    node('schedule-download-returns').addEventListener('click',()=>csv('returns'));
    EvidenceResults.init();
    ResultExplorer.init();
  }
  // After a reload, show again the newest latest screen that this browser sent to the service.
  async function resume(){
    if(typeof location==='undefined'||location.protocol==='file:'||!BacktestRuns.pending())return;
    busy(true);
    let run;
    try{run=await BacktestRuns.recover();}
    finally{busy(false);}
    if(!run)return;
    restoreBacktestSettings({mode:run.mode,...run.options});
    return follow(run);
  }
  // The per-trial block of a random-date result names its trial; the headline shows all trials.
  // An older random-date result can hold its summary only. Then a trial has no stocks and no period
  // returns: a note says so and how to get them. Nothing is calculated to show them.
  function trial(artifact){
    node('schedule-trial-title').textContent='Trial '+(inspectedTrial+1)+' of '+artifact.result.trials.length;
    const stored=[3,4].includes(artifact.version)||!!artifact.result.trial_results?.[inspectedTrial];
    node('schedule-trial-missing').hidden=stored;
    if(!stored)node('schedule-results').hidden=true;
    return stored;
  }
  function inspect(index){
    inspectedTrial=index;const artifact=ResultArtifacts.forView('custom');
    if(!trial(artifact))return;
    if([3,4].includes(artifact.version))EvidenceResults.show(artifact,index+1);else render();
  }
  function inspectOriginal(number,period,sector){
    const artifact=ResultArtifacts.forView('custom');if(!artifact)return;
    if(number===undefined&&inspectedTrial!==null){node('schedule-results').hidden=!node('schedule-trial-missing').hidden;return;}
    number??=1;period??=1;
    inspectedTrial=number-1;inspectedSector=sector;
    if(artifact.kind==='random'&&!trial(artifact))return;
    if([3,4].includes(artifact.version))EvidenceResults.show(artifact,number,{period,sector});
    else{render();node('schedule-period').value=String(period-1);stocks();}
  }
  function show(artifact){
    node('custom-view').hidden=false;
    ResultExplorer.clear();
    EvidenceResults.showProducer(artifact);
    inspectedTrial=null;inspectedSector=undefined;EvidenceResults.clear();node('schedule-period-pages').hidden=true;node('schedule-holdings-pages').hidden=true;node('schedule-trial-missing').hidden=true;
    if(artifact.kind==='random'){
      RobustnessView.render(artifact.result);node('schedule-results').hidden=true;
      ResultExplorer.show(artifact,'all',{summary:artifact.result,periods:artifact.result.trials[0]?.periods??0});
    }else{
      if([3,4].includes(artifact.version))EvidenceResults.show(artifact,1);else render();node('robustness-results').hidden=true;
    }
    // The status line speaks only for a failed read or a refused copy; an opened result needs none.
    node('schedule-message').textContent='';node('schedule-message').className='';
  }
  return {runPrepared,init,resume,show,inspectOriginal};
})();
