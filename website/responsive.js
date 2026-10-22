/* Delegate to the SVG so details also work after a chart is redrawn. */
document.querySelectorAll('svg').forEach(chart=>{
  const show=event=>{
    const mark=event.target.closest('rect,path,line');
    if(!mark || !chart.contains(mark))return;
    const text=mark.getAttribute('aria-label') || mark.querySelector('title')?.textContent;
    if(!text)return;
    const detail=chart.closest('.scroll')?.nextElementSibling;
    if(detail?.classList.contains('chart-detail'))detail.textContent=text;
  };
  ['click','focusin','pointerover'].forEach(event=>chart.addEventListener(event,show));
});
