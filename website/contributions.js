/* Equal-weight return attribution. This does not alter the stock-picking ranks. */
(function(root){
  'use strict';
  function analyze(holdings){
    const n=holdings.length;
    if(!n)return {count:0,top_count:0,top:[],gains:0,losses:0,net:0,top_total:0,other_total:0,gain_slices:[],loss_slices:[]};
    const rows=holdings.map(h=>({...h,weight:1/n,contribution:h.return_value/n}));
    const sorted=rows.slice().sort((a,b)=>b.contribution-a.contribution || (a.symbol<b.symbol?-1:a.symbol>b.symbol?1:0));
    const top=sorted.slice(0,10),chosen=new Set(top.map(h=>h.symbol));
    const gains=rows.reduce((s,h)=>s+Math.max(0,h.contribution),0);
    const losses=rows.reduce((s,h)=>s+Math.max(0,-h.contribution),0);
    const net=rows.reduce((s,h)=>s+h.contribution,0);
    const top_total=top.reduce((s,h)=>s+h.contribution,0);
    function slices(sign){
      const result=top.filter(h=>h.contribution*sign>0).map(h=>({label:h.symbol,value:h.contribution*sign,contribution:h.contribution,other:false}));
      const rest=rows.filter(h=>!chosen.has(h.symbol)).reduce((s,h)=>s+Math.max(0,h.contribution*sign),0);
      if(rest>0)result.push({label:sign>0?'Other gainers':'Other losers',value:rest,contribution:rest*sign,other:true});
      return result;
    }
    return {count:n,top_count:top.length,top,gains,losses,net,top_total,other_total:rows.filter(h=>!chosen.has(h.symbol)).reduce((s,h)=>s+h.contribution,0),gain_slices:slices(1),loss_slices:slices(-1)};
  }
  const api={analyze};
  if(typeof module==='object' && module.exports)module.exports=api;
  root.ReturnContributions=api;
})(globalThis);
