/* Custom dated books use the local prepared daily cache. Rendering consumes
   dated periods; it never assumes one rebalance per calendar year. */
const ScheduleView=(()=>{
  let requestNumber=0,running=false,preparing=false,timer=null,startedAt=0,activeRun=null,inspectedTrial=null,inspectedSector=undefined,statusChanged=()=>{};
  const hasResults=()=>!!ResultArtifacts.forView('custom');
  function displayedResult(){
    const artifact=ResultArtifacts.forView('custom');
    return artifact?.kind==='random'?artifact.result.trial_results?.[inspectedTrial]:artifact?.result;
  }
  const node=id=>document.getElementById(id);
  const format=v=>v===null?'—':(v*100).toFixed(2)+'%';
  const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function elapsed(){
    const seconds=Math.max(0,Math.floor((Date.now()-startedAt)/1000));
    return Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');
  }
  function startBusy(){
    running=true;startedAt=Date.now();
    const button=node('run-screen');
    button.disabled=true;
    node('stop-backtest').hidden=false;
    button.textContent='Backtesting…';
    node('custom-view').setAttribute('aria-busy','true');
    node('schedule-progress').hidden=false;
    node('schedule-message').className='';
    node('schedule-message').textContent='Backtest runs on the server. You can lock your phone or close this page. Reopen this address to retrieve the result.'+(hasResults()?' Previous results remain below until it finishes.':'');
    const tick=()=>{node('schedule-elapsed').textContent=elapsed();statusChanged({running:true,detail:node('schedule-progress-detail').textContent,elapsed:elapsed()});};
    tick();timer=setInterval(tick,1000);
    updateResultsState();
  }
  function stopBusy(){
    if(timer!==null){clearInterval(timer);timer=null;}
    if(running){
      node('run-screen').disabled=false;
      node('run-screen').textContent=viewKey()==='latest'?'Screen latest':'Run backtest';
    }
    running=false;activeRun=null;statusChanged({running:false,detail:node('schedule-message').textContent,elapsed:elapsed()});
    node('stop-backtest').hidden=true;
    node('stop-backtest').disabled=false;
    node('schedule-progress').hidden=true;
    node('custom-view').setAttribute('aria-busy','false');
    updateResultsState();
  }
  function csv(kind){
    if(EvidenceResults.download(kind))return;
    const artifact=ResultArtifacts.forView('custom');
    const result=displayedResult();
    if(!result)return;
    const keys=kind==='holdings'?['period_start','period_end','rank','symbol','name','exchange','sector','market_cap','enterprise_value','metric','metric_multiple','metric_yield','fiscal','entry','exit','return_value','weight','contribution_pp','status']:['entry','exit','names','portfolio','spy'];
    const observations=kind==='holdings'?result.periods.flatMap(p=>p.holdings.map(h=>({...h,period_start:p.entry,period_end:p.exit,metric:result.options.metric??'ev_ebitda'}))):result.periods;
    const producer=artifact.result.producer;
    if(producer)keys.push('engine');
    const rows=[keys,...observations.map(h=>keys.map(k=>k==='engine'?producer.engine:h[k]))];
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
  async function run(filters,override=null,replay=null){
    if(running||preparing)return;
    if(typeof location==='undefined' || location.protocol==='file:'){
      node('screen-error').textContent='Custom dates use the local service. Double-click start.cmd, or run python3 website/serve.py, then use the browser window it opens.';return;
    }
    preparing=true;
    try{
    const random=!!replay || (!override && node('date-testing').value==='random');
    const {engine:replayEngine,...recorded}=replay||{};
    const plan=JSON.parse(JSON.stringify(recorded));
    let body=replay?{...plan.options,...CalendarSettings.fields(plan),trials:plan.requested,seed:plan.seed,engine:replayEngine??'original'}:
      override?{...filters,...override,...EngineControls.fields()}:{...filters,...CalendarSettings.read(),...EngineControls.fields()};
    if(!replay&&random){
      body.trials=+node('random-trials').value;
      if(node('repeat-random').checked)body.seed=+node('random-seed').value;
    }
    EngineControls.requireCalendar(body);
    body=await StrategyDraft.captureBuiltins(body);
    if(replay&&!plan.options.strategy)plan.options={strategy:body.strategy};
    preparing=false;
    await follow(BacktestRuns.create(random?'random':'custom',body,replay?plan:null));
    }catch(error){node('screen-error').textContent=error.message;}
    finally{preparing=false;}
  }
  async function runPrepared(settings){
    if(running||preparing)return;
    if(typeof location==='undefined'||location.protocol==='file:'){node('screen-error').textContent='Backtests use the local service. Run python3 website/serve.py, then open its local website.';return;}
    const {mode,...options}=JSON.parse(JSON.stringify(settings));
    if(['custom','random'].includes(mode))EngineControls.requireCalendar(options);
    await follow(BacktestRuns.create(mode,options));
  }
  async function follow(run){
    if(running)return;
    const number=++requestNumber,body=run.options,random=run.mode==='random',isCurrent=ResultArtifacts.opening();
    activeRun=run;
    node('screen-error').textContent='';
    node('schedule-progress-detail').textContent=run.mode==='latest'?'Screening latest cached close with submitted variables.':CalendarSettings.decode(body).start+' → '+CalendarSettings.decode(body).end+' · '+CalendarSettings.label(body)+'. '+(random?body.trials+' random-date trials; preparing new dates can take longer.':'New schedules can take a few minutes.');
    node('trial-progress').hidden=!random;node('trial-progress').value=0;node('trial-progress').max=random?body.trials:1;
    startBusy();
    startedAt=run.submitted;
    try{
      let rememberedSeed=null;
      const state=await BacktestRuns.follow(run,state=>{
        if(state.state==='reconnecting'){
          node('schedule-progress-detail').textContent='Connection lost. Reconnecting to the server run. You can reopen this address later.';return;
        }
        if(state.configuration && state.configuration.seed!==rememberedSeed){
          rememberedSeed=state.configuration.seed;RobustnessView.remember(state.configuration,run.options.engine);
        }
        if(state.state==='stopping'){
          node('schedule-progress-detail').textContent='Stopping on the server. Waiting for workers and cache cleanup.';return;
        }
        const event=state.progress;
        if(event && (event.type==='progress'||event.type==='preparation')){
          node('trial-progress').value=event.completed;node('trial-progress').max=event.total;
          const books=event.total_new_books>0?' · preparing books '+event.calculated_books+'/'+event.total_new_books+' with '+event.workers+' worker'+(event.workers===1?'':'s'):'';
          node('schedule-progress-detail').textContent=event.completed+'/'+event.total+' trials complete'+books+' · '+(event.completed<event.total?'evaluating trial '+event.trial:'finishing summary')+' · '+CalendarSettings.label(body)+'.';
        }
      },{current:()=>number===requestNumber});
      if(number!==requestNumber || !state)return;
      if(state.state==='cancelled'){
        node('schedule-message').textContent='Backtest stopped.'+(hasResults()?' Previous results remain displayed.':' Select Run backtest when ready.');
        return;
      }
      if(state.state==='failed')throw Object.assign(Error(state.error),{code:state.code,path:state.path,errors:state.errors});
      if(!isCurrent())return;
      let next=state.result;
      if(state.evidence){
        const used=await ResultArtifacts.use({kind:'run',id:run.id},artifact=>{next=artifact.result;publishResult(artifact);},{current:isCurrent,display:{catalog:sourceCatalog(),presentation:scheduledPresentation({mode:run.mode,...body}),captured_at:new Date().toISOString()}});
        if(!used.consumed)return;
      }else completeResult({mode:run.mode,...body},next);
      if(random){
        node('schedule-message').textContent='Random-date test complete · '+next.completed+' trials · '+elapsed()+' elapsed.';
      }else if(run.mode==='latest'){node('schedule-message').textContent='Latest variable screen complete · '+next.names+' selected stocks.';}else{
        node('schedule-message').textContent='Backtest complete · '+(state.evidence?.manifest.periods??next.periods.length)+' holding periods · '+elapsed()+' elapsed.';
      }
      node('schedule-message').className='backtest-complete';
    }catch(error){if(number===requestNumber){
      node('screen-error').textContent=error.message+(hasResults()?' The previous results remain displayed.':' Try running the backtest again.');
      node('schedule-message').textContent='Backtest failed after '+elapsed()+'.';
      node('schedule-message').className='backtest-failed';
    }}finally{if(number===requestNumber)stopBusy();}
  }
  function init(readContext,onStatus=()=>{}){
    statusChanged=onStatus;
    CalendarSettings.init();void EngineControls.init(readContext);
    const repeat=node('repeat-random');
    const syncSeed=()=>node('random-seed').disabled=!repeat.checked;
    repeat.checked=false;syncSeed();repeat.addEventListener('change',syncSeed);
    RobustnessView.init((trial,configuration,stored,index)=>stored||[3,4].includes(ResultArtifacts.forView('custom')?.version)?inspect(index):run(configuration.options,{dates:trial.dates,...CalendarSettings.fields(configuration)}),configuration=>run(configuration.options,null,configuration),()=>{const artifact=ResultArtifacts.forView('custom');return artifact?.kind==='random'?artifact.result:null;});
    node('schedule-period').addEventListener('change',stocks);
    node('schedule-download-holdings').addEventListener('click',()=>csv('holdings'));
    node('schedule-download-returns').addEventListener('click',()=>csv('returns'));
    EvidenceResults.init();
    ResultExplorer.init();
  }
  async function resume(){
    if(typeof location==='undefined'||location.protocol==='file:')return;
    if(running||!BacktestRuns.pending())return;
    startBusy();
    node('stop-backtest').hidden=true;
    node('schedule-progress-detail').textContent='Checking saved runs on the server…';
    let run;
    try{run=await BacktestRuns.recover(()=>{node('schedule-progress-detail').textContent='Reconnecting to check saved runs…';});}
    finally{stopBusy();}
    if(!run){node('screen-error').textContent='No previous run is available. It may have stopped, failed or expired. Run the backtest again.';return;}
    try{restoreBacktestSettings({mode:run.mode,...run.options});}
    catch(error){node('screen-error').textContent=error.message;return;}
    return follow(run);
  }
  function inspect(index){inspectedTrial=index;const artifact=ResultArtifacts.forView('custom');if([3,4].includes(artifact?.version))EvidenceResults.show(artifact,index+1);else render();}
  function inspectOriginal(number,period,sector){
    if(number===undefined&&inspectedTrial!==null){node('schedule-results').hidden=false;return;}
    number??=1;period??=1;
    inspectedTrial=number-1;inspectedSector=sector;
    const artifact=ResultArtifacts.forView('custom');if(!artifact)return;
    if([3,4].includes(artifact.version))EvidenceResults.show(artifact,number,{period,sector});
    else{render();node('schedule-period').value=String(period-1);stocks();}
  }
  function show(artifact){
    node('custom-view').hidden=false;
    ResultExplorer.clear();
    EvidenceResults.showProducer(artifact);
    inspectedTrial=null;inspectedSector=undefined;EvidenceResults.clear();node('schedule-period-pages').hidden=true;node('schedule-holdings-pages').hidden=true;
    if(artifact.kind==='random'){
      RobustnessView.render(artifact.result,artifact.settings.engine);node('schedule-results').hidden=true;
      ResultExplorer.show(artifact,'all',{summary:artifact.result,periods:artifact.result.trials[0]?.periods??0});
    }else{
      if([3,4].includes(artifact.version))EvidenceResults.show(artifact,1);else render();node('robustness-results').hidden=true;
    }
    node('schedule-message').textContent='Backtest results ready.';node('schedule-message').className='';
  }
  function cancel(){
    if(!running||!activeRun)return;
    BacktestRuns.stop(activeRun);
    node('stop-backtest').disabled=true;
    node('schedule-message').textContent='Stop requested. The server will confirm after worker and cache cleanup. If disconnected, this request will retry when the page reconnects.';
  }
  return {run,runPrepared,init,resume,cancel,show,inspectOriginal,isRunning:()=>running||preparing};
})();
