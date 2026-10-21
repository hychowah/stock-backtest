"""Reconstruct current holdings from cache using revalue's selection and exits."""
import json
import statistics
import sys
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "scripts"))
import run
import revalue


def load():
    # Forbid downloads during website generation, including accidental future calls.
    def offline(*args, **kwargs):
        raise RuntimeError('Website builds must use cached data only')
    run.get_json = offline
    universe = {r['symbol']: r for r in json.loads((run.RAW/'universe.json').read_text())}
    book = run.build_statements(universe)
    spy = run.load_bars(run.RAW/'spy-div.json', 'adjClose')
    sessions = [d for d, _ in spy]
    yields = []
    for r in json.loads((run.RAW/'treasury.json').read_text()):
        d, v = run.parse_day(r.get('date')), run.num(r.get('month3'))
        if d is not None and v is not None:
            yields.append((d, v/100))
    picks = run.screen(book, sorted(yields), sessions)
    prices = {s: run.load_price_pair(s) for s in {r['symbol'] for rs in picks.values() for r in rs}}
    result = {}
    for year, candidates in picks.items():
        ranked = []
        for r in candidates:
            light, div = prices[r['symbol']]
            scaled = run.rescale(r, light or div)
            if scaled is not None:
                ranked.append(scaled)
        ranked.sort(key=lambda r:r['spread'], reverse=True)
        holdings = []
        exit_day = run.session_on_or_after(sessions,date(year+1,1,1)) if year<run.LAST_YEAR else sessions[-1]
        for rank, r in enumerate(ranked[:run.HOLD],1):
            div = prices[r['symbol']][1]
            start = run.first_on_or_after(div,r['entry_day'],4)
            if start is None:
                continue
            end = run.last_on_or_before(div,exit_day,10)
            status = 'Scheduled exit' if year<run.LAST_YEAR else 'Marked to date'
            if (year,r['symbol']) in revalue.BANKRUPT:
                ret, status = -1., 'Bankruptcy'
                end = revalue.last_in_window(div,start[0],exit_day)
            else:
                if end is None:
                    end = revalue.last_in_window(div,start[0],exit_day)
                    status = 'Last available price'
                if end is None:
                    continue
                ret = end[1]/start[1]-1
            info = universe[r['symbol']]
            holdings.append(dict(rank=rank,symbol=r['symbol'],name=info.get('name') or 'Unavailable',exchange=info.get('exchange') or 'Unavailable',sector=info.get('sector') or 'Unavailable',fiscal=str(r['fiscal']),entry=str(start[0]),exit=str(end[0]) if end else '',market_cap=r['equity_now'],enterprise_value=r['ev_now'],ebitda_yield=r['ebitda_yield_now'],ev_ebitda=1/r['ebitda_yield_now'],return_value=ret,status=status))
        result[year] = dict(holdings=holdings,median_yield=statistics.median(r['ebitda_yield'] for r in holdings),median_multiple=statistics.median(r['ev_ebitda'] for r in holdings))
    return result
