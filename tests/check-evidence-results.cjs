'use strict';
// Real bounded presenter and acquisition owner; pages arrive through controlled
// result transport. Rendering never consults a current library or catalog.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const nodes=new Map(),urls=[],downloads=[];
const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',hidden:false,open:false,handlers:{},addEventListener(k,f){this.handlers[k]=f;},setAttribute(){}});return nodes.get(id);};
const exact={variable_id:'variable:old',revision:'sha256:'+'a'.repeat(64)};
const strategy={selection:{ranking:{source:{kind:'formula',...exact},direction:'highest'},rank_from:1,rank_to:70,selection_order:'rank_first',conditions:[]},pool:'legacy',bounds:{},variables:{presentation:[{...exact,name:'Submitted original'}]},builtins:[]};
const holding={rank:1,symbol:'A0000',name:'Company',exchange:'NYSE',sector:'Sector',ranking_value:.1,ranking_unit:'scalar',ranking_display:'percent',ranking_direction:'highest',market_cap:150e6,enterprise_value:180e6,fiscal:'2014-06-30',entry:'2015-01-02',exit:'2015-01-05',return_value:.1,contribution_pp:10,status:'Scheduled exit',metric_multiple:10,scalar_evidence:{scope:'s0',lanes:{}}};
const period={entry:'2015-01-02',exit:'2015-01-05',names:1,portfolio:.1,spy:.02};
const summary={start:period.entry,end:period.exit,cagr:.2,spy_cagr:.03,growth:1.1,seconds:0,coverage:'Complete',options:{strategy}};
let screenWait=null,explanationWait=null,explanationFailure=false,release=null,currentId='1'.repeat(32),robust=0,recorded={};
const context=vm.createContext({console,document:{getElementById:node,createElement:()=>({click(){downloads.push({href:this.href,download:this.download});}})},
 Uint8Array,crypto:require('node:crypto').webcrypto,AbortController,money:v=>String(v),metricLabel:()=>{throw Error('Scalar presentation must use captured meaning');},
 CalendarSettings:{label:()=> 'Monthly',init(){}},EngineControls:{label:()=> 'Original',init(){}},
 RobustnessView:{init(){},render(){robust++;},preview(){}},VariableEvidence:{records:()=>'<p>Detached selected trace</p>'},
 fetch:async(url)=>{
  urls.push(url);assert(url.startsWith('/api/backtest-runs/'));
  const parts=url.split('/'),operation=parts[6],cursor=+parts.at(-1);let value;
  if(operation==='screen'){if(screenWait){const pause=screenWait;screenWait=null;await pause();}value={rows:[{...holding,...recorded,symbol:cursor?'A0064':'A0000'}],cursor,next:cursor?null:64,total:70};}
  else if(operation==='trial')value={summary,short:0,empty:0};
  else if(operation==='curve')value={available:false};
  else if(operation==='periods')value={rows:[{number:1,value:period},{number:2,value:{...period,entry:'2016-01-04',exit:'2016-01-05'}}],cursor:0,next:null,total:2};
  else if(operation==='holdings')value={rows:[{...holding,...recorded,symbol:parts[8]==='2'?'SECOND':'FIRST'}],cursor:0,next:null,total:1};
  else if(operation==='explanations'){if(explanationWait){const pause=explanationWait;explanationWait=null;await pause();}if(explanationFailure){explanationFailure=false;throw Error('Replaced explanation failure');}value={rows:[{scope:'s0',block:{results:[]}}],cursor,next:cursor?null:64,total:65};}
  else throw Error('Unexpected result route '+url);
  return {ok:true,headers:{get:()=>null},json:async()=>structuredClone({...value,identity:parts[3]})};
 }});
