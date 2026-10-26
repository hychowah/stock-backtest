const allReturns=data.slice();
const screeningData=JSON.parse(document.getElementById('screening-data').textContent);
const rankFrom=document.getElementById('rank-from'),rankTo=document.getElementById('rank-to');
const fromYear=document.getElementById('from-year'),toYear=document.getElementById('to-year');
const fields={metric:'ranking-metric',pool:'stock-pool',min_cap:'min-cap',max_cap:'max-cap',min_ev:'min-ev',min_yield:'min-yield',max_multiple:'max-multiple',sector:'sector-filter',exchange:'exchange-filter'};
let screeningMode='latest';
let filterConditions=[];
function viewKey(){return screeningMode==='latest'?'latest':document.getElementById('schedule-kind').value==='custom'?'custom':'january';}
const currentArtifact=()=>ResultArtifacts.forView(viewKey());
const sourceCatalog=()=>({metrics:screeningData.metrics,filters:screeningData.filter_catalog});
const displayCatalog=()=>currentArtifact()?.catalog||sourceCatalog();
const metricLabel=id=>displayCatalog().metrics[id]?.label||screeningData.metrics[id]?.label||id;
function currentSettings(){
  const {first,last,...options}=readOptions(),view=viewKey();
  if(view==='latest')return {mode:'latest',...options};
  if(view==='january')return {mode:'january',first,last,...options};
  const settings={mode:'custom',...options,start:document.getElementById('trade-start').value,end:document.getElementById('trade-end').value,months:+document.getElementById('rebalance-months').value};
  if(document.getElementById('date-testing').value==='random'){
    settings.mode='random';settings.trials=+document.getElementById('random-trials').value;
    if(document.getElementById('repeat-random').checked)settings.seed=+document.getElementById('random-seed').value;
  }
  return settings;
}
function applyPresentation(presentation={}){
  document.getElementById('screen-coverage').textContent=presentation.coverage||'';
  const notice=presentation.notice||{};
  document.getElementById('screen-status').textContent=notice.text||'';
  document.getElementById('screen-status').className='screen-message'+(notice.severity==='warning'?' warning':'');
  document.getElementById('range-note').textContent=presentation.rangeNote||'';
  document.querySelector('.pill').textContent=presentation.periodLabel||'';
}
function publishResult(artifact){
  const completed=ResultArtifacts.publish(artifact);
  if((completed.kind==='random'?'custom':completed.kind)!==viewKey()){
    if(['custom','random'].includes(completed.kind))ScheduleView.show(completed);
    updateResultsState();return;
  }
  applyPresentation(completed.presentation);
  syncCatalogControls();renderConditions();updateMetricLabels(completed.settings);
  if(completed.kind==='latest')renderLatest(completed.result);
  else if(completed.kind==='january')renderJanuary(completed.result);
  else ScheduleView.show(completed);
  document.getElementById('screen-error').textContent='';updateResultsState();
}
function completeResult(settings,result){
  const presentation=settings.mode==='latest'?latestPresentation(result):settings.mode==='january'?januaryPresentation(result):{
    coverage:'Custom dates use the local daily-cache service. Original candidate-set restrictions and cached-price coverage still apply.',
    notice:{text:'Results use the submitted stock filters and trade dates.',severity:'info'},
    rangeNote:'Custom schedule: trade dates and interval determine holding periods. Results and CSV exports below use this schedule.',
    periodLabel:settings.start+' → '+settings.end};
  publishResult(ResultArtifacts.create(settings,result,sourceCatalog(),presentation));
}
function updateResultsState(){
  const view=viewKey(),saved=currentArtifact(),state=document.getElementById('results-state');
  let matches=false;try{matches=ResultArtifacts.matches(saved,currentSettings());}catch(_){}
  const stale=!!saved&&!matches;
  state.className='screen-message'+(stale||!saved?' warning':'');
  state.textContent=stale?'Settings changed — displayed results do not match the current settings. Select '+(view==='latest'?'Screen latest':'Run backtest')+' to update them. Downloads still use the displayed results.':!saved?'No results for these settings yet. Select '+(view==='latest'?'Screen latest.':'Run backtest.'):'Results match the current settings.';
  if(ScheduleView.isRunning())state.textContent+=' A backtest is running with the settings submitted at its start.';
  for(const id of ['latest-view','backtest-view','custom-view'])document.getElementById(id).setAttribute('data-results-stale',String(stale));
  SavedBacktests.update();
}
function settingsChanged(changed,run=true){
  if(+fromYear.value>+toYear.value){if(changed==='from')toYear.value=fromYear.value;else fromYear.value=toYear.value;}
  if(+rankFrom.value>+rankTo.value && ['rank-from','rank-to'].includes(changed)){
    if(changed==='rank-from')rankTo.value=rankFrom.value;else rankFrom.value=rankTo.value;
  }
  updateResultsState();
  if(run && document.getElementById('auto-run').checked && !ScheduleView.isRunning())applyRange();
}
const money=v=>v===null?'—':'$'+(v/1e6).toLocaleString('en-US',{maximumFractionDigits:1})+'m';
const safe=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function selectedHoldings(year){return ResultArtifacts.forView('january')?.result.years.find(y=>y.year===+year)?.holdings??[];}
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
function renderConditions(){
  const container=document.getElementById('filter-conditions');
  container.innerHTML=filterConditions.map((c,i)=>`<div class="condition-row">
    <label>Metric<select data-index="${i}" data-key="field" aria-label="Filter ${i+1} metric">${Object.entries({...screeningData.filter_catalog,...displayCatalog().filters}).map(([key,m])=>`<option value="${safe(key)}" ${key===c.field?'selected':''} ${m.available?'':'disabled'}>${safe(m.label)}${m.available?'':' — needs financial data'}</option>`).join('')}</select></label>
    <label>Comparison<select data-index="${i}" data-key="op" aria-label="Filter ${i+1} comparison"><option value="lt" ${c.op==='lt'?'selected':''}>Less than (&lt;)</option><option value="gt" ${c.op==='gt'?'selected':''}>More than (&gt;)</option></select></label>
    <label>Value<input data-index="${i}" data-key="value" aria-label="Filter ${i+1} value" type="number" step="any" required value="${safe(c.value)}" placeholder="Enter value"></label>
    <button type="button" data-remove="${i}" aria-label="Remove filter ${i+1}">Remove</button></div>`).join('');
  document.getElementById('add-filter').disabled=filterConditions.length>=50;
}
function resetFilters(){
  filterConditions=[];renderConditions();
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
  o.filters=filterConditions.map(c=>{
    if(String(c.value).trim()==='')throw Error('Enter a value for each added filter.');
    return {...c,value:Number(c.value)};
  });
  return o;
}
function updateMetricLabels(o){
  const label=metricLabel(o.metric);
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
    if(v!==null)markup+=`<rect tabindex="0" x="${x}" y="${y(v)}" width="${step-10}" height="${330-y(v)}" fill="#20775e"><title>${d.year}: ${money(v)} median market cap</title></rect>`;
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
function januaryPresentation(result){
  const o=result.options;
  const coverage=o.pool==='legacy'?'Original candidate set: the same 250-name pre-price screen as the saved backtest. Report-level $100m market cap / $50m EV floors still apply.':'All prepared stocks with cached prices. This is a partial universe; company sector and exchange are cached profiles, not historical classifications.';
  const warnings=[];
  if(result.short_years.length)warnings.push('Fewer than '+(o.rank_to-o.rank_from+1)+' matching stocks in: '+result.short_years.join(', ')+'. Available stocks are equally weighted.');
  if(result.empty_years.length)warnings.push('No matches in: '+result.empty_years.join(', ')+'. Strategy CAGR and cumulative growth are unavailable across the full period.');
  const baseline=new Set(Object.values(holdingsData).flatMap(g=>g.holdings.map(h=>h.entry.slice(0,4)+':'+h.symbol)));
  const extraStops=result.years.flatMap(g=>g.holdings).filter(h=>h.status==='Last available price'&&!baseline.has(h.year+':'+h.symbol)).length;
  if(extraStops)warnings.push(extraStops+' early trading stops fall outside the original top-50 exit review; these use the last available price.');
  const {first,last,rank_from,rank_to}=o;
  return {coverage,notice:{text:warnings.join(' ')||'Backtest updated. Every selected year has the requested number of stocks.',severity:warnings.length?'warning':'info'},
    rangeNote:`${first}–${last} books, inclusive · ${result.first} to ${result.end}${last===2026?' · 2026 is partial':''}. Ranks ${rank_from}–${rank_to} after filtering, equal weight. CSV exports use the current selection.`,
    periodLabel:`${first} — ${last}${last===2026?'*':''}`};
}
function setModeVisibility(){
  const latest=screeningMode==='latest',custom=!latest && document.getElementById('schedule-kind').value==='custom';
  document.getElementById('schedule-choice').hidden=latest;
  document.getElementById('schedule-controls').hidden=!custom;
  document.getElementById('custom-view').hidden=!custom;
  document.getElementById('backtest-view').hidden=latest||custom;
  document.getElementById('latest-view').hidden=!latest;
  document.getElementById('year-controls').hidden=latest||custom;
  document.getElementById('historical-help').hidden=latest||custom;
  document.getElementById('mode-latest').setAttribute('aria-pressed',latest);
  document.getElementById('mode-backtest').setAttribute('aria-pressed',!latest);
  if(!ScheduleView.isRunning())document.getElementById('run-screen').textContent=latest?'Screen latest':'Run backtest';
  const artifact=currentArtifact();
  applyPresentation(artifact?.presentation);syncCatalogControls();renderConditions();
  if(artifact)updateMetricLabels(artifact.settings);
}
function switchMode(mode){
  screeningMode=mode;setModeVisibility();settingsChanged();
}
function applyLatest(){
  let settings,result;
  try{settings=currentSettings();result=StockScreener.latestScreen(screeningData,readOptions());}
  catch(error){document.getElementById('screen-error').textContent=error.message+' The previous result remains displayed.';return;}
  completeResult(settings,result);
}
function renderLatest(r){
  document.getElementById('screen-error').textContent='';
  const o=r.options;
  updateMetricLabels(o);
  document.getElementById('latest-date').textContent=r.asof;
  document.getElementById('latest-count').textContent=String(r.stocks.length);
  document.getElementById('latest-median-cap').textContent=money(r.median_market_cap);
  document.getElementById('latest-median-yield').textContent=r.median_yield===null?'—':(r.median_yield*100).toFixed(2)+'%';
  document.getElementById('latest-body').innerHTML=r.stocks.map(h=>{
    const vals=[h.rank,h.symbol,h.name,h.exchange,h.sector,h.price.toFixed(2),money(h.market_cap),money(h.enterprise_value),(h.metric_yield*100).toFixed(2)+'%',h.metric_multiple.toFixed(2)+'×',h.fiscal,h.known,h.price_date];
    return '<tr>'+vals.map(v=>'<td>'+safe(v)+'</td>').join('')+'</tr>';
  }).join('')||'<tr><td colspan="13">No stocks match these latest-date filters.</td></tr>';
}
function latestPresentation(r){
  const o=r.options;
  const meta=screeningData.latest.metadata;
  const coverage=`Latest cached session: ${r.asof}. Only cached currently-listed names with a price on that exact date are eligible. ${screeningData.latest.cached.length} valued names out of ${meta.eligible_financials} active names with eligible financials; coverage is incomplete.`+(o.pool==='legacy'?' Original candidate set keeps the pre-price 250-name buffer and report-level size floors.':'');
  const text=r.stocks.length<r.requested?`Only ${r.stocks.length} picks are available for the requested ${r.requested} ranks after filtering on ${r.asof}.`:`Showing ${r.stocks.length} picks valued at the ${r.asof} cached close, re-ranked from ${r.matches} matching names.`;
  const severity=r.stocks.length<r.requested?'warning':'info';
  const rangeNote=`Latest picks · ${r.asof} · ranks ${o.rank_from}–${o.rank_to} after filters. No January holding returns or future performance are used in this list.`;
  return {coverage,notice:{text,severity},rangeNote,periodLabel:r.asof};
}
function applyRange(changed){
  updateResultsState();
  if(+fromYear.value>+toYear.value){if(changed==='from')toYear.value=fromYear.value;else fromYear.value=toYear.value;}
  if(+rankFrom.value>+rankTo.value && ['rank-from','rank-to'].includes(changed)){
    if(changed==='rank-from')rankTo.value=rankFrom.value;else rankFrom.value=rankTo.value;
  }
  if(screeningMode==='latest'){applyLatest();return;}
  if(document.getElementById('schedule-kind').value==='custom'){
    try{ScheduleView.run(readOptions());}catch(error){document.getElementById('screen-error').textContent=error.message;}
    return;
  }
  let settings,result;
  try{settings=currentSettings();result=StockScreener.screen(screeningData,readOptions());}
  catch(error){document.getElementById('screen-error').textContent=error.message+' The previous result remains displayed.';return;}
  completeResult(settings,result);
}
function renderJanuary(result){
  document.getElementById('screen-error').textContent='';
  data=result.years.map(y=>({year:y.year,portfolio:y.portfolio,spy:y.spy,names:y.names}));
  updateMetricLabels(result.options);
  const {first,last,rank_from,rank_to}=result.options;
  document.getElementById('strategy-legend').textContent=`${metricLabel(result.options.metric)} ranks ${rank_from}–${rank_to}`;
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
  stats[0].textContent=result.cagr===null?'—':(result.cagr*100).toFixed(2)+'%';
  stats[1].textContent=(result.spy_cagr*100).toFixed(2)+'%';
  stats[2].textContent=result.growth===null?'—':'$'+result.growth.toFixed(2);
  notes[0].textContent=result.first+' → '+result.end;
  notes[1].textContent='Same selected holding periods';
  notes[2].textContent='Strategy · SPY $'+result.spy_growth.toFixed(2);
  document.getElementById('detail').textContent='Hover over or focus a bar to see its return.';
}
function downloadLatest(){
  const currentLatest=ResultArtifacts.forView('latest')?.result;
  if(!currentLatest)return;
  const keys=['rank','symbol','name','exchange','sector','price','market_cap','enterprise_value','ebitda_yield','ev_ebitda','metric','metric_yield','metric_multiple','fiscal','known','price_date'];
  const rows=[keys,...currentLatest.stocks.map(h=>keys.map(k=>k==='metric'?currentLatest.options.metric:h[k]))];
  const csv=rows.map(row=>row.map(v=>'"'+String(v??'').replace(/"/g,'""')+'"').join(',')).join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='latest-picks-'+currentLatest.asof+'.csv';a.click();URL.revokeObjectURL(url);
}
function downloadSelection(kind){
  const result=ResultArtifacts.forView('january')?.result;
  if(!result)return;
  let rows;
  if(kind==='holdings'){
    const keys=['year','rank','symbol','name','exchange','sector','market_cap','enterprise_value','ebitda_yield','ev_ebitda','metric','metric_yield','metric_multiple','fiscal','entry','exit','return_value','weight','contribution_pp','status'];
    rows=[keys,...result.years.flatMap(y=>y.holdings.map(h=>keys.map(k=>k==='metric'?result.options.metric:k==='weight'?1/y.names:k==='contribution_pp'?h.return_value/y.names*100:h[k])))];
  }else rows=[['year','names','portfolio','spy','median_market_cap'],...result.years.map(y=>[y.year,y.names,y.portfolio??'',y.spy,y.median_market_cap??''])];
  const csv=rows.map(row=>row.map(v=>'"'+String(v??'').replace(/"/g,'""')+'"').join(',')).join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download=kind+'-'+result.options.first+'-'+result.options.last+'.csv';a.click();URL.revokeObjectURL(url);
}
function syncCatalogControls(){
  const selected=document.getElementById('ranking-metric').value;
  document.getElementById('ranking-metric').innerHTML=Object.entries({...screeningData.metrics,...displayCatalog().metrics}).map(([key,item])=>`<option value="${safe(key)}">${safe(item.label)}</option>`).join('');
  document.getElementById('ranking-metric').value=selected;
}
function restoreSavedBacktest(snapshot){
  const artifact=ResultArtifacts.decode(snapshot);
  if(artifact.kind==='latest')throw Error('Expected a saved backtest.');
  restoreBacktestSettings(artifact.settings,artifact.catalog,artifact.result.configuration?.seed);
  publishResult(artifact);
  if(artifact.kind!=='january')document.getElementById('schedule-message').textContent='Saved backtest restored. No calculation was run.';
}
function restoreBacktestSettings(settings,catalog=sourceCatalog(),seed=settings.seed){
  screeningMode='backtest';
  document.getElementById('schedule-kind').value=settings.mode==='january'?'january':'custom';
  setModeVisibility();

  const set=(id,value,label=value)=>{
    const control=document.getElementById(id),text=String(value??'');
    if(control.tagName==='SELECT' && ![...control.options].some(option=>option.value===text))control.add(new Option(label,text));
    control.value=text;
  };
  for(const [key,id] of Object.entries(fields)){
    const value=settings[key];
    set(id,value===null||value===undefined?'':typeof value==='number'?value/(key==='min_cap'||key==='max_cap'||key==='min_ev'?1e6:key==='min_yield'?.01:1):value,key==='metric'?(catalog.metrics[value]?.label||value):value);
  }
  set('rank-from',settings.rank_from??1);set('rank-to',settings.rank_to??50);
  filterConditions=(settings.filters||[]).map(condition=>({...condition}));
  if(settings.mode==='january'){
    set('from-year',settings.first);set('to-year',settings.last);
  }else{
    set('trade-start',settings.start);set('trade-end',settings.end);set('rebalance-months',settings.months);
    set('date-testing',settings.mode==='random'?'random':'single');
    if(settings.mode==='random'){
      set('random-trials',settings.trials);set('random-seed',seed??42);
      document.getElementById('repeat-random').checked=seed!==undefined;document.getElementById('random-seed').disabled=seed===undefined;
    }
  }
  renderConditions();
}
initializeFilters();
ScheduleView.init();
document.getElementById('schedule-kind').addEventListener('change',()=>{setModeVisibility();settingsChanged();});
setModeVisibility();
document.getElementById('mode-latest').addEventListener('click',()=>switchMode('latest'));
document.getElementById('mode-backtest').addEventListener('click',()=>switchMode('backtest'));
document.getElementById('download-latest').addEventListener('click',e=>{e.preventDefault();downloadLatest();});
fromYear.addEventListener('change',()=>settingsChanged('from'));
toYear.addEventListener('change',()=>settingsChanged('to'));
rankFrom.addEventListener('change',()=>settingsChanged('rank-from'));
rankTo.addEventListener('change',()=>settingsChanged('rank-to'));
document.getElementById('strategy-form').addEventListener('submit',e=>{e.preventDefault();applyRange();});
document.getElementById('reset-range').addEventListener('click',()=>{fromYear.value='1996';toYear.value='2025';settingsChanged();});
document.getElementById('reset-ranks').addEventListener('click',()=>{rankFrom.value='1';rankTo.value='50';settingsChanged();});
document.getElementById('top100').addEventListener('click',()=>{rankFrom.value='1';rankTo.value='100';settingsChanged();});
document.getElementById('reset-strategy').addEventListener('click',()=>{resetFilters();rankFrom.value='1';rankTo.value='50';settingsChanged();});
document.getElementById('holding-year').addEventListener('change',showHoldingYear);
document.querySelectorAll('.holding-years details').forEach(el=>el.addEventListener('toggle',()=>{if(el.open)renderStockTable(+el.id.replace('holdings-',''));}));
document.getElementById('download-returns').addEventListener('click',e=>{e.preventDefault();downloadSelection('returns');});
document.getElementById('download-holdings').addEventListener('click',e=>{e.preventDefault();downloadSelection('holdings');});
applyRange();

document.getElementById('add-filter').addEventListener('click',()=>{
  if(filterConditions.length<50)filterConditions.push({field:'return_1y',op:'gt',value:''});
  renderConditions();settingsChanged(undefined,false);
});
document.getElementById('filter-conditions').addEventListener('input',event=>{
  const target=event.target;
  if(target.dataset.key){filterConditions[Number(target.dataset.index)][target.dataset.key]=target.value;settingsChanged(undefined,false);}
});
document.getElementById('filter-conditions').addEventListener('change',event=>{
  const target=event.target;
  if(target.dataset.key){filterConditions[Number(target.dataset.index)][target.dataset.key]=target.value;settingsChanged();}
});
document.getElementById('filter-conditions').addEventListener('click',event=>{
  const index=event.target.dataset.remove;
  if(index!==undefined){filterConditions.splice(Number(index),1);renderConditions();settingsChanged();}
});

const autoRun=document.getElementById('auto-run');
autoRun.checked=true;
try{autoRun.checked=localStorage.getItem('backtest-auto-run')!=='false';}catch(_){}
autoRun.addEventListener('change',()=>{
  try{localStorage.setItem('backtest-auto-run',String(autoRun.checked));}catch(_){}
  settingsChanged();
});
document.getElementById('strategy-form').addEventListener('input',event=>{
  if(event.target.id!=='auto-run')settingsChanged(undefined,false);
});
document.getElementById('strategy-form').addEventListener('change',event=>{
  const id=event.target.id;
  if(['auto-run','from-year','to-year','rank-from','rank-to','schedule-kind'].includes(id)||event.target.dataset.key)return;
  settingsChanged();
});
document.getElementById('stop-backtest').addEventListener('click',()=>ScheduleView.cancel());

SavedBacktests.init({current:currentArtifact,isRunning:()=>ScheduleView.isRunning(),open:restoreSavedBacktest});
ScheduleView.resume();
