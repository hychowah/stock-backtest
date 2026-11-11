/* Engine choice for submissions. The server lists the engines it runs. A new
   draft uses Original and shows no choice. A restored draft keeps its recorded
   engine; when that engine cannot run here, the choice appears so the user can
   pick Original. The server refuses an engine it does not run. Prepared views
   and stored results do not use the live selector to establish provenance. */
const EngineControls=(()=>{
  const labels={original:'Original',experimental:'New engine — experimental'};
  // Null until the server lists its engines; until then only Original runs.
  let engines=null,context=()=>({mode:'custom',scalar:false});
  const label=id=>labels[id]||'Unknown engine';
  const selected=()=>document.getElementById('backtest-engine')?.value||'original';
  // Every submission names its engine, so a restored choice is never dropped.
  const fields=()=>({engine:selected()});
  const runnable=(engine=selected())=>(engines??[{id:'original'}]).some(e=>e.id===engine);
  const calendarSupported=(engine=selected())=>(engines??[]).some(e=>e.id===engine&&e.calendar===1);
  function sync(){
    const intent=context(),dated=['custom','random'].includes(intent.mode),engine=selected();
    const boundary=document.getElementById('engine-controls');
    if(boundary)boundary.hidden=runnable(engine)||!intent.scalar&&!dated;
    const controls=document.getElementById('calendar-controls');
    if(controls)controls.hidden=!calendarSupported()&&!document.getElementById('calendar-custom')?.checked;
    const status=document.getElementById('engine-status');
    if(status)status.textContent=runnable(engine)?'':label(engine)+' cannot run on this server. Choose Original to run this test.';
  }
  async function init(readContext){
    if(typeof readContext==='function')context=readContext;
    document.getElementById('backtest-engine')?.addEventListener('change',()=>sync());
    sync();
    if(typeof location==='undefined'||location.protocol==='file:')return;
    try{
      const response=await fetch('/api/backtest-capabilities',{cache:'no-store'}),value=await response.json();
      if(response.ok===false||!Array.isArray(value.engines))throw Error('Capabilities unavailable');
      engines=value.engines;
      sync();
    }catch(_){}
  }
  return {fields,selected,label,runnable,calendarSupported,sync,init};
})();
if(typeof module!=='undefined')module.exports=EngineControls;
