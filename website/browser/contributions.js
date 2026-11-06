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
  const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pp=x=>(x>=0?'+':'')+(x*100).toFixed(2);
  // One gains (sign 1) or losses (sign -1) pie of an analyzed book. Shares are
  // normalized within the pie and never show negative slices.
  function pie(slices,total,sign){
    const colors=sign>0?['#20775e','#359671','#549e7b','#77b38f','#95c8a6','#16745b','#428b76','#66b6a0','#88c9b7','#b1dbc8']:['#ae4d40','#c96957','#db8a70','#e3a38d','#edc0ac'];
    let cursor=0;
    const parts=slices.map((slice,i)=>{
      const share=total>0?slice.value/total*100:0,color=slice.other?(sign>0?'#d8e3dc':'#e8cbc3'):colors[i%colors.length];
      const start=cursor;cursor+=share;
      return {...slice,share,color,gradient:color+' '+start+'% '+cursor+'%'};
    });
    const heading=sign>0?'Gains':'Losses';
    const description=total>0?heading+' contribution '+pp(total*sign)+' percentage points. '+parts.map(p=>p.label+': '+p.share.toFixed(1)+'% of '+heading.toLowerCase()).join('; '):'No '+heading.toLowerCase()+' in this book.';
    return `<figure><h4>${heading}</h4><div class="contribution-pie" role="img" aria-label="${escape(description)}" style="background:${parts.length?'conic-gradient('+parts.map(p=>p.gradient).join(',')+')':'#e5eae4'}"><div class="contribution-pie-center">${pp(total*sign)} pp<small>portfolio impact</small></div></div>${parts.length?'<ul class="contribution-legend">'+parts.map(p=>`<li><i style="background:${p.color}"></i>${escape(p.label)} · ${p.share.toFixed(1)}% · ${pp(p.contribution)} pp</li>`).join('')+'</ul>':'<p class="hint">No '+heading.toLowerCase()+' this year.</p>'}</figure>`;
  }
  const api={analyze,analyzeStored,pie};
  if(typeof module==='object' && module.exports)module.exports=api;
  root.ReturnContributions=api;
})(globalThis);
