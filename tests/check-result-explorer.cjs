'use strict';
// Actual reader transport and explorer controller; only HTTP and DOM are fixtures.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const nodes=new Map(),requests=[],downloads=[];let deferred=null,projected=null;
const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',innerHTML:'',textContent:'',hidden:false,open:false,handlers:{},addEventListener(event,fn){this.handlers[event]=fn;}});return nodes.get(id);};
const periods=Array.from({length:70},(_,i)=>({entry:(1997+i)+'-01-02',exit:(1998+i)+'-01-02',names:30,portfolio:.1,spy:.05,
 holdings:Array.from({length:30},(_,rank)=>({symbol:'S'+rank,rank:rank+1,return_value:.1}))}));
const result={start:periods[0].entry,end:periods.at(-1).exit,periods,options:{rank_from:1,rank_to:30},growth:1.2,spy_growth:1.1,cagr:.01,spy_cagr:.005};
const info={summary:result,periods:70,empty:0,short:0};
const response=value=>({ok:true,headers:{get:()=>null},json:async()=>structuredClone(value)});
const context=vm.createContext({AbortController,console,document:{getElementById:node,createElement:()=>({click(){downloads.push(this.href);}})},
 fetch:async(url,options={})=>{
  requests.push({url,options});
  if(options.method==='DELETE')return response({released:true});
  let selected,id;
  if(url==='/api/backtest-exploration')selected=JSON.parse(options.body).selection;
  else{
   const parts=url.split('/');id=parts[3];
   if(parts[5]==='explore'){
    selected=Object.fromEntries(['trial','period_from','period_to','rank_from','rank_to'].map((key,i)=>[key,i===0&&parts[6]==='all'?'all':+parts[6+i]]));
   }else{
    assert.equal(parts[6],'periods');
    const cursor=+parts[8],end=Math.min(cursor+64,periods.length);
    return response({identity:id,rows:periods.slice(cursor,end).map(({holdings,...value},i)=>({number:cursor+i+1,value})),cursor,next:end<periods.length?end:null,total:70});
   }
  }
  const value=selected.trial==='all'?{...projected,identity:id,exploration:{...selected,start:'2010-01-02',end:'2015-01-25',periods:5}}:{...selected,identity:id,start:periods[selected.period_from-1].entry,end:periods[selected.period_to-1].exit,
   periods:selected.period_to-selected.period_from+1,total_return:selected.rank_to/100,spy_total_return:.08,growth:1+selected.rank_to/100,cagr:.03,spy_cagr:.02,empty:0,short:0};
  if(deferred){const wait=deferred;deferred=null;await wait();}
  return response(value);
 }});
