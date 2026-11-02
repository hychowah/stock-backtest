/* Bounded immutable result presentation for existing codec1 and scalar codec2.
   Every reply is fenced by acquired artifact and navigation generation. */
const EvidenceResults=(()=>{
  let bounded=null,explanationSequence=0;
  const node=id=>document.getElementById(id);
  const format=v=>v===null||v===undefined?'—':(v*100).toFixed(2)+'%';
  const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function chart(periods){
    const values=periods.flatMap(p=>[p.portfolio,p.spy]).filter(Number.isFinite);
    const low=Math.min(0,...values),high=Math.max(.1,...values),span=high-low||1;
    const y=v=>30+(high-v)/span*260,step=1100/periods.length;
    let html=`<line x1="60" x2="1160" y1="${y(0)}" y2="${y(0)}" stroke="#acb8c5"/>`;
    for(let i=0;i<=4;i++){const v=low+span*i/4;html+=`<text x="55" y="${y(v)+4}" text-anchor="end" font-size="11">${format(v)}</text>`;}
    periods.forEach((p,i)=>{
      const x=60+i*step,width=Math.max(.3,(step-2)/2);
      for(const [v,offset,color,label] of [[p.portfolio,0,'#20775e','Strategy'],[p.spy,width,'#acb8c5','SPY']]){
        if(v===null)continue;
        const text=escape(p.entry+' → '+p.exit+' · '+label+' '+format(v));
        html+=`<rect x="${x+offset}" y="${Math.min(y(0),y(v))}" width="${width}" height="${Math.max(1,Math.abs(y(v)-y(0)))}" fill="${color}" tabindex="0" aria-label="${text}"><title>${text}</title></rect>`;
      }
      if(i%Math.max(1,Math.ceil(periods.length/12))===0)html+=`<text x="${x}" y="315" font-size="10" transform="rotate(-35 ${x} 315)">${p.entry}</text>`;
    });
    node('schedule-chart').innerHTML=html;
  }
  function valid(state){return bounded===state&&ResultArtifacts.current(state.artifact);}
  function clearExplanation(){
    explanationSequence++;
    if(bounded){bounded.explanationRequested=false;bounded.explanationNext=null;}
    node('scalar-explanation').open=false;node('scalar-explanation-content').innerHTML='';
  }
  function readError(state,error){if(valid(state)&&error.name!=='AbortError')node('screen-error').textContent=error.message;}
  function navigation(id,cursor,next,total,label){
    node(id+'-pages').hidden=false;node(id+'-back').disabled=cursor===0;node(id+'-next').disabled=next===null;
    node(id+'-page').textContent=label+' · '+total+' total';
  }
  async function storedHoldings(state,cursor=0,firstPage=null){
    clearExplanation();
    const period=state.period,sequence=++state.holdingSequence;
    try{
      const page=await (firstPage??state.reader.holdings(state.trial,period,cursor));
      if(!valid(state)||state.period!==period||state.holdingSequence!==sequence)return;
      state.holdingCursor=page.cursor;state.holdingNext=page.next;
      const scalar=state.artifact.version===4;node('schedule-multiple-head').textContent=scalar?'Ranking value · '+(page.rows[0]?.ranking_unit??'')+' · '+(page.rows[0]?.ranking_direction??''):metricLabel(state.info.summary.options.metric??'ev_ebitda')+' (×)';
      node('schedule-explanation-head').hidden=!scalar;
      node('schedule-stock-body').innerHTML=page.rows.map(h=>'<tr>'+[h.rank,h.symbol,h.name,h.exchange,h.sector,(state.artifact.version===4?ResultArtifacts.scalarValue(h):h.metric_multiple.toFixed(2)),money(h.market_cap),money(h.enterprise_value),h.fiscal,h.entry,h.exit,format(h.return_value),h.contribution_pp.toFixed(2)+' pp',h.status].map(v=>'<td>'+escape(v)+'</td>').join('')+(scalar?'<td><button type="button" data-stored-explain="'+escape(h.symbol)+'">Explain</button></td>':'')+'</tr>').join('')||'<tr><td colspan="14">No matching stocks in this period.</td></tr>';
      state.rows=page.rows;
      node('schedule-stock-body').onclick=event=>{const symbol=event.target.dataset.storedExplain;if(symbol)void explain(state.rows.find(row=>row.symbol===symbol));};
      navigation('schedule-holdings',page.cursor,page.next,page.total,'Stocks '+(page.total?page.cursor+1:0)+'–'+(page.cursor+page.rows.length));
    }catch(error){if(state.period===period&&state.holdingSequence===sequence)readError(state,error);}
  }
  async function storedStocks(state){
    clearExplanation();
    const period=+node('schedule-period').value,sequence=++state.stockSequence;state.period=period;
    const selected=state.page.rows.find(row=>row.number===period);if(!selected)return;
    node('schedule-holdings-back').disabled=true;node('schedule-holdings-next').disabled=true;
    node('schedule-stock-body').innerHTML='';state.holdingCursor=0;state.holdingNext=null;
    node('schedule-attribution').textContent='Reading contributions from all selected stocks…';
    // One bounded first page serves this table and attribution operation.
    // Both attribution passes keep original order. Replacement fences every
    // response before consumption or publication; no prior period is retained.
    const firstPage=state.reader.holdings(state.trial,period,0);
    void storedHoldings(state,0,firstPage);
    try{
      const group=await ReturnContributions.analyzeStored(selected.value.names,async visit=>{
        let page=await firstPage;
        do{
          if(!valid(state)||state.period!==period||state.stockSequence!==sequence)throw Error('This period view was replaced.');
          page.rows.forEach(visit);
          if(page.next===null)break;
          page=await state.reader.holdings(state.trial,period,page.next);
        }while(true);
      });
      if(!valid(state)||state.period!==period||state.stockSequence!==sequence)return;
      node('schedule-attribution').innerHTML=group.count?'<h3>Top 10 contributors</h3><div class="contribution-pies">'+contributionPie(group.gain_slices,group.gains,1)+contributionPie(group.loss_slices,group.losses,-1)+'</div><p>Top '+group.top_count+' stocks: '+group.top.map(h=>escape(h.symbol)+' ('+h.contribution_pp.toFixed(2)+' pp)').join(', ')+'. Contributions use all '+group.count+' selected stocks; pies show gains and losses separately.</p>':'<p>No stocks to attribute.</p>';
    }catch(error){if(state.period===period&&state.stockSequence===sequence)readError(state,error);}
  }
  async function storedPeriods(state,cursor=0){
    clearExplanation();
    const sequence=++state.periodSequence;state.period=null;state.stockSequence++;
    node('schedule-period-back').disabled=true;node('schedule-period-next').disabled=true;
    node('schedule-holdings-back').disabled=true;node('schedule-holdings-next').disabled=true;
    try{
      const page=await state.reader.periods(state.trial,cursor);
      if(!valid(state)||state.periodSequence!==sequence)return;
      state.page=page;state.period=null;
      chart(page.rows.map(row=>row.value));
      node('schedule-rows').innerHTML=page.rows.map(({value:p})=>'<tr>'+[p.entry,p.exit,p.names,format(p.portfolio),format(p.spy)].map(v=>'<td>'+escape(v)+'</td>').join('')+'</tr>').join('');
      node('schedule-period').innerHTML=page.rows.map(({number,value:p})=>`<option value="${number}">${number}. ${p.entry} → ${p.exit} · ${p.names} stocks</option>`).join('');
      node('schedule-period').value=String(page.rows[0]?.number??'');
      navigation('schedule-period',page.cursor,page.next,page.total,'Chart and table: periods '+(page.total?page.cursor+1:0)+'–'+(page.cursor+page.rows.length));
      void storedStocks(state);
    }catch(error){if(state.periodSequence===sequence)readError(state,error);}
  }
  async function storedRender(artifact,trial){
    const state={artifact,trial,reader:ResultArtifacts.reader(artifact),periodSequence:0,holdingSequence:0,stockSequence:0};bounded=state;
    node('schedule-results').hidden=false;node('schedule-rows').innerHTML='';node('schedule-stock-body').innerHTML='';node('schedule-chart').innerHTML='';node('schedule-period').innerHTML='';node('schedule-attribution').textContent='Reading stored evidence…';
    try{
      state.info=await state.reader.trial(trial);if(!valid(state))return;
      const r=state.info.summary;
      node('schedule-dates').textContent=r.start+' → '+r.end+' · '+(artifact.kind==='january'?'January books':CalendarSettings.label(r));
      node('schedule-cagr').textContent=format(r.cagr);node('schedule-spy-cagr').textContent=format(r.spy_cagr);
      node('schedule-growth').textContent=r.growth===null?'—':'$'+r.growth.toFixed(2);
      node('schedule-coverage').textContent=r.coverage+' '+state.info.short+' short periods; '+state.info.empty+' empty periods. '+(state.info.empty?'Full-period strategy growth and CAGR unavailable. ':'')+'Computed in '+r.seconds.toFixed(2)+'s; repeated periods reuse prepared books.'+(r.cash_days?' Both strategy and paired SPY hold cash until '+r.first_trade+' ('+r.cash_days+' days); CAGR uses the common window.':'');
      await storedPeriods(state);
    }catch(error){readError(state,error);}
  }
  async function screenPage(state,cursor=0){
    clearExplanation();
    const sequence=++state.stockSequence;
    try{
      const page=await state.reader.screen(cursor);if(!valid(state)||sequence!==state.stockSequence)return;
      state.holdingCursor=page.cursor;state.holdingNext=page.next;
      node('scalar-screen-rows').innerHTML=page.rows.map((row,index)=>'<tr>'+[row.rank,row.symbol,row.name,ResultArtifacts.scalarValue(row),row.ranking_unit,row.ranking_direction].map(v=>'<td>'+escape(v)+'</td>').join('')+'<td><button type="button" data-scalar-explain="'+index+'">Explain '+escape(row.symbol)+'</button></td></tr>').join('')||'<tr><td colspan="7">No matching stocks. Missing ranking values cannot be selected.</td></tr>';
      state.rows=page.rows;node('scalar-screen-page').textContent=(page.total?page.cursor+1:0)+'–'+(page.cursor+page.rows.length)+' of '+page.total;
      node('scalar-screen-back').disabled=page.cursor===0;node('scalar-screen-next').disabled=page.next===null;
    }catch(error){readError(state,error);}
  }
  async function explain(row=null){
    const state=bounded,sequence=++explanationSequence;if(!state||state.artifact.version!==4)return;
    const target=node('scalar-explanation-content');state.explanationRequested=true;node('scalar-explanation').open=true;target.textContent='Reading original explanations…';
    try{
      const scope=row?.scalar_evidence?.scope,chunks=new Set(Object.values(row?.scalar_evidence?.lanes||{}).filter(ref=>ref.chunk!==undefined).map(ref=>ref.chunk));let cursor=0,found=[];
      do{
        const page=await state.reader.explanations(cursor);if(!valid(state)||sequence!==explanationSequence)return;
        for(const record of page.rows)if((!scope||record.scope===scope)&&(!chunks.size||record.block&&chunks.has(record.chunk)))found.push(record);
        // Keep only one bounded explanation page at a time. Navigation reaches
        // the complete immutable evidence; download retains the full graph.
        if((chunks.size?[...chunks].every(chunk=>found.some(record=>record.chunk===chunk)):found.length)||page.next===null){state.explanationNext=page.next;state.explanationScope=scope;state.explanationRow=row;break;}
        cursor=page.next;
      }while(true);
      if(!valid(state)||sequence!==explanationSequence)return;
      const labels=state.artifact.settings.strategy.variables?.presentation||[];
      target.innerHTML='<p>'+escape(labels.map(v=>v.name+' @ '+v.revision).join('; '))+'</p>'+VariableEvidence.records(found,row,state.artifact.settings.strategy);
      if(state.explanationNext!==null)target.innerHTML+='<button type="button" id="scalar-explanation-next">Next explanation page</button>';
      node('scalar-explanation-next')?.addEventListener('click',()=>void nextExplanation(state));
    }catch(error){if(sequence===explanationSequence)readError(state,error);}
  }
  async function nextExplanation(state){
    const sequence=++explanationSequence;
    try{const page=await state.reader.explanations(state.explanationNext);if(!valid(state)||sequence!==explanationSequence)return;state.explanationNext=page.next;node('scalar-explanation-content').innerHTML=VariableEvidence.records(page.rows,state.explanationRow,state.artifact.settings.strategy)+(page.next===null?'':'<button type="button" id="scalar-explanation-next">Next explanation page</button>');node('scalar-explanation-next')?.addEventListener('click',()=>void nextExplanation(state));}catch(error){if(sequence===explanationSequence)readError(state,error);}
  }
  function show(artifact,trial=1){
    explanationSequence++;node('scalar-evidence-view').hidden=artifact.version!==4;node('scalar-explanation').open=false;
    if(artifact.version===4){
      node('scalar-evidence-heading').textContent=artifact.kind==='latest'?'Latest variable screen':artifact.kind==='january'?'January variable backtest':'Variable backtest';
      const strategy=artifact.settings.strategy,ranking=strategy.selection.ranking.source;
      const name=ranking.kind==='builtin'?strategy.builtins.find(item=>item.id===ranking.id)?.label:strategy.variables.presentation.find(item=>item.variable_id===ranking.variable_id&&item.revision===ranking.revision)?.name;
      node('scalar-evidence-summary').textContent=name+' · '+strategy.selection.ranking.direction+' first · ranks '+strategy.selection.rank_from+'–'+strategy.selection.rank_to+' · '+strategy.selection.selection_order+'. These values and downloads use original captured evidence.';
    }
    node('scalar-screen-results').hidden=artifact.kind!=='latest';node('scalar-download-returns').hidden=artifact.kind==='latest';
    if(artifact.kind==='latest'){
      const state={artifact,trial:0,reader:ResultArtifacts.reader(artifact),stockSequence:0};bounded=state;
      node('latest-view').hidden=true;node('custom-view').hidden=true;void screenPage(state);
    }else{node('custom-view').hidden=false;if(artifact.kind==='january')node('backtest-view').hidden=true;void storedRender(artifact,trial);}
  }
  function init(){
    node('schedule-period-back').addEventListener('click',()=>{if(bounded?.page)void storedPeriods(bounded,Math.max(0,bounded.page.cursor-64));});
    node('schedule-period-next').addEventListener('click',()=>{if(bounded?.page&&bounded.page.next!==null)void storedPeriods(bounded,bounded.page.next);});
    node('schedule-holdings-back').addEventListener('click',()=>{if(bounded)void storedHoldings(bounded,Math.max(0,bounded.holdingCursor-64));});
    node('schedule-holdings-next').addEventListener('click',()=>{if(bounded&&bounded.holdingNext!==null)void storedHoldings(bounded,bounded.holdingNext);});
    node('scalar-screen-back')?.addEventListener('click',()=>{if(bounded)void screenPage(bounded,Math.max(0,bounded.holdingCursor-64));});
    node('scalar-screen-next')?.addEventListener('click',()=>{if(bounded&&bounded.holdingNext!==null)void screenPage(bounded,bounded.holdingNext);});
    node('scalar-screen-rows')?.addEventListener('click',event=>{const index=event.target.dataset.scalarExplain;if(index!==undefined)void explain(bounded.rows[+index]);});
    node('scalar-explanation')?.addEventListener('toggle',()=>{if(!bounded)return;if(node('scalar-explanation').open){if(!bounded.explanationRequested)void explain();}else{bounded.explanationRequested=false;explanationSequence++;}});
    for(const [id,kind] of [['scalar-download-rows',null],['scalar-download-returns','returns'],['scalar-download-evidence','evidence']])node(id)?.addEventListener('click',()=>{if(bounded)bounded.reader.download(kind||(bounded.artifact.kind==='latest'?'screen':'holdings'),bounded.trial||1);});
  }
  return {show,init,chart,stocks:()=>{if(!bounded?.page||!valid(bounded))return false;void storedStocks(bounded);return true;},clear:()=>{clearExplanation();bounded=null;if(node('scalar-evidence-view'))node('scalar-evidence-view').hidden=true;},download:(kind,trial)=>{if(!bounded||!valid(bounded))return false;bounded.reader.download(kind,trial??bounded.trial);return true;}};
})();
