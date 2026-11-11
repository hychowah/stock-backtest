'use strict';
// The actual navigation owner keeps existing draft and queue nodes mounted.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const nodes=new Map();
const node=id=>{if(!nodes.has(id))nodes.set(id,{id,value:'',innerHTML:'',textContent:'',hidden:false,open:false,dataset:{},handlers:{},attributes:{},addEventListener(k,f){this.handlers[k]=f;},setAttribute(k,v){this.attributes[k]=v;},querySelectorAll:()=>[],append(child){child.parentNode=this;},showModal(){this.open=true;},close(){this.open=false;this.handlers.close?.();}});return nodes.get(id);};
const nav=['builder','runs','library','review'].map(name=>{const n=node('nav-'+name);n.dataset.workspace=name;return n;});
const tabs=['overview','selection','returns','settings'].map(name=>{const n=node('tab-'+name);n.dataset.review=name;return n;});
const queries=selector=>selector==='[data-workspace]'||selector.startsWith('#workspace-nav')?nav:selector==='[data-review]'?tabs:[];
// Review blocks list their tabs; a random- or fixed- name limits a block to that kind of result.
const panels=['overview','random-returns','fixed-overview returns','selection returns'].map(reviewPanel=>({dataset:{reviewPanel},hidden:false}));
node('workspace-review').querySelectorAll=()=>panels;const visible=()=>panels.filter(panel=>!panel.hidden).map(panel=>panel.dataset.reviewPanel);
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
// The headline of the original result shows under the title, for a fixed and a random-date result.
const headline=()=>node('workspace-headline').innerHTML.split('</div>').filter(Boolean).map(cell=>cell.replace(/<[^>]+>/g,' ').trim().replace(/\s+/g,' '));
assert.deepEqual(headline(),['Strategy CAGR 10.00%','SPY CAGR 5.00%','Difference vs SPY +5.00 pp','Growth of $1 $1.10']);
assert.deepEqual(visible(),['overview','fixed-overview returns']);run("Workspaces.reviewSection('returns')");assert.deepEqual(visible(),['fixed-overview returns','selection returns']);
// A recorded warning stays above the tabs. Other notes, and how the result was opened, wait in the notes disclosure.
context.noted=artifacts.create({mode:'custom',start:'2015-01-02',end:'2016-01-04',months:12,rank_to:50},{cagr:.1,spy_cagr:.05,growth:1.1,start:'2015-01-02',end:'2016-01-04'},{metrics:{},filters:{}},{notice:{text:'Recorded note',severity:'info'},coverage:'Recorded coverage'});
run("Workspaces.published(ResultArtifacts.publish(noted),'Recorded test','Opened without a calculation.')");
assert.equal(node('workspace-recorded-notice').hidden,true);assert.equal(node('workspace-recorded-info').textContent,'Recorded note');assert.equal(node('workspace-opened-note').textContent,'Opened without a calculation.');
assert.equal(node('workspace-recorded-coverage').textContent,'Recorded coverage');assert.equal(node('workspace-recorded-context').hidden,false);
context.warned=artifacts.create({mode:'custom',start:'2015-01-02',end:'2016-01-04',months:12,rank_to:50},{cagr:.1,spy_cagr:.05,growth:1.1,start:'2015-01-02',end:'2016-01-04'},{metrics:{},filters:{}},{notice:{text:'Recorded warning',severity:'warning'}});
run("Workspaces.published(ResultArtifacts.publish(warned),'Recorded test')");
assert.equal(node('workspace-recorded-notice').textContent,'Recorded warning');assert.equal(node('workspace-recorded-notice').hidden,false);assert.equal(node('workspace-recorded-info').textContent,'');assert.equal(node('workspace-opened-note').textContent,'');
const statistics={mean:.15,min:-.02,max:.31};
context.random=artifacts.create({mode:'random',start:'2015-01-02',end:'2016-01-04',months:12,rank_to:50,trials:3},{completed:3,valid:3,incomplete:0,beat_spy:2,configuration:{seed:9,window_start:'2015-01-02',window_end:'2016-01-04'},distributions:{cagr:statistics,spy_cagr:{mean:.2},excess_cagr:{mean:-.05}}},{metrics:{},filters:{}},{});
run("Workspaces.published(ResultArtifacts.publish(random),'Random test')");
assert.deepEqual(headline(),['Mean strategy CAGR 15.00%','Mean SPY CAGR 20.00%','Mean difference vs SPY -5.00 pp','Trials beating SPY 2/3','Worst trial CAGR -2.00%','Best trial CAGR 31.00%']);
assert.equal(node('workspace-recorded-context').hidden,true,'No recorded note leaves no empty disclosure');
assert.deepEqual(visible(),['overview']);run("Workspaces.reviewSection('returns')");assert.deepEqual(visible(),['random-returns','fixed-overview returns','selection returns']);
run("Workspaces.published(ResultArtifacts.publish(input),'Recorded test')");
node('workspace-edit-copy').handlers.click();assert.equal(copied.kind,'custom');assert.equal(node('rank-to').value,'25');
run("Workspaces.runStatus({detail:'Preparing original books',elapsed:'0:02'})");assert(node('workspace-run-detail').textContent.includes('Preparing original books'));
assert.equal(form.innerHTML,'Mounted draft');
console.log('Passed: mounted draft/queue lifetimes, original recorded settings, the result headline, kind-specific review blocks, recorded notes, explicit copy, and independent background-status updates.');
