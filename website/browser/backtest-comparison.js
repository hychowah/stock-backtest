/* Read-only descriptions of stored tests. No transport, DOM, holdings traversal,
   calculation or artifact publication belongs here. Defaults describe documented
   omission semantics; explicit values and unfamiliar settings remain visible. */
const BacktestComparison=(()=>{
  const calendar=typeof CalendarSettings!=='undefined'?CalendarSettings:typeof require==='function'?require('./calendar-settings.js'):null;
  const own=(value,key)=>Object.prototype.hasOwnProperty.call(value,key);
  const stable=value=>value===undefined?'[not recorded]':JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.entries(item).sort(([a],[b])=>a.localeCompare(b))):item);
  const text=value=>value===undefined?'Not recorded':value===null?'None':typeof value==='object'?stable(value):String(value);
  const percent=value=>Number.isFinite(value)?(value*100).toFixed(2)+'%':'Unavailable';
  const labels={january:'January',custom:'Fixed dates',random:'Random dates'};
  const defaults={rank_from:1,rank_to:50,pool:'legacy',metric:'ev_ebitda',selection_order:'filter_first',min_cap:100e6,max_cap:null,min_ev:50e6,min_yield:0,max_multiple:null,sector:null,exchange:null};
  const names={rank_from:'First rank',rank_to:'Last rank',pool:'Stock pool',metric:'Ranking metric',selection_order:'Selection order',min_cap:'Minimum market cap (USD)',max_cap:'Maximum market cap (USD)',min_ev:'Minimum EV (USD)',min_yield:'Minimum yield',max_multiple:'Maximum multiple',sector:'Sector',exchange:'Exchange'};
  const entry=(key,label,value,display=text(value))=>({key,label,value,display});
  const catalogLabel=(catalog,id)=>typeof catalog?.[id]==='string'?catalog[id]:catalog?.[id]?.label||id;
  function filters(value){
    // All conditions are AND: order and repeated identical conditions do not
    // change meaning. Keep strict operators and exact recorded numeric values.
    return [...new Map((value||[]).map(condition=>[stable(condition),condition])).entries()].sort(([a],[b])=>a.localeCompare(b)).map(([,condition])=>condition);
  }
  function scalarRows(capture){
    const s=capture.selection,labels=new Map((capture.variables?.presentation||[]).map(item=>[item.variable_id+'@'+item.revision,item.name]));
    const source=value=>value.kind==='builtin'?(capture.builtins.find(item=>item.id===value.id)?.label||value.id)+' ('+value.id+')':(labels.get(value.variable_id+'@'+value.revision)||value.variable_id)+' @ '+value.revision;
    return [entry('strategy','Captured ranking',s.ranking,source(s.ranking.source)),entry('direction','Ranking direction',s.ranking.direction),entry('rank_from','First rank',s.rank_from),entry('rank_to','Last rank',s.rank_to),entry('selection_order','Selection order',s.selection_order),entry('pool','Stock pool',capture.pool),...Object.entries(capture.bounds).map(([key,value])=>entry('bound.'+key,names[key]||key,value)),...s.conditions.map((condition,index)=>entry('condition.'+index,'Variable condition '+(index+1),condition,source(condition.source)+' '+(condition.op==='lt'?'<':'>')+' '+condition.submitted_threshold.value+' '+condition.submitted_threshold.unit+' (canonical '+condition.threshold.value+' '+condition.threshold.unit+')'))];
  }
  function describe(artifact){
    if(!artifact||![1,2,3,4].includes(artifact.version)||!labels[artifact.kind]||!artifact.settings||!artifact.result)throw Error('This saved test cannot be compared. Its record was kept.');
    const kind=artifact.kind,s=artifact.settings,r=artifact.result,catalog=artifact.catalog||{},parameters=[],performance=[],handled=new Set(['mode']);
    const add=(key,label,value,display)=>parameters.push(entry(key,label,value,display));
    add('mode','Test type',kind,labels[kind]);
    let requestedWindow;
    if(kind==='january'){
      for(const key of ['first','last']){handled.add(key);add(key,key==='first'?'First book year':'Last book year',s[key]);}
      requestedWindow={first:s.first,last:s.last};
    }else{
      const normalized=calendar.normalize({...s,mode:kind}),dates=normalized.calendar;
      for(const key of ['calendar','start','end','months'])handled.add(key);
      if(dates){
        add('start','Requested start',dates.start);add('end','Requested end',dates.end);
        add('interval','Rebalance interval',dates.interval,dates.interval.count+' '+dates.interval.unit+'(s)');
        requestedWindow={start:dates.start,end:dates.end};
      }else requestedWindow={};
      handled.add('engine');const engine=own(s,'engine')?s.engine:'original';
      add('engine','Requested engine',engine,engine==='original'?'Original':engine==='experimental'?'New engine — experimental':text(engine));
    }
    if(s.strategy){
      handled.add('strategy');const c=s.strategy;
      parameters.push(...scalarRows(c));
    }
    for(const [key,fallback] of Object.entries(s.strategy?{}:defaults)){
      handled.add(key);const value=own(s,key)?s[key]:fallback;
      let display=text(value);
      if(key==='metric')display=catalogLabel(catalog.metrics,value)+' ('+text(value)+')';
      if(key==='pool')display=value==='legacy'?'Original candidate set':value==='cached'?'All cached stocks':text(value);
      if(key==='selection_order')display=value==='filter_first'?'Filter before ranking':value==='rank_first'?'Select ranks before filtering':text(value);
      if(key==='min_yield')display=Number.isFinite(value)?text(value*100)+'%':text(value);
      if(value===null&&['max_cap','max_multiple'].includes(key))display='No limit';
      if(value===null&&['sector','exchange'].includes(key))display='All';
      add(key,names[key],value,display);
    }
    handled.add('filters');const conditions=filters(s.filters);
    add('filters','Additional AND conditions',conditions,conditions.length?conditions.map(c=>catalogLabel(catalog.filters,c.field)+' '+(c.op==='lt'?'<':c.op==='gt'?'>':text(c.op))+' '+text(c.value)+(Object.keys(c).some(k=>!['field','op','value'].includes(k))?' '+stable(c):'')).join('; '):'None');
    if(kind==='random'){
      handled.add('trials');handled.add('seed');
      add('trials','Requested trials',own(s,'trials')?s.trials:24);
      add('seed_policy','Requested random date policy',s.seed==null?{fresh:true}:{seed:s.seed},s.seed==null?'Fresh dates each run':'Repeat date set '+text(s.seed));
      add('actual_seed','Recorded random date set',r.configuration?.seed);
    }
    for(const key of Object.keys(s).filter(key=>!handled.has(key)).sort())add('setting.'+key,'Setting: '+key,s[key]);
    const producer=r.producer;
    let producerDisplay='Unidentified (not recorded)';
    if(producer){
      const engineNames={original:'Original',experimental:'New engine — experimental'};
      producerDisplay=text(producer.label||engineNames[producer.engine]||producer.engine);
      if(producer.engine&&producerDisplay!==engineNames[producer.engine])producerDisplay+=' ('+text(producer.engine)+')';
      const provenance=Object.keys(producer).filter(key=>!['label','engine'].includes(key)).sort().map(key=>key+': '+text(producer[key]));
      if(provenance.length)producerDisplay+=' · '+provenance.join('; ');
    }
    add('producer','Recorded producer',producer,producerDisplay);
    let observationWindow;
    if(kind==='random'){
      observationWindow={start:r.configuration?.window_start,end:r.configuration?.window_end};
      performance.push(entry('completed','Completed trials',r.completed),entry('valid','Trials with available performance',r.valid),entry('incomplete','Incomplete trials',r.incomplete));
      const statisticLabels={mean:'Mean',median:'Median',p10:'P10',p25:'P25',p75:'P75',p90:'P90',min:'Worst',max:'Best',stddev:'Std. dev.'};
      const measures={cagr:'strategy CAGR',spy_cagr:'paired SPY CAGR',excess_cagr:'CAGR difference vs SPY',total_return:'strategy total return',growth:'strategy growth'};
      // Read stored distributions directly. Missing statistics stay unavailable;
      // never derive means, percentiles or performance from trial holdings.
      const distributions=r.distributions||{};
      for(const measure of new Set(['cagr',...Object.keys(distributions)])){
        const statistics=distributions[measure]||{};
        for(const stat of new Set(['mean',...Object.keys(statistics).filter(k=>k!=='n')])){
          const value=statistics[stat],label=(statisticLabels[stat]||stat)+' trial '+(measures[measure]||measure);
          const display=!own(measures,measure)?text(value):measure==='growth'?Number.isFinite(value)?text(value)+'×':'Unavailable':measure==='excess_cagr'?Number.isFinite(value)?text(value*100)+' pp':'Unavailable':percent(value);
          performance.push(entry(measure+'.'+stat,label,value,display));
        }
      }
    }else{
      observationWindow={start:r.start??r.first,end:r.end};
      performance.push(entry('cagr','Strategy CAGR',r.cagr,percent(r.cagr)),entry('spy_cagr','SPY CAGR',r.spy_cagr,percent(r.spy_cagr)),entry('growth','Growth of $1',r.growth,Number.isFinite(r.growth)?text(r.growth)+'×':'Unavailable'));
    }
    add('observed_start','Recorded observation start',observationWindow.start);
    add('observed_end','Recorded observation end',observationWindow.end);
    return {kind,parameters,performance,requestedWindow,observationWindow,notices:kind==='random'?['Random results are trial distributions. Mean trial CAGR is not one portfolio return. Percentiles are not confidence intervals.']:[]};
  }
  // Inputs are compact descriptions, not stored artifacts. Values determine
  // differences; labels retain each record's original catalog wording.
  function compare(left,right){
    function align(a,b){
      const l=new Map(a.map(row=>[row.key,row])),r=new Map(b.map(row=>[row.key,row]));
      return [...new Set([...l.keys(),...r.keys()])].map(key=>({key,label:l.get(key)?.label||r.get(key).label,left:l.get(key)?.display??'Not recorded',right:r.get(key)?.display??'Not recorded',different:stable(l.get(key)?.value)!==stable(r.get(key)?.value)}));
    }
    const notices=[...new Set([...left.notices,...right.notices])];
    if(left.kind!==right.kind)notices.push('These tests use different test types. Their performance measures can differ.');
    if(stable(left.requestedWindow)!==stable(right.requestedWindow))notices.push('These tests use different requested date windows.');
    if(stable(left.observationWindow)!==stable(right.observationWindow))notices.push('These tests use different recorded observation windows.');
    return {parameters:align(left.parameters,right.parameters),performance:align(left.performance,right.performance),notices};
  }
  return {describe,compare,scalarRows};
})();
if(typeof module!=='undefined')module.exports=BacktestComparison;
