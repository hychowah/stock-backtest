/* Random-date experiment presentation.
   Formula and sampling policy belong to the backend; this module consumes results. */
const RobustnessView=(()=>{
  const node=id=>document.getElementById(id);
  const pct=v=>v===null?'—':(v*100).toFixed(2)+'%';
  const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let configuration=null,getResult=()=>null,displayed=null;
  function remember(next,engine){
    configuration=engine?{...next,engine}:next;
    try{localStorage.setItem('backtest-experiment',JSON.stringify(configuration));}catch(_){}
    if(!node('repeat-random').checked)node('random-seed').value=String(next.seed);
    node('robustness-replay').hidden=false;
    node('robustness-replay-note').textContent='Date set saved. Replay uses the same dates, filters and window, including after an interrupted run.';
  }
  function chart(result){
    const key=node('robustness-measure').value||'cagr';
    const label={cagr:'CAGR',total_return:'Total return',excess_cagr:'CAGR difference vs SPY (pp)'}[key];
    const complete=result.trials.filter(t=>Number.isFinite(t.cagr));
    const series=[{name:key==='excess_cagr'?'Strategy − SPY':'Strategy',color:'#20775e',values:complete.map(t=>t[key]).filter(Number.isFinite)}];
    if(key!=='excess_cagr')series.push({name:'Paired SPY',color:'#557ca5',values:complete.map(t=>key==='cagr'?t.spy_cagr:Number.isFinite(t.spy_growth)?t.spy_growth-1:null).filter(Number.isFinite)});
    const svg=node('robustness-chart');
    node('robustness-chart-note').textContent=`Seed ${result.configuration.seed} · ${complete.length} complete trials. Bars show observed trial counts. Strategy and paired SPY use the same bins and axes. Dashed bell curves are normal fits, not evidence that returns are normally distributed. They are not confidence intervals.`;
    const values=series.flatMap(s=>s.values);
    if(!values.length){svg.innerHTML='<text x="60" y="80">No complete trials to plot.</text>';return;}
    series.forEach(s=>{
      s.mean=s.values.length?s.values.reduce((a,b)=>a+b,0)/s.values.length:null;
      s.sd=s.values.length?Math.sqrt(s.values.reduce((a,b)=>a+(b-s.mean)**2,0)/s.values.length):0;
    });
    const varied=Math.max(...values)>Math.min(...values);
    const bins=varied?Math.min(40,Math.max(12,Math.ceil(3*Math.sqrt(complete.length)))):1;
    const pad=Math.max(...series.map(s=>s.sd*.6),Math.abs(values[0])*.01,.0001);
    const bounds=series.filter(s=>s.mean!==null).flatMap(s=>[s.mean-3*s.sd,s.mean+3*s.sd]);
    const lo=Math.min(...values,...bounds)-pad,hi=Math.max(...values,...bounds)+pad;
    const width=(hi-lo)/bins;
    series.forEach(s=>{
      s.counts=Array(bins).fill(0);
      s.values.forEach(v=>s.counts[Math.min(bins-1,Math.floor((v-lo)/width))]++);
      s.density=v=>s.sd>0?s.values.length*width/(s.sd*Math.sqrt(2*Math.PI))*Math.exp(-.5*((v-s.mean)/s.sd)**2):0;
    });
    const top=Math.max(1,...series.flatMap(s=>[...s.counts,s.density(s.mean)]))*1.15;
    const x=v=>70+(v-lo)/(hi-lo)*880,y=v=>310-v/top*240;
    const format=v=>(v*100).toFixed(2)+(key==='excess_cagr'?' pp':'%');
    let out='<title>'+label+' distribution for seed '+escape(result.configuration.seed)+'</title>';
    for(let i=0;i<=4;i++){
      const count=top*i/4,yy=y(count);
      out+=`<line x1="70" x2="950" y1="${yy}" y2="${yy}" stroke="#dce3e8"/><text x="58" y="${yy+4}" text-anchor="end" font-size="12">${count.toFixed(1)}</text>`;
    }
    series.forEach((s,j)=>{
      out+=`<rect x="${70+j*400}" y="12" width="14" height="14" fill="${s.color}"/><text x="${92+j*400}" y="24" font-size="13">${s.name}${s.mean===null?' · no data':' · mean '+format(s.mean)}</text>`;
      s.counts.forEach((count,i)=>{out+=`<rect tabindex="0" x="${x(lo+i*width)+1}" y="${y(count)}" width="${880/bins-2}" height="${310-y(count)}" fill="${s.color}" opacity=".45"><title>${s.name}: ${format(lo+i*width)} to ${format(lo+(i+1)*width)}: ${count} trials</title></rect>`;});
      if(s.sd>0){
        const points=Array.from({length:201},(_,i)=>{const v=lo+(hi-lo)*i/200;return `${i?'L':'M'}${x(v)},${y(s.density(v))}`;}).join(' ');
        out+=`<path d="${points}" fill="none" stroke="${s.color}" stroke-width="3" stroke-dasharray="7 4"/>`;
      }
      if(s.mean!==null)out+=`<line x1="${x(s.mean)}" x2="${x(s.mean)}" y1="60" y2="310" stroke="${s.color}" stroke-dasharray="3 4"/>`;
    });
    for(let i=0;i<=5;i++){const v=lo+(hi-lo)*i/5;out+=`<text x="${x(v)}" y="335" text-anchor="middle" font-size="12">${format(v)}</text>`;}
    out+='<text x="510" y="370" text-anchor="middle" font-size="14">'+label+'</text><text transform="translate(18,180) rotate(-90)" text-anchor="middle" font-size="14">Trial count</text>';
    svg.innerHTML=out;
    if(series.every(s=>!s.sd))node('robustness-chart-note').textContent+=' Each series has identical returns; no bell curves are fitted.';
  }
  function render(next,engine){
    remember(next.configuration,engine);
    preview(next);
  }
  function preview(result){
    displayed=result;node('robustness-results').hidden=false;
    chart(result);
    const d=result.distributions;
    node('robustness-mean').textContent=pct(d.cagr.mean);
    node('robustness-median').textContent=pct(d.cagr.median);
    node('robustness-spy').textContent=pct(d.spy_cagr.mean);
    node('robustness-description').textContent=`${result.completed} trials · ${result.valid} complete, ${result.incomplete} incomplete · ${result.unique_schedules} distinct schedules · ${result.beat_spy}/${result.valid} complete trials beat paired SPY. ${result.note}`;
    const definitions=[['Strategy CAGR','cagr',pct],['Paired SPY CAGR','spy_cagr',pct],['CAGR difference (pp)','excess_cagr',v=>v===null?'—':(v*100).toFixed(2)],['Total strategy return','total_return',pct],['Ending value of $1','growth',v=>v===null?'—':'$'+v.toFixed(2)]];
    node('robustness-distribution').innerHTML=definitions.map(([label,key,format])=>'<tr><td>'+label+'</td>'+['mean','median','p10','p25','p75','p90','min','max','stddev'].map(stat=>'<td>'+format(d[key][stat])+'</td>').join('')+'</tr>').join('');
    node('robustness-trials').innerHTML=result.trials.map(t=>'<tr>'+[t.trial,t.start,t.first_trade,t.end,t.periods,pct(t.cagr),pct(t.spy_cagr),t.excess_cagr===null?'—':(t.excess_cagr*100).toFixed(2),t.empty_periods,t.short_periods].map(v=>'<td>'+escape(v)+'</td>').join('')+'</tr>').join('');
    node('robustness-trial').innerHTML=result.trials.map((t,i)=>`<option value="${i}">Trial ${t.trial} · ${t.first_trade} · CAGR ${pct(t.cagr)}</option>`).join('');
    node('robustness-trial').value='0';
  }
  function download(){
    const artifact=typeof ResultArtifacts!=='undefined'?ResultArtifacts.forView('custom'):null;
    if(artifact?.kind==='random'&&[3,4].includes(artifact.version)){ResultArtifacts.reader(artifact).download('random');return;}
    const result=getResult();
    if(!result)return;
    const keys=['trial','start','first_trade','end','cash_days','periods','cagr','spy_cagr','excess_cagr','total_return','growth','spy_growth','empty_periods','short_periods','seed',...(result.configuration.calendar?['interval_unit','interval_count']:['months']),'dates'];
    if(result.producer)keys.push('engine');
    const market=artifact?.settings.market;if(market!==undefined)keys.unshift('market','currency');
    const rows=[keys,...result.trials.map(t=>keys.map(k=>k==='market'?market:k==='currency'?'USD':k==='engine'?result.producer.engine:k==='dates'?t.dates.join(';'):k==='seed'?result.configuration.seed:k==='months'?result.configuration.months:k==='interval_unit'?result.configuration.calendar.interval.unit:k==='interval_count'?result.configuration.calendar.interval.count:t[k]))];
    const csv=rows.map(row=>row.map(v=>'"'+String(v??'').replace(/"/g,'""')+'"').join(',')).join('\r\n');
    const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='random-dates-seed-'+result.configuration.seed+'.csv';link.click();URL.revokeObjectURL(url);
  }
  function init(inspect,replay,readResult=()=>null){
    getResult=readResult;
    try{const saved=JSON.parse(localStorage.getItem('backtest-experiment'));if(saved)remember(saved);}catch(_){}
    node('robustness-replay').addEventListener('click',()=>configuration?replay(configuration):undefined);
    node('robustness-measure').addEventListener('change',()=>{const result=displayed??getResult();if(result)chart(result);});
    node('robustness-download').addEventListener('click',download);
    node('robustness-inspect').addEventListener('click',()=>{const result=getResult(),index=+node('robustness-trial').value;return result?inspect(result.trials[index],result.configuration,result.trial_results?.[index],index):undefined;});
  }
  return {render,preview,init,remember};
})();