for(const name of ['result-artifacts.js','backtest-comparison.js','robustness.js','result-explorer.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser',name),'utf8'),context);
const run=code=>vm.runInContext(code,context),tick=()=>new Promise(resolve=>setImmediate(resolve));
const input=id=>node('explore-'+id),panel=()=>node('result-explorer');
const applied=()=>requests.filter(row=>row.url==='/api/backtest-exploration'||row.url.includes('/reader/explore/'));
const change=(id,value)=>{input(id).value=String(value);input(id).handlers.input();};
async function show(artifact,trial=1,details=info){
 context.input=artifact;context.details=details;context.trial=trial;
 run('{const published=ResultArtifacts.publish(input);ResultExplorer.show(published,trial,details)}');
 panel().open=true;panel().handlers.toggle();await tick();await tick();
}
const artifact=()=>({version:2,kind:'custom',settings:{mode:'custom',rank_from:1,rank_to:30},result:structuredClone(result),presentation:{},catalog:{}});
(async()=>{
 run('ResultExplorer.init()');
 const original=artifact(),before=JSON.stringify(original);
 await show(original);
 assert.equal(requests.length,0,'Opening eager exploration reads only the captured result');
 assert(input('period-from').innerHTML.includes('2008-01-02'));assert(input('period-to').innerHTML.includes('2016-01-02'));
 assert.equal(input('period-to').value,'70');assert.equal(input('rank-to').value,'30');
 assert.equal(input('strategy-return').textContent,'20.00%');
 change('period-from',12);change('period-to',19);change('rank-from',20);change('rank-to',30);
 input('apply').handlers.click();await tick();
 const first=JSON.parse(applied().at(-1).options.body);
 assert.deepEqual(first.result,original.result);assert.deepEqual(first.selection,{trial:1,period_from:12,period_to:19,rank_from:20,rank_to:30});
 assert(input('window').textContent.includes('2008-01-02 → 2016-01-02'));assert(input('window').textContent.includes('ranks 20–30'));
 assert.equal(input('strategy-return').textContent,'30.00%');assert.equal(JSON.stringify(original),before);
 const count=applied().length;change('rank-to',31);input('apply').handlers.click();await tick();assert.equal(applied().length,count);
 assert(input('status').textContent.includes('within the original'));
 input('reset').handlers.click();assert.equal(input('strategy-return').textContent,'20.00%');assert.equal(applied().length,count);
 // Editing and applying a newer selection fences a late reply, even when HTTP ignores abort.
 let resume;deferred=()=>new Promise(resolve=>resume=resolve);
 change('rank-to',20);input('apply').handlers.click();await tick();const pending=applied().at(-1);
 change('rank-to',10);assert(pending.options.signal.aborted);input('apply').handlers.click();await tick();
 assert.equal(input('strategy-return').textContent,'10.00%');resume();await tick();assert.equal(input('strategy-return').textContent,'10.00%');
 // Reset cancels pending work and restores recorded precision and window.
 deferred=()=>new Promise(resolve=>resume=resolve);input('apply').handlers.click();await tick();
 input('reset').handlers.click();resume();await tick();assert.equal(input('strategy-return').textContent,'20.00%');
 // The reader can still summarize a single original trial independently.
 const random=artifact();random.kind='random';random.settings.mode='random';
 const second=structuredClone(result);second.growth=1.42;
 random.result={trial_results:[random.result,second]};
 await show(random,2,{...info,summary:second});input('apply').handlers.click();await tick();
 assert.deepEqual(JSON.parse(applied().at(-1).options.body).result,second);
 assert.equal(JSON.parse(applied().at(-1).options.body).selection.trial,1);
 // A saved 24-trial result shows its all-trial panel closed; its controls load when it opens.
 const stats=mean=>({n:24,mean,median:mean,p10:mean,p25:mean,p75:mean,p90:mean,min:mean,max:mean,stddev:0});
 const distributions=mean=>Object.fromEntries(['cagr','spy_cagr','excess_cagr','total_return','growth'].map(key=>[key,stats(mean)]));
 const batch=artifact();batch.kind='random';batch.settings={mode:'random',rank_from:1,rank_to:50};
 const trialRows=Array.from({length:24},(_,i)=>({trial:i+1,start:'2000-01-01',end:'2025-01-27',first_trade:'2000-01-02',periods:25,
  dates:Array.from({length:25},(_,j)=>(2000+j)+'-01-02'),cagr:.15,spy_cagr:.08,spy_growth:2,excess_cagr:.07,total_return:3,growth:4,empty_periods:0,short_periods:0}));
 batch.result={completed:24,valid:24,incomplete:0,unique_schedules:24,beat_spy:24,note:'Original',
  configuration:{seed:42,options:{rank_from:1,rank_to:50},blocks:Array.from({length:25},(_,i)=>({start:(2000+i)+'-01-01'}))},
  trials:trialRows,distributions:distributions(.15),trial_results:Array.from({length:24},()=>structuredClone(result))};
 const batchBefore=JSON.stringify(batch);
 projected={...batch.result,note:'Selected',distributions:distributions(.42),trials:trialRows.map(row=>({...row,cagr:.42,periods:5,start:'2010-01-02',end:'2015-01-25'}))};
 projected.trials[0].empty_periods=1;
 context.input=batch;context.details={summary:batch.result,periods:25};
 run("ResultExplorer.show(ResultArtifacts.publish(input),'all',details)");
 assert(!panel().open&&!panel().hidden);assert.equal(input('title').textContent,'Explore all 24 trials');
 assert(input('apply').disabled);assert.equal(input('period-from').innerHTML,'');
 // Opening the panel, Apply and Reset keep the trial that the user chose for inspection.
 node('robustness-trial').value='2';
 panel().open=true;panel().handlers.toggle();await tick();assert(!input('apply').disabled);assert.equal(node('robustness-trial').value,'2');
 assert(input('summary').hidden&&!input('trials').hidden);assert.equal(node('robustness-mean').textContent,'15.00%');
 assert(node('robustness-scope').hidden,'The original result carries no selection notice');
 assert(input('period-from').innerHTML.includes('2010-01-01'));
 assert(input('period-to').innerHTML.includes('2015-01-01'));
 change('period-from',11);change('period-to',15);change('rank-from',20);change('rank-to',30);
 input('apply').handlers.click();await tick();
 const all=JSON.parse(applied().at(-1).options.body);
 assert.equal(all.result.trial_results.length,24);
 assert.deepEqual(all.selection,{trial:'all',period_from:11,period_to:15,rank_from:20,rank_to:30});
 assert.equal(node('robustness-mean').textContent,'42.00%');
 // The chart and tables that follow the selection say so; Reset removes the notice.
 assert(!node('robustness-scope').hidden);assert(node('robustness-scope').textContent.includes('2010-01-02 → 2015-01-25 · ranks 20–30'));
 assert(input('coverage').textContent.includes('Trials with cash periods: 1.'));
 assert(input('coverage').textContent.includes('SPY keeps its period return'));
 assert(node('robustness-trials').innerHTML.includes('2010-01-02'));
 assert(input('window').textContent.includes('ranks 20–30'));
 node('robustness-measure').value='cagr';
 run('RobustnessView.init(()=>{})');
 node('robustness-measure').handlers.change();assert(node('robustness-chart').innerHTML.includes('mean 42.00%'));
 const allCount=applied().length;input('reset').handlers.click();
 assert.equal(node('robustness-mean').textContent,'15.00%');assert.equal(applied().length,allCount);
 assert(node('robustness-scope').hidden&&!node('robustness-scope').textContent);
 assert.equal(JSON.stringify(batch),batchBefore);
 for(const version of [3,4]){
  const bounded=structuredClone(batch);bounded.version=version;delete bounded.result.trial_results;
  bounded.evidence={id:String(version).repeat(32),format_version:version===4?2:1,trials:24,periods:600,holdings:30000};
  const pageCount=requests.filter(row=>row.url.includes('/page/')).length;
  await show(bounded,'all',{summary:bounded.result,periods:25});
  assert.equal(requests.filter(row=>row.url.includes('/page/')).length,pageCount,'Batch controls use saved date metadata');
  change('period-from',11);change('period-to',15);change('rank-from',20);change('rank-to',30);
  input('apply').handlers.click();await tick();assert(applied().at(-1).url.endsWith('/reader/explore/all/11/15/20/30'));
  assert.equal(node('robustness-mean').textContent,'42.00%');
 }
 // Reset keeps old unavailable originals; Apply uses the server's cash summary.
 const old=artifact();old.result.growth=null;old.result.cagr=null;
 old.result.periods[0]={...old.result.periods[0],holdings:[],names:0,portfolio:null};
 await show(old,1,{...info,summary:old.result,empty:1,short:1});
 assert.equal(input('strategy-return').textContent,'—');
 assert(input('coverage').textContent.includes('select Apply'));
 input('apply').handlers.click();await tick();assert.equal(input('strategy-return').textContent,'30.00%');
 input('reset').handlers.click();assert.equal(input('strategy-return').textContent,'—');
 assert.equal(old.result.periods[0].portfolio,null);
 // Bounded artifacts retain their existing reader and independent download capability.
 for(const version of [3,4]){
  const bounded=artifact();bounded.version=version;bounded.evidence={id:String(version).repeat(32),format_version:version===4?2:1,trials:1,periods:70,holdings:2100};
  await show(bounded);
  assert(requests.some(row=>row.url.endsWith('/page/periods/1/64')));
  change('period-from',12);change('period-to',19);change('rank-to',10);input('apply').handlers.click();await tick();
  assert(applied().at(-1).url.endsWith('/reader/explore/1/12/19/1/10'));
  assert.equal(input('strategy-return').textContent,'10.00%');
  run('ResultArtifacts.reader(ResultArtifacts.forView("custom")).download("holdings")');
  assert(downloads.at(-1).endsWith('/reader/export/holdings/1'));
 }
 // A chain's explorer bounds come from its last Rank, here ranks 20–40.
 const chain=artifact();chain.version=4;chain.evidence={id:'c'.repeat(32),format_version:2,trials:1,periods:70,holdings:2100};
 const steps=[{kind:'rank',source:{kind:'builtin',id:'filter:pe'},direction:'lowest',rank_from:1,rank_to:200},{kind:'rank',source:{kind:'builtin',id:'filter:pe'},direction:'highest',rank_from:20,rank_to:40},{kind:'filter',source:{kind:'field',field:'sector'},op:'eq',threshold:'Energy'}];
 const chainOptions={strategy:{format:'strategy-capture',version:2,universe:{pool:'cached'},steps,builtins:[],variables:null}};
 chain.settings={mode:'custom',...chainOptions};
 await show(chain,1,{...info,summary:{...result,options:chainOptions}});
 assert.equal(input('rank-from').min,'20');assert.equal(input('rank-to').max,'40');
 change('period-from',12);change('period-to',19);change('rank-from',25);change('rank-to',40);input('apply').handlers.click();await tick();
 assert(applied().at(-1).url.endsWith('/reader/explore/1/12/19/25/40'));
 change('rank-to',41);const chainCount=applied().length;input('apply').handlers.click();await tick();assert.equal(applied().length,chainCount,'Ranks stay within the last Rank');
 // Replacing a result releases its reader, aborts work and prevents late publication.
 deferred=()=>new Promise(resolve=>resume=resolve);input('apply').handlers.click();await tick();
 await show(artifact());const fresh=input('window').textContent;resume();await tick();assert.equal(input('window').textContent,fresh);
 run('ResultExplorer.clear()');assert(panel().hidden);
 assert(requests.every(row=>row.url==='/api/backtest-exploration'||row.url.includes('/reader')));
 const html=fs.readFileSync(path.join(__dirname,'../website/browser/template.html'),'utf8');
 assert(html.indexOf('id="result-explorer"')>html.indexOf('</form>'));
 assert(html.includes('Download original holdings'));
 // Explore follows the main chart and the tables of both kinds of result.
 for(const id of ['robustness-chart','robustness-trials','schedule-chart','schedule-rows'])assert(html.indexOf('id="result-explorer"')>html.indexOf('id="'+id+'"'),id);
 console.log('Passed: closed all-24-trial date/rank controls that load on opening, the selection notice, combined statistics and chart, eager and both codec transports, original artifacts, reset, validation and cancellation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
