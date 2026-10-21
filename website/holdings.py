"""Load the current top-50 holdings from the prepared January database."""
import sys
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'scripts'))
from research import website_holdings


def load():
    groups = website_holdings()
    fields = ['rank','symbol','name','exchange','sector','fiscal','entry','exit',
              'market_cap','enterprise_value','ebitda_yield','ev_ebitda',
              'return_value','status']
    result = {}
    for year, group in groups.items():
        stocks = [{key: row[key] for key in fields} for row in group['holdings']]
        for row in stocks:
            row['ev_ebitda'] = 1.0 / row['ebitda_yield']
        result[year] = dict(holdings=stocks,
                           median_yield=statistics.median(h['ebitda_yield'] for h in stocks),
                           median_multiple=statistics.median(h['ev_ebitda'] for h in stocks))
    return result
