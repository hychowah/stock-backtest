/* The value of $1 on every market day of the open result, read from the curves
   saved with its periods. One chart shows a trial (or a fixed schedule); the
   other shows the spread of all random trials. A result saved without curves,
   or an inline result, shows neither. */
const AssetCurve=(()=>{
  const node=id=>document.getElementById(id);
  const money=v=>'$'+(v>=100?v.toFixed(0):v>=10?v.toFixed(1):v.toFixed(2));
  const time=day=>Date.parse(day+'T00:00:00Z');
  const STRATEGY='#20775e',SPY='#557ca5',WIDTH=1200,LEFT=86,RIGHT=1170,TOP=48,BOTTOM=312;
  const pending={},shown={};
  // Equal heights are equal percentage moves; a total loss sits at the floor.
  const log=v=>Math.log(Math.max(v,1e-4));
  // Round dollar values: 1-2-5 steps over a wide range, even steps over a narrow one.
  function ticks(low,high){
    const found=[];
    for(let k=Math.floor(Math.log10(low));k<=Math.ceil(Math.log10(high));k++)
      for(const step of [1,2,5]){const v=step*10**k;if(v>=low&&v<=high)found.push(v);}
    if(found.length>=3)return found;
    const rough=(high-low)/4,unit=10**Math.floor(Math.log10(rough)),step=[1,2,2.5,5,10].map(f=>f*unit).find(v=>v>=rough);
    return Array.from({length:Math.floor(high/step)-Math.ceil(low/step)+1},(_,i)=>(Math.ceil(low/step)+i)*step);
  }
  function dateTicks(first,last){
    const start=new Date(first),end=new Date(last),months=(end.getUTCFullYear()-start.getUTCFullYear())*12+end.getUTCMonth()-start.getUTCMonth();
    // Years label a long window; months label one shorter than three years.
    const unit=months>=36?12:1,step=Math.ceil(months/unit/12)*unit,found=[];
    for(let m=start.getUTCMonth()+1;;m++){
      const day=Date.UTC(start.getUTCFullYear(),m,1);if(day>last)break;
      const date=new Date(day);
      if((unit===12?date.getUTCMonth()===0&&date.getUTCFullYear()%(step/12)===0:m%step===0))found.push([day,unit===12?String(date.getUTCFullYear()):date.toISOString().slice(0,7)]);
    }
    return found;
  }
  // lines: [{label, values, color}]; band: {low, high} values or null.
  function draw(name,days,lines,band,describe){
    const svg=node('curve-'+name+'-chart'),readout=node('curve-'+name+'-readout');
    const times=days.map(time),first=times[0],last=times.at(-1),span=last-first||1;
    const all=lines.flatMap(line=>line.values).concat(band?[...band.low,...band.high]:[]);
    const top=log(Math.max(...all))+.03,bottom=log(Math.min(...all))-.03;
    const x=t=>LEFT+(t-first)/span*(RIGHT-LEFT),y=v=>BOTTOM-(log(v)-bottom)/(top-bottom)*(BOTTOM-TOP);
    const path=values=>values.map((v,i)=>(i?'L':'M')+x(times[i]).toFixed(1)+','+y(v).toFixed(1)).join('');
    let out='';
    for(const v of ticks(Math.exp(bottom),Math.exp(top)))out+=`<line x1="${LEFT}" x2="${RIGHT}" y1="${y(v)}" y2="${y(v)}" stroke="${v===1?'#9aa8a4':'#e3e8e1'}"/><text x="${LEFT-8}" y="${y(v)+4}" text-anchor="end" font-size="16">${v>=10?'$'+Math.round(v):money(v)}</text>`;
    for(const [t,label] of dateTicks(first,last))out+=`<text x="${x(t)}" y="${BOTTOM+28}" text-anchor="middle" font-size="16">${label}</text>`;
    if(band)out+=`<path d="${path(band.high)}L${days.map((_,i)=>x(times[days.length-1-i]).toFixed(1)+','+y(band.low[days.length-1-i]).toFixed(1)).join('L')}Z" fill="${STRATEGY}" opacity=".16"/>`;
    lines.forEach((line,j)=>{
      out+=`<path d="${path(line.values)}" fill="none" stroke="${line.color}" stroke-width="2.5"/>`;
      out+=`<line x1="${LEFT+j*240}" x2="${LEFT+24+j*240}" y1="18" y2="18" stroke="${line.color}" stroke-width="3"/><text x="${LEFT+32+j*240}" y="24" font-size="17">${line.label}</text>`;
    });
    if(band)out+=`<rect x="${LEFT+lines.length*240}" y="11" width="24" height="14" fill="${STRATEGY}" opacity=".16"/><text x="${LEFT+32+lines.length*240}" y="24" font-size="17">Lowest to highest trial</text>`;
    out+=`<line id="curve-${name}-marker" x1="${RIGHT}" x2="${RIGHT}" y1="${TOP}" y2="${BOTTOM}" stroke="#7a8a86" stroke-dasharray="3 3"/>`;
    svg.innerHTML=out;
    // The readout names the day under the pointer; it rests on the last day.
    const mark=i=>{readout.textContent=describe(i);node('curve-'+name+'-marker')?.setAttribute('x1',x(times[i]));node('curve-'+name+'-marker')?.setAttribute('x2',x(times[i]));};
    svg.onpointermove=event=>{
      const box=svg.getBoundingClientRect(),t=first+((event.clientX-box.left)/box.width*WIDTH-LEFT)/(RIGHT-LEFT)*span;
      let lo=0,hi=times.length-1;
      while(lo<hi){const mid=(lo+hi)>>1;if(times[mid]<t)lo=mid+1;else hi=mid;}
      mark(lo>0&&t-times[lo-1]<times[lo]-t?lo-1:lo);
    };
    svg.onpointerleave=()=>mark(days.length-1);
    mark(days.length-1);
  }
  function render(name,value){
    if(name==='all')draw(name,value.days,[{label:'Median trial',values:value.median,color:STRATEGY},{label:'SPY (median)',values:value.spy,color:SPY}],
      {low:value.lowest,high:value.highest},i=>value.days[i]+' · Median trial '+money(value.median[i])+' (lowest '+money(value.lowest[i])+', highest '+money(value.highest[i])+') · SPY '+money(value.spy[i]));
    else draw(name,value.days,[{label:'Strategy',values:value.strategy,color:STRATEGY},{label:'SPY',values:value.spy,color:SPY}],
      null,i=>value.days[i]+' · Strategy '+money(value.strategy[i])+' · SPY '+money(value.spy[i]));
  }
  function hide(name){pending[name]?.abort();delete pending[name];delete shown[name];node('curve-'+name).hidden=true;}
  async function load(name,artifact,selection){
    const key=artifact.evidence?.id+'/'+selection;
    if(shown[name]===key)return;
    hide(name);
    const reader=ResultArtifacts.reader(artifact);if(!reader.curve)return;
    const controller=new AbortController();pending[name]=controller;
    try{
      const value=await reader.curve(selection,{signal:controller.signal});
      if(pending[name]!==controller||!ResultArtifacts.current(artifact)||!value.available)return;
      shown[name]=key;node('curve-'+name).hidden=false;render(name,value);
    }catch(error){
      if(pending[name]===controller&&ResultArtifacts.current(artifact)&&error.name!=='AbortError'){node('curve-'+name).hidden=false;node('curve-'+name+'-chart').innerHTML='';node('curve-'+name+'-readout').textContent=error.message;}
    }finally{if(pending[name]===controller)delete pending[name];}
  }
  return {trial:(artifact,number)=>load('trial',artifact,number),all:artifact=>load('all',artifact,'all'),clear:()=>{hide('trial');hide('all');}};
})();
if(typeof module!=='undefined')module.exports=AssetCurve;
