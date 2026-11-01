const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../website/browser/backtest-runs.js'),'utf8');
const storage=new Map();let clock=Date.now();
const recordKey=id=>'backtest-server-run:'+id;
function page(fetch){
  const context=vm.createContext({fetch,AbortController,crypto:require('node:crypto').webcrypto,Uint8Array,Date:class extends Date{static now(){return ++clock}},
    // Short polling ticks keep transport tests independent of wall-clock speed.
    setTimeout:(fn,ms)=>setTimeout(fn,ms===1000?1:ms),clearTimeout,
    localStorage:{get length(){return storage.size},key:index=>[...storage.keys()][index],getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)}});
  vm.runInContext(source,context);
  return {context,run:code=>vm.runInContext(code,context)};
}
const reply=(payload,status=200)=>({ok:status<400,status,json:async()=>payload});
(async()=>{
  let alive=true,requests=[];
  const original=page(async(url,options)=>{requests.push({url,options});return reply({state:'running',progress:{completed:0}})});
  const submitted=original.run('BacktestRuns.create("random",{start:"2015-01-01",trials:3})');
  assert.match(submitted.id,/^[a-f0-9]{32}$/);
  assert.equal(JSON.parse(storage.get(recordKey(submitted.id))).id,submitted.id,'Persist ID before submitting');
  original.context.update=()=>alive=false;original.context.current=()=>alive;original.context.job=submitted;
  await original.run('BacktestRuns.follow(job,update,{current})');
  assert.equal(requests.length,1);assert.equal(requests[0].options.method,'POST');
  assert(!requests[0].options.signal.aborted,'Closing the view must not request cancellation');

  // A new page has no in-memory state. It recovers via localStorage and GET.
  requests=[];
  const reopened=page(async(url,options)=>{requests.push({url,options});return reply(url.endsWith('/status')?{state:'complete'}:{state:'complete',result:{completed:3,trial_results:[{stocks:['A']}]}})});
  const recovered=await reopened.run('BacktestRuns.follow(BacktestRuns.pending(),()=>{})');
  assert.equal(recovered.result.completed,3);assert.equal(recovered.result.trial_results[0].stocks[0],'A');
  assert.equal(requests.length,2);assert(requests.every(request=>request.options.method==='GET'));
  assert(requests[0].url.endsWith(submitted.id+'/status'));assert(requests[1].url.endsWith(submitted.id));
  assert(storage.has(recordKey(submitted.id)),'Retain completed ID for another reopen');
  storage.clear();

  // A lost start acknowledgement retries one ID and identical options.
  requests=[];
  const uncertain=page(async(url,options)=>{
    requests.push({url,options});if(requests.length===1)throw TypeError('offline');
    return reply({state:'complete',result:{periods:[]}});
  });
  uncertain.run('const job=BacktestRuns.create("custom",{months:3})');
  const updates=[];uncertain.context.update=state=>updates.push(state.state);
  await uncertain.run('BacktestRuns.follow(job,update,{})');
  assert.equal(requests.length,2);assert.equal(requests[0].url,requests[1].url);
  assert.equal(requests[0].options.body,requests[1].options.body);assert(updates.includes('reconnecting'));

  // Dropped polling requests never submit another calculation or stop it.
  requests=[];
  const disconnected=page(async(url,options)=>{
    requests.push({url,options});if(requests.length===1)throw TypeError('phone locked');
    return reply({state:'complete',result:{periods:[]}});
  });
  await disconnected.run('BacktestRuns.follow(BacktestRuns.pending(),()=>{})');
  assert(requests.every(r=>r.options.method==='GET'));

  // Explicit Stop survives refresh and lost acknowledgements, then clears ID.
  requests=[];
  disconnected.run('BacktestRuns.stop(BacktestRuns.pending())');
  const stopping=page(async(url,options)=>{
    requests.push({url,options});if(requests.length===1)throw TypeError('offline');
    return reply({state:'cancelled'});
  });
  assert.equal((await stopping.run('BacktestRuns.follow(BacktestRuns.pending(),()=>{})')).state,'cancelled');
  assert(requests.every(r=>r.options.method==='POST'&&r.url.endsWith('/stop')));
  assert.equal(storage.size,0);

  // An expired/restarted job reports the loss without silently starting again.
  requests=[];
  const missing=page(async(url,options)=>{requests.push({url,options});return reply({error:'Run expired'},404)});
  const expired=missing.run('BacktestRuns.create("custom",{})');
  storage.set(recordKey(expired.id)+':accepted','1');
  await assert.rejects(missing.run('BacktestRuns.follow(BacktestRuns.pending(),()=>{})'),/Run expired/);
  assert.equal(requests.length,1);assert.equal(requests[0].options.method,'GET');assert.equal(storage.size,0);

  // Rejected submissions clear their ID and do not loop in reconnect mode.
  const busy=page(async()=>reply({error:'Another backtest is running'},409));
  busy.run('const job=BacktestRuns.create("custom",{})');
  await assert.rejects(busy.run('BacktestRuns.follow(job,()=>{},{})'),/Another backtest/);
  assert.equal(storage.size,0);
  // Refresh before acknowledgement reconciles through the same idempotent POST.
  storage.clear();requests=[];let acknowledge,originalAlive=true;
  const submitting=page((url,options)=>{requests.push({url,options});return new Promise(resolve=>acknowledge=resolve)});
  submitting.run('const job=BacktestRuns.create("custom",{months:6})');
  submitting.context.current=()=>originalAlive;
  const oldFollow=submitting.run('BacktestRuns.follow(job,()=>{},{current})');
  originalAlive=false;
  const refreshing=page(async(url,options)=>{requests.push({url,options});return reply({state:'complete',result:{periods:[]}})});
  await refreshing.run('BacktestRuns.recover()');
  assert.equal(requests.length,2);assert.equal(requests[0].url,requests[1].url);
  assert.equal(requests[0].options.body,requests[1].options.body);assert.equal(requests[1].options.method,'POST');
  acknowledge(reply({state:'running'}));await oldFollow;
  assert.equal(refreshing.run('BacktestRuns.pending().phase'),'complete','A late acknowledgement cannot regress completion');

  // Another tab's rejected admission removes only its own provisional record.
  storage.clear();requests=[];let observing=true;
  const active=page(async()=>reply({state:'running'}));
  active.run('const job=BacktestRuns.create("random",{trials:2})');
  active.context.current=()=>observing;active.context.update=()=>observing=false;
  await active.run('BacktestRuns.follow(job,update,{current})');
  const accepted=active.run('BacktestRuns.pending()');
  const competitor=page(async()=>reply({error:'Another backtest is running'},409));
  const rejected=competitor.run('const job=BacktestRuns.create("custom",{months:1});job');
  assert.notEqual(rejected.id,accepted.id);assert(storage.has(recordKey(accepted.id)));
  assert.equal(competitor.run('BacktestRuns.pending().id'),rejected.id,'Keep the uncertain submission available for reconciliation');
  await assert.rejects(competitor.run('BacktestRuns.follow(job,()=>{})'),/Another backtest/);
  const recovery=page(async()=>reply({state:'complete',result:{completed:2}}));
  assert.equal(recovery.run('BacktestRuns.pending().id'),accepted.id);
  assert(!storage.has(recordKey(rejected.id)));assert(storage.has(recordKey(accepted.id)));

  // Stop is independent of another observer's delayed acknowledgement.
  let lateResponse,observerAlive=true;
  const observer=page(()=>new Promise(resolve=>lateResponse=resolve));
  observer.context.current=()=>observerAlive;
  const late=observer.run('BacktestRuns.follow(BacktestRuns.pending(),()=>{},{current})');
  active.run('BacktestRuns.stop(job)');observerAlive=false;
  lateResponse(reply({state:'running'}));await late;
  assert.equal(recovery.run('BacktestRuns.pending().stop'),true);
  requests=[];
  const stopper=page(async(url,options)=>{requests.push({url,options});return reply({state:'cancelled'})});
  await stopper.run('BacktestRuns.follow(BacktestRuns.pending(),()=>{})');
  assert(requests[0].url.endsWith('/stop'));assert.equal(storage.size,0);

  // Stop before initial acknowledgement first reconciles admission, then stops.
  const unacknowledged=page(async()=>reply({state:'running'}));
  unacknowledged.run('const job=BacktestRuns.create("custom",{});BacktestRuns.stop(job)');
  requests=[];
  const resumedStop=page(async(url,options)=>{requests.push({url,options});return reply({state:url.endsWith('/stop')?'cancelled':'running'})});
  await resumedStop.run('BacktestRuns.follow(BacktestRuns.pending(),()=>{})');
  assert.equal(requests.length,2);assert.equal(requests[0].options.method,'POST');assert(!requests[0].url.endsWith('/stop'));
  assert(requests[1].url.endsWith('/stop'));assert.equal(storage.size,0);

  // Reconcile an older tab's unobserved completion before choosing a result.
  const remote=new Map();requests=[];let watching=true;
  const service=async(url,options)=>{
    requests.push({url,options});const id=url.split('/')[3],state=remote.get(id);
    if(!state)return reply({error:'Run expired'},404);
    return reply(url.endsWith('/status')?{state:state.state}:state);
  };
  const tabA=page(service);const older=tabA.run('const job=BacktestRuns.create("custom",{months:3});job');
  remote.set(older.id,{state:'running'});
  tabA.context.current=()=>watching;tabA.context.update=()=>watching=false;
  await tabA.run('BacktestRuns.follow(job,update,{current})');
  remote.set(older.id,{state:'complete',result:{label:'older'}});
  const tabB=page(service);const newer=tabB.run('const job=BacktestRuns.create("custom",{months:6});job');
  remote.set(newer.id,{state:'complete',result:{label:'newer'}});
  await tabB.run('BacktestRuns.follow(job,()=>{})');
  const returning=page(service);const chosen=await returning.run('BacktestRuns.recover()');
  assert.equal(chosen.id,newer.id,'The older accepted record is not proof of active work');
  returning.context.chosen=chosen;
  assert.equal((await returning.run('BacktestRuns.follow(chosen,()=>{})')).result.label,'newer');

  // Genuinely active work wins; expired/failed/stopped candidates are skipped.
  remote.set(older.id,{state:'running'});
  assert.equal((await returning.run('BacktestRuns.recover()')).id,older.id);
  remote.set(older.id,{state:'failed'});
  remote.delete(newer.id);
  assert.equal(await returning.run('BacktestRuns.recover()'),null);
  assert.equal(storage.size,0);
  const fallback=returning.run('BacktestRuns.create("custom",{})');
  storage.set(recordKey(fallback.id)+':accepted','1');remote.set(fallback.id,{state:'complete',result:{label:'kept'}});
  const stopped=returning.run('BacktestRuns.create("custom",{})');
  storage.set(recordKey(stopped.id)+':accepted','1');remote.set(stopped.id,{state:'cancelled'});
  const expiredRun=returning.run('BacktestRuns.create("custom",{})');storage.set(recordKey(expiredRun.id)+':accepted','1');
  assert.equal((await returning.run('BacktestRuns.recover()')).id,fallback.id);
  assert(!storage.has(recordKey(stopped.id)));assert(!storage.has(recordKey(expiredRun.id)));
  console.log('Passed: closed-page recovery, retained results, idempotent submission, network retries, explicit Stop recovery, expired runs, uncertain-submission refresh, competing tabs and monotonic Stop recovery.');
})().catch(error=>{console.error(error);process.exitCode=1});
