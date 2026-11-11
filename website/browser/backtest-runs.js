/* A latest screen that runs on the local service: submit it, then ask for its
   status until it ends. The page keeps no record of a screen, so a reload starts
   without it. Dated tests run from the queue and never start here. */
const BacktestRuns=(()=>{
  function create(options){
    const bytes=crypto.getRandomValues(new Uint8Array(16));
    return {id:Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join(''),mode:'latest',options:JSON.parse(JSON.stringify(options))};
  }
  async function request(run,action){
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
    try{
      const response=await fetch('/api/backtest-runs/'+run.id+(action==='status'?'/status':''),{
        method:action==='start'?'POST':'GET',headers:{'Content-Type':'application/json'},cache:'no-store',signal:controller.signal,
        ...(action==='start'?{body:JSON.stringify({mode:run.mode,options:run.options})}:{})});
      let payload;
      try{payload=await response.json();}catch(error){
        if(response.ok)throw error;
        payload={error:'Could not access this latest screen (HTTP '+response.status+').'};
      }
      if(!response.ok){
        const message=action==='start'&&response.status===404?'This tab is connected to an older server. Run start.cmd again and use the new browser tab it opens. Refreshing this tab alone does not update the server.':payload.error||'Could not access this latest screen.';
        const error=Error(message);
        error.terminal=response.status>=400&&response.status<500;
        error.status=response.status;error.code=payload.code;error.path=payload.path;error.errors=payload.errors;
        throw error;
      }
      return payload;
    }finally{clearTimeout(timeout);}
  }
  // The run ID makes a repeated submission the same run, so a lost reply is asked
  // for again. A refusal ends the screen. current() tells if the page still wants it.
  async function follow(run,update,{current=()=>true}={}){
    let action='start';
    while(current()){
      try{
        const state=await request(run,action);
        action='status';
        if(!current())return null;
        update(state);
        if(['complete','failed','cancelled'].includes(state.state))return state;
      }catch(error){
        if(!current())return null;
        if(error.terminal)throw error;
        update({state:'reconnecting'});
      }
      await new Promise(resolve=>setTimeout(resolve,1000));
    }
    return null;
  }
  return {create,follow};
})();
