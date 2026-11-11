'use strict';
// The asset-curve charts over the real result reader: drawing, the readout, old results and late replies.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const nodes=new Map(),requests=[];
const node=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',innerHTML:'',hidden:false,attributes:{},setAttribute(k,v){this.attributes[k]=v;},getBoundingClientRect:()=>({left:0,width:1200})});return nodes.get(id);};
const days=['2015-01-02','2015-06-01','2016-01-04','2016-06-01','2017-01-03'];
const trial={available:true,days,strategy:[1,1.2,.9,1.5,2],spy:[1,1.05,1.1,1.2,1.3]};
const all={available:true,trials:2,days,median:[1,1.1,1,1.4,1.8],lowest:[1,.9,.8,1.2,1.5],highest:[1,1.3,1.2,1.6,2.1],spy:[1,1.05,1.1,1.2,1.3]};
let wait=null,answer=null;
const context=vm.createContext({console,AbortController,Uint8Array,crypto:require('node:crypto').webcrypto,document:{getElementById:node},
 fetch:async(url,options={})=>{
  if(options.method==='DELETE')return {ok:true,headers:{get:()=>null},json:async()=>({})};
  requests.push(url);
  const parts=url.split('/'),selection=parts[6];
  if(wait){const pause=wait;wait=null;await pause();}
  const value=answer??(selection==='all'?all:trial);
  return {ok:true,headers:{get:()=>null},json:async()=>structuredClone({...value,identity:parts[3]})};
 }});
for(const file of ['result-artifacts.js','asset-curve.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser',file),'utf8'),context);
const run=code=>vm.runInContext(code,context),tick=()=>new Promise(resolve=>setImmediate(resolve));
const artifact=(id,version=4)=>({version,kind:'random',settings:{mode:'random'},result:{trials:[{},{}],trial_results:[]},catalog:{metrics:{},filters:{}},
 ...(version>2?{evidence:{id:id.repeat(32),format_version:2,trials:2,periods:4,holdings:8}}:{})});
const publish=value=>{context.input=value;return run('ResultArtifacts.publish(input)');};
(async()=>{
 // One trial: two lines, a marker and a readout that rests on the last day.
 let open=publish(artifact('a'));context.open=open;
 await run('AssetCurve.trial(open,1)');
 assert.equal(node('curve-trial').hidden,false);
 assert.equal(requests.at(-1),'/api/backtest-runs/'+'a'.repeat(32)+'/reader/curve/1');
 const chart=node('curve-trial-chart');
 assert.equal((chart.innerHTML.match(/<path /g)||[]).length,2,'Strategy and SPY lines');
 assert(chart.innerHTML.includes('>$1.00<')&&chart.innerHTML.includes('>2016-01<'),'Money ticks and month labels for a short window');
 assert.equal(node('curve-trial-readout').textContent,'2017-01-03 · Strategy $2.00 · SPY $1.30');
 // The pointer reads the nearest day; leaving rests on the last day again.
 const x=t=>86+(Date.parse(t+'T00:00:00Z')-Date.parse(days[0]+'T00:00:00Z'))/(Date.parse(days[4]+'T00:00:00Z')-Date.parse(days[0]+'T00:00:00Z'))*1084;
 chart.onpointermove({clientX:x('2016-01-10')});
 assert.equal(node('curve-trial-readout').textContent,'2016-01-04 · Strategy $0.90 · SPY $1.10');
 assert.equal(node('curve-trial-marker').attributes.x1,x('2016-01-04'));
 chart.onpointerleave();assert(node('curve-trial-readout').textContent.startsWith('2017-01-03'));
 // The same trial is not read again; another trial is.
 const count=requests.length;await run('AssetCurve.trial(open,1)');assert.equal(requests.length,count);
 await run('AssetCurve.trial(open,2)');assert.equal(requests.length,count+1);
 // All trials: the median line, SPY and the band.
 await run('AssetCurve.all(open)');
 assert.equal(node('curve-all').hidden,false);
 assert.equal((node('curve-all-chart').innerHTML.match(/<path /g)||[]).length,3,'Band, median and SPY');
 assert.equal(node('curve-all-readout').textContent,'2017-01-03 · Median trial $1.80 (lowest $1.50, highest $2.10) · SPY $1.30');
 // A result saved before curves shows no chart.
 answer={available:false};open=publish(artifact('b'));context.open=open;
 run('AssetCurve.clear()');await run('AssetCurve.trial(open,1)');await run('AssetCurve.all(open)');
 assert.equal(node('curve-trial').hidden,true);assert.equal(node('curve-all').hidden,true);
 // An inline result has no curve route and makes no request.
 answer=null;const before=requests.length;open=publish(artifact('c',2));context.open=open;
 await run('AssetCurve.trial(open,1)');assert.equal(requests.length,before);assert.equal(node('curve-trial').hidden,true);
 // A late reply for a replaced result is not drawn.
 open=publish(artifact('d'));context.open=open;let resume;wait=()=>new Promise(resolve=>resume=resolve);
 const late=run('AssetCurve.trial(open,1)');await tick();
 publish(artifact('e'));resume();await late;
 assert.equal(node('curve-trial').hidden,true,'A replaced result draws nothing');
 // A failed read says why.
 open=publish(artifact('f'));context.open=open;wait=async()=>{throw Error('Could not read stored evidence.');};
 await run('AssetCurve.trial(open,1)');
 assert.equal(node('curve-trial').hidden,false);assert.equal(node('curve-trial-readout').textContent,'Could not read stored evidence.');
 console.log('Passed: trial and all-trial charts, pointer readout, no chart for old or inline results, late replies and failures.');
})().catch(error=>{console.error(error);process.exit(1);});
