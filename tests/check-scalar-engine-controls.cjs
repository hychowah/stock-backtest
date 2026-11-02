'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const nodes=new Map();
const node=id=>{if(!nodes.has(id))nodes.set(id,{id,value:'',checked:false,hidden:false,textContent:'',events:{},addEventListener(name,fn){this.events[name]=fn;}});return nodes.get(id);};
node('backtest-engine').value='original';
let current={mode:'latest',scalar:false};
let capabilities={calendar:null,engines:[
 {id:'original',calendar:1,status:{state:'current'},scalar:{operations:['latest','january','custom','random']}},
 {id:'experimental',calendar:1,status:{state:'current'},scalar:{operations:['latest','january','custom','random']}}
]};
const context=vm.createContext({module:{exports:{}},document:{getElementById:node},location:{protocol:'http:'},
 fetch:async()=>({ok:true,json:async()=>capabilities})});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/engine-controls.js'),'utf8'),context);
const engine=context.module.exports;
(async()=>{
 await engine.init(()=>current);
 assert(node('engine-controls').hidden);
 assert.equal(engine.selected(),'original');
 current={mode:'latest',scalar:true};engine.sync();assert(!node('engine-controls').hidden);
 node('backtest-engine').value='experimental';node('backtest-engine').events.change();
 assert(node('engine-status').textContent.includes('current'));
 for(const mode of ['latest','january','custom','random']){
  current={mode,scalar:true};engine.sync();assert(!node('engine-controls').hidden);
  const captured=engine.fields({scalar:true});assert.equal(captured.engine,'experimental');
  node('backtest-engine').value='original';assert.equal(captured.engine,'experimental');
  node('backtest-engine').value='experimental';
 }
 current={mode:'january',scalar:false};engine.sync();assert(node('engine-controls').hidden);
 current={mode:'custom',scalar:false};engine.sync();assert(!node('engine-controls').hidden);
 capabilities={calendar:1};await engine.init();
 current={mode:'latest',scalar:true};engine.sync();
 assert.equal(engine.selected(),'experimental');
 assert.equal(engine.fields({scalar:true}).engine,'experimental');
 assert.deepEqual(Object.keys(engine.fields()),[]);
 console.log('Passed: one shared engine control, standalone views, all scalar modes and immutable retained choices when advice is unavailable.');
})().catch(error=>{console.error(error);process.exitCode=1;});
