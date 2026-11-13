const screeningMarkets=JSON.parse(document.getElementById('screening-data').textContent);
let screeningData=screeningMarkets;
const marketLabels={us:'US',hk:'Hong Kong',jp:'Japan · Tokyo'};
const selectedMarket=()=>document.getElementById('stock-market')?.value||'us';
function selectMarket(value){
  const control=document.getElementById('stock-market');if(control)control.value=value;
  screeningData=value==='us'?screeningMarkets:screeningMarkets.markets[value];
  document.getElementById('stock-pool').innerHTML='<option value="cached">All stocks with cached prices</option>';
  const asof=screeningData.latest.metadata.asof;
  const first=screeningData.bounds.first||'1996-01-01';
  for(const id of ['trade-start','trade-end']){document.getElementById(id).min=first;document.getElementById(id).max=asof||'';}
  if(asof){document.getElementById('trade-end').value=asof;const start=document.getElementById('trade-start');if(start.value<first)start.value=first;if(start.value>asof)start.value=asof;}
  if(!asof)document.getElementById('screen-error').textContent='Prepare '+marketLabels[value]+' data from Manage backtest data before running this market.';
}

let screeningMode='latest';
// A new step exists only in the form until its source is chosen.
let pendingStep=null,stepSources=null,stepSourcesState='idle';
function viewKey(){return screeningMode==='latest'?'latest':'custom';}
const currentArtifact=()=>ResultArtifacts.forView(viewKey());
const sourceCatalog=()=>({metrics:screeningData.metrics,filters:screeningData.filter_catalog});
// A metric label names the multiple (EV / EBITDA). The yield is the inverse
// ratio, so its name swaps the two sides (EBITDA / EV).
const inverseRatio=label=>label.split(' / ').reverse().join(' / ');
const pairLabel=(item,component)=>{const label=typeof item==='string'?item:item.label;return (component==='yield'?inverseRatio(label):label)+' '+component;};
const metricLabel=(id,artifact=currentArtifact())=>artifact?.catalog?.metrics[id]?.label||(typeof artifact?.catalog?.metrics[id]==='string'?artifact.catalog.metrics[id]:screeningData.metrics[id]?.label)||id;
function currentSettings(){
  const selection=StrategyDraft.selection(),engine=EngineControls.fields();
  if(viewKey()==='latest')return {mode:'latest',market:selectedMarket(),...selection,...(selection.strategy?engine:{})};
  const settings={mode:'custom',market:selectedMarket(),...selection,...CalendarSettings.read(),...engine};
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
function scheduledPresentation(settings){
  if(settings.strategy)return {coverage:(marketLabels[settings.market||'us']||settings.market)+' · USD returns and cash. Captured strategy over prepared stocks. FMP coverage and later revisions remain limitations. US Treasury reference yields; SPY total-return benchmark uses the previous completed US close for Asian dates.',notice:{text:'Results retain the submitted settings and selected stock values, including explanations for custom variables.',severity:'info'},rangeNote:'Downloads use completed immutable evidence. Period and stock tables show pages of the complete result.',periodLabel:settings.mode==='latest'?'Latest cached close':CalendarSettings.decode(settings).start+' → '+CalendarSettings.decode(settings).end};
  return {
    coverage:(marketLabels[settings.market||'us']||settings.market)+' · USD returns and cash. FMP coverage is incomplete; financial statements may include later revisions. US Treasury reference yields. SPY is the S&P 500 total-return proxy, using the previous completed US close for Asian dates.',
    notice:{text:'Results use the submitted stock filters and trade dates.',severity:'info'},
    rangeNote:'Custom schedule: trade dates and interval determine holding periods. '+StockScreener.selectionDescription(settings)+' Results and CSV exports below use this schedule.',
    periodLabel:CalendarSettings.decode(settings).start+' → '+CalendarSettings.decode(settings).end};
}
// The line under the builder speaks for the latest picks only. A dated result is a
// stored record: no draft setting makes it stale. Picks that match the settings
// need no line.
function updateResultsState(){
  if(screeningMode!=='latest')return;
  const saved=ResultArtifacts.forView('latest'),state=document.getElementById('results-state');
  let matches=false;try{matches=ResultArtifacts.matches(saved,currentSettings());}catch(_){}
  const stale=!!saved&&!matches,missing=!saved;
  state.className='screen-message'+(stale||missing?' warning':'');
  state.textContent=stale?'Settings changed — displayed results do not match the current settings. Select Screen latest to update them. Downloads still use the displayed results.':missing?'No results for these settings yet. Select Screen latest.':'';
  document.getElementById('latest-view').setAttribute('data-results-stale',String(stale));
}
// Auto-run belongs to Latest stock picks and covers the offline shape only; other
// chains wait for Screen latest. A changed setting never starts a dated test.
function settingsChanged(run=true){
  updateResultsState();
  StrategyDraft.touch();
  StrategyDraft.render();
  if(run && screeningMode==='latest' && StrategyDraft.flat() && StrategyDraft.complete() && document.getElementById('auto-run').checked)applyRange();
}
const money=v=>v===null?'—':'$'+(v/1e6).toLocaleString('en-US',{maximumFractionDigits:1})+'m';
const safe=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function initializeFilters(){
  document.getElementById('trade-start').value='2015-01-01';
  selectMarket('us');
  document.getElementById('rebalance-months').value='12';
  if(document.getElementById('calendar-custom'))document.getElementById('calendar-custom').checked=false;
  document.getElementById('date-testing').value='random';
  document.getElementById('random-trials').value='24';
  document.getElementById('random-seed').value='42';
  document.getElementById('repeat-random').checked=false;
  StrategyDraft.reset();
}
const comparisons=[['gt','More than (>)'],['lt','Less than (<)'],['ge','At least (≥)'],['le','At most (≤)']];
function sourceField(key,row,name){
  return `<div class="filter-source"><label for="filter-search-${key}">${row.kind==='rank'?'Rank by':'Filter on'}</label><div class="filter-combo"><input id="filter-search-${key}" data-filter-search="${key}" type="text" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="filter-options-${key}" autocomplete="off" spellcheck="false" placeholder="Type to search: P/E, revenue, margin…" value="${safe(row.label)}" data-label="${safe(row.label)}"${row.title?` title="${safe(row.title)}"`:''}><span class="filter-combo-arrow" aria-hidden="true">▾</span><div id="filter-options-${key}" class="filter-options" role="listbox" aria-label="${name} choices" hidden></div></div></div>`;
}
function stepRow(row){
  const key=row.id,name='Step '+row.number+' · '+(row.kind==='rank'?'Rank':'Filter'),field=(id,extra)=>`id="step-${id}-${key}" data-step="${key}" data-key="${id}" ${extra}`;
  let middle,value;
  if(row.kind==='rank'){
    middle=`<select ${field('direction',`aria-label="${name} order"`)}>${[['highest','Highest first'],['lowest','Lowest first']].map(([v,l])=>`<option value="${v}" ${row.direction===v?'selected':''}>${l}</option>`).join('')}</select>`;
    value=`<span class="condition-value"><span class="condition-unit">Ranks</span><input ${field('rank_from',`aria-label="${name} first rank" type="number" min="1" max="5000" step="1" required value="${safe(row.rank_from)}"`)}><span class="condition-unit">to</span><input ${field('rank_to',`aria-label="${name} last rank" type="number" min="1" max="5000" step="1" required value="${safe(row.rank_to)}"`)}></span>`;
  }else if(row.text){
    middle=`<select ${field('op',`aria-label="${name} comparison"`)}>${[['eq','Is'],['ne','Is not']].map(([v,l])=>`<option value="${v}" ${row.op===v?'selected':''}>${l}</option>`).join('')}</select>`;
    value=`<select ${field('value',`aria-label="${name} value"`)}><option value="">Choose…</option>${[...new Set([...row.choices,...(row.value?[row.value]:[])])].map(v=>`<option value="${safe(v)}" ${v===row.value?'selected':''}>${safe(v)}</option>`).join('')}</select>`;
  }else{
    middle=`<select ${field('op',`aria-label="${name} comparison"`)}>${comparisons.map(([v,l])=>`<option value="${v}" ${row.op===v?'selected':''}>${safe(l)}</option>`).join('')}</select>`;
    const unit=row.units?.length>1?`<select ${field('unit',`aria-label="${name} unit"`)}>${row.units.map(u=>`<option value="${safe(u)}" ${u===row.unit?'selected':''}>${safe(VariableWorkspace.displayName(u))}</option>`).join('')}</select>`:row.unit?`<span class="condition-unit">${safe(VariableWorkspace.displayName(row.unit))}</span>`:'';
    value=`<span class="condition-value"><input ${field('value',`aria-label="${name} value" inputmode="decimal" autocomplete="off" value="${safe(row.value)}" placeholder="Enter value"`)}>${unit}</span>`;
  }
  // A compact button keeps its full name as the accessible name and the tooltip.
  const button=(action,label,text=label,disabled=false)=>`<button type="button" id="step-${action}-${key}" data-action="${action}" data-step="${key}" aria-label="${label} ${name.toLowerCase()}" title="${label}"${disabled?' disabled':''}>${text}</button>`;
  return `<li class="condition-row step-${row.kind}" data-row="${key}"><span class="step-name">${name}</span>${sourceField(key,row,name)}${middle}${value}<div class="condition-actions">${row.formula?button('edit','Edit formula'):''}${button('up','Move up','↑',row.number===1)}${button('down','Move down','↓',row.last)}${button('remove','Remove','✕')}</div></li>`;
}
// When the steps change, each row slides from its old place to its new one. The
// step that the user moved lifts, slides and settles with a short tint. A chosen
// source slides from the New row to its step. A new row fades in. A system that
// asks for reduced motion gets the plain redraw.
let movingStep=null;
function slideSteps(list,before){
  const moved=movingStep;movingStep=null;
  const rows=[...list.querySelectorAll('[data-row]')];
  if(!before.size||!rows.length||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  for(const row of rows){
    const id=row.dataset.row,start=before.get(id)??before.get('new');
    if(start===undefined){row.animate([{opacity:0,transform:'translateY(-6px)'},{opacity:1,transform:'none'}],{duration:200,easing:'ease-out'});continue;}
    const shift=start-row.getBoundingClientRect().top;
    if(id===moved||!before.has(id))row.animate([
      {transform:`translateY(${shift}px) scale(1.01)`,boxShadow:'0 0 0 6px #fff,0 14px 30px #102e252e',backgroundColor:'#fff',zIndex:1,easing:'cubic-bezier(.2,.8,.2,1)'},
      {offset:.5,transform:'none',boxShadow:'0 0 0 6px #e3f0e7,0 2px 6px #102e2514',backgroundColor:'#e3f0e7',zIndex:1},
      {transform:'none',boxShadow:'0 0 0 6px #e3f0e700,0 0 0 #102e2500',backgroundColor:'#e3f0e700',zIndex:1}],{duration:700});
    else if(Math.abs(shift)>=1)row.animate([{transform:`translateY(${shift}px)`},{transform:'none'}],{duration:330,easing:'cubic-bezier(.2,.8,.2,1)'});
  }
}
function renderSteps(){
  const rows=StrategyDraft.view(),list=document.getElementById('strategy-steps');
  const before=new Map([...list.querySelectorAll('[data-row]')].map(row=>[row.dataset.row,row.getBoundingClientRect().top]));
  list.innerHTML=rows.map(stepRow).join('')+(pendingStep?`<li class="condition-row condition-pending" data-row="new"><span class="step-name">New ${pendingStep}</span>${sourceField('new',{kind:pendingStep,label:''},'New '+pendingStep)}<div class="condition-actions"><button type="button" data-action="cancel">Cancel</button></div></li>`:'');
  slideSteps(list,before);
  FilterPicker.refresh();
  // Variable rows list their units from the catalog; a restored strategy loads it once.
  if(rows.some(row=>row.formula)&&stepSourcesState==='idle')loadStepSources();
}
function stepMessage(text,failed=false){const note=document.getElementById('filter-message');note.textContent=text;note.className=failed?'error':'hint';}
// Every source a step can use, in one searchable list. Built-in sources need
// no service; saved variables and financial inputs come from the local service.
function stepChoices(key){
  const kind=key==='new'?pendingStep:StrategyDraft.view().find(row=>row.id===key)?.kind,catalog=StrategyDraft.catalog(),groups=[];
  if(kind==='filter')groups.push({label:'Size and listing',options:Object.entries(StrategyDraft.fields).map(([field,label])=>({value:{kind:'field',field,label},label,keywords:field}))});
  groups.push({label:'EV/EBITDA metrics',options:Object.entries(catalog.metrics).flatMap(([key,item])=>['yield','multiple'].map(component=>{const label=pairLabel(item,component);return {value:{kind:'builtin',id:'metric:'+key+':'+component,label},label,keywords:key,detail:component==='yield'?'Higher is cheaper':'Lower is cheaper',disabled:!screeningData.metrics[key]};}))});
  groups.push({label:'Built-in values',options:Object.entries(catalog.filters).map(([field,item])=>({value:{kind:'builtin',id:'filter:'+field,label:item.label},label:item.label,keywords:field,
    detail:item.available?'':screeningData.filter_catalog[field]?'Needs annual financial data. Download it in Manage backtest data.':'Unavailable in this data',disabled:!item.available}))});
  if(stepSources){
    const library=[...stepSources.library].sort((a,b)=>(b.favourite?1:0)-(a.favourite?1:0));
    groups.push({label:'My variables',options:library.map(entry=>({value:{kind:'library',variable_id:entry.variable_id,revision:entry.revision,label:entry.name},label:(entry.favourite?'★ ':'')+entry.name,detail:'Saved variable'}))});
    groups.push({label:'Financial inputs',options:stepSources.inputs.map(item=>({value:{kind:'input',id:item.id,label:item.name},label:item.name,detail:item.category}))});
  }
  const note=stepSourcesState==='loading'?'Loading saved variables and financial inputs…':stepSourcesState==='failed'?'Saved variables and financial inputs need the local service. Built-in sources work offline.':'';
  return {groups,note,actions:stepSourcesState==='failed'?[]:[{value:{kind:'create'},label:'＋ Create a new variable…',detail:'Type a formula, then use it in this step.'}]};
}
function loadStepSources(){
  if(stepSourcesState==='loading')return;
  if(!stepSources)stepSourcesState='loading';
  VariableWorkspace.sources().then(value=>{stepSources=value;stepSourcesState='ready';},()=>{stepSourcesState=stepSources?'ready':'failed';}).then(()=>{renderSteps();StrategyDraft.render();});
}
function focusStep(id,key){document.getElementById('step-'+key+'-'+id)?.focus();}
const firstControl=id=>StrategyDraft.view().find(row=>row.id===id)?.kind==='rank'?'direction':'value';
function chooseStep(key,choice){
  const role=key==='new'?pendingStep:key;
  stepMessage('');
  if(choice.kind==='create'){void VariableWorkspace.open(role,null);return;}
  const expected=StrategyDraft.read().revision;
  if(choice.kind==='builtin'||choice.kind==='field'){
    const id=StrategyDraft.patch({role,source:choice.kind==='field'?{kind:'field',field:choice.field}:{kind:'builtin',id:choice.id}},expected);
    focusStep(id,firstControl(id));settingsChanged();return;
  }
  stepMessage('Adding '+choice.label+'…');
  VariableWorkspace.useSource(role,choice,expected).then(()=>{
    stepMessage('');const id=StrategyDraft.read().changed;focusStep(id,firstControl(id));
  },failure=>{
    renderSteps();
    stepMessage(failure.code==='STALE_DRAFT'?'The strategy changed while '+choice.label+' was loading. Choose it again.':failure.message,true);
  });
}
function updateMetricLabels(o){
  const label=metricLabel(o.metric);
  document.querySelectorAll('[data-metric-multiple]').forEach(el=>el.textContent=label+' (×)');
  document.querySelectorAll('[data-metric-yield]').forEach(el=>el.textContent=inverseRatio(label)+' (%)');
}
function setModeVisibility(){
  const latest=screeningMode==='latest';
  document.getElementById('schedule-controls').hidden=latest;
  document.getElementById('latest-view').hidden=!latest;
  document.getElementById('mode-latest').setAttribute('aria-pressed',latest);
  document.getElementById('mode-backtest').setAttribute('aria-pressed',!latest);
  // Latest stock picks has Screen latest and Auto-run. Historical backtest has the test name and Add to queue.
  for(const id of ['run-screen','auto-run-controls'])document.getElementById(id).hidden=!latest;
  document.getElementById('queue-controls').hidden=latest;
  // The status line, the results line and the notes of the displayed picks belong to Latest stock picks.
  for(const id of ['screen-status','results-state','screen-coverage','range-note'])document.getElementById(id).hidden=!latest;
  const artifact=ResultArtifacts.forView('latest'),scalar=document.getElementById('scalar-evidence-view');
  applyPresentation(artifact?.presentation);renderSteps();
  // A server latest panel in the builder belongs to latest mode only.
  if(!latest&&scalar?.parentNode?.id==='workspace-builder')scalar.hidden=true;
  if(latest&&artifact?.version===4){EvidenceResults.show(artifact);Workspaces.published(artifact);}
  StrategyDraft.render();
}
// Only the offline latest screen recalculates on a mode switch; a dated
// test starts from Add to queue.
function switchMode(mode){
  screeningMode=mode;setModeVisibility();settingsChanged(mode==='latest');
}
function applyLatest(){
  let settings,result;
  try{
    settings=currentSettings();
    if(!screeningData.latest.metadata.asof)throw Error('Prepare '+marketLabels[selectedMarket()]+' data from Manage backtest data.');
    StrategyDraft.requireValues();result=StockScreener.latestScreen(screeningData,StrategyDraft.flat());
  }
  catch(error){document.getElementById('screen-error').textContent=error.message+' The previous result remains displayed.';return;}
  publishResult(ResultArtifacts.create(settings,result,sourceCatalog(),latestPresentation(result)));
}
function renderLatest(r){
  // A server latest screen hides this offline table; an offline screen shows it again.
  document.getElementById('screen-error').textContent='';document.getElementById('latest-view').hidden=false;
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
// Screen latest. The offline screen runs the shape flat options express; every other chain runs on the service.
function applyRange(){
  if(document.getElementById('run-screen').disabled)return;
  updateResultsState();
  if(StrategyDraft.flat()){applyLatest();return;}
  document.getElementById('run-screen').disabled=true;
  void StrategyDraft.prepareSubmission().then(settings=>ScheduleView.runPrepared(settings)).catch(error=>{document.getElementById('screen-error').textContent=error.message;}).finally(()=>{document.getElementById('run-screen').disabled=false;});
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

function restoreSavedBacktest(snapshot,name){
  const artifact=ResultArtifacts.decode(snapshot);
  if(artifact.kind==='latest')throw Error('Expected a saved backtest.');
  publishResult(artifact,name);
}
function copySavedBacktestSettings(snapshot){
  const artifact=ResultArtifacts.decode(snapshot);
  if(artifact.kind==='latest')throw Error('Expected a saved backtest.');
  restoreBacktestSettings(artifact.settings,artifact.catalog,artifact.result.configuration?.seed);
  Workspaces.show('builder');
  document.getElementById('queue-add').focus?.({preventScroll:true});
}
// The form owns one ordered draft: Universe (market and pool controls), then
// Rank and Filter steps. Step IDs exist only in the browser. Restoration
// sources cannot replace a queued edit; only its session may load settings
// until a confirmed save/cancel ends it.
const StrategyDraft=(()=>{
  // steps is the active sleeve's list, so the step editors work on that sleeve.
  let active=null,revision=0,sleeves=[],current=0,steps=[],detached=[],projections={},recorded=[],restoredCatalog=null,restored=null,captured=null,nextId=0,changed=null;
  const copy=value=>JSON.parse(JSON.stringify(value));
  const fields={market_cap:'Market cap',enterprise_value:'Enterprise value',sector:'Sector',exchange:'Exchange'};
  const textField=source=>source.kind==='field'&&(source.field==='sector'||source.field==='exchange');
  const flatKeys=new Set([...Object.keys(StockScreener.defaults),'rank_from','rank_to','filters']);
  // Editable labels belong to the draft. Result labels stay with their artifact.
  // Availability comes from current support, even when a saved label is retained.
  function catalog(){
    const source=sourceCatalog();
    return {metrics:{...source.metrics,...restoredCatalog?.metrics},filters:Object.fromEntries(Object.entries({...source.filters,...restoredCatalog?.filters}).map(([id,item])=>[id,{...item,available:!!source.filters[id]?.available}]))};
  }
  const exactKey=value=>JSON.stringify([value.variable_id,value.revision]);
  const bare=list=>list.map(({id,...step})=>step);
  // Whole-draft rules (captures, the step limit, submission) read every sleeve.
  const allSteps=()=>sleeves.flatMap(sleeve=>sleeve.steps);
  // A sleeve takes the value of its sector Is filter as its name until a name is typed.
  const defaultName=(list,index)=>list.find(step=>step.source.kind==='field'&&step.source.field==='sector'&&step.op==='eq'&&step.threshold)?.threshold||'Sleeve '+(index+1);
  const nameOf=(sleeve,index)=>sleeve.name||defaultName(sleeve.steps,index);
  // The market keys the capture cache and the unchanged restore: a Hong Kong or
  // Japan capture holds the market-aware form of each formula.
  const content=()=>JSON.stringify({market:selectedMarket(),universe:{pool:document.getElementById('stock-pool').value},sleeves:sleeves.map((sleeve,index)=>({name:nameOf(sleeve,index),steps:bare(sleeve.steps)}))});
  function compactDetached(captures,chain){
    const needed=new Set(chain.map(step=>step.source).filter(source=>source.kind==='formula').map(exactKey)),kept=[];
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
  const builtinDescriptor=id=>recorded.find(item=>item.id===id)||VariableWorkspace.builtin(id);
  function sourceLabel(source){
    if(source.kind==='field')return fields[source.field]||source.field;
    if(source.kind==='builtin'){
      const [,key,component]=source.id.split(':'),item=catalog().metrics[key];
      const label=source.id.startsWith('filter:')?catalog().filters[key]?.label:item&&pairLabel(item,component);
      return recorded.find(item=>item.id===source.id)?.label||label||source.id;
    }
    for(const capture of detached){const found=capture.presentation.find(item=>item.variable_id===source.variable_id&&item.revision===source.revision);if(found)return found.name;}
    return source.variable_id;
  }
  // Canonical unit and default display of a formula or built-in source.
  function sourceOutput(source){
    if(source.kind==='builtin')return builtinDescriptor(source.id);
    for(const capture of [...detached].reverse()){const found=capture.program.definitions.find(item=>exactKey(item)===exactKey(source));if(found)return found;}
    return null;
  }
  // A formula step's exact root and the capture that holds it, as the editor opens it.
  function formula(role){
    const {variable_id,revision}=steps.find(item=>item.id===role).source,root={variable_id,revision};
    return copy({root,capture:[...detached].reverse().find(capture=>capture.program.definitions.some(item=>exactKey(item)===exactKey(root)))});
  }
  const shown=step=>step.submitted_threshold||step.threshold;
  // An edited threshold drops the values derived from its earlier submission.
  function setThreshold(step,threshold){step.threshold=threshold;delete step.submitted_threshold;delete step.comparison_value;delete step.storage_comparison_value;}
  // A new source keeps the typed value. Built-in units are fixed (a built-in
  // filter lane may wait for the catalog); a field or variable keeps the
  // chosen unit only when it still fits.
  function retarget(step){
    if(textField(step.source)){step.op='eq';setThreshold(step,'');return;}
    const previous=typeof step.threshold==='string'||!step.threshold?{value:''}:shown(step),source=step.source;
    if(!step.op||step.op==='eq'||step.op==='ne')step.op='gt';
    const output=sourceOutput(source),unit=source.kind==='field'?(['usd','usd_million'].includes(previous.unit)?previous.unit:'usd_million')
      :source.kind==='formula'?(VariableWorkspace.displays(output?.unit).includes(previous.unit)?previous.unit:output?.display||'number')
      :source.id.startsWith('metric:')?(source.id.endsWith(':yield')?'percent':'multiple'):output?.display;
    setThreshold(step,{value:previous.value,unit});
  }
  function view(){
    return steps.map((step,index)=>{
      const formula=step.source.kind==='formula';
      const row={id:step.id,kind:step.kind,number:index+1,last:index===steps.length-1,label:sourceLabel(step.source),title:formula?step.source.variable_id+' @ '+step.source.revision:'',formula};
      if(step.kind==='rank')return {...row,direction:step.direction,rank_from:step.rank_from,rank_to:step.rank_to};
      if(typeof step.threshold==='string')return {...row,text:true,op:step.op,value:step.threshold,choices:screeningData.choices[step.source.field]||[]};
      const threshold=shown(step),units=step.source.kind==='field'?['usd_million','usd']:formula?[...new Set([...VariableWorkspace.displays(sourceOutput(step.source)?.unit),threshold.unit])]:null;
      return {...row,op:step.op,value:threshold.value,unit:threshold.unit,units};
    });
  }
  // Exact decimal scaling: one decimal-to-binary rounding, as the server does.
  const scaled=(text,exponent)=>{const [mantissa,power='0']=String(text).trim().toLowerCase().split('e');return /^[+-]?(\d+\.?\d*|\.\d+)$/.test(mantissa)&&/^[+-]?\d+$/.test(power)?Number(mantissa+'e'+(+power+exponent)):NaN;};
  const exponents={usd:0,USD:0,usd_million:6,percent:-2,number:0,multiple:0,scalar:0};
  // The offline latest screen runs exactly this shape: one highest EBITDA/EV
  // yield Rank, first or last, and filters the flat options already express.
  // Missing minimums become 0, which every prepared row passes. Sleeves run on the service.
  function flat(){
    if(sleeves.length>1)return null;
    const ranks=steps.filter(step=>step.kind==='rank'),rank=ranks[0],[kind,metric,component]=rank?.source.id?.split(':')||[];
    if(ranks.length!==1||rank.source.kind!=='builtin'||kind!=='metric'||component!=='yield'||rank.direction!=='highest')return null;
    const at=steps.indexOf(rank);if(at!==0&&at!==steps.length-1)return null;
    const o={rank_from:rank.rank_from,rank_to:rank.rank_to,selection_order:at===steps.length-1?'filter_first':'rank_first',metric,pool:document.getElementById('stock-pool').value,
      min_cap:0,max_cap:null,min_ev:0,min_yield:0,max_multiple:null,sector:null,exchange:null,filters:[]},seen=new Set();
    for(const step of steps){
      if(step===rank)continue;
      const source=step.source,threshold=typeof step.threshold==='string'?null:shown(step);
      const key=source.kind==='field'?{market_cap:{ge:'min_cap',le:'max_cap'},enterprise_value:{ge:'min_ev'},sector:{eq:'sector'},exchange:{eq:'exchange'}}[source.field][step.op]
        :source.id===rank.source.id&&step.op==='ge'?'min_yield':source.id==='metric:'+metric+':multiple'&&step.op==='le'?'max_multiple':null;
      if(key){
        if(seen.has(key))return null;seen.add(key);
        if(!threshold){o[key]=step.threshold;continue;}
        if(!Object.hasOwn(exponents,threshold.unit))return null;
        o[key]=scaled(threshold.value,exponents[threshold.unit]);continue;
      }
      if(source.kind!=='builtin'||!source.id.startsWith('filter:')||!['lt','gt'].includes(step.op)||threshold.unit!==undefined&&threshold.unit!==builtinDescriptor(source.id)?.display)return null;
      o.filters.push({field:source.id.slice(7),op:step.op,value:scaled(threshold.value,0)});
    }
    return o;
  }
  const empty=step=>step.kind==='filter'&&String(typeof step.threshold==='string'?step.threshold:shown(step).value).trim()==='';
  function requireValues(list=allSteps()){if(list.some(empty))throw Error('Enter a value for each filter.');}
  const placeholder=()=>{const {market,...draft}=JSON.parse(content());return {format:'strategy-draft',version:2,...draft};};
  const unchanged=()=>restored?.content===content();
  function selection(){
    const offline=viewKey()==='latest'&&flat();
    if(offline)return offline;
    // A submission captures a copied flat or capture/1 strategy as a chain;
    // until then the copy shows its recorded selection.
    if(captured?.content===content())return {strategy:copy(captured.strategy)};
    if(unchanged())return copy(restored.selection);
    return {strategy:placeholder()};
  }
  // Old size, metadata and pair bounds become ordinary filters. A zero minimum
  // adds no step: every prepared row has a positive market cap and EV, and
  // ranked yields are positive. An empty flat minimum matched nothing, so it
  // returns as a filter that needs a value.
  function boundSteps(bounds,metric,flatSettings){
    return [['min_cap','market_cap','ge'],['max_cap','market_cap','le'],['min_ev','enterprise_value','ge'],['sector','sector','eq'],['exchange','exchange','eq'],['min_yield','yield','ge'],['max_multiple','multiple','le']].flatMap(([key,lane,op])=>{
      const value=bounds[key],pair=lane==='yield'||lane==='multiple';
      if(value===undefined||value===0&&op==='ge'||value===null&&!(flatSettings&&op==='ge'))return [];
      const source=pair?{kind:'builtin',id:'metric:'+metric+':'+lane}:{kind:'field',field:lane};
      if(op==='eq')return [{kind:'filter',source,op,threshold:value}];
      const [unit,exponent,canonical]=lane==='yield'?['percent',-2,'number']:lane==='multiple'?['multiple',0,'multiple']:['usd_million',6,'usd'];
      if(value===null)return [{kind:'filter',source,op,threshold:{value:'',unit}}];
      // Keep a short display spelling only when it converts back to the same value.
      const text=String(Number((exponent>0?value/10**exponent:value*10**-exponent).toPrecision(15)));
      return [{kind:'filter',source,op,threshold:scaled(text,exponent)===value?{value:text,unit}:{value:String(value),unit:canonical}}];
    });
  }
  // One boundary for every recorded format. filter_first means filters, then
  // the Rank; rank_first means the Rank, then filters. Formats before sleeves
  // are one sleeve. A recorded name equal to its default keeps following the sector filter.
  function fromSettings(settings){
    const capture=settings.strategy,one=(pool,list)=>({pool,sleeves:[{name:'',steps:list}]});
    if(capture?.version===3)return {pool:capture.universe.pool,sleeves:capture.sleeves.map((sleeve,index)=>({name:sleeve.name===defaultName(sleeve.steps,index)?'':sleeve.name,steps:copy(sleeve.steps)}))};
    if(capture?.version===2)return one(capture.universe.pool,copy(capture.steps));
    const order=(selectionOrder,filters,rank)=>selectionOrder==='rank_first'?[rank,...filters]:[...filters,rank];
    if(capture){
      const s=capture.selection,metric=s.ranking.source.id?.split(':')[1];
      return one(capture.pool,order(s.selection_order,[...boundSteps(capture.bounds,metric,false),...s.conditions.map(item=>({kind:'filter',...copy(item)}))],
        {kind:'rank',...copy(s.ranking),rank_from:s.rank_from,rank_to:s.rank_to}));
    }
    const o={...StockScreener.defaults,...settings};
    return one(o.pool,order(o.selection_order,[...boundSteps(o,o.metric,true),...(o.filters||[]).map(item=>({kind:'filter',source:{kind:'builtin',id:'filter:'+item.field},op:item.op,threshold:{value:String(item.value)}}))],
      {kind:'rank',source:{kind:'builtin',id:'metric:'+o.metric+':yield'},direction:'highest',rank_from:o.rank_from,rank_to:o.rank_to}));
  }
  // Built-in lanes chosen before the catalog loaded take its display unit here.
  // One sleeve sends a chain (version 2); two or more send sleeves (version 3).
  async function intentFor(draft){
    const all=draft.sleeves.flatMap(sleeve=>sleeve.steps),unranked=draft.sleeves.find(sleeve=>!sleeve.steps.some(step=>step.kind==='rank'));
    if(all.length>50)throw Error('A strategy has at most 50 steps.');
    if(unranked)throw Error(draft.sleeves.length>1?'Add a Rank step to '+unranked.name+'.':'Add a Rank step.');
    requireValues(all);
    let builtins=null;
    const chains=[];
    for(const sleeve of draft.sleeves){
      const chain=[];
      for(const step of sleeve.steps){
        if(step.kind==='rank'){chain.push({...step,rank_from:+step.rank_from,rank_to:+step.rank_to});continue;}
        if(typeof step.threshold==='string'||step.submitted_threshold){chain.push(step);continue;}
        let unit=step.threshold.unit;
        if(!unit){
          builtins??=(await VariableWorkspace.request('/catalog')).builtins;
          unit=builtins.find(item=>item.id===step.source.id)?.display;
          if(!unit)throw Error('The selected built-in filter is unavailable. Your settings were kept.');
        }
        chain.push({...step,threshold:{value:String(step.threshold.value).trim(),unit}});
      }
      chains.push({name:sleeve.name,steps:chain});
    }
    return chains.length===1?{format:'strategy-intent',version:2,universe:draft.universe,steps:chains[0].steps}:{format:'strategy-intent',version:3,universe:draft.universe,sleeves:chains};
  }
  // An unchanged chain capture is resubmitted as recorded. Saving an unchanged
  // held queue edit keeps its original selection in any format; every other
  // submission captures the draft.
  async function prepareSubmission({held=false}={}){
    let settings=copy(currentSettings());
    if(held&&active&&unchanged()){const {strategy,...rest}=settings;return {...rest,...copy(restored.selection)};}
    // A copied flat or capture/1 selection runs as a newly captured chain.
    if(!(settings.strategy?.version>=2))settings={...Object.fromEntries(Object.entries(settings).filter(([key])=>!flatKeys.has(key))),strategy:placeholder()};
    if(settings.strategy?.format!=='strategy-draft')return settings;
    // Snapshot before the first await; later edits never change this submission.
    const key=content(),chosen=settings.strategy.sleeves.flatMap(sleeve=>sleeve.steps),available=copy(compactDetached(detached,chosen)),known=copy(projections);
    const sources=chosen.map(step=>step.source).filter(source=>source.kind==='formula');
    const intent=await intentFor(settings.strategy);
    for(const source of sources){
      const exact=exactKey(source);if(known[exact])continue;
      const capture=[...available].reverse().find(item=>item.program.definitions.some(entry=>exactKey(entry)===exact));
      if(!capture)throw Error('The exact selected variable content is unavailable. Open the picker again. Your draft was kept.');
      const projected=await VariableWorkspace.request('/detached',{root:{variable_id:source.variable_id,revision:source.revision},capture});
      known[exact]={submitted:projected.authored,labels:capture.presentation};
    }
    const prepared=await VariableWorkspace.request('/capture',{intent,market:settings.market,...(sources.length?VariableWorkspace.content(...sources.map(source=>known[exactKey(source)]),{labels:available.flatMap(capture=>capture.presentation)}):{})});
    captured={content:key,strategy:copy(prepared.strategy)};
    for(const source of sources)if(allSteps().some(step=>step.source.kind==='formula'&&exactKey(step.source)===exactKey(source)))projections[exactKey(source)]??=known[exactKey(source)];
    return {...settings,strategy:prepared.strategy};
  }
  const defaultSteps=()=>[{kind:'filter',source:{kind:'field',field:'market_cap'},op:'ge',threshold:{value:'100',unit:'usd_million'}},
    {kind:'filter',source:{kind:'field',field:'enterprise_value'},op:'ge',threshold:{value:'50',unit:'usd_million'}},
    {kind:'rank',source:{kind:'builtin',id:'metric:ev_ebitda:yield'},direction:'highest',rank_from:1,rank_to:50}];
  const identify=list=>list.map(step=>({id:'s'+(++nextId),...step}));
  function load(next,catalogValue,builtins,variables){
    sleeves=next.map(sleeve=>({name:sleeve.name,steps:identify(sleeve.steps)}));current=0;steps=sleeves[0].steps;restoredCatalog=catalogValue&&copy(catalogValue);recorded=copy(builtins||[]);
    detached=variables?[copy(variables)]:[];projections={};captured=null;restored=null;pendingStep=null;
  }
  function reset(){
    touch();load([{name:'',steps:defaultSteps()}]);
    document.getElementById('stock-pool').innerHTML='<option value="cached">All stocks with cached prices</option>';document.getElementById('stock-pool').value='cached';
    renderSteps();render();
  }
  function render(){
    EngineControls.sync();
    const last=steps.findLast(step=>step.kind==='rank'),offline=flat(),names=sleeves.map(nameOf),total=allSteps().length;
    document.getElementById('strategy-heading').textContent=sleeves.length>1?'Sleeves '+names.join(' + '):last?(last.direction==='highest'?'Highest ':'Lowest ')+sourceLabel(last.source):'Add a Rank step';
    // One tab per sleeve. A name field and Remove show when there are two or more sleeves.
    document.getElementById('sleeve-tabs').innerHTML=names.map((name,index)=>`<button type="button" data-sleeve="${index}" aria-pressed="${index===current}">${safe(name)}</button>`).join('');
    for(const id of ['add-filter','add-rank'])document.getElementById(id).disabled=total>=50;
    document.getElementById('sleeve-copy').disabled=total+steps.length>50;
    document.getElementById('sleeve-edit').hidden=sleeves.length<2;
    const name=document.getElementById('sleeve-name');name.value=sleeves[current].name;name.placeholder=defaultName(steps,current);
    document.getElementById('auto-run').disabled=!offline;
    document.getElementById('auto-run-note').textContent=offline?'':'Auto-run is paused for this strategy. Select Screen latest to calculate.';
    document.getElementById('legacy-pool-note').hidden=document.getElementById('stock-pool').value!=='legacy'||!!offline;
    // Random-date and custom-interval inputs show only while their choice is on,
    // and the dates block only in backtest mode. A hidden input with a range is
    // disabled, so its value cannot block form validation.
    const dated=screeningMode!=='latest',custom=document.getElementById('calendar-custom').checked,random=document.getElementById('date-testing').value==='random';
    document.getElementById('random-controls').hidden=!random;document.getElementById('calendar-interval').hidden=!custom;
    const enabled={'trade-start':dated,'trade-end':dated,'rebalance-months':!custom,'calendar-count':dated&&custom,'random-trials':dated&&random,'random-seed':dated&&random&&document.getElementById('repeat-random').checked};
    for(const [id,on] of Object.entries(enabled))document.getElementById(id).disabled=!on;
  }
  function after(id){changed=id;touch();renderSteps();render();updateResultsState();return id;}
  function patch(change,expected){
    if(expected!==revision)throw Object.assign(Error('The strategy draft changed. Choose the source again.'),{code:'STALE_DRAFT'});
    const {role,source}=change;
    let step=steps.find(item=>item.id===role);
    if(!step){
      if(role!=='filter'&&role!=='rank')throw Object.assign(Error('The strategy draft changed. Choose the source again.'),{code:'STALE_DRAFT'});
      if(allSteps().length>=50)throw Error('A strategy has at most 50 steps.');
      // A new filter goes before the last Rank, so it applies before final ranking.
      [step]=identify([role==='rank'?{kind:'rank',direction:'highest',rank_from:1,rank_to:50}:{kind:'filter'}]);
      const last=steps.findLastIndex(item=>item.kind==='rank');
      steps.splice(role==='filter'&&last>=0?last:steps.length,0,step);pendingStep=null;
    }
    if(change.capture)detached.push(copy(change.capture));
    step.source=copy(source);
    if(step.kind==='filter')retarget(step);
    if(change.authored)projections[exactKey(source)]={submitted:copy(change.authored),labels:copy(change.capture.presentation)};
    detached=compactDetached(detached,allSteps());
    const selected=new Set(allSteps().map(item=>item.source).filter(item=>item.kind==='formula').map(exactKey));
    projections=Object.fromEntries(Object.entries(projections).filter(([key])=>selected.has(key)));
    return after(step.id);
  }
  function edit(id,key,value){
    const step=steps.find(item=>item.id===id);if(!step)return;
    if(key==='direction'||key==='op')step[key]=value;
    else if(key==='rank_from'||key==='rank_to')step[key]=value===''?'':Number(value);
    else if(typeof step.threshold==='string')step.threshold=value;
    else setThreshold(step,{...shown(step),[key]:value});
  }
  // A committed range keeps first ≤ last by moving the other end.
  function commitRange(id,key){
    const step=steps.find(item=>item.id===id);
    if(step?.kind!=='rank'||!(+step.rank_from>+step.rank_to))return;
    if(key==='rank_from')step.rank_to=step.rank_from;else step.rank_from=step.rank_to;
    renderSteps();focusStep(id,key);
  }
  function move(id,offset){
    const at=steps.findIndex(item=>item.id===id),to=at+offset;
    if(at<0||to<0||to>=steps.length)return;
    [steps[at],steps[to]]=[steps[to],steps[at]];
    after(id);
    focusStep(id,document.getElementById('step-'+(offset<0?'up':'down')+'-'+id)?.disabled?(offset<0?'down':'up'):(offset<0?'up':'down'));
  }
  function remove(id){
    const at=steps.findIndex(item=>item.id===id);if(at<0)return;
    steps.splice(at,1);detached=compactDetached(detached,allSteps());
    after(null);
    const next=steps[Math.min(at,steps.length-1)];
    if(next)focusStep(next.id,'remove');else document.getElementById('add-filter').focus?.();
  }
  const refusal=()=>Error('Save or cancel the queued edit before replacing the strategy settings.');
  function apply(settings,catalogValue=sourceCatalog(),seed=settings.seed){
    const restoredSteps=fromSettings(settings);
    touch();
    load(restoredSteps.sleeves,catalogValue,settings.strategy?.builtins,settings.strategy?.variables);
    selectMarket(settings.market||'us');
    // Every restored record is a dated test.
    screeningMode='backtest';
    const set=(id,value,label=value)=>{
      const control=document.getElementById(id),text=String(value??'');
      if(control.tagName==='SELECT' && ![...control.options].some(option=>option.value===text))control.add(new Option(label,text));
      control.value=text;
    };
    set('stock-pool',restoredSteps.pool,restoredSteps.pool==='legacy'?'Recorded US original candidate set':restoredSteps.pool);
    if(document.getElementById('backtest-engine'))set('backtest-engine',settings.engine??'original',
      EngineControls.label?.(settings.engine??'original')||settings.engine||'Original');
    // January settings restore the strategy only; their book years never
    // become a dated calendar.
    if(settings.mode!=='january'){
      CalendarSettings.restore(settings);
      set('date-testing',settings.mode==='random'?'random':'single');
      if(settings.mode==='random'){
        set('random-trials',settings.trials);set('random-seed',seed??42);
        document.getElementById('repeat-random').checked=seed!==undefined;
      }
    }
    restored={content:content(),selection:settings.strategy?{strategy:copy(settings.strategy)}:Object.fromEntries(Object.entries(settings).filter(([key])=>flatKeys.has(key)))};
    setModeVisibility();
  }
  // A copy refuses more than 50 steps; a held queue edit loads every step. Every
  // copy into the builder leaves the test-name box empty: a name typed for other
  // settings must not name the next test. A held edit loads its own name.
  function restore(settings,...args){
    if(active)throw refusal();
    if(fromSettings(settings).sleeves.flatMap(sleeve=>sleeve.steps).length>50)throw Error('This strategy has more than 50 steps as a chain, so it cannot be copied into the builder. Its record was kept.');
    apply(settings,...args);document.getElementById('queue-name').value='';
  }
  function beginQueuedEdit(id){
    if(active)throw refusal();
    restored=null;
    const session={id,
      restore(...args){if(active!==session)throw Error('This strategy edit is no longer active.');return apply(...args);},
      end(){if(active===session){active=null;touch();}}
    };
    active=session;touch();return session;
  }
  // A tab change makes a late choice for the other sleeve stale.
  function select(index){current=index;steps=sleeves[index].steps;pendingStep=null;document.getElementById('strategy-steps').innerHTML='';after(null);}
  // A copy repeats the active sleeve's steps, without its typed name, and becomes the active sleeve.
  function copySleeve(){sleeves.push({name:'',steps:identify(copy(bare(steps)))});select(sleeves.length-1);}
  function removeSleeve(){sleeves.splice(current,1);detached=compactDetached(detached,allSteps());select(Math.min(current,sleeves.length-1));}
  function describe(role){
    const at=steps.findIndex(item=>item.id===role);
    if(at<0)return {title:'New '+role,use:'Add as '+role};
    return {title:'Step '+(at+1)+' · '+(steps[at].kind==='rank'?'Rank':'Filter'),use:'Update step '+(at+1)};
  }
  return {restore,beginQueuedEdit,catalog,fields,read:()=>({revision,changed,detached:copy(detached)}),formula,describe,
    patch,edit,commitRange,move,remove,select,copySleeve,removeSleeve,rename:name=>{sleeves[current].name=name;},reset,view,flat,requireValues,complete:()=>!allSteps().some(empty),selection,prepareSubmission,touch,render};
})();
const restoreBacktestSettings=StrategyDraft.restore;

initializeFilters();
ScheduleView.init(()=>({mode:viewKey()==='custom'&&document.getElementById('date-testing').value==='random'?'random':viewKey(),scalar:!StrategyDraft.flat()}));
VariableWorkspace.init({draft:StrategyDraft});
setModeVisibility();
document.getElementById('mode-latest').addEventListener('click',()=>switchMode('latest'));
document.getElementById('mode-backtest').addEventListener('click',()=>switchMode('backtest'));
document.getElementById('download-latest').addEventListener('click',e=>{e.preventDefault();downloadLatest();});
// The form submits for Screen latest only. In Historical backtest mode a submit, such as Enter in a
// step field, starts nothing: a dated test starts from Add to queue.
document.getElementById('strategy-form').addEventListener('submit',e=>{e.preventDefault();if(screeningMode==='latest')applyRange();});
document.getElementById('reset-strategy').addEventListener('click',()=>{StrategyDraft.reset();settingsChanged();});
applyRange();

// A new step asks for its source first; it joins the strategy once chosen.
for(const kind of ['filter','rank'])document.getElementById('add-'+kind).addEventListener('click',()=>{
  pendingStep=kind;renderSteps();
  document.getElementById('filter-search-new').focus();
});
const stepList=document.getElementById('strategy-steps');
FilterPicker.bind(stepList,{choices:stepChoices,choose:chooseStep,opened:loadStepSources});
stepList.addEventListener('input',event=>{
  const target=event.target;
  if(target.dataset.key)StrategyDraft.edit(target.dataset.step,target.dataset.key,target.value);
});
stepList.addEventListener('change',event=>{
  const target=event.target;if(!target.dataset.key)return;
  StrategyDraft.edit(target.dataset.step,target.dataset.key,target.value);StrategyDraft.commitRange(target.dataset.step,target.dataset.key);settingsChanged();
});
stepList.addEventListener('click',event=>{
  const target=event.target.closest('button');if(!target)return;
  const {action,step}=target.dataset;
  stepMessage('');
  if(action==='cancel'){pendingStep=null;renderSteps();document.getElementById('add-filter').focus?.();return;}
  if(action==='edit'){void VariableWorkspace.open(step,StrategyDraft.formula(step));return;}
  if(action==='up'||action==='down'){movingStep=step;StrategyDraft.move(step,action==='up'?-1:1);settingsChanged();}
  if(action==='remove'){StrategyDraft.remove(step);settingsChanged();}
});

// Sleeve tabs. A redrawn tab row gives focus back to the active tab.
const focusSleeve=()=>document.querySelector('#sleeve-tabs [aria-pressed="true"]').focus();
document.getElementById('sleeve-tabs').addEventListener('click',event=>{const tab=event.target.closest('[data-sleeve]');if(tab){StrategyDraft.select(+tab.dataset.sleeve);focusSleeve();}});
document.getElementById('sleeve-copy').addEventListener('click',()=>{StrategyDraft.copySleeve();settingsChanged();});
document.getElementById('sleeve-remove').addEventListener('click',()=>{StrategyDraft.removeSleeve();settingsChanged();focusSleeve();});
document.getElementById('sleeve-name').addEventListener('input',event=>StrategyDraft.rename(event.target.value));

const autoRun=document.getElementById('auto-run');
autoRun.checked=true;
try{autoRun.checked=localStorage.getItem('backtest-auto-run')!=='false';}catch(_){}
autoRun.addEventListener('change',()=>{
  try{localStorage.setItem('backtest-auto-run',String(autoRun.checked));}catch(_){}
  settingsChanged();
});
document.getElementById('strategy-form').addEventListener('input',event=>{
  if(event.target.id!=='auto-run')settingsChanged(false);
});
document.getElementById('strategy-form').addEventListener('change',event=>{
  const id=event.target.id;
  if(id==='auto-run'||event.target.dataset.key)return;
  if(id==='stock-market'){selectMarket(selectedMarket());document.getElementById('stock-pool').value='cached';renderSteps();}
  settingsChanged();
});

RunMarkets.init();
SavedBacktests.init({open:restoreSavedBacktest,copy:copySavedBacktestSettings});
BacktestQueue.init({changed:Workspaces.queueStatus,libraryChanged:SavedBacktests.changed,beginEdit:StrategyDraft.beginQueuedEdit,prepareSubmission:StrategyDraft.prepareSubmission,catalog:sourceCatalog,presentation:scheduledPresentation,restore:restoreBacktestSettings,open:restoreSavedBacktest,
  showBuilder:()=>Workspaces.show('builder'),
  metricLabel:id=>sourceCatalog().metrics[id]?.label||id,filterLabel:id=>sourceCatalog().filters[id]?.label||id});
Workspaces.init();
