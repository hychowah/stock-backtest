"""Acquire detached page projections from one verified prepared database."""
from contextlib import closing
from dataclasses import dataclass
import csv
import io
import json
from pathlib import Path
import statistics
from backtest.inputs.research import connect, aggregate
from backtest.financial.metrics import METRICS, FILTERS
from backtest.inputs.baseline import cutoff
from backtest import screening

ROOT = Path(__file__).resolve().parents[1]

FIELDS = ['year','symbol','candidate_rank','fiscal','entry','exit',
          'market_cap','enterprise_value','ebitda_yield','ev_ebitda',
          'return_value','status']


def load_screening_data(db=None):
    if db is None:
        with closing(connect()) as acquired:
            return load_screening_data(acquired)
    companies = {r['symbol']: [r['name'], r['exchange'], r['sector']]
                 for r in db.execute('SELECT * FROM companies WHERE symbol IN (SELECT symbol FROM snapshots UNION SELECT symbol FROM latest_snapshots)')}
    periods = {r['year']: dict(r) for r in db.execute('SELECT * FROM periods ORDER BY year')}
    pools = {}
    for pool in ['legacy', 'cached']:
        pools[pool] = [list(row) for row in db.execute(
            'SELECT '+','.join(FIELDS)+' FROM snapshots WHERE pool=? ORDER BY year,symbol', (pool,))]
    latest_fields=['symbol','candidate_rank','fiscal','known','price_date','price','market_cap','enterprise_value','ebitda_yield','ev_ebitda','spread']
    latest={pool:[list(row) for row in db.execute('SELECT '+','.join(latest_fields)+' FROM latest_snapshots WHERE pool=? ORDER BY symbol',(pool,))] for pool in ['legacy','cached']}
    latest['metadata']=json.loads(db.execute("SELECT value FROM metadata WHERE key='latest'").fetchone()[0])
    metric_values={}
    for r in db.execute('SELECT * FROM screening_metrics'):
        key=f"{r['mode']}:{r['pool']}:{r['year']}:{r['symbol']}"
        metric_values.setdefault(key,{})[r['metric']]=[r['multiple'],r['yield_value']]
    filter_values={}
    for r in db.execute('SELECT * FROM filter_values'):
        key=f"{r['mode']}:{r['pool']}:{r['year']}:{r['symbol']}"
        filter_values.setdefault(key,{})[r['field']]=r['value']
    return dict(filter_catalog=FILTERS, filter_values=filter_values, companies=companies, periods=periods, pools=pools, latest=latest,
                metrics=METRICS, metric_values=metric_values)

def load_holdings(db=None):
    if db is None:
        with closing(connect()) as acquired:
            return load_holdings(acquired)
    groups = aggregate(screening.historical(db))
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

@dataclass
class PageData:
    report_bytes: bytes
    report_text: str
    csv_text: str
    rows: list
    annual: list
    holdings: dict
    screening_data: dict
    latest_stocks: list
    historical_through: str


def load_page_data():
    report_bytes=(ROOT.parent/'results/summary-exits.txt').read_bytes()
    text=report_bytes.decode('utf-8').replace('\r\n','\n')
    csv_text=text[text.index('year,portfolio,spy,'):]
    rows=list(csv.DictReader(io.StringIO(csv_text)))
    annual=[dict(year=int(r['year']),portfolio=float(r['portfolio']),spy=float(r['spy'])) for r in rows]
    with closing(connect()) as db:
        holdings=load_holdings(db)
        screening_data=load_screening_data(db)
        latest_stocks=screening.latest(db)
    for group in holdings.values():
        group['median_market_cap']=statistics.median(h['market_cap'] for h in group['holdings'])
    for row in rows:
        stocks=holdings[int(row['year'])]['holdings']
        assert len(stocks)==int(row['names'])
        assert abs(sum(h['return_value'] for h in stocks)/len(stocks)-float(row['portfolio']))<=.000051,row['year']
    return PageData(report_bytes,text,csv_text,rows,annual,holdings,screening_data,latest_stocks,str(cutoff(text)))
