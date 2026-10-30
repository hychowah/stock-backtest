/* One immutable completed result per view. Decode old records at this boundary;
   renderers and persistence receive the same settings, numbers and display meaning. */
const ResultArtifacts=(()=>{
  const views=new Map(),readers=new Map();let revision=0;
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
    if(!snapshot||![1,2,3].includes(snapshot.version)||!['latest','january','custom','random'].includes(snapshot.kind)||!snapshot.settings||!snapshot.result)throw Error('Unsupported saved backtest format.');
    if(snapshot.version===3){
      if(!['custom','random'].includes(snapshot.kind)||!/^([a-f0-9]{32})$/.test(snapshot.evidence?.id)||snapshot.evidence.format_version!==1||!Number.isInteger(snapshot.evidence.trials)||snapshot.evidence.trials<1||!Number.isInteger(snapshot.evidence.periods)||!Number.isInteger(snapshot.evidence.holdings))throw Error('Unsupported saved backtest format.');
      return freeze({...snapshot});
    }
    return freeze({version:2,kind:snapshot.kind,settings:snapshot.settings,result:snapshot.result,
      catalog:snapshot.catalog||{metrics:{},filters:{}},presentation:snapshot.version===1?legacyPresentation(snapshot.context):snapshot.presentation||{},
      captured_at:snapshot.captured_at||null});
  }
  function create(settings,result,catalog,presentation){
    const copy=value=>JSON.parse(JSON.stringify(value));
    return decode({version:2,kind:settings.mode,settings:copy(settings),result,catalog:copy(catalog),presentation:copy(presentation),captured_at:new Date().toISOString()});
  }
  function publish(artifact){
    const completed=decode(artifact),key=view(completed.kind),previous=views.get(key);
    revision++;views.set(key,completed);
    if(previous?.evidence?.id!==completed.evidence?.id)release(previous);
    return completed;
  }
  const identity=artifact=>artifact?.evidence?.id;
  const current=artifact=>views.get(view(artifact.kind))?.evidence?.id===identity(artifact);
  function opening(){const ticket=++revision;return ()=>ticket===revision;}
  function identifier(){return Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');}
  async function transport(path,options={}){
    const response=await fetch(path,{cache:'no-store',...options});
    const length=Number(response.headers?.get('Content-Length'));
    if(length>32*1024*1024)throw Error('Evidence response exceeds its byte limit.');
    const value=await response.json();
    if(!response.ok){const error=Error(value.error||'Could not read stored evidence.');error.requires_reader=value.requires_reader;throw error;}
    return value;
  }
  async function acquire(source,display={},id=identifier()){
    const artifact=decode(await transport('/api/backtest-runs/'+id+'/reader',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source,display})}));
    if(artifact.evidence.id!==id)throw Error('Evidence acquisition identity differs.');
    reader(artifact);return artifact;
  }
  function release(artifact){
    const id=identity(artifact);if(!id)return;
    const state=readers.get(id);
    if(state){state.closed=true;for(const controller of state.requests)controller.abort();readers.delete(id);}
    // Requests already admitted by the server retain their own independent pin.
    void fetch('/api/backtest-runs/'+id+'/reader',{method:'DELETE',keepalive:true}).catch(()=>{});
  }
  function reader(artifact){
    if(artifact.version!==3){
      const trial=number=>artifact.kind==='random'?artifact.result.trial_results?.[number-1]:number===1?artifact.result:null;
      const requireTrial=number=>{const value=trial(number);if(!value)throw Error('Complete stored trial details are unavailable.');return value;};
      const page=(rows,cursor)=>({rows:rows.slice(cursor,cursor+64),cursor,next:cursor+64<rows.length?cursor+64:null,total:rows.length});
      return {
        async trial(number){const {periods,...summary}=requireTrial(number),n=(summary.options.rank_to??50)-(summary.options.rank_from??1)+1;return {summary,periods:periods.length,short:periods.filter(p=>p.names<n).length,empty:periods.filter(p=>!p.names).length};},
        async periods(number,cursor=0){return page(requireTrial(number).periods.map(({holdings,...value},i)=>({number:i+1,value})),cursor);},
        async holdings(number,period,cursor=0){return page(requireTrial(number).periods[period-1].holdings,cursor);}
      };
    }
    const id=identity(artifact);if(readers.has(id))return readers.get(id).api;
    const state={closed:false,requests:new Set()};
    async function request(path){
      if(state.closed)throw Error('This result view was replaced.');
      const controller=new AbortController();state.requests.add(controller);
      try{
        const value=await transport('/api/backtest-runs/'+id+'/reader/page/'+path,{signal:controller.signal});
        if(state.closed||value.identity!==id)throw Error('This result view was replaced.');
        return freeze(value);
      }finally{state.requests.delete(controller);}
    }
    state.api={
      trial:number=>request('trial/'+number+'/0'),
      periods:(number,cursor=0)=>request('periods/'+number+'/'+cursor),
      holdings:(number,period,cursor=0)=>request('holdings/'+number+'/'+period+'/'+cursor),
      download(kind,number=1){
        if(state.closed)throw Error('This result view was replaced.');
        const link=document.createElement('a');link.href='/api/backtest-runs/'+id+'/reader/export/'+kind+'/'+number;link.click();
      }
    };
    readers.set(id,state);return state.api;
  }
  if(typeof addEventListener==='function')addEventListener('pagehide',()=>{for(const artifact of views.values())release(artifact);});
  function matches(artifact,settings){
    if(!artifact)return false;
    let submitted=artifact.settings;
    // Opening a fresh-date run exposes its actual seed for an exact replay.
    if(artifact.kind==='random'&&settings.seed!==undefined)submitted={...submitted,seed:artifact.result.configuration.seed};
    const calendar=typeof CalendarSettings!=='undefined'?CalendarSettings:typeof require==='function'?require('./calendar-settings.js'):null;
    return signature(calendar?calendar.normalize(submitted):submitted)===signature(calendar?calendar.normalize(settings):settings);
  }
  return {create,decode,publish,matches,reader,acquire,release,opening,current,forView:key=>views.get(key)};
})();
if(typeof module!=='undefined')module.exports=ResultArtifacts;
