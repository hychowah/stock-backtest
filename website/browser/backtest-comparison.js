/* Read-only descriptions of stored tests. No transport, DOM, holdings traversal,
   calculation or artifact publication belongs here. Defaults describe documented
   omission semantics; explicit values and unfamiliar settings remain visible.
   A row's display is plain wording for summaries. Its exact field keeps the
   recorded ids, units and canonical values when the plain wording leaves them out.
   The headline is the short answer of one result: the same first three keys for
   every test type, read from stored summary fields only. */
const BacktestComparison=(()=>{
  const calendar=typeof CalendarSettings!=='undefined'?CalendarSettings:typeof require==='function'?require('./calendar-settings.js'):null;
  const own=(value,key)=>Object.prototype.hasOwnProperty.call(value,key);
  const stable=value=>value===undefined?'[not recorded]':JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.entries(item).sort(([a],[b])=>a.localeCompare(b))):item);
  const text=value=>value===undefined?'Not recorded':value===null?'None':typeof value==='object'?stable(value):String(value);
  // On-screen numbers: 2 decimals; below 0.01, 2 significant digits; below 0.000001, 0.00.
  // ResultArtifacts.scalarValue applies the same rule to table values.
  const rounded=value=>{const size=Math.abs(value);return size<1e-6?'0.00':size<.01?value.toPrecision(2):value.toFixed(2);};
  const percent=value=>Number.isFinite(value)?rounded(value*100)+'%':'Unavailable';
  // A difference from SPY in percentage points. The sign follows the rounded
  // number on screen: a gain shows a plus sign, and a shown 0.00 shows none.
  const points=value=>{
    if(!Number.isFinite(value))return 'Unavailable';
    const shown=rounded(value*100);return (value>0&&+shown?'+':'')+shown+' pp';
  };
  const labels={january:'January',custom:'Fixed dates',random:'Random dates'};
  const defaults={rank_from:1,rank_to:50,pool:'legacy',metric:'ev_ebitda',selection_order:'filter_first',min_cap:100e6,max_cap:null,min_ev:50e6,min_yield:0,max_multiple:null,sector:null,exchange:null};
  const names={rank_from:'First rank',rank_to:'Last rank',pool:'Stock pool',metric:'Ranking metric',selection_order:'Selection order',min_cap:'Minimum market cap (USD)',max_cap:'Maximum market cap (USD)',min_ev:'Minimum EV (USD)',min_yield:'Minimum yield',max_multiple:'Maximum multiple',sector:'Sector',exchange:'Exchange'};
  const entry=(key,label,value,display=text(value),exact=display)=>exact===display?{key,label,value,display}:{key,label,value,display,exact};
  // A recorded fact is what the run stored, not what the user requested: fresh random dates differ on every run.
  const fact=(...row)=>({...entry(...row),recorded:true});
  const catalogLabel=(catalog,id)=>typeof catalog?.[id]==='string'?catalog[id]:catalog?.[id]?.label||id;
  function filters(value){
    // All conditions are AND: order and repeated identical conditions do not
    // change meaning. Keep strict operators and exact recorded numeric values.
    return [...new Map((value||[]).map(condition=>[stable(condition),condition])).entries()].sort(([a],[b])=>a.localeCompare(b)).map(([,condition])=>condition);
  }
  const symbols={lt:'<',gt:'>',le:'≤',ge:'≥',eq:'='};
  // Recorded final Rank: a chain's last Rank, else the capture/1 or flat range.
  function finalRank(options){
    const capture=options?.strategy;
    if(capture?.version===2)return capture.steps.findLast(step=>step.kind==='rank');
    const rank=capture?{...capture.selection.ranking,rank_from:capture.selection.rank_from,rank_to:capture.selection.rank_to}:{rank_from:options?.rank_from,rank_to:options?.rank_to};
    return {...rank,rank_from:rank.rank_from??1,rank_to:rank.rank_to??50};
  }
  // A recorded source name from the capture itself, never a current catalog.
  // The plain name leaves out the unit, id or revision that the exact name keeps.
  function plainName(capture,value){
    if(value.kind==='field')return {market_cap:'Market cap',enterprise_value:'Enterprise value',sector:'Sector',exchange:'Exchange'}[value.field]||value.field;
    if(value.kind==='builtin')return capture.builtins.find(item=>item.id===value.id)?.label||value.id;
    return capture.variables?.presentation.find(item=>item.variable_id===value.variable_id&&item.revision===value.revision)?.name||value.variable_id;
  }
  function exactName(capture,value){
    const name=plainName(capture,value);
    return value.kind==='field'?name+(['market_cap','enterprise_value'].includes(value.field)?' (USD)':''):value.kind==='builtin'?name+' ('+value.id+')':name+' @ '+value.revision;
  }
  const dollars=(value,suffix='')=>String(value).replace(/^[+-]?/,sign=>sign+'$')+suffix;
  // A submitted threshold as typed, with its unit in plain form: $100M, 2%, 8×.
  const quantity=({value,unit})=>unit==='usd_million'?dollars(value,'M'):unit==='usd'?dollars(value):unit==='usd_per_share'?dollars(value,' per share'):value+({percent:'%',percentage_points:' pp',multiple:'×',shares:' shares',number:'',scalar:''}[unit]??' '+unit);
  // A pool, flat setting or capture/1 bound: its plain display, then its exact text when that differs.
  function setting(key,value){
    if(key==='pool')return [value==='cached'?'All stocks with cached prices':value==='legacy'?'Original candidate set':text(value),text(value)];
    if(['min_cap','max_cap','min_ev'].includes(key)&&Number.isFinite(value))return [value&&value%1e6===0?dollars(value/1e6,'M'):dollars(value.toLocaleString('en-US')),text(value)];
    if(key==='min_yield'&&Number.isFinite(value))return [Number((value*100).toPrecision(12))+'%'];
    if(key==='selection_order')return [value==='filter_first'?'Filter before ranking':value==='rank_first'?'Select ranks before filtering':text(value)];
    if(value===null&&['max_cap','max_multiple'].includes(key))return ['No limit'];
    if(value===null&&['sector','exchange'].includes(key))return ['All'];
    return [text(value)];
  }
  function scalarRows(capture){
    const plain=value=>plainName(capture,value),exact=value=>exactName(capture,value);
    const condition=item=>{
      const op=' '+symbols[item.op]+' ',submitted=item.submitted_threshold;
      return typeof item.threshold==='string'?[plain(item.source)+op+item.threshold,exact(item.source)+op+item.threshold]
        :[plain(item.source)+op+quantity(submitted),exact(item.source)+op+submitted.value+' '+submitted.unit+' (canonical '+item.threshold.value+' '+item.threshold.unit+')'];
    };
    if(capture.version===2)return [entry('pool','Stock pool',capture.universe.pool,...setting('pool',capture.universe.pool)),...capture.steps.map((step,index)=>{
      const range=step.direction+' first · ranks '+step.rank_from+'–'+step.rank_to;
      return entry('step.'+index,'Step '+(index+1)+' · '+(step.kind==='rank'?'Rank':'Filter'),step,...(step.kind==='rank'?[plain(step.source)+' · '+range,exact(step.source)+' '+range]:condition(step)));
    })];
    const s=capture.selection;
    return [entry('strategy','Captured ranking',s.ranking,plain(s.ranking.source),exact(s.ranking.source)),entry('direction','Ranking direction',s.ranking.direction),entry('rank_from','First rank',s.rank_from),entry('rank_to','Last rank',s.rank_to),entry('selection_order','Selection order',s.selection_order),entry('pool','Stock pool',capture.pool,...setting('pool',capture.pool)),...Object.entries(capture.bounds).map(([key,value])=>entry('bound.'+key,names[key]||key,value,...setting(key,value))),...s.conditions.map((item,index)=>entry('condition.'+index,'Variable condition '+(index+1),item,...condition(item)))];
  }
  function describe(artifact){
    if(!artifact||![1,2,3,4].includes(artifact.version)||!labels[artifact.kind]||!artifact.settings||!artifact.result)throw Error('This saved test cannot be compared. Its record was kept.');
    const kind=artifact.kind,s=artifact.settings,r=artifact.result,catalog=artifact.catalog||{},parameters=[],performance=[],handled=new Set(['mode']);
    const add=(...row)=>parameters.push(entry(...row));
    add('mode','Test type',kind,labels[kind]);
    handled.add('market');const market=s.market??'us';
    add('market','Stock market',market,{us:'US',hk:'Hong Kong',jp:'Japan · Tokyo'}[market]||text(market));
    add('currency','Return currency','USD');
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
    }
    if(['custom','random'].includes(kind)||s.strategy){
      handled.add('engine');const engine=own(s,'engine')?s.engine:'original';
      add('engine','Requested engine',engine,engine==='original'?'Original':engine==='experimental'?'New engine — experimental':text(engine));
    }
    if(s.strategy){
      handled.add('strategy');const c=s.strategy;
      parameters.push(...scalarRows(c));
    }
    for(const [key,fallback] of Object.entries(s.strategy?{}:defaults)){
      handled.add(key);const value=own(s,key)?s[key]:fallback;
      if(key==='metric'){const label=catalogLabel(catalog.metrics,value);add(key,names[key],value,label,label+' ('+text(value)+')');continue;}
      add(key,names[key],value,...setting(key,value));
    }
    handled.add('filters');const conditions=filters(s.filters);
    add('filters','Additional AND conditions',conditions,conditions.length?conditions.map(c=>catalogLabel(catalog.filters,c.field)+' '+(c.op==='lt'?'<':c.op==='gt'?'>':text(c.op))+' '+text(c.value)+(Object.keys(c).some(k=>!['field','op','value'].includes(k))?' '+stable(c):'')).join('; '):'None');
    if(kind==='random'){
      handled.add('trials');handled.add('seed');
      add('trials','Requested trials',own(s,'trials')?s.trials:24);
      add('seed_policy','Requested random date policy',s.seed==null?{fresh:true}:{seed:s.seed},s.seed==null?'Fresh dates each run':'Repeat date set '+text(s.seed));
      parameters.push(fact('actual_seed','Recorded random date set',r.configuration?.seed));
    }
    for(const key of Object.keys(s).filter(key=>!handled.has(key)).sort())add('setting.'+key,'Setting: '+key,s[key]);
    let headline;
    if(kind==='random'){
      // Stored trial statistics and counts only; a missing one stays unavailable.
      // Only complete trials are counted, and the display says so when some are incomplete.
      const stat=(measure,name)=>r.distributions?.[measure]?.[name],counted=Number.isInteger(r.beat_spy)&&Number.isInteger(r.valid);
      headline=[entry('cagr','Mean strategy CAGR',stat('cagr','mean'),percent(stat('cagr','mean'))),entry('spy_cagr','Mean SPY CAGR',stat('spy_cagr','mean'),percent(stat('spy_cagr','mean'))),
        entry('difference','Mean difference vs SPY',stat('excess_cagr','mean'),points(stat('excess_cagr','mean'))),entry('beat_spy','Trials beating SPY',counted?r.beat_spy:undefined,counted?r.beat_spy+'/'+r.valid+(r.incomplete>0?' complete':''):'Unavailable'),
        entry('worst','Worst trial CAGR',stat('cagr','min'),percent(stat('cagr','min'))),entry('best','Best trial CAGR',stat('cagr','max'),percent(stat('cagr','max')))];
    }else{
      const difference=Number.isFinite(r.cagr)&&Number.isFinite(r.spy_cagr)?r.cagr-r.spy_cagr:undefined;
      headline=[entry('cagr','Strategy CAGR',r.cagr,percent(r.cagr)),entry('spy_cagr','SPY CAGR',r.spy_cagr,percent(r.spy_cagr)),entry('difference','Difference vs SPY',difference,points(difference)),
        entry('growth','Growth of $1',r.growth,Number.isFinite(r.growth)?'$'+rounded(r.growth):'Unavailable')];
    }
    const producer=r.producer;
    let producerDisplay='Unidentified (not recorded)';
    if(producer){
      const engineNames={original:'Original',experimental:'New engine — experimental'};
      producerDisplay=text(producer.label||engineNames[producer.engine]||producer.engine);
      if(producer.engine&&producerDisplay!==engineNames[producer.engine])producerDisplay+=' ('+text(producer.engine)+')';
      const provenance=Object.keys(producer).filter(key=>!['label','engine'].includes(key)).sort().map(key=>key+': '+text(producer[key]));
      if(provenance.length)producerDisplay+=' · '+provenance.join('; ');
    }
    parameters.push(fact('producer','Recorded producer',producer,producerDisplay));
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
          const display=!own(measures,measure)?text(value):measure==='growth'?Number.isFinite(value)?rounded(value)+'×':'Unavailable':measure==='excess_cagr'?Number.isFinite(value)?rounded(value*100)+' pp':'Unavailable':percent(value);
          performance.push(entry(measure+'.'+stat,label,value,display));
        }
      }
    }else{
      observationWindow={start:r.start??r.first,end:r.end};
      performance.push(entry('cagr','Strategy CAGR',r.cagr,percent(r.cagr)),entry('spy_cagr','SPY CAGR',r.spy_cagr,percent(r.spy_cagr)),entry('growth','Growth of $1',r.growth,Number.isFinite(r.growth)?rounded(r.growth)+'×':'Unavailable'));
    }
    parameters.push(fact('observed_start','Recorded observation start',observationWindow.start),fact('observed_end','Recorded observation end',observationWindow.end));
    // A quiet row holds only its documented default or no bound: the Original engine, filtering before
    // ranking, no extra condition, fresh random dates, no limit, a zero minimum. A short list of settings
    // leaves these rows to the full list.
    for(const row of parameters)if(row.key==='engine'&&row.value==='original'||row.key==='selection_order'&&row.value==='filter_first'||row.key==='filters'&&!row.value.length||row.key==='seed_policy'&&row.value.fresh||/^(bound\.)?(min_|max_|sector$|exchange$)/.test(row.key)&&(row.value===null||row.value===0))row.quiet=true;
    return {kind,parameters,performance,headline,requestedWindow,observationWindow,notices:kind==='random'?['Random dates: mean trial CAGR is not one portfolio return, and percentiles are not confidence intervals.']:[]};
  }
  // Inputs are compact descriptions, not stored artifacts, one cell of text per
  // description in each row. Values determine differences; a label keeps each
  // record's original wording. When two values differ behind the same plain
  // text, the cells of that row print the exact text. A setting that a test
  // lacks reads Not recorded; a measure that it lacks shows a dash. A row of
  // recorded facts keeps its mark, so a list of requested settings can omit it.
  function compare(descriptions){
    const distinct=values=>new Set(values).size>1;
    function align(lists,missing){
      const maps=lists.map(rows=>new Map(rows.map(row=>[row.key,row])));
      return [...new Set(maps.flatMap(map=>[...map.keys()]))].map(key=>{
        const rows=maps.map(map=>map.get(key)),values=rows.map(row=>stable(row?.value));
        const hidden=rows.some((row,i)=>row&&rows.some((other,j)=>j>i&&other&&values[i]!==values[j]&&row.display===other.display));
        return {key,label:[...new Set(rows.filter(Boolean).map(row=>row.label))].join(' / '),cells:rows.map(row=>row?hidden?row.exact??row.display:row.display:missing),different:distinct(values),...(rows.some(row=>row?.recorded)&&{recorded:true})};
      });
    }
    const of=key=>descriptions.map(description=>description[key]),notices=[...new Set(of('notices').flat())];
    if(distinct(of('kind')))notices.push('These tests use different test types; their measures can differ.');
    const windows=[['requested date windows','requestedWindow'],['recorded observation windows','observationWindow']].filter(([,key])=>distinct(of(key).map(stable))).map(([name])=>name);
    if(windows.length)notices.push('These tests use different '+windows.join(' and ')+'.');
    return {parameters:align(of('parameters'),'Not recorded'),headline:align(of('headline'),'—'),performance:align(of('performance'),'—'),notices};
  }
  return {describe,compare,scalarRows,finalRank,plainName};
})();
if(typeof module!=='undefined')module.exports=BacktestComparison;
