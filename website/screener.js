/* Pure selection engine shared by the browser and SQL parity tests. */
(function(root) {
  'use strict';
  const defaults = Object.freeze({first:1996,last:2025,rank_from:1,rank_to:50,pool:'legacy',metric:'ev_ebitda',min_cap:100e6,max_cap:null,min_ev:50e6,min_yield:0,max_multiple:null,sector:null,exchange:null,filters:null});
  function validate(options) {
    const o={...defaults,...options};
    for(const key of ['rank_from','rank_to']) if(!Number.isInteger(o[key])) throw Error('Years and ranks must be whole numbers.');
    if(o.rank_from<1 || o.rank_to<o.rank_from || o.rank_to>5000) throw Error('Choose increasing ranks between 1 and 5000.');
    if(!['legacy','cached'].includes(o.pool)) throw Error('Choose a valid stock universe.');
    for(const key of ['min_cap','max_cap','min_ev','min_yield','max_multiple']) {
      if(o[key]!==null && (!Number.isFinite(o[key]) || o[key]<0)) throw Error('Financial filters must be non-negative numbers.');
    }
    if(o.max_cap!==null && o.max_cap<o.min_cap) throw Error('Maximum market cap must be at least the minimum.');
    if(o.filters!==null && (!Array.isArray(o.filters) || o.filters.length>50))throw Error('Use a list of at most 50 filter conditions.');
    for(const c of o.filters??[]){
      if(!c || Object.keys(c).sort().join(',')!=='field,op,value' || typeof c.field!=='string' || !['lt','gt'].includes(c.op) || !Number.isFinite(c.value))throw Error('Each filter needs a metric, less than or more than, and a finite value.');
    }
    return o;
  }
  function median(values) {
    if(!values.length)return null;
    const a=values.slice().sort((a,b)=>a-b),i=Math.floor(a.length/2);
    return a.length%2?a[i]:(a[i-1]+a[i])/2;
  }
  function select(observations,o,dataset,mode) {
    if(!Object.hasOwn(dataset.metrics,o.metric))throw Error('Choose a valid ranking metric.');
    for(const c of o.filters??[])if(!dataset.filter_catalog?.[c.field]?.available)throw Error('Choose an available filter metric.');
    observations=observations.filter(h=>{
      const values=dataset.filter_values?.[mode+':'+o.pool+':'+(h.year??0)+':'+h.symbol]??{};
      return (o.filters??[]).every(c=>Number.isFinite(values[c.field]) && (c.op==='lt'?values[c.field]<c.value:values[c.field]>c.value));
    });
    observations=observations.map(h=>{
      const value=dataset.metric_values[mode+':'+o.pool+':'+(h.year??0)+':'+h.symbol]?.[o.metric];
      return value?{...h,metric_multiple:value[0],metric_yield:value[1]}:null;
    }).filter(h=>h!==null);
    const matches=observations.filter(h=>h.market_cap>=o.min_cap && h.enterprise_value>=o.min_ev && h.metric_yield>=o.min_yield && (o.max_cap===null || h.market_cap<=o.max_cap) && (o.max_multiple===null || h.metric_multiple<=o.max_multiple) && (o.sector===null || h.sector===o.sector) && (o.exchange===null || h.exchange===o.exchange));
    matches.sort((a,b)=>b.metric_yield-a.metric_yield || (a.candidate_rank??-Infinity)-(b.candidate_rank??-Infinity) || (a.symbol<b.symbol?-1:a.symbol>b.symbol?1:0));
    return {stocks:matches.slice(o.rank_from-1,o.rank_to).map((h,i)=>({...h,rank:o.rank_from+i})),matches:matches.length};
  }
  function screen(dataset, options) {
    const o=validate(options), groups={};
    if(!Number.isInteger(o.first) || !Number.isInteger(o.last) || o.first>o.last || o.first<1996 || o.last>2026) throw Error('Choose an increasing year range within 1996–2026.');
    for(let year=o.first;year<=o.last;year++) groups[year]=[];
    for(const row of dataset.pools[o.pool]) {
      const [year,symbol,candidate_rank,fiscal,entry,exit,market_cap,enterprise_value,ebitda_yield,ev_ebitda,return_value,status]=row;
      if(year<o.first || year>o.last)continue;
      const [name,exchange,sector]=dataset.companies[symbol];
      groups[year].push({year,symbol,candidate_rank,fiscal,entry,exit,market_cap,enterprise_value,ebitda_yield,ev_ebitda,return_value,status,name,exchange,sector});
    }
    const years=[];
    for(let year=o.first;year<=o.last;year++) {
      const {stocks:holdings}=select(groups[year],o,dataset,'historical');
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
  function latestScreen(dataset, options){
    const o=validate(options),matches=[];
    for(const row of dataset.latest[o.pool]){
      const [symbol,candidate_rank,fiscal,known,price_date,price,market_cap,enterprise_value,ebitda_yield,ev_ebitda,spread]=row;
      const [name,exchange,sector]=dataset.companies[symbol];
      matches.push({symbol,candidate_rank,fiscal,known,price_date,price,market_cap,enterprise_value,ebitda_yield,ev_ebitda,spread,name,exchange,sector});
    }
    const {stocks,matches:count}=select(matches,o,dataset,'latest');
    return {options:o,asof:dataset.latest.metadata.asof,stocks,matches:count,requested:o.rank_to-o.rank_from+1,median_market_cap:median(stocks.map(h=>h.market_cap)),median_yield:median(stocks.map(h=>h.metric_yield))};
  }
  const api={defaults,validate,median,screen,latestScreen};
  if(typeof module==='object' && module.exports)module.exports=api;
  root.StockScreener=api;
})(globalThis);
