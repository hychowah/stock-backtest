/* Pure selection engine shared by the browser and SQL parity tests. */
(function(root) {
  'use strict';
  const defaults = Object.freeze({first:1996,last:2025,rank_from:1,rank_to:50,pool:'legacy',min_cap:100e6,max_cap:null,min_ev:50e6,min_yield:0,max_multiple:null,sector:null,exchange:null});
  function validate(options) {
    const o={...defaults,...options};
    for(const key of ['first','last','rank_from','rank_to']) if(!Number.isInteger(o[key])) throw Error('Years and ranks must be whole numbers.');
    if(o.first>o.last || o.first<1996 || o.last>2026) throw Error('Choose an increasing year range within 1996–2026.');
    if(o.rank_from<1 || o.rank_to<o.rank_from || o.rank_to>5000) throw Error('Choose increasing ranks between 1 and 5000.');
    if(!['legacy','cached'].includes(o.pool)) throw Error('Choose a valid stock universe.');
    for(const key of ['min_cap','max_cap','min_ev','min_yield','max_multiple']) {
      if(o[key]!==null && (!Number.isFinite(o[key]) || o[key]<0)) throw Error('Financial filters must be non-negative numbers.');
    }
    if(o.max_cap!==null && o.max_cap<o.min_cap) throw Error('Maximum market cap must be at least the minimum.');
    return o;
  }
  function median(values) {
    if(!values.length)return null;
    const a=values.slice().sort((a,b)=>a-b),i=Math.floor(a.length/2);
    return a.length%2?a[i]:(a[i-1]+a[i])/2;
  }
  function screen(dataset, options) {
    const o=validate(options), groups={};
    for(let year=o.first;year<=o.last;year++) groups[year]=[];
    for(const row of dataset.pools[o.pool]) {
      const [year,symbol,candidate_rank,fiscal,entry,exit,market_cap,enterprise_value,ebitda_yield,ev_ebitda,return_value,status]=row;
      if(year<o.first || year>o.last || market_cap<o.min_cap || enterprise_value<o.min_ev || ebitda_yield<o.min_yield || (o.max_cap!==null && market_cap>o.max_cap) || (o.max_multiple!==null && ev_ebitda>o.max_multiple))continue;
      const [name,exchange,sector]=dataset.companies[symbol];
      if((o.sector && sector!==o.sector)||(o.exchange && exchange!==o.exchange))continue;
      groups[year].push({year,symbol,candidate_rank,fiscal,entry,exit,market_cap,enterprise_value,ebitda_yield,ev_ebitda,return_value,status,name,exchange,sector});
    }
    const years=[];
    for(let year=o.first;year<=o.last;year++) {
      groups[year].sort((a,b)=>b.ebitda_yield-a.ebitda_yield || (a.candidate_rank??-Infinity)-(b.candidate_rank??-Infinity) || (a.symbol<b.symbol?-1:a.symbol>b.symbol?1:0));
      const holdings=groups[year].slice(o.rank_from-1,o.rank_to).map((h,i)=>({...h,rank:o.rank_from+i}));
      years.push({year,holdings,names:holdings.length,portfolio:holdings.length?holdings.reduce((v,h)=>v+h.return_value,0)/holdings.length:null,spy:dataset.periods[year].spy,median_market_cap:median(holdings.map(h=>h.market_cap))});
    }
    const first=dataset.periods[o.first].entry,end=dataset.periods[o.last].exit;
    const duration=(Date.parse(end)-Date.parse(first))/(365.25*86400000);
    const complete=years.every(y=>y.names>0);
    const growth=complete?years.reduce((v,y)=>v*(1+y.portfolio),1):null;
    const spy_growth=years.reduce((v,y)=>v*(1+y.spy),1);
    const wanted=o.rank_to-o.rank_from+1;
    return {options:o,years,first,end,growth,spy_growth,cagr:complete?Math.pow(growth,1/duration)-1:null,spy_cagr:Math.pow(spy_growth,1/duration)-1,short_years:years.filter(y=>y.names<wanted).map(y=>y.year),empty_years:years.filter(y=>!y.names).map(y=>y.year)};
  }
  const api={defaults,validate,median,screen};
  if(typeof module==='object' && module.exports)module.exports=api;
  root.StockScreener=api;
})(globalThis);
