const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes=new Map();function node(id){if(!nodes.has(id))nodes.set(id,{value:'',checked:false,textContent:'',hidden:false,addEventListener(){}});return nodes.get(id)}
let sent,holdCapture=false,finishCapture,captureCalls=0;
node('screening-data').textContent=JSON.stringify({metrics:{},filter_catalog:{},latest:{metadata:{asof:'2015-02-27'}}});
const context=vm.createContext({document:{getElementById:node},console,StockScreener:require('../website/browser/screener.js'),VariableWorkspace:{request:async(route,input)=>{assert.equal(route,'/capture');captureCalls++;if(holdCapture)await new Promise(resolve=>finishCapture=resolve);return {strategy:{...input.intent,format:'strategy-capture',version:1,variables:null}};}},location:{protocol:'http:'},ResultArtifacts:{forView:()=>null},BacktestRuns:{create(mode,options,planned){sent={mode,options,planned};throw Error('captured');}},fetch:async()=>({json:async()=>({calendar:null,engines:[{id:'original',calendar:1,status:{state:'current'}}]})})});
for(const file of ['engine-controls.js','calendar-settings.js','result-explorer.js','evidence-results.js','schedule.js'])vm.runInContext(fs.readFileSync(require('path').join(__dirname,'../website/browser',file),'utf8'),context);
const draftSource=fs.readFileSync(require('path').join(__dirname,'../website/browser/range.js'),'utf8');vm.runInContext(draftSource.slice(0,draftSource.indexOf('\ninitializeFilters();')),context);
const run=code=>vm.runInContext(code,context);
(async()=>{
 await run('EngineControls.init()');node('date-testing').value='random';
 const legacy={start:'2015-01-02',end:'2015-02-27',months:12,requested:24,seed:42,options:{rank_to:3},window_start:'2015-01-02',window_end:'2015-02-27',blocks:[{start:'2015-01-02',end:'2016-01-02',available:40}],samples:[['2015-01-05']]};
 const canonical={calendar:{version:1,start:legacy.start,end:legacy.end,interval:{unit:'week',count:1}},requested:24,seed:42,options:{rank_to:3},window_start:legacy.window_start,window_end:legacy.window_end,blocks:legacy.blocks,samples:legacy.samples};
 for(const [live,replay] of [[legacy,canonical],[canonical,legacy]]){
   context.live=live;context.replay=replay;
   run('CalendarSettings.restore(live)');const original=JSON.stringify(replay);
   await run('ScheduleView.run({rank_to:99},null,replay)');
   assert.equal(sent.options.strategy.selection.rank_to,3);assert(!('rank_to' in sent.options));assert.deepEqual(sent.planned,{...replay,options:{strategy:sent.options.strategy}});assert.equal(JSON.stringify(replay),original);
   assert.equal('calendar' in sent.options,'calendar' in replay);
   assert.equal('months' in sent.options,'months' in replay);
   assert(!('calendar' in sent.options&&'start' in sent.options));
 }
 const captured=JSON.parse(JSON.stringify(sent.planned));context.captured=captured;
 await run('ScheduleView.run({},null,captured)');assert.deepEqual(sent.planned,captured);
 // Slow capture admission must not allocate another run on a repeated click.
 sent=null;holdCapture=true;const callsBefore=captureCalls;
 const preparing=run('ScheduleView.run({},null,replay)');assert(run('ScheduleView.isRunning()'));
 const duplicate=run('ScheduleView.run({},null,replay)');assert.equal(captureCalls,callsBefore+1);assert.equal(sent,null);
 holdCapture=false;finishCapture();await Promise.all([preparing,duplicate]);assert(!run('ScheduleView.isRunning()'));
 context.inspection=legacy.options;context.dates=legacy.samples[0];context.inspectionCalendar={start:legacy.start,end:legacy.end,months:legacy.months};
 const originalOptions=JSON.stringify(legacy.options);
 await run('ScheduleView.run(inspection,{...inspectionCalendar,dates})');
 assert.equal(sent.mode,'custom');assert.equal(sent.options.strategy.selection.rank_to,3);assert.deepEqual(sent.options.dates,legacy.samples[0]);assert.equal(JSON.stringify(legacy.options),originalOptions);
 node('calendar-custom').checked=true;node('calendar-unit').value='month';node('calendar-count').value='104';sent=null;
 await run('ScheduleView.run({rank_to:3})');
 assert.equal(sent,null);assert.match(node('screen-error').textContent,/Invalid saved calendar/);
 context.restoreWide={mode:'custom',calendar:{version:1,start:'2015-01-02',end:'2016-12-30',interval:{unit:'week',count:104}}};
 node('calendar-count').max='24';run('CalendarSettings.restore(restoreWide)');
 assert.equal(node('calendar-unit').value,'week');assert.equal(node('calendar-count').max,'104');assert.equal(node('calendar-count').value,104);
 console.log('Passed: recorded replay ignores live filters and both calendar representation changes; invalid async inputs show validation without submission.');
})().catch(error=>{console.error(error);process.exitCode=1});
(async()=>{
 await new Promise(resolve=>setImmediate(resolve));
 context.fetch=async()=>({json:async()=>({calendar:null,engines:[{id:'original',calendar:null,status:{state:'current'}}]})});
 await run('EngineControls.init()');node('backtest-engine').value='original';
 assert.equal(run('EngineControls.calendarSupported()'),false);
 context.recorded={engine:'experimental',start:'2015-01-02',end:'2015-02-27',months:12,requested:2,seed:42,options:{rank_to:3},window_start:'2015-01-02',window_end:'2015-02-27',blocks:[{start:'2015-01-02',end:'2016-01-02',available:40}],samples:[['2015-01-05']]};
 await run('ScheduleView.run({rank_to:99},null,recorded)');
 assert.equal(sent.options.engine,'experimental');assert(!('engine' in sent.planned));
 assert.equal(run("EngineControls.runnable('experimental')"),false);
 // A recorded engine this server does not run keeps its calendar; the server refuses it.
 context.recorded={...context.recorded,calendar:{version:1,start:'2015-01-02',end:'2015-02-27',interval:{unit:'week',count:1}}};
 delete context.recorded.start;delete context.recorded.end;delete context.recorded.months;sent=null;
 await run('ScheduleView.run({},null,recorded)');
 assert.equal(sent.options.engine,'experimental');assert.equal(sent.options.calendar.interval.unit,'week');
 context.recorded={...context.recorded,engine:'original'};sent=null;
 await run('ScheduleView.run({},null,recorded)');
 assert.equal(sent,null);assert.match(node('screen-error').textContent,/Original does not support/);
 console.log('Passed: normal-app calendar preflight and replay use pinned engine, not live selector.');
})().catch(error=>{console.error(error);process.exitCode=1});
