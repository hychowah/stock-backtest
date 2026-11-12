/* The market switch of Runs shows the tests of one market, or of all markets, in
   In progress and Saved backtests. Each list reports the markets of its rows, and
   each button shows the sum for its market. The page remembers the last choice. */
const RunMarkets=(()=>{
  const labels={'':'All',us:'US',hk:'Hong Kong',jp:'Tokyo'},storageKey='runs-market',counts={},listeners=[];
  let chosen='';
  try{chosen=localStorage.getItem(storageKey)||'';}catch(_){}
  function render(){
    const all=Object.values(counts).flat();
    for(const button of document.getElementById('run-markets').querySelectorAll('button[data-market]')){
      const market=button.dataset.market;
      button.setAttribute('aria-pressed',String(market===chosen));
      button.querySelector('span').textContent=market?all.filter(value=>value===market).length:all.length;
    }
  }
  function init(){
    document.getElementById('run-markets').addEventListener('click',event=>{
      const market=event.target.closest?.('button[data-market]')?.dataset.market;
      if(market===undefined||market===chosen)return;
      chosen=market;try{localStorage.setItem(storageKey,chosen);}catch(_){}
      render();listeners.forEach(listener=>listener());
    });
    render();
  }
  return {
    init,
    // A record that has no readable market shows under All only.
    shows:market=>!chosen||market===chosen,
    // The name of the chosen market for an empty list, or '' for All.
    label:()=>chosen&&labels[chosen],
    report(list,markets){counts[list]=markets;render();},
    changed(listener){listeners.push(listener);},
  };
})();
