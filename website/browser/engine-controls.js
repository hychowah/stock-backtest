/* Execution choice and advisory capabilities. Prepared views and stored results
   do not use the live selector to establish their provenance. */
const EngineControls=(()=>{
  const labels={original:'Original',experimental:'New engine — experimental'};
  let selectable=true,available=false,engines=[],context=()=>({mode:'custom',scalar:false});
  const label=id=>labels[id]||'Unknown engine';
  const selected=()=>document.getElementById('backtest-engine')?.value||'original';
  // Scalar drafts retain their explicit choice even if advisory support fails.
  // The server rejects that intent; it never changes the selected engine.
  const fields=({scalar=false}={})=>selectable||scalar?{engine:selected()}:{};
  const calendarSupported=(engine=selected())=>selectable?engines.some(e=>e.id===engine&&e.calendar===1):available;
  function requireCalendar(options){
    if(options.calendar&&!calendarSupported(options.engine??selected()))
      throw Error(label(options.engine??selected())+' does not support custom week/month calendars on this server. Reload the updated website.');
  }
  function sync(){
    const intent=context(),dated=['custom','random'].includes(intent.mode);
    const boundary=document.getElementById('engine-controls');
    if(boundary)boundary.hidden=!selectable||!intent.scalar&&!dated;
    const choice=document.getElementById('engine-choice');if(choice)choice.hidden=!selectable;
    const controls=document.getElementById('calendar-controls');
    if(controls)controls.hidden=!calendarSupported()&&!document.getElementById('calendar-custom')?.checked;
    const status=document.getElementById('engine-status'),engine=selected();
    const supported=engines.find(e=>e.id===engine);
    if(status){
      if(intent.scalar&&engine==='experimental'&&!supported?.scalar?.operations?.includes(intent.mode))
        status.textContent=label(engine)+' · variable execution support is unavailable on this server. Your choice is kept.';
      else status.textContent=engine==='experimental'?label(engine)+' · '+(supported?.status?.state||'status unavailable')+'. Prepare it in Manage backtest data. Resource limits apply.':label(engine)+' · '+(intent.scalar?'variable strategies use the local service. Sample preview uses Original reference execution.':'fixed and random schedules. Experimental setup is optional.');
    }
  }
  async function init(readContext){
    if(typeof readContext==='function')context=readContext;
    document.getElementById('backtest-engine')?.addEventListener('change',()=>sync());
    sync();
    if(typeof location==='undefined'||location.protocol==='file:')return;
    try{
      const response=await fetch('/api/backtest-capabilities',{cache:'no-store'}),value=await response.json();
      if(response.ok===false)throw Error('Capabilities unavailable');
      available=value.calendar===1;selectable=Array.isArray(value.engines);engines=value.engines||[];
      sync();
    }catch(_){}
  }
  return {fields,selected,label,calendarSupported,requireCalendar,sync,init};
})();
if(typeof module!=='undefined')module.exports=EngineControls;
