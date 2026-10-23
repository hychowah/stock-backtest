"""Independent cache-only January calculation and verified reference refresh.

This engine uses run's original screen and price arithmetic. It does not use
prepared snapshots, books.snapshot, or the SQL selector.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import date
import io
import json

import run
from paths import RAW, RESULTS

# Filled after the filing check. Symbol-year pairs that are bankruptcies.
BANKRUPT: set[tuple[int, str]] = set()


def last_in_window(div, entry: date, exit_day: date):
    last = None
    for day, price in div:
        if entry <= day <= exit_day:
            last = (day, price)
    return last


def calculate(through: date):
    """Return full-precision years and priced holdings through a fixed date.

    Read saved files only. The caller owns cache_access for both engines. Dates
    in the result are ISO strings; unavailable prices are never carried forward
    beyond the original engine's price rules. This function never publishes.
    """
    universe = {row['symbol']: row for row in json.loads((RAW/'universe.json').read_text(encoding='utf-8'))}
    with redirect_stdout(io.StringIO()):
        book = run.build_statements(universe)
        spy = [row for row in run.load_bars(RAW/'spy-div.json','adjClose') if row[0] <= through]
        sessions = [day for day, _ in spy]
        treasury = json.loads((RAW/'treasury.json').read_text(encoding='utf-8'))
        yields = []
        for row in treasury:
            day, value = run.parse_day(row.get('date')), run.num(row.get('month3'))
            if day is not None and value is not None: yields.append((day,value/100.))
        yields.sort()
        picks = run.screen(book,yields,sessions)
    prices = {symbol: run.load_price_pair(symbol) for symbol in sorted({r['symbol'] for rows in picks.values() for r in rows})}
    years = []
    for year in range(run.FIRST_YEAR,run.LAST_YEAR+1):
        rows = picks.get(year) or []
        if not rows: continue
        rebalance = rows[0]['rebalance']
        end = run.session_on_or_after(sessions,date(year+1,1,1)) if year < run.LAST_YEAR else sessions[-1]
        if end is None: raise ValueError('Reference calculation lacks an exit session for '+str(year))
        refreshed = []
        for row in rows:
            light, div = prices[row['symbol']]
            scaled = run.rescale(row,light or div)
            if scaled is not None: refreshed.append(scaled)
        refreshed.sort(key=lambda r:r['spread'],reverse=True)
        holdings = []
        for rank,row in enumerate(refreshed[:run.HOLD],1):
            light, div = prices[row['symbol']]
            start = run.first_on_or_after(div,row['entry_day'],4)
            if start is None: continue
            finish = run.last_on_or_before(div,end,10)
            status = 'Scheduled exit' if end.year > rebalance.year else 'Marked to date'
            bankrupt = (year,row['symbol']) in BANKRUPT
            if finish is None:
                finish = last_in_window(div,start[0],end)
                status = 'Last available price'
            if finish is None: continue
            ret = -1. if bankrupt else finish[1]/start[1]-1
            if bankrupt: status = 'Bankruptcy'
            fiscal = run.last_on_or_before(light or div,row['fiscal'],7)
            entry = run.first_on_or_after(light or div,rebalance,4)
            holdings.append(dict(symbol=row['symbol'],rank=rank,fiscal=str(row['fiscal']),entry=str(start[0]),exit=str(finish[0]),
                                 fiscal_price_date=str(fiscal[0]),valuation_date=str(entry[0]),fiscal_price=fiscal[1],valuation_price=entry[1],entry_price=start[1],exit_price=finish[1],
                                 market_cap=row['equity_now'],enterprise_value=row['ev_now'],ebitda=row['ebitda_yield']*row['enterprise'],
                                 return_value=ret,status=status))
        if not holdings: raise ValueError('Reference calculation has no holdings for '+str(year))
        a,b=run.first_on_or_after(spy,rebalance,4),run.last_on_or_before(spy,end,4)
        years.append(dict(year=year,entry=str(rebalance),exit=str(end),spy_entry=str(a[0]),spy_exit=str(b[0]),
                          spy_entry_price=a[1],spy_exit_price=b[1],spy=b[1]/a[1]-1,
                          portfolio=sum(h['return_value'] for h in holdings)/len(holdings),holdings=holdings))
    return dict(through=str(through),years=years)


def main():
    # Keep one publication policy for the CLI, launcher and data panel.
    import research
    research.prepare(force=True)
    print((RESULTS/'summary-exits.txt').read_text(encoding='utf-8'),flush=True)


if __name__=='__main__': main()
