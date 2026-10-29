const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes=new Map();function node(id){if(!nodes.has(id))nodes.set(id,{value:'',checked:false,textContent:'',hidden:false,addEventListener(){}});return nodes.get(id)}
let sent;
const context=vm.createContext({document:{getElementById:node},console,location:{protocol:'http:'},ResultArtifacts:{forView:()=>null},BacktestRuns:{create(mode,options,planned){sent={mode,options,planned};throw Error('captured');}},fetch:async()=>({json:async()=>({calendar:1})})});
for(const file of ['calendar-settings.js','schedule.js'])vm.runInContext(fs.readFileSync(require('path').join(__dirname,'../website',file),'utf8'),context);
const run=code=>vm.runInContext(code,context);
(async()=>{
 await run('CalendarSettings.init()');node('date-testing').value='random';
 const legacy={start:'2015-01-02',end:'2015-02-27',months:12,requested:24,seed:42,options:{rank_to:3},samples:[['2015-01-05']]};
 const canonical={calendar:{version:1,start:legacy.start,end:legacy.end,interval:{unit:'week',count:1}},requested:24,seed:42,options:{rank_to:3},samples:legacy.samples};
 for(const [live,replay] of [[legacy,canonical],[canonical,legacy]]){
   context.live=live;context.replay=replay;
   run('CalendarSettings.restore(live)');
   await run('ScheduleView.run({rank_to:99},null,replay)');
   assert.equal(sent.options.rank_to,3);assert.deepEqual(sent.planned,replay);
   assert.equal('calendar' in sent.options,'calendar' in replay);
   assert.equal('months' in sent.options,'months' in replay);
   assert(!('calendar' in sent.options&&'start' in sent.options));
 }
 node('calendar-custom').checked=true;node('calendar-unit').value='month';node('calendar-count').value='104';sent=null;
 await run('ScheduleView.run({rank_to:3})');
 assert.equal(sent,null);assert.match(node('screen-error').textContent,/Invalid saved calendar/);
 context.restoreWide={mode:'custom',calendar:{version:1,start:'2015-01-02',end:'2016-12-30',interval:{unit:'week',count:104}}};
 node('calendar-count').max='24';run('CalendarSettings.restore(restoreWide)');
 assert.equal(node('calendar-unit').value,'week');assert.equal(node('calendar-count').max,'104');assert.equal(node('calendar-count').value,104);
 console.log('Passed: recorded replay ignores live filters and both calendar representation changes; invalid async inputs show validation without submission.');
})().catch(error=>{console.error(error);process.exitCode=1});
