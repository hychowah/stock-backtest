/* Custom dated books use the local prepared daily cache. Rendering consumes
   dated periods; it never assumes one rebalance per calendar year. */
const ScheduleView=(()=>{
  let requestNumber=0,running=false,timer=null,startedAt=0,activeRun=null,inspectedTrial=null;
  let bounded=null;
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
    const tick=()=>node('schedule-elapsed').textContent=elapsed();
    tick();timer=setInterval(tick,1000);
    updateResultsState();
  }
  function stopBusy(){
    if(timer!==null){clearInterval(timer);timer=null;}
    if(running){
      node('run-screen').disabled=false;
      node('run-screen').textContent=viewKey()==='latest'?'Screen latest':'Run backtest';
    }
    running=false;activeRun=null;
    node('stop-backtest').hidden=true;
    node('stop-backtest').disabled=false;
    node('schedule-progress').hidden=true;
    node('custom-view').setAttribute('aria-busy','false');
    updateResultsState();
  }
  function csv(kind){
    const artifact=ResultArtifacts.forView('custom');
    if([3,4].includes(artifact?.version)){ResultArtifacts.reader(artifact).download(kind,artifact.kind==='random'?inspectedTrial+1:1);return;}
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
  function chart(periods){
    const values=periods.flatMap(p=>[p.portfolio,p.spy]).filter(Number.isFinite);
    const low=Math.min(0,...values),high=Math.max(.1,...values),span=high-low||1;
    const y=v=>30+(high-v)/span*260,step=1100/periods.length;
    let html=`<line x1="60" x2="1160" y1="${y(0)}" y2="${y(0)}" stroke="#acb8c5"/>`;
    for(let i=0;i<=4;i++){const v=low+span*i/4;html+=`<text x="55" y="${y(v)+4}" text-anchor="end" font-size="11">${format(v)}</text>`;}
    periods.forEach((p,i)=>{
      const x=60+i*step,width=Math.max(.3,(step-2)/2);
      for(const [v,offset,color,label] of [[p.portfolio,0,'#20775e','Strategy'],[p.spy,width,'#acb8c5','SPY']]){
        if(v===null)continue;
        const text=escape(p.entry+' → '+p.exit+' · '+label+' '+format(v));
        html+=`<rect x="${x+offset}" y="${Math.min(y(0),y(v))}" width="${width}" height="${Math.max(1,Math.abs(y(v)-y(0)))}" fill="${color}" tabindex="0" aria-label="${text}"><title>${text}</title></rect>`;
      }
      if(i%Math.max(1,Math.ceil(periods.length/12))===0)html+=`<text x="${x}" y="315" font-size="10" transform="rotate(-35 ${x} 315)">${p.entry}</text>`;
    });
    node('schedule-chart').innerHTML=html;
  }
  function stocks(){
    if(bounded&&ResultArtifacts.current(bounded.artifact)){void storedStocks(bounded);return;}
    const result=displayedResult();
    if(!result)return;
    const period=result.periods[+node('schedule-period').value];
    if(!period)return;
    const metric=metricLabel(result.options.metric??'ev_ebitda');
    node('schedule-multiple-head').textContent=metric+' (×)';
    node('schedule-stock-body').innerHTML=period.holdings.map(h=>'<tr>'+[h.rank,h.symbol,h.name,h.exchange,h.sector,h.metric_multiple.toFixed(2),money(h.market_cap),money(h.enterprise_value),h.fiscal,h.entry,h.exit,format(h.return_value),h.contribution_pp.toFixed(2)+' pp',h.status].map(v=>'<td>'+escape(v)+'</td>').join('')+'</tr>').join('')||'<tr><td colspan="14">No matching stocks in this period.</td></tr>';
    const group=ReturnContributions.analyze(period.holdings);
    node('schedule-attribution').innerHTML=group.count?'<h3>Top 10 contributors</h3><div class="contribution-pies">'+contributionPie(group.gain_slices,group.gains,1)+contributionPie(group.loss_slices,group.losses,-1)+'</div><p>Top '+group.top_count+' stocks: '+group.top.map(h=>escape(h.symbol)+' ('+h.contribution_pp.toFixed(2)+' pp)').join(', ')+'. Contributions are stock return divided by actual stock count; pies show gains and losses separately.</p>':'<p>No stocks to attribute.</p>';
  }
  function render(){
    const result=displayedResult();
    if(!result)return;
    node('schedule-results').hidden=false;
    node('schedule-dates').textContent=result.start+' → '+result.end+' · '+CalendarSettings.label(result);
    node('schedule-cagr').textContent=format(result.cagr);
    node('schedule-spy-cagr').textContent=format(result.spy_cagr);
    node('schedule-growth').textContent=result.growth===null?'—':'$'+result.growth.toFixed(2);
    const requested=(result.options.rank_to??50)-(result.options.rank_from??1)+1;
    const short=result.periods.filter(p=>p.names<requested).length,empty=result.periods.filter(p=>p.names===0).length;
    node('schedule-coverage').textContent=result.coverage+' '+StockScreener.selectionDescription(result.options)+' '+short+' short periods; '+empty+' empty periods. '+(empty?'Full-period strategy growth and CAGR unavailable. ':'')+'Computed in '+result.seconds.toFixed(2)+'s; repeated periods reuse prepared books.'+(result.cash_days?' Both strategy and paired SPY hold cash until '+result.first_trade+' ('+result.cash_days+' days); CAGR uses the common window.':'');
    chart(result.periods);
    node('schedule-rows').innerHTML=result.periods.map(p=>'<tr>'+[p.entry,p.exit,p.names,format(p.portfolio),format(p.spy)].map(v=>'<td>'+escape(v)+'</td>').join('')+'</tr>').join('');
    node('schedule-period').innerHTML=result.periods.map((p,i)=>`<option value="${i}">${p.entry} → ${p.exit} · ${p.names} stocks</option>`).join('');
    node('schedule-period').value=String(result.periods.length-1);stocks();
  }
  function valid(state){return bounded===state&&ResultArtifacts.current(state.artifact);}
  function readError(state,error){if(valid(state)&&error.name!=='AbortError')node('screen-error').textContent=error.message;}
  function navigation(id,cursor,next,total,label){
    node(id+'-pages').hidden=false;node(id+'-back').disabled=cursor===0;node(id+'-next').disabled=next===null;
    node(id+'-page').textContent=label+' · '+total+' total';
  }
  async function storedHoldings(state,cursor=0,firstPage=null){
    const period=state.period,sequence=++state.holdingSequence;
    try{
      const page=await (firstPage??state.reader.holdings(state.trial,period,cursor));
      if(!valid(state)||state.period!==period||state.holdingSequence!==sequence)return;
      state.holdingCursor=page.cursor;state.holdingNext=page.next;
      const scalar=state.artifact.version===4,metric=metricLabel(state.info.summary.options.metric??'ev_ebitda');node('schedule-multiple-head').textContent=scalar?'Ranking value · '+(page.rows[0]?.ranking_unit??'')+' · '+(page.rows[0]?.ranking_direction??''):metric+' (×)';
      node('schedule-stock-body').innerHTML=page.rows.map(h=>'<tr>'+[h.rank,h.symbol,h.name,h.exchange,h.sector,(state.artifact.version===4?ResultArtifacts.scalarValue(h):h.metric_multiple.toFixed(2)),money(h.market_cap),money(h.enterprise_value),h.fiscal,h.entry,h.exit,format(h.return_value),h.contribution_pp.toFixed(2)+' pp',h.status].map(v=>'<td>'+escape(v)+'</td>').join('')+'</tr>').join('')||'<tr><td colspan="14">No matching stocks in this period.</td></tr>';
      navigation('schedule-holdings',page.cursor,page.next,page.total,'Stocks '+(page.total?page.cursor+1:0)+'–'+(page.cursor+page.rows.length));
    }catch(error){if(state.period===period&&state.holdingSequence===sequence)readError(state,error);}
  }
  async function storedStocks(state){
    const period=+node('schedule-period').value,sequence=++state.stockSequence;state.period=period;
    const selected=state.page.rows.find(row=>row.number===period);if(!selected)return;
    node('schedule-holdings-back').disabled=true;node('schedule-holdings-next').disabled=true;
    node('schedule-stock-body').innerHTML='';state.holdingCursor=0;state.holdingNext=null;
    node('schedule-attribution').textContent='Reading contributions from all selected stocks…';
    // One bounded first page serves this table and attribution operation.
    // Both attribution passes keep original order. Replacement fences every
    // response before consumption or publication; no prior period is retained.
    const firstPage=state.reader.holdings(state.trial,period,0);
    void storedHoldings(state,0,firstPage);
    try{
      const group=await ReturnContributions.analyzeStored(selected.value.names,async visit=>{
        let page=await firstPage;
        do{
          if(!valid(state)||state.period!==period||state.stockSequence!==sequence)throw Error('This period view was replaced.');
          page.rows.forEach(visit);
          if(page.next===null)break;
          page=await state.reader.holdings(state.trial,period,page.next);
        }while(true);
      });
      if(!valid(state)||state.period!==period||state.stockSequence!==sequence)return;
      node('schedule-attribution').innerHTML=group.count?'<h3>Top 10 contributors</h3><div class="contribution-pies">'+contributionPie(group.gain_slices,group.gains,1)+contributionPie(group.loss_slices,group.losses,-1)+'</div><p>Top '+group.top_count+' stocks: '+group.top.map(h=>escape(h.symbol)+' ('+h.contribution_pp.toFixed(2)+' pp)').join(', ')+'. Contributions use all '+group.count+' selected stocks; pies show gains and losses separately.</p>':'<p>No stocks to attribute.</p>';
    }catch(error){if(state.period===period&&state.stockSequence===sequence)readError(state,error);}
  }
  async function storedPeriods(state,cursor=0){
    const sequence=++state.periodSequence;state.period=null;state.stockSequence++;
    node('schedule-period-back').disabled=true;node('schedule-period-next').disabled=true;
    node('schedule-holdings-back').disabled=true;node('schedule-holdings-next').disabled=true;
    try{
      const page=await state.reader.periods(state.trial,cursor);
      if(!valid(state)||state.periodSequence!==sequence)return;
      state.page=page;state.period=null;
      chart(page.rows.map(row=>row.value));
      node('schedule-rows').innerHTML=page.rows.map(({value:p})=>'<tr>'+[p.entry,p.exit,p.names,format(p.portfolio),format(p.spy)].map(v=>'<td>'+escape(v)+'</td>').join('')+'</tr>').join('');
      node('schedule-period').innerHTML=page.rows.map(({number,value:p})=>`<option value="${number}">${number}. ${p.entry} → ${p.exit} · ${p.names} stocks</option>`).join('');
      node('schedule-period').value=String(page.rows[0]?.number??'');
      navigation('schedule-period',page.cursor,page.next,page.total,'Chart and table: periods '+(page.total?page.cursor+1:0)+'–'+(page.cursor+page.rows.length));
      void storedStocks(state);
    }catch(error){if(state.periodSequence===sequence)readError(state,error);}
  }
  async function storedRender(artifact,trial){
    const state={artifact,trial,reader:ResultArtifacts.reader(artifact),periodSequence:0,holdingSequence:0,stockSequence:0};bounded=state;
    node('schedule-results').hidden=false;node('schedule-rows').innerHTML='';node('schedule-stock-body').innerHTML='';node('schedule-chart').innerHTML='';node('schedule-period').innerHTML='';node('schedule-attribution').textContent='Reading stored evidence…';
    try{
      state.info=await state.reader.trial(trial);if(!valid(state))return;
      const r=state.info.summary;
      node('schedule-dates').textContent=r.start+' → '+r.end+' · '+(artifact.kind==='january'?'January books':CalendarSettings.label(r));
      node('schedule-cagr').textContent=format(r.cagr);node('schedule-spy-cagr').textContent=format(r.spy_cagr);
      node('schedule-growth').textContent=r.growth===null?'—':'$'+r.growth.toFixed(2);
      node('schedule-coverage').textContent=r.coverage+' '+state.info.short+' short periods; '+state.info.empty+' empty periods. '+(state.info.empty?'Full-period strategy growth and CAGR unavailable. ':'')+'Computed in '+r.seconds.toFixed(2)+'s; repeated periods reuse prepared books.'+(r.cash_days?' Both strategy and paired SPY hold cash until '+r.first_trade+' ('+r.cash_days+' days); CAGR uses the common window.':'');
      await storedPeriods(state);
    }catch(error){readError(state,error);}
  }
  async function run(options,override=null,replay=null){
    if(running)return;
    if(typeof location==='undefined' || location.protocol==='file:'){
      node('screen-error').textContent='Custom dates use the local service. Double-click start.cmd, or run python3 website/serve.py, then use the browser window it opens.';return;
    }
    try{
    const {first,last,...filters}=options;
    const random=!!replay || (!override && node('date-testing').value==='random');
    const {engine:replayEngine,...plan}=replay||{};
    const body=replay?{...plan.options,...CalendarSettings.fields(plan),trials:plan.requested,seed:plan.seed,...('engine' in EngineControls.fields()?{engine:replayEngine??'original'}:{})}:
      override?{...filters,...override,...EngineControls.fields()}:{...filters,...CalendarSettings.read(),...EngineControls.fields()};
    if(!replay&&random){
      body.trials=+node('random-trials').value;
      if(node('repeat-random').checked)body.seed=+node('random-seed').value;
    }
    EngineControls.requireCalendar(body);
    await follow(BacktestRuns.create(random?'random':'custom',body,replay?plan:null));
    }catch(error){node('screen-error').textContent=error.message;}
  }
  async function follow(run){
    if(running)return;
    const number=++requestNumber,body=run.options,random=run.mode==='random',isCurrent=ResultArtifacts.opening();
    activeRun=run;
    node('screen-error').textContent='';
    node('schedule-progress-detail').textContent=CalendarSettings.decode(body).start+' → '+CalendarSettings.decode(body).end+' · '+CalendarSettings.label(body)+'. '+(random?body.trials+' random-date trials; preparing new dates can take longer.':'New schedules can take a few minutes.');
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
      if(state.state==='failed')throw Error(state.error);
      if(!isCurrent())return;
      let next=state.result;
      if(state.evidence){
        const used=await ResultArtifacts.use({kind:'run',id:run.id},artifact=>{next=artifact.result;publishResult(artifact);},{current:isCurrent,display:{catalog:sourceCatalog(),presentation:scheduledPresentation({mode:run.mode,...body}),captured_at:new Date().toISOString()}});
        if(!used.consumed)return;
      }else completeResult({mode:random?'random':'custom',...body},next);
      if(random){
        node('schedule-message').textContent='Random-date test complete · '+next.completed+' trials · '+elapsed()+' elapsed.';
      }else{
        node('schedule-message').textContent='Backtest complete · '+(state.evidence?.manifest.periods??next.periods.length)+' holding periods · '+elapsed()+' elapsed.';
      }
      node('schedule-message').className='backtest-complete';
    }catch(error){if(number===requestNumber){
      node('screen-error').textContent=error.message+(hasResults()?' The previous results remain displayed.':' Try running the backtest again.');
      node('schedule-message').textContent='Backtest failed after '+elapsed()+'.';
      node('schedule-message').className='backtest-failed';
    }}finally{if(number===requestNumber)stopBusy();}
  }
  function init(){
    CalendarSettings.init();void EngineControls.init();
    const repeat=node('repeat-random');
    const syncSeed=()=>node('random-seed').disabled=!repeat.checked;
    repeat.checked=false;syncSeed();repeat.addEventListener('change',syncSeed);
    RobustnessView.init((trial,configuration,stored,index)=>stored||[3,4].includes(ResultArtifacts.forView('custom')?.version)?inspect(index):run(configuration.options,{dates:trial.dates,...CalendarSettings.fields(configuration)}),configuration=>run(configuration.options,null,configuration),()=>{const artifact=ResultArtifacts.forView('custom');return artifact?.kind==='random'?artifact.result:null;});
    node('schedule-period').addEventListener('change',stocks);
    node('schedule-download-holdings').addEventListener('click',()=>csv('holdings'));
    node('schedule-download-returns').addEventListener('click',()=>csv('returns'));
    node('schedule-period-back').addEventListener('click',()=>{if(bounded?.page)void storedPeriods(bounded,Math.max(0,bounded.page.cursor-64));});
    node('schedule-period-next').addEventListener('click',()=>{if(bounded?.page&&bounded.page.next!==null)void storedPeriods(bounded,bounded.page.next);});
    node('schedule-holdings-back').addEventListener('click',()=>{if(bounded)void storedHoldings(bounded,Math.max(0,bounded.holdingCursor-64));});
    node('schedule-holdings-next').addEventListener('click',()=>{if(bounded&&bounded.holdingNext!==null)void storedHoldings(bounded,bounded.holdingNext);});
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
  function inspect(index){inspectedTrial=index;const artifact=ResultArtifacts.forView('custom');if([3,4].includes(artifact?.version))void storedRender(artifact,index+1);else render();}
  function show(artifact){
    const producer=node('result-producer');
    if(producer)producer.textContent=artifact.result.producer?'Calculated by '+artifact.result.producer.label+'.':'Producer not recorded in this result.';
    inspectedTrial=null;bounded=null;node('schedule-period-pages').hidden=true;node('schedule-holdings-pages').hidden=true;
    if(artifact.kind==='random'){
      RobustnessView.render(artifact.result,artifact.settings.engine);node('schedule-results').hidden=true;
    }else{
      if([3,4].includes(artifact.version))void storedRender(artifact,1);else render();node('robustness-results').hidden=true;
    }
    node('schedule-message').textContent='Backtest results ready.';node('schedule-message').className='';
  }
  function cancel(){
    if(!running||!activeRun)return;
    BacktestRuns.stop(activeRun);
    node('stop-backtest').disabled=true;
    node('schedule-message').textContent='Stop requested. The server will confirm after worker and cache cleanup. If disconnected, this request will retry when the page reconnects.';
  }
  return {run,init,resume,cancel,show,isRunning:()=>running};
})();
