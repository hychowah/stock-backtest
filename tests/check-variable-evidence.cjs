'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const context=vm.createContext({console,ResultArtifacts:require('../website/browser/result-artifacts.js')});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../website/browser/variable-evidence.js'),'utf8'),context);
const exact={variable_id:'variable:margin',revision:'sha256:'+'a'.repeat(64)};
function block(symbol,valid=true){return {requests:[{symbol,date:'2015-01-02'}],program:{nodes:[{id:'n0',unit:'scalar',stat:'mean'}]},
 observations:{contexts:[{id:'c0',date:'2015-01-02'}],roots:[{root:'c0',symbol,date:'2015-01-02',admitted:valid,reason:valid?null:'NO_ELIGIBLE_REPORT'}],results:[{id:'o0',parameter:'annual.operating_margin',context:'c0',unit:'scalar',reason:valid?null:'ROOT_NOT_ADMITTED',members:valid?[{value:.1,valid:true,fiscal_date:'2014-06-30',evidence:{known_date:'2014-09-28'}}]:[]}]},
 operations:[{id:'t0',node:'n0',context:'c0',observation:'o0',operation:'parameter',path:'/expression',operands:[],inputs:valid?[.1]:[],value:valid?.1:null,valid,reason:valid?null:'ROOT_NOT_ADMITTED'}],
 results:[{...exact,request:0,root:'c0',unit:'scalar',display:'percent',evidence:{operation:'t0'},value:valid?.1:null,valid,reason:valid?null:'ROOT_NOT_ADMITTED'}]};}
context.response={requested:[{},{}],evaluations:[block('A0000'),block('UNKNOWN',false)]};
let html=vm.runInContext('VariableEvidence.preview(response)',context);
assert(html.includes('1 of 2 requested samples available'));assert(html.includes('10%'));assert(html.includes('No eligible annual report'));assert(html.includes('2014-06-30'));assert(html.includes('2014-09-28'));assert(html.includes('Read parameter'));assert(html.includes('<summary>Advanced'));
context.strategy={variables:{presentation:[{...exact,name:'Original margin <label>'}]},builtins:[]};
context.records=[{scope:'scope1',chunk:0,block:block('UNRELATED')},{scope:'scope1',chunk:1,block:block('A0000')}];
context.row={symbol:'A0000',scalar_evidence:{scope:'scope1',lanes:{ranking:{scope:'scope1',chunk:1,request:0,...exact,evidence:{operation:'t0'}}}}};
html=vm.runInContext('VariableEvidence.records(records,row,strategy)',context);
const primary=html.slice(0,html.indexOf('<summary>Advanced'));
assert(primary.includes('Original margin &lt;label&gt;'));assert(primary.includes('A0000'));assert(!primary.includes('UNRELATED'));assert(primary.includes('10%'));assert(primary.includes('2014-09-28'));
// Equal operation IDs in another scope/chunk cannot supply a selected trace.
context.records[1].scope='scope2';html=vm.runInContext('VariableEvidence.records(records,row,strategy)',context);assert(html.includes('no matching calculation block'));
context.strategy.builtins=[{id:'filter:pe',label:'Submitted P/E',display:'multiple'}];context.row.scalar_evidence.lanes={ranking:{source:{kind:'builtin',id:'filter:pe'},canonical:12,stored:12,unit:'scalar',valid:true}};
html=vm.runInContext('VariableEvidence.records(records,row,strategy)',context);assert(html.includes('Submitted P/E'));assert(html.includes('12×'));assert(html.includes('original stored value 12'));
context.row.scalar_evidence.lanes={ranking:{scope:'scope1',...exact,value:.25,valid:true,reason:null,unit:'scalar',display:'percent'},c0:{scope:'scope1',...exact,value:null,valid:false,reason:'ZERO_DENOMINATOR',unit:'scalar',display:'percent'}};
html=vm.runInContext('VariableEvidence.records(records,row,strategy)',context);assert(html.includes('25%'));assert(html.includes('ZERO_DENOMINATOR'));assert(html.includes('random-date results keep values, not step traces'));
console.log('Passed: readable detached preview counts/values/reasons/fiscal/known dates, recorded operations, exact scope/chunk/request trace selection, original built-in labels and optional complete JSON.');
