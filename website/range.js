const allReturns=data.slice();
const screeningData=JSON.parse(document.getElementById('screening-data').textContent);
const rankFrom=document.getElementById('rank-from'),rankTo=document.getElementById('rank-to');
const fromYear=document.getElementById('from-year'),toYear=document.getElementById('to-year');
const fields={metric:'ranking-metric',pool:'stock-pool',min_cap:'min-cap',max_cap:'max-cap',min_ev:'min-ev',min_yield:'min-yield',max_multiple:'max-multiple',sector:'sector-filter',exchange:'exchange-filter'};
let currentScreen=null,currentLatest=null;
let screeningMode='latest';
const money=v=>v===null?'—':'$'+(v/1e6).toLocaleString('en-US',{maximumFractionDigits:1})+'m';
const safe=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function selectedHoldings(year){return currentScreen?.years.find(y=>y.year===+year)?.holdings??[];}
function medianMarketCap(year){return StockScreener.median(selectedHoldings(year).map(h=>h.market_cap));}
function initializeFilters(){
  const options=allReturns.map(d=>`<option value="${d.year}">${d.year}${d.year===2026?' (partial)':''}</option>`).join('');
  fromYear.innerHTML=toYear.innerHTML=options;
  fromYear.value='1996';toYear.value='2025';rankFrom.value='1';rankTo.value='50';
  for(const [field,index] of [['sector-filter',2],['exchange-filter',1]]){
    const values=[...new Set(Object.values(screeningData.companies).map(c=>c[index]))].sort();
    document.getElementById(field).innerHTML='<option value="">All</option>'+values.map(v=>`<option value="${safe(v)}">${safe(v)}</option>`).join('');
  }
  document.getElementById('ranking-metric').innerHTML=Object.entries(screeningData.metrics).map(([key,m])=>`<option value="${safe(key)}">${safe(m.label)}</option>`).join('');
  document.getElementById('schedule-kind').value='january';
  document.getElementById('trade-start').value='2015-01-01';
  document.getElementById('trade-end').value=screeningData.latest.metadata.asof;
  document.getElementById('trade-end').max=screeningData.latest.metadata.asof;
  document.getElementById('rebalance-months').value='12';
  document.getElementById('date-testing').value='single';
  document.getElementById('random-trials').value='24';
  document.getElementById('random-seed').value='42';
  resetFilters();
}
function resetFilters(){
  for(const [key,id] of Object.entries(fields)){
    const v=StockScreener.defaults[key];
    document.getElementById(id).value=v===null?'':String(key==='min_cap'||key==='min_ev'?v/1e6:key==='min_yield'?v*100:v);
  }
}
function readOptions(){
  const o={first:+fromYear.value,last:+toYear.value,rank_from:+rankFrom.value,rank_to:+rankTo.value};
  for(const [key,id] of Object.entries(fields)){
    const text=document.getElementById(id).value.trim();
    if(['metric','pool','sector','exchange'].includes(key))o[key]=text||null;
    else{
      if(!text && ['min_cap','min_ev','min_yield'].includes(key))throw Error('Fill in each minimum, or enter 0.');
      o[key]=text===''?null:Number(text)*(key==='min_cap'||key==='max_cap'||key==='min_ev'?1e6:key==='min_yield'?.01:1);
    }
  }
  return o;
}
function updateMetricLabels(o){
  const label=screeningData.metrics[o.metric].label;
  document.querySelectorAll('[data-metric-multiple]').forEach(el=>el.textContent=label+' (×)');
  document.querySelectorAll('[data-metric-yield]').forEach(el=>el.textContent='Selected metric yield');
  document.getElementById('strategy-heading').textContent='Lowest '+label;
}
function drawMarketCaps(){
  const values=data.map(d=>medianMarketCap(d.year)).filter(v=>v!==null);
  const max=Math.max(1,Math.ceil(Math.max(0,...values)/1e9)),y=v=>330-v/1e9/max*290,step=1120/data.length;
  let markup='';
  for(let i=0;i<=4;i++){
    const tick=max*i/4,pos=y(tick*1e9);
    markup+=`<line x1="60" x2="1180" y1="${pos}" y2="${pos}" stroke="#e5eae4"/><text x="48" y="${pos+4}" text-anchor="end" font-size="11">$${tick}bn</text>`;
  }
  data.forEach((d,i)=>{
    const v=medianMarketCap(d.year),x=60+i*step+5;
    if(v!==null)markup+=`<rect x="${x}" y="${y(v)}" width="${step-10}" height="${330-y(v)}" fill="#20775e"><title>${d.year}: ${money(v)} median market cap</title></rect>`;
    markup+=`<text transform="translate(${x+step/2-5},353) rotate(-55)" text-anchor="end" font-size="11">${d.year}</text>`;
  });
  document.getElementById('market-cap-chart').innerHTML=markup;
}
function contributionPie(slices,total,sign){
  const colors=sign>0?['#20775e','#359671','#549e7b','#77b38f','#95c8a6','#16745b','#428b76','#66b6a0','#88c9b7','#b1dbc8']:['#ae4d40','#c96957','#db8a70','#e3a38d','#edc0ac'];
  let cursor=0;
  const parts=slices.map((slice,i)=>{
    const share=total>0?slice.value/total*100:0,color=slice.other?(sign>0?'#d8e3dc':'#e8cbc3'):colors[i%colors.length];
    const start=cursor;cursor+=share;
    return {...slice,share,color,gradient:color+' '+start+'% '+cursor+'%'};
  });
  const heading=sign>0?'Gains':'Losses';
  const description=total>0?heading+' contribution '+pp(total*sign)+' percentage points. '+parts.map(p=>p.label+': '+p.share.toFixed(1)+'% of '+heading.toLowerCase()).join('; '):'No '+heading.toLowerCase()+' in this book.';
  return `<figure><h4>${heading}</h4><div class="contribution-pie" role="img" aria-label="${safe(description)}" style="background:${parts.length?'conic-gradient('+parts.map(p=>p.gradient).join(',')+')':'#e5eae4'}"><div class="contribution-pie-center">${pp(total*sign)} pp<small>portfolio impact</small></div></div>${parts.length?'<ul class="contribution-legend">'+parts.map(p=>`<li><i style="background:${p.color}"></i>${safe(p.label)} · ${p.share.toFixed(1)}% · ${pp(p.contribution)} pp</li>`).join('')+'</ul>':'<p class="hint">No '+heading.toLowerCase()+' this year.</p>'}</figure>`;
}
function renderContributions(year){
  const group=ReturnContributions.analyze(selectedHoldings(year));
  const target=document.getElementById('contributions-'+year);
  if(!group.count){target.innerHTML='<p class="contribution-empty">No selected stocks to attribute for this year.</p>';return;}
  const rows=group.top.map(h=>`<tr><td>${safe(h.symbol)}</td><td>${safe(h.name)}</td><td>${pct(h.return_value)}</td><td class="${h.contribution>=0?'positive':'negative'}">${pp(h.contribution)} pp</td></tr>`).join('');
  target.innerHTML=`<div class="contribution-panel"><h3>${year} return contributions${year===2026?' · partial year':''}</h3><p class="hint">Each contribution is the stock return ÷ ${group.count}, in percentage points (pp) of portfolio return. Showing the top ${group.top_count} of ${group.count} stocks, capped at 10 and ranked by signed contribution.</p><div class="contribution-facts"><span>Portfolio return<strong>${pct(group.net)}</strong></span><span>Top ${group.top_count} contribution<strong>${pp(group.top_total)} pp</strong></span><span>Other ${group.count-group.top_count} contribution<strong>${pp(group.other_total)} pp</strong></span></div><div class="contribution-layout"><div><div class="contribution-pies">${contributionPie(group.gain_slices,group.gains,1)}${contributionPie(group.loss_slices,group.losses,-1)}</div><p class="hint">Each pie shows shares of gains or losses separately. Gains minus losses equals the portfolio return. Named slices are top contributors; other stocks are grouped.</p></div><div class="top-contributors"><h3>Top 10 contributors · ${group.top_count} stocks</h3><div class="scroll"><table><thead><tr><th>Stock</th><th>Company</th><th>Stock return</th><th>Contribution</th></tr></thead><tbody>${rows}</tbody></table></div><p class="hint">If all stocks lost money, the top contributors are the smallest losses. Contributions describe this historical book, not the selection signal.</p></div></div></div>`;
}
function renderStockTable(year){
  renderContributions(year);
  const stocks=selectedHoldings(year);
  document.getElementById('holding-body-'+year).innerHTML=stocks.map(h=>{
    const vals=[h.rank,h.symbol,h.name,h.exchange,h.sector,(h.metric_yield*100).toFixed(2)+'%',h.metric_multiple.toFixed(2)+'×',money(h.market_cap),money(h.enterprise_value),h.fiscal,h.entry,h.exit,pct(h.return_value),pp(h.return_value/stocks.length)+' pp',h.status];
    return `<tr>${vals.map(v=>'<td>'+safe(v)+'</td>').join('')}</tr>`;
  }).join('')||'<tr><td colspan="15">No stocks match these filters.</td></tr>';
}
function showHoldingYear(){
  const selected=document.getElementById('holding-year').value;
  if(!selected)return;
  document.querySelectorAll('.holding-years details').forEach(d=>d.open=false);
  const detail=document.getElementById('holdings-'+selected);
  renderStockTable(+selected);detail.open=true;detail.scrollIntoView({behavior:'smooth',block:'start'});
}
function updateWarnings(){
  const o=currentScreen.options;
  const coverage=o.pool==='legacy'?'Original candidate set: the same 250-name pre-price screen as the saved backtest. Report-level $100m market cap / $50m EV floors still apply.':'All prepared stocks with cached prices. This is a partial universe; company sector and exchange are cached profiles, not historical classifications.';
  const warnings=[];
  if(currentScreen.short_years.length)warnings.push('Fewer than '+(o.rank_to-o.rank_from+1)+' matching stocks in: '+currentScreen.short_years.join(', ')+'. Available stocks are equally weighted.');
  if(currentScreen.empty_years.length)warnings.push('No matches in: '+currentScreen.empty_years.join(', ')+'. Strategy CAGR and cumulative growth are unavailable across the full period.');
  const baseline=new Set(Object.values(holdingsData).flatMap(g=>g.holdings.map(h=>h.entry.slice(0,4)+':'+h.symbol)));
  const extraStops=currentScreen.years.flatMap(g=>g.holdings).filter(h=>h.status==='Last available price'&&!baseline.has(h.year+':'+h.symbol)).length;
  if(extraStops)warnings.push(extraStops+' early trading stops fall outside the original top-50 exit review; these use the last available price.');
  document.getElementById('screen-coverage').textContent=coverage;
  const status=document.getElementById('screen-status');
  status.textContent=warnings.join(' ')||'Backtest updated. Every selected year has the requested number of stocks.';
  status.className=warnings.length?'screen-message warning':'screen-message';
}
function setModeVisibility(){
  const latest=screeningMode==='latest',custom=!latest && document.getElementById('schedule-kind').value==='custom';
  if(!custom)ScheduleView.cancel();
  document.getElementById('schedule-choice').hidden=latest;
  document.getElementById('schedule-controls').hidden=!custom;
  document.getElementById('custom-view').hidden=!custom;
  document.getElementById('backtest-view').hidden=latest||custom;
  document.getElementById('latest-view').hidden=!latest;
  document.getElementById('year-controls').hidden=latest||custom;
  document.getElementById('historical-help').hidden=latest||custom;
  document.getElementById('mode-latest').setAttribute('aria-pressed',latest);
  document.getElementById('mode-backtest').setAttribute('aria-pressed',!latest);
  document.getElementById('run-screen').textContent=latest?'Screen latest':'Run backtest';
}
function switchMode(mode){
  screeningMode=mode;setModeVisibility();applyRange();
}
function applyLatest(){
  try{currentLatest=StockScreener.latestScreen(screeningData,readOptions());}
  catch(error){document.getElementById('screen-error').textContent=error.message+' The previous result remains displayed.';return;}
  document.getElementById('screen-error').textContent='';
  const r=currentLatest,o=r.options;
  updateMetricLabels(o);
  document.getElementById('latest-date').textContent=r.asof;
  document.getElementById('latest-count').textContent=String(r.stocks.length);
  document.getElementById('latest-median-cap').textContent=money(r.median_market_cap);
  document.getElementById('latest-median-yield').textContent=r.median_yield===null?'—':(r.median_yield*100).toFixed(2)+'%';
  document.getElementById('latest-body').innerHTML=r.stocks.map(h=>{
    const vals=[h.rank,h.symbol,h.name,h.exchange,h.sector,h.price.toFixed(2),money(h.market_cap),money(h.enterprise_value),(h.metric_yield*100).toFixed(2)+'%',h.metric_multiple.toFixed(2)+'×',h.fiscal,h.known,h.price_date];
    return '<tr>'+vals.map(v=>'<td>'+safe(v)+'</td>').join('')+'</tr>';
  }).join('')||'<tr><td colspan="13">No stocks match these latest-date filters.</td></tr>';
  const meta=screeningData.latest.metadata;
  document.getElementById('screen-coverage').textContent=`Latest cached session: ${r.asof}. Only cached currently-listed names with a price on that exact date are eligible. ${screeningData.latest.cached.length} valued names out of ${meta.eligible_financials} active names with eligible financials; coverage is incomplete.`+(o.pool==='legacy'?' Original candidate set keeps the pre-price 250-name buffer and report-level size floors.':'');
  const status=document.getElementById('screen-status');
  status.textContent=r.stocks.length<r.requested?`Only ${r.stocks.length} picks are available for the requested ${r.requested} ranks after filtering on ${r.asof}.`:`Showing ${r.stocks.length} picks valued at the ${r.asof} cached close, re-ranked from ${r.matches} matching names.`;
  status.className=r.stocks.length<r.requested?'screen-message warning':'screen-message';
  document.getElementById('range-note').textContent=`Latest picks · ${r.asof} · ranks ${o.rank_from}–${o.rank_to} after filters. No January holding returns or future performance are used in this list.`;
  document.querySelector('.pill').textContent=r.asof;
}
function applyRange(changed){
  if(+fromYear.value>+toYear.value){if(changed==='from')toYear.value=fromYear.value;else fromYear.value=toYear.value;}
  if(+rankFrom.value>+rankTo.value && ['rank-from','rank-to'].includes(changed)){
    if(changed==='rank-from')rankTo.value=rankFrom.value;else rankFrom.value=rankTo.value;
  }
  if(screeningMode==='latest'){applyLatest();return;}
  if(document.getElementById('schedule-kind').value==='custom'){
    document.getElementById('range-note').textContent='Custom schedule: trade dates and interval determine holding periods. Results and CSV exports below use this schedule.';
    document.getElementById('screen-coverage').textContent='Custom dates use the local daily-cache service. Original candidate-set restrictions and cached-price coverage still apply.';
    document.getElementById('screen-status').textContent='Apply the current stock filters to the custom schedule.';
    document.getElementById('screen-status').className='screen-message';
    try{ScheduleView.run(readOptions());}catch(error){document.getElementById('screen-error').textContent=error.message;}
    return;
  }
  try{
    const next=StockScreener.screen(screeningData,readOptions());
    currentScreen=next;
  }catch(error){document.getElementById('screen-error').textContent=error.message+' The previous result remains displayed.';return;}
  document.getElementById('screen-error').textContent='';
  data=currentScreen.years.map(y=>({year:y.year,portfolio:y.portfolio,spy:y.spy,names:y.names}));
  updateMetricLabels(currentScreen.options);
  const {first,last,rank_from,rank_to}=currentScreen.options;
  document.getElementById('strategy-legend').textContent=`${screeningData.metrics[currentScreen.options.metric].label} ranks ${rank_from}–${rank_to}`;
  draw();drawMarketCaps();
  document.getElementById('rows').innerHTML=data.map(d=>`<tr><td>${d.year}${d.year===2026?'*':''}</td><td>${d.names}</td><td class="${d.portfolio>=0?'positive':'negative'}">${d.portfolio===null?'—':pct(d.portfolio)}</td><td class="${d.spy>=0?'positive':'negative'}">${pct(d.spy)}</td><td>${d.portfolio===null?'—':pp(d.portfolio-d.spy)}</td></tr>`).join('');
  const active=document.getElementById('holding-year').value;
  document.querySelectorAll('.holding-years details').forEach(el=>{
    const year=+el.id.replace('holdings-',''),stocks=selectedHoldings(year);
    el.hidden=year<first||year>last;
    if(el.hidden)el.open=false;
    document.getElementById('holding-summary-'+year).textContent=`${year} · ${stocks.length} stocks · Ranks ${rank_from}–${rank_to} · Median market cap ${money(medianMarketCap(year))}`;
    document.getElementById('holding-body-'+year).innerHTML='';
    document.getElementById('contributions-'+year).innerHTML='';
    if(el.open)renderStockTable(year);
  });
  document.getElementById('holding-year').innerHTML='<option value="">Choose year…</option>'+data.map(d=>`<option value="${d.year}">${d.year}</option>`).join('');
  if(active && +active>=first && +active<=last)document.getElementById('holding-year').value=active;
  else{
    document.getElementById('holding-year').value=String(last);
    renderStockTable(last);
    document.getElementById('holdings-'+last).open=true;
  }
  const stats=document.querySelectorAll('.stat strong'),notes=document.querySelectorAll('.stat small');
  stats[0].textContent=currentScreen.cagr===null?'—':(currentScreen.cagr*100).toFixed(2)+'%';
  stats[1].textContent=(currentScreen.spy_cagr*100).toFixed(2)+'%';
  stats[2].textContent=currentScreen.growth===null?'—':'$'+currentScreen.growth.toFixed(2);
  notes[0].textContent=currentScreen.first+' → '+currentScreen.end;
  notes[1].textContent='Same selected holding periods';
  notes[2].textContent='Strategy · SPY $'+currentScreen.spy_growth.toFixed(2);
  document.getElementById('range-note').textContent=`${first}–${last} books, inclusive · ${currentScreen.first} to ${currentScreen.end}${last===2026?' · 2026 is partial':''}. Ranks ${rank_from}–${rank_to} after filtering, equal weight. CSV exports use the current selection.`;
  document.getElementById('detail').textContent='Hover over or focus a bar to see its return.';
  document.querySelector('.pill').textContent=`${first} — ${last}${last===2026?'*':''}`;
  updateWarnings();
}
function downloadLatest(){
  if(!currentLatest)return;
  const keys=['rank','symbol','name','exchange','sector','price','market_cap','enterprise_value','ebitda_yield','ev_ebitda','metric','metric_yield','metric_multiple','fiscal','known','price_date'];
  const rows=[keys,...currentLatest.stocks.map(h=>keys.map(k=>k==='metric'?currentLatest.options.metric:h[k]))];
  const csv=rows.map(row=>row.map(v=>'"'+String(v??'').replace(/"/g,'""')+'"').join(',')).join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='latest-picks-'+currentLatest.asof+'.csv';a.click();URL.revokeObjectURL(url);
}
function downloadSelection(kind){
  if(!currentScreen)return;
  let rows;
  if(kind==='holdings'){
    const keys=['year','rank','symbol','name','exchange','sector','market_cap','enterprise_value','ebitda_yield','ev_ebitda','metric','metric_yield','metric_multiple','fiscal','entry','exit','return_value','weight','contribution_pp','status'];
    rows=[keys,...currentScreen.years.flatMap(y=>y.holdings.map(h=>keys.map(k=>k==='metric'?currentScreen.options.metric:k==='weight'?1/y.names:k==='contribution_pp'?h.return_value/y.names*100:h[k])))];
  }else rows=[['year','names','portfolio','spy','median_market_cap'],...currentScreen.years.map(y=>[y.year,y.names,y.portfolio??'',y.spy,y.median_market_cap??''])];
  const csv=rows.map(row=>row.map(v=>'"'+String(v??'').replace(/"/g,'""')+'"').join(',')).join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download=kind+'-'+currentScreen.options.first+'-'+currentScreen.options.last+'.csv';a.click();URL.revokeObjectURL(url);
}
initializeFilters();
ScheduleView.init();
document.getElementById('schedule-kind').addEventListener('change',()=>{setModeVisibility();applyRange();});
setModeVisibility();
document.getElementById('mode-latest').addEventListener('click',()=>switchMode('latest'));
document.getElementById('mode-backtest').addEventListener('click',()=>switchMode('backtest'));
document.getElementById('download-latest').addEventListener('click',e=>{e.preventDefault();downloadLatest();});
fromYear.addEventListener('change',()=>applyRange('from'));
toYear.addEventListener('change',()=>applyRange('to'));
rankFrom.addEventListener('change',()=>applyRange('rank-from'));
rankTo.addEventListener('change',()=>applyRange('rank-to'));
document.getElementById('strategy-form').addEventListener('submit',e=>{e.preventDefault();applyRange();});
document.getElementById('reset-range').addEventListener('click',()=>{fromYear.value='1996';toYear.value='2025';applyRange();});
document.getElementById('reset-ranks').addEventListener('click',()=>{rankFrom.value='1';rankTo.value='50';applyRange();});
document.getElementById('top100').addEventListener('click',()=>{rankFrom.value='1';rankTo.value='100';applyRange();});
document.getElementById('reset-strategy').addEventListener('click',()=>{resetFilters();rankFrom.value='1';rankTo.value='50';applyRange();});
document.getElementById('holding-year').addEventListener('change',showHoldingYear);
document.querySelectorAll('.holding-years details').forEach(el=>el.addEventListener('toggle',()=>{if(el.open)renderStockTable(+el.id.replace('holdings-',''));}));
document.getElementById('download-returns').addEventListener('click',e=>{e.preventDefault();downloadSelection('returns');});
document.getElementById('download-holdings').addEventListener('click',e=>{e.preventDefault();downloadSelection('holdings');});
applyRange();
