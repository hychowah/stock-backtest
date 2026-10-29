/* One immutable completed result per view. Decode old records at this boundary;
   renderers and persistence receive the same settings, numbers and display meaning. */
const ResultArtifacts=(()=>{
  const views=new Map();
  const view=kind=>kind==='random'?'custom':kind;
  const signature=settings=>JSON.stringify(settings,(_key,value)=>typeof value==='number'&&!Number.isFinite(value)?String(value):value&&typeof value==='object'&&!Array.isArray(value)?Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b))):value);
  function freeze(value){
    if(value&&typeof value==='object'&&!Object.isFrozen(value)){
      Object.freeze(value);Object.values(value).forEach(freeze);
    }
    return value;
  }
  function legacyPresentation(context={}){
    context=context||{};
    const notes=new Map((context.notes||[]).map(row=>[row[0],row[1]]));
    return {coverage:notes.get('screen-coverage')||'',notice:{text:notes.get('screen-status')||'',severity:(context.notes||[]).find(row=>row[0]==='screen-status')?.[2]?.includes('warning')?'warning':'info'},rangeNote:notes.get('range-note')||'',periodLabel:context.pill||''};
  }
  function decode(snapshot){
    if(!snapshot||![1,2].includes(snapshot.version)||!['latest','january','custom','random'].includes(snapshot.kind)||!snapshot.settings||!snapshot.result)throw Error('Unsupported saved backtest format.');
    return freeze({version:2,kind:snapshot.kind,settings:snapshot.settings,result:snapshot.result,
      catalog:snapshot.catalog||{metrics:{},filters:{}},presentation:snapshot.version===1?legacyPresentation(snapshot.context):snapshot.presentation||{},
      captured_at:snapshot.captured_at||null});
  }
  function create(settings,result,catalog,presentation){
    const copy=value=>JSON.parse(JSON.stringify(value));
    return decode({version:2,kind:settings.mode,settings:copy(settings),result,catalog:copy(catalog),presentation:copy(presentation),captured_at:new Date().toISOString()});
  }
  function publish(artifact){
    const completed=decode(artifact);views.set(view(completed.kind),completed);return completed;
  }
  function matches(artifact,settings){
    if(!artifact)return false;
    let submitted=artifact.settings;
    // Opening a fresh-date run exposes its actual seed for an exact replay.
    if(artifact.kind==='random'&&settings.seed!==undefined)submitted={...submitted,seed:artifact.result.configuration.seed};
    // Older saved records used filter-first selection. Compare that default
    // without adding fields to, or rewriting, the stored artifact.
    return signature({selection_order:'filter_first',...submitted})===signature({selection_order:'filter_first',...settings});
  }
  return {create,decode,publish,matches,forView:key=>views.get(key)};
})();
if(typeof module!=='undefined')module.exports=ResultArtifacts;
