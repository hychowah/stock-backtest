'use strict';
// The actual navigation owner keeps existing draft and queue nodes mounted.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const nodes=new Map();
const node=id=>{if(!nodes.has(id))nodes.set(id,{id,value:'',innerHTML:'',textContent:'',hidden:false,open:false,dataset:{},handlers:{},attributes:{},addEventListener(k,f){this.handlers[k]=f;},setAttribute(k,v){this.attributes[k]=v;},querySelectorAll:()=>[],append(child){child.parentNode=this;},prepend(child){child.parentNode=this;this.first=child;},showModal(){this.open=true;},close(){this.open=false;this.handlers.close?.();}});return nodes.get(id);};
const nav=['builder','runs','review'].map(name=>{const n=node('nav-'+name);n.dataset.workspace=name;return n;});
const tabs=['overview','selection','returns','settings'].map(name=>{const n=node('tab-'+name);n.dataset.review=name;return n;});
const queries=selector=>selector==='[data-workspace]'||selector.startsWith('#workspace-nav')?nav:selector==='[data-review]'?tabs:[];
// Review blocks list their tabs; a random- or fixed- name limits a block to that kind of result.
// The names come from the page markup. shows(id) tells if the block that holds that element is visible.
const template=fs.readFileSync(path.join(__dirname,'../website/browser/template.html'),'utf8');
const panels=[...new Set([...template.matchAll(/data-review-panel="([^"]+)"/g)].map(match=>match[1]))].map(reviewPanel=>({dataset:{reviewPanel},hidden:false}));
node('workspace-review').querySelectorAll=()=>panels;
const shows=id=>{const name=template.slice(0,template.indexOf('id="'+id+'"')).match(/.*data-review-panel="([^"]+)"/s)[1];return !panels.find(panel=>panel.dataset.reviewPanel===name).hidden;};
const blocks=()=>['robustness-chart','schedule-trial-missing','schedule-trial-title','schedule-chart','schedule-period-pages','schedule-stock-table','result-explorer'].filter(shows);
let copied=null,shown=null,tabsTop=120,contentStarts=0;const scrolls=[];
// The tab row of Result review and the content that follows it.
Object.assign(node('workspace-review-tabs'),{getBoundingClientRect:()=>({top:tabsTop}),nextElementSibling:{getClientRects:()=>[{}],scrollIntoView(){contentStarts++;}}});
const artifacts=require('../website/browser/result-artifacts.js');
const context=vm.createContext({console,scrollTo:(x,y)=>scrolls.push(y),document:{getElementById:node,querySelectorAll:queries},viewKey:()=> 'latest',ResultArtifacts:artifacts,
 BacktestComparison:require('../website/browser/backtest-comparison.js'),SectorView:{init(){},show:a=>shown=a,load(){}},ScheduleView:{show(){},inspectOriginal(){}},EvidenceResults:{show(){}},copySavedBacktestSettings:a=>copied=a});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/workspaces.js'),'utf8'),context);
const run=code=>vm.runInContext(code,context);
node('rank-to').value='25';node('filter-value').value='17';node('strategy-form').innerHTML='Mounted draft';
run('Workspaces.init()');
const form=node('strategy-form'),queue=node('queue-panel');
// A view change starts at the top of the page. Showing the same view again does not move the page.
for(const view of ['runs','review','builder'])run(`Workspaces.show('${view}')`);
assert.deepEqual(scrolls,[0,0,0]);run("Workspaces.show('builder')");assert.equal(scrolls.length,3);
// The tray borrows the queue panel and returns it to the top of Runs, above the Saved backtests rows.
node('workspace-queue-open').handlers.click();assert.equal(queue.parentNode,node('workspace-queue-content'));
node('workspace-queue-close').handlers.click();assert.equal(queue.parentNode,node('workspace-runs'));assert.equal(node('workspace-runs').first,queue);
context.queue={records:[{state:'running',name:'Existing run',progress:{completed:2,total:5}},{state:'held'}],paused:false,available:true};
// The status bar shows queue states only: idle, then the running test with its progress and the waiting count.
assert.equal(node('workspace-run-state').textContent,'Idle');
run('Workspaces.queueStatus(queue)');assert.equal(node('workspace-run-state').textContent,'Running · Existing run');assert(node('workspace-run-detail').textContent.includes('2 / 5'));assert(node('workspace-waiting').textContent.includes('1 waiting'));
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
// The colour of the difference follows its sign on screen: a shown 0.00 has no tone.
const tone=()=>node('workspace-headline').innerHTML.match(/data-tone="(\w+)"/)?.[1];assert.equal(tone(),'up');
const fixed=(result,presentation={})=>artifacts.create({mode:'custom',start:'2015-01-02',end:'2016-01-04',months:12,rank_to:50},{cagr:.1,spy_cagr:.05,growth:1.1,start:'2015-01-02',end:'2016-01-04',...result},{metrics:{},filters:{}},presentation);
const publish=(artifact,...rest)=>{context.next=artifact;context.rest=rest;run('Workspaces.published(ResultArtifacts.publish(next),...rest)');};
publish(fixed({cagr:.02}));assert.equal(tone(),'down');
publish(fixed({cagr:.1+.2,spy_cagr:.3}));assert.equal(headline()[2],'Difference vs SPY 0.00 pp');assert.equal(tone(),undefined);
// The fixed result shows its chart, its pager and Explore in Overview; Returns adds the stocks. The per-trial block stays hidden.
assert.deepEqual(blocks(),['robustness-chart','schedule-chart','schedule-period-pages','result-explorer']);
run("Workspaces.reviewSection('returns')");assert.deepEqual(blocks(),['schedule-chart','schedule-period-pages','schedule-stock-table','result-explorer']);
// A tab change moves the page only while the tab row is stuck at the top of the window: the start of the new content goes under the row.
assert.equal(contentStarts,0);tabsTop=0;run("Workspaces.reviewSection('overview')");assert.equal(contentStarts,1);tabsTop=120;run("Workspaces.reviewSection('returns')");assert.equal(contentStarts,1);
// The coverage line of a fixed result is a recorded note. It moves below the headline when a headline value is unavailable.
assert.equal(node('schedule-coverage').parentNode,node('workspace-recorded-context'));assert.equal(node('workspace-recorded-context').hidden,false);
publish(fixed({cagr:null,growth:null}));assert.equal(headline()[0],'Strategy CAGR Unavailable');
assert.equal(node('schedule-coverage').parentNode,node('workspace-headline-note'));assert.equal(node('workspace-recorded-context').hidden,true);
// A recorded warning stays above the tabs. Other notes, and how the result was opened, wait in the notes disclosure.
publish(fixed({},{notice:{text:'Recorded note',severity:'info'},coverage:'Recorded coverage'}),'Recorded test','Opened without a calculation.');
assert.equal(node('workspace-recorded-notice').hidden,true);assert.equal(node('workspace-recorded-info').textContent,'Recorded note');assert.equal(node('workspace-opened-note').textContent,'Opened without a calculation.');
assert.equal(node('workspace-recorded-coverage').textContent,'Recorded coverage');assert.equal(node('workspace-recorded-context').hidden,false);
publish(fixed({},{notice:{text:'Recorded warning',severity:'warning'}}),'Recorded test');
assert.equal(node('workspace-recorded-notice').textContent,'Recorded warning');assert.equal(node('workspace-recorded-notice').hidden,false);assert.equal(node('workspace-recorded-info').textContent,'');assert.equal(node('workspace-opened-note').textContent,'');
const statistics={mean:.15,min:-.02,max:.31};
const random=artifacts.create({mode:'random',start:'2015-01-02',end:'2016-01-04',months:12,rank_to:50,trials:3},{completed:3,valid:3,incomplete:0,beat_spy:2,configuration:{seed:9,window_start:'2015-01-02',window_end:'2016-01-04'},distributions:{cagr:statistics,spy_cagr:{mean:.2},excess_cagr:{mean:-.05}}},{metrics:{},filters:{}},{});
publish(random,'Random test');
assert.deepEqual(headline(),['Mean strategy CAGR 15.00%','Mean SPY CAGR 20.00%','Mean difference vs SPY -5.00 pp','Trials beating SPY 2/3','Worst trial CAGR -2.00%','Best trial CAGR 31.00%']);
// For random dates the coverage line describes the inspected trial and stays with it.
assert.equal(node('schedule-coverage').parentNode,node('schedule-trial'));
assert.equal(node('workspace-recorded-context').hidden,true,'No recorded note leaves no empty disclosure');
// A producer line inside the disclosure keeps the disclosure in view.
node('result-producer').textContent='Calculated by Original.';publish(random,'Random test');assert.equal(node('workspace-recorded-context').hidden,false);
node('result-producer').hidden=true;publish(random,'Random test');assert.equal(node('workspace-recorded-context').hidden,true);
Object.assign(node('result-producer'),{textContent:'',hidden:false});
// The random-date result shows its distribution in Overview; Returns shows one trial with its chart and stocks,
// or the note of a result that stored no trials.
assert.deepEqual(blocks(),['robustness-chart','result-explorer']);
run("Workspaces.reviewSection('returns')");assert.deepEqual(blocks(),['schedule-trial-missing','schedule-trial-title','schedule-chart','schedule-period-pages','schedule-stock-table','result-explorer']);
run("Workspaces.published(ResultArtifacts.publish(input),'Recorded test')");
node('workspace-edit-copy').handlers.click();assert.equal(copied.kind,'custom');assert.equal(node('rank-to').value,'25');
context.queue={records:[],paused:false,available:true};run('Workspaces.queueStatus(queue)');assert.equal(node('workspace-run-state').textContent,'Idle');assert.equal(node('workspace-run-detail').textContent,'No active backtest.');
assert.equal(form.innerHTML,'Mounted draft');
console.log('Passed: mounted draft/queue lifetimes, the queue panel returned to the top of Runs, queue-only status, original recorded settings, the result headline and its tone, the scroll reset of a view change and the tab change under a stuck tab row, kind-specific review blocks from the page markup, recorded notes, the coverage line and producer line, and explicit copy.');
