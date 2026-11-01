"""Render static fallback markup and the self-contained browser page."""
import html
import json
import math
import re
import statistics
from website.rendering import assets
from website.rendering.attribution import render as render_attribution


def render(page_data):
    data=page_data.annual
    rows=page_data.rows
    holdings=page_data.holdings
    screening_data=page_data.screening_data
    latest_stocks=page_data.latest_stocks
    def pct(value):
        return f'{value:+.2%}'

    def y(value):
        return 20 + (1 - value) / 1.4 * 345

    # Include real chart and table markup so previews need no JavaScript to show data.
    svg = []
    for tick in range(-40, 101, 20):
        pos = y(tick / 100)
        svg.append(f'<line x1="60" x2="1180" y1="{pos}" y2="{pos}" stroke="{ "#7e9188" if tick == 0 else "#e5eae4"}"/><text x="48" y="{pos+4}" text-anchor="end" font-size="11" fill="#657774">{tick}%</text>')
    table = []
    step = 1120 / len(data)
    for i, row in enumerate(data):
        year = str(row['year']) + ('*' if row['year'] == 2026 else '')
        desc = f"{year} · Strategy {pct(row['portfolio'])} · SPY {pct(row['spy'])} · Excess {(row['portfolio']-row['spy'])*100:+.2f} pp"
        x = 60 + i * step + 4
        width = (step - 10) / 2
        for offset, key, color in [(0, 'portfolio', '#20775e'), (width+2, 'spy', '#acb8c5')]:
            value = row[key]
            svg.append(f'<rect class="bar" tabindex="0" aria-label="{desc}" x="{x+offset}" y="{min(y(0), y(value))}" width="{width}" height="{max(1,abs(y(value)-y(0)))}" rx="2" fill="{color}"><title>{desc}</title></rect>')
        svg.append(f'<text transform="translate({x+step/2-4},388) rotate(-55)" text-anchor="end" font-size="11" fill="#536762">{year}</text>')
        cells = []
        for value, suffix in [(row['portfolio'], '%'), (row['spy'], '%'), (row['portfolio']-row['spy'], '')]:
            cells.append(f'<td class="{"positive" if value >= 0 else "negative"}">{value*100:+.2f}{suffix}</td>')
        table.append(f'<tr><td>{year}</td><td>50</td>{"".join(cells)}</tr>')
    page = assets.template().replace('__DATA__', json.dumps(data))
    page = re.sub(r'(<svg id="chart"[^>]*>).*?(</svg>)', lambda m: m[1]+''.join(svg)+m[2], page, count=1, flags=re.S)
    page = page.replace('<tbody id="rows"></tbody>', '<tbody id="rows">'+''.join(table)+'</tbody>')
    def esc(v):
        return html.escape(str(v), quote=True)

    maximum = max(1, math.ceil(max(r['median_market_cap'] for r in holdings.values())/1e9))
    vy = lambda v: 330-v/1e9/maximum*290
    vs = []
    for i in range(5):
        tick = maximum*i/4
        pos = vy(tick*1e9)
        vs.append(f'<line x1="60" x2="1180" y1="{pos}" y2="{pos}" stroke="#e5eae4"/><text x="48" y="{pos+4}" text-anchor="end" font-size="11">${tick:g}bn</text>')
    sections = []
    for i, (year, group) in enumerate(holdings.items()):
        x = 60+i*step+5
        median = group['median_market_cap']
        vs.append(f'<rect tabindex="0" x="{x}" y="{vy(median)}" width="{step-10}" height="{330-vy(median)}" fill="#20775e"><title>{year}: ${median/1e6:,.1f}m median market cap</title></rect><text transform="translate({x+step/2-5},353) rotate(-55)" text-anchor="end" font-size="11">{year}</text>')
        trs = []
        for h in group['holdings']:
            vals = [h['rank'],h['symbol'],h['name'],h['exchange'],h['sector'],f"{h['ebitda_yield']:.2%}",f"{h['ev_ebitda']:.2f}×",f"${h['market_cap']/1e6:,.1f}m",f"${h['enterprise_value']/1e6:,.1f}m",h['fiscal'],h['entry'],h['exit'],pct(h['return_value']),f"{h['return_value']/len(group['holdings'])*100:+.2f} pp",h['status']]
            trs.append(f'<tr id="stock-{year}-{h["rank"]}">'+''.join('<td>'+esc(v)+'</td>' for v in vals)+'</tr>')
        heads = ['Rank','Symbol','Company','Exchange','Sector','EBITDA/EV','EV/EBITDA','Market cap','Enterprise value','Fiscal year-end','Entry','Exit / mark','Return','Contribution (pp)','Exit basis']
        sections.append(f'<details id="holdings-{year}"'+(' open' if year==2025 else '')+f'><summary id="holding-summary-{year}">{year} · {len(group["holdings"])} stocks · Median market cap ${median/1e6:,.1f}m</summary><div id="contributions-{year}">{render_attribution(group["holdings"],year)}</div><h3 class="all-holdings-label">All selected stocks</h3><div class="scroll"><table class="stock-table"><thead><tr>'+''.join('<th'+(' data-metric-multiple' if h=='EV/EBITDA' else ' data-metric-yield' if h=='EBITDA/EV' else '')+'>'+h+'</th>' for h in heads)+f'</tr></thead><tbody id="holding-body-{year}">'+''.join(trs)+'</tbody></table></div></details>')
    options = ''.join(f'<option value="{yr}">{yr}</option>' for yr in holdings)
    extra = '<section class="panel"><h2>Median market cap at each January purchase</h2><p class="hint">Median equity market value of the selected stocks at purchase, in nominal US dollars. The middle two market caps are averaged. Axis shown in billions of dollars.</p><div class="scroll"><svg id="market-cap-chart" viewBox="0 0 1200 400" role="img" aria-label="Median stock market capitalization by book year">'+''.join(vs)+'</svg></div></section>'
    extra += '<section class="panel"><h2>Explore the selected stocks</h2><p class="hint">Choose a year to see contribution pies, the top 10 contributors, and the full stock list. Market cap and enterprise value are estimates at purchase; sector and company names come from cached universe metadata, not historical profiles. Unavailable sectors are left unclassified. Prices used for valuation and returns are dividend-adjusted.</p><label for="holding-year">Book year </label><select id="holding-year"><option value="">Choose year…</option>'+options+'</select> <a id="download-holdings" href="holdings.csv" download>Download selected holdings ↓</a><div class="holding-years">'+''.join(sections)+'</div></section>'
    extra += """<style>details{border-top:1px solid #dce1d9;margin-top:12px}summary{cursor:pointer;padding:16px 0;color:#244f43}details table{min-width:1600px}details td:nth-child(3){text-align:left;min-width:220px}select{padding:8px;border:1px solid #ccd5d0;border-radius:5px}</style>"""
    page = page.replace('<div class="method">', extra+'<div class="method">')
    # Static options also keep the period controls understandable in previews.
    for token, chosen in [('__FROM_OPTIONS__', 1996), ('__TO_OPTIONS__', 2025)]:
        opts = ''.join(f'<option value="{d["year"]}"'+(' selected' if d['year']==chosen else '')+f'>{d["year"]}</option>' for d in data)
        page = page.replace(token, opts)
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
    scripts=assets.scripts(screening_data,holdings)
    page=page.replace('</head>', '<style>'+assets.styles()+'</style></head>')
    # Keep scroll instructions and keyboard access in the static fallback too.
    page = re.sub(r'<div class="(scroll|table-wrap|latest-table)">',
                  lambda m: '<p class="scroll-hint">Scroll sideways for more columns or chart periods.</p>'
                  + '<div class="'+m[1]+'" tabindex="0" role="region" aria-label="Scrollable chart or data table">', page)
    page = re.sub(r'(</svg></div>)(?!<p id="detail")', r'\1<p class="chart-detail" aria-live="polite">Tap, hover over, or focus a chart mark to see details.</p>', page)
    page = page.replace('</body>', scripts+'</body>')
    return page
