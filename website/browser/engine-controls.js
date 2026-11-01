/* Execution choice and advisory capabilities. Prepared views and stored results
   do not use the live selector to establish their provenance. */
const EngineControls=(()=>{
  const labels={original:'Original',experimental:'New engine — experimental'};
  let selectable=true,available=false,engines=[];
  const label=id=>labels[id]||'Unknown engine';
  const selected=()=>document.getElementById('backtest-engine')?.value||'original';
  const fields=()=>selectable?{engine:selected()}:{};
  const calendarSupported=(engine=selected())=>selectable?engines.some(e=>e.id===engine&&e.calendar===1):available;
  function requireCalendar(options){
    if(options.calendar&&!calendarSupported(options.engine??selected()))
      throw Error(label(options.engine??selected())+' does not support custom week/month calendars on this server. Reload the updated website.');
  }
  function sync(){
    const controls=document.getElementById('calendar-controls');
    if(controls)controls.hidden=!calendarSupported()&&!document.getElementById('calendar-custom')?.checked;
    const status=document.getElementById('engine-status'),engine=selected();
    if(status)status.textContent=engine==='experimental'?label(engine)+' · '+(engines.find(e=>e.id===engine)?.status?.state||'status unavailable')+'. Prepare it in Manage backtest data. Resource limits apply.':label(engine)+' · fixed and random schedules. Experimental setup is optional.';
  }
  async function init(){
    document.getElementById('backtest-engine')?.addEventListener('change',sync);
    if(typeof location==='undefined'||location.protocol==='file:')return;
    try{
      const response=await fetch('/api/backtest-capabilities',{cache:'no-store'}),value=await response.json();
      if(response.ok===false)throw Error('Capabilities unavailable');
      available=value.calendar===1;selectable=Array.isArray(value.engines);engines=value.engines||[];
      const choice=document.getElementById('engine-choice');if(choice)choice.hidden=!selectable;
      sync();
    }catch(_){}
  }
  return {fields,selected,label,calendarSupported,requireCalendar,sync,init};
})();
if(typeof module!=='undefined')module.exports=EngineControls;
