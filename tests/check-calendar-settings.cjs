'use strict';
const assert=require('assert'),Calendar=require('../website/browser/calendar-settings.js'),Artifacts=require('../website/browser/result-artifacts.js');
const old={mode:'custom',start:'2015-01-02',end:'2016-12-30',months:12,rank_to:3};
const canonical={mode:'custom',calendar:Calendar.decode(old),rank_to:3};
assert.deepEqual(Calendar.normalize(old),Calendar.normalize(canonical));
const week={...canonical,calendar:{...canonical.calendar,interval:{unit:'week',count:104}}};
assert.equal(Calendar.label(week),'every 104 week(s)');
assert.equal(Calendar.label({...week,start:'2015-01-05',end:'2016-12-30'}),'every 104 week(s)');
assert.notDeepEqual(Calendar.normalize(week),Calendar.normalize({...old,months:24}));
for(const version of [1,2]){
 const snapshot={version,kind:'custom',settings:old,result:{months:12},catalog:{metrics:{old:{label:'Original label'}},filters:{}},presentation:{},context:{pill:'Original period'}};
 const raw=JSON.stringify(snapshot),artifact=Artifacts.decode(snapshot);
 assert.equal(JSON.stringify(snapshot),raw);
 assert.equal(artifact.catalog.metrics.old.label,'Original label');
 const next=Artifacts.create(week,{calendar:week.calendar},snapshot.catalog,{});
 assert(Artifacts.matches(next,week));assert(!Artifacts.matches(next,old));
}
assert.throws(()=>Calendar.decode({...week,months:12}),/one calendar/);
assert.equal(Calendar.decode({start:old.start,end:old.end}).interval.count,12);
for(const value of [null,false,0]){
 assert.throws(()=>Calendar.decode({...old,calendar:value}));
 assert.throws(()=>Calendar.normalize({mode:'custom',calendar:value}));
}
assert.throws(()=>Calendar.decode({...old,months:null}));
for(const count of [null,0,105,1.5])assert.throws(()=>Calendar.decode({calendar:{...week.calendar,interval:{unit:'week',count}}}));
console.log('Passed: old v1/v2 snapshots, exact submitted settings, equivalent month comparisons, weekly labels and mixed request rejection.');
