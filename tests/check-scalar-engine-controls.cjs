'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const nodes=new Map();
const node=id=>{if(!nodes.has(id))nodes.set(id,{id,value:'',checked:false,hidden:false,textContent:'',events:{},addEventListener(name,fn){this.events[name]=fn;}});return nodes.get(id);};
node('backtest-engine').value='original';
let current={mode:'latest',scalar:false};
const capabilities={engines:[{id:'original',calendar:1}]};
const context=vm.createContext({module:{exports:{}},document:{getElementById:node},location:{protocol:'http:'},
 fetch:async()=>({ok:true,json:async()=>capabilities})});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/engine-controls.js'),'utf8'),context);
const engine=context.module.exports;
(async()=>{
 // Before the server answers, only Original runs and every submission names it.
 assert.equal(engine.runnable('original'),true);assert.equal(engine.runnable('experimental'),false);
 assert.deepEqual({...engine.fields()},{engine:'original'});
 await engine.init(()=>current);
 // A new draft runs Original and shows no engine choice in any mode.
 for(const intent of [{mode:'latest',scalar:false},{mode:'custom',scalar:false},{mode:'random',scalar:true}]){
  current=intent;engine.sync();assert(node('engine-controls').hidden);assert.equal(node('engine-status').textContent,'');
 }
 // A restored draft keeps its recorded engine; the choice appears so the user can pick Original.
 node('backtest-engine').value='experimental';node('backtest-engine').events.change();
 for(const mode of ['latest','january','custom','random']){
  current={mode,scalar:true};engine.sync();assert(!node('engine-controls').hidden);
  assert.match(node('engine-status').textContent,/New engine — experimental cannot run on this server\. Choose Original/);
  assert.equal(engine.fields().engine,'experimental');
 }
 current={mode:'january',scalar:false};engine.sync();assert(node('engine-controls').hidden);
 current={mode:'custom',scalar:false};engine.sync();assert(!node('engine-controls').hidden);
 node('backtest-engine').value='original';node('backtest-engine').events.change();
 assert(node('engine-controls').hidden);assert.equal(node('engine-status').textContent,'');
 assert.equal(engine.label('experimental'),'New engine — experimental');
 console.log('Passed: new drafts run Original without a choice; a restored engine this server does not run stays selected and shows the choice.');
})().catch(error=>{console.error(error);process.exitCode=1;});
