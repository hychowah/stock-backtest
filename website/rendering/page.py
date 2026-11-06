"""Render static latest-screen markup and the self-contained browser page."""
import html
import re
import statistics
from website.rendering import assets


def render(page_data):
    screening_data=page_data.screening_data
    latest_stocks=page_data.latest_stocks

    def esc(v):
        return html.escape(str(v), quote=True)

    page = assets.template()
    latest_asof = screening_data['latest']['metadata']['asof']
    latest_heads = ['Rank','Symbol','Company','Exchange','Sector','Adj. price (USD)','Market cap','Enterprise value','EBITDA/EV','EV/EBITDA','Fiscal year-end','Available from (assumed)','Price date']
    latest_rows = []
    for h in latest_stocks:
        vals = [h['rank'],h['symbol'],h['name'],h['exchange'],h['sector'],f"{h['price']:.2f}",f"${h['market_cap']/1e6:,.1f}m",f"${h['enterprise_value']/1e6:,.1f}m",f"{h['ebitda_yield']:.2%}",f"{h['ev_ebitda']:.2f}×",h['fiscal'],h['known'],h['price_date']]
        latest_rows.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in vals)+'</tr>')
    latest_cap = f"${statistics.median(h['market_cap'] for h in latest_stocks)/1e6:,.1f}m" if latest_stocks else '—'
    latest_yield = f"{statistics.median(h['ebitda_yield'] for h in latest_stocks):.2%}" if latest_stocks else '—'
    latest_panel = f'''<section id="latest-view" class="panel"><div class="toolbar"><div><span class="eyebrow">Latest cached close</span><h2>Stock picks · <span id="latest-date">{latest_asof}</span></h2></div><a id="download-latest" href="latest-picks.csv" download>Download latest picks ↓</a></div>
    <p class="hint">Re-ranked using prices on this exact session and available annual financials, with a 90-day reporting lag and 800-day report-age limit. Stocks without a price on this date, including old trading stops, are excluded. Cached listing status and price coverage limit the universe. This is a saved-data screen, not a live quote feed.</p>
    <div class="latest-facts"><span>Selected stocks<strong id="latest-count">{len(latest_stocks)}</strong></span><span>Median market cap<strong id="latest-median-cap">{latest_cap}</strong></span><span>Median selected metric yield<strong id="latest-median-yield">{latest_yield}</strong></span></div>
    <div class="latest-table"><table class="stock-table"><thead><tr>{''.join('<th'+(' data-metric-multiple' if h=='EV/EBITDA' else ' data-metric-yield' if h=='EBITDA/EV' else '')+'>'+h+'</th>' for h in latest_heads)}</tr></thead><tbody id="latest-body">{''.join(latest_rows) if latest_rows else '<tr><td colspan="13">No stocks match these filters.</td></tr>'}</tbody></table></div><p class="hint">Market cap and EV are estimates at the displayed date using dividend-adjusted prices and report net debt. “Available from” is the assumed fiscal year-end plus 90 days, not a verified publication date. No holding return or contribution exists yet for these picks.</p></section>'''
    page = page.replace('__LATEST_PANEL__', latest_panel)
    page = page.replace('__BACKTEST_QUEUE__',assets.queue_fragment())
    page = page.replace('<div class="filter-grid">',assets.variable_controls()+'<div class="filter-grid">',1)
    page = page.replace('</main>',assets.variable_fragment()+'</main>')
    scripts=assets.scripts(screening_data)
    page=page.replace('</head>', '<style>'+assets.styles()+'</style></head>')
    # Keep scroll instructions and keyboard access in the static fallback too.
    page = re.sub(r'<div class="(scroll|table-wrap|latest-table)">',
                  lambda m: '<p class="scroll-hint">Scroll sideways for more columns or chart periods.</p>'
                  + '<div class="'+m[1]+'" tabindex="0" role="region" aria-label="Scrollable chart or data table">', page)
    page = re.sub(r'(</svg></div>)', r'\1<p class="chart-detail" aria-live="polite">Tap, hover over, or focus a chart mark to see details.</p>', page)
    page = page.replace('</body>', scripts+'</body>')
    return page
