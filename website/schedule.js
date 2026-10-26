/* Custom dated books use the local prepared daily cache. Rendering consumes
   dated periods; it never assumes one rebalance per calendar year. */
const ScheduleView=(()=>{
  let result=null,requestNumber=0,running=false,timer=null,startedAt=0,buttonText='',hasResults=false,controller=null;
  const node=id=>document.getElementById(id);
  const format=v=>v===null?'—':(v*100).toFixed(2)+'%';
  const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function elapsed(){
    const seconds=Math.max(0,Math.floor((Date.now()-startedAt)/1000));
    return Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');
  }
  function startBusy(){
    running=true;startedAt=Date.now();
    const button=node('run-screen');buttonText=button.textContent;
    button.disabled=true;
    node('stop-backtest').hidden=false;
    button.textContent='Backtesting…';
    node('custom-view').setAttribute('aria-busy','true');
    node('schedule-progress').hidden=false;
    node('schedule-message').className='';
    node('schedule-message').textContent=hasResults?'Backtest in progress. Previous results remain below until it finishes.':'Backtest in progress. Results will appear here when ready.';
    const tick=()=>node('schedule-elapsed').textContent=elapsed();
    tick();timer=setInterval(tick,1000);
    updateResultsState();
  }
  function stopBusy(){
    if(timer!==null){clearInterval(timer);timer=null;}
    if(running){
      node('run-screen').disabled=false;
      node('run-screen').textContent=buttonText;
    }
    running=false;controller=null;
    node('stop-backtest').hidden=true;
    node('schedule-progress').hidden=true;
    node('custom-view').setAttribute('aria-busy','false');
    updateResultsState();
  }
  function csv(kind){
    if(!result)return;
    const keys=kind==='holdings'?['period_start','period_end','rank','symbol','name','exchange','sector','market_cap','enterprise_value','metric','metric_multiple','metric_yield','fiscal','entry','exit','return_value','weight','contribution_pp','status']:['entry','exit','names','portfolio','spy'];
    const observations=kind==='holdings'?result.periods.flatMap(p=>p.holdings.map(h=>({...h,period_start:p.entry,period_end:p.exit,metric:result.options.metric??'ev_ebitda'}))):result.periods;
    const rows=[keys,...observations.map(h=>keys.map(k=>h[k]))];
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
    node('schedule-results').hidden=false;
    node('schedule-dates').textContent=result.start+' → '+result.end+' · every '+result.months+' month(s)';
    node('schedule-cagr').textContent=format(result.cagr);
    node('schedule-spy-cagr').textContent=format(result.spy_cagr);
    node('schedule-growth').textContent=result.growth===null?'—':'$'+result.growth.toFixed(2);
    const requested=(result.options.rank_to??50)-(result.options.rank_from??1)+1;
    const short=result.periods.filter(p=>p.names<requested).length,empty=result.periods.filter(p=>p.names===0).length;
    node('schedule-coverage').textContent=result.coverage+' '+short+' short periods; '+empty+' empty periods. '+(empty?'Full-period strategy growth and CAGR unavailable. ':'')+'Computed in '+result.seconds.toFixed(2)+'s; repeated periods reuse prepared books.'+(result.cash_days?' Both strategy and paired SPY hold cash until '+result.first_trade+' ('+result.cash_days+' days); CAGR uses the common window.':'');
    chart(result.periods);
    node('schedule-rows').innerHTML=result.periods.map(p=>'<tr>'+[p.entry,p.exit,p.names,format(p.portfolio),format(p.spy)].map(v=>'<td>'+escape(v)+'</td>').join('')+'</tr>').join('');
    node('schedule-period').innerHTML=result.periods.map((p,i)=>`<option value="${i}">${p.entry} → ${p.exit} · ${p.names} stocks</option>`).join('');
    node('schedule-period').value=String(result.periods.length-1);stocks();
  }
  async function run(options,override=null,replay=null){
    if(running)return;
    const number=++requestNumber;
    if(typeof location==='undefined' || location.protocol==='file:'){
      node('screen-error').textContent='Custom dates use the local service. Double-click start.cmd, or run python3 website/serve.py, then use the browser window it opens.';return;
    }
    const {first,last,...filters}=options;
    const random=!!replay || (!override && node('date-testing').value==='random');
    const body=override?{...filters,...override}:{...filters,start:node('trade-start').value,end:node('trade-end').value,months:+node('rebalance-months').value};
    if(replay){Object.assign(body,{...replay.options,start:replay.start,end:replay.end,months:replay.months,trials:replay.requested,seed:replay.seed});}
    else if(random){
      body.trials=+node('random-trials').value;
      if(node('repeat-random').checked)body.seed=+node('random-seed').value;
    }
    node('screen-error').textContent='';
    node('schedule-progress-detail').textContent=body.start+' → '+body.end+' · every '+body.months+' month(s). '+(random?body.trials+' random-date trials; preparing new dates can take longer.':'New schedules can take a few minutes.');
    node('trial-progress').hidden=!random;node('trial-progress').value=0;node('trial-progress').max=random?body.trials:1;
    controller=new AbortController();
    startBusy();
    try{
      const headers={'Content-Type':'application/json'};
      if(random)headers['X-Backtest-Details']='holdings';
      const response=await fetch(random?'/api/robustness':'/api/schedule',{method:'POST',headers,body:JSON.stringify(body),signal:controller.signal});
      if(number!==requestNumber){await response.body?.cancel();return;}
      if(!response.ok){
        if(response.status===404)throw Error('This tab is connected to an older server. Run start.cmd again and use the new browser tab it opens. Refreshing this tab alone does not update the server.');
        const error=await response.json();throw Error(error.error||'Schedule calculation failed.');
      }
      const next=random?await RobustnessView.read(response,event=>{
        if(number===requestNumber && (event.type==='progress'||event.type==='preparation')){
          node('trial-progress').value=event.completed;node('trial-progress').max=event.total;
          const books=event.total_new_books>0?' · preparing books '+event.calculated_books+'/'+event.total_new_books+' with '+event.workers+' worker'+(event.workers===1?'':'s'):'';
          node('schedule-progress-detail').textContent=event.completed+'/'+event.total+' trials complete'+books+' · '+(event.completed<event.total?'evaluating trial '+event.trial:'finishing summary')+' · every '+body.months+' month(s).';
        }
      },()=>number===requestNumber):await response.json();
      if(number!==requestNumber)return;
      renderingCatalog={metrics:screeningData.metrics,filters:screeningData.filter_catalog};
      if(random){
        RobustnessView.render(next);hasResults=true;
        rememberResult({mode:'random',...body},next);
        node('schedule-results').hidden=true;
        node('schedule-message').textContent='Random-date test complete · '+next.completed+' trials · '+elapsed()+' elapsed.';
        node('schedule-message').className='backtest-complete';
        return;
      }
      if(!override)node('robustness-results').hidden=true;
      result=next;render();hasResults=true;
      rememberResult({mode:'custom',...body},next);
      node('schedule-message').textContent='Backtest complete · '+result.periods.length+' holding periods · '+elapsed()+' elapsed.';
      node('schedule-message').className='backtest-complete';
    }catch(error){if(number===requestNumber){
      const message=error instanceof TypeError?'Could not reach the server. If you closed it, restart start.cmd and run this backtest again.':error.message;
      node('screen-error').textContent=message+(hasResults?' The previous results remain displayed.':' Try running the backtest again.');
      node('schedule-message').textContent='Backtest failed after '+elapsed()+'.';
      node('schedule-message').className='backtest-failed';
    }}finally{if(number===requestNumber)stopBusy();}
  }
  function init(){
    const repeat=node('repeat-random');
    const syncSeed=()=>node('random-seed').disabled=!repeat.checked;
    repeat.checked=false;syncSeed();repeat.addEventListener('change',syncSeed);
    RobustnessView.init((trial,configuration,stored)=>stored?inspect(stored):run(configuration.options,{dates:trial.dates,start:configuration.start,end:configuration.end,months:configuration.months}),configuration=>run(configuration.options,null,configuration));
    node('schedule-period').addEventListener('change',stocks);
    node('schedule-download-holdings').addEventListener('click',()=>csv('holdings'));
    node('schedule-download-returns').addEventListener('click',()=>csv('returns'));
  }
  function inspect(stored){result=stored;render();hasResults=true;}
  function restore(stored,kind){
    if(kind==='random'){
      RobustnessView.render(stored);node('schedule-results').hidden=true;
    }else{
      result=stored;render();node('robustness-results').hidden=true;
    }
    hasResults=true;node('schedule-message').textContent='Saved backtest restored. No calculation was run.';node('schedule-message').className='';
  }
  function cancel(){
    if(!running)return;
    requestNumber++;controller?.abort();stopBusy();
    node('schedule-message').textContent='Backtest stopped.'+(hasResults?' Previous results remain displayed.':' Select Run backtest when ready.')+' A new run may wait for cleanup.';
    node('schedule-message').className='';
  }
  return {run,init,cancel,restore,isRunning:()=>running};
})();
