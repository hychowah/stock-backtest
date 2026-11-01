"""Static return-contribution fallback for previews without JavaScript."""
from html import escape

GAIN_COLORS = ['#20775e','#359671','#549e7b','#77b38f','#95c8a6','#16745b','#428b76','#66b6a0','#88c9b7','#b1dbc8']
LOSS_COLORS = ['#ae4d40','#c96957','#db8a70','#e3a38d','#edc0ac']


def pp(value):
    return f'{value*100:+.2f}'


def pie(top, others, sign):
    named = [(h['symbol'], h['contribution'] * sign, False) for h in top if h['contribution'] * sign > 0]
    remaining = sum(max(0, h['contribution'] * sign) for h in others)
    if remaining:
        named.append(('Other gainers' if sign > 0 else 'Other losers', remaining, True))
    total = sum(value for _, value, _ in named)
    colors = GAIN_COLORS if sign > 0 else LOSS_COLORS
    heading = 'Gains' if sign > 0 else 'Losses'
    gradient, legend, cursor = [], [], 0.
    for i, (label, value, other) in enumerate(named):
        share = value / total * 100
        color = ('#d8e3dc' if sign > 0 else '#e8cbc3') if other else colors[i % len(colors)]
        gradient.append(f'{color} {cursor}% {cursor+share}%')
        cursor += share
        legend.append(f'<li><i style="background:{color}"></i>{escape(label)} · {share:.1f}% · {pp(value*sign)} pp</li>')
    background = 'conic-gradient('+','.join(gradient)+')' if gradient else '#e5eae4'
    content = '<ul class="contribution-legend">'+''.join(legend)+'</ul>' if legend else f'<p class="hint">No {heading.lower()} this year.</p>'
    label = escape(f'{heading} contribution {pp(total*sign)} percentage points.')
    return f'<figure><h4>{heading}</h4><div class="contribution-pie" role="img" aria-label="{label}" style="background:{background}"><div class="contribution-pie-center">{pp(total*sign)} pp<small>portfolio impact</small></div></div>{content}</figure>'


def render(holdings, year):
    n = len(holdings)
    if not n:
        return '<p class="contribution-empty">No selected stocks to attribute for this year.</p>'
    ranked = sorted((dict(h, contribution=h['return_value']/n) for h in holdings), key=lambda h: (-h['contribution'], h['symbol']))
    top = ranked[:10]
    others = ranked[len(top):]
    net = sum(h['return_value'] for h in holdings)/n
    top_total = sum(h['contribution'] for h in top)
    rest_total = sum(h['contribution'] for h in others)
    rows = ''.join(f'<tr><td>{escape(h["symbol"])}</td><td>{escape(h["name"])}</td><td>{pp(h["return_value"])}%</td><td class="{"positive" if h["contribution"]>=0 else "negative"}">{pp(h["contribution"])} pp</td></tr>' for h in top)
    partial = ' · partial year' if year == 2026 else ''
    return f'''<div class="contribution-panel"><h3>{year} return contributions{partial}</h3>
<p class="hint">Each contribution is the stock return ÷ {n}, in percentage points (pp) of portfolio return. Showing the top {len(top)} of {n} stocks, capped at 10 and ranked by signed contribution.</p>
<div class="contribution-facts"><span>Portfolio return<strong>{pp(net)}%</strong></span><span>Top {len(top)} contribution<strong>{pp(top_total)} pp</strong></span><span>Other {len(others)} contribution<strong>{pp(rest_total)} pp</strong></span></div>
<div class="contribution-layout"><div><div class="contribution-pies">{pie(top,others,1)}{pie(top,others,-1)}</div><p class="hint">Each pie shows shares of gains or losses separately. Gains minus losses equals the portfolio return. Named slices are top contributors; other stocks are grouped.</p></div>
<div class="top-contributors"><h3>Top 10 contributors · {len(top)} stocks</h3><div class="scroll"><table><thead><tr><th>Stock</th><th>Company</th><th>Stock return</th><th>Contribution</th></tr></thead><tbody>{rows}</tbody></table></div><p class="hint">If all stocks lost money, the top contributors are the smallest losses. Contributions describe this historical book, not the selection signal.</p></div></div></div>'''
