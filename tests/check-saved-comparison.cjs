const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const CalendarSettings=require('../website/calendar-settings.js'),nodes=new Map(),copy=value=>JSON.parse(JSON.stringify(value));
function node(id){if(!nodes.has(id))nodes.set(id,{id,value:'',innerHTML:'',textContent:'',hidden:false,disabled:false,handlers:{},captures:{},querySelectorAll(){return []},addEventListener(event,fn,capture){this.handlers[event]=fn;this.captures[event]=capture}});return nodes.get(id)}
const make=(id,kind='custom',version=2)=>({id,name:'Saved '+id[0],created_at:'2026-11-01T00:00:00Z',kind,cagr:.12,start:'2015-01-02',end:'2020-12-31',snapshot:{version,kind,settings:{mode:kind,start:'2015-01-01',end:'2020-12-31',months:12,rank_to:id[0]==='a'?25:50},result:{start:'2015-01-02',end:'2020-12-31',cagr:.12,spy_cagr:.08,growth:2,producer:{engine:'original',label:'Original'},...(kind==='random'?{completed:2,valid:2,incomplete:0,configuration:{seed:42,window_start:'2015-01-02',window_end:'2020-12-31'},distributions:{cagr:{mean:.12,median:.11,p10:.05,p90:.2}}}:{}),periods:[]},catalog:{metrics:{},filters:{}},presentation:{},...(version===3?{evidence:{id:'e'.repeat(32)}}:{})}});
const ids=['a','b','c'].map(c=>c.repeat(32));let records=[make(ids[0]),make(ids[1],'random',3),make(ids[2])],requests=[],released=[],acquired=[],rejectAcquire=false,invalidAcquire=false,holdAcquire=false,releaseAcquire=null,comparisonPublished=0;
const main=Object.freeze({version:2,kind:'custom',settings:{mode:'custom'},result:{cagr:.99}});
const context=vm.createContext({document:{getElementById:node},location:{protocol:'http:'},crypto:require('node:crypto').webcrypto,Uint8Array,Date,console,CalendarSettings,ResultArtifacts:{opening(){throw Error('Comparison must not use main opening identity')},publish(){comparisonPublished++;throw Error('No main publication')},release:artifact=>released.push(artifact.evidence?.id),async acquire(source,display,id){
 acquired.push(id);const snapshot={...copy(records.find(record=>record.id===source.id).snapshot),evidence:{id}};
 if(holdAcquire){holdAcquire=false;await new Promise(resolve=>releaseAcquire=resolve);}
 if(rejectAcquire)throw Error('Lost acquisition response');
 if(invalidAcquire)snapshot.kind='invalid';
 return snapshot;
}},async fetch(url,options={}){
 requests.push({url,method:options.method||'GET'});const id=url.split('/')[3],record=records.find(record=>record.id===id);let value,status=200;
 if(options.method==='POST'){record.name=JSON.parse(options.body).name;const {snapshot,...metadata}=record;value=metadata;}
 else if(options.method==='DELETE'){records=records.filter(item=>item.id!==id);value={deleted:true};}
 else if(!id)value={limit:100,records:records.map(({snapshot,...metadata})=>metadata)};
 else if(record.snapshot.version===3){value={error:'Requires reader',requires_reader:true};status=409;}
 else value=record;
 return {ok:status<400,status,json:async()=>copy(value)};
}});
for(const name of ['backtest-comparison.js','saved-backtests.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../website',name),'utf8'),context);
const run=code=>vm.runInContext(code,context),settle=()=>new Promise(resolve=>setImmediate(resolve));
function choose(left,right){for(const [id,value] of [['saved-compare-left',left],['saved-compare-right',right]]){node(id).value=value;node(id).handlers.change();}}
(async()=>{
 run('SavedBacktests.init({current:()=>null,isRunning:()=>false,open:()=>{throw Error("No restoration")}})');await settle();
 choose(ids[0],ids[0]);assert(node('saved-compare').disabled);assert(node('saved-compare-message').textContent.includes('different'));
 choose(ids[0],ids[2]);assert(!node('saved-compare').disabled);await node('saved-compare').handlers.click();
 assert(!node('saved-comparison').hidden);assert(node('saved-comparison').innerHTML.includes('Different'));assert(node('saved-comparison').innerHTML.includes('comparison-different'));
 assert(node('saved-comparison').innerHTML.includes('Last rank'));assert(node('saved-comparison').innerHTML.includes('25'));assert(node('saved-comparison').innerHTML.includes('50'));
 assert.equal(comparisonPublished,0);assert.equal(main.result.cagr,.99);assert(requests.every(request=>request.method==='GET'));
 node('saved-sort').value='performance-desc';node('saved-sort').handlers.change();assert.equal(node('saved-compare-left').value,ids[0]);assert(!node('saved-comparison').hidden);
 node('saved-list').handlers.click({target:{dataset:{rename:ids[0]}}});
 node('saved-list').handlers.input({target:{dataset:{renameInput:ids[0]},value:'Renamed <comparison>'}});
 await node('saved-list').handlers.click({target:{dataset:{saveName:ids[0]}}});await settle();
 assert.equal(node('saved-compare-left').value,ids[0]);assert(node('saved-comparison').innerHTML.includes('Renamed &lt;comparison&gt;'));
 choose(ids[0],ids[1]);await node('saved-compare').handlers.click();assert.equal(acquired.length,1);assert.deepEqual(released,acquired);
 assert(node('saved-comparison').innerHTML.includes('not one portfolio return'));assert(node('saved-comparison').innerHTML.includes('P90 trial strategy CAGR'));
 // Readers release even when projection fails or acquisition acknowledgment is lost.
 invalidAcquire=true;await node('saved-compare').handlers.click();invalidAcquire=false;
 assert(node('saved-compare-message').textContent.includes('cannot be compared'));assert.deepEqual(released,acquired);
 rejectAcquire=true;await node('saved-compare').handlers.click();rejectAcquire=false;
 assert(node('saved-compare-message').textContent.includes('Lost acquisition response'));assert.deepEqual(released,acquired);
 // Clear and a changed selection invalidate late responses without changing main-view identity.
 choose(ids[1],ids[0]);holdAcquire=true;const pending=node('saved-compare').handlers.click();await settle();assert(releaseAcquire);
 node('saved-compare-clear').handlers.click();releaseAcquire();await pending;
 assert(node('saved-comparison').hidden);assert(node('saved-compare-message').textContent.includes('cleared'));assert.deepEqual(released,acquired);
 choose(ids[1],ids[0]);holdAcquire=true;const old=node('saved-compare').handlers.click();await settle();
 choose(ids[0],ids[2]);await node('saved-compare').handlers.click();const current=node('saved-comparison').innerHTML;releaseAcquire();await old;
 assert.equal(node('saved-comparison').innerHTML,current);assert.deepEqual(released,acquired);
 // All parameters is lazy, uses stored labels, escapes content and retains
 // expansion across sorting, rename and refresh without retaining readers.
 const toggle=(id,open=true)=>node('saved-list').handlers.toggle({target:{dataset:{parametersId:id},open}});
 assert.equal(node('saved-list').captures.toggle,true,'Native toggle requires capture delegation');
 records[0].snapshot.settings.filters=[{field:'fcf',op:'gt',value:-2}];
 records[0].snapshot.catalog.filters={fcf:{label:'<Original & cash flow>'}};
 records[0].snapshot.settings.future_setting='<img src=x onerror=bad>';
 const beforeDisclosure=requests.length;await toggle(ids[0]);
 assert.equal(requests.length,beforeDisclosure+1);assert(node('saved-list').innerHTML.includes('&lt;Original &amp; cash flow&gt;'));
 assert(node('saved-list').innerHTML.includes('&lt;img src=x onerror=bad&gt;'));assert(!node('saved-list').innerHTML.includes('<img src=x'));
 const beforeReopen=requests.length;await toggle(ids[0],false);await toggle(ids[0]);assert.equal(requests.length,beforeReopen);
 node('saved-sort').value='performance-asc';node('saved-sort').handlers.change();
 assert(node('saved-list').innerHTML.includes('data-parameters-id="'+ids[0]+'" open'));
 node('saved-list').handlers.click({target:{dataset:{rename:ids[0]}}});
 node('saved-list').handlers.input({target:{dataset:{renameInput:ids[0]},value:'Renamed with expanded parameters'}});
 await node('saved-list').handlers.click({target:{dataset:{saveName:ids[0]}}});await settle();
 assert(node('saved-list').innerHTML.includes('data-parameters-id="'+ids[0]+'" open'));
 await node('refresh-backtests').handlers.click();assert(node('saved-list').innerHTML.includes('&lt;Original &amp; cash flow&gt;'));
 const beforeEvidence=acquired.length;await toggle(ids[1]);assert.equal(acquired.length,beforeEvidence+1);assert.deepEqual(released,acquired);
 assert(node('saved-list').innerHTML.includes('Recorded random date set'));
 const retryId='d'.repeat(32);records.push(make(retryId,'custom',3));await node('refresh-backtests').handlers.click();
 rejectAcquire=true;await toggle(retryId);rejectAcquire=false;
 assert(node('saved-list').innerHTML.includes('Retry parameters'));assert.deepEqual(released,acquired);
 const beforeRetry=acquired.length;
 await node('saved-list').handlers.click({target:{dataset:{parametersRetry:retryId}}});
 assert.equal(acquired.length,beforeRetry+1);assert.deepEqual(released,acquired);
 const lateId='f'.repeat(32);records.push(make(lateId,'custom',3));await node('refresh-backtests').handlers.click();
 holdAcquire=true;const late=toggle(lateId);await settle();const duringLoad=acquired.length;
 await toggle(lateId);assert.equal(acquired.length,duringLoad,'Rerendered open details cannot duplicate pending loads');
 records=records.filter(record=>record.id!==lateId);await node('refresh-backtests').handlers.click();releaseAcquire();await late;
 assert(!node('saved-list').innerHTML.includes(lateId));assert.deepEqual(released,acquired);
 assert.equal(comparisonPublished,0);assert.equal(main.result.cagr,.99);
 // An external deletion reconciles selected IDs explicitly and drops the old comparison.
 records=records.filter(record=>record.id!==ids[2]);await node('refresh-backtests').handlers.click();
 assert.equal(node('saved-compare-right').value,'');assert(node('saved-comparison').hidden);assert(node('saved-compare-message').textContent.includes('deleted'));
 assert.equal(comparisonPublished,0);assert.equal(main.result.cagr,.99);
 console.log('Passed: exactly-two comparison, marked differences, same-view performance, sorting/rename identity, explicit deletion reconciliation, eager/v3 loading, failed/stale acquisition cleanup, lazy retained/retryable parameter disclosures and unchanged main view.');
})().catch(error=>{console.error(error);process.exitCode=1});
