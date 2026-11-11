const fs=require('fs'),vm=require('vm'),assert=require('assert');
const output=require('path').resolve(process.argv[2]||require('path').join(__dirname,'../website/local'));
const html=fs.readFileSync(require('path').join(output,'index.html'),'utf8');
const els=new Map();
const embedded=html.match(/<script id="screening-data" type="application\/json">([\s\S]*?)<\/script>/)[1];
const prepared=JSON.parse(embedded),screener=require('../website/browser/screener.js');
const latestDate=prepared.latest.metadata.asof;
const latestCount=limit=>screener.latestScreen(prepared,{pool:'cached',rank_to:limit}).stocks.length;
function el(id){if(!els.has(id))els.set(id,{id,innerHTML:'',textContent:'',value:'',hidden:(html.match(new RegExp('<[^>]*id="'+id+'"[^>]*>'))?.[0]||'').includes(' hidden'),open:false,disabled:false,dataset:{},style:{},handlers:{},addEventListener(k,f){this.handlers[k]=f},setAttribute(k,v){this.attributes??={};this.attributes[k]=String(v)},querySelectorAll(){return []},focus(){},append(child){child.parentNode=this;},showModal(){this.open=true;},close(){this.open=false;this.handlers.close?.();},closest(){return this}});return els.get(id)}
const document={getElementById:el,querySelector:s=>s==='.pill'?el('pill'):el(s.replace(/^#/,'')),querySelectorAll:()=>[]};
el('screening-data').textContent=embedded;
const storage=new Map();
const ctx=vm.createContext({document,console,Date,Math,scrollTo(){},AbortController,crypto:require('crypto').webcrypto,Uint8Array,setTimeout,clearTimeout,localStorage:{get length(){return storage.size},key:index=>[...storage.keys()][index],getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},setInterval(){}});
for(const m of html.matchAll(/<script>([\s\S]*?)<\/script>/g))vm.runInContext(m[1],ctx);
const run=code=>vm.runInContext(code,ctx);
// What Result review shows for a result: the window line and the headline cells.
const reviewWindow=()=>el('workspace-result-window').textContent;
const headline=()=>el('workspace-headline').innerHTML.split('</div>').filter(Boolean).map(cell=>cell.replace(/<[^>]+>/g,' ').trim().replace(/\s+/g,' '));
run('const LATEST_VIEW="latest"');
assert.equal(run('screeningMode'),'latest');
// One ordered step list replaces the ranking, order, range and floor controls.
for(const removed of ['ranking-source','ranking-metric','selection-order','variable-direction','min-cap','min-yield','rank-to','top100','sector-filter','variable-new'])assert(!html.includes('id="'+removed+'"'),removed);
assert.equal((html.match(/id="strategy-steps"/g)||[]).length,1);
const steps=()=>JSON.parse(run('JSON.stringify(StrategyDraft.view())')),stepIds=()=>steps().map(row=>row.id),rankId=()=>steps().findLast(row=>row.kind==='rank').id;
const stepEvent=(type,step,key,value)=>el('strategy-steps').handlers[type]({target:{dataset:{step,key},value}});
const stepButton=(action,step)=>el('strategy-steps').handlers.click({target:{closest:()=>({dataset:{action,step}})}});
const addStep=(kind,choice)=>{el('add-'+kind).handlers.click();run('chooseStep("new",'+JSON.stringify(choice)+')');return run('StrategyDraft.read().changed');};
assert.deepEqual(steps().map(row=>[row.kind,row.label]),[['filter','Market cap'],['filter','Enterprise value'],['rank','EV / EBITDA yield']]);
assert(el('strategy-steps').innerHTML.includes('Highest first'));
assert.equal(el('latest-view').hidden,false);assert.equal(el('custom-view').hidden,true);assert.equal(el('schedule-controls').hidden,true);
assert.equal(run('ResultArtifacts.forView(LATEST_VIEW).result.asof'),latestDate);
assert.equal(run('ResultArtifacts.forView(LATEST_VIEW).result.stocks.length'),latestCount(50));
// Each mode shows its own run controls: Screen latest and Auto-run for latest picks, the test name and
// Add to queue for a dated test.
const modeControls=()=>['run-screen','auto-run-controls','queue-controls'].filter(id=>!el(id).hidden);
assert.deepEqual(modeControls(),['run-screen','auto-run-controls']);
// Opening the dated view starts nothing; it shows the schedule controls. A
// latest evidence panel in the builder hides with latest mode.
el('workspace-builder').append(el('scalar-evidence-view'));el('scalar-evidence-view').hidden=false;
run("switchMode('backtest')");assert.equal(el('scalar-evidence-view').hidden,true);
assert.equal(el('workspace-builder').hidden,false);assert.equal(el('workspace-review').hidden,true);assert.equal(el('latest-view').hidden,true);assert.equal(el('schedule-controls').hidden,false);
assert.deepEqual(modeControls(),['queue-controls']);assert.equal(el('screen-error').textContent,'');
assert.equal(run('ResultArtifacts.forView("custom")'),undefined);
run("switchMode('latest')");assert.deepEqual(modeControls(),['run-screen','auto-run-controls']);
console.log('Passed: default latest mode, the default chain, the run controls of each mode and the dated view opening without a run.');
// Market changes in manual mode restore local choices and bounds without a run.
el('auto-run').checked=false;el('auto-run').handlers.change();
const heldLatest=run('ResultArtifacts.forView(LATEST_VIEW)');
const sectorStep=addStep('filter',{kind:'field',field:'sector',label:'Sector'});
for(const value of prepared.choices.sector)assert(el('strategy-steps').innerHTML.includes('value="'+value.replace(/&/g,'&amp;')+'"'),'sector '+value);
const exchangeStep=addStep('filter',{kind:'field',field:'exchange',label:'Exchange'});
for(const code of ['hk','jp']){
 el('stock-market').value=code;el('strategy-form').handlers.change({target:el('stock-market')});
 assert.equal(run('currentSettings().market'),code);assert.equal(el('stock-pool').value,'cached');
 assert.equal(run('ResultArtifacts.forView(LATEST_VIEW)'),heldLatest);
 for(const exchange of prepared.markets[code].choices.exchange)assert(el('strategy-steps').innerHTML.includes(exchange));
 assert.equal(el('trade-end').max,prepared.markets[code].latest.metadata.asof||'');
}
el('stock-market').value='us';el('strategy-form').handlers.change({target:el('stock-market')});
stepButton('remove',sectorStep);stepButton('remove',exchangeStep);assert.equal(steps().length,3);
el('auto-run').checked=true;el('auto-run').handlers.change();
assert(el('stock-pool').innerHTML.includes('cached')&&!el('stock-pool').innerHTML.includes('legacy'));

// CSV downloads use the displayed result.
let savedCsv='',downloadName='';
ctx.Blob=class{constructor(parts){this.parts=parts;}};
ctx.URL={createObjectURL(blob){savedCsv=blob.parts.join('');return 'blob:test';},revokeObjectURL(){}};
document.createElement=()=>({click(){downloadName=this.download;}});
assert.equal(el('latest-view').hidden,false);assert.equal(el('custom-view').hidden,true);
assert.equal(el('latest-date').textContent,latestDate);
assert.equal((el('latest-body').innerHTML.match(/<tr>/g)||[]).length,Math.max(1,latestCount(50)));
assert(run("ResultArtifacts.forView(LATEST_VIEW).result.stocks.every(h=>h.price_date===screeningData.latest.metadata.asof && !('return_value' in h))"));
stepEvent('change',rankId(),'rank_to','100');assert.equal(run('ResultArtifacts.forView(LATEST_VIEW).result.stocks.length'),latestCount(100));
const [capStep]=stepIds();stepEvent('input',capStep,'value','500');
const maxCap=addStep('filter',{kind:'field',field:'market_cap',label:'Market cap'});stepEvent('change',maxCap,'op','le');stepEvent('input',maxCap,'value','5000');
assert.deepEqual(stepIds().slice(2),[maxCap,rankId()],'A new filter goes before the last Rank');
el('strategy-form').handlers.submit({preventDefault(){}});
assert(run('ResultArtifacts.forView(LATEST_VIEW).result.stocks.every(h=>h.market_cap>=500e6 && h.market_cap<=5e9)'));
stepEvent('input',capStep,'value','6000');run('applyRange()');assert(el('screen-error').textContent.includes('Maximum market cap'));stepEvent('input',capStep,'value','500');run('applyRange()');assert.equal(el('screen-error').textContent,'');
el('download-latest').handlers.click({preventDefault(){}});
assert.equal(downloadName,`latest-picks-${latestDate}.csv`);
assert(savedCsv.includes('"price_date"'));assert(savedCsv.includes('"market","currency"')&&savedCsv.includes('"us","USD"'));assert(!savedCsv.includes('return_value'));
const noSector=addStep('filter',{kind:'field',field:'sector',label:'Sector'});stepEvent('input',noSector,'value','No matching sector');run('applyRange()');
assert.equal(run('ResultArtifacts.forView(LATEST_VIEW).result.stocks.length'),0);assert(el('latest-body').innerHTML.includes('No stocks match'));
assert.equal(el('latest-median-cap').textContent,'—');
el('reset-strategy').handlers.click();el('mode-backtest').handlers.click();
assert.equal(el('workspace-builder').hidden,false);assert.equal(el('latest-view').hidden,true);
assert.deepEqual(modeControls(),['queue-controls']);
console.log('Passed: exact-date picks, shared filters and ranks, invalid-input recovery, current CSV, empty latest screen, and switching to the dated view.');
run("switchMode('latest')");run('chooseStep("'+rankId()+'",{kind:"builtin",id:"metric:ev_ebitda_3y:yield",label:"3-year yield"})');
assert.equal(run('ResultArtifacts.forView(LATEST_VIEW).result.options.metric'),'ev_ebitda_3y');
assert(run('ResultArtifacts.forView(LATEST_VIEW).result.stocks.length')>0);
assert(el('strategy-heading').textContent.includes('3-year average'));
assert(run('ResultArtifacts.forView(LATEST_VIEW).result.stocks.every(h=>h.metric_multiple>0)'));
el('download-latest').handlers.click({preventDefault(){}});
assert(savedCsv.includes('ev_ebitda_3y'));assert(savedCsv.includes('metric_multiple'));
el('reset-strategy').handlers.click();
assert.equal(run('ResultArtifacts.forView(LATEST_VIEW).result.options.metric'),'ev_ebitda');
console.log('Passed: metric selection and reset to default.');
// Manual mode keeps results and exports tied to the last successful settings.
el('auto-run').checked=false;el('auto-run').handlers.change();
assert.equal(storage.get('backtest-auto-run'),'false');
const beforeManual=run('ResultArtifacts.forView(LATEST_VIEW).result');
stepEvent('change',rankId(),'rank_to','100');assert.equal(run('ResultArtifacts.forView(LATEST_VIEW).result'),beforeManual);
assert(el('results-state').textContent.includes('do not match'));
assert.equal(el('latest-view').attributes['data-results-stale'],'true');
// Results that match the settings need no line.
stepEvent('change',rankId(),'rank_to','50');assert.equal(el('results-state').textContent,'');
stepEvent('input',rankId(),'rank_to','25');el('strategy-form').handlers.input({target:{id:'step-rank_to'}});
assert(el('results-state').textContent.includes('do not match'));
el('strategy-form').handlers.submit({preventDefault(){}});
assert.equal(run('ResultArtifacts.forView(LATEST_VIEW).result.options.rank_to'),25);
assert.equal(el('results-state').textContent,'');
stepEvent('change',rankId(),'rank_to','50');
el('auto-run').checked=true;el('auto-run').handlers.change();
assert.equal(run('ResultArtifacts.forView(LATEST_VIEW).result.options.rank_to'),50);
console.log('Passed: manual multi-setting edits, dirty notice, restoring settings, explicit submit and re-enabling auto-run.');
// A saved version-1 January result opens in the dated view from its own
// stock rows, without selection or calculation, and its record is unchanged.
const bookStocks=JSON.parse(run('JSON.stringify(ResultArtifacts.forView(LATEST_VIEW).result.stocks.slice(0,3))'));
assert.equal(bookStocks.length,3,'The latest screen needs three stocks for the saved January fixture.');
const bookHoldings=bookStocks.map((h,i)=>({...h,year:2015,rank:i+1,entry:'2015-01-02',exit:'2016-01-04',return_value:[.5,.25,-.1][i],status:'Scheduled exit'}));
bookHoldings[0].symbol='SAVED_ONLY';
const savedSettings={mode:'january',first:2015,last:2016,rank_from:1,rank_to:7,pool:'legacy',metric:'ev_ebitda',min_cap:100e6,max_cap:null,min_ev:50e6,min_yield:0,max_multiple:null,sector:null,exchange:null,filters:[{field:'market_cap',op:'gt',value:0}]};
const savedJanuary={version:1,kind:'january',settings:savedSettings,captured_at:'2026-10-26T00:00:00Z',
 result:{options:{...savedSettings},years:[{year:2015,names:3,portfolio:(.5+.25-.1)/3,spy:.1,median_market_cap:null,holdings:bookHoldings},{year:2016,names:0,portfolio:null,spy:.05,median_market_cap:null,holdings:[]}],
  first:'2015-01-02',end:'2016-10-20',growth:null,spy_growth:1.155,cagr:null,spy_cagr:.08,short_years:[2015,2016],empty_years:[2016]},
 catalog:{metrics:{...prepared.metrics,ev_ebitda:{...prepared.metrics.ev_ebitda,label:'Saved valuation label'}},filters:{...prepared.filter_catalog,market_cap:{...prepared.filter_catalog.market_cap,label:'Saved cap threshold'}}},
 context:{notes:[['screen-coverage','Saved coverage','hint'],['screen-status','Saved warning','screen-message warning'],['range-note','Saved range','hint']],pill:'Saved period'}};
ctx.savedJanuary=savedJanuary;const savedBytes=JSON.stringify(savedJanuary);
run("switchMode('backtest')");
const tradeStart=el('trade-start').value,beforeCopy=run('currentArtifact()');
el('auto-run').checked=true;stepEvent('input',rankId(),'rank_to','3');
ctx.fetch=()=>{throw Error('Saved results must not calculate')};
run('copySavedBacktestSettings(savedJanuary)');
assert.deepEqual(steps().map(row=>[row.kind,row.op??row.direction,row.value??row.rank_to]),[['filter','ge','100'],['filter','ge','50'],['filter','gt','0'],['rank','highest',7]]);
// Auto-run belongs to latest picks: a copy into the builder leaves it as the user set it.
assert.equal(el('auto-run').checked,true);assert.equal(storage.get('backtest-auto-run'),'true');assert.strictEqual(run('currentArtifact()'),beforeCopy);
assert(el('strategy-steps').innerHTML.includes('Saved valuation label yield'));assert(el('strategy-steps').innerHTML.includes('Saved cap threshold'));
assert.equal(el('trade-start').value,tradeStart,'January book years never become a calendar.');
run('restoreSavedBacktest(savedJanuary)');
const opened=run('currentArtifact()');assert.equal(opened.kind,'january');assert.equal(opened.version,2);assert.equal(opened.captured_at,savedJanuary.captured_at);
assert.equal(el('custom-view').hidden,false);assert.equal(el('latest-view').hidden,true);
assert.equal(reviewWindow(),'2015-01-02 → 2016-10-20 · Saved January books');
// Its totals were not recorded: the headline says so, and the coverage line gives the reason.
assert.deepEqual(headline(),['Strategy CAGR Unavailable','SPY CAGR 8.00%','Difference vs SPY Unavailable','Growth of $1 Unavailable']);
assert(el('schedule-coverage').textContent.includes('Recorded totals are unavailable'));
assert(el('schedule-rows').innerHTML.includes('<td>2015-01-02</td><td>2016</td><td>3</td>'));
assert(el('schedule-rows').innerHTML.includes('<td>2016</td><td>2016-10-20</td><td>0</td>'));
assert.equal(el('schedule-message').textContent,'');
assert.equal(el('workspace-review').hidden,false);assert.equal(el('workspace-builder').hidden,true);
assert(el('workspace-parameters').innerHTML.includes('Saved valuation label'));
assert.equal(el('workspace-recorded-notice').textContent,'Saved warning');assert(el('workspace-recorded-notice').className.includes('warning'));
assert.equal(el('workspace-recorded-coverage').textContent,'Saved coverage');
assert.equal(el('results-state').textContent,'','The builder shows no line for a dated result');
el('schedule-period').value='0';el('schedule-period').handlers.change();assert(el('schedule-stock-body').innerHTML.includes('SAVED_ONLY'));
assert(el('schedule-attribution').innerHTML.includes('Top 10 contributors'));
el('schedule-download-holdings').handlers.click();assert(savedCsv.includes('SAVED_ONLY'));assert(savedCsv.includes('"period_start"'));
run("switchMode('latest');switchMode('backtest')");assert.strictEqual(run('currentArtifact()'),opened);
assert.equal(JSON.stringify(savedJanuary),savedBytes);assert(!run('JSON.stringify({...currentArtifact(),record:null})').includes('screen-status'));assert.equal(run('JSON.stringify(currentArtifact().record)'),savedBytes);
const savedRankFirst=JSON.parse(savedBytes);
savedRankFirst.settings.selection_order='rank_first';savedRankFirst.result.options.selection_order='rank_first';
ctx.savedRankFirst=savedRankFirst;run('restoreSavedBacktest(savedRankFirst)');
assert.equal(steps().at(-1).kind,'rank','Opening a result leaves the draft order alone');assert.equal(run('currentArtifact().settings.selection_order'),'rank_first');
run('StrategyDraft.reset()');el('auto-run').checked=true;run('settingsChanged(false)');
console.log('Passed: a saved January result opens independently of its draft with its exact stored stocks, returns and CSV in the dated view without calculation.');

// A dated test starts from Add to queue only. Its stored result opens with its periods, stocks and downloads.
(async()=>{
 const selected={holdings:bookHoldings.map(h=>({...h,entry:'2015-03-16',exit:'2015-06-15'}))};
 const period={entry:'2015-03-16',exit:'2015-06-15',names:3,holdings:selected.holdings.map(h=>({...h,contribution_pp:h.return_value/3*100})),portfolio:(.5+.25-.1)/3,spy:.02};
 const fixture={periods:[period],start:period.entry,end:period.exit,months:3,options:{metric:'ev_ebitda',rank_from:1,rank_to:50},growth:1+period.portfolio,spy_growth:1+period.spy,cagr:.1,spy_cagr:.05,seconds:.03,coverage:'Fixture coverage'};
 // Capture transport is controlled here; selection parity is checked against
 // SQL by test_scalar_execution, and real wire capture by check-strategy-draft.
 run(`VariableWorkspace.request=async(route,input)=>{
   if(route==='/catalog')return {builtins:[{id:'filter:market_cap',display:'usd_million'}]};
   if(route!=='/capture')throw Error('Unexpected variable request');
   const steps=input.intent.steps.map(step=>step.kind==='filter'&&typeof step.threshold!=='string'&&!step.submitted_threshold?{...step,submitted_threshold:step.threshold,storage_comparison_value:Number(step.threshold.value)}:step);
   return {strategy:{...input.intent,format:'strategy-capture',steps,variables:null,builtins:[]}};
 };`);
 const tick=()=>new Promise(resolve=>setImmediate(resolve));
 let calls=0;ctx.location={protocol:'http:'};ctx.fetch=()=>{calls++;throw Error('The builder must not request a calculation');};
 el('trade-start').value='2015-03-15';el('trade-end').value='2015-06-15';el('rebalance-months').value='3';
 run("screeningMode='backtest';setModeVisibility()");
 const capFilter=addStep('filter',{kind:'builtin',id:'filter:market_cap',label:'Market cap ($ million)'});stepEvent('input',capFilter,'value','0');
 // In Historical backtest mode a form submit, such as Enter in a step field, starts nothing. A changed
 // setting starts nothing with Auto-run ticked.
 const latestBefore=run('ResultArtifacts.forView(LATEST_VIEW)');
 el('auto-run').checked=true;el('strategy-form').handlers.submit({preventDefault(){}});stepEvent('change',rankId(),'rank_to','40');stepEvent('change',rankId(),'rank_to','50');await tick();
 assert.equal(calls,0);assert.equal(el('run-screen').disabled,false);assert.equal(el('screen-error').textContent,'');assert.equal(el('results-state').textContent,'');
 assert.strictEqual(run('ResultArtifacts.forView(LATEST_VIEW)'),latestBefore);
 const fixedSettings=JSON.parse(JSON.stringify(await run('StrategyDraft.prepareSubmission()')));
 // The submission that Add to queue sends: explicit dates, the interval and one captured chain.
 const sentFilter=fixedSettings.strategy.steps.find(step=>step.source.id==='filter:market_cap');
 assert.equal(sentFilter.storage_comparison_value,0);assert.equal(sentFilter.submitted_threshold.unit,'usd_million','A built-in unit comes from the catalog');assert(!('filters' in fixedSettings));
 assert.equal(fixedSettings.mode,'custom');assert.equal(fixedSettings.start,'2015-03-15');assert.equal(fixedSettings.months,3);assert(!('first' in fixedSettings));
 // A stored fixed result, as the queue keeps it with the catalog and the notes of its submission. It opens
 // without calculation and leaves the draft alone.
 const stored=(settings,result)=>{ctx.storedSettings=settings;ctx.storedResult=result;return JSON.parse(run('JSON.stringify(ResultArtifacts.create(storedSettings,storedResult,sourceCatalog(),scheduledPresentation(storedSettings)))'));};
 const savedFixed=stored(fixedSettings,fixture);ctx.savedFixed=savedFixed;
 el('trade-start').value='2001-01-01';stepEvent('input',rankId(),'rank_to','2');
 run('restoreSavedBacktest(savedFixed)');
 assert.equal(el('trade-start').value,'2001-01-01');assert.equal(steps().at(-1).rank_to,2);assert.equal(el('custom-view').hidden,false);
 assert.equal(reviewWindow(),'2015-03-16 → 2015-06-15 · Fixed schedule');assert(el('schedule-chart').innerHTML.includes('<rect'));
 const fixedHeadline=['Strategy CAGR 10.00%','SPY CAGR 5.00%','Difference vs SPY +5.00 pp','Growth of $1 $1.22'];assert.deepEqual(headline(),fixedHeadline);
 // The coverage line of a fixed result is one of its recorded notes.
 assert.equal(el('schedule-coverage').parentNode,el('workspace-recorded-context'));assert(el('schedule-coverage').textContent.includes('Fixture coverage'));
 assert(el('schedule-stock-body').innerHTML.includes(selected.holdings[0].symbol));
 el('schedule-download-holdings').handlers.click();assert(savedCsv.includes('period_start'));assert(savedCsv.includes('2015-03-16'));
 // A stored result is a record: changed draft settings do not mark it, and the builder shows no line for it.
 stepEvent('change',rankId(),'rank_to','25');assert.equal(el('results-state').textContent,'');assert.equal(el('custom-view').attributes?.['data-results-stale'],undefined);
 assert.deepEqual(headline(),fixedHeadline);assert.equal(calls,0);
 // Random independent rebalances: the submission holds the trial count and, with Repeat ticked, the date set.
 el('date-testing').value='random';el('random-trials').value='3';el('random-seed').value='123';el('repeat-random').checked=true;el('rebalance-months').value='24';
 const randomSettings=JSON.parse(JSON.stringify(await run('StrategyDraft.prepareSubmission()')));
 assert.equal(randomSettings.mode,'random');assert.equal(randomSettings.trials,3);assert.equal(randomSettings.seed,123);assert.equal(randomSettings.months,24);
 const stat={n:3,mean:.1,median:.1,p10:.1,p25:.1,p75:.1,p90:.1,min:.1,max:.1,stddev:0};
 const batch={kind:'random_dates',completed:3,valid:3,incomplete:0,beat_spy:2,unique_schedules:3,note:'Independent dates in each block.',configuration:{start:'2015-03-15',end:'2015-06-15',months:24,seed:123,requested:3,options:{metric:'ev_ebitda',rank_to:50}},distributions:Object.fromEntries(['cagr','spy_cagr','excess_cagr','total_return','growth'].map(k=>[k,stat])),trials:[1,2,3].map(trial=>({trial,start:'2015-03-16',first_trade:'2015-03-16',end:'2015-06-15',dates:['2015-03-16'],periods:1,cagr:.1,spy_cagr:.05,excess_cagr:.05,empty_periods:0,short_periods:0}))};
 const savedRandom=stored(randomSettings,{...batch,trial_results:[fixture,fixture,fixture]});ctx.savedRandom=savedRandom;
 run('restoreSavedBacktest(savedRandom)');
 assert.equal(el('robustness-results').hidden,false);assert.equal(el('schedule-results').hidden,true);assert.equal(el('robustness-mean').textContent,'10.00%');
 assert.equal(el('workspace-review').dataset.section,'overview');
 el('robustness-trial').value='1';await el('robustness-inspect').handlers.click();assert.equal(calls,0,'Stored trial inspection must not call the service');
 assert.equal(el('robustness-results').hidden,false);assert.equal(el('schedule-results').hidden,false);
 // The chosen trial opens in Returns under its own title.
 assert.equal(el('workspace-review').dataset.section,'returns');assert.equal(el('schedule-trial-title').textContent,'Trial 2 of 3');
 assert.equal(el('schedule-dates').textContent,fixture.start+' → '+fixture.end+' · every '+fixture.months+' month(s)');assert.equal(el('schedule-cagr').textContent,'10.00%');
 assert.equal(el('schedule-coverage').parentNode,el('schedule-trial'));assert.equal(headline()[0],'Mean strategy CAGR 10.00%');
 // Tune copies the trial count and the recorded date set with Repeat ticked, so a new test can use the same dates.
 const beforeRandomCopy=run('currentArtifact()');
 el('random-seed').value='999';el('random-trials').value='1';el('repeat-random').checked=false;
 run('copySavedBacktestSettings(savedRandom)');
 assert.equal(el('random-seed').value,'123');assert.equal(el('random-trials').value,'3');
 assert.equal(el('repeat-random').checked,true);assert.equal(el('auto-run').checked,true);
 assert.strictEqual(run('currentArtifact()'),beforeRandomCopy);
 el('random-seed').value='999';el('random-trials').value='1';
 run('restoreSavedBacktest(savedRandom)');
 assert.equal(el('random-seed').value,'999');assert.equal(el('random-trials').value,'1');assert.equal(el('repeat-random').checked,true);
 assert.equal(el('results-state').textContent,'');
 assert.equal(el('schedule-results').hidden,true);await el('robustness-inspect').handlers.click();
 assert.equal(calls,0);assert.equal(el('schedule-results').hidden,false);

 el('repeat-random').checked=false;el('strategy-form').handlers.change({target:el('repeat-random')});assert.equal(el('random-seed').disabled,true);
 assert(!('seed' in await run('StrategyDraft.prepareSubmission()')),'Fresh random mode must not send a fixed seed');
 console.log('Passed: no run from a form submit or a changed setting in Historical backtest mode; submissions with dates, frequency, trial count and date set; stored fixed and random results with chart, stocks, attribution, CSV and stored-trial inspection.');

 // One form-owner boundary protects a held edit from every restoration source.
 const waitingId='a'.repeat(32),completedId='b'.repeat(32);
 let queueRows=[{id:waitingId,name:'Edit this test',state:'queued',revision:1,position:1,mode:'custom',options:savedFixed.settings},
   {id:completedId,name:'Completed test',state:'complete',revision:1,position:2,mode:'custom',options:savedFixed.settings}],rejectHold=false;
 ctx.waitingId=waitingId;ctx.completedId=completedId;
 ctx.fetch=async(url,options={})=>{
   if(url.startsWith('/api/backtests/'))return {ok:true,json:async()=>({name:'Library result',snapshot:savedFixed})};
   assert(url.startsWith('/api/backtest-queue'),'Form policy must not submit a calculation');
   const [,id,action]=url.match(/^\/api\/backtest-queue(?:\/([^/]+))?(?:\/([^/]+))?$/);
   if(!id)return {ok:true,json:async()=>({limit:100,paused:true,records:JSON.parse(JSON.stringify(queueRows))})};
   const record=queueRows.find(row=>row.id===id);
   if(!options.method||options.method==='GET')return {ok:true,json:async()=>({...record,snapshot:savedFixed})};
   const body=JSON.parse(options.body);
   if(action==='hold'&&rejectHold)return {ok:false,status:409,json:async()=>({error:'The test already started.'})};
   if(options.method==='DELETE'){queueRows=queueRows.filter(row=>row.id!==id);return {ok:true,json:async()=>({id,deleted:true})};}
   record.revision++;
   if(action==='hold'){record.state='held';record.edit={id:body.edit_id,revision:record.revision,state:'active'};}
   if(action==='release'){record.state='queued';record.edit.state='cancelled';}
   if(action==='update'){Object.assign(record,{mode:body.mode,options:body.options,name:body.name,state:'queued'});record.edit.state='saved';}
   return {ok:true,json:async()=>JSON.parse(JSON.stringify(record))};
 };
 await run('BacktestQueue.refresh();');await run('BacktestQueue.action("edit",waitingId)');
 stepEvent('input',rankId(),'rank_to','7');run('settingsChanged(false)');
 const draft=run('JSON.stringify(currentSettings())'),artifactBefore=run('ResultArtifacts.forView("custom")');
 assert.doesNotThrow(()=>run('restoreSavedBacktest(savedFixed)'));
 assert.throws(()=>run('copySavedBacktestSettings(savedFixed)'),/Save or cancel/);
 assert.equal(run('JSON.stringify(currentSettings())'),draft);assert.notEqual(run('ResultArtifacts.forView("custom")'),artifactBefore);
 await run('BacktestQueue.action("open",completedId)');assert(el('queue-status').textContent.includes('Opened'));
 await run('BacktestQueue.action("copy",completedId)');assert(el('queue-status').textContent.includes('Save or cancel'));
 await el('saved-list').handlers.click({target:{dataset:{open:'library-result'}}});
 assert(el('saved-status').textContent.includes('Opened'));
 await el('saved-list').handlers.click({target:{dataset:{copy:'library-result'}}});
 assert(el('saved-status').textContent.includes('Save or cancel'));
 assert.equal(run('JSON.stringify(currentSettings())'),draft);assert.equal(el('queue-name').value,'Edit this test');
 await run('BacktestQueue.add()');assert.equal(queueRows[0].options.strategy.steps.at(-1).rank_to,7);assert.equal(run('BacktestQueue.isEditing()'),false);
 await el('saved-list').handlers.click({target:{dataset:{open:'library-result'}}});assert.equal(steps().at(-1).rank_to,7);assert.equal(run('ResultArtifacts.forView("custom").kind'),'custom');
 await run('BacktestQueue.action("edit",waitingId)');stepEvent('input',rankId(),'rank_to','9');
 await el('queue-cancel-edit').handlers.click();assert.equal(queueRows[0].options.strategy.steps.at(-1).rank_to,7);
 await run('BacktestQueue.action("open",completedId)');assert.equal(steps().at(-1).rank_to,9);assert.equal(run('ResultArtifacts.forView("custom").kind'),'custom');
 await run('BacktestQueue.action("edit",waitingId)');await run('BacktestQueue.action("confirm",waitingId)');
 run('const afterDelete=StrategyDraft.beginQueuedEdit("after-delete");afterDelete.end()');
 queueRows.push({id:waitingId,name:'Rejected hold',state:'queued',revision:1,position:3,mode:'custom',options:savedFixed.settings});
 rejectHold=true;await run('BacktestQueue.refresh()');await run('BacktestQueue.action("edit",waitingId)');
 assert.equal(run('BacktestQueue.isEditing()'),false);assert.doesNotThrow(()=>run('restoreSavedBacktest(savedFixed)'));
 // Saving an unchanged held legacy row submits its exact legacy selection, seed and plan. A form submit
 // during the held edit starts nothing: this transport refuses every address outside the queue.
 rejectHold=false;el('date-testing').value='random';el('random-trials').value='3';el('repeat-random').checked=false;
 const legacyOptions={market:'us',rank_from:1,rank_to:9,pool:'cached',metric:'ev_ebitda',min_cap:100e6,max_cap:null,min_ev:50e6,min_yield:0,max_multiple:null,sector:null,exchange:null,filters:[],selection_order:'filter_first',
   ...JSON.parse(run('JSON.stringify(CalendarSettings.read())')),engine:'original',trials:3};
 const legacyRow={id:'d'.repeat(32),name:'Held legacy random',state:'queued',revision:1,position:4,mode:'random',options:legacyOptions,
   seed:321,plan:{seed:321,samples:[['2015-03-16']],window_start:'2015-03-16',window_end:'2015-06-15'},configuration:{seed:321}};
 const originalLegacy=structuredClone({options:legacyRow.options,seed:legacyRow.seed,plan:legacyRow.plan});
 queueRows.push(legacyRow);ctx.legacyHeldId=legacyRow.id;
 await run('BacktestQueue.refresh()');await run('BacktestQueue.action("edit",legacyHeldId)');
 el('strategy-form').handlers.submit({preventDefault(){}});await tick();
 await run('BacktestQueue.add()');
 assert.equal(run('BacktestQueue.isEditing()'),false);assert(!legacyRow.options.strategy);
 assert.deepEqual({options:legacyRow.options,seed:legacyRow.seed,plan:legacyRow.plan},originalLegacy);
 el('date-testing').value='single';
 // Every copy into the builder leaves the test-name box empty: Tune on a queued test, Tune on a saved backtest and
 // the button of the open result. A held edit loads its record name (above); a refused copy keeps it.
 for(const tune of [()=>run('BacktestQueue.action("copy",completedId)'),()=>el('saved-list').handlers.click({target:{dataset:{copy:'library-result'}}}),async()=>el('workspace-edit-copy').handlers.click()]){
   el('queue-name').value='Typed for other settings';el('auto-run').checked=true;stepEvent('input',rankId(),'rank_to','4321');await tune();
   assert.equal(el('queue-name').value,'');assert.equal(el('auto-run').checked,true);assert.notEqual(String(steps().findLast(row=>row.kind==='rank').rank_to),'4321','The copy restored the recorded strategy');
 }
 el('date-testing').value='single';
 queueRows=[];await run('BacktestQueue.refresh()');
 console.log('Passed: held draft ownership across queue open/copy and saved-library opening; save/cancel/delete and failed admission release the form; every copy into the builder empties the name box.');

 // Latest stock picks shows no queue controls. In Historical backtest mode Add to queue submits the chosen settings.
 let submissions=0;
 ctx.fetch=async(url,options={})=>{
   assert.equal(url,'/api/backtest-queue','The queue controls must never submit an immediate calculation');
   if(options.method==='POST'){
     submissions++;
     const body=JSON.parse(options.body);
     const record={...body,state:'queued',position:queueRows.length+1,revision:1};
     queueRows.push(record);return {ok:true,json:async()=>record};
   }
   return {ok:true,json:async()=>({limit:100,paused:true,records:queueRows})};
 };
 run("switchMode('latest')");assert.deepEqual(modeControls(),['run-screen','auto-run-controls']);
 el('mode-backtest').handlers.click();assert.deepEqual(modeControls(),['queue-controls']);assert.equal(run('currentSettings().mode'),'custom');
 const queuedRank=rankId();stepEvent('input',queuedRank,'rank_to','12');for(let i=steps().length;i>1;i--)stepButton('up',queuedRank);
 assert.equal(stepIds()[0],queuedRank);assert.equal(submissions,0);
 await el('queue-add').handlers.click();assert.equal(submissions,1);
 assert.equal(queueRows[0].options.strategy.steps[0].rank_to,12);assert.equal(queueRows[0].mode,'custom');
 assert.equal(queueRows[0].options.strategy.steps[0].kind,'rank','Rank first is the first step');assert(!('rank_to' in queueRows[0].options));
 assert.equal(el('queue-add').textContent,'Add to queue');
 queueRows=[];await run('BacktestQueue.refresh()');
 console.log('Passed: no queue controls in latest mode; Add to queue submits the chosen settings in Historical backtest mode.');

run("StrategyDraft.reset();switchMode('latest')");
el('add-filter').handlers.click();
assert(el('strategy-steps').innerHTML.includes('id="filter-search-new"'));assert.equal(run('StrategyDraft.flat().filters.length'),0);
const builtinChoices=run("stepChoices('new').groups.find(group=>group.label==='Built-in values').options");
for(const field of ['pe','pb','ps','fcf','fcf_yield','profit_margin','operating_yield_spread_3y','peg','roe','current_ratio','interest_coverage','debt_equity',
 ...['pe','ps','pb'].flatMap(key=>[3,5].flatMap(years=>[key+'_avg_'+years+'y',key+'_vs_avg_'+years+'y']))]) {
 const option=builtinChoices.find(item=>item.value.id==='filter:'+field);
 assert(option,'Missing financial filter '+field);assert.equal(!!option.disabled,!prepared.filter_catalog[field].available);
}
run("chooseStep('new',{kind:'builtin',id:'filter:return_1y',label:'1-year trailing return (%)'})");
const returnStep=run('StrategyDraft.read().changed');
assert.equal(run('pendingStep'),null);assert.throws(()=>run('StrategyDraft.requireValues()'),/Enter a value/);
stepEvent('input',returnStep,'value','0');
assert.equal(run('StrategyDraft.flat().filters[0].value'),0);
run('applyRange()');
assert(run("ResultArtifacts.forView(LATEST_VIEW).result.stocks.every(h=>screeningData.filter_values[ResultArtifacts.forView(LATEST_VIEW).result.options.pool][h.symbol].return_1y>0)"));
stepButton('remove',returnStep);
assert.equal(run('StrategyDraft.flat().filters.length'),0);
// A chain outside the offline shape screens latest on the service with its
// captured chain; auto-run stays offline-only. The offline result stays shown.
const extraRank=addStep('rank',{kind:'builtin',id:'metric:ev_ebitda:multiple',label:'EV / EBITDA multiple'});
assert.equal(el('run-screen').disabled,false);assert.equal(el('auto-run').disabled,true);
const offlineLatest=run('ResultArtifacts.forView(LATEST_VIEW)'),queueFetch=ctx.fetch;let latestRequest,finishScreen,screens=0;
ctx.fetch=(url,options)=>{screens++;latestRequest={url,...JSON.parse(options.body)};return new Promise(resolve=>finishScreen=resolve);};
run('applyRange()');await tick();await tick();
// While the service screens, the button waits. A second request starts nothing more.
assert.equal(el('run-screen').disabled,true);assert.equal(el('run-screen').textContent,'Screening…');
run('applyRange()');el('strategy-form').handlers.submit({preventDefault(){}});await tick();assert.equal(screens,1);
finishScreen({ok:false,status:400,json:async()=>({error:'Fixture refusal'})});await tick();await tick();
assert(latestRequest.url.startsWith('/api/backtest-runs/'));assert.equal(latestRequest.mode,'latest');assert(!('start' in latestRequest.options));
assert.equal(latestRequest.options.strategy.format,'strategy-capture');assert.equal(latestRequest.options.strategy.steps.at(-1).source.id,'metric:ev_ebitda:multiple');
assert.equal(run('ResultArtifacts.forView(LATEST_VIEW)'),offlineLatest);assert(el('screen-error').textContent.includes('Fixture refusal'));assert.equal(el('run-screen').disabled,false);assert.equal(el('run-screen').textContent,'Screen latest');
// Opened as a file, the page says how to start the service and sends nothing.
ctx.location={protocol:'file:'};run('applyRange()');await tick();await tick();assert.equal(screens,1);assert(el('screen-error').textContent.includes('website/serve.py'));assert.equal(el('run-screen').disabled,false);ctx.location={protocol:'http:'};
ctx.fetch=queueFetch;
stepButton('remove',extraRank);assert.equal(el('auto-run').disabled,false);
run('applyRange()');assert.notEqual(run('ResultArtifacts.forView(LATEST_VIEW)'),offlineLatest,'A flat chain screens offline again');assert.equal(el('latest-view').hidden,false);
console.log('Passed: add/edit/remove filter steps, numeric thresholds and latest chains on the service.');

// Shared prepared views are independent of the selected dated executor.
let sharedLatest;
for(const engine of ['original','experimental']){
 el('backtest-engine').value=engine;el('auto-run').checked=false;
 run("switchMode('latest');applyRange()");
 const latest=run("ResultArtifacts.forView('latest')");
 assert(!('engine' in latest.settings));assert(!('producer' in latest.result));
 const latestValues=JSON.stringify(latest.result);
 if(sharedLatest)assert.equal(latestValues,sharedLatest);else sharedLatest=latestValues;
}
console.log('Passed: Latest remains an identical shared prepared view in both engine contexts, without invented producer metadata.');

})().catch(error=>{console.error(error);process.exitCode=1});
