/* One searchable list for every filter source. The owner supplies grouped
   choices and receives the chosen value. The picker keeps no strategy state:
   rows can be re-rendered at any time and an open list follows its row key. */
const FilterPicker=(()=>{
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const field=key=>document.getElementById('filter-search-'+key),box=key=>document.getElementById('filter-options-'+key);
  let owner=null,state=null;
  function matches(option,query){
    const text=[option.label,option.detail,option.keywords].join(' ').toLowerCase();
    return String(query||'').toLowerCase().split(/\s+/).filter(Boolean).every(word=>text.includes(word));
  }
  function view(){
    const choices=owner.choices(),query=state.typed?state.query:'';
    const groups=choices.groups.map(group=>({label:group.label,options:group.options.filter(option=>matches(option,query))})).filter(group=>group.options.length);
    return {groups,actions:choices.actions||[],note:choices.note||''};
  }
  function render(){
    const input=field(state.key),list=box(state.key);
    if(!input||!list){state=null;return;}
    const current=view(),items=[...current.groups.flatMap(group=>group.options),...current.actions];
    // After typing, Enter takes the best match. Actions are only chosen on purpose.
    if(state.active>=items.length||items[state.active]?.disabled)state.active=-1;
    if(state.active<0&&state.typed)state.active=items.slice(0,items.length-current.actions.length).findIndex(item=>!item.disabled);
    let index=0;
    const option=item=>{const i=index++;return `<div role="option" id="filter-option-${esc(state.key)}-${i}" data-option="${i}" aria-selected="${i===state.active}"${item.disabled?' aria-disabled="true"':''}><span>${esc(item.label)}</span>${item.detail?`<small>${esc(item.detail)}</small>`:''}</div>`;};
    list.innerHTML=current.groups.map(group=>`<div role="group" aria-label="${esc(group.label)}"><div class="filter-options-heading" aria-hidden="true">${esc(group.label)}</div>${group.options.map(option).join('')}</div>`).join('')
      +(current.groups.length?'':`<p class="filter-options-empty">Nothing matches “${esc(state.query)}”. Try another word, or create a variable.</p>`)
      +(current.note?`<p class="filter-options-note">${esc(current.note)}</p>`:'')
      +(current.actions.length?`<div class="filter-options-actions">${current.actions.map(option).join('')}</div>`:'');
    state.items=items;list.hidden=false;
    input.setAttribute('aria-expanded','true');
    input.setAttribute('aria-activedescendant',state.active>=0?'filter-option-'+state.key+'-'+state.active:'');
    list.querySelector('[aria-selected="true"]')?.scrollIntoView({block:'nearest'});
  }
  function open(key){
    if(state?.key===key)return;
    close();state={key,typed:false,query:'',active:-1,items:[]};
    owner.opened();render();
  }
  function close(){
    if(!state)return;
    const input=field(state.key),list=box(state.key);state=null;
    if(list){list.hidden=true;list.innerHTML='';}
    if(input){input.value=input.dataset.label||'';input.setAttribute('aria-expanded','false');input.setAttribute('aria-activedescendant','');}
  }
  function move(step){
    const count=state.items.length;if(!count)return;
    for(let i=1;i<=count;i++){const next=(state.active+step*i+count*2)%count;if(!state.items[next].disabled){state.active=next;break;}}
    render();
  }
  function choose(index){
    const item=state?.items[index];if(!item||item.disabled)return;
    const key=state.key;close();
    // Keep the chosen label visible while the owner applies the choice.
    const input=field(key);if(input)input.value=item.label;
    owner.choose(key,item.value);
  }
  function bind(container,options){
    owner=options;
    const key=target=>target.dataset.filterSearch;
    container.addEventListener('focusin',event=>{const k=key(event.target);if(k===undefined)return;open(k);event.target.select();});
    container.addEventListener('input',event=>{const k=key(event.target);if(k===undefined)return;event.stopPropagation();if(state?.key!==k)open(k);state.typed=true;state.query=event.target.value;state.active=-1;render();});
    container.addEventListener('change',event=>{if(key(event.target)!==undefined)event.stopPropagation();});
    container.addEventListener('keydown',event=>{
      const k=key(event.target);if(k===undefined)return;
      if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();if(state?.key!==k)open(k);move(event.key==='ArrowDown'?1:-1);}
      else if(event.key==='Enter'){event.preventDefault();if(state?.key===k&&state.active>=0)choose(state.active);}
      else if(event.key==='Escape'&&state?.key===k){event.preventDefault();event.stopPropagation();close();}
    });
    // Re-rendering a row removes its focused field and fires focusout. Close
    // only if focus did not move to the same row's new field.
    container.addEventListener('focusout',event=>{
      const k=key(event.target);if(k===undefined||state?.key!==k)return;
      setTimeout(()=>{if(state?.key===k&&document.activeElement!==field(k))close();});
    });
    // Pointer use inside the list, including its scrollbar, must not blur the
    // search field first.
    container.addEventListener('mousedown',event=>{
      if(!event.target.closest('.filter-options'))return;event.preventDefault();
      const option=event.target.closest('[data-option]');if(option)choose(+option.dataset.option);
    });
  }
  // Rows re-render after strategy changes. Keep an open list on its new row.
  function refresh(){
    if(!state)return;
    const input=field(state.key);if(!input){state=null;return;}
    if(state.typed)input.value=state.query;
    if(document.activeElement!==input)input.focus({preventScroll:true});
    render();
  }
  return {bind,refresh};
})();
