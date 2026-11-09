"""Acquire detached latest-screen projections from the open (latest) book of the book store."""
from contextlib import closing
from dataclasses import dataclass
from backtest.inputs import book_store, daily, facts, market, research
from backtest.financial.metrics import METRICS, FILTERS
from backtest import screening


def load_screening_data(db,market_id='us'):
    """The latest book's rows, ranking pairs and filter values; db is a daily connection that attaches research."""
    book=book_store.open_book(db,market=market_id);record=book_store.record(db,book)
    # A latest row is the book's LATEST shape without its pool, in that order.
    fields=book_store.LATEST[1:]
    companies,latest,metric_values,filter_values={},{},{},{}
    for pool in (('legacy','cached') if market_id=='us' else ('cached',)):
        rows=list(book_store.rows(db,book,pool))
        latest[pool]=[[row[field] for field in fields] for row in rows]
        companies.update((row['symbol'],[row['name'],row['exchange'],row['sector']]) for row in rows)
        # By pool, then symbol in symbol order.
        pairs,values=book_store.lanes(db,book,pool)
        metric_values[pool]={symbol:{metric:[multiples[symbol],yields[symbol]] for metric,(multiples,yields) in pairs.items()
                                     if symbol in multiples}
                             for symbol in sorted(set().union(*(multiples for multiples,_ in pairs.values())))}
        filter_values[pool]={symbol:{field:found[symbol] for field,found in values.items() if symbol in found}
                             for symbol in sorted(set().union(*values.values()))}
    latest['metadata']=dict(asof=record['entry'],eligible_financials=record['candidates'])
    # Sector and exchange choices cover every saved company, for dated runs too.
    choices={column:[row[0] for row in db.execute(f"SELECT DISTINCT c.{column} FROM research.companies c LEFT JOIN research.company_markets m USING(symbol) WHERE COALESCE(m.market,'us')=? ORDER BY c.{column}",(market_id,))]
             for column in ('sector','exchange')}
    sessions=facts.sessions(db,market_id)
    bounds=dict(first=max('1996-01-01',str(sessions[0])) if sessions else None,last=str(sessions[-1]) if sessions else None)
    return dict(market=market_id,bounds=bounds,filter_catalog=FILTERS, filter_values=filter_values, companies=companies, latest=latest,
                metrics=METRICS, metric_values=metric_values, choices=choices)


@dataclass
class PageData:
    screening_data: dict
    latest_stocks: list


def load_page_data():
    with closing(daily.connect()) as db:
        record=research.identity(db,'research')
        dates=record.get('latest_dates',{'us':record['latest_date']})
        def screen(market_id):
            if market_id in dates:return load_screening_data(db,market_id)
            return dict(market=market_id,bounds=dict(first=None,last=None),filter_catalog=FILTERS,filter_values={'legacy':{},'cached':{}},
                        companies={},latest={'legacy':[],'cached':[],'metadata':dict(asof=None,eligible_financials=0)},
                        metrics=METRICS,metric_values={'legacy':{},'cached':{}},choices={'sector':[],'exchange':[]})
        screening_data=screen('us')
        screening_data['markets']={code:screen(code) for code in market.MARKETS if code!='us'}
        latest_stocks=screening.latest(db,pool='cached') if 'us' in dates else []
    return PageData(screening_data,latest_stocks)
