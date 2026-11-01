/* Own submission, recovery and Stop intent for server runs. Each ID has its own
   storage record, so rejection in another tab cannot erase an accepted run. */
const BacktestRuns=(()=>{
  const prefix='backtest-server-run:',unsaved=new Map();
  function records(){
    const saved=new Map();
    try{
      for(let i=0;i<localStorage.length;i++){
        const key=localStorage.key(i);
        if(!key?.startsWith(prefix))continue;
        try{
          const run=JSON.parse(localStorage.getItem(key));
          if(!run?.id)continue;
          run.phase=localStorage.getItem(key+':complete')?'complete':localStorage.getItem(key+':accepted')?'accepted':run.phase;
          run.stop=run.stop||!!localStorage.getItem(key+':stop');
          saved.set(run.id,run);
        }catch(_){}
      }
    }catch(_){}
    for(const [id,run] of unsaved){
      const stored=saved.get(id);
      run.stop=run.stop||!!stored?.stop;
      if(stored?.phase==='complete'||(stored?.phase==='accepted'&&run.phase==='submitting'))run.phase=stored.phase;
      saved.set(id,run);
    }
    return [...saved.values()];
  }
  function save(run){
    // Independent, monotonic markers prevent a late acknowledgement in one tab
    // from overwriting Stop or completion already recorded by another tab.
    const key=prefix+run.id;
    try{
      if(!localStorage.getItem(key))localStorage.setItem(key,JSON.stringify(run));
      if(run.phase!=='submitting')localStorage.setItem(key+':accepted','1');
      if(run.phase==='complete')localStorage.setItem(key+':complete','1');
      if(run.stop)localStorage.setItem(key+':stop','1');
      unsaved.delete(run.id);
    }
    catch(_){unsaved.set(run.id,run);}
  }
  function pending(){
    return records().sort((a,b)=>b.submitted-a.submitted)[0]||null;
  }
  function forget(id){
    unsaved.delete(id);
    try{for(const suffix of ['',':accepted',':complete',':stop'])localStorage.removeItem(prefix+id+suffix);}catch(_){}
  }
  function create(mode,options,planned=null){
    const bytes=crypto.getRandomValues(new Uint8Array(16));
    const run={id:Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join(''),mode,options,...(planned?{planned}:{}),submitted:Date.now(),phase:'submitting',stop:false};
    save(run);return run;
  }
  async function request(run,action){
    const controller=new AbortController();
    let timeout=setTimeout(()=>controller.abort(),15000);
    try{
      const response=await fetch('/api/backtest-runs/'+run.id+(action==='stop'?'/stop':action==='status'?'/status':''),{
        method:['start','stop'].includes(action)?'POST':'GET',headers:{'Content-Type':'application/json'},cache:'no-store',signal:controller.signal,
        ...(action==='start'?{body:JSON.stringify({mode:run.mode,options:run.options,...(run.planned?{planned:run.planned}:{})})}:{})});
      // Completed random runs can contain large holding lists. Allow transfer
      // time after headers arrive while still bounding a stalled connection.
      clearTimeout(timeout);timeout=setTimeout(()=>controller.abort(),180000);
      let payload;
      try{payload=await response.json();}catch(error){
        if(response.ok)throw error;
        payload={error:'Could not access this backtest run (HTTP '+response.status+').'};
      }
      if(!response.ok){
        const message=action==='start'&&response.status===404?'This tab is connected to an older server. Run start.cmd again and use the new browser tab it opens. Refreshing this tab alone does not update the server.':payload.error||'Could not access this backtest run.';
        const error=Error(message);
        error.terminal=response.status>=400&&response.status<500;
        error.status=response.status;
        throw error;
      }
      return payload;
    }finally{clearTimeout(timeout);}
  }
  async function reconcile(run){
    const saved=records().find(saved=>saved.id===run.id);
    if(saved)Object.assign(run,saved);
    const state=await request(run,run.phase==='submitting'?'start':run.stop?'stop':'status');
    run.phase=state.state==='complete'?'complete':'accepted';
    if(['failed','cancelled'].includes(state.state))forget(run.id);
    else save(run);
    return state;
  }
  async function recover(update=()=>{}){
    // Browser records describe past observations. Ask the server before
    // selecting active work, or the newest available completed result.
    let completed=null;
    for(const run of records().sort((a,b)=>b.submitted-a.submitted)){
      while(true){
        try{
          const state=await reconcile(run);
          if(['running','stopping'].includes(state.state))return run;
          if(state.state==='complete'&&!completed)completed=run;
          break;
        }catch(error){
          if(error.terminal){forget(run.id);break;}
          update({state:'reconnecting'});
          await new Promise(resolve=>setTimeout(resolve,1000));
        }
      }
    }
    return completed;
  }
  async function follow(run,update,{current=()=>true}={}){
    while(current()){
      try{
        let state=await reconcile(run);
        if(!current())return null;
        if(state.state==='complete'&&!state.result&&!state.evidence)state=await request(run,null);
        if(!current())return null;
        update(state);
        if(['complete','failed','cancelled'].includes(state.state)){
          // Keep only recent completed recovery records. Other tabs' active or
          // unacknowledged runs must remain available until reconciled.
          const completed=records().filter(saved=>saved.phase==='complete').sort((a,b)=>b.submitted-a.submitted);
          for(const old of completed.slice(4))forget(old.id);
          return state;
        }
      }catch(error){
        if(!current())return null;
        if(error.terminal){forget(run.id);throw error;}
        update({state:'reconnecting'});
      }
      await new Promise(resolve=>setTimeout(resolve,1000));
    }
    return null;
  }
  function stop(run){run.stop=true;save(run);}
  return {create,pending,recover,follow,stop};
})();
