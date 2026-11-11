'use strict';
// Run the actual immutable artifact/reader and stored description owners.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const requests=[],releases=[];
const context=vm.createContext({console,Date,Uint8Array,AbortController,crypto:require('node:crypto').webcrypto,
 document:{createElement:()=>({click(){},set href(value){requests.push(value);}})},
 async fetch(url,options={}){
  if(options.method==='DELETE'){releases.push(url);return {ok:true,json:async()=>({released:true})};}
  return {ok:true,headers:{get:()=>null},json:async()=>({identity:'a'.repeat(32),rows:[{symbol:'A'}],cursor:0,next:null,total:1})};
 }});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/result-artifacts.js'),'utf8'),context);
const run=code=>vm.runInContext(code,context);
const capture={format:'strategy-capture',version:1,selection:{ranking:{source:{kind:'formula',variable_id:'draft:a',revision:'sha256:'+'a'.repeat(64)},direction:'lowest'},rank_from:1,rank_to:5,selection_order:'rank_first',conditions:[]},variables:{presentation:[{name:'Original submitted margin'}]},pool:'cached'};
const artifact={version:4,kind:'custom',settings:{mode:'custom',strategy:capture},result:{cagr:.1},catalog:{metrics:{},filters:{}},presentation:{kind:'scalar'},evidence:{id:'a'.repeat(32),format_version:2,trials:1,periods:1,holdings:1}};
context.artifact=artifact;
(async()=>{
 assert.equal(run('ResultArtifacts.scalarValue({ranking_value:.08,ranking_display:"percent"})'),'8%');
 // Evidence views keep 8 digits.
 assert.equal(run('ResultArtifacts.scalarValue({ranking_value:.33233461,ranking_display:"percent"})'),'33.233461%');
 const decoded=run('ResultArtifacts.decode(artifact)');assert.equal(decoded.version,4);assert(Object.isFrozen(decoded.settings.strategy));
 run('ResultArtifacts.publish(artifact)');assert.equal(run('ResultArtifacts.forView("custom").settings.strategy.selection.ranking.direction'),'lowest');
 const api=run('ResultArtifacts.reader(ResultArtifacts.forView("custom"))');
 assert.equal((await api.scopes()).rows[0].symbol,'A');assert.equal((await api.explanations()).total,1);assert.equal((await api.screen()).total,1);
 api.download('evidence');assert(requests.some(url=>url.endsWith('/export/evidence/1')));
 const latest={...structuredClone(artifact),kind:'latest',settings:{mode:'latest',strategy:structuredClone(capture)},evidence:{...artifact.evidence,trials:0,periods:0}};
 context.latest=latest;assert.equal(run('ResultArtifacts.decode(latest).kind'),'latest');
 context.latest=structuredClone(latest);context.latest.evidence.trials=1;assert.throws(()=>run('ResultArtifacts.decode(latest)'));
 for(const [version,format] of [[3,1],[4,2]]){
  context.record={...structuredClone(artifact),version,evidence:{...artifact.evidence,format_version:format}};
  assert.equal(run('ResultArtifacts.decode(record).version'),version);
  context.record=structuredClone(context.record);context.record.evidence.format_version=version===3?2:1;assert.throws(()=>run('ResultArtifacts.decode(record)'));
 }
 context.old={version:1,kind:'custom',settings:{mode:'custom'},result:{periods:[]},context:{}};
 assert.equal(run('ResultArtifacts.decode(old).version'),2);
 run('ResultArtifacts.release(ResultArtifacts.forView("custom"))');await new Promise(resolve=>setImmediate(resolve));assert.equal(releases.length,1);
 console.log('Scalar artifact4/codec2 immutable decoding, reader pages, downloads and old readers passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
