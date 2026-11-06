"""Acquire detached latest-screen projections from one verified prepared database."""
from contextlib import closing
from dataclasses import dataclass
import json
from backtest.inputs.research import connect
from backtest.financial.metrics import METRICS, FILTERS
from backtest import screening


def load_screening_data(db=None):
    if db is None:
        with closing(connect()) as acquired:
            return load_screening_data(acquired)
    companies = {r['symbol']: [r['name'], r['exchange'], r['sector']]
                 for r in db.execute('SELECT * FROM companies WHERE symbol IN (SELECT symbol FROM latest_snapshots)')}
    latest_fields=['symbol','candidate_rank','fiscal','known','price_date','price','market_cap','enterprise_value','ebitda_yield','ev_ebitda','spread']
    latest={pool:[list(row) for row in db.execute('SELECT '+','.join(latest_fields)+' FROM latest_snapshots WHERE pool=? ORDER BY symbol',(pool,))] for pool in ['legacy','cached']}
    latest['metadata']=json.loads(db.execute("SELECT value FROM metadata WHERE key='latest'").fetchone()[0])
    metric_values={}
    for r in db.execute("SELECT * FROM screening_metrics WHERE mode='latest'"):
        key=f"{r['mode']}:{r['pool']}:{r['year']}:{r['symbol']}"
        metric_values.setdefault(key,{})[r['metric']]=[r['multiple'],r['yield_value']]
    filter_values={}
    for r in db.execute("SELECT * FROM filter_values WHERE mode='latest'"):
        key=f"{r['mode']}:{r['pool']}:{r['year']}:{r['symbol']}"
        filter_values.setdefault(key,{})[r['field']]=r['value']
    # Sector and exchange choices cover every saved company, for dated runs too.
    choices={column:[row[0] for row in db.execute(f'SELECT DISTINCT {column} FROM companies ORDER BY {column}')]
             for column in ('sector','exchange')}
    return dict(filter_catalog=FILTERS, filter_values=filter_values, companies=companies, latest=latest,
                metrics=METRICS, metric_values=metric_values, choices=choices)


@dataclass
class PageData:
    screening_data: dict
    latest_stocks: list


def load_page_data():
    with closing(connect()) as db:
        screening_data=load_screening_data(db)
        latest_stocks=screening.latest(db)
    return PageData(screening_data,latest_stocks)
