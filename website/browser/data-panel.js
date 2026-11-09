/* The service owns updates and timing. Opening or reconnecting only reads status. */
const DataPanel=(()=>{
  const node=id=>document.getElementById(id);
  const escape=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const controls=['data-update','data-add','data-check','data-rebuild'];
  let lastReport=null,pollTimer=null,connected=false,busy=false,submitting=false,uncertain=false,lastUpdate={},admissionError='';
  function read(){
    const o={market:node('data-market')?.value||'us',scope:node('data-scope').value,symbols:node('data-symbols').value,start:node('data-start').value,end:node('data-end').value,datasets:['universe','financials','fundamentals','prices','spy','treasury']};
    if(!o.start||!o.end||o.start>o.end)throw Error('Choose a start date before the end date.');
    if(o.scope==='symbols'&&!o.symbols.trim())throw Error('Enter the stock symbols to update.');
    return o;
  }
  function duration(seconds){
    if(!Number.isFinite(seconds))return '—';
    const s=Math.max(0,Math.floor(seconds)),h=Math.floor(s/3600),m=Math.floor(s%3600/60);
    return (h?h+' hr ':'')+(m||h?m+' min ':'')+(s%60)+' sec';
  }
  function remaining(seconds){
    if(!Number.isFinite(seconds))return 'Estimating time remaining';
    if(seconds<60)return 'Less than a minute';
    const low=Math.max(1,Math.floor(seconds*.8/60)),high=Math.max(low+1,Math.ceil(seconds*1.3/60));
    return low+'–'+high+' min';
  }
  function schedule(delay){
    if(pollTimer===null)pollTimer=setTimeout(()=>{pollTimer=null;refresh();},delay);
  }
  function disable(){
    for(const id of controls)node(id).disabled=!connected||busy||submitting||uncertain;
    if(lastUpdate.can_continue)node('data-add').disabled=true;
    node('data-cancel').disabled=!connected||submitting||lastUpdate.stage==='Stopping safely';
  }
  function stocks(){
    const query=node('data-search').value.trim().toUpperCase();
    const rows=(lastReport?.prices??[]).filter(row=>(row.symbol+' '+row.state).toUpperCase().includes(query));
    node('data-prices').innerHTML=rows.map(row=>'<tr>'+[row.symbol,row.state,row.count,row.first,row.last,row.windows].map(v=>'<td>'+escape(v)+'</td>').join('')+'</tr>').join('')||'<tr><td colspan="6">No stock histories match.</td></tr>';
    node('data-price-note').textContent=`Showing ${rows.length} of ${lastReport?.target_count??0} stocks in the checked group. Dates show actual saved prices.`;
  }
  function renderReport(report){
    if(!report)return;
    lastReport=report;node('data-export').disabled=false;
    node('data-checked').textContent=`Checked ${new Date(report.checked_at).toLocaleString()} · ${report.options.start} to ${report.options.end} · ${report.options.market||'us'} market · ${report.options.scope} group.`;
    node('data-key').textContent=report.api_key_present?'Provider key file is present. Access is checked when an update makes a request.':'Provider key file is missing. Checks and preparation work offline. Add the key before updating.';
    const values=[['Stocks in checked group',report.target_count],['With usable price histories',report.prices_available],['Missing annual records',report.missing_financials.length]];
    node('data-summary').innerHTML=values.map(([label,value])=>'<div>'+escape(label)+'<strong>'+escape(value)+'</strong></div>').join('');
    node('data-assets').innerHTML=report.assets.map(row=>'<tr>'+[row.name,row.state,row.count,row.first,row.last].map(v=>'<td>'+escape(v)+'</td>').join('')+'</tr>').join('');
    node('data-financials').textContent=`${(report.issues??[]).join(' ')} ${report.financial_symbols} symbols have annual records. ${report.invalid_financial_lines} invalid financial lines. Missing symbols: ${report.missing_financials.slice(0,30).join(', ')||'none'}.`;
    node('data-derived').innerHTML=report.derived.map(row=>'<tr>'+[row.name,row.state,row.bytes?(row.bytes/1e6).toFixed(1)+' MB':'—'].map(v=>'<td>'+escape(v)+'</td>').join('')+'</tr>').join('');
    stocks();
  }
  function render(state){
    const job=state.job??{};
    let update=state.update??state.refresh??{};
    if(job.running&&['update','refresh','continue'].includes(job.action)&&!update.running){
      update={...update,percent:null,estimated_remaining_seconds:null,ready:false,error:null,
        elapsed_seconds:job.action==='continue'?update.elapsed_seconds:0,stage:job.message,work:{}};
    }
    lastUpdate=update;
    const prepared=Boolean(state.prepared??update.ready);
    busy=Boolean(update.running||update.unconfirmed||job.running);
    node('data-update').textContent=update.can_continue?'Continue update':'Update data';
    node('data-cancel').hidden=!busy||update.unconfirmed&&!job.running;
    node('data-connect').hidden=connected;
    node('data-readiness').textContent=update.unconfirmed?'Update status unconfirmed':busy?'Updating data':prepared?(update.can_continue?'Ready for backtests. Update unfinished.':'Ready for backtests'):update.outcome==='interrupted'?'Update interrupted':update.outcome==='cancelled'?'Update stopped':update.outcome==='failed'?'Update needs attention':update.outcome==='partial'?'Some data could not be updated':'Choose Update data to get ready';
    const code=node('data-market')?.value||'us',dates=state.latest_dates??update.latest_dates;
    node('data-latest').textContent=(dates?dates[code]:code==='us'?('latest_session' in state?state.latest_session:update.latest_session):null)??'No prepared session';
    node('data-last-success').textContent=update.last_success?new Date(update.last_success).toLocaleString():'No successful update recorded';
    node('data-open').hidden=!prepared||busy;
    node('data-progress').hidden=!update.started_at&&!update.outcome&&!job.action;
    node('data-progress-title').textContent=update.unconfirmed?'Waiting to confirm update status':busy?'Updating your data':update.outcome==='complete'?'Data updated':update.can_continue?'Your update can continue':'Saved data';
    const percent=update.outcome==='complete'&&prepared?100:update.percent===100?null:update.percent;
    node('data-percent').textContent=Number.isFinite(percent)?(percent===100?'100% complete':'About '+percent+'% complete'):'Estimating overall completion';
    if(update.unconfirmed)node('data-percent').textContent='Last recorded: '+node('data-percent').textContent;
    node('data-elapsed').textContent=duration(update.elapsed_seconds);
    node('data-remaining').textContent=update.unconfirmed?'Unconfirmed':busy?remaining(update.estimated_remaining_seconds):update.outcome==='complete'?'Complete':update.can_continue?'Available when you continue':'—';
    const message=update.stage??(job.running?'Checking saved data':job.message??'');
    node('data-message').textContent=message;
    const current=update.work?.[update.kind];
    node('data-count').textContent=current?.total>0?`${current.completed.toLocaleString()} of ${current.total.toLocaleString()} checked · ${Math.min(100,Math.floor(100*current.completed/current.total))}% of this step`:'';
    node('data-estimate-note').textContent=update.estimate_note??'';
    node('data-detail').textContent=update.detail??job.message??'';
    node('data-error').textContent=update.error??job.error??admissionError;
    node('data-warnings').textContent=update.warning??job.warning??'';
    node('data-log').textContent=state.log_file?'Development log: '+state.log_file:'';
    const bar=node('data-progress-bar');
    if(Number.isFinite(percent)){bar.max=100;bar.value=percent;}else bar.removeAttribute('value');
    const steps=[['Checking',['checking']],['Reports',['annual','statements']],['Prices',['prices']],['Preparing',['research','daily','website','sheets']],['Ready',['verify']]];
    node('data-steps').innerHTML=steps.map(([label,kinds])=>{
      const work=kinds.map(k=>update.work?.[k]);
      const done=work.every(w=>w&&w.total!==null&&w.completed>=w.total);
      const current=kinds.includes(update.kind)&&busy;
      return '<li'+(current?' aria-current="step"':'')+'>'+(done?'✓ ':'')+label+'</li>';
    }).join('');
    if(state.report&&state.report.checked_at!==lastReport?.checked_at)renderReport(state.report);
    disable();schedule(busy?1000:5000);
  }
  async function api(path,body){
    const response=await fetch('/api/data/'+path,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(response.status===404)throw Error('Restart start.cmd to use the updated data page.');
    let result;try{result=await response.json();}catch{throw Error('The local service could not be read. Reconnecting…');}
    if(!response.ok){const error=Error(result.error??'The data action could not start. Reconnect and try again.');error.rejected=response.status>=400&&response.status<500;throw error;}
    return result;
  }
  async function refresh(){
    try{
      const state=await api('status');connected=true;
      if(uncertain)admissionError='';
      uncertain=false;
      node('data-connection').textContent='Connected. Updates continue if you close this page.';
      render(state);
    }catch(error){
      connected=false;node('data-connection').textContent='Connection lost. Reconnecting… '+error.message;
      node('data-readiness').textContent='Cannot read update status';
      node('data-connect').hidden=false;
      node('data-percent').textContent='Last seen: '+node('data-percent').textContent.replace(/^Last seen: /,'');
      node('data-remaining').textContent='Last seen: '+node('data-remaining').textContent.replace(/^Last seen: /,'');
      disable();schedule(2000);
    }
  }
  async function start(action,scoped=false){
    if(submitting||uncertain)return;
    let request;
    try{
      request=action==='continue'||action==='cancel'?{}:action==='update'&&!scoped?{market:node('data-market')?.value||'us'}:action==='rebuild'?{}:read();
    }catch(error){admissionError=error.message;node('data-error').textContent=admissionError;return;}
    submitting=true;disable();admissionError='';node('data-error').textContent='';
    try{const state=await api(action,request);submitting=false;render(state);}
    catch(error){
      submitting=false;uncertain=!error.rejected;admissionError=error.message;node('data-error').textContent=admissionError;
      if(error.rejected){disable();return;}
      // A lost response does not prove rejection. Observe before offering a new start.
      await refresh();
    }
  }
  function init(){
    node('data-connect').addEventListener('click',refresh);
    const now=new Date();
    node('data-end').max=[now.getFullYear(),now.getMonth()+1,now.getDate()].map(n=>String(n).padStart(2,'0')).join('-');
    if(!node('data-end').value)node('data-end').value=node('data-end').max;
    node('data-update').addEventListener('click',()=>start(lastUpdate.can_continue?'continue':'update'));
    node('data-add').addEventListener('click',()=>start('update',true));
    for(const action of ['check','rebuild','cancel'])node('data-'+action).addEventListener('click',()=>start(action));
    node('data-scope').addEventListener('change',()=>node('data-symbols').disabled=node('data-scope').value!=='symbols');
    node('data-market')?.addEventListener('change',refresh);
    node('data-search').addEventListener('input',stocks);
    node('data-export').addEventListener('click',()=>{
      if(!lastReport)return;const url=URL.createObjectURL(new Blob([JSON.stringify(lastReport,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='backtest-data-check.json';link.click();URL.revokeObjectURL(url);
    });
    if(location.protocol==='file:'){
      connected=false;
      node('data-readiness').textContent='Open the local data service';
      node('data-connection').textContent='Open start.cmd, then choose Manage backtest data to connect.';disable();
    }else refresh();
  }
  return {init,read,render,refresh,start};
})();
DataPanel.init();
