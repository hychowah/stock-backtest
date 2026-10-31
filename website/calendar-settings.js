/* Calendar representation and labels only. Dates are planned by the server.
   Stored settings are decoded in memory and are never rewritten. */
const CalendarSettings=(()=>{
  const legacy=[1,3,6,12,24];
  function decode(value){
    if(Object.hasOwn(value,'calendar')){
      if(['months','start','end','interval','version'].some(k=>k in value))throw Error('Use one calendar representation.');
      const c=value.calendar;
      if(!c||typeof c!=='object')throw Error('Invalid saved calendar.');
      const i=c.interval;
      if(c.version!==1||Object.keys(c).sort().join(',')!=='end,interval,start,version'||!i||Object.keys(i).sort().join(',')!=='count,unit'||!Number.isInteger(i.count)||i.count<1||i.count>({week:104,month:24}[i.unit]||0))throw Error('Invalid saved calendar.');
      return c;
    }
    const count=Object.hasOwn(value,'months')?value.months:12;
    if(!legacy.includes(count))throw Error('Invalid month interval.');
    return {version:1,start:value.start,end:value.end,interval:{unit:'month',count}};
  }
  const fields=value=>Object.hasOwn(value,'calendar')?{calendar:decode(value)}:{start:value.start,end:value.end,months:decode(value).interval.count};
  const label=value=>{const c=decode(Object.hasOwn(value,'calendar')?{calendar:value.calendar}:value);return 'every '+c.interval.count+' '+c.interval.unit+'(s)';};
  function normalize(value){
    if(!['custom','random'].includes(value.mode)||!Object.hasOwn(value,'calendar')&&value.start===undefined)return value;
    const {calendar,start,end,months,...rest}=value;
    return {...rest,calendar:decode(value)};
  }
  function read(){
    const node=id=>document.getElementById(id),start=node('trade-start').value,end=node('trade-end').value;
    if(node('calendar-custom')?.checked){
      const value={calendar:{version:1,start,end,interval:{unit:node('calendar-unit').value,count:+node('calendar-count').value}}};
      decode(value);return value;
    }
    return {start,end,months:+node('rebalance-months').value};
  }
  function restore(value){
    const node=id=>document.getElementById(id),c=decode(value);
    node('trade-start').value=c.start;node('trade-end').value=c.end;
    if(node('calendar-custom')){
      node('calendar-custom').checked=Object.hasOwn(value,'calendar');
      node('calendar-unit').value=c.interval.unit;node('calendar-count').max=c.interval.unit==='week'?'104':'24';
      node('calendar-count').value=c.interval.count;
      node('calendar-controls').hidden=!Object.hasOwn(value,'calendar')&&!supported();
    }
    if(!Object.hasOwn(value,'calendar'))node('rebalance-months').value=String(c.interval.count);
  }
  let available=false,selectable=true,engines=[];
  const engineFields=()=>selectable?{engine:document.getElementById('backtest-engine')?.value||'original'}:{};
  const supported=()=>selectable?engines.some(e=>e.id===engineFields().engine&&e.calendar===1):available;
  function syncEngine(){
    const controls=document.getElementById('calendar-controls');
    if(controls)controls.hidden=!supported()&&!document.getElementById('calendar-custom')?.checked;
    const status=document.getElementById('engine-status'),engine=engineFields().engine;
    if(status)status.textContent=engine==='experimental'?'New engine — experimental · '+(engines.find(e=>e.id===engine)?.status?.state||'status unavailable')+'. Prepare it in Manage backtest data. Operating yield spread is unsupported. Resource limits apply.':'Original · monthly frequency presets. Experimental setup is optional.';
  }
  async function init(){
    const unit=document.getElementById('calendar-unit'),count=document.getElementById('calendar-count');
    unit?.addEventListener('change',()=>{count.max=unit.value==='week'?'104':'24';});
    document.getElementById('backtest-engine')?.addEventListener('change',syncEngine);
    if(typeof location==='undefined'||location.protocol==='file:')return;
    try{
      const response=await fetch('/api/backtest-capabilities',{cache:'no-store'});const value=await response.json();
      available=value.calendar===1;selectable=Array.isArray(value.engines);engines=value.engines||[];
      const choice=document.getElementById('engine-choice');if(choice)choice.hidden=!selectable;
      syncEngine();
    }catch(_){}
  }
  return {decode,fields,label,normalize,read,restore,init,supported,engineFields,syncEngine};
})();
if(typeof module!=='undefined')module.exports=CalendarSettings;
