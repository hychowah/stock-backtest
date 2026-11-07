"""Read-only coverage evidence for an ordinary independently prepared workspace."""
from backtest.inputs import book_store, daily as daily_inputs, facts, market
from backtest.financial import rules

from collections import Counter
from contextlib import closing
from datetime import date
import json
from pathlib import Path

from backtest.inputs import research as r
from backtest.financial import books as books
from backtest.runtime import cache_access as cache_access


def series_summary(payload,key,*,positive=False):
    if isinstance(payload,dict):payload=payload.get('historical') or payload.get('data') or []
    if not isinstance(payload,list):raise ValueError('Invalid saved series.')
    dates=[];invalid=0
    for row in payload:
        day=rules.parse_day(row.get('date')) if isinstance(row,dict) else None
        value=rules.num(row.get(key)) if isinstance(row,dict) else None
        if day is None or value is None or positive and value<=0:invalid+=1
        else:dates.append(str(day))
    counts=Counter(dates);ordered=sorted(counts)
    gaps=Counter((date.fromisoformat(b)-date.fromisoformat(a)).days for a,b in zip(ordered,ordered[1:]))
    return dict(rows=len(payload),valid_rows=len(dates),invalid_rows=invalid,unique_dates=len(ordered),
                first=ordered[0] if ordered else None,last=ordered[-1] if ordered else None,
                duplicate_dates={d:n for d,n in sorted(counts.items()) if n>1},
                calendar_gap_days={str(k):v for k,v in sorted(gaps.items())},
                maximum_calendar_gap_days=max(gaps,default=None),
                scope='Observed saved dates. Calendar gaps do not prove missing exchange sessions.')


def _stock_sessions(db,checkpoint):
    """Valid adjusted closes against valid SPY sessions, from the research facts of a daily connection."""
    examples=[];totals=Counter();seen=set()
    query='''SELECT p.symbol,MIN(p.day),MAX(p.day),COUNT(s.day),COUNT(*)
             FROM research.stock_days p LEFT JOIN research.market_days s ON s.day=p.day AND s.spy IS NOT NULL
             WHERE p.adjusted IS NOT NULL GROUP BY p.symbol ORDER BY p.symbol'''
    for symbol,first,last,matched,observed in db.execute(query):
        checkpoint();seen.add(symbol)
        expected=db.execute('SELECT COUNT(*) FROM research.market_days WHERE spy IS NOT NULL AND day BETWEEN ? AND ?',(first,last)).fetchone()[0]
        missing=expected-matched
        if missing<0:raise ValueError('Invalid stock/session coverage.')
        totals['symbols_with_adjusted_prices']+=1;totals['observed_adjusted_rows']+=observed
        totals['available_spy_sessions_within_stock_spans']+=expected;totals['observed_internal_omissions']+=missing
        if missing:
            totals['symbols_with_internal_omissions']+=1
            examples.append(dict(symbol=symbol,first=first,last=last,available_spy_sessions=expected,observed=matched,missing=missing))
    examples=sorted(examples,key=lambda v:(-v['missing'],v['symbol']))[:20]
    totals['symbols_without_adjusted_prices']=len(facts.BookFacts(db).cached()-seen)
    return dict(totals=totals,largest_examples=examples,
                scope='Omissions relative to saved SPY sessions within each stock observed span. Legitimate nontrading intervals are not classified as repairable gaps. Leading/trailing unavailability is excluded.')


def _source_histories(raw):
    # The prepared primary key can retain only one row per symbol/fiscal date.
    # Pre-price membership must use the same full saved variants as research.
    records,invalid=r.cache_assets.financial_records(raw/'metrics.jsonl')
    if invalid:raise ValueError('Invalid annual financial records.')
    universe={row['symbol']:row for row in json.loads((raw/'universe.json').read_bytes())}
    return books.pools(books.statements(records,universe))


def _coverage(db,spy_payload,treasury_payload,checkpoint,histories=None):
    """The report of one daily connection that attaches research."""
    inventory=json.loads(db.execute("SELECT value FROM research.metadata WHERE key='prices'").fetchone()[0])
    histories=facts.BookFacts(db).reports() if histories is None else histories
    stock_files={symbol:market.cache_path_for(symbol).name in inventory for symbol in histories[0]}
    return dict(version=4,
        companies=db.execute('SELECT COUNT(*) FROM research.companies').fetchone()[0],
        financial_symbols=len(histories[0]),accepted_price_files=len(inventory),
        financial_symbols_without_price_files=sum(not v for v in stock_files.values()),
        spy=series_summary(spy_payload,'adjClose',positive=True),treasury=series_summary(treasury_payload,'month3'),
        stock_sessions=_stock_sessions(db,checkpoint),
        daily_books=book_store.counts(db),
        limits=['Counts describe the cached inputs and ordinary eligibility, not the full US universe.',
                'No classification of new early stops or bankruptcy review is implied.'])


def report(research_path=None,daily_path=None,*,checkpoint=lambda:None):
    """Report coverage from current ordinary prepared data.

    Version 4 reads the stock sessions from the research facts and counts the
    book store's books, pools and rows (the latest book included), through one
    daily connection (daily.connect checks its binding and each price file's
    stamps). It replaces version 1, which counted January books and named a
    report digest. Missing observations remain explicit.
    """
    research_path=Path(research_path or r.DATABASE);daily_path=Path(daily_path or daily_inputs.DATABASE)
    with cache_access.access(),closing(daily_inputs.connect(daily_path,research_path)) as db:
        r.identity(db,'research',prices=True)
        spy=json.loads((r.RAW/'spy-div.json').read_bytes());treasury=json.loads((r.RAW/'treasury.json').read_bytes())
        return _coverage(db,spy,treasury,checkpoint,_source_histories(r.RAW))
