/* Compact sector views belong to the currently published immutable artifact.
   Keep only its all-trial summary and the selected trial's period counts. */
const SectorView=(()=>{
  const node=id=>document.getElementById('sector-'+id);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const label=name=>name===null?'Unknown':name;
  const percent=value=>Number.isFinite(value)?(value*100).toFixed(1)+'%':'—';
  const colors=['#42674b','#8aa481','#aec4a1','#cfb47d','#c8906b','#90afb5','#b6a3bc','#a1b6c8','#a4ad81','#d5bba7','#8e97b1'];
  const color=name=>name===null?'#cbd0c3':active.colors.get(name);
  const attribute=name=>escape(JSON.stringify(name));
  const sorted=rows=>rows.slice().sort((a,b)=>b.mean-a.mean||label(a.name).localeCompare(label(b.name)));
  const stats=(trial,name)=>trial.sectors.find(row=>row.name===name)||{name,mean:0,minimum:0,maximum:0,present:0};
  let active=null,isInspecting=()=>false;
  const valid=state=>active===state&&ResultArtifacts.current(state.artifact);
  function show(artifact){
    active?.controller?.abort();
    active={artifact,reader:ResultArtifacts.reader(artifact),scope:artifact.kind==='random'?'all':1,sector:undefined,period:null,all:null,detail:null,colors:new Map()};
    node('view').hidden=false;node('message').textContent='';node('insight').hidden=true;
    node('chart').innerHTML='';node('mix').innerHTML='';node('legend').innerHTML='';node('trials').innerHTML='';
    node('trial').innerHTML=(artifact.kind==='random'?'<option value="all">All original trials</option>':'')+
      Array.from({length:artifact.evidence?.trials??(artifact.kind==='random'?artifact.result.trials.length:1)},(_,i)=>'<option value="'+(i+1)+'">'+(artifact.kind==='random'?'Trial '+(i+1):'Fixed schedule')+'</option>').join('');
    node('trial').value=String(active.scope);node('period-controls').hidden=true;
  }
  async function load(){
    const state=active;if(!state||!valid(state))return;
    state.controller?.abort();
    const scope=state.scope;
    if(scope==='all'&&state.all||scope!=='all'&&state.detail?.trials[0].number===scope){render(state);return;}
    const controller=new AbortController();state.controller=controller;
    node('message').textContent='Reading sector counts from original saved holdings…';
    node('chart').innerHTML='';node('mix').innerHTML='';node('legend').innerHTML='';node('trials').innerHTML='';
    node('insight').hidden=true;node('period-controls').hidden=true;node('clear').hidden=true;
    if(isInspecting())document.getElementById('schedule-results').hidden=true;
    try{
      const value=await state.reader.sectors(scope,{signal:controller.signal});
      if(!valid(state)||state.scope!==scope||controller.signal.aborted)return;
      if(scope==='all')state.all=value;else{state.detail=value;state.period=value.periods.at(-1)?.number??null;}
      node('message').textContent='';render(state);
    }catch(error){if(valid(state)&&state.scope===scope&&error.name!=='AbortError')node('message').textContent=error.message+' Select Selection to retry.';}
    finally{if(state.controller===controller)state.controller=null;}
  }
  function inspect(state){
    if(isInspecting()&&state.scope!=='all'&&state.period!==null&&state.detail?.trials[0].number===state.scope)ScheduleView.inspectOriginal(state.scope,state.period,state.sector);
  }
  function render(state){
    const all=state.scope==='all',data=all?state.all:state.detail;
    if(!data||!all&&data.trials[0].number!==state.scope)return;
    if(all&&isInspecting())document.getElementById('schedule-results').hidden=true;
    const trial=all?null:data.trials[0],period=all?null:data.periods.find(row=>row.number===state.period);
    const means=all?data.sectors:trial.sectors,lead=sorted(means)[0];
    const names=[...new Set(data.trials.flatMap(t=>t.sectors.map(s=>s.name)))].filter(name=>name!==null).sort();
    for(const name of names)if(!state.colors.has(name))state.colors.set(name,colors[state.colors.size%colors.length]);
    node('clear').hidden=state.sector===undefined;
    node('clear').textContent=state.sector===undefined?'Show all sectors':'Clear '+label(state.sector)+' filter';
    node('insight').hidden=false;
    node('insight').textContent=lead?(all?label(lead.name)+' has the largest mean allocation in '+lead.leading+' of '+data.complete+' complete trials. Mean entry allocation: '+percent(lead.mean)+'.':label(lead.name)+' averages '+percent(lead.mean)+' at entry in this trial. '+trial.empty+' of '+trial.periods+' rebalances hold cash.'):'No sector average is available.';
    if(all)node('message').textContent=data.complete+' complete trials · '+data.incomplete+' incomplete (excluded from the combined average).';
    node('chart-title').textContent=all?'Sector mix in every trial':'Sector mix through time';
    node('chart-note').textContent=all?'Average entry allocations within each trial. Select a trial bar to inspect its books.':'Entry allocation at each rebalance. Select a bar to inspect its stocks.';
    const bars=all?data.trials.map(t=>({number:t.number,text:'Trial '+t.number,sectors:t.sectors,cash:t.cash,complete:t.complete})):data.periods.map(p=>({number:p.number,text:p.entry+' → '+p.exit,sectors:p.sectors.map(s=>({...s,mean:s.weight})),cash:p.names?0:1,complete:true}));
    node('chart').style.minWidth=Math.max(280,bars.length*24)+'px';
    node('chart').innerHTML=bars.map(bar=>'<button type="button" class="sector-bar '+(!bar.complete?'incomplete ':'')+(!all&&bar.number===state.period?'selected':'')+'" data-sector-bar="'+bar.number+'" aria-label="'+escape(bar.text+(!bar.complete?' · incomplete':'')+' · inspect selections')+'"><span class="sector-stack">'+bar.sectors.filter(s=>s.mean>0).map(s=>'<span class="sector-segment '+(state.sector!==undefined&&state.sector!==s.name?'dimmed':'')+'" style="height:'+s.mean*100+'%;background:'+color(s.name)+'" title="'+escape(label(s.name)+' '+percent(s.mean))+'"></span>').join('')+(bar.cash?'<span class="sector-segment sector-cash" style="height:'+bar.cash*100+'%" title="Cash '+percent(bar.cash)+'"></span>':'')+'</span><span class="sector-bar-label">'+(all?bar.number:bar.number%Math.max(1,Math.ceil(bars.length/12))===0||bar.number===1?escape(bar.text.slice(0,10)):'·')+'</span></button>').join('');
    const labels=sorted(means);
    node('legend').innerHTML=labels.map(s=>'<button type="button" data-sector-name="'+attribute(s.name)+'" aria-pressed="'+(state.sector===s.name)+'"><i style="background:'+color(s.name)+'"></i>'+escape(label(s.name))+'</button>').join('')+'<span><i class="sector-cash"></i>Cash</span>';
    node('mix-title').textContent=all?'Average across complete trials':period?period.entry:'No period selected';
    node('mix-note').textContent=all?'Ranges compare trial averages. Each complete trial counts equally.':period?period.names+' selected stocks · held through '+period.exit:'';
    const mix=all?data.sectors:period?.sectors.map(s=>({...s,mean:s.weight}))??[];
    node('mix').innerHTML=sorted(mix).map(s=>'<button type="button" class="sector-mix-row" data-sector-name="'+attribute(s.name)+'" aria-pressed="'+(state.sector===s.name)+'"><span><i style="background:'+color(s.name)+'"></i>'+escape(label(s.name))+'<small>'+(all?percent(s.minimum)+'–'+percent(s.maximum):s.count+' '+(s.count===1?'stock':'stocks'))+'</small><strong>'+percent(s.mean)+'</strong></span><span class="sector-track"><span style="width:'+s.mean*100+'%;background:'+color(s.name)+'"></span></span></button>').join('')+(all&&data.cash>0?'<p class="hint">Average cash: '+percent(data.cash)+'.</p>':!all&&!period?.names?'<p class="hint">No stocks selected. The portfolio holds cash until the next rebalance.</p>':'');
    node('trials-wrap').hidden=!all;node('period-controls').hidden=all;
    if(all){
      node('trials').innerHTML=data.trials.map(t=>{
        const s=state.sector===undefined?sorted(t.sectors)[0]:stats(t,state.sector);
        return '<tr><td>'+t.number+'</td><td>'+escape(s?label(s.name):'Cash')+'</td><td>'+percent(s?.mean??t.cash)+'</td><td>'+(s?percent(s.minimum)+'–'+percent(s.maximum):'—')+'</td><td>'+(s?.present??0)+' / '+t.periods+'</td><td>'+(t.complete?'Complete':'Incomplete')+'</td><td><button type="button" data-sector-inspect="'+t.number+'" '+(s?'data-inspect-sector="'+attribute(s.name)+'"':'')+'>Inspect →</button></td></tr>';
      }).join('');
    }else{
      node('period').innerHTML=data.periods.map(p=>'<option value="'+p.number+'">'+p.number+'. '+escape(p.entry+' → '+p.exit)+' · '+p.names+' stocks</option>').join('');
      node('period').value=String(state.period);
      node('period-back').disabled=state.period===data.periods[0]?.number;
      node('period-next').disabled=state.period===data.periods.at(-1)?.number;
      inspect(state);
    }
  }
  function pickTrial(number,sector){const state=active;if(!state)return;state.scope=number;if(sector!==undefined)state.sector=sector;node('trial').value=String(number);void load();}
  function init(inspecting){
    isInspecting=inspecting;
    node('view').hidden=true;
    node('trial').addEventListener('change',()=>{if(!active)return;active.scope=node('trial').value==='all'?'all':+node('trial').value;void load();});
    node('view').addEventListener('click',event=>{
      const target=event.target.closest('button');if(!target||!active)return;
      if(target.dataset.sectorName!==undefined){const name=JSON.parse(target.dataset.sectorName);active.sector=active.sector===name?undefined:name;render(active);}
      if(target.dataset.sectorInspect)pickTrial(+target.dataset.sectorInspect,target.dataset.inspectSector===undefined?undefined:JSON.parse(target.dataset.inspectSector));
      if(target.dataset.sectorBar){if(active.scope==='all')pickTrial(+target.dataset.sectorBar);else{active.period=+target.dataset.sectorBar;render(active);}}
    });
    node('clear').addEventListener('click',()=>{if(active){active.sector=undefined;render(active);}});
    node('period').addEventListener('change',()=>{if(active){active.period=+node('period').value;render(active);}});
    for(const [id,step] of [['period-back',-1],['period-next',1]])node(id).addEventListener('click',()=>{if(active){active.period+=step;render(active);}});
  }
  return {init,show,load};
})();
