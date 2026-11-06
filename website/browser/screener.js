/* Pure latest-screen selection engine shared by the browser and SQL parity tests. */
(function(root) {
  'use strict';
  const defaults = Object.freeze({rank_from:1,rank_to:50,pool:'legacy',metric:'ev_ebitda',min_cap:100e6,max_cap:null,min_ev:50e6,min_yield:0,max_multiple:null,sector:null,exchange:null,filters:null,selection_order:'filter_first'});
  function validate(options) {
    const o={...defaults,...options};
    for(const key of ['rank_from','rank_to']) if(!Number.isInteger(o[key])) throw Error('Ranks must be whole numbers.');
    if(o.rank_from<1 || o.rank_to<o.rank_from || o.rank_to>5000) throw Error('Choose increasing ranks between 1 and 5000.');
    if(!['filter_first','rank_first'].includes(o.selection_order))throw Error('Choose filter first or rank first.');
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
  // Scalar lanes have no formula, unit conversion, return or reciprocal logic.
  // Source adapters validate their inputs. Legacy populations have no callable
  // formula candidate ceiling; all user conditions move together as one stage.
  function selectValues(candidates,specification) {
    const {ranking,rank_from,rank_to,selection_order,conditions}=specification;
    if(!['highest','lowest'].includes(ranking.direction))throw Error('Choose highest or lowest.');
    const passes=row=>conditions.every(c=>{
      const value=row.values[c.lane];
      if(!['lt','gt','le','ge','eq'].includes(c.op))throw Error('Choose a valid scalar comparison.');
      if(c.op==='eq')return value===c.value;
      if(!Number.isFinite(value))return false;
      return c.op==='lt'?value<c.value:c.op==='gt'?value>c.value:c.op==='le'?value<=c.value:value>=c.value;
    });
    let matches=candidates.map((row,index)=>({row,index,value:row.values[ranking.lane]})).filter(item=>Number.isFinite(item.value));
    if(selection_order==='filter_first')matches=matches.filter(item=>passes(item.row));
    const compare=(a,b)=>a<b?-1:a>b?1:0;
    matches.sort((a,b)=>{
      const value=compare(a.value,b.value)*(ranking.direction==='highest'?-1:1);
      const ar=a.row.candidate_rank,br=b.row.candidate_rank;
      return value || (ar===null||ar===undefined?br===null||br===undefined?0:-1:br===null||br===undefined?1:compare(ar,br)) || compare(a.row.symbol,b.row.symbol);
    });
    let selected=matches.slice(rank_from-1,rank_to).map((item,index)=>({index:item.index,rank:rank_from+index,value:item.value}));
    if(selection_order==='rank_first')selected=selected.filter(item=>passes(candidates[item.index]));
    return {selected,matches:selection_order==='rank_first'?selected.length:matches.length};
  }
  function legacySpecification(o) {
    const conditions=[{lane:'market_cap',op:'ge',value:o.min_cap},{lane:'enterprise_value',op:'ge',value:o.min_ev},{lane:'metric_yield',op:'ge',value:o.min_yield}];
    for(const [lane,op,value] of [['market_cap','le',o.max_cap],['metric_multiple','le',o.max_multiple],['sector','eq',o.sector],['exchange','eq',o.exchange]])if(value!==null)conditions.push({lane,op,value});
    for(const c of o.filters??[])conditions.push({lane:'filter.'+c.field,op:c.op,value:c.value});
    return {ranking:{lane:'metric_yield',direction:'highest'},rank_from:o.rank_from,rank_to:o.rank_to,selection_order:o.selection_order,conditions};
  }
  function select(observations,o,dataset) {
    if(!Object.hasOwn(dataset.metrics,o.metric))throw Error('Choose a valid ranking metric.');
    for(const c of o.filters??[])if(!dataset.filter_catalog?.[c.field]?.available)throw Error('Choose an available filter metric.');
    observations=observations.map(h=>{
      const value=dataset.metric_values['latest:'+o.pool+':0:'+h.symbol]?.[o.metric];
      return value?{...h,metric_multiple:value[0],metric_yield:value[1]}:null;
    }).filter(h=>h!==null);
    const candidates=observations.map(h=>({symbol:h.symbol,candidate_rank:h.candidate_rank,values:{...h,
      ...Object.fromEntries(Object.entries(dataset.filter_values?.['latest:'+o.pool+':0:'+h.symbol]??{}).map(([field,value])=>['filter.'+field,value]))}}));
    const result=selectValues(candidates,legacySpecification(o));
    return {stocks:result.selected.map(item=>({...observations[item.index],rank:item.rank})),matches:result.matches};
  }
  function latestScreen(dataset, options){
    const o=validate(options),matches=[];
    for(const row of dataset.latest[o.pool]){
      const [symbol,candidate_rank,fiscal,known,price_date,price,market_cap,enterprise_value,ebitda_yield,ev_ebitda,spread]=row;
      const [name,exchange,sector]=dataset.companies[symbol];
      matches.push({symbol,candidate_rank,fiscal,known,price_date,price,market_cap,enterprise_value,ebitda_yield,ev_ebitda,spread,name,exchange,sector});
    }
    const {stocks,matches:count}=select(matches,o,dataset);
    return {options:o,asof:dataset.latest.metadata.asof,stocks,matches:count,requested:o.rank_to-o.rank_from+1,median_market_cap:median(stocks.map(h=>h.market_cap)),median_yield:median(stocks.map(h=>h.metric_yield))};
  }
  function selectionDescription(options={}) {
    const ranks=`Ranks ${options.rank_from??defaults.rank_from}–${options.rank_to??defaults.rank_to}`;
    return options.selection_order==='rank_first'?ranks+' selected before filters. No replacements; original ranks retained. Equal weight across passing stocks.':ranks+' after filtering, equal weight.';
  }
  const api={defaults,validate,median,latestScreen,selectionDescription,selectValues};
  if(typeof module==='object' && module.exports)module.exports=api;
  root.StockScreener=api;
})(globalThis);
