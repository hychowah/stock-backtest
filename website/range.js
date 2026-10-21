const allReturns=data.slice();
const screeningData=JSON.parse(document.getElementById('screening-data').textContent);
const rankFrom=document.getElementById('rank-from'),rankTo=document.getElementById('rank-to');
const fromYear=document.getElementById('from-year'),toYear=document.getElementById('to-year');
const fields={pool:'stock-pool',min_cap:'min-cap',max_cap:'max-cap',min_ev:'min-ev',min_yield:'min-yield',max_multiple:'max-multiple',sector:'sector-filter',exchange:'exchange-filter'};
let currentScreen=null;
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
    if(['pool','sector','exchange'].includes(key))o[key]=text||null;
    else{
      if(!text && ['min_cap','min_ev','min_yield'].includes(key))throw Error('Fill in each minimum, or enter 0.');
      o[key]=text===''?null:Number(text)*(key==='min_cap'||key==='max_cap'||key==='min_ev'?1e6:key==='min_yield'?.01:1);
    }
  }
  return o;
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
function renderStockTable(year){
  const stocks=selectedHoldings(year);
  document.getElementById('holding-body-'+year).innerHTML=stocks.map(h=>{
    const vals=[h.rank,h.symbol,h.name,h.exchange,h.sector,(h.ebitda_yield*100).toFixed(2)+'%',h.ev_ebitda.toFixed(2)+'×',money(h.market_cap),money(h.enterprise_value),h.fiscal,h.entry,h.exit,pct(h.return_value),h.status];
    return `<tr>${vals.map(v=>'<td>'+safe(v)+'</td>').join('')}</tr>`;
  }).join('')||'<tr><td colspan="14">No stocks match these filters.</td></tr>';
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
function applyRange(changed){
  if(+fromYear.value>+toYear.value){if(changed==='from')toYear.value=fromYear.value;else fromYear.value=toYear.value;}
  if(+rankFrom.value>+rankTo.value && ['rank-from','rank-to'].includes(changed)){
    if(changed==='rank-from')rankTo.value=rankFrom.value;else rankFrom.value=rankTo.value;
  }
  try{
    const next=StockScreener.screen(screeningData,readOptions());
    currentScreen=next;
  }catch(error){document.getElementById('screen-error').textContent=error.message+' The previous result remains displayed.';return;}
  document.getElementById('screen-error').textContent='';
  data=currentScreen.years.map(y=>({year:y.year,portfolio:y.portfolio,spy:y.spy,names:y.names}));
  const {first,last,rank_from,rank_to}=currentScreen.options;
  document.getElementById('strategy-legend').textContent=`EBITDA/EV ranks ${rank_from}–${rank_to}`;
  draw();drawMarketCaps();
  document.getElementById('rows').innerHTML=data.map(d=>`<tr><td>${d.year}${d.year===2026?'*':''}</td><td>${d.names}</td><td class="${d.portfolio>=0?'positive':'negative'}">${d.portfolio===null?'—':pct(d.portfolio)}</td><td class="${d.spy>=0?'positive':'negative'}">${pct(d.spy)}</td><td>${d.portfolio===null?'—':pp(d.portfolio-d.spy)}</td></tr>`).join('');
  const active=document.getElementById('holding-year').value;
  document.querySelectorAll('.holding-years details').forEach(el=>{
    const year=+el.id.replace('holdings-',''),stocks=selectedHoldings(year);
    el.hidden=year<first||year>last;
    if(el.hidden)el.open=false;
    document.getElementById('holding-summary-'+year).textContent=`${year} · ${stocks.length} stocks · Ranks ${rank_from}–${rank_to} · Median market cap ${money(medianMarketCap(year))}`;
    document.getElementById('holding-body-'+year).innerHTML='';
    if(el.open)renderStockTable(year);
  });
  document.getElementById('holding-year').innerHTML='<option value="">Choose year…</option>'+data.map(d=>`<option value="${d.year}">${d.year}</option>`).join('');
  if(active && +active>=first && +active<=last)document.getElementById('holding-year').value=active;
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
function downloadSelection(kind){
  if(!currentScreen)return;
  let rows;
  if(kind==='holdings'){
    const keys=['year','rank','symbol','name','exchange','sector','market_cap','enterprise_value','ebitda_yield','ev_ebitda','fiscal','entry','exit','return_value','status'];
    rows=[keys,...currentScreen.years.flatMap(y=>y.holdings.map(h=>keys.map(k=>h[k])))];
  }else rows=[['year','names','portfolio','spy','median_market_cap'],...currentScreen.years.map(y=>[y.year,y.names,y.portfolio??'',y.spy,y.median_market_cap??''])];
  const csv=rows.map(row=>row.map(v=>'"'+String(v??'').replace(/"/g,'""')+'"').join(',')).join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download=kind+'-'+currentScreen.options.first+'-'+currentScreen.options.last+'.csv';a.click();URL.revokeObjectURL(url);
}
initializeFilters();
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
