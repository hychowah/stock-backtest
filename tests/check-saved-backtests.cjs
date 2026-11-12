const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',handlers:{},disabled:false,querySelectorAll(){return []},addEventListener(k,fn){this.handlers[k]=fn}});return nodes.get(id)}
let next=0,requests=[],records=[],loaded=null,failList=false,holdNextList=false,releaseList=null;
const snapshot={mode:'january',first:2015,last:2020,rank_from:1,rank_to:25,filters:[{field:'market_cap',op:'gt',value:100}]};
const result={cagr:.12,first:'2015-01-02',end:'2021-01-04',years:[{names:1,holdings:[{symbol:'SAVED',return_value:.5}],portfolio:.5,spy:.1}]};
// The server saves a queue test when it finishes. The page only reads, renames and deletes saved records.
const stored=name=>{const record={id:String(++next).padStart(32,'0'),name,created_at:'2026-10-26T00:00:00Z',kind:'january',start:result.first,end:result.end,cagr:result.cagr,snapshot:{version:2,kind:'january',settings:snapshot,result,presentation:{},catalog:{metrics:{},filters:{}}}};records.push(record);return record;};
const ctx=vm.createContext({document:{getElementById:node},Date,console,location:{protocol:'http:'},async fetch(url,options={}){
 requests.push({url,...options});
 const id=url.split('/')[3],method=options.method||'GET';let value;
 if(method==='GET'&&!id&&failList)throw Error('List disconnected');
 assert(id||method==='GET','The page saves nothing itself');
 if(method==='POST'){const request=JSON.parse(options.body),record=records.find(r=>r.id===id);if('locked' in request){record.locked=request.locked;value={id,locked:request.locked};}else{record.name=request.name;const {snapshot,...metadata}=record;value=metadata;}}
 else if(method==='DELETE'){records=records.filter(r=>r.id!==id);value={deleted:true};}
 else value=id?records.find(r=>r.id===id):{limit:100,records:records.map(({snapshot,...metadata})=>metadata)};
 const packed=JSON.stringify(value);
 if(method==='GET'&&!id&&holdNextList){holdNextList=false;await new Promise(resolve=>releaseList=resolve);}
 return {ok:true,status:200,json:async()=>JSON.parse(packed)};
}});
ctx.ResultArtifacts={opening:()=>()=>true,release:()=>{},async use(source,consume){const response=await ctx.fetch((source.kind==='saved'?'/api/backtests/':'/api/backtest-queue/')+source.id);const record=await response.json();if(record.state==='archived')return {consumed:false,record};if(!record.snapshot)throw Error('This result is not ready yet.');return {consumed:true,value:consume(record.snapshot),record};}};
for(const name of ['run-markets.js','saved-backtests.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser',name),'utf8'),ctx);
const call=code=>vm.runInContext(code,ctx);ctx.snapshot=snapshot;ctx.result=result;
const settle=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 let copied=null,refuseCopy=false;
 ctx.openRecord=value=>loaded=value;
 ctx.copySettings=value=>{if(refuseCopy)throw Error('Save or cancel the queued edit before replacing the strategy settings.');copied=value;};
 call('SavedBacktests.init({open:openRecord,copy:copySettings})');await settle();
 assert.equal(node('saved-count').textContent,'0 / 100');
 // A test that the queue saved shows after the queue says that the library changed.
 const first=stored('<My strategy & stocks>');call('SavedBacktests.changed()');await settle();
 assert.equal(node('saved-count').textContent,'1 / 100');
 assert(node('saved-list').innerHTML.includes('&lt;My strategy &amp; stocks&gt;'));assert(!node('saved-list').innerHTML.includes('<My strategy'));
 await node('saved-list').handlers.click({target:{dataset:{open:first.id}}});
 assert.deepStrictEqual(JSON.parse(JSON.stringify(loaded.settings)),snapshot);
 assert.equal(loaded.result.years[0].holdings[0].symbol,'SAVED');
 // A list action reports above the Saved backtests rows.
 assert(node('saved-status').textContent.includes('without rerunning'));
 assert(node('saved-list').innerHTML.includes('>Tune<'));
 const storedBytes=JSON.stringify(first),displayed=loaded,beforeCopy=requests.length;
 await node('saved-list').handlers.click({target:{dataset:{copy:first.id}}});
 assert.deepStrictEqual(copied.settings,snapshot);assert.strictEqual(loaded,displayed);
 assert.equal(JSON.stringify(first),storedBytes);assert(requests.slice(beforeCopy).every(r=>!r.method));
 assert(node('saved-status').textContent.includes('Copied settings'));assert(node('saved-status').textContent.includes('select Add to queue'));
 refuseCopy=true;copied=null;
 await node('saved-list').handlers.click({target:{dataset:{copy:first.id}}});
 assert.equal(copied,null);assert(node('saved-status').textContent.includes('Save or cancel'));refuseCopy=false;
 // A tick box also sends input events; without a rename they change nothing.
 node('saved-list').handlers.input({target:{dataset:{tick:first.id},value:'on'}});
 // Inline rename, cancellation and acknowledgment survive list failure.
 node('saved-list').handlers.click({target:{dataset:{rename:first.id}}});
 assert(node('saved-list').innerHTML.includes('data-rename-input'));
 node('saved-list').handlers.input({target:{dataset:{renameInput:first.id},value:'  Renamed <book>  '}});
 failList=true;await node('saved-list').handlers.click({target:{dataset:{saveName:first.id}}});await settle();
 assert.equal(records[0].name,'Renamed <book>');assert.equal(records[0].snapshot.result.years[0].holdings[0].symbol,'SAVED');
 assert(node('saved-status').textContent.startsWith('Renamed'));assert(node('saved-status').textContent.includes('could not be refreshed'));
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
 // An acknowledged mutation stays successful even when reconciliation fails.
 const acknowledged=stored('Acknowledged');await node('queue-refresh').handlers.click();assert.equal(node('saved-count').textContent,'2 / 100');
 failList=true;
 node('saved-list').handlers.click({target:{dataset:{delete:acknowledged.id}}});
 await node('saved-list').handlers.click({target:{dataset:{confirm:acknowledged.id}}});await settle();
 assert.equal(records.length,1);assert.equal(node('saved-count').textContent,'1 / 100');
 assert(node('saved-status').textContent.startsWith('Saved backtest deleted.'));assert(node('saved-status').textContent.includes('could not be refreshed'));assert.notEqual(node('saved-status').className,'backtest-failed');
 // The one Refresh of Runs reads the Saved backtests rows again.
 failList=false;await node('queue-refresh').handlers.click();assert.equal(node('saved-status').textContent,'Saved backtests refreshed.');
 // A delayed older list must not revive a record deleted by a newer action.
 const racing=stored('Race');await node('queue-refresh').handlers.click();
 node('saved-list').handlers.click({target:{dataset:{rename:first.id}}});node('saved-list').handlers.input({target:{dataset:{renameInput:first.id},value:'Renamed <book>'}});
 holdNextList=true;await node('saved-list').handlers.click({target:{dataset:{saveName:first.id}}});assert(releaseList);
 node('saved-list').handlers.click({target:{dataset:{delete:racing.id}}});
 await node('saved-list').handlers.click({target:{dataset:{confirm:racing.id}}});await settle();
 releaseList();await settle();
 assert.equal(node('saved-count').textContent,'1 / 100');assert(!node('saved-list').innerHTML.includes(racing.id));
 for(let i=1;i<100;i++)records.push({...first,id:String(++next).padStart(32,'0'),name:'Book '+i});
 await node('queue-refresh').handlers.click();assert.equal(node('saved-count').textContent,'100 / 100');
 const beforeDelete=requests.length;
 node('saved-list').handlers.click({target:{dataset:{delete:first.id}}});
 assert(node('saved-list').innerHTML.includes('Delete this saved backtest?'));
 node('saved-list').handlers.click({target:{dataset:{keep:first.id}}});assert.equal(requests.length,beforeDelete);
 node('saved-list').handlers.click({target:{dataset:{delete:first.id}}});
 await node('saved-list').handlers.click({target:{dataset:{confirm:first.id}}});
 assert.equal(records.length,99);assert.equal(node('saved-count').textContent,'99 / 100');assert.equal(loaded.result.years[0].holdings[0].symbol,'SAVED','A deletion keeps the displayed result');
 // A heading sorts the Saved backtests rows by stored values. A second click reverses the order. A missing
 // CAGR stays last in both directions. Equal values show the newest saved first, then the lower id.
 records=[{...first,id:'a'.repeat(32),name:'Low',cagr:-.2,created_at:'2026-10-01T00:00:00Z'},{...first,id:'b'.repeat(32),name:'High',cagr:.5,created_at:'2026-10-03T00:00:00Z'},
  {...first,id:'c'.repeat(32),name:'Missing',cagr:null,created_at:'2026-10-02T00:00:00Z'},{...first,id:'d'.repeat(32),name:'Tie',cagr:.5,created_at:'2026-10-03T00:00:00Z'}];
 await node('queue-refresh').handlers.click();
 const order=()=>['Low','High','Missing','Tie'].map(name=>[node('saved-list').innerHTML.indexOf('>'+name+'<'),name]).sort((a,b)=>a[0]-b[0]).map(pair=>pair[1]).join(' ');
 const sort=key=>{node('saved-head').handlers.click({target:{dataset:{sort:key}}});return order();};
 assert.equal(order(),'High Tie Missing Low','Newest saved first');assert.equal(node('saved-sort-saved').textContent,'Saved ↓');
 assert.equal(sort('cagr'),'High Tie Low Missing');assert.equal(node('saved-sort-cagr').textContent,'CAGR ↓');assert.equal(node('saved-sort-saved').textContent,'Saved');
 assert.equal(sort('cagr'),'Low High Tie Missing');assert.equal(node('saved-sort-cagr').textContent,'CAGR ↑');
 assert.equal(sort('name'),'High Low Missing Tie');assert.equal(sort('name'),'Tie Missing Low High');
 assert.equal(sort('saved'),'High Tie Missing Low');assert.equal(sort('saved'),'Low Missing Tie High');
 node('saved-head').handlers.click({target:{dataset:{}}});assert.equal(order(),'Low Missing Tie High','A heading without a sort keeps the order');
 // Names sort with their numbers in number order.
 const numbered=records;records=['Ranks 1–10','Ranks 1–6','Ranks 1–20'].map((name,index)=>({...first,id:String(index).repeat(32),name}));await node('queue-refresh').handlers.click();
 node('saved-head').handlers.click({target:{dataset:{sort:'name'}}});
 assert.deepEqual(records.map(record=>node('saved-list').innerHTML.indexOf('>'+record.name+'<')).map((at,index,all)=>all.filter(other=>other<at).length),[1,0,2]);
 records=numbered;node('saved-head').handlers.click({target:{dataset:{sort:'saved'}}});node('saved-head').handlers.click({target:{dataset:{sort:'saved'}}});await node('queue-refresh').handlers.click();
 // The focus returns to the control with the same id when the list is drawn again.
 let refocused=0;const tickId='saved-tick-'+'a'.repeat(32);node(tickId).focus=()=>refocused++;ctx.document.activeElement={id:tickId};
 await node('queue-refresh').handlers.click();assert(refocused>0);ctx.document.activeElement=undefined;
 // Read the advertised capacity, including an older server's smaller limit.
 const oldFetch=ctx.fetch;ctx.fetch=async(...args)=>{const response=await oldFetch(...args);return {...response,json:async()=>({...await response.json(),limit:4})}};
 await node('queue-refresh').handlers.click();assert.equal(node('saved-count').textContent,'4 / 4');ctx.fetch=oldFetch;
 // Queue notification during an active library operation must get its own
 // reconciliation after that operation; the older list omits the new record.
 holdNextList=true;const refreshing=node('queue-refresh').handlers.click();await settle();
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
 // The market switch shows the saved tests of one market; a record without a readable market shows under All only.
 // Lock ticked locks the ticked rows: a locked row says Locked and its Details has no Delete. The box in the
 // heading ticks every row shown. Delete ticked asks one time, then deletes the ticked rows that are not locked.
 // Unlock ticked unlocks them. Another market clears every tick.
 records=[['1','US one','us'],['2','HK one','hk'],['3','HK two','hk'],['4','Unreadable',null]].map(([digit,name,market])=>({...first,id:digit.repeat(32),name,market}));
 await node('queue-refresh').handlers.click();
 const markets=['','us','hk','jp'].map(market=>({dataset:{market},attributes:{},setAttribute(name,value){this.attributes[name]=value},querySelector(){return this.count||(this.count={textContent:''})}}));
 node('run-markets').querySelectorAll=()=>markets;call('RunMarkets.init()');
 const choose=market=>node('run-markets').handlers.click({target:{closest:()=>markets.find(button=>button.dataset.market===market)}});
 const shown=()=>records.filter(record=>node('saved-list').innerHTML.includes('>'+record.name+'<')).map(record=>record.name).sort();
 const bar=data=>node('saved-bar').handlers.click({target:{dataset:data}});
 assert.deepEqual(markets.map(button=>button.count.textContent),[4,1,2,0]);
 choose('hk');assert.deepEqual(shown(),['HK one','HK two']);assert.equal(markets[2].attributes['aria-pressed'],'true');
 const hkOne='2'.repeat(32),savedRow=id=>{const html=node('saved-list').innerHTML;return html.slice(html.indexOf('id="saved-tick-'+id),html.indexOf('</li>',html.indexOf('id="saved-tick-'+id)));};
 await node('saved-list').handlers.change({target:{dataset:{tick:hkOne},checked:true}});
 assert(node('saved-bar').innerHTML.includes('>Lock ticked<'));
 await bar({lockTicked:'true'});await settle();
 assert.equal(records.find(record=>record.id===hkOne).locked,true);assert.equal(node('saved-status').textContent,'Saved backtest locked.');
 assert(savedRow(hkOne).includes('>Locked<'));assert(!savedRow(hkOne).includes('data-delete='));assert(savedRow('3'.repeat(32)).includes('data-delete='));
 assert(node('saved-bar').innerHTML.includes('>Unlock ticked<'));assert(node('saved-bar').innerHTML.includes('data-delete-ticked disabled'),'Every ticked row is locked');
 const reads=requests.length;
 await node('saved-tick-all').handlers.change({target:{checked:true}});
 assert.equal(node('saved-tick-all').checked,true);assert.equal(node('saved-list').innerHTML.split(' checked').length-1,2);
 assert(node('saved-bar').innerHTML.includes('2 tests ticked'));assert(node('saved-bar').innerHTML.includes('>Lock ticked<'));assert.equal(requests.length,reads,'A tick reads nothing');
 bar({deleteTicked:''});assert(node('saved-bar').innerHTML.includes('Delete 1 saved backtest? Locked tests stay.'));
 bar({keepTicked:''});assert(!node('saved-bar').innerHTML.includes('Delete 1 saved backtest?'));assert.equal(requests.length,reads);
 bar({deleteTicked:''});await bar({confirmTicked:''});await settle();
 assert.deepEqual(requests.slice(reads).filter(request=>request.method==='DELETE').map(request=>request.url[15]),['3']);
 assert.deepEqual(records.map(record=>record.name),['US one','HK one','Unreadable']);assert(node('saved-status').textContent.startsWith('Saved backtest deleted.'));
 await bar({lockTicked:'false'});await settle();assert.equal(records.find(record=>record.id===hkOne).locked,false);assert.equal(node('saved-status').textContent,'Saved backtest unlocked.');
 bar({deleteTicked:''});await bar({confirmTicked:''});await settle();
 assert.deepEqual(records.map(record=>record.name),['US one','Unreadable']);
 assert(node('saved-list').innerHTML.includes('No saved Hong Kong backtests.'));assert(node('saved-bar').hidden);
 choose('');assert.deepEqual(shown(),['US one','Unreadable']);
 await node('saved-list').handlers.change({target:{dataset:{tick:records[0].id},checked:true}});assert(!node('saved-bar').hidden);
 choose('us');assert.deepEqual(shown(),['US one']);assert(node('saved-bar').hidden);assert(!node('saved-list').innerHTML.includes(' checked'));
 console.log('Passed: no save request from the page, a queue-saved test listed after its notification, opening and Tune from stored records, heading sorts, focus kept by id, the advertised capacity, the market switch, ticking every row shown, Lock and Unlock ticked, Delete ticked that leaves locked rows, explicit deletion, acknowledged rename/delete despite refresh failure, stale-read exclusion and preserved displayed results.');
})().catch(error=>{console.error(error);process.exitCode=1});
