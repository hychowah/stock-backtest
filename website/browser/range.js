const screeningMarkets=JSON.parse(document.getElementById('screening-data').textContent);
let screeningData=screeningMarkets;
const marketLabels={us:'US',hk:'Hong Kong',jp:'Japan · Tokyo'};
const selectedMarket=()=>document.getElementById('stock-market')?.value||'us';
function selectMarket(value){
  const control=document.getElementById('stock-market');if(control)control.value=value;
  screeningData=value==='us'?screeningMarkets:screeningMarkets.markets[value];
  document.getElementById('stock-pool').innerHTML='<option value="cached">All stocks with cached prices</option>';
  for(const [id,key] of [['sector-filter','sector'],['exchange-filter','exchange']]){
    document.getElementById(id).innerHTML='<option value="">All</option>'+screeningData.choices[key].map(v=>`<option value="${safe(v)}">${safe(v)}</option>`).join('');
  }
  const asof=screeningData.latest.metadata.asof;
  const first=screeningData.bounds.first||'1996-01-01';
  for(const id of ['trade-start','trade-end']){document.getElementById(id).min=first;document.getElementById(id).max=asof||'';}
  if(asof){document.getElementById('trade-end').value=asof;const start=document.getElementById('trade-start');if(start.value<first)start.value=first;if(start.value>asof)start.value=asof;}
  document.getElementById('variable-preview-date').value=asof||'';
  if(!asof)document.getElementById('screen-error').textContent='Prepare '+marketLabels[value]+' data from Manage backtest data before running this market.';
}

