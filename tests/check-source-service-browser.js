/* Playwright qualification template. The disposable harness substitutes only
   __FIXTURE__; application functions, responses and downloads stay unchanged. */
async (page) => {
  const {url, expected, oracle, output, label}=__FIXTURE__;
  const assert=(ok,message)=>{if(!ok)throw Error(message);};
  const checks=[],downloads=[],errors=[];
  page.setDefaultTimeout(60000);
  page.on('pageerror',error=>errors.push(error.message));
  const equal=(a,b,where)=>{
    if(typeof b==='number')assert(Number.isFinite(a)&&Math.abs(a-b)<=Math.max(1e-12,Math.abs(b)*1e-12),where);
    else if(Array.isArray(b)){assert(Array.isArray(a)&&a.length===b.length,where+' length');b.forEach((v,i)=>equal(a[i],v,where+'['+i+']'));}
    else if(b&&typeof b==='object'){for(const [k,v] of Object.entries(b))if(!['seconds','execution'].includes(k))equal(a[k],v,where+'.'+k);}
    else assert(a===b,where+': '+a+' != '+b);
  };
  const parse=text=>{
    const rows=[];let row=[],field='',quoted=false;
    for(let i=0;i<text.length;i++){
      const ch=text[i];
      if(ch==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++;}else quoted=!quoted;}
      else if(ch===','&&!quoted){row.push(field);field='';}
      else if(ch==='\n'&&!quoted){row.push(field.replace(/\r$/,''));rows.push(row);row=[];field='';}
      else field+=ch;
    }
    if(field||row.length){row.push(field.replace(/\r$/,''));rows.push(row);}
    assert(!quoted,'Truncated CSV');const headers=rows.shift();
    return {headers,rows:rows.map(r=>Object.fromEntries(headers.map((h,i)=>[h,r[i]])))};
  };
  async function download(selector,reference,fields){
    const pending=page.waitForEvent('download');await page.locator(selector).click();
    const artifact=await pending;assert(await artifact.failure()===null,'Download failed');
    const stream=await artifact.createReadStream();let text='',bytes=0;
    for await(const chunk of stream){bytes+=chunk.length;assert(bytes<=16*1024**2,'Download bound');text+=chunk.toString('utf8');}
    const csv=parse(text);assert(csv.rows.length===reference.length,'CSV row count '+selector);
    for(const key of fields)assert(csv.headers.includes(key),'CSV header '+key);
    csv.rows.forEach((row,i)=>fields.forEach(key=>{
      const v=reference[i][key];
      if(typeof v==='number')equal(Number(row[key]),v,'CSV '+selector+'.'+i+'.'+key);
      else equal(row[key],String(v??''),'CSV '+selector+'.'+i+'.'+key);
    }));
    await artifact.saveAs(output+'/'+label+'-'+downloads.length+'-'+artifact.suggestedFilename());
    downloads.push({selector,name:artifact.suggestedFilename(),bytes,rows:csv.rows.length,headers:csv.headers});
    assert(downloads.reduce((n,d)=>n+d.bytes,0)<=16*1024**2,'Aggregate download bound');
  }
  async function submit(){await page.locator('#run-screen').click();await page.waitForFunction(()=>!document.querySelector('#run-screen').disabled);assert(await page.locator('#screen-error').textContent()==='','Browser screen error');}
  const stockFields=['rank','symbol','name','exchange','sector','market_cap','enterprise_value','metric_multiple','metric_yield','fiscal'];
  const stockEvidence=rows=>rows.map(h=>Object.fromEntries([...stockFields,'candidate_rank','ebitda_yield','ev_ebitda',
    'year','entry','exit','return_value','status','price','known','price_date'].filter(k=>k in h).map(k=>[k,h[k]])));
  await page.setViewportSize({width:1440,height:1000});
  await page.goto(url,{waitUntil:'networkidle'});
  await page.waitForFunction(()=>typeof currentLatest!=='undefined'&&currentLatest!==null);
  equal(stockEvidence(await page.evaluate(()=>currentLatest.stocks)),stockEvidence(expected.latest),'Latest SQL');
  assert(await page.locator('#latest-count').textContent()==='50','Latest displayed count');
  await download('#download-latest',expected.latest,[...stockFields,'price','known','price_date']);
  checks.push('default_latest_SQL_and_CSV');
  await page.locator('#stock-pool').selectOption('cached');
  await page.locator('#ranking-metric').selectOption('ev_ebitda_3y');
  await page.locator('#rank-to').fill('7');
  await page.locator('#add-filter').click();
  await page.locator('.condition-row select').nth(0).selectOption('pe');
  await page.locator('.condition-row select').nth(1).selectOption('lt');
  await page.locator('.condition-row input').fill('20');await submit();
  equal(stockEvidence(await page.evaluate(()=>currentLatest.stocks)),stockEvidence(expected.browser_latest),'Changed metric SQL');
  await download('#download-latest',expected.browser_latest,[...stockFields,'price','known','price_date']);
  checks.push('changed_metric_threshold_SQL_and_CSV');
  await page.locator('#reset-strategy').click();await page.locator('#mode-backtest').click();
  await page.locator('#stock-pool').selectOption('cached');
  await page.locator('#from-year').selectOption('2015');await page.locator('#to-year').selectOption('2016');
  await page.locator('#rank-from').fill('2');await page.locator('#rank-to').fill('4');await submit();
  equal(stockEvidence(await page.evaluate(()=>currentScreen.years.flatMap(y=>y.holdings))),stockEvidence(expected.browser_historical),'Historical SQL');
  const historical=expected.browser_historical.map(h=>({...h,weight:1/3,contribution_pp:h.return_value/3*100}));
  await download('#download-holdings',historical,[...stockFields,'year','entry','exit','return_value','status','weight','contribution_pp']);
  const years=await page.evaluate(()=>currentScreen.years);
  await download('#download-returns',years,['year','names','portfolio','spy','median_market_cap']);
  await page.locator('#min-cap').fill('1000000');await submit();
  assert(await page.evaluate(()=>currentScreen.empty_years.length===2&&currentScreen.cagr===null),'Empty-year coverage');
  checks.push('historical_year_rank_SQL_CSV_and_empty_coverage');
  await page.locator('#min-cap').fill('100');await page.locator('#rank-from').fill('1');
  await page.locator('#schedule-kind').selectOption('custom');
  await page.locator('#trade-start').fill('2015-01-01');await page.locator('#trade-end').fill('2016-12-30');
  await page.locator('#rebalance-months').selectOption('12');await page.locator('#date-testing').selectOption('single');
  const fixedResponse=page.waitForResponse(r=>r.url().endsWith('/api/schedule')&&r.request().method()==='POST');
  await submit();const fixed=await (await fixedResponse).json();equal(fixed,oracle.fixed,'Fixed direct-function oracle');
  const fixedStocks=fixed.periods.flatMap(p=>p.holdings.map(h=>({...h,period_start:p.entry,period_end:p.exit})));
  await download('#schedule-download-returns',fixed.periods,['entry','exit','names','portfolio','spy']);
  await download('#schedule-download-holdings',fixedStocks,[...stockFields,'period_start','period_end','entry','exit','return_value','weight','contribution_pp','status']);
  checks.push('fixed_schedule_HTTP_oracle_and_CSV');
  await page.locator('#date-testing').selectOption('random');await page.locator('#random-trials').fill('5');
  async function random(){
    const pending=page.waitForResponse(r=>r.url().endsWith('/api/robustness')&&r.request().method()==='POST');
    await submit();const sent=(await pending).request().postDataJSON();
    const configuration=await page.evaluate(()=>JSON.parse(localStorage.getItem('backtest-experiment')));
    assert((await page.locator('#schedule-message').textContent()).startsWith('Random-date test complete · 5 trials'),'Browser random completion');
    // CDP does not retain every streamed response body. Replay the recorded
    // seed through the ordinary API, then compare actual UI downloads below.
    const response=await page.request.post(url+'api/robustness',{data:{...sent,seed:configuration.seed}});
    const rows=(await response.text()).trim().split('\n').map(JSON.parse);
    assert(rows.at(-1).type==='complete','Incomplete random stream');return rows.at(-1).result;
  }
  const freshA=await random(),freshB=await random();
  assert(freshA.completed===5&&freshB.completed===5&&freshA.configuration.seed!==freshB.configuration.seed,'Fresh random seeds');
  await page.locator('.random-advanced summary').click();await page.locator('#repeat-random').check();
  await page.locator('#random-seed').fill('42');const seeded=await random();equal(seeded,oracle.random,'Random direct-function oracle');
  const cached=await random();equal(cached,seeded,'Cached random');assert(cached.execution.missing_books===0,'Cached random computed books');
  const trials=seeded.trials.map(t=>({...t,seed:42,months:12,dates:t.dates.join(';')}));
  await download('#robustness-download',trials,['trial','start','first_trade','end','cash_days','periods','cagr','spy_cagr','excess_cagr','total_return','growth','spy_growth','empty_periods','short_periods','seed','months','dates']);
  await page.locator('#robustness-trial').selectOption('2');
  const inspectedResponse=page.waitForResponse(r=>r.url().endsWith('/api/schedule')&&r.request().method()==='POST');
  await page.locator('#robustness-inspect').click();const inspected=await (await inspectedResponse).json();
  await page.waitForFunction(()=>!document.querySelector('#run-screen').disabled);equal(inspected,oracle.inspected,'Saved date inspection');
  await page.reload({waitUntil:'networkidle'});await page.locator('#mode-backtest').click();
  await page.locator('#schedule-kind').selectOption('custom');
  await page.waitForFunction(()=>!document.querySelector('#run-screen').disabled);
  const replayResponse=page.waitForResponse(r=>r.url().endsWith('/api/robustness')&&r.request().method()==='POST');
  await page.locator('#robustness-replay').click();const replaySent=(await replayResponse).request().postDataJSON();
  await page.waitForFunction(()=>!document.querySelector('#run-screen').disabled);
  const replay=await page.request.post(url+'api/robustness',{data:replaySent});
  const replayRows=(await replay.text()).trim().split('\n').map(JSON.parse);
  equal(replayRows.at(-1).result,seeded,'Reload saved replay');
  checks.push('fresh_random_cached_seed_inspection_real_CSV_reload_replay');
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile horizontal overflow');
  await page.screenshot({path:output+'/'+label+'-mobile.png'});
  await page.goto(url+'data.html',{waitUntil:'networkidle'});
  await page.locator('#data-scope').selectOption('symbols');await page.locator('#data-symbols').fill('ZZ000 ZZ063');
  await page.locator('#data-start').fill('2015-01-01');await page.locator('#data-end').fill('2016-12-30');
  await page.locator('#data-check').click();await page.waitForFunction(()=>document.querySelector('#data-message').textContent==='Data check complete.');
  assert(await page.locator('#data-error').textContent()==='','Panel check error');
  assert((await page.locator('#data-key').textContent()).toLowerCase().includes('missing'),'Missing key display');
  await page.locator('#data-rebuild').click();await page.waitForFunction(()=>document.querySelector('#data-message').textContent.startsWith('Rebuild complete.'));
  assert(await page.locator('#data-error').textContent()==='','Panel rebuild error');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Panel mobile overflow');
  await page.screenshot({path:output+'/'+label+'-panel-mobile.png'});
  checks.push('actual_panel_check_rebuild_mobile_layout');
  assert(errors.length===0,'Page errors '+errors.join('; '));
  return {label,checks,downloads,pageErrors:errors,financialTolerance:{absolute:1e-12,relative:1e-12},browserResources:'unqualified',realAdmission:'closed'};
}
