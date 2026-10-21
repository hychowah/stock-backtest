const allReturns = data.slice();
const rankFrom = document.getElementById('rank-from');
const rankTo = document.getElementById('rank-to');
rankFrom.value='1';rankTo.value='50';
function selectedHoldings(year) {
  return holdingsData[year].holdings.filter(h=>h.rank>=+rankFrom.value && h.rank<=+rankTo.value);
}
function medianMarketCap(year) {
  const caps=selectedHoldings(year).map(h=>h.market_cap).sort((a,b)=>a-b), n=caps.length;
  return n%2?caps[(n-1)/2]:(caps[n/2-1]+caps[n/2])/2;
}
const fromYear = document.getElementById('from-year');
const toYear = document.getElementById('to-year');
const rangeOptions = allReturns.map(d => `<option value="${d.year}">${d.year}${d.year===2026?' (partial)':''}</option>`).join('');
fromYear.innerHTML = toYear.innerHTML = rangeOptions;
fromYear.value = '1996';
toYear.value = '2025';

function selectedPerformance(selected, key) {
  const growth = selected.reduce((v, d) => v * (1+d[key]), 1);
  const first = holdingsData[selected[0].year].holdings.map(h=>h.entry).sort()[0];
  const lastYear = selected[selected.length-1].year;
  const end = bookExits[lastYear];
  const years = (Date.parse(end)-Date.parse(first))/(365.25*86400000);
  return {growth, cagr: Math.pow(growth,1/years)-1, first, end};
}
function drawMarketCaps() {
  const max = Math.max(1, Math.ceil(Math.max(...data.map(d=>medianMarketCap(d.year)))/1e9));
  const y = v=>330-v/1e9/max*290;
  const step = 1120/data.length;
  let markup = '';
  for (let i=0;i<=4;i++) {
    const tick=max*i/4, pos=y(tick*1e9);
    markup+=`<line x1="60" x2="1180" y1="${pos}" y2="${pos}" stroke="#e5eae4"/><text x="48" y="${pos+4}" text-anchor="end" font-size="11">$${tick}bn</text>`;
  }
  data.forEach((d,i)=>{
    const v=medianMarketCap(d.year),x=60+i*step+5;
    markup+=`<rect x="${x}" y="${y(v)}" width="${step-10}" height="${330-y(v)}" fill="#20775e"><title>${d.year}: $${(v/1e6).toFixed(1)}m median market cap</title></rect><text transform="translate(${x+step/2-5},353) rotate(-55)" text-anchor="end" font-size="11">${d.year}</text>`;
  });
  document.getElementById('market-cap-chart').innerHTML=markup;
}
function applyRange(changed) {
  if (+fromYear.value > +toYear.value) {
    if (changed==='from') toYear.value=fromYear.value;
    else fromYear.value=toYear.value;
  }
  if (+rankFrom.value > +rankTo.value) {
    if (changed==='rank-from') rankTo.value=rankFrom.value;
    else rankFrom.value=rankTo.value;
  }
  const start=+fromYear.value, end=+toYear.value;
  data=allReturns.filter(d=>d.year>=start && d.year<=end).map(d=>{
    const stocks=selectedHoldings(d.year);
    return {...d, portfolio:stocks.reduce((total,h)=>total+h.return_value,0)/stocks.length};
  });
  document.getElementById('strategy-legend').textContent=`EBITDA/EV ranks ${rankFrom.value}–${rankTo.value}`;
  draw();
  drawMarketCaps();
  document.getElementById('rows').innerHTML=data.map(d=>`<tr><td>${d.year}${d.year===2026?'*':''}</td><td class="${d.portfolio>=0?'positive':'negative'}">${pct(d.portfolio)}</td><td class="${d.spy>=0?'positive':'negative'}">${pct(d.spy)}</td><td class="${d.portfolio>=d.spy?'positive':'negative'}">${pp(d.portfolio-d.spy)}</td></tr>`).join('');
  document.querySelectorAll('.holding-years details').forEach(el=>{
    const year=+el.id.replace('holdings-','');
    el.hidden=year<start || year>end;
    if(el.hidden)el.open=false;
    const stocks=selectedHoldings(year);
    document.getElementById('holding-summary-'+year).textContent=`${year} · ${stocks.length} stocks · Ranks ${rankFrom.value}–${rankTo.value} · Median market cap $${(medianMarketCap(year)/1e6).toFixed(1)}m`;
    holdingsData[year].holdings.forEach(h=>{
      document.getElementById(`stock-${year}-${h.rank}`).hidden=h.rank<+rankFrom.value || h.rank>+rankTo.value;
    });
  });
  document.getElementById('holding-year').innerHTML='<option value="">Choose year…</option>'+data.map(d=>`<option value="${d.year}">${d.year}</option>`).join('');
  const strategy=selectedPerformance(data,'portfolio'), spy=selectedPerformance(data,'spy');
  const stats=document.querySelectorAll('.stat strong');
  stats[0].textContent=(strategy.cagr*100).toFixed(2)+'%';
  stats[1].textContent=(spy.cagr*100).toFixed(2)+'%';
  stats[2].textContent='$'+strategy.growth.toFixed(2);
  const notes=document.querySelectorAll('.stat small');
  notes[0].textContent=strategy.first+' → '+strategy.end;
  notes[1].textContent='Same selected holding periods';
  notes[2].textContent='Strategy · SPY $'+spy.growth.toFixed(2);
  document.getElementById('range-note').textContent=`${start}–${end} books, inclusive · ${strategy.first} to ${strategy.end}${end===2026?' · 2026 is partial':''}. Ranks ${rankFrom.value}–${rankTo.value} inclusive, ${selectedHoldings(start).length} stocks per year, equal weight. Strategy statistics use the selected stocks’ cached returns. CSV downloads contain all ranks and years.`;
  document.getElementById('detail').textContent='Hover over or focus a bar to see its return.';
  document.querySelector('.pill').textContent=`${start} — ${end}${end===2026?'*':''}`;
}
fromYear.addEventListener('change',()=>applyRange('from'));
toYear.addEventListener('change',()=>applyRange('to'));
document.getElementById('reset-range').addEventListener('click',()=>{fromYear.value='1996';toYear.value='2025';applyRange();});
applyRange();

rankFrom.addEventListener('change',()=>applyRange('rank-from'));
rankTo.addEventListener('change',()=>applyRange('rank-to'));
document.getElementById('reset-ranks').addEventListener('click',()=>{rankFrom.value='1';rankTo.value='50';applyRange();});
