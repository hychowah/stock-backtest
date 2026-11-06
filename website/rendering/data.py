"""Acquire detached latest-screen projections from the latest book of the book store."""
from contextlib import closing
from dataclasses import dataclass
from backtest.inputs import book_store, daily
from backtest.financial.metrics import METRICS, FILTERS
from backtest import screening


def load_screening_data(db=None):
    """The latest book's rows, ranking pairs and filter values; db is a daily connection that attaches research."""
    if db is None:
        with closing(daily.connect()) as acquired:
            return load_screening_data(acquired)
    book,asof=book_store.latest(db)
    companies = {r['symbol']: [r['name'], r['exchange'], r['sector']]
                 for r in db.execute('SELECT symbol,name,exchange,sector FROM research.companies '
                                     'WHERE symbol IN (SELECT symbol FROM book_rows WHERE book=?)',(book,))}
    latest_fields=['symbol','candidate_rank','fiscal','known','entry','price','market_cap','enterprise_value','ebitda_yield','ev_ebitda','spread']
    latest={pool:[list(row) for row in db.execute('SELECT '+','.join(latest_fields)+' FROM book_rows WHERE book=? AND pool=? ORDER BY symbol',(book,pool))] for pool in ['legacy','cached']}
    candidates=db.execute('SELECT candidates FROM books WHERE book=?',(book,)).fetchone()[0]
    latest['metadata']=dict(asof=asof,eligible_financials=candidates)
    # The browser keys keep their old 'latest:<pool>:0:<symbol>' form.
    metric_values={}
    for r in db.execute('SELECT pool,symbol,metric,multiple,yield_value FROM book_metrics WHERE book=?',(book,)):
        metric_values.setdefault(f"latest:{r['pool']}:0:{r['symbol']}",{})[r['metric']]=[r['multiple'],r['yield_value']]
    filter_values={}
    for r in db.execute('SELECT pool,symbol,field,value FROM book_filters WHERE book=?',(book,)):
        filter_values.setdefault(f"latest:{r['pool']}:0:{r['symbol']}",{})[r['field']]=r['value']
    # Sector and exchange choices cover every saved company, for dated runs too.
    choices={column:[row[0] for row in db.execute(f'SELECT DISTINCT {column} FROM research.companies ORDER BY {column}')]
             for column in ('sector','exchange')}
    return dict(filter_catalog=FILTERS, filter_values=filter_values, companies=companies, latest=latest,
                metrics=METRICS, metric_values=metric_values, choices=choices)


@dataclass
class PageData:
    screening_data: dict
    latest_stocks: list


def load_page_data():
    with closing(daily.connect()) as db:
        screening_data=load_screening_data(db)
        latest_stocks=screening.latest(db)
    return PageData(screening_data,latest_stocks)
