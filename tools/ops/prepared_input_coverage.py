"""Read-only coverage evidence for an ordinary independently prepared workspace."""
from backtest.inputs import daily as daily_inputs, market
from backtest.financial import rules

from collections import Counter
from contextlib import ExitStack, closing
from datetime import date
import json
from pathlib import Path
import sqlite3

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


def _stock_sessions(daily,checkpoint):
    examples=[];totals=Counter();seen=set()
    query='''SELECT p.symbol,MIN(p.day),MAX(p.day),COUNT(s.day),COUNT(*)
             FROM prices p LEFT JOIN sessions s ON s.day=p.day
             WHERE p.adjusted IS NOT NULL GROUP BY p.symbol ORDER BY p.symbol'''
    for symbol,first,last,matched,observed in daily.execute(query):
        checkpoint();seen.add(symbol)
        expected=daily.execute('SELECT COUNT(*) FROM sessions WHERE day BETWEEN ? AND ?',(first,last)).fetchone()[0]
        missing=expected-matched
        if missing<0:raise ValueError('Invalid stock/session coverage.')
        totals['symbols_with_adjusted_prices']+=1;totals['observed_adjusted_rows']+=observed
        totals['available_spy_sessions_within_stock_spans']+=expected;totals['observed_internal_omissions']+=missing
        if missing:
            totals['symbols_with_internal_omissions']+=1
            examples.append(dict(symbol=symbol,first=first,last=last,available_spy_sessions=expected,observed=matched,missing=missing))
    examples=sorted(examples,key=lambda v:(-v['missing'],v['symbol']))[:20]
    totals['symbols_without_adjusted_prices']=len(daily_inputs.cached_symbols(daily)-seen)
    return dict(totals=totals,largest_examples=examples,
                scope='Omissions relative to saved SPY sessions within each stock observed span. Legitimate nontrading intervals are not classified as repairable gaps. Leading/trailing unavailability is excluded.')


def _source_histories(raw):
    # The prepared primary key can retain only one row per symbol/fiscal date.
    # Pre-price membership must use the same full saved variants as research.
    records,invalid=r.cache_assets.financial_records(raw/'metrics.jsonl')
    if invalid:raise ValueError('Invalid annual financial records.')
    universe={row['symbol']:row for row in json.loads((raw/'universe.json').read_bytes())}
    return books.pools(books.statements(records,universe))


def _coverage(research,daily,spy_payload,treasury_payload,checkpoint,histories=None):
    metadata={row[0]:json.loads(row[1]) for row in research.execute('SELECT key,value FROM metadata')}
    inventory=metadata['prices'];histories=daily_inputs.histories(daily) if histories is None else histories
    stock_files={symbol:market.cache_path_for(symbol).name in inventory for symbol in histories[0]}
    return dict(version=2,
        companies=research.execute('SELECT COUNT(*) FROM companies').fetchone()[0],
        financial_symbols=len(histories[0]),accepted_price_files=len(inventory),
        financial_symbols_without_price_files=sum(not v for v in stock_files.values()),
        spy=series_summary(spy_payload,'adjClose',positive=True),treasury=series_summary(treasury_payload,'month3'),
        stock_sessions=_stock_sessions(daily,checkpoint),
        daily_books={t:daily.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('periods','snapshots','period_pools')},
        limits=['Counts describe the cached inputs and ordinary eligibility, not the full US universe.',
                'No classification of new early stops or bankruptcy review is implied.'])


def report(research_path=None,daily_path=None,*,checkpoint=lambda:None):
    """Report coverage from current ordinary prepared data.

    Version 2 has no January book counts or report digest. Missing
    observations remain explicit.
    """
    research_path=Path(research_path or r.DATABASE);daily_path=Path(daily_path or daily_inputs.DATABASE)
    with cache_access.access(),ExitStack() as stack:
        research=stack.enter_context(closing(r.connect(research_path,full_prices=True)))
        daily=stack.enter_context(closing(sqlite3.connect(daily_path.resolve().as_uri()+'?mode=ro',uri=True)))
        daily.row_factory=sqlite3.Row
        saved=json.loads(daily.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()[0])
        if saved!=daily_inputs.fingerprint(research_path):raise ValueError('Daily cache changed. Run ordinary preparation.')
        spy=json.loads((r.RAW/'spy-div.json').read_bytes());treasury=json.loads((r.RAW/'treasury.json').read_bytes())
        result=_coverage(research,daily,spy,treasury,checkpoint,_source_histories(r.RAW))
        result['price_binding']=r.prepared_price_binding(research_path)
        return result
