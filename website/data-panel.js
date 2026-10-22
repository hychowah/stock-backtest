/* Data jobs are local-service actions; the static page never downloads by itself. */
const DataPanel=(()=>{
  const node=id=>document.getElementById(id);
  const escape=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let lastReport=null,pollTimer=null,connected=false,busy=false;
  function read(){
    const o={scope:node('data-scope').value,symbols:node('data-symbols').value,start:node('data-start').value,end:node('data-end').value,datasets:[...document.querySelectorAll('input[name="data-type"]:checked')].map(e=>e.value)};
    if(!o.start||!o.end||o.start>o.end)throw Error('Choose a start date before the end date.');
    if(!o.datasets.length)throw Error('Select at least one data type.');
    if(o.scope==='symbols'&&!o.symbols.trim())throw Error('Enter the stock symbols to check.');
    return o;
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
    node('data-checked').textContent=`Checked ${new Date(report.checked_at).toLocaleString()} · ${report.options.start} to ${report.options.end} · ${report.options.scope} group. Changes to the controls take effect on the next check.`;
    node('data-key').textContent=report.api_key_present?'FMP key file is present. Provider access is checked only when a download makes a request.':'FMP key file is missing. Checks and rebuilds work offline. Add the key file before downloading.';
    const values=[['Stocks in checked group',report.target_count],['With usable price histories',report.prices_available],['Missing annual financial records',report.missing_financials.length]];
    node('data-summary').innerHTML=values.map(([label,value])=>'<div>'+escape(label)+'<strong>'+escape(value)+'</strong></div>').join('');
    node('data-assets').innerHTML=report.assets.map(row=>'<tr>'+[row.name,row.state,row.count,row.first,row.last].map(v=>'<td>'+escape(v)+'</td>').join('')+'</tr>').join('');
    node('data-financials').textContent=`${(report.issues??[]).join(' ')} ${report.financial_symbols} symbols have financial cache records; ${report.empty_financials.length} returned no annual reports. ${report.invalid_financial_lines} invalid financial lines. ${report.price_files} stock price files are saved overall. Missing financial symbols: ${report.missing_financials.slice(0,30).join(', ')||'none'}${report.missing_financials.length>30?'… (full list in the exported report)':''}.`;
    node('data-derived').innerHTML=report.derived.map(row=>'<tr>'+[row.name,row.state,row.bytes?(row.bytes/1e6).toFixed(1)+' MB':'—'].map(v=>'<td>'+escape(v)+'</td>').join('')+'</tr>').join('');
    stocks();
  }
  function render(state){
    const job=state.job;busy=job.running;
    for(const id of ['data-check','data-download','data-rebuild'])node(id).disabled=!connected||busy;
    node('data-cancel').hidden=!busy;
    node('data-progress').hidden=!job.action;
    node('data-message').textContent=job.message;
    node('data-error').textContent=job.error??'';
    node('data-warnings').textContent=job.warning??'';
    const progress=node('data-progress-bar');progress.hidden=!busy;
    if(job.total>0){progress.max=job.total;progress.value=job.completed;}else progress.removeAttribute('value');
    if(state.report && state.report.checked_at!==lastReport?.checked_at)renderReport(state.report);
    if(busy && pollTimer===null)pollTimer=setTimeout(()=>{pollTimer=null;refresh();},1000);
  }
  async function api(path,body){
    const response=await fetch('/api/data/'+path,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(response.status===404)throw Error('This server does not have the data panel API. Restart start.cmd and open the new browser window.');
    let result;try{result=await response.json();}catch{throw Error('The local service returned an unreadable response. Restart start.cmd.');}
    if(!response.ok)throw Error(result.error??'The local data request failed.');
    return result;
  }
  async function refresh(){
    try{const state=await api('status');connected=true;node('data-connection').textContent='Connected to the local data service.';render(state);}
    catch(error){connected=false;node('data-connection').textContent=error.message+' Open this panel through start.cmd to connect.';for(const id of ['data-check','data-download','data-rebuild'])node(id).disabled=true;}
  }
  async function start(action){
    try{node('data-error').textContent='';const request=action==='cancel'?{}:read();for(const id of ['data-check','data-download','data-rebuild'])node(id).disabled=true;render(await api(action,request));}
    catch(error){node('data-error').textContent=error.message;for(const id of ['data-check','data-download','data-rebuild'])node(id).disabled=!connected||busy;}
  }
  function init(){
    node('data-connect').addEventListener('click',refresh);
    node('data-end').max=new Date().toISOString().slice(0,10);
    for(const action of ['check','download','rebuild','cancel'])node('data-'+action).addEventListener('click',()=>start(action));
    node('data-scope').addEventListener('change',()=>node('data-symbols').disabled=node('data-scope').value!=='symbols');
    node('data-search').addEventListener('input',stocks);
    node('data-export').addEventListener('click',()=>{
      if(!lastReport)return;const url=URL.createObjectURL(new Blob([JSON.stringify(lastReport,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='backtest-data-check.json';link.click();URL.revokeObjectURL(url);
    });
    if(location.protocol==='file:'){
      node('data-connection').textContent='Open start.cmd, then choose Manage backtest data. This saved page needs the local service to inspect or change files.';
      for(const id of ['data-check','data-download','data-rebuild'])node(id).disabled=true;
    }else refresh();
  }
  return {init,read,render,refresh,start};
})();
DataPanel.init();
