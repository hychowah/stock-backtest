/* Temporary date/rank selections over an immutable completed result. The panel
   starts closed and reads its date labels when it opens.
   Only the server aggregates returns. Original views and saving stay separate. */
const ResultExplorer=(()=>{
  let active=null;
  const node=id=>document.getElementById('explore-'+id);
  const panel=()=>document.getElementById('result-explorer');
  const format=value=>value==null?'—':(value*100).toFixed(2)+'%';
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const valid=state=>active===state&&ResultArtifacts.current(state.artifact);
  function cancel(state){
    if(!state)return;
    state.generation++;state.controller?.abort();state.controller=null;panel().ariaBusy='false';
  }
  function clear(){cancel(active);active=null;panel().hidden=true;panel().open=false;}
  function render(value){
    if(active.trial==='all'){
      const view=value.exploration??{...value.configuration.options,start:value.trials[0]?.start,end:value.trials[0]?.end,periods:active.info.periods};
      node('window').textContent=view.start+' → '+view.end+' · ranks '+(view.rank_from??active.firstRank)+'–'+(view.rank_to??active.lastRank)+' · '+view.periods+' holding periods per trial · '+value.completed+' trials';
      const cash=value.trials.filter(row=>row.empty_periods>0&&Number.isFinite(row.growth)).length;
      node('coverage').textContent=value.valid+' complete trials; '+value.incomplete+' incomplete trials. Trials with cash periods: '+cash+'. Empty selections hold cash at 0%; SPY keeps its period return. Counts appear in the trial table. '+(value.trials.some(row=>row.empty_periods>0&&row.growth===null)?'Older recorded totals remain unavailable; select Apply for a cash-based summary.':'');
      node('status').textContent='Summary across all saved trials. No backtest was run.';
      RobustnessView.preview(value,value.exploration?view:null);return;
    }
    node('window').textContent=value.start+' → '+value.end+' · ranks '+value.rank_from+'–'+value.rank_to+' · '+value.periods+' holding periods';
    node('strategy-return').textContent=format(value.total_return);
    node('spy-return').textContent=format(value.spy_total_return);
    node('strategy-cagr').textContent=format(value.cagr);
    node('spy-cagr').textContent=format(value.spy_cagr);
    node('coverage').textContent=value.short+' short periods; '+value.empty+' empty periods.'+(value.empty?(value.growth==null?' Recorded return is unavailable; select Apply to treat empty periods as cash.':' Empty periods hold cash at 0%; SPY keeps its period return.'):'')+(value.cash_days?' Includes '+value.cash_days+' initial days in cash.':'')+(value.growth!=null&&value.cagr==null?' Exact boundary dates were not saved, so CAGR is unavailable.':'');
    node('status').textContent='Summary of saved returns. No backtest was run.';
  }
  function reset(){
    const state=active;if(!state?.loaded||!valid(state))return;
    cancel(state);
    node('period-from').value='1';node('period-to').value=String(state.info.periods);
    node('rank-from').value=String(state.firstRank);node('rank-to').value=String(state.lastRank);
    const r=state.info.summary;
    if(state.trial==='all'){render(r);return;}
    render({...r,rank_from:state.firstRank,rank_to:state.lastRank,periods:state.info.periods,
      empty:state.info.empty,short:state.info.short,
      total_return:r.growth==null?null:r.growth-1,spy_total_return:r.spy_growth==null?null:r.spy_growth-1});
  }
  async function load(){
    const state=active;if(!state||state.loaded||state.loading||!valid(state))return;
    state.loading=true;node('status').textContent='Reading saved holding periods…';
    try{
      let cursor=0,from='',to='';
      if(state.trial==='all'){
        const result=state.info.summary,rows=result.trials,blocks=result.configuration.blocks;
        if(!rows.length||!state.info.periods||rows.some(row=>row.periods!==state.info.periods||row.dates?.length!==state.info.periods))throw Error('Complete saved trial dates are required.');
        const label=dates=>{const sorted=dates.slice().sort();return sorted[0]===sorted.at(-1)?sorted[0]:sorted[0]+' … '+sorted.at(-1);};
        for(let i=0;i<state.info.periods;i++){
          const entry=blocks?.[i]?.start??label(rows.map(row=>row.dates[i]));
          const exit=blocks?.[i+1]?.start??label(rows.map(row=>row.dates[i+1]??row.end));
          from+='<option value="'+(i+1)+'">'+escape(entry)+'</option>';
          to+='<option value="'+(i+1)+'">'+escape(exit)+'</option>';
        }
      }else do{
        const page=await state.reader.periods(state.trial,cursor);if(!valid(state))return;
        // Keep only date labels for the controls, never period or holding rows.
        for(const {number,value} of page.rows){
          from+='<option value="'+number+'">'+escape(value.entry)+'</option>';
          to+='<option value="'+number+'">'+escape(value.exit)+'</option>';
        }
        cursor=page.next;
      }while(cursor!==null);
      node('period-from').innerHTML=from;node('period-to').innerHTML=to;
      state.loaded=true;node('apply').disabled=false;node('reset').disabled=false;reset();
    }catch(error){if(valid(state))node('status').textContent=error.message;}
    finally{state.loading=false;}
  }
  function show(artifact,trial,info){
    clear();
    const options=trial==='all'?info.summary.configuration.options:info.summary.options;
    const rank=BacktestComparison.finalRank(options??artifact.settings);
    const state={artifact,trial,info,reader:ResultArtifacts.reader(artifact),generation:0,
      firstRank:rank.rank_from,lastRank:rank.rank_to,loaded:false,loading:false};
    active=state;panel().hidden=false;
    node('title').textContent=trial==='all'?'Explore all '+info.summary.completed+' trials':'Explore this result';
    node('from-label').textContent=trial==='all'?'From entry block':'From entry';
    node('to-label').textContent=trial==='all'?'Through exit block':'Through exit / mark';
    node('summary').hidden=trial==='all';node('trials').hidden=trial!=='all';
    for(const id of ['rank-from','rank-to']){node(id).min=String(state.firstRank);node(id).max=String(state.lastRank);}
    node('apply').disabled=true;node('reset').disabled=true;node('period-from').innerHTML='';node('period-to').innerHTML='';
    node('window').textContent='';node('coverage').textContent='';node('status').textContent='Choose a saved time window and stock ranks.';
    for(const id of ['strategy-return','spy-return','strategy-cagr','spy-cagr'])node(id).textContent='—';
  }
  async function apply(){
    const state=active;if(!state?.loaded||!valid(state))return;
    cancel(state);
    const generation=state.generation;
    const selection={trial:state.trial,period_from:+node('period-from').value,period_to:+node('period-to').value,
      rank_from:+node('rank-from').value,rank_to:+node('rank-to').value};
    if(![selection.period_from,selection.period_to,selection.rank_from,selection.rank_to].every(Number.isInteger)||selection.period_from<1||selection.period_to>state.info.periods||selection.period_from>selection.period_to||selection.rank_from<state.firstRank||selection.rank_to>state.lastRank||selection.rank_from>selection.rank_to){
      node('status').textContent='Choose increasing periods and ranks within the original result.';return;
    }
    state.controller=new AbortController();panel().ariaBusy='true';node('status').textContent='Summarizing saved returns…';
    try{
      const value=await state.reader.explore(selection,{signal:state.controller.signal});
      if(valid(state)&&generation===state.generation)render(value);
    }catch(error){if(valid(state)&&generation===state.generation&&error.name!=='AbortError')node('status').textContent=error.message;}
    finally{if(valid(state)&&generation===state.generation){state.controller=null;panel().ariaBusy='false';}}
  }
  function init(){
    panel().addEventListener('toggle',()=>{if(panel().open)void load();});
    node('apply').addEventListener('click',()=>void apply());node('reset').addEventListener('click',reset);
    for(const id of ['period-from','period-to','rank-from','rank-to'])node(id).addEventListener('input',()=>{
      cancel(active);node('status').textContent='Selection changed. Select Apply to update the summary.';
    });
  }
  return {init,show,clear};
})();
