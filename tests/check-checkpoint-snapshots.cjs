/* Consume real Python-store fixtures after generation replacement and eviction.
   Exercise the existing artifact, inspection and CSV boundaries without a server. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
assert.equal(input.before.length,3);assert.equal(input.after.length,3);
assert.deepEqual(input.before.map(row=>row.snapshot.version),[1,2,2]);
const downloads=[];
function inspect(snapshot){
  const nodes=new Map(),stored=new Map();let csv='';
  const node=id=>{
    if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',value:'',hidden:true,checked:false,handlers:{},
      addEventListener(key,callback){this.handlers[key]=callback;}});
    return nodes.get(id);
  };
  const fail=()=>{throw Error('Reopening or exporting a saved snapshot must not calculate or request inputs.');};
  const context=vm.createContext({console,TextDecoder,fetch:fail,BacktestRuns:{create:fail,follow:fail,pending:fail},
    localStorage:{setItem:(key,value)=>stored.set(key,value),getItem:key=>stored.get(key)},
    document:{getElementById:node,createElement:()=>({click(){downloads.push({filename:this.download,csv});}})},
    Blob:class{constructor(parts){this.parts=parts;}},
    URL:{createObjectURL(blob){csv=blob.parts.join('');return 'blob:stored-snapshot';},revokeObjectURL(){}},
    money:value=>String(value),contributionPie:()=>'',completeResult:fail,restoreBacktestSettings:fail,
    currentCatalog:{metrics:{ev_ebitda:{label:'Replacement runtime metric'}}}});
  const execute=code=>vm.runInContext(code,context);
  for(const file of ['engine-controls.js','screener.js','calendar-settings.js','result-artifacts.js','contributions.js','robustness.js','schedule.js'])
    execute(fs.readFileSync(path.join(__dirname,'../website/browser',file),'utf8'));
  execute("const metricLabel=id=>ResultArtifacts.forView('custom').catalog.metrics[id].label;");
  context.snapshot=snapshot;
  const raw=JSON.stringify(snapshot),start=downloads.length;
  execute('ScheduleView.init(); const restored=ResultArtifacts.publish(snapshot); ScheduleView.show(restored);');
  const restored=execute("ResultArtifacts.forView('custom')");
  assert.equal(JSON.stringify(snapshot),raw,'Legacy decode cannot rewrite its original snapshot.');
  assert.equal(restored.version,2);
  assert.deepEqual(JSON.parse(JSON.stringify(restored.settings)),snapshot.settings);
  assert.deepEqual(JSON.parse(JSON.stringify(restored.result)),snapshot.result);
  assert.deepEqual(JSON.parse(JSON.stringify(restored.presentation)),input.presentation);
  assert.equal(restored.catalog.metrics.ev_ebitda.label,'Original saved metric');
  assert(execute("Object.isFrozen(ResultArtifacts.forView('custom').result.trial_results[0].periods[0].holdings)"));
  node('robustness-download').handlers.click();
  assert(downloads.at(-1).csv.includes('"'+snapshot.result.configuration.seed+'"'));
  for(let index=0;index<snapshot.result.completed;index++){
    node('robustness-trial').value=String(index);
    node('robustness-inspect').handlers.click();
    assert.equal(node('schedule-multiple-head').textContent,'Original saved metric (×)');
    const trial=snapshot.result.trial_results[index];
    assert.equal(node('schedule-dates').textContent,trial.start+' → '+trial.end+' · every '+trial.months+' month(s)');
    node('schedule-download-holdings').handlers.click();
    const holdingExport=downloads.at(-1);
    const holdings=trial.periods.flatMap(period=>period.holdings);
    assert.equal(holdingExport.csv.split('\r\n').length,holdings.length+1);
    for(const holding of holdings){
      assert(holdingExport.csv.includes('"'+holding.symbol+'"'));
      assert(holdingExport.csv.includes('"'+holding.status+'"'));
      assert(holdingExport.csv.includes('"'+String(holding.return_value)+'"'));
    }
    node('schedule-download-returns').handlers.click();
    assert.equal(downloads.at(-1).csv.split('\r\n').length,trial.periods.length+1);
  }
  return downloads.slice(start);
}
let exportCount=0;
for(let index=0;index<input.before.length;index++){
  const before=inspect(input.before[index].snapshot),after=inspect(input.after[index].snapshot);
  assert.deepEqual(after,before,'Existing CSV exporters must preserve all bytes after generation replacement and eviction.');
  exportCount+=after.length;
}
console.log(JSON.stringify({check:'durable-snapshot-generation-eviction',snapshots:3,
  formats:['library-v1','library-v2','completed-queue-v2'],trials:input.after.map(row=>row.snapshot.result.completed),
  unchanged_exports:exportCount,calculation_requests:0}));
