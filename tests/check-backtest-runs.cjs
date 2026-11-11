const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../website/browser/backtest-runs.js'),'utf8');
// The page has no browser storage here: the client keeps no record of a screen.
function page(fetch){
  const context=vm.createContext({fetch,AbortController,crypto:require('node:crypto').webcrypto,Uint8Array,
    // Short polling ticks keep transport tests independent of wall-clock speed.
    setTimeout:(fn,ms)=>setTimeout(fn,ms===1000?1:ms),clearTimeout});
  vm.runInContext(source,context);
  return {context,run:code=>vm.runInContext(code,context)};
}
const reply=(payload,status=200)=>({ok:status<400,status,json:async()=>payload});
const screened={state:'complete',evidence:{manifest:{periods:0}}};
(async()=>{
  // The client submits latest screens only, and it has no request that stops work.
  let alive=true,requests=[];
  const original=page(async(url,options)=>{requests.push({url,options});return reply({state:'running',progress:null})});
  const submitted=original.run('BacktestRuns.create({strategy:{steps:3}})');
  assert.match(submitted.id,/^[a-f0-9]{32}$/);
  original.context.update=()=>alive=false;original.context.current=()=>alive;original.context.job=submitted;
  assert.equal(await original.run('BacktestRuns.follow(job,update,{current})'),null);
  assert.equal(requests.length,1);assert.equal(requests[0].url,'/api/backtest-runs/'+submitted.id);assert.equal(requests[0].options.method,'POST');
  assert.deepEqual(JSON.parse(requests[0].options.body),{mode:'latest',options:{strategy:{steps:3}}});
  assert(!requests[0].options.signal.aborted,'A page that stops asking does not abort the screen');

  // An accepted screen is followed by status requests until it ends. The last state goes to the caller.
  requests=[];
  const followed=page(async(url,options)=>{requests.push({url,options});return reply(requests.length<3?{state:'running'}:screened)});
  followed.run('const job=BacktestRuns.create({strategy:{steps:4}})');
  assert.deepEqual(await followed.run('BacktestRuns.follow(job,()=>{})'),screened);
  assert.deepEqual(requests.map(r=>r.options.method),['POST','GET','GET']);assert(requests[1].url.endsWith(followed.run('job.id')+'/status'));

  // A lost start acknowledgement retries one ID and identical options.
  requests=[];
  const uncertain=page(async(url,options)=>{
    requests.push({url,options});if(requests.length===1)throw TypeError('offline');
    return reply(screened);
  });
  uncertain.run('const job=BacktestRuns.create({strategy:{steps:2}})');
  const updates=[];uncertain.context.update=state=>updates.push(state.state);
  await uncertain.run('BacktestRuns.follow(job,update,{})');
  assert.equal(requests.length,2);assert.equal(requests[0].url,requests[1].url);
  assert.equal(requests[0].options.body,requests[1].options.body);assert(updates.includes('reconnecting'));

  // Dropped polling requests never submit another screen.
  requests=[];
  const disconnected=page(async(url,options)=>{
    requests.push({url,options});if(requests.length===2)throw TypeError('phone locked');
    return reply(requests.length===1?{state:'running'}:screened);
  });
  disconnected.run('const job=BacktestRuns.create({})');
  await disconnected.run('BacktestRuns.follow(job,()=>{})');
  assert.deepEqual(requests.map(r=>r.options.method),['POST','GET','GET']);

  // An expired or restarted run reports the loss without starting again.
  requests=[];
  const missing=page(async(url,options)=>{requests.push({url,options});return requests.length===1?reply({state:'running'}):reply({error:'Run expired'},404)});
  missing.run('const job=BacktestRuns.create({})');
  await assert.rejects(missing.run('BacktestRuns.follow(job,()=>{})'),/Run expired/);
  assert.deepEqual(requests.map(r=>r.options.method),['POST','GET']);

  // A refused submission ends at once and does not loop in reconnect mode. A failed screen returns its state.
  const busy=page(async()=>reply({error:'Another backtest is running'},409));
  busy.run('const job=BacktestRuns.create({})');
  await assert.rejects(busy.run('BacktestRuns.follow(job,()=>{},{})'),/Another backtest/);
  const failed=page(async()=>reply({state:'failed',error:'Fix the strategy',code:'INVALID'}));
  failed.run('const job=BacktestRuns.create({})');
  assert.equal((await failed.run('BacktestRuns.follow(job,()=>{})')).error,'Fix the strategy');
  console.log('Passed: latest-only submission without a stored record, status requests until the end, idempotent submission, network retries, expired runs, refused and failed screens.');
})().catch(error=>{console.error(error);process.exitCode=1});
