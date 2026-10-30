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
 if(method==='POST'){
  if(records.length===20){value={error:'All 20 saved slots are used.'};status=409;}
  else{const request=JSON.parse(options.body);value={id:String(++next).padStart(32,'0'),name:request.name,created_at:'2026-10-26T00:00:00Z',kind:request.snapshot.kind,start:request.snapshot.result.first,end:request.snapshot.result.end,cagr:request.snapshot.result.cagr,snapshot:request.snapshot};records.push(value);}
 }else if(method==='DELETE'){records=records.filter(r=>r.id!==id);value={deleted:true};}
 else value=id?records.find(r=>r.id===id):{limit:20,records:records.map(({snapshot,...metadata})=>metadata)};
 if(method==='POST'&&status<400){const {snapshot,...metadata}=value;value=metadata;}
 const packed=JSON.stringify(value);
 if(method==='GET'&&!id&&holdNextList){holdNextList=false;await new Promise(resolve=>releaseList=resolve);}
 return {ok:status<400,status,json:async()=>JSON.parse(packed)};
}});
ctx.ResultArtifacts={opening:()=>()=>true,release:()=>{}};
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/saved-backtests.js'),'utf8'),ctx);
const call=code=>vm.runInContext(code,ctx);ctx.snapshot=snapshot;ctx.result=result;
const settle=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 ctx.readArtifact=()=>view==='latest'?null:artifact;ctx.isRunning=()=>running;ctx.openRecord=value=>loaded=value;
 call('SavedBacktests.init({current:readArtifact,isRunning,open:openRecord})');await settle();
 assert.equal(node('saved-count').textContent,'0 / 20');assert(node('save-backtest').disabled);
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
 // A failed save preserves the current display and every existing record.
 fail=true;await node('save-backtest').handlers.click();fail=false;
 assert.equal(records.length,1);assert(node('saved-message').textContent.includes('disconnected'));
 // An acknowledged mutation stays successful even when reconciliation fails.
 failList=true;node('saved-name').value='Acknowledged save';
 const beforeAcknowledged=requests.filter(r=>r.method==='POST').length;
 await node('save-backtest').handlers.click();await settle();
 assert.equal(records.length,2);assert.equal(node('saved-count').textContent,'2 / 20');
 assert(node('saved-message').textContent.startsWith('Saved “Acknowledged save”'));
 assert(node('saved-message').textContent.includes('could not be refreshed'));assert.notEqual(node('saved-message').className,'backtest-failed');
 assert.equal(requests.filter(r=>r.method==='POST').length,beforeAcknowledged+1);
 const acknowledged=records[1];
 node('saved-list').handlers.click({target:{dataset:{delete:acknowledged.id}}});
 await node('saved-list').handlers.click({target:{dataset:{confirm:acknowledged.id}}});await settle();
 assert.equal(records.length,1);assert.equal(node('saved-count').textContent,'1 / 20');
 assert(node('saved-message').textContent.startsWith('Saved backtest deleted.'));assert(node('saved-message').textContent.includes('could not be refreshed'));
 failList=false;await node('refresh-backtests').handlers.click();assert.equal(node('saved-message').textContent,'Saved list refreshed.');
 // A delayed older list must not revive a record deleted by a newer action.
 holdNextList=true;node('saved-name').value='Race';await node('save-backtest').handlers.click();
 assert(releaseList);const racing=records[1];
 node('saved-list').handlers.click({target:{dataset:{delete:racing.id}}});
 await node('saved-list').handlers.click({target:{dataset:{confirm:racing.id}}});await settle();
 releaseList();await settle();
 assert.equal(node('saved-count').textContent,'1 / 20');assert(!node('saved-list').innerHTML.includes(racing.id));
 for(let i=1;i<20;i++)records.push({...first,id:String(++next).padStart(32,'0'),name:'Book '+i});
 await node('refresh-backtests').handlers.click();assert.equal(node('saved-count').textContent,'20 / 20');assert(node('save-backtest').disabled);
 await node('save-backtest').handlers.click();assert.equal(records.length,20);assert(node('saved-message').textContent.includes('20'));
 const beforeDelete=requests.length;
 node('saved-list').handlers.click({target:{dataset:{delete:first.id}}});
 assert(node('saved-list').innerHTML.includes('Delete this saved backtest?'));
 node('saved-list').handlers.click({target:{dataset:{keep:first.id}}});assert.equal(requests.length,beforeDelete);
 node('saved-list').handlers.click({target:{dataset:{delete:first.id}}});
 await node('saved-list').handlers.click({target:{dataset:{confirm:first.id}}});
 assert.equal(records.length,19);assert(!node('save-backtest').disabled);assert.equal(loaded.result.years[0].holdings[0].symbol,'SAVED');
 await node('save-backtest').handlers.click();assert.equal(records.length,20);
 view='latest';call('SavedBacktests.update()');assert(node('save-backtest').disabled);
 console.log('Passed: complete snapshot saving/opening, 20-record cap, explicit deletion, acknowledged save/delete despite refresh failure, stale-read exclusion and preserved displayed results.');
})().catch(error=>{console.error(error);process.exitCode=1});