const rankFrom=document.getElementById('rank-from'),rankTo=document.getElementById('rank-to');
const fields={selection_order:'selection-order',metric:'ranking-metric',pool:'stock-pool',min_cap:'min-cap',max_cap:'max-cap',min_ev:'min-ev',min_yield:'min-yield',max_multiple:'max-multiple',sector:'sector-filter',exchange:'exchange-filter'};
let screeningMode='latest';
// Built-in strategies keep their filters here. Variable strategies keep them in
// StrategyDraft. One row list shows whichever owner is active.
let filterConditions=[];
// A new row exists only in the form until its source is chosen.
let pendingFilter=false,filterSources=null,filterSourcesState='idle';
function viewKey(){return screeningMode==='latest'?'latest':'custom';}
const currentArtifact=()=>ResultArtifacts.forView(viewKey());
const sourceCatalog=()=>({metrics:screeningData.metrics,filters:screeningData.filter_catalog});
const displayCatalog=()=>currentArtifact()?.catalog||sourceCatalog();
const metricLabel=(id,artifact=currentArtifact())=>artifact?.catalog?.metrics[id]?.label||(typeof artifact?.catalog?.metrics[id]==='string'?artifact.catalog.metrics[id]:screeningData.metrics[id]?.label)||id;
function currentSettings({preserveLegacy=false}={}){
  const options=StrategyDraft.selectionSettings(readOptions(),preserveLegacy),view=viewKey();
  const engine=EngineControls.fields();
  if(view==='latest')return {mode:'latest',market:selectedMarket(),...options,...(StrategyDraft.isScalar()?engine:{})};
  const settings={mode:'custom',market:selectedMarket(),...options,...CalendarSettings.read(),...engine};
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
// Every result other than a latest screen, saved January results included,
// renders in the dated view.
function publishResult(artifact,name){
  const completed=ResultArtifacts.publish(artifact);
  if(completed.kind==='latest'){
    applyPresentation(completed.presentation);
    if(completed.version===4)EvidenceResults.show(completed);else renderLatest(completed.result);
  }else{
    ScheduleView.show(completed);
  }
  Workspaces.published(completed,name);
  document.getElementById('screen-error').textContent='';updateResultsState();
}
function completeResult(settings,result){
  const presentation=settings.mode==='latest'?latestPresentation(result):scheduledPresentation(settings);
  publishResult(ResultArtifacts.create(settings,result,sourceCatalog(),presentation));
}
function scheduledPresentation(settings){
  if(settings.strategy)return {coverage:(marketLabels[settings.market||'us']||settings.market)+' · USD returns and cash. Captured strategy over prepared stocks. FMP coverage and later revisions remain limitations. US Treasury reference yields; SPY total-return benchmark uses the previous completed US close for Asian dates.',notice:{text:'Results retain the submitted settings and selected stock values, including explanations for custom variables.',severity:'info'},rangeNote:'Downloads use completed immutable evidence. Period and stock tables show pages of the complete result.',periodLabel:settings.mode==='latest'?'Latest cached close':CalendarSettings.decode(settings).start+' → '+CalendarSettings.decode(settings).end};
  return {
    coverage:(marketLabels[settings.market||'us']||settings.market)+' · USD returns and cash. FMP coverage is incomplete; financial statements may include later revisions. US Treasury reference yields. SPY is the S&P 500 total-return proxy, using the previous completed US close for Asian dates.',
    notice:{text:'Results use the submitted stock filters and trade dates.',severity:'info'},
    rangeNote:'Custom schedule: trade dates and interval determine holding periods. '+StockScreener.selectionDescription(settings)+' Results and CSV exports below use this schedule.',
    periodLabel:CalendarSettings.decode(settings).start+' → '+CalendarSettings.decode(settings).end};
}
function updateResultsState(){
  const view=viewKey(),saved=currentArtifact(),state=document.getElementById('results-state');
  let matches=false;try{matches=ResultArtifacts.matches(saved,currentSettings());}catch(_){}
  const stale=!!saved&&!matches;
  state.className='screen-message'+(stale||!saved?' warning':'');
  // A saved January result opens without calculation; no current setting reproduces it.
  state.textContent=saved?.kind==='january'?'Saved January result shown without calculation. January backtests were removed. To compare, run a custom schedule every 12 months from 1 January.':stale?'Settings changed — displayed results do not match the current settings. Select '+(view==='latest'?'Screen latest':'Run backtest')+' to update them. Downloads still use the displayed results.':!saved?'No results for these settings yet. Select '+(view==='latest'?'Screen latest.':'Run backtest.'):'Results match the current settings.';
  if(ScheduleView.isRunning())state.textContent+=' A backtest is running with the settings submitted at its start.';
  for(const id of ['latest-view','custom-view'])document.getElementById(id).setAttribute('data-results-stale',String(stale));
  SavedBacktests.update();
}
function settingsChanged(changed,run=true){
  if(+rankFrom.value>+rankTo.value && ['rank-from','rank-to'].includes(changed)){
    if(changed==='rank-from')rankTo.value=rankFrom.value;else rankFrom.value=rankTo.value;
  }
  updateResultsState();
  StrategyDraft.touch();
  StrategyDraft.render();
  if(run && !StrategyDraft.isScalar() && document.getElementById('auto-run').checked && !ScheduleView.isRunning() && !BacktestQueue.isManaging())applyRange();
}
const money=v=>v===null?'—':'$'+(v/1e6).toLocaleString('en-US',{maximumFractionDigits:1})+'m';
const safe=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function initializeFilters(){
  rankFrom.value='1';rankTo.value='50';
  document.getElementById('trade-start').value='2015-01-01';
  selectMarket('us');
  document.getElementById('rebalance-months').value='12';
  if(document.getElementById('calendar-custom'))document.getElementById('calendar-custom').checked=false;
  document.getElementById('date-testing').value='single';
  document.getElementById('random-trials').value='24';
  document.getElementById('random-seed').value='42';
  resetFilters();
}
function builtinFilterLabel(field){
  const item=StrategyDraft.catalog().filters[field];
  return (item?.label||field)+(item?.available?'':screeningData.filter_catalog[field]?' — needs financial data':' — unavailable');
}
function conditionRow(key,row,scalar){
  const name=key==='new'?'New filter':'Filter '+(+key+1);
  const search=`<div class="filter-source"><label for="filter-search-${key}">Filter on</label><div class="filter-combo"><input id="filter-search-${key}" data-filter-search="${key}" type="text" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="filter-options-${key}" autocomplete="off" spellcheck="false" placeholder="Type to search: P/E, revenue, margin…" value="${safe(row.label)}" data-label="${safe(row.label)}"${row.title?` title="${safe(row.title)}"`:''}><span class="filter-combo-arrow" aria-hidden="true">▾</span><div id="filter-options-${key}" class="filter-options" role="listbox" aria-label="${name} choices" hidden></div></div></div>`;
  if(key==='new')return `<div class="condition-row condition-pending">${search}<div class="condition-actions"><button type="button" data-filter-cancel>Cancel</button></div></div>`;
  const value=scalar?`<input id="filter-value-${key}" data-index="${key}" data-key="value" aria-label="${name} value" inputmode="decimal" autocomplete="off" value="${safe(row.value)}" placeholder="Enter value">`
    :`<input id="filter-value-${key}" data-index="${key}" data-key="value" aria-label="${name} value" type="number" step="any" required value="${safe(row.value)}" placeholder="Enter value">`;
  const unit=!row.units?'':row.units.length>1?`<select data-index="${key}" data-key="unit" aria-label="${name} unit">${row.units.map(u=>`<option value="${safe(u)}" ${u===row.unit?'selected':''}>${safe(VariableWorkspace.displayName(u))}</option>`).join('')}</select>`:`<span class="condition-unit">${safe(VariableWorkspace.displayName(row.unit))}</span>`;
  return `<div class="condition-row">${search}<label>Comparison<select data-index="${key}" data-key="op" aria-label="${name} comparison"><option value="gt" ${row.op==='gt'?'selected':''}>More than (&gt;)</option><option value="lt" ${row.op==='lt'?'selected':''}>Less than (&lt;)</option></select></label><label>Value<span class="condition-value">${value}${unit}</span></label><div class="condition-actions">${row.formula?`<button type="button" data-edit="${key}" aria-label="Edit ${name.toLowerCase()} formula">Edit formula</button>`:''}<button type="button" data-remove="${key}" aria-label="Remove ${name.toLowerCase()}">Remove</button></div></div>`;
}
function renderConditions(){
  const scalar=StrategyDraft.isScalar();
  const rows=scalar?StrategyDraft.filterRows():filterConditions.map(c=>({label:builtinFilterLabel(c.field),op:c.op,value:c.value}));
  document.getElementById('filter-conditions').innerHTML=rows.map((row,i)=>conditionRow(String(i),row,scalar)).join('')+(pendingFilter?conditionRow('new',{label:''},scalar):'');
  document.getElementById('add-filter').disabled=rows.length>=50;
  FilterPicker.refresh();
  // Variable rows list their units from the catalog; a restored strategy loads it once.
  if(scalar&&filterSourcesState==='idle')loadFilterSources();
}
function filterMessage(text,failed=false){const note=document.getElementById('filter-message');note.textContent=text;note.className=failed?'error':'hint';}
// Every source a filter can use, in one searchable list. Built-in filters need
// no service; variables, measures and parameters come from the local service.
function filterChoices(){
  const groups=[{label:'Built-in filters',options:Object.entries(StrategyDraft.catalog().filters).map(([field,item])=>({value:{kind:'builtin',field,label:item.label},label:item.label,keywords:field,
    detail:item.available?'':screeningData.filter_catalog[field]?'Needs annual financial data. Download it in Manage backtest data.':'Unavailable in this data',disabled:!item.available}))}];
  if(filterSources){
    const library=[...filterSources.library].sort((a,b)=>(b.favourite?1:0)-(a.favourite?1:0));
    groups.push({label:'My variables',options:library.map(entry=>({value:{kind:'library',variable_id:entry.variable_id,revision:entry.revision,label:entry.name},label:(entry.favourite?'★ ':'')+entry.name,detail:'Saved variable'}))});
    groups.push({label:'Measures',options:filterSources.measures.map(item=>({value:{kind:'measure',id:item.id,label:item.name},label:item.name,detail:'Measure · '+VariableWorkspace.displayName(item.display),keywords:item.description}))});
    groups.push({label:'Financial parameters',options:filterSources.parameters.filter(item=>item.kind!=='adapter').map(item=>({value:{kind:'parameter',id:item.id,label:item.name},label:item.name,keywords:item.id,
      detail:[item.source?.endpoint,item.unit==='scalar'?'ratio':item.unit,item.note].filter(Boolean).join(' · ')}))});
  }
  const note=filterSourcesState==='loading'?'Loading saved variables, measures and parameters…':filterSourcesState==='failed'?'Saved variables, measures and parameters need the local service. Built-in filters work offline.':'';
  return {groups,note,actions:filterSourcesState==='failed'?[]:[{value:{kind:'create'},label:'＋ Create a new variable…',detail:'Build a formula in the variable editor, then add it as this filter.'}]};
}
function loadFilterSources(){
  if(filterSourcesState==='loading')return;
  if(!filterSources)filterSourcesState='loading';
  VariableWorkspace.sources().then(value=>{filterSources=value;filterSourcesState='ready';},()=>{filterSourcesState=filterSources?'ready':'failed';}).then(()=>{renderConditions();syncCatalogControls();});
}
function focusFilterValue(index){document.getElementById('filter-value-'+index).focus();}
function chooseFilter(key,choice){
  const index=key==='new'?null:+key,role=index===null?'condition':index;
  filterMessage('');
  if(choice.kind==='create'){void VariableWorkspace.open(role);return;}
  if(choice.kind==='builtin'&&!StrategyDraft.isScalar()){
    if(index===null){filterConditions.push({field:choice.field,op:'gt',value:''});pendingFilter=false;}
    else filterConditions[index].field=choice.field;
    const row=index??filterConditions.length-1;
    renderConditions();settingsChanged(undefined,String(filterConditions[row].value).trim()!=='');focusFilterValue(row);return;
  }
  // A variable source moves the whole strategy to the local service.
  const expected=StrategyDraft.read().revision;
  filterMessage('Adding '+choice.label+'…');
  const work=choice.kind==='builtin'?VariableWorkspace.sources().then(()=>StrategyDraft.patch({role,source:{kind:'builtin',id:'filter:'+choice.field}},expected)):VariableWorkspace.useSource(role,choice,expected);
  work.then(()=>{filterMessage('');focusFilterValue(index??StrategyDraft.filterRows().length-1);},failure=>{
    renderConditions();
    filterMessage(failure.code==='STALE_DRAFT'?'The strategy changed while '+choice.label+' was loading. Choose it again.':failure.message,true);
  });
}
function editFilter(index,key,value,run){
  if(StrategyDraft.isScalar()){StrategyDraft.condition(index,key,value);return;}
  filterConditions[index][key]=value;settingsChanged(undefined,run);
}
function resetFilters(){
  filterConditions=[];pendingFilter=false;renderConditions();
  document.getElementById('stock-pool').innerHTML='<option value="cached">Broad cached-price pool</option>';
  for(const [key,id] of Object.entries(fields)){
    const v=key==='pool'?'cached':StockScreener.defaults[key];
    document.getElementById(id).value=v===null?'':String(key==='min_cap'||key==='min_ev'?v/1e6:key==='min_yield'?v*100:v);
  }
}
function readOptions(){
  const o=readBounds();
  o.filters=filterConditions.map(c=>{
    if(String(c.value).trim()==='')throw Error('Enter a value for each added filter.');
    return {...c,value:Number(c.value)};
  });
  return o;
}
function readBounds(){
  const o={rank_from:+rankFrom.value,rank_to:+rankTo.value};
  for(const [key,id] of Object.entries(fields)){
    const text=document.getElementById(id).value.trim();
    if(['selection_order','metric','pool','sector','exchange'].includes(key))o[key]=text||null;
    else{
      if(!text && ['min_cap','min_ev','min_yield'].includes(key)&&!document.getElementById(id).disabled&&!(StrategyDraft.isScalar()&&['min_cap','min_ev'].includes(key)))throw Error('Fill in each minimum, or enter 0.');
      o[key]=text===''?null:Number(text)*(key==='min_cap'||key==='max_cap'||key==='min_ev'?1e6:key==='min_yield'?.01:1);
    }
  }
  return o;
}
function updateMetricLabels(o){
  const label=metricLabel(o.metric);
  document.querySelectorAll('[data-metric-multiple]').forEach(el=>el.textContent=label+' (×)');
  document.querySelectorAll('[data-metric-yield]').forEach(el=>el.textContent='Selected metric yield');
}
function setModeVisibility(){
  const latest=screeningMode==='latest';
  document.getElementById('schedule-controls').hidden=latest;
  document.getElementById('latest-view').hidden=!latest;
  document.getElementById('mode-latest').setAttribute('aria-pressed',latest);
  document.getElementById('mode-backtest').setAttribute('aria-pressed',!latest);
  if(!ScheduleView.isRunning())document.getElementById('run-screen').textContent=latest?'Screen latest':'Run backtest';
  const artifact=currentArtifact();
  applyPresentation(artifact?.presentation);syncCatalogControls();renderConditions();
  if(latest&&artifact?.version===4){EvidenceResults.show(artifact);Workspaces.published(artifact);}
  StrategyDraft.render();
}
// Only the offline latest screen recalculates on a mode switch; a dated
// backtest starts from Run backtest or a changed setting.
function switchMode(mode){
  screeningMode=mode;setModeVisibility();settingsChanged(undefined,mode==='latest');
}
function applyLatest(){
  let settings,result;
  try{settings=currentSettings();if(!screeningData.latest.metadata.asof)throw Error('Prepare '+marketLabels[selectedMarket()]+' data from Manage backtest data.');result=StockScreener.latestScreen(screeningData,readOptions());}
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
  const coverage=`${marketLabels[selectedMarket()]} · USD values. Latest cached session: ${r.asof}. Only cached currently-listed names with a price on that exact date are eligible. ${screeningData.latest.cached.length} valued names out of ${meta.eligible_financials} active names with eligible financials; coverage is incomplete.`+(o.pool==='legacy'?' Original candidate set keeps the pre-price 250-name buffer and report-level size floors.':'');
  const text=o.selection_order==='rank_first'?`${r.stocks.length} of the requested ${r.requested} ranks pass the filters on ${r.asof}. No replacements are added.`:r.stocks.length<r.requested?`Only ${r.stocks.length} picks are available for the requested ${r.requested} ranks after filtering on ${r.asof}.`:`Showing ${r.stocks.length} picks valued at the ${r.asof} cached close, re-ranked from ${r.matches} matching names.`;
  const severity=r.stocks.length<r.requested?'warning':'info';
  const rangeNote=`Latest picks · ${r.asof} · ${StockScreener.selectionDescription(o)} No holding returns or future performance are used in this list.`;
  return {coverage,notice:{text,severity},rangeNote,periodLabel:r.asof};
}
function applyRange(changed){
  if(document.getElementById('run-screen').disabled)return;
  updateResultsState();
  if(+rankFrom.value>+rankTo.value && ['rank-from','rank-to'].includes(changed)){
    if(changed==='rank-from')rankTo.value=rankFrom.value;else rankFrom.value=rankTo.value;
  }
  if(screeningMode==='latest'&&!StrategyDraft.isScalar()){applyLatest();return;}
  document.getElementById('run-screen').disabled=true;
  void StrategyDraft.prepareSubmission().then(settings=>ScheduleView.runPrepared(settings)).catch(error=>{document.getElementById('screen-error').textContent=error.message;}).finally(()=>{if(!ScheduleView.isRunning())document.getElementById('run-screen').disabled=false;});
}
function downloadLatest(){
  const artifact=ResultArtifacts.forView('latest');if(artifact?.version===4){ResultArtifacts.reader(artifact).download('screen');return;}
  const currentLatest=ResultArtifacts.forView('latest')?.result;
  if(!currentLatest)return;
  const keys=[...(Object.hasOwn(artifact.settings,'market')?['market','currency']:[]),'rank','symbol','name','exchange','sector','price','market_cap','enterprise_value','ebitda_yield','ev_ebitda','metric','metric_yield','metric_multiple','fiscal','known','price_date'];
  const rows=[keys,...currentLatest.stocks.map(h=>keys.map(k=>k==='market'?artifact.settings.market:k==='currency'?'USD':k==='metric'?currentLatest.options.metric:h[k]))];
  const csv=rows.map(row=>row.map(v=>'"'+String(v??'').replace(/"/g,'""')+'"').join(',')).join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='latest-picks-'+currentLatest.asof+'.csv';a.click();URL.revokeObjectURL(url);
}
// One native ranking list. The hidden metric value only adapts legacy requests.
function rankingChoices(){
  const catalog=StrategyDraft.catalog();
  return [
    {label:'EV/EBITDA metrics',items:Object.entries(catalog.metrics).flatMap(([key,item])=>['yield','multiple'].map(component=>({kind:'builtin',id:'metric:'+key+':'+component,label:item.label+' '+component})))},
    {label:'Built-in parameters',items:Object.entries(catalog.filters).map(([key,item])=>({kind:'builtin',id:'filter:'+key,label:item.label}))},
    {label:'Financial parameters',items:(filterSources?.parameters||[]).map(item=>({kind:'parameter',id:item.id,label:item.name}))},
    {label:'Measures',items:(filterSources?.measures||[]).map(item=>({kind:'measure',id:item.id,label:item.name}))},
    {label:'My variables',items:(filterSources?.library||[]).map(item=>({kind:'library',variable_id:item.variable_id,revision:item.revision,label:item.name}))}
  ];
}
const rankingKey=choice=>JSON.stringify(choice.kind==='library'||choice.kind==='formula'?{kind:choice.kind,variable_id:choice.variable_id,revision:choice.revision}:{kind:choice.kind,id:choice.id});
function syncCatalogControls(){
  const ranking=StrategyDraft.ranking(),source=ranking.source,groups=rankingChoices();
  let selected=rankingKey(source);
  if(source.kind==='formula'){
    const saved=groups[4].items.find(item=>item.variable_id===source.variable_id&&item.revision===source.revision);
    if(saved){selected=rankingKey(saved);saved.label=StrategyDraft.sourceLabel(source);}
    else groups[4].items.push({...source,label:StrategyDraft.sourceLabel(source)});
  }else{
    const group=groups[source.id.startsWith('metric:')?0:1],item=group.items.find(item=>item.id===source.id);
    if(item)item.label=StrategyDraft.sourceLabel(source);
    else group.items.push({...source,label:StrategyDraft.sourceLabel(source)});
  }
  document.getElementById('ranking-source').innerHTML=groups.map(group=>`<optgroup label="${safe(group.label)}">${group.items.map(item=>`<option value="${safe(rankingKey(item))}" ${item.kind==='builtin'&&!((item.id.startsWith('metric:')&&screeningData.metrics[item.id.split(':')[1]])||(item.id.startsWith('filter:')&&screeningData.filter_catalog[item.id.slice(7)]))?'disabled':''}>${safe(item.label)}</option>`).join('')}</optgroup>`).join('');
  document.getElementById('ranking-source').value=selected;
  document.getElementById('variable-direction').value=ranking.direction;
  document.getElementById('ranking-source-note').textContent=filterSourcesState==='loading'?'Loading saved variables and parameters…':filterSourcesState==='failed'?'Saved variables and parameters need the local service. Open Rank by to retry.':'';
}
async function chooseRanking(choice){
  const expected=StrategyDraft.read().revision;
  try{
    if(choice.kind==='formula')return; // Current detached selection, retained on restore.
    if(choice.direction){
      if(!StrategyDraft.isScalar()&&filterConditions.some(item=>!VariableWorkspace.builtin('filter:'+item.field)))await VariableWorkspace.sources();
      StrategyDraft.patch({direction:choice.direction},expected);
    }else if(choice.kind==='builtin'){
      if(!(choice.id.startsWith('metric:')&&choice.id.endsWith(':yield')&&!StrategyDraft.isScalar())&&!VariableWorkspace.builtin(choice.id))await VariableWorkspace.sources();
      StrategyDraft.patch({role:'ranking',source:{kind:'builtin',id:choice.id}},expected);
    }else await VariableWorkspace.useSource('ranking',choice,expected);
    document.getElementById('screen-error').textContent='';
  }catch(error){document.getElementById('screen-error').textContent=error.message;}
  finally{StrategyDraft.render();}
}

function restoreSavedBacktest(snapshot,name){
  const artifact=ResultArtifacts.decode(snapshot);
  if(artifact.kind==='latest')throw Error('Expected a saved backtest.');
  publishResult(artifact,name);
  document.getElementById('schedule-message').textContent='Saved backtest opened. Draft settings are unchanged; no calculation was run.';
}
function copySavedBacktestSettings(snapshot){
  const artifact=ResultArtifacts.decode(snapshot);
  if(artifact.kind==='latest')throw Error('Expected a saved backtest.');
  restoreBacktestSettings(artifact.settings,artifact.catalog,artifact.result.configuration?.seed);
  autoRun.checked=false;
  try{localStorage.setItem('backtest-auto-run','false');}catch(_){}
  updateResultsState();
  Workspaces.show('builder');
  document.getElementById('strategy-form').scrollIntoView?.({behavior:'smooth',block:'start'});
  document.getElementById('run-screen').focus?.({preventScroll:true});
}
// The form owns its draft. Restoration sources cannot replace a queued edit;
// only its session may load settings until a confirmed save/cancel ends it.
const StrategyDraft=(()=>{
  let active=null,revision=0,scalar=null,restoredCatalog=null,capturedBuiltins=null;
  const copy=value=>JSON.parse(JSON.stringify(value));
  // Editable labels belong to the draft. Result labels stay with their artifact.
  // Availability comes from current support, even when a saved label is retained.
  function catalog(){
    const source=sourceCatalog();
    return {metrics:{...source.metrics,...restoredCatalog?.metrics},filters:Object.fromEntries(Object.entries({...source.filters,...restoredCatalog?.filters}).map(([id,item])=>[id,{...item,available:!!source.filters[id]?.available}]))};
  }
  const exactKey=value=>JSON.stringify([value.variable_id,value.revision]);
  function sameContent(left,right){
    const ordered=value=>Array.isArray(value)?value.map(ordered):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,ordered(value[key])])):value;
    return JSON.stringify(ordered(left))===JSON.stringify(ordered(right));
  }
  function compactDetached(captures,selection){
    const sources=[selection.ranking.source,...selection.conditions.map(item=>item.source)];
    const needed=new Set(sources.filter(source=>source.kind==='formula').map(exactKey)),kept=[];
    // Every capture already contains its complete dependency closure. Choose
    // existing captures by exact identity; the server alone handles graph policy.
    for(const capture of [...captures].reverse()){
      const identities=capture.program.definitions.map(exactKey);
      if(!identities.some(identity=>needed.has(identity)))continue;
      kept.push(capture);identities.forEach(identity=>needed.delete(identity));
    }
    return kept.reverse();
  }
  function touch(){revision++;}
  function selectionSettings(legacy,preserveLegacy=false){
    if(!scalar){
      if(preserveLegacy)return legacy;
      return viewKey()!=='latest'&&capturedBuiltins&&sameContent(legacy,capturedBuiltins.options)?{strategy:copy(capturedBuiltins.strategy)}:legacy;
    }
    const intent=readIntent(legacy),capture=scalar.original?copy(scalar.original):{format:'strategy-draft',version:1};
    Object.assign(capture,{selection:intent.selection,pool:intent.pool,bounds:intent.bounds});
    return {strategy:capture};
  }
  function readIntent(legacy=readOptions()){
    const intent=copy(scalar.intent);
    intent.selection.rank_from=+rankFrom.value;intent.selection.rank_to=+rankTo.value;
    intent.selection.selection_order=document.getElementById('selection-order').value;
    intent.pool=document.getElementById('stock-pool').value;
    intent.bounds=Object.fromEntries(['min_cap','max_cap','min_ev','sector','exchange',...['min_yield','max_multiple'].filter(key=>pairRanking(intent.selection.ranking)&&(Object.hasOwn(intent.bounds,key)||(key==='min_yield'?legacy[key]!==0:legacy[key]!==null)))].map(key=>[key,legacy[key]]));
    return intent;
  }
  const builtinDescriptor=id=>scalar?.original?.builtins?.find(item=>item.id===id)||VariableWorkspace.builtin(id);
  function sourceLabel(source){
    if(source.kind==='builtin'){
      const [,key,component]=source.id.split(':'),item=catalog().metrics[key];
      const label=source.id.startsWith('filter:')?catalog().filters[key]?.label:item&&(typeof item==='string'?item:item.label)+' '+component;
      return (scalar&&builtinDescriptor(source.id)?.label)||label||source.id;
    }
    for(const capture of scalar?.detached||[]){const found=capture.presentation.find(item=>item.variable_id===source.variable_id&&item.revision===source.revision);if(found)return found.name;}
    return source.variable_id;
  }
  // Canonical unit and default display of a selected source.
  function sourceOutput(source){
    if(source.kind==='builtin')return builtinDescriptor(source.id);
    for(const capture of [...(scalar?.detached||[])].reverse()){const found=capture.program.definitions.find(item=>exactKey(item)===exactKey(source));if(found)return found;}
    return null;
  }
  function filterRows(){
    return scalar.intent.selection.conditions.map(item=>{
      const threshold=item.submitted_threshold||item.threshold,formula=item.source.kind==='formula',output=sourceOutput(item.source);
      return {label:sourceLabel(item.source),title:formula?item.source.variable_id+' @ '+item.source.revision:'',op:item.op,value:threshold.value,unit:threshold.unit,formula,
        units:formula?[...new Set([...VariableWorkspace.displays(output?.unit),threshold.unit])]:null};
    });
  }
  // Built-in conditions return to the offline form in their display units.
  // An edited threshold drops the values derived from its earlier submission.
  function setThreshold(item,threshold){item.threshold=threshold;delete item.submitted_threshold;delete item.comparison_value;delete item.storage_comparison_value;}
  function legacyFilters(){
    return scalar.intent.selection.conditions.flatMap(item=>{
      const threshold=item.submitted_threshold||item.threshold,field=item.source.kind==='builtin'&&item.source.id.startsWith('filter:')?item.source.id.slice(7):null;
      return field&&threshold.unit===builtinDescriptor(item.source.id)?.display?[{field,op:item.op,value:threshold.value}]:[];
    });
  }
  const ranking=()=>scalar?copy(scalar.intent.selection.ranking):{source:{kind:'builtin',id:'metric:'+document.getElementById('ranking-metric').value+':yield'},direction:'highest'};
  const pairRanking=value=>value.direction==='highest'&&value.source.kind==='builtin'&&/^metric:[^:]+:yield$/.test(value.source.id);
  function renderScalar(){
    EngineControls.sync();
    const selected=ranking(),pair=pairRanking(selected);
    document.getElementById('variable-strategy-summary').textContent=scalar?'Select Screen latest or Run backtest to calculate. Editing or checking a variable never runs a backtest.':'Built-in strategies work offline. Reusable variables use the local service.';
    document.getElementById('strategy-ranking-help').textContent='Rank 1 has the '+selected.direction+' available selected value. Missing ranking values are excluded. Conditions apply at the chosen selection stage; survivors have equal weight.';
    document.getElementById('strategy-heading').textContent=(selected.direction==='highest'?'Highest ':'Lowest ')+sourceLabel(selected.source);
    for(const id of ['legacy-yield-control','legacy-multiple-control'])document.getElementById(id).hidden=!pair;
    document.getElementById('legacy-metric-help').hidden=!pair;
    for(const id of ['min-yield','max-multiple'])document.getElementById(id).disabled=!pair;
    document.getElementById('min-yield').required=pair;
    for(const id of ['min-cap','min-ev'])document.getElementById(id).required=!scalar;
    document.getElementById('auto-run').disabled=!!scalar;
    document.getElementById('auto-run-note').textContent=scalar?'Auto-run is paused for captured strategies. Select Screen latest or Run backtest to calculate.':'Turn off to change several settings, then select Run backtest. You can edit settings during a run.';
    document.getElementById('legacy-pool-note').hidden=document.getElementById('stock-pool').value!=='legacy'||(selected.source.kind==='builtin'&&(selected.source.id.startsWith('metric:')||selected.source.id==='filter:ebitda_yield'));
    syncCatalogControls();
  }
  function transition(){
    const legacy=readBounds();
    const unit=field=>{const descriptor=VariableWorkspace.builtin('filter:'+field);if(!descriptor)throw Error('Open Rank by to load the supported filter units. Your draft was kept.');return descriptor.display;};
    // Rows without a value move too; submission asks for the value.
    const conditions=filterConditions.map(item=>({source:{kind:'builtin',id:'filter:'+item.field},op:item.op,threshold:{value:String(item.value).trim(),unit:unit(item.field)}}));
    scalar={intent:{format:'strategy-intent',version:1,pool:legacy.pool,bounds:{min_yield:legacy.min_yield,max_multiple:legacy.max_multiple},selection:{ranking:{source:{kind:'builtin',id:'metric:'+legacy.metric+':yield'},direction:'highest'},rank_from:legacy.rank_from,rank_to:legacy.rank_to,selection_order:legacy.selection_order,conditions}},detached:[],projections:{},original:null};
    filterConditions=[];
  }
  function patch(change,expected){
    if(expected!==revision)throw Object.assign(Error('The strategy draft changed. Choose the source again.'),{code:'STALE_DRAFT'});
    if(change.legacy){
      const kept=scalar?legacyFilters():filterConditions,removed=scalar?scalar.intent.selection.conditions.length-kept.length:0;
      filterConditions=kept;scalar=null;capturedBuiltins=null;touch();renderScalar();renderConditions();updateResultsState();
      if(removed)filterMessage(removed+(removed===1?' variable filter was':' variable filters were')+' removed. Built-in filters were kept.');
      return;
    }
    const next={...ranking(),...(change.direction?{direction:change.direction}:{}),...(change.role==='ranking'?{source:change.source}:{})};
    const bounds=readBounds();
    if(!pairRanking(next)&&(bounds.min_yield!==0||bounds.max_multiple!==null))throw Error('This ranking cannot use inclusive minimum yield or maximum multiple. Set minimum yield to 0 and clear maximum multiple explicitly before changing the ranking. Your draft was kept.');
    if(scalar&&pairRanking(next)&&(change.role==='ranking'||change.direction)&&legacyFilters().length===scalar.intent.selection.conditions.length){
      patch({legacy:true},expected);
      document.getElementById('ranking-metric').value=next.source.id.split(':')[1];settingsChanged();return;
    }
    // Supported highest-yield metrics keep the existing offline latest path.
    if(!scalar&&pairRanking(next)){
      if(change.role==='ranking'){
        document.getElementById('ranking-metric').value=next.source.id.split(':')[1];settingsChanged();return;
      }
      if(change.direction){touch();renderScalar();return;}
    }
    if(!scalar){transition();capturedBuiltins=null;}
    if(!pairRanking(next)){delete scalar.intent.bounds.min_yield;delete scalar.intent.bounds.max_multiple;}
    if(change.direction)scalar.intent.selection.ranking.direction=change.direction;
    if(change.role!==undefined){
      if(change.capture)scalar.detached.push(copy(change.capture));
      const conditions=scalar.intent.selection.conditions,formula=change.source.kind==='formula',output=sourceOutput(change.source);
      if(change.role==='ranking')scalar.intent.selection.ranking.source=copy(change.source);
      else if(typeof change.role==='number'){
        // A new source keeps the typed value. Built-in units are fixed; a
        // variable keeps the chosen unit only when it still fits.
        const item=conditions[change.role],threshold=item.submitted_threshold||item.threshold;
        const unit=formula&&VariableWorkspace.displays(output?.unit).includes(threshold.unit)?threshold.unit:output?.display||'number';
        item.source=copy(change.source);setThreshold(item,{value:threshold.value,unit});
      }
      else{conditions.push({source:copy(change.source),op:'gt',threshold:{value:'',unit:output?.display||'number'}});pendingFilter=false;}
      if(change.authored)scalar.projections[exactKey(change.source)]={submitted:copy(change.authored),labels:copy(change.capture.presentation)};
      scalar.detached=compactDetached(scalar.detached,scalar.intent.selection);
      const selected=new Set([scalar.intent.selection.ranking.source,...scalar.intent.selection.conditions.map(item=>item.source)].filter(source=>source.kind==='formula').map(exactKey));
      scalar.projections=Object.fromEntries(Object.entries(scalar.projections).filter(([key])=>selected.has(key)));
    }
    touch();renderScalar();renderConditions();updateResultsState();
  }
  async function captureBuiltins(options){
    // Convert a detached request, never the form or an accepted record. Capture
    // finishes before the caller allocates a run or queue submission identity.
    options=copy(options);
    if(options.strategy)return options;
    const legacy={rank_from:1,rank_to:50,filters:[],...StockScreener.defaults,...options};
    if(['min_cap','min_ev','min_yield'].some(key=>legacy[key]===null))throw Error('This recorded test has an empty minimum and cannot be replayed exactly; enter a value.');
    const filters=legacy.filters||[];
    const descriptors=filters.length?(await VariableWorkspace.request('/catalog')).builtins:[];
    const conditions=filters.map(item=>{
      const descriptor=descriptors.find(source=>source.id==='filter:'+item.field);
      if(!descriptor)throw Error('The selected built-in filter is unavailable. Your settings were kept.');
      return {source:{kind:'builtin',id:descriptor.id},op:item.op,threshold:{value:String(item.value),unit:descriptor.display}};
    });
    const bounds=Object.fromEntries(['min_cap','max_cap','min_ev','min_yield','max_multiple','sector','exchange'].map(key=>[key,legacy[key]]));
    const intent={format:'strategy-intent',version:1,pool:legacy.pool,bounds,selection:{ranking:{source:{kind:'builtin',id:'metric:'+legacy.metric+':yield'},direction:'highest'},rank_from:legacy.rank_from,rank_to:legacy.rank_to,selection_order:legacy.selection_order,conditions}};
    const prepared=await VariableWorkspace.request('/capture',{intent});
    const selectionKeys=new Set([...Object.keys(StockScreener.defaults),'rank_from','rank_to','filters']);
    return {...Object.fromEntries(Object.entries(options).filter(([key])=>!selectionKeys.has(key))),strategy:prepared.strategy};
  }
  async function prepareSubmission(){
    const settings=copy(currentSettings());
    if(!scalar){
      if(settings.mode==='latest')return settings;
      const submittedRevision=revision,options=copy(readOptions()),prepared=await captureBuiltins(settings);
      if(submittedRevision===revision&&!scalar)capturedBuiltins={options,strategy:copy(prepared.strategy)};
      return prepared;
    }
    if(scalar.intent.selection.conditions.some(item=>String((item.submitted_threshold||item.threshold).value).trim()===''))throw Error('Enter a value for each added filter.');
    const submittedRevision=revision;
    const intent=readIntent(),detached=copy(compactDetached(scalar.detached,intent.selection)),projections=copy(scalar.projections),original=scalar.original?copy(scalar.original):null,originalIntent=original?{format:'strategy-intent',version:1,selection:original.selection,pool:original.pool,bounds:original.bounds}:null;
    const unchanged=sameContent(intent,originalIntent)&&sameContent(detached,scalar.original?.variables?[scalar.original.variables]:[]);
    let snapshot;
    if(unchanged)snapshot={intent,original};
    else{
      const sources=[intent.selection.ranking.source,...intent.selection.conditions.map(item=>item.source)].filter(source=>source.kind==='formula');
      for(const source of sources){
        const key=exactKey(source);if(projections[key])continue;
        const capture=[...detached].reverse().find(item=>item.program.definitions.some(entry=>exactKey(entry)===key));
        if(!capture)throw Error('The exact selected variable content is unavailable. Open the picker again. Your draft was kept.');
        const projected=await VariableWorkspace.request('/detached',{root:{variable_id:source.variable_id,revision:source.revision},capture});
        projections[key]={submitted:projected.authored,labels:capture.presentation};
      }
      snapshot={intent,...VariableWorkspace.content(...sources.map(source=>projections[exactKey(source)]),{labels:detached.flatMap(capture=>capture.presentation)})};
    }
    const prepared=await VariableWorkspace.request('/capture',snapshot);
    if(submittedRevision===revision){
      scalar.original=copy(prepared.strategy);
      scalar.intent={format:'strategy-intent',version:1,selection:copy(prepared.strategy.selection),pool:prepared.strategy.pool,bounds:copy(prepared.strategy.bounds)};
      scalar.detached=prepared.strategy.variables?[copy(prepared.strategy.variables)]:[];
      scalar.projections=projections;
    }
    return {...settings,strategy:prepared.strategy};
  }
  const refusal=()=>Error('Save or cancel the queued edit before replacing the strategy settings.');
  function apply(settings,catalog=sourceCatalog(),seed=settings.seed){
    touch();
    restoredCatalog=copy(catalog);
    capturedBuiltins=null;
    const capture=settings.strategy;
    // New built-in captures reopen in the ordinary form. Keep their exact
    // capture for unchanged submissions and displayed-result matching.
    if(capture?.variables===null&&Object.hasOwn(capture.bounds,'min_yield')&&Object.hasOwn(capture.bounds,'max_multiple')&&capture.selection.conditions.every(item=>item.source.kind==='builtin'&&item.source.id.startsWith('filter:'))){
      const {strategy,...rest}=settings;
      settings={...rest,...capture.bounds,pool:capture.pool,metric:capture.builtins.find(item=>item.id===capture.selection.ranking.source.id).storage.metric,
        ...Object.fromEntries(['rank_from','rank_to','selection_order'].map(key=>[key,capture.selection[key]])),
        filters:capture.selection.conditions.map(item=>({field:item.source.id.slice(7),op:item.op,value:item.storage_comparison_value}))};
      capturedBuiltins={strategy:copy(capture)};
    }
    scalar=settings.strategy?{intent:{format:'strategy-intent',version:1,selection:copy(settings.strategy.selection),pool:settings.strategy.pool,bounds:copy(settings.strategy.bounds)},detached:settings.strategy.variables?[copy(settings.strategy.variables)]:[],projections:{},original:copy(settings.strategy)}:null;
    selectMarket(settings.market||'us');
    screeningMode=settings.mode==='latest'?'latest':'backtest';
    setModeVisibility();

    const set=(id,value,label=value)=>{
      const control=document.getElementById(id),text=String(value??'');
      if(control.tagName==='SELECT' && ![...control.options].some(option=>option.value===text))control.add(new Option(label,text));
      control.value=text;
    };
    for(const [key,id] of Object.entries(fields)){
      const scalarValue=scalar?(key==='selection_order'?settings.strategy.selection.selection_order:key==='pool'?settings.strategy.pool:Object.hasOwn(settings.strategy.bounds,key)?settings.strategy.bounds[key]:StockScreener.defaults[key]):settings[key];
      const value=key==='selection_order'?(scalarValue??StockScreener.defaults.selection_order):key==='pool'?(scalarValue??'legacy'):scalarValue;
      set(id,value===null||value===undefined?'':typeof value==='number'?value/(key==='min_cap'||key==='max_cap'||key==='min_ev'?1e6:key==='min_yield'?.01:1):value,key==='metric'?(catalog.metrics[value]?.label||value):key==='pool'&&value==='legacy'?'Recorded US original candidate set':value);
    }
    set('rank-from',settings.strategy?.selection.rank_from??settings.rank_from??1);set('rank-to',settings.strategy?.selection.rank_to??settings.rank_to??50);
    if(document.getElementById('backtest-engine'))set('backtest-engine',settings.engine??'original',
      EngineControls.label?.(settings.engine??'original')||settings.engine||'Original');
    EngineControls.sync();
    filterConditions=(settings.filters||[]).map(condition=>({...condition}));pendingFilter=false;
    // January settings restore the strategy only; their book years never
    // become a dated calendar.
    if(!['latest','january'].includes(settings.mode)){
      CalendarSettings.restore(settings);
      set('date-testing',settings.mode==='random'?'random':'single');
      if(settings.mode==='random'){
        set('random-trials',settings.trials);set('random-seed',seed??42);
        document.getElementById('repeat-random').checked=seed!==undefined;document.getElementById('random-seed').disabled=seed===undefined;
      }
    }
    syncCatalogControls();renderConditions();renderScalar();
    if(capturedBuiltins)capturedBuiltins.options=copy(readOptions());
  }
  function restore(...args){
    if(active)throw refusal();
    return apply(...args);
  }
  function beginQueuedEdit(id){
    if(active)throw refusal();
    const session={id,
      restore(...args){if(active!==session)throw Error('This strategy edit is no longer active.');return apply(...args);},
      end(){if(active===session){active=null;touch();}}
    };
    active=session;touch();return session;
  }
  return {restore,beginQueuedEdit,catalog,read:()=>({revision,settings:scalar?copy(currentSettings()):null,detached:scalar?copy(scalar.detached):[]}),patch,prepareSubmission,captureBuiltins,selectionSettings,touch,isScalar:()=>!!scalar,ranking,sourceLabel,render:renderScalar,filterRows,condition:(index,key,value)=>{const item=scalar.intent.selection.conditions[index];if(key==='op')item.op=value;else setThreshold(item,{...item.submitted_threshold||item.threshold,[key]:value});touch();updateResultsState();},remove:index=>{scalar.intent.selection.conditions.splice(index,1);touch();renderConditions();updateResultsState();}};
})();
const restoreBacktestSettings=StrategyDraft.restore;

initializeFilters();
ScheduleView.init(()=>({mode:viewKey()==='custom'&&document.getElementById('date-testing').value==='random'?'random':viewKey(),scalar:StrategyDraft.isScalar()}),Workspaces.runStatus);
VariableWorkspace.init({draft:StrategyDraft,asof:screeningData.latest.metadata.asof,pool:()=>document.getElementById('stock-pool').value,market:selectedMarket});
StrategyDraft.render();
setModeVisibility();
document.getElementById('ranking-source').addEventListener('focus',loadFilterSources);
document.getElementById('mode-latest').addEventListener('click',()=>switchMode('latest'));
document.getElementById('mode-backtest').addEventListener('click',()=>switchMode('backtest'));
document.getElementById('download-latest').addEventListener('click',e=>{e.preventDefault();downloadLatest();});
rankFrom.addEventListener('change',()=>settingsChanged('rank-from'));
rankTo.addEventListener('change',()=>settingsChanged('rank-to'));
document.getElementById('strategy-form').addEventListener('submit',e=>{e.preventDefault();applyRange();});
document.getElementById('reset-ranks').addEventListener('click',()=>{rankFrom.value='1';rankTo.value='50';settingsChanged();});
document.getElementById('top100').addEventListener('click',()=>{rankFrom.value='1';rankTo.value='100';settingsChanged();});
document.getElementById('reset-strategy').addEventListener('click',()=>{if(StrategyDraft.isScalar())StrategyDraft.patch({legacy:true},StrategyDraft.read().revision);resetFilters();rankFrom.value='1';rankTo.value='50';settingsChanged();});
applyRange();

// A new row asks for its source first; it joins the strategy once chosen.
document.getElementById('add-filter').addEventListener('click',()=>{
  if(!pendingFilter){pendingFilter=true;renderConditions();}
  document.getElementById('filter-search-new').focus();
});
FilterPicker.bind(document.getElementById('filter-conditions'),{choices:filterChoices,choose:chooseFilter,opened:loadFilterSources});
document.getElementById('filter-conditions').addEventListener('input',event=>{
  const target=event.target;
  if(target.dataset.key)editFilter(Number(target.dataset.index),target.dataset.key,target.value,false);
});
document.getElementById('filter-conditions').addEventListener('change',event=>{
  const target=event.target;
  if(target.dataset.key)editFilter(Number(target.dataset.index),target.dataset.key,target.value,true);
});
document.getElementById('filter-conditions').addEventListener('click',event=>{
  const target=event.target.closest('button');if(!target)return;
  const {remove,edit}=target.dataset;
  if(target.dataset.filterCancel!==undefined){pendingFilter=false;renderConditions();return;}
  if(edit!==undefined){void VariableWorkspace.open(Number(edit));return;}
  if(remove===undefined)return;
  filterMessage('');
  if(StrategyDraft.isScalar()){StrategyDraft.remove(Number(remove));return;}
  filterConditions.splice(Number(remove),1);renderConditions();settingsChanged();
});

const autoRun=document.getElementById('auto-run');
autoRun.checked=true;
try{autoRun.checked=localStorage.getItem('backtest-auto-run')!=='false';}catch(_){}
autoRun.addEventListener('change',()=>{
  try{localStorage.setItem('backtest-auto-run',String(autoRun.checked));}catch(_){}
  settingsChanged();
});
document.getElementById('strategy-form').addEventListener('input',event=>{
  if(!['auto-run','ranking-source','variable-direction'].includes(event.target.id))settingsChanged(undefined,false);
});
document.getElementById('strategy-form').addEventListener('change',event=>{
  const id=event.target.id;
  if(id==='ranking-source'){void chooseRanking(JSON.parse(event.target.value));return;}
  if(id==='variable-direction'){void chooseRanking({direction:event.target.value});return;}
  if(['auto-run','rank-from','rank-to'].includes(id)||event.target.dataset.key)return;
  if(id==='stock-market'){selectMarket(selectedMarket());document.getElementById('stock-pool').value='cached';}
  settingsChanged();
});
document.getElementById('stop-backtest').addEventListener('click',()=>ScheduleView.cancel());

SavedBacktests.init({current:()=>ResultArtifacts.forView('custom'),isRunning:()=>ScheduleView.isRunning(),open:restoreSavedBacktest,copy:copySavedBacktestSettings});
BacktestQueue.init({changed:Workspaces.queueStatus,libraryChanged:SavedBacktests.changed,beginEdit:StrategyDraft.beginQueuedEdit,settings:currentSettings,prepareSubmission:StrategyDraft.prepareSubmission,catalog:sourceCatalog,presentation:scheduledPresentation,restore:restoreBacktestSettings,open:restoreSavedBacktest,
  prepare:()=>{Workspaces.show('builder');autoRun.checked=false;try{localStorage.setItem('backtest-auto-run','false');}catch(_){}},
  configure:()=>{
    screeningMode='backtest';
    setModeVisibility();settingsChanged(undefined,false);
    document.getElementById('schedule-controls').scrollIntoView?.({behavior:'smooth',block:'center'});
  },
  metricLabel:id=>sourceCatalog().metrics[id]?.label||id,filterLabel:id=>sourceCatalog().filters[id]?.label||id});
Workspaces.init();
ScheduleView.resume();
