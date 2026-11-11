'use strict';
// The actual navigation owner keeps existing draft and queue nodes mounted.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const nodes=new Map();
const node=id=>{if(!nodes.has(id))nodes.set(id,{id,value:'',innerHTML:'',textContent:'',hidden:false,open:false,dataset:{},handlers:{},attributes:{},addEventListener(k,f){this.handlers[k]=f;},setAttribute(k,v){this.attributes[k]=v;},querySelectorAll:()=>[],append(child){child.parentNode=this;},showModal(){this.open=true;},close(){this.open=false;this.handlers.close?.();}});return nodes.get(id);};
const nav=['builder','runs','library','review'].map(name=>{const n=node('nav-'+name);n.dataset.workspace=name;return n;});
const tabs=['overview','selection','returns','settings'].map(name=>{const n=node('tab-'+name);n.dataset.review=name;return n;});
const queries=selector=>selector==='[data-workspace]'||selector.startsWith('#workspace-nav')?nav:selector==='[data-review]'?tabs:[];
let copied=null,shown=null;
const artifacts=require('../website/browser/result-artifacts.js');
const context=vm.createContext({console,document:{getElementById:node,querySelectorAll:queries},viewKey:()=> 'latest',ResultArtifacts:artifacts,
 BacktestComparison:require('../website/browser/backtest-comparison.js'),SectorView:{init(){},show:a=>shown=a,load(){}},ScheduleView:{show(){},cancel(){},inspectOriginal(){}},EvidenceResults:{show(){}},copySavedBacktestSettings:a=>copied=a});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/workspaces.js'),'utf8'),context);
const run=code=>vm.runInContext(code,context);
node('rank-to').value='25';node('filter-value').value='17';node('strategy-form').innerHTML='Mounted draft';
run('Workspaces.init()');
const form=node('strategy-form'),queue=node('queue-panel');
for(const view of ['runs','library','review','builder'])run(`Workspaces.show('${view}')`);
node('workspace-queue-open').handlers.click();assert.equal(queue.parentNode,node('workspace-queue-content'));
node('workspace-queue-close').handlers.click();assert.equal(queue.parentNode,node('workspace-runs'));
context.queue={records:[{state:'running',name:'Existing run',progress:{completed:2,total:5}},{state:'held'}],paused:false,available:true};
run('Workspaces.queueStatus(queue)');assert(node('workspace-run-detail').textContent.includes('2 / 5'));assert(node('workspace-waiting').textContent.includes('1 waiting'));
assert.equal(node('rank-to').value,'25');assert.equal(node('filter-value').value,'17');assert.equal(node('strategy-form'),form);assert.equal(form.innerHTML,'Mounted draft');
context.input=artifacts.create({mode:'custom',start:'2015-01-02',end:'2016-01-04',months:12,rank_to:50},{cagr:.1,spy_cagr:.05,growth:1.1,start:'2015-01-02',end:'2016-01-04'},{metrics:{},filters:{}},{});
run("Workspaces.published(ResultArtifacts.publish(input),'Recorded test')");
assert.equal(shown.kind,'custom');assert.equal(node('workspace-review').hidden,false);assert(node('workspace-parameters').innerHTML.includes('Last rank</dt><dd>50'));
// The settings list reads plain wording; the exact recorded text waits in a closed disclosure.
const [plainSettings,exactSettings]=node('workspace-parameters').innerHTML.split('<details><summary>Exact recorded values</summary>');
assert(plainSettings.includes('Minimum market cap (USD)</dt><dd>$100M</dd>')&&!plainSettings.includes('100000000'));assert(exactSettings.includes('Minimum market cap (USD)</dt><dd>100000000</dd>')&&!exactSettings.includes('Last rank'));
assert.equal(node('rank-to').value,'25');assert.equal(node('workspace-result-title').textContent,'Recorded test');
node('workspace-edit-copy').handlers.click();assert.equal(copied.kind,'custom');assert.equal(node('rank-to').value,'25');
run("Workspaces.runStatus({detail:'Preparing original books',elapsed:'0:02'})");assert(node('workspace-run-detail').textContent.includes('Preparing original books'));
assert.equal(form.innerHTML,'Mounted draft');
console.log('Passed: mounted draft/queue lifetimes, original recorded settings, explicit copy, and independent background-status updates.');