for(const file of ['screener.js','contributions.js','result-artifacts.js','backtest-comparison.js','result-explorer.js','asset-curve.js','evidence-results.js','schedule.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser',file),'utf8'),context);
const run=code=>vm.runInContext(code,context),tick=()=>new Promise(resolve=>setImmediate(resolve));
function artifact(kind='latest',version=4,id=currentId){return {version,kind,settings:{mode:kind,strategy},result:{...summary,producer:{engine:'original',label:'Original'},configuration:{seed:42},trials:[],distribution:{}},catalog:{metrics:{},filters:{}},presentation:{},evidence:{id,format_version:version===4?2:1,trials:kind==='latest'?0:1,periods:kind==='latest'?0:1,holdings:kind==='latest'?70:1}};}
async function show(value){context.artifact=value;run('{const completed=ResultArtifacts.publish(artifact);EvidenceResults.show(completed)}');await tick();await tick();}
(async()=>{
 run('ScheduleView.init()');
 // Completed producer text belongs to the artifact in every mode. Retain an
 // actually displayed legacy custom result before showing a numerical January
 // result through its direct bounded presenter, as ordinary completion does.
 const prior=artifact('custom',2,'8'.repeat(32));prior.result.options={metric:'ev_ebitda'};prior.result.periods=[{...period,holdings:[holding]}];
 context.metricLabel=()=> 'Retained EV/EBITDA';context.prior=prior;
 run('ScheduleView.show(ResultArtifacts.publish(prior))');
 assert.equal(node('result-producer').textContent,'Calculated by Original.');assert.equal(node('result-producer').hidden,false);
 context.metricLabel=()=>{throw Error('Scalar presentation must use captured meaning');};
 const numerical=artifact('january',4,'9'.repeat(32));numerical.settings.engine='experimental';numerical.result.producer={engine:'experimental',label:'New engine — experimental'};
 node('backtest-engine').value='original';await show(numerical);
 assert.equal(node('scalar-result-producer').textContent,'Calculated by New engine — experimental.');assert.equal(node('scalar-result-producer').hidden,false);assert.equal(node('scalar-evidence-view').hidden,false);
 assert.equal(node('result-producer').textContent,'Calculated by New engine — experimental.');assert.equal(node('result-producer').hidden,true);
 const numericalLatest=artifact('latest',4,'a'.repeat(32));numericalLatest.settings.engine='experimental';numericalLatest.result.producer=structuredClone(numerical.result.producer);await show(numericalLatest);
 assert.equal(node('scalar-result-producer').textContent,'Calculated by New engine — experimental.');assert.equal(node('custom-view').hidden,true);assert.equal(node('scalar-result-producer').hidden,false);
 // A saved snapshot is decoded and reopened while the current selector says
 // Original. The original producer survives both that change and trial views.
 const reopened=JSON.parse(JSON.stringify(numerical));reopened.evidence.id='b'.repeat(32);node('backtest-engine').value='original';await show(reopened);
 assert.equal(node('scalar-result-producer').textContent,'Calculated by New engine — experimental.');
 for(const kind of ['custom','random']){
  context.recorded={...structuredClone(reopened),kind,evidence:{...reopened.evidence,id:(kind==='custom'?'c':'d').repeat(32)}};
  run('ScheduleView.show(ResultArtifacts.publish(recorded))');await tick();await tick();
  assert.equal(node('scalar-result-producer').textContent,'Calculated by New engine — experimental.');assert.equal(node('result-producer').hidden,true);
 }
 robust=0;
 // Requested settings never establish a missing historical producer.
 const unknown=structuredClone(prior);delete unknown.result.producer;unknown.settings.engine='experimental';context.prior=unknown;context.metricLabel=()=> 'Retained EV/EBITDA';
 run('ScheduleView.show(ResultArtifacts.publish(prior))');assert.equal(node('result-producer').textContent,'Producer not recorded in this result.');assert.equal(node('result-producer').hidden,false);
 context.metricLabel=()=>{throw Error('Scalar presentation must use captured meaning');};
 await show(artifact());
 assert(node('scalar-screen-rows').innerHTML.includes('<td>10.00%</td>'));assert(node('scalar-evidence-summary').textContent.includes('Submitted original'));
 // A capture/1 row has no step evidence; it is never reconstructed.
 assert(node('scalar-screen-rows').innerHTML.includes('Step trail not recorded in this result.'));assert(node('scalar-screen-page').textContent.includes('of 70'));
 node('scalar-screen-next').handlers.click();await tick();assert(node('scalar-screen-rows').innerHTML.includes('A0064'));assert(node('scalar-screen-next').disabled);
 node('scalar-download-rows').handlers.click();node('scalar-download-evidence').handlers.click();assert(downloads[0].href.includes('/export/screen/'));assert(downloads[1].href.includes('/export/evidence/'));
 node('scalar-screen-rows').handlers.click({target:{dataset:{scalarExplain:'0'}}});await tick();assert(node('scalar-explanation-content').innerHTML.includes('Submitted original'));
 // A selected-company reply cannot survive navigation within the same screen.
 for(const failed of [false,true]){
  explanationFailure=failed;explanationWait=()=>new Promise(resolve=>release=resolve);node('scalar-screen-rows').handlers.click({target:{dataset:{scalarExplain:'0'}}});await tick();
  node(node('scalar-screen-back').disabled?'scalar-screen-next':'scalar-screen-back').handlers.click();await tick();release();await tick();assert.equal(node('scalar-explanation').open,false);assert.equal(node('scalar-explanation-content').innerHTML,'');assert(!node('screen-error').textContent.includes('Replaced explanation failure'));
 }
 // A late rejection from Next explanation page is fenced in the same way.
 node('scalar-screen-rows').handlers.click({target:{dataset:{scalarExplain:'0'}}});await tick();
 explanationFailure=true;explanationWait=()=>new Promise(resolve=>release=resolve);node('scalar-explanation-next').handlers.click();await tick();
 node('scalar-screen-back').handlers.click();await tick();release();await tick();assert.equal(node('scalar-explanation-content').innerHTML,'');assert(!node('screen-error').textContent.includes('Replaced explanation failure'));
 // A slow page from a replaced artifact never overwrites the new screen.
 screenWait=()=>new Promise(resolve=>release=resolve);context.artifact=artifact('latest',4,'2'.repeat(32));run('EvidenceResults.show(ResultArtifacts.publish(artifact))');await tick();
 await show(artifact('latest',4,'3'.repeat(32)));const current=node('scalar-screen-rows').innerHTML;release();await tick();assert.equal(node('scalar-screen-rows').innerHTML,current);
 // Fire the real schedule handlers with no custom result, then with retained
 // eager and bounded custom results. January controls always use January.
 for(const retained of [null,2,3]){
  if(retained){const old=artifact('custom',retained,'7'.repeat(32));old.result={...summary,options:{metric:'ev_ebitda'},periods:[{...period,holdings:[holding]}]};context.old=old;run('ResultArtifacts.publish(old)');}
  await show(artifact('january',4,'4'.repeat(32)));assert.equal(node('custom-view').hidden,false);assert(node('schedule-stock-body').innerHTML.includes('<td>10.00%</td>'));assert.equal(node('schedule-explanation-head').hidden,false);assert(node('schedule-dates').textContent.includes('January books'));
  node('schedule-period').value='2';node('schedule-period').handlers.change();await tick();await tick();assert(node('schedule-stock-body').innerHTML.includes('SECOND'));assert(!node('schedule-stock-body').innerHTML.includes('FIRST'));
  for(const kind of ['holdings','returns']){node('schedule-download-'+kind).handlers.click();assert.equal(downloads.at(-1).href,'/api/backtest-runs/'+'4'.repeat(32)+'/reader/export/'+kind+'/1');}
 }
 // Period navigation invalidates a delayed selected-company explanation.
 for(const failed of [false,true]){
  const symbol=node('schedule-stock-body').innerHTML.includes('SECOND')?'SECOND':'FIRST';explanationFailure=failed;explanationWait=()=>new Promise(resolve=>release=resolve);node('schedule-stock-body').onclick({target:{dataset:{storedExplain:symbol}}});await tick();
  node('schedule-period').value=node('schedule-period').value==='1'?'2':'1';node('schedule-period').handlers.change();await tick();release();await tick();assert.equal(node('scalar-explanation').open,false);assert.equal(node('scalar-explanation-content').innerHTML,'');assert(!node('screen-error').textContent.includes('Replaced explanation failure'));
 }
 // Random results retain the existing distribution and bounded trial inspection.
 context.artifact=artifact('random',4,'5'.repeat(32));
 context.artifact.result.configuration.options={strategy};
 context.artifact.result.completed=2;context.artifact.result.valid=2;context.artifact.result.incomplete=0;
 context.artifact.result.trials=[1,2].map(trial=>({trial,start:'2015-01-02',end:'2017-01-02',periods:2,dates:['2015-01-02','2016-01-04']}));
 run('ScheduleView.show(ResultArtifacts.publish(artifact))');await tick();assert.equal(robust,1);assert(node('schedule-results').hidden);
 assert(!node('result-explorer').open&&!node('result-explorer').hidden);
 assert.equal(node('explore-title').textContent,'Explore all 2 trials');
 node('result-explorer').open=true;node('result-explorer').handlers.toggle();await tick();assert.equal(node('explore-rank-to').value,'70');
 run('EvidenceResults.show(ResultArtifacts.forView("custom"),2)');await tick();
 assert.equal(node('explore-title').textContent,'Explore all 2 trials','Inspecting an original trial keeps the batch controls');
 // The per-trial block of a random-date result names its trial.
 run('ScheduleView.inspectOriginal(1)');await tick();assert.equal(node('schedule-trial-title').textContent,'Trial 1 of 2');
 // The same extracted presenter still accepts codec1/artifact3.
 context.metricLabel=()=> 'Retained EV/EBITDA';await show(artifact('custom',3,'6'.repeat(32)));assert.equal(node('schedule-explanation-head').hidden,true);assert(node('schedule-stock-body').innerHTML.includes('10.00'));assert(!node('schedule-stock-body').innerHTML.includes('data-stored-explain'));
 // A chain capture summarizes its last Rank and step count from the record itself.
 const chain=artifact('custom',4,'7'.repeat(32));
 chain.settings={mode:'custom',strategy:{format:'strategy-capture',version:2,universe:{pool:'cached'},builtins:[{id:'metric:ev_ebitda:yield',label:'Recorded EV/EBITDA yield',unit:'scalar',display:'percent'}],
  variables:{presentation:[{...exact,name:'Submitted original'}],program:{definitions:[{...exact,unit:'scalar',display:'percent'}]}},
  steps:[{kind:'rank',source:{kind:'formula',...exact},direction:'lowest',rank_from:1,rank_to:200},{kind:'filter',source:{kind:'field',field:'sector'},op:'eq',threshold:'Energy'},
   {kind:'filter',source:{kind:'formula',...exact},op:'ge',threshold:{value:'0',unit:'number'}},{kind:'rank',source:{kind:'builtin',id:'metric:ev_ebitda:yield'},direction:'highest',rank_from:20,rank_to:40}]}};
 chain.result.options={strategy:chain.settings.strategy};
 // Each step shows its recorded value and rank or pass; the repeated formula
 // reads its own lane, and the sector Filter reads the holding's own field.
 const formulaLane={scope:'s0',...exact,value:.05,valid:true};
 recorded={sector:'Energy',scalar_evidence:{scope:'s0',steps:[7,null,null,25],lanes:{s0:formulaLane,s2:formulaLane,s3:{scope:'s0',source:{kind:'builtin',id:'metric:ev_ebitda:yield'},canonical:.3,unit:'scalar',valid:true}}}};
 await show(chain);
 assert.equal(node('scalar-evidence-summary').textContent,'Recorded EV/EBITDA yield · highest first · ranks 20–40 · 4 steps. These values and downloads use original captured evidence.');
 // Plain recorded names; a scalar value's display already carries its unit.
 for(const line of ['Step 1 · Rank · Submitted original · 5.00% · rank 7 (kept 1–200)','Step 2 · Filter · Sector · Energy · passed',
   'Step 3 · Filter · Submitted original · 5.00% · passed','Step 4 · Rank · Recorded EV/EBITDA yield · 30.00% · rank 25 (kept 20–40)'])
  assert(node('schedule-stock-body').innerHTML.includes('<li>'+line+'</li>'),line);
 // A latest chain shows the same trail and its recorded market date.
 const latestChain=artifact('latest',4,'6'.repeat(32));latestChain.settings={mode:'latest',strategy:chain.settings.strategy};latestChain.result.asof='2015-01-05';
 await show(latestChain);
 assert(node('scalar-evidence-summary').textContent.startsWith('Latest cached session 2015-01-05 · '));
 assert(node('scalar-screen-rows').innerHTML.includes('<li>Step 2 · Filter · Sector · Energy · passed</li>'));assert(node('scalar-screen-rows').innerHTML.includes('data-scalar-explain="0"'));
 recorded={};
 // A saved version-1 January result opens in the same dated view, from its
 // stored rows, without any request.
 const before=urls.length;
 context.saved={version:1,kind:'january',settings:{mode:'january',first:2015,last:2016,metric:'ev_ebitda',rank_from:1,rank_to:50},
  result:{options:{first:2015,last:2016,metric:'ev_ebitda',rank_from:1,rank_to:50},first:'2015-01-02',end:'2016-10-20',growth:1.1,spy_growth:1.02,cagr:.05,spy_cagr:.01,short_years:[],empty_years:[],
   years:[{year:2015,names:1,portfolio:.1,spy:.02,holdings:[{...holding,symbol:'JAN15'}]},{year:2016,names:1,portfolio:0,spy:0,holdings:[{...holding,symbol:'JAN16',return_value:0}]}]},
  catalog:{metrics:{},filters:{}},context:{notes:[]}};
 run('ScheduleView.show(ResultArtifacts.publish(ResultArtifacts.decode(saved)))');await tick();
 // Only the replaced bounded display is released; nothing is read or calculated.
 assert(urls.slice(before).every(url=>url.endsWith('/reader')));assert.equal(node('schedule-results').hidden,false);assert.equal(node('robustness-results').hidden,true);
 assert.equal(node('schedule-dates').textContent,'2015-01-02 → 2016-10-20 · January books');
 assert(node('schedule-rows').innerHTML.includes('<td>2015-01-02</td><td>2016</td><td>1</td>'));
 assert(node('schedule-rows').innerHTML.includes('<td>2016</td><td>2016-10-20</td>'));
 assert(node('schedule-stock-body').innerHTML.includes('JAN16'));assert(!node('schedule-coverage').textContent.includes('Computed in'));
 node('schedule-period').value='0';node('schedule-period').handlers.change();assert(node('schedule-stock-body').innerHTML.includes('JAN15'));
 assert(node('schedule-attribution').innerHTML.includes('Top 10 contributors'));
 assert(!urls.some(url=>url.includes('/variables')||url.includes('/catalog')));
 console.log('Passed: bounded scalar latest/January/random presentation, saved version-1 January results in the dated view without requests, immutable producer labels across legacy replacement/saved reopening/current selector changes, page replacement fencing, selected explanations, complete download capabilities and unchanged artifact3 presentation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
