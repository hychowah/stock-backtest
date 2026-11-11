const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const CalendarSettings=require('../website/browser/calendar-settings.js'),nodes=new Map(),copy=value=>JSON.parse(JSON.stringify(value));
function node(id){if(!nodes.has(id))nodes.set(id,{id,value:'',innerHTML:'',textContent:'',hidden:false,disabled:false,handlers:{},captures:{},querySelectorAll(){return []},addEventListener(event,fn,capture){this.handlers[event]=fn;this.captures[event]=capture}});return nodes.get(id)}
const make=(id,kind='custom',version=2)=>({id,name:'Saved '+id[0],created_at:'2026-11-01T00:00:00Z',kind,cagr:id[0]==='c'?.2:.12,start:'2015-01-02',end:'2020-12-31',snapshot:{version,kind,settings:{mode:kind,start:'2015-01-01',end:'2020-12-31',months:12,rank_to:id[0]==='a'?25:50},result:{start:'2015-01-02',end:'2020-12-31',cagr:id[0]==='c'?.2:.12,spy_cagr:.08,growth:2,producer:{engine:'original',label:'Original'},...(kind==='random'?{completed:2,valid:2,incomplete:0,configuration:{seed:42,window_start:'2015-01-02',window_end:'2020-12-31'},distributions:{cagr:{mean:.12,median:.11,p10:.05,p90:.2}}}:{}),periods:[]},catalog:{metrics:{},filters:{}},presentation:{},...(version===3?{evidence:{id:'e'.repeat(32)}}:{})}});
const ids=['a','b','c'].map(c=>c.repeat(32));let records=[make(ids[0]),make(ids[1],'random',3),make(ids[2])],requests=[],released=[],acquired=[],rejectAcquire=false,invalidAcquire=false,holdAcquire=false,releaseAcquire=null,holdList=false,releaseList=null,comparisonPublished=0;
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
   if(invalidAcquire)snapshot.kind='invalid';
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
(async()=>{
 run('SavedBacktests.init({current:()=>null,isRunning:()=>false,open:()=>{throw Error("No restoration")}})');await settle();
 // No row is read before a tick. A tick stays usable while a list action runs.
 assert(node('saved-comparison').hidden);assert.deepEqual(requests.map(request=>request.url),['/api/backtests']);
 records[0].snapshot.settings.filters=[{field:'fcf',op:'gt',value:-2}];
 records[0].snapshot.catalog.filters={fcf:{label:'<Original & cash flow>'}};
 records[0].snapshot.settings.future_setting='<img src=x onerror=bad>';
 holdList=true;const busy=refresh();await settle();assert(releaseList);
 await tick(ids[0]);releaseList();await busy;
 // One tick: the headline, the saved ID and every setting of that test in plain wording. The exact recorded text waits in a closed disclosure.
 assert(!node('saved-comparison').hidden);assert.deepEqual([loads(ids[0]),loads(ids[1]),loads(ids[2]),acquired.length],[1,0,0,0]);
 for(const shown of ['Saved a','Saved ID: '+ids[0],'Strategy CAGR 12.00%','Difference vs SPY +4.00 pp','Last rank 25'])assert(text(panel()).includes(shown),'Missing '+shown);
 assert(panel().includes('&lt;Original &amp; cash flow&gt;'));assert(panel().includes('&lt;img src=x onerror=bad&gt;'));assert(!panel().includes('<img src=x'));
 let [plain,exact]=panel().split('<details');
 assert(text(plain).includes('Minimum market cap (USD) $100M')&&!text(plain).includes('100000000'));assert(text('<details'+exact).startsWith('Exact recorded values'));assert(!exact.startsWith(' open'));
 assert(text(exact).includes('Minimum market cap (USD) 100000000')&&!text(exact).includes('Last rank'),'Only the settings with exact text are listed again');
 // Two ticks: one column per test. The first rows are exactly the settings that differ, then the headlines.
 await tick(ids[2]);assert.deepEqual([loads(ids[0]),loads(ids[1]),loads(ids[2])],[1,0,1]);
 let [top,all]=panel().split('<details');
 assert.deepEqual(rows(top),['Saved a Saved c','Settings that differ','Last rank 25 50','Additional AND conditions <Original & cash flow> > -2 None','Setting: future_setting <img src=x onerror=bad> Not recorded',
  'Headline','Strategy CAGR 12.00% 20.00%','SPY CAGR 8.00% 8.00%','Difference vs SPY +4.00 pp +12.00 pp','Growth of $1 $2.00 $2.00']);
 // Every measure and setting waits in a closed disclosure. Only setting rows carry the difference marker.
 assert(!all.startsWith(' open'));assert(text('<details'+all).startsWith('All measures and settings'));
 assert(!text(top).includes('Different'));assert(rows(all).includes('Last rank Different 25 50'));assert(rows(all).includes('Strategy CAGR 12.00% 20.00%'));assert(rows(all).includes('First rank 1 1'));
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
 assert(rows(top).includes('Test type Fixed dates Random dates Fixed dates'));assert(rows(all).includes('P90 trial strategy CAGR — 20.00% —'));
 assert(text(top).includes('not one portfolio return'));assert(text(top).includes('different test types'));
 // An unticked row leaves the panel. Its description stays, so a new tick reads nothing.
 await tick(ids[1],false);assert.equal(rows(panel())[0],'Renamed <comparison> Saved c');
 await tick(ids[1]);assert.equal(rows(panel())[0],'Renamed <comparison> Saved b Saved c');assert.equal(acquired.length,1);assert.equal(loads(ids[1]),1);
 await tick(ids[1],false);
 // A failed read is not kept: the row loses its tick, the status line gives the reason and the reader closes.
 const retryId='d'.repeat(32);records.push(make(retryId,'custom',3));await refresh();
 const two=panel();
 for(const [failure,reason] of [['reject','Lost acquisition response'],['invalid','Unsupported saved backtest format']]){
  rejectAcquire=failure==='reject';invalidAcquire=failure==='invalid';const before=acquired.length;await tick(retryId);rejectAcquire=invalidAcquire=false;
  assert.equal(acquired.length,before+1);assert.deepEqual(released,acquired);assert.equal(panel(),two);
  assert(node('saved-status').textContent.includes('Could not read “Saved d”'));assert(node('saved-status').textContent.includes(reason));assert.equal(node('saved-status').className,'backtest-failed');
 }
 const beforeRetry=acquired.length;await tick(retryId);assert.equal(acquired.length,beforeRetry+1);assert.deepEqual(released,acquired);assert.equal(rows(panel())[0],'Renamed <comparison> Saved c Saved d');
 await tick(retryId,false);assert.equal(panel(),two);
 // A late reply cannot change a newer state: the tick was removed during the read.
 const lateId='f'.repeat(32);records.push(make(lateId,'custom',3));await refresh();
 holdAcquire=true;const late=tick(lateId);await settle();assert(text(panel()).includes('Reading 1 stored result'));assert.equal(rows(panel())[0],'Renamed <comparison> Saved c');
 await tick(lateId,false);assert.equal(panel(),two);releaseAcquire();await late;assert.equal(panel(),two);assert.deepEqual(released,acquired);
 // A deleted row leaves the panel and the descriptions, also when its read is still in progress.
 const goneId='e'.repeat(32);records.push(make(goneId,'custom',3));await refresh();
 holdAcquire=true;const gone=tick(goneId);await settle();
 records=records.filter(record=>record.id!==goneId&&record.id!==ids[2]);await refresh();
 assert.equal(text(panel()).split(' Saved ID')[0],'1 test ticked Clear Renamed <comparison>','One ticked test remains');
 releaseAcquire();await gone;assert(!panel().includes('Saved e'));assert.deepEqual(released,acquired);
 records.push(make(ids[2]),make(goneId,'custom',3));await refresh();assert(!panel().includes('Saved c'),'A returned id has no tick');
 const beforeReturn=acquired.length;await tick(ids[2]);await tick(goneId);assert.equal(loads(ids[2]),2,'A deleted row left the descriptions');assert.equal(acquired.length,beforeReturn+1);assert.deepEqual(released,acquired);
 // A sort changes the column order with the row order. It reads nothing.
 const beforeSort=requests.length;node('saved-head').handlers.click({target:{dataset:{sort:'cagr'}}});
 assert.equal(rows(panel())[0],'Saved c Renamed <comparison> Saved e');assert.equal(requests.length,beforeSort);
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
 // The panel compares 8 tests at most: a ninth tick is refused with a reason, reads nothing, and the box loses its tick.
 clear();assert(records.length>=9);for(const record of records.slice(0,8))await tick(record.id);
 const ninth={dataset:{tick:records[8].id},checked:true},beforeNinth=requests.length;await node('saved-list').handlers.change({target:ninth});
 assert.equal(ninth.checked,false);assert(node('saved-status').textContent.includes('Untick a test first'));assert.equal(requests.length,beforeNinth);assert(text(panel()).startsWith('8 tests ticked'));
 await tick(records[0].id,false);ninth.checked=true;await node('saved-list').handlers.change({target:ninth});assert.equal(ninth.checked,true);assert(text(panel()).startsWith('8 tests ticked'));
 assert.deepEqual(released,acquired);assert.equal(comparisonPublished,0);assert.equal(main.result.cagr,.99);
 console.log('Passed: no read before a tick, one read per ticked test by one serial loader, the one-test panel with exact text, a panel that keeps its tests during a read, differing requested settings first with recorded facts in the full list, shared headline keys, marked setting differences only, Clear and the limit of 8 ticks, rename/sort identity, failed reads not kept, late replies and deleted rows discarded, released readers and unchanged main view.');
})().catch(error=>{console.error(error);process.exitCode=1});
