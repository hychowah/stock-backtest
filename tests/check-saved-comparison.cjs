const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const CalendarSettings=require('../website/browser/calendar-settings.js'),nodes=new Map(),copy=value=>JSON.parse(JSON.stringify(value));
function node(id){if(!nodes.has(id))nodes.set(id,{id,value:'',innerHTML:'',textContent:'',hidden:false,disabled:false,handlers:{},captures:{},querySelectorAll(){return []},addEventListener(event,fn,capture){this.handlers[event]=fn;this.captures[event]=capture}});return nodes.get(id)}
const make=(id,kind='custom',version=2)=>({id,name:'Saved '+id[0],created_at:'2026-11-01T00:00:00Z',kind,cagr:id[0]==='c'?.2:.12,start:'2015-01-02',end:'2020-12-31',snapshot:{version,kind,settings:{mode:kind,start:'2015-01-01',end:'2020-12-31',months:12,rank_to:id[0]==='a'?25:50},result:{start:'2015-01-02',end:'2020-12-31',cagr:id[0]==='c'?.2:.12,spy_cagr:.08,growth:2,producer:{engine:'original',label:'Original'},...(kind==='random'?{completed:2,valid:2,incomplete:0,configuration:{seed:42,window_start:'2015-01-02',window_end:'2020-12-31'},distributions:{cagr:{mean:.12,median:.11,p10:.05,p90:.2}}}:{}),periods:[]},catalog:{metrics:{},filters:{}},presentation:{},...(version===3?{evidence:{id:'e'.repeat(32)}}:{})}});
const ids=['a','b','c'].map(c=>c.repeat(32));let records=[make(ids[0]),make(ids[1],'random',3),make(ids[2])],requests=[],released=[],acquired=[],rejectAcquire=false,holdAcquire=false,releaseAcquire=null,holdList=false,releaseList=null,comparisonPublished=0;
const main=Object.freeze({version:2,kind:'custom',settings:{mode:'custom'},result:{cagr:.99}});
const context=vm.createContext({document:{getElementById:node},location:{protocol:'http:'},crypto:require('node:crypto').webcrypto,Uint8Array,Date,console,CalendarSettings,async fetch(url,options={}){
 requests.push({url,method:options.method||'GET'});
 if(url.startsWith('/api/backtest-runs/')){
   const id=url.split('/')[3];
   if(options.method==='DELETE'){released.push(id);return {ok:true,json:async()=>({released:true})};}
   acquired.push(id);const source=JSON.parse(options.body).source;
   const snapshot={...copy(records.find(record=>record.id===source.id).snapshot),evidence:{id,format_version:1,trials:2,periods:2,holdings:2}};
   if(holdAcquire){holdAcquire=false;await new Promise(resolve=>releaseAcquire=resolve);}
   if(rejectAcquire)throw Error('Lost acquisition response');
   return {ok:true,json:async()=>snapshot};
 }
 const id=url.split('/')[3],record=records.find(record=>record.id===id);let value,status=200;
 if(options.method==='POST'){record.name=JSON.parse(options.body).name;const {snapshot,...metadata}=record;value=metadata;}
 else if(options.method==='DELETE'){records=records.filter(item=>item.id!==id);value={deleted:true};}
 else if(!id){value={limit:100,records:records.map(({snapshot,...metadata})=>metadata)};if(holdList){holdList=false;await new Promise(resolve=>releaseList=resolve);}}
 else if(record.snapshot.version===3){value={error:'Requires reader',requires_reader:true};status=409;}
 else value=record;
 return {ok:status<400,status,json:async()=>copy(value)};
}});
for(const name of ['result-artifacts.js','backtest-comparison.js','saved-backtests.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser',name),'utf8'),context);
const run=code=>vm.runInContext(code,context);run('ResultArtifacts.opening=()=>{throw Error("Compact inspection cannot get a main-view ticket")};ResultArtifacts.publish=()=>{throw Error("Compact inspection cannot publish")};');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
// The panel as text: one entry per table row, or the whole panel.
const panel=()=>node('saved-comparison').innerHTML,text=html=>html.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim().replace(/&(lt|gt|amp);/g,(_,name)=>({lt:'<',gt:'>',amp:'&'}[name]));
const rows=html=>html.split('<tr').slice(1).map(row=>text('<tr'+row.split('</tr>')[0]));
const tick=(id,checked=true)=>node('saved-list').handlers.change({target:{dataset:{tick:id},checked}});
const loads=id=>requests.filter(request=>request.url==='/api/backtests/'+id&&request.method==='GET').length;
const refresh=()=>node('queue-refresh').handlers.click();
// Details of a row: the toggle of its control, and the markup of that row.
const open=(id,opened=true)=>node('saved-list').handlers.toggle({target:{dataset:{menu:id},open:opened}});
const row=id=>{const html=node('saved-list').innerHTML,start=html.indexOf('data-menu="'+id+'"');return start<0?'':html.slice(start,html.indexOf('</li>',start));};
(async()=>{
 run('SavedBacktests.init({open:()=>{throw Error("No restoration")}})');await settle();
 // No row is read before a tick or an open Details.
 assert(node('saved-comparison').hidden);assert.deepEqual(requests.map(request=>request.url),['/api/backtests']);
 records[0].snapshot.settings.filters=[{field:'fcf',op:'gt',value:-2}];
 records[0].snapshot.catalog.filters={fcf:{label:'<Original & cash flow>'}};
 records[0].snapshot.settings.future_setting='<img src=x onerror=bad>';
 assert.equal(node('saved-list').captures.toggle,true,'Native toggle needs capture on the list');
 assert(text(row(ids[0])).includes('Reading the saved settings…'));assert(text(row(ids[0])).includes('Tune'),'The actions do not wait for the read');
 // Details reads that test one time, without a tick, and shows its parameters in the row: one line with the market,
 // the test type, the window and the interval, then the settings that hold a value, the headline, the saved ID and the actions.
 await open(ids[0]);
 assert.deepEqual([loads(ids[0]),loads(ids[1]),loads(ids[2]),acquired.length],[1,0,0,0]);assert(node('saved-comparison').hidden,'Details ticks nothing');
 let [plain,exact]=row(ids[0]).split('Exact recorded values');
 const parts=['US · USD · Fixed dates · 2015-01-01 → 2020-12-31 · every 12 month(s)','Last rank: 25','Minimum market cap (USD): $100M','Strategy CAGR 12.00% · SPY CAGR 8.00% · Difference vs SPY +4.00 pp · Growth of $1 $2.00','Saved ID: '+ids[0]];
 for(const part of parts)assert(text(plain).includes(part),'Missing '+part);
 assert.deepEqual(parts.map(part=>text(plain).indexOf(part)),parts.map(part=>text(plain).indexOf(part)).sort((a,b)=>a-b),'The parts keep this order');
 assert(text(exact).indexOf('Tune')>text(exact).indexOf('Minimum market cap (USD): 100000000'),'The actions follow the settings');
 // A recorded fact and a default-only setting show in the closed list only. That list has every recorded row.
 for(const quiet of ['Requested engine: Original','Recorded producer: Original'])assert(!text(plain).includes(quiet)&&text(exact).includes(quiet),quiet);
 assert(!text(plain).includes('100000000')&&text(exact).includes('Last rank: 25'));
 assert(row(ids[0]).includes('&lt;Original &amp; cash flow&gt;'));assert(row(ids[0]).includes('&lt;img src=x onerror=bad&gt;'));assert(!row(ids[0]).includes('<img src=x'));
 // A second open, a list that is drawn again, a sort and a rename show the same text and read nothing.
 const first=row(ids[0]);await open(ids[0],false);await open(ids[0]);await refresh();await open(ids[0]);
 node('saved-head').handlers.click({target:{dataset:{sort:'name'}}});node('saved-head').handlers.click({target:{dataset:{sort:'saved'}}});
 assert.equal(row(ids[0]),first);assert.equal(loads(ids[0]),1);
 // A tick of that row reads nothing more. One tick shows the top line only; a tick stays usable while a list action runs.
 holdList=true;const busy=refresh();await settle();assert(releaseList);
 await tick(ids[0]);releaseList();await busy;
 assert(!node('saved-comparison').hidden);assert.equal(text(panel()),'1 test ticked. Tick another to compare. Clear');assert(!panel().includes('<table'));
 assert.deepEqual([loads(ids[0]),loads(ids[1]),loads(ids[2]),acquired.length],[1,0,0,0]);
 let top,all;
 // Two ticks: one column per test. The first rows are exactly the settings that differ, then the headlines.
 await tick(ids[2]);assert.deepEqual([loads(ids[0]),loads(ids[1]),loads(ids[2])],[1,0,1]);
 [top,all]=panel().split('<details');
 assert.deepEqual(rows(top),['Saved a Saved c','Settings that differ','Last rank 25 50','Additional AND conditions <Original & cash flow> > -2 None','Setting: future_setting <img src=x onerror=bad> Not recorded',
  'Headline','Strategy CAGR 12.00% 20.00%','SPY CAGR 8.00% 8.00%','Difference vs SPY +4.00 pp +12.00 pp','Growth of $1 $2.00 $2.00']);
 // Every setting waits in a closed disclosure. Fixed tests have no measure outside the headline, so its title is
 // All settings. Only setting rows carry the difference marker.
 assert(!all.startsWith(' open'));assert(text('<details'+all).startsWith('All settings'));assert(!rows(all).includes('More measures'));
 assert(!text(top).includes('Different'));assert(rows(all).includes('Last rank Different 25 50'));assert(rows(all).includes('First rank 1 1'));
 assert(rows(all).includes('Saved ID '+ids[0]+' '+ids[2]));
 assert.equal(comparisonPublished,0);assert.equal(main.result.cagr,.99);assert(requests.every(request=>request.method==='GET'),'A tick only reads');
 // A rename keeps the ticks and reads no result again.
 node('saved-list').handlers.click({target:{dataset:{rename:ids[0]}}});
 node('saved-list').handlers.input({target:{dataset:{renameInput:ids[0]},value:'Renamed <comparison>'}});
 await node('saved-list').handlers.click({target:{dataset:{saveName:ids[0]}}});await settle();
 assert(panel().includes('Renamed &lt;comparison&gt;'));assert.equal(rows(panel())[2],'Last rank 25 50');assert.deepEqual([loads(ids[0]),loads(ids[2])],[1,1]);
 // One loader reads one result at a time. A compact result uses a temporary reader, which closes after the read.
 // During a read the panel keeps the tests that it shows; its top line names the read.
 const shown=panel().split('</div>').slice(1).join('</div>');
 holdAcquire=true;const third=tick(ids[1]);await settle();assert(releaseAcquire);assert(text(panel()).startsWith('3 tests ticked Reading 1 stored result… Clear'));
 assert.equal(panel().split('</div>').slice(1).join('</div>'),shown,'The comparison below the top line does not change during a read');
 const extra='9'.repeat(32);records.push(make(extra));await refresh();const fourth=tick(extra);await settle();assert.equal(loads(extra),0,'The next read waits for the current one');
 assert(text(panel()).startsWith('4 tests ticked Reading 2 stored results… Clear'));assert.equal(rows(panel())[0],'Renamed <comparison> Saved c');
 releaseAcquire();await third;await fourth;assert.equal(loads(extra),1);assert.equal(acquired.length,1);assert.deepEqual(released,acquired);
 await tick(extra,false);
 // Tests of different types line up on the shared headline keys; a measure that a test lacks shows a dash.
 [top,all]=panel().split('<details');
 assert.equal(rows(top)[0],'Renamed <comparison> Saved b Saved c');assert(rows(top).includes('Strategy CAGR / Mean strategy CAGR 12.00% 12.00% 20.00%'));assert(rows(top).includes('Growth of $1 $2.00 — $2.00'));
 assert(rows(top).includes('Test type Fixed dates Random dates Fixed dates'));
 // With a random-date test the disclosure adds its 6 other measures, without a marker; a fixed test shows a dash there.
 assert(text('<details'+all).startsWith('More measures and all settings'));assert.equal(rows(all).indexOf('Settings')-rows(all).indexOf('More measures'),7);
 assert(rows(all).includes('Strategy CAGR, P10 to P90 — 5.00% to 20.00% —'));assert(rows(all).includes('Trials — 2 —'));
 assert(text(top).includes('not one portfolio return'));assert(text(top).includes('different test types'));
 // An unticked row leaves the panel. Its description stays, so a new tick reads nothing.
 await tick(ids[1],false);assert.equal(rows(panel())[0],'Renamed <comparison> Saved c');
 await tick(ids[1]);assert.equal(rows(panel())[0],'Renamed <comparison> Saved b Saved c');assert.equal(acquired.length,1);assert.equal(loads(ids[1]),1);
 await tick(ids[1],false);
 // A failed read is not kept: the row loses its tick, the status line gives the reason and the reader closes.
 // A new tick reads again.
 const retryId='d'.repeat(32);records.push(make(retryId,'custom',3));await refresh();
 const two=panel();
 rejectAcquire=true;const beforeRetry=acquired.length;await tick(retryId);rejectAcquire=false;
 assert.equal(acquired.length,beforeRetry+1);assert.deepEqual(released,acquired);assert.equal(panel(),two);
 assert(node('saved-status').textContent.includes('Could not read “Saved d”. Lost acquisition response'));assert.equal(node('saved-status').className,'backtest-failed');
 await tick(retryId);assert.equal(acquired.length,beforeRetry+2);assert.deepEqual(released,acquired);assert.equal(rows(panel())[0],'Renamed <comparison> Saved c Saved d');
 await tick(retryId,false);assert.equal(panel(),two);
 // A failed read of an opened row leaves its actions in place. A list that is drawn again, which fires toggle for
 // an open Details, does not read it again; closing and opening Details does.
 const failedId='7'.repeat(32);records.push(make(failedId,'custom',3));await refresh();
 rejectAcquire=true;const beforeFailed=acquired.length;await open(failedId);rejectAcquire=false;
 assert.equal(acquired.length,beforeFailed+1);assert(node('saved-status').textContent.includes('Could not read “Saved 7”'));
 assert(text(row(failedId)).includes('The saved settings were not read'));assert(text(row(failedId)).includes('Rename'),'The actions stay');
 await refresh();await open(failedId);assert.equal(acquired.length,beforeFailed+1);
 await open(failedId,false);await open(failedId);assert.equal(acquired.length,beforeFailed+2);assert(text(row(failedId)).includes('Last rank: 50'));
 // A sort changes the column order with the row order. It reads nothing.
 const beforeSort=requests.length;node('saved-head').handlers.click({target:{dataset:{sort:'cagr'}}});
 assert.equal(rows(panel())[0],'Saved c Renamed <comparison>');assert.equal(requests.length,beforeSort);
 // Clear removes every tick.
 const clear=()=>node('saved-comparison').handlers.click({target:{dataset:{clear:''}}});
 clear();assert(node('saved-comparison').hidden);assert.equal(panel(),'');assert(!node('saved-list').innerHTML.includes(' checked'));
 node('saved-comparison').handlers.click({target:{dataset:{}}});assert(node('saved-comparison').hidden,'Another click in the panel changes nothing');
 // Recorded facts are not requested settings: two random tests with equal settings and fresh dates have the same
 // settings. The recorded date sets still show, marked, in the full list.
 const fresh=['1','2'].map((digit,index)=>{const record=make(digit.repeat(32),'random',3);record.snapshot.result.configuration.seed=42+index;return record;});
 records.push(...fresh);await refresh();await tick(fresh[0].id);await tick(fresh[1].id);
 [top,all]=panel().split('<details');
 assert.deepEqual(rows(top).slice(0,3),['Saved 1 Saved 2','Same settings','Headline']);assert(rows(all).includes('Recorded random date set Different 42 43'));
 assert.deepEqual(released,acquired);assert.equal(comparisonPublished,0);assert.equal(main.result.cagr,.99);
 console.log('Passed: no read before a tick or an open Details, one read per test by one serial loader, Details with the settings in the row and every recorded row in a closed disclosure, one tick without a table, a panel that keeps its tests during a read, differing requested settings first with recorded facts in the full list, shared headline keys, the short list of other measures for random dates, marked setting differences only, Clear, rename/sort identity, failed reads not kept and read again by a new tick or a reopened Details, released readers and unchanged main view.');
})().catch(error=>{console.error(error);process.exitCode=1});
