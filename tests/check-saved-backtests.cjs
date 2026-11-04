const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',handlers:{},disabled:false,querySelectorAll(){return []},addEventListener(k,fn){this.handlers[k]=fn}});return nodes.get(id)}
let view='january',running=false,artifact=null,next=0,requests=[],records=[],loaded=null,fail=false,failList=false,holdNextList=false,releaseList=null;
const snapshot={mode:'january',first:2015,last:2020,rank_from:1,rank_to:25,filters:[{field:'market_cap',op:'gt',value:100}]};
const result={cagr:.12,first:'2015-01-02',end:'2021-01-04',years:[{names:1,holdings:[{symbol:'SAVED',return_value:.5}],portfolio:.5,spy:.1}]};
const ctx=vm.createContext({document:{getElementById:node},Date,console,location:{protocol:'http:'},viewKey:()=>view,ScheduleView:{isRunning:()=>running},restoreSavedBacktest:value=>loaded=value,async fetch(url,options={}){
 requests.push({url,...options});if(fail)throw Error('Service disconnected');
 const id=url.split('/')[3],method=options.method||'GET';let value,status=200;
 if(method==='GET'&&!id&&failList)throw Error('List disconnected');
 if(method==='POST'&&id){const request=JSON.parse(options.body),record=records.find(r=>r.id===id);record.name=request.name;const {snapshot,...metadata}=record;value=metadata;}else if(method==='POST'){
  if(records.length===100){value={error:'All 100 saved slots are used.'};status=409;}
  else{const request=JSON.parse(options.body);value={id:String(++next).padStart(32,'0'),name:request.name,created_at:'2026-10-26T00:00:00Z',kind:request.snapshot.kind,start:request.snapshot.result.first,end:request.snapshot.result.end,cagr:request.snapshot.result.cagr,snapshot:request.snapshot};records.push(value);}
 }else if(method==='DELETE'){records=records.filter(r=>r.id!==id);value={deleted:true};}
 else value=id?records.find(r=>r.id===id):{limit:100,records:records.map(({snapshot,...metadata})=>metadata)};
 if(method==='POST'&&status<400){const {snapshot,...metadata}=value;value=metadata;}
 const packed=JSON.stringify(value);
 if(method==='GET'&&!id&&holdNextList){holdNextList=false;await new Promise(resolve=>releaseList=resolve);}
 return {ok:status<400,status,json:async()=>JSON.parse(packed)};
}});
ctx.ResultArtifacts={opening:()=>()=>true,release:()=>{},async use(source,consume){const response=await ctx.fetch((source.kind==='saved'?'/api/backtests/':'/api/backtest-queue/')+source.id);const record=await response.json();if(record.state==='archived')return {consumed:false,record};if(!record.snapshot)throw Error('This result is not ready yet.');return {consumed:true,value:consume(record.snapshot),record};}};
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/saved-backtests.js'),'utf8'),ctx);
const call=code=>vm.runInContext(code,ctx);ctx.snapshot=snapshot;ctx.result=result;
const settle=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 let copied=null,refuseCopy=false;
 ctx.readArtifact=()=>view==='latest'?null:artifact;ctx.isRunning=()=>running;ctx.openRecord=value=>loaded=value;
 ctx.copySettings=value=>{if(refuseCopy)throw Error('Save or cancel the queued edit before replacing the strategy settings.');copied=value;};
 call('SavedBacktests.init({current:readArtifact,isRunning,open:openRecord,copy:copySettings})');await settle();
 assert.equal(node('saved-count').textContent,'0 / 100');assert(node('save-backtest').disabled);
 artifact={version:2,kind:'january',settings:snapshot,result,presentation:{},catalog:{metrics:{},filters:{}}};call('SavedBacktests.update()');
 assert(!node('save-backtest').disabled);
 node('saved-name').value='<My strategy & stocks>';
 await node('save-backtest').handlers.click();
 assert.equal(records.length,1);assert.equal(records[0].snapshot.result.years[0].holdings[0].symbol,'SAVED');
 assert.equal(records[0].snapshot.settings.rank_to,25);assert.equal(records[0].name,'<My strategy & stocks>');
 assert(node('saved-list').innerHTML.includes('&lt;My strategy &amp; stocks&gt;'));assert(!node('saved-list').innerHTML.includes('<My strategy'));
 assert(node('saved-message').textContent.includes('Saved'));
 running=true;call('SavedBacktests.update()');assert(node('save-backtest').disabled);
 await node('save-backtest').handlers.click();assert.equal(records.length,1);running=false;call('SavedBacktests.update()');
 const first=records[0];await node('saved-list').handlers.click({target:{dataset:{open:first.id}}});
 assert.deepStrictEqual(JSON.parse(JSON.stringify(loaded.settings)),snapshot);
 assert.equal(loaded.result.years[0].holdings[0].symbol,'SAVED');
 assert(node('saved-message').textContent.includes('without rerunning'));
 assert(node('saved-list').innerHTML.includes('data-copy="'+first.id+'">Copy settings'));
 const storedBytes=JSON.stringify(first),displayed=loaded,beforeCopy=requests.length;
 await node('saved-list').handlers.click({target:{dataset:{copy:first.id}}});
 assert.deepStrictEqual(copied.settings,snapshot);assert.strictEqual(loaded,displayed);
 assert.equal(JSON.stringify(first),storedBytes);assert(requests.slice(beforeCopy).every(r=>!r.method));
 assert(node('saved-message').textContent.includes('Copied settings'));assert(node('saved-message').textContent.includes('Auto-run is off'));
 refuseCopy=true;copied=null;
 await node('saved-list').handlers.click({target:{dataset:{copy:first.id}}});
 assert.equal(copied,null);assert(node('saved-message').textContent.includes('Save or cancel'));refuseCopy=false;
 // Full IDs, inline rename, cancellation and acknowledgment survive list failure.
 assert(node('saved-list').innerHTML.includes('ID: '+first.id));
 node('saved-list').handlers.click({target:{dataset:{rename:first.id}}});
 assert(node('saved-list').innerHTML.includes('data-rename-input'));
 node('saved-list').handlers.input({target:{dataset:{renameInput:first.id},value:'  Renamed <book>  '}});
 failList=true;await node('saved-list').handlers.click({target:{dataset:{saveName:first.id}}});await settle();
 assert.equal(records[0].name,'Renamed <book>');assert.equal(records[0].snapshot.result.years[0].holdings[0].symbol,'SAVED');
 assert(node('saved-message').textContent.startsWith('Renamed'));assert(node('saved-message').textContent.includes('could not be refreshed'));
 assert(node('saved-list').innerHTML.includes('Renamed &lt;book&gt;'));
 failList=false;
 node('saved-list').handlers.click({target:{dataset:{rename:first.id}}});
 node('saved-list').handlers.input({target:{dataset:{renameInput:first.id},value:''}});
 const beforeInvalid=requests.length;
 await node('saved-list').handlers.click({target:{dataset:{saveName:first.id}}});assert.equal(requests.length,beforeInvalid);
 node('saved-list').handlers.click({target:{dataset:{cancelName:first.id}}});assert.equal(records[0].name,'Renamed <book>');
 // Ordinary buttons retain native keyboard activation, with or without a rename.
 async function key(data,key){let prevented=false;await node('saved-list').handlers.keydown({target:{dataset:data},key,preventDefault(){prevented=true}});return prevented;}
 for(const data of [{open:first.id},{rename:first.id},{delete:first.id},{}]){
  assert.equal(await key(data,'Enter'),false);assert.equal(await key(data,'Escape'),false);
 }
 node('saved-list').handlers.click({target:{dataset:{rename:first.id}}});
 assert.equal(await key({open:first.id},'Enter'),false);
 node('saved-list').handlers.input({target:{dataset:{renameInput:first.id},value:'Renamed <book>'}});
 assert.equal(await key({renameInput:first.id},'Enter'),true);await settle();
 assert.equal(records[0].name,'Renamed <book>');assert(!node('saved-list').innerHTML.includes('data-rename-input'));
 node('saved-list').handlers.click({target:{dataset:{rename:first.id}}});
 node('saved-list').handlers.input({target:{dataset:{renameInput:first.id},value:'Discard this name'}});
 const beforeEscape=requests.length;
 assert.equal(await key({renameInput:first.id},'Escape'),true);
 assert.equal(requests.length,beforeEscape);assert.equal(records[0].name,'Renamed <book>');
 assert(!node('saved-list').innerHTML.includes('data-rename-input'));
 // A failed save preserves the current display and every existing record.
 fail=true;await node('save-backtest').handlers.click();fail=false;
 assert.equal(records.length,1);assert(node('saved-message').textContent.includes('disconnected'));
 // An acknowledged mutation stays successful even when reconciliation fails.
 failList=true;node('saved-name').value='Acknowledged save';
 const beforeAcknowledged=requests.filter(r=>r.method==='POST').length;
 await node('save-backtest').handlers.click();await settle();
 assert.equal(records.length,2);assert.equal(node('saved-count').textContent,'2 / 100');
 assert(node('saved-message').textContent.startsWith('Saved “Acknowledged save”'));
 assert(node('saved-message').textContent.includes('could not be refreshed'));assert.notEqual(node('saved-message').className,'backtest-failed');
 assert.equal(requests.filter(r=>r.method==='POST').length,beforeAcknowledged+1);
 const acknowledged=records[1];
 node('saved-list').handlers.click({target:{dataset:{delete:acknowledged.id}}});
 await node('saved-list').handlers.click({target:{dataset:{confirm:acknowledged.id}}});await settle();
 assert.equal(records.length,1);assert.equal(node('saved-count').textContent,'1 / 100');
 assert(node('saved-message').textContent.startsWith('Saved backtest deleted.'));assert(node('saved-message').textContent.includes('could not be refreshed'));
 failList=false;await node('refresh-backtests').handlers.click();assert.equal(node('saved-message').textContent,'Saved list refreshed.');
 // A delayed older list must not revive a record deleted by a newer action.
 holdNextList=true;node('saved-name').value='Race';await node('save-backtest').handlers.click();
 assert(releaseList);const racing=records[1];
 node('saved-list').handlers.click({target:{dataset:{delete:racing.id}}});
 await node('saved-list').handlers.click({target:{dataset:{confirm:racing.id}}});await settle();
 releaseList();await settle();
 assert.equal(node('saved-count').textContent,'1 / 100');assert(!node('saved-list').innerHTML.includes(racing.id));
 for(let i=1;i<100;i++)records.push({...first,id:String(++next).padStart(32,'0'),name:'Book '+i});
 await node('refresh-backtests').handlers.click();assert.equal(node('saved-count').textContent,'100 / 100');assert(node('save-backtest').disabled);
 await node('save-backtest').handlers.click();assert.equal(records.length,100);assert(node('saved-message').textContent.includes('100'));
 const beforeDelete=requests.length;
 node('saved-list').handlers.click({target:{dataset:{delete:first.id}}});
 assert(node('saved-list').innerHTML.includes('Delete this saved backtest?'));
 node('saved-list').handlers.click({target:{dataset:{keep:first.id}}});assert.equal(requests.length,beforeDelete);
 node('saved-list').handlers.click({target:{dataset:{delete:first.id}}});
 await node('saved-list').handlers.click({target:{dataset:{confirm:first.id}}});
 assert.equal(records.length,99);assert(!node('save-backtest').disabled);assert.equal(loaded.result.years[0].holdings[0].symbol,'SAVED');
 await node('save-backtest').handlers.click();assert.equal(records.length,100);
 // Stored performance sorting handles negative, missing and tied values.
 records=[{...first,id:'a'.repeat(32),name:'Low',cagr:-.2},{...first,id:'b'.repeat(32),name:'High',cagr:.5},{...first,id:'c'.repeat(32),name:'Missing',cagr:null},{...first,id:'d'.repeat(32),name:'Tie',cagr:.5}];
 await node('refresh-backtests').handlers.click();
 node('saved-sort').value='performance-desc';node('saved-sort').handlers.change();
 let html=node('saved-list').innerHTML;assert(html.indexOf('<strong>High')<html.indexOf('<strong>Tie'));assert(html.indexOf('<strong>Tie')<html.indexOf('<strong>Low'));assert(html.indexOf('<strong>Low')<html.indexOf('<strong>Missing'));
 node('saved-sort').value='performance-asc';node('saved-sort').handlers.change();
 html=node('saved-list').innerHTML;assert(html.indexOf('<strong>Low')<html.indexOf('<strong>High'));assert(html.indexOf('<strong>Tie')<html.indexOf('<strong>Missing'));
 // Read the advertised capacity, including an older server's smaller limit.
 const oldFetch=ctx.fetch;ctx.fetch=async(...args)=>{const response=await oldFetch(...args);return {...response,json:async()=>({...await response.json(),limit:4})}};
 await node('refresh-backtests').handlers.click();assert.equal(node('saved-count').textContent,'4 / 4');assert(node('save-backtest').disabled);ctx.fetch=oldFetch;
 // Queue notification during an active library operation must get its own
 // reconciliation after that operation; the older list omits the new record.
 holdNextList=true;const refreshing=node('refresh-backtests').handlers.click();await settle();
 records.push({...first,id:'e'.repeat(32),name:'Transferred externally'});
 call('SavedBacktests.changed()');releaseList();await refreshing;await settle();
 assert(node('saved-list').innerHTML.includes('Transferred externally'));
 // Queue completion cannot rebuild a rename input or interrupt its focus.
 const renameTarget=records[0].id;
 for(const finish of ['cancel','escape','save']){
  node('saved-list').handlers.click({target:{dataset:{rename:renameTarget}}});
  node('saved-list').handlers.input({target:{dataset:{renameInput:renameTarget},value:'Typing '+finish}});
  const focused={id:'saved-rename-'+renameTarget};ctx.document.activeElement=focused;
  const beforeNotification=requests.length,beforeMarkup=node('saved-list').innerHTML;
  call('SavedBacktests.changed()');await settle();
  assert.equal(requests.length,beforeNotification);assert.equal(node('saved-list').innerHTML,beforeMarkup);
  assert.strictEqual(ctx.document.activeElement,focused);
  if(finish==='cancel')node('saved-list').handlers.click({target:{dataset:{cancelName:renameTarget}}});
  else if(finish==='escape')await key({renameInput:renameTarget},'Escape');
  else await node('saved-list').handlers.click({target:{dataset:{saveName:renameTarget}}});
  await settle();assert(requests.length>beforeNotification);assert(!node('saved-list').innerHTML.includes('data-rename-input'));
  if(finish==='save')assert.equal(records.find(record=>record.id===renameTarget).name,'Typing save');
 }
 view='latest';call('SavedBacktests.update()');assert(node('save-backtest').disabled);
 console.log('Passed: complete snapshot saving/opening, 100-record cap, explicit deletion, acknowledged save/delete despite refresh failure, stale-read exclusion and preserved displayed results.');
})().catch(error=>{console.error(error);process.exitCode=1});
