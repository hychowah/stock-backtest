/* Readable views of detached evaluator/provider evidence. No calculation,
   library or catalog access. Qualification always stays inside one chunk. */
const VariableEvidence=(()=>{
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const reason=code=>({ROOT_NOT_ADMITTED:'Company was not admitted to this prepared sample',NO_ELIGIBLE_REPORT:'No eligible annual report',MISSING_INPUT:'Required input is unavailable',MISSING_ANNUAL_MEMBER:'A consecutive annual observation is unavailable',FUTURE_DATE:'Observation date is after the requested screen date',DIVISION_BY_ZERO:'Division by zero',NONFINITE_RESULT:'Arithmetic result is not finite'}[code]||String(code||'Unavailable').replaceAll('_',' ').toLowerCase())+(code?' ('+code+')':'');
  function value(number,unit,display){return ResultArtifacts.scalarValue({ranking_value:number,ranking_unit:unit,ranking_display:display||'number'});}
  function trace(block,result){
    const operations=new Map(block.operations.map(item=>[item.id,item])),nodes=new Map(block.program.nodes.map(item=>[item.id,item])),observations=new Map(block.observations.results.map(item=>[item.id,item]));
    const ordered=[],visited=new Set();
    function visit(id){if(visited.has(id))return;visited.add(id);const item=operations.get(id);if(!item)return;item.operands.forEach(visit);ordered.push(item);}
    visit(result.evidence.operation);
    const inputs=[],steps=[];
    for(const item of ordered){
      const node=nodes.get(item.node),observation=observations.get(item.observation),context=block.observations.contexts.find(c=>c.id===item.context);
      if(observation){
        if(!observation.members.length)inputs.push(observation.parameter+' at '+context.date+': '+reason(observation.reason));
        for(const member of observation.members)inputs.push(observation.parameter+' at '+context.date+' · fiscal '+(member.fiscal_date||'unavailable')+' · available '+(member.evidence?.known_date||observation.anchor_report?.known||'unavailable')+' · '+(member.valid?value(member.value,observation.unit):reason(member.reason||observation.reason)));
      }
      const title={add:'Add',sub:'Subtract',mul:'Multiply',div:'Divide',neg:'Negate',annual:'Annual '+(node?.stat||'statistic'),at:'Use earlier dated value',lookback:'Use month lookback',ref:'Use exact saved reference',parameter:'Read parameter',constant:'Use constant'}[item.operation]||item.operation;
      steps.push(title+' · '+item.inputs.map(input=>value(input,'scalar')).join(', ')+' → '+(item.valid?value(item.value,node?.unit)+' '+(node?.unit||''):reason(item.reason))+' · '+item.path);
    }
    return {inputs:[...new Set(inputs)],steps:steps.slice(0,256),truncated:steps.length>256};
  }
  function sample(block,result,label=''){
    const requested=block.requests[result.request],admission=block.observations.roots.find(root=>root.root===result.root),details=trace(block,result);
    return {symbol:requested.symbol,date:requested.date,label,value:result.valid?value(result.value,result.unit,result.display):'Unavailable',unit:result.unit,status:result.valid?'Available':reason(admission&&!admission.admitted?admission.reason:result.reason),...details};
  }
  function table(samples,caption=''){
    return (caption?'<p>'+esc(caption)+'</p>':'')+'<div class="variable-evidence-samples" aria-label="Captured variable values">'+samples.map(item=>'<article class="variable-evidence-sample"><h4>'+esc(item.symbol+' · '+item.date+(item.label?' · '+item.label:''))+'</h4><dl><div><dt>Value</dt><dd>'+esc(item.value)+'</dd></div><div><dt>Unit</dt><dd>'+esc(item.unit)+'</dd></div><div><dt>Availability</dt><dd>'+esc(item.status)+'</dd></div></dl><p>Original inputs and dates:</p>'+(item.inputs.length?'<ul>'+item.inputs.map(text=>'<li>'+esc(text)+'</li>').join('')+'</ul>':'<p>No financial parameter inputs in this expression.</p>')+'<details><summary>Recorded calculation steps</summary><ol>'+item.steps.map(text=>'<li>'+esc(text)+'</li>').join('')+'</ol>'+(item.truncated?'<p>More steps are retained in complete evidence.</p>':'')+'</details></article>').join('')+'</div>';
  }
  function preview(response){
    const samples=response.evaluations.flatMap(block=>block.results.map(result=>sample(block,result)));
    return '<p>'+esc(response.producer?.label||'Original reference sample preview')+'</p>'+table(samples,samples.filter(item=>item.status==='Available').length+' of '+response.requested.length+' requested samples available. Availability among these requested samples only; this is not complete-pool coverage.')+'<details><summary>Advanced · complete preview JSON</summary><pre>'+esc(JSON.stringify(response,null,2))+'</pre></details>';
  }
  function records(records,row,strategy){
    const labels=new Map((strategy.variables?.presentation||[]).map(item=>[item.variable_id+'@'+item.revision,item.name])),samples=[],stored=[];
    if(row){
      for(const [lane,ref] of Object.entries(row.scalar_evidence?.lanes||{})){
        const label=lane==='ranking'?'Ranking':'Filter '+(Number(lane.slice(1))+1);
        if(ref.source){
          const descriptor=strategy.builtins.find(item=>item.id===ref.source.id);
          stored.push(label+' · '+(descriptor?.label||ref.source.id)+' · '+(ref.valid?value(ref.canonical,ref.unit,descriptor?.display):reason(ref.reason))+' · original stored value '+String(ref.stored)+' · '+ref.unit);
        }else for(const record of records){
          if(record.scope!==ref.scope||record.chunk!==ref.chunk||!record.block)continue;
          const result=record.block.results.find(item=>item.request===ref.request&&item.variable_id===ref.variable_id&&item.revision===ref.revision&&item.evidence.operation===ref.evidence.operation);
          if(result)samples.push(sample(record.block,result,label+' · '+(labels.get(result.variable_id+'@'+result.revision)||result.variable_id)));
        }
      }
    }else for(const record of records)if(record.block)for(const result of record.block.results){if(samples.length===16)break;samples.push(sample(record.block,result,labels.get(result.variable_id+'@'+result.revision)||result.variable_id));}
    return '<p>'+esc(row?'Original values and inputs for '+row.symbol+'.':'Showing at most 16 captured samples from this evidence page. Choose Explain beside a stock for its qualified trace.')+'</p>'+table(samples)+(stored.length?'<ul>'+stored.map(text=>'<li>'+esc(text)+'</li>').join('')+'</ul>':'')+(!samples.length&&!stored.length?'<p>This page has no matching calculation block. Continue to the next page, or download complete evidence.</p>':'')+'<details><summary>Advanced · original evidence page JSON</summary><pre>'+esc(JSON.stringify(records,null,2))+'</pre></details>';
  }
  return {preview,records};
})();
