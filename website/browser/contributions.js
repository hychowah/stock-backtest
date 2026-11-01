/* Equal-weight return attribution. This does not alter the stock-picking ranks. */
(function(root){
  'use strict';
  function analyze(holdings){
    const state=accumulator(holdings.length);
    holdings.forEach(state.add);holdings.forEach(state.other);return state.finish();
  }
  function accumulator(n){
    let top=[],gains=0,losses=0,net=0,other_total=0,otherGains=0,otherLosses=0;
    const order=(a,b)=>b.contribution-a.contribution||(a.symbol<b.symbol?-1:a.symbol>b.symbol?1:0);
    return {
      add(h){const row={...h,weight:1/n,contribution:h.return_value/n};gains+=Math.max(0,row.contribution);losses+=Math.max(0,-row.contribution);net+=row.contribution;top.push(row);top.sort(order);if(top.length>10)top.pop();},
      other(h){if(top.some(row=>row.symbol===h.symbol))return;const c=h.return_value/n;other_total+=c;otherGains+=Math.max(0,c);otherLosses+=Math.max(0,-c);},
      finish(){
        const slices=(sign,rest)=>{const rows=top.filter(h=>h.contribution*sign>0).map(h=>({label:h.symbol,value:h.contribution*sign,contribution:h.contribution,other:false}));if(rest>0)rows.push({label:sign>0?'Other gainers':'Other losers',value:rest,contribution:rest*sign,other:true});return rows;};
        return {count:n,top_count:top.length,top,gains,losses,net,top_total:top.reduce((s,h)=>s+h.contribution,0),other_total,gain_slices:slices(1,otherGains),loss_slices:slices(-1,otherLosses)};
      }
    };
  }
  // Two ordered passes preserve eager addition order without retaining all rows.
  async function analyzeStored(count,visit){
    const state=accumulator(count);
    await visit(state.add);await visit(state.other);return state.finish();
  }
  const api={analyze,analyzeStored};
  if(typeof module==='object' && module.exports)module.exports=api;
  root.ReturnContributions=api;
})(globalThis);
