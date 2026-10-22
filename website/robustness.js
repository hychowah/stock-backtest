/* Random-date experiment presentation and incremental NDJSON transport.
   Formula and sampling policy belong to the backend; this module consumes results. */
const RobustnessView=(()=>{
  const node=id=>document.getElementById(id);
  const pct=v=>v===null?'—':(v*100).toFixed(2)+'%';
  const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let result=null,configuration=null;
  function remember(next){
    configuration=next;
    try{localStorage.setItem('backtest-experiment',JSON.stringify(next));}catch(_){}
    node('random-seed').value=String(next.seed);
    node('robustness-replay').hidden=false;
    node('robustness-replay-note').textContent='Date set saved. Replay uses the same dates, filters and window, including after an interrupted run.';
  }
  async function read(response,progress){
    if(!response.body?.getReader)return response.json();
    const reader=response.body.getReader(),decoder=new TextDecoder();
    let buffer='',complete=null;
    function line(text){
      if(!text.trim())return;
      const event=JSON.parse(text);
      if(event.type==='configuration'){remember(event.configuration);progress(event);}
      else if(event.type==='progress')progress(event);
      else if(event.type==='complete')complete=event.result;
      else if(event.type==='error')throw Error(event.message);
    }
    try{
      while(true){
        const {value,done}=await reader.read();
        buffer+=decoder.decode(value,{stream:!done});
        let end;
        while((end=buffer.indexOf('\n'))!==-1){line(buffer.slice(0,end));buffer=buffer.slice(end+1);}
        if(done)break;
      }
      if(buffer.trim())line(buffer);
      if(!complete)throw Error('The server connection ended before all trials completed. Restart the launcher, then select Replay saved date test to reuse completed books.');
      return complete;
    }finally{reader.releaseLock();}
  }
  function render(next){
    result=next;node('robustness-results').hidden=false;
    remember(result.configuration);
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
    if(!result)return;
    const keys=['trial','start','first_trade','end','cash_days','periods','cagr','spy_cagr','excess_cagr','total_return','growth','spy_growth','empty_periods','short_periods','seed','months','dates'];
    const rows=[keys,...result.trials.map(t=>keys.map(k=>k==='dates'?t.dates.join(';'):k==='seed'?result.configuration.seed:k==='months'?result.configuration.months:t[k]))];
    const csv=rows.map(row=>row.map(v=>'"'+String(v??'').replace(/"/g,'""')+'"').join(',')).join('\r\n');
    const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='random-dates-seed-'+result.configuration.seed+'.csv';link.click();URL.revokeObjectURL(url);
  }
  function init(inspect,replay){
    try{const saved=JSON.parse(localStorage.getItem('backtest-experiment'));if(saved)remember(saved);}catch(_){}
    node('robustness-replay').addEventListener('click',()=>configuration?replay(configuration):undefined);
    node('robustness-download').addEventListener('click',download);
    node('robustness-inspect').addEventListener('click',()=>result?inspect(result.trials[+node('robustness-trial').value],result.configuration):undefined);
  }
  return {read,render,init};
})();
