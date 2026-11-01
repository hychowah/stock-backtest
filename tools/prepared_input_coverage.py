"""Read-only coverage evidence for an ordinary independently prepared workspace."""
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.inputs import daily as daily_inputs, market
from backtest.financial import rules

import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0,str(_PackagePath(__file__).resolve().parents[1]))
from backtest import screening

from collections import Counter
from contextlib import ExitStack, closing
from datetime import date
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE/'scripts'))
from backtest.inputs import research as r
from backtest.engines.original import schedules as s
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


def _omission(daily,symbol,statement,entry,exit_day,year):
    observations=[]
    def lookup(day,column,forward,slack):
        found=daily_inputs.price(daily,symbol,day,column,forward,slack)
        observations.append((column,forward,slack,found));return found
    row=books.snapshot(statement,entry,exit_day,lookup,(year,symbol) in r.rules.BANKRUPT)
    if row is not None:return 'unclassified_financial_or_preparation_exclusion'
    if any(v[3] is None for v in observations[:2]):return 'required_valuation_observation_absent'
    if len(observations)>2 and observations[2][3] is None:return 'required_adjusted_entry_absent'
    if observations and observations[-1][:3]==('adjusted',False,100000):
        last=observations[-1][3];start=observations[2][3]
        if last is None or start is not None and last[0]<start[0]:return 'required_adjusted_exit_window_absent'
    return 'unclassified_financial_or_preparation_exclusion'


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
    periods={row['year']:dict(row) for row in research.execute('SELECT * FROM periods')}
    snapshots={(pool,year):count for pool,year,count in research.execute('SELECT pool,year,COUNT(*) FROM snapshots GROUP BY pool,year')}
    stock_files={symbol:market.cache_path_for(symbol).name in inventory for symbol in histories[0]}
    years=[]
    for year in range(1996,2027):
        checkpoint();period=periods.get(year);counts={}
        statements,ranks=books.candidates(histories,date.fromisoformat(period['entry'])) if period else ({'legacy':{},'cached':{}},{})
        for pool in ('legacy','cached'):
            filtered=screening.historical(research,first=year,last=year,pool=pool,rank_to=5000)
            selected=screening.historical(research,first=year,last=year,pool=pool)
            omitted=Counter();eligible=statements[pool]
            if pool=='legacy':eligible={symbol:row for symbol,row in eligible.items() if symbol in ranks}
            saved={row[0] for row in research.execute('SELECT symbol FROM snapshots WHERE pool=? AND year=?',(pool,year))}
            for symbol,statement in eligible.items():
                checkpoint()
                if symbol in saved:continue
                if not stock_files.get(symbol):omitted['price_file_absent']+=1
                else:omitted[_omission(daily,symbol,statement,date.fromisoformat(period['entry']),date.fromisoformat(period['exit']),year)]+=1
            counts[pool]=dict(pre_price_candidates=period[pool+'_candidates'] if period else None,
                usable_snapshots=snapshots.get((pool,year),0),
                default_eligible=len(filtered) if len(filtered)<5000 else None,
                default_eligible_lower_bound=len(filtered),default_eligible_exact=len(filtered)<5000,
                selected_holdings=len(selected),requested_holdings=50,omitted_pre_price_candidates=dict(omitted))
        years.append(dict(year=year,prepared_period=period is not None,
                          entry=period['entry'] if period else None,exit=period['exit'] if period else None,pools=counts))
    required=sorted({p[k] for p in periods.values() for k in ('entry','exit')})
    spy_dates={row[0] for row in daily.execute('SELECT day FROM sessions')}
    missing_treasury=[p['entry'] for p in periods.values() if daily.execute('SELECT 1 FROM treasuries WHERE day<=? LIMIT 1',(p['entry'],)).fetchone() is None]
    return dict(version=1,through=metadata['historical_through'],years=years,
        companies=research.execute('SELECT COUNT(*) FROM companies').fetchone()[0],
        financial_symbols=len(histories[0]),accepted_price_files=len(inventory),
        financial_symbols_without_price_files=sum(not v for v in stock_files.values()),
        spy=series_summary(spy_payload,'adjClose',positive=True),treasury=series_summary(treasury_payload,'month3'),
        required_spy_dates_absent=[d for d in required if d not in spy_dates],
        required_treasury_asof_absent=missing_treasury,
        stock_sessions=_stock_sessions(daily,checkpoint),
        daily_books={t:daily.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('periods','snapshots','period_pools')},
        baseline_revision=metadata.get('baseline_revision'),baseline_report_sha256=metadata.get('baseline_report_sha'),
        limits=['Counts describe the cached inputs and ordinary eligibility, not the full US universe.',
                'Candidate-minus-snapshot differences include valuation and financial exclusions.',
                'Eligible counts reaching the ordinary 5000-rank limit are lower bounds.',
                'No classification of new early stops or bankruptcy review is implied.'])


def report(research_path=None,daily_path=None,*,checkpoint=lambda:None):
    """Report coverage from current ordinary prepared data.

    Candidate, usable snapshot and selected holding counts describe different
    populations. Missing observations remain explicit.
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
        result['report_sha256']=hashlib.sha256((r.RESULTS/'summary-exits.txt').read_bytes()).hexdigest()
        return result
