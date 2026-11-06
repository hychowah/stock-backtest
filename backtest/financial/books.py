"""Financial policy shared by latest and dated books, and the one book-row rule.

book() computes one pool of a latest or a dated book from prepared facts
through one price-lookup interface. Price adapters return (date, positive
price) or None within the given tolerance. Storage, calendar planning and SQL
insertion stay outside this module. A change to book policy must pass the
development check (python3 scripts/check.py) on the real-data bench.
"""
from datetime import timedelta

from backtest.financial import metrics
from backtest.financial import rules as run

# Forward price lookups accept a session up to ENTRY_SLACK days after their
# anchor: the entry valuation after the entry day, then the buy price after the
# valuation day. No book reads a price later than max(exit, entry+FORWARD_REACH).
ENTRY_SLACK=4
FORWARD_REACH=timedelta(days=2*ENTRY_SLACK)


def statements(records, universe):
    """Apply annual eligibility once for preparation and cache coverage groups.

    Records must come from cache_assets.financial_records. Missing financial
    fields exclude a report; malformed JSON records are handled at that boundary.
    """
    broad={}
    for symbol,record in records.items():
        if symbol not in universe:continue
        rows=[]
        for report in record['rows']:
            fiscal=run.parse_day(report.get('date'))
            cap,ev,multiple=map(run.num,[report.get('marketCap'),report.get('enterpriseValue'),report.get('evToEBITDA')])
            if fiscal is None or any(v is None or v<=0 for v in (cap,ev,multiple)) or str(report.get('reportedCurrency') or 'USD').upper()!='USD':continue
            rows.append(dict(fiscal=fiscal,known=fiscal+run.LAG,market_cap=cap,enterprise=ev,ebitda=ev/multiple,**{'yield':1/multiple}))
        if rows:broad[symbol]=sorted(rows,key=lambda row:row['fiscal'])
    return broad


def pools(broad):
    """Original eligibility is report-size filtered before choosing a report."""
    legacy={symbol:[s for s in rows if s['market_cap']>=run.MIN_MARKET_CAP and s['enterprise']>=run.MIN_EV] for symbol,rows in broad.items()}
    return broad,{symbol:rows for symbol,rows in legacy.items() if rows}


def candidates(books, day):
    """Choose available reports and the original single-year pre-price buffer."""
    broad,legacy=books
    statements={pool:{symbol:s for symbol,rows in book.items() if (s:=run.latest_statement(rows,day)) is not None} for pool,book in [('cached',broad),('legacy',legacy)]}
    ranks={symbol:i for i,symbol in enumerate(sorted(statements['legacy'],key=lambda s:statements['legacy'][s]['yield'],reverse=True)[:run.BUFFER],1)}
    return statements,ranks


def eligible(pool, cap, ev):
    return cap>0 and ev>0 and (pool!='legacy' or (cap>=run.MIN_MARKET_CAP and ev>=run.MIN_EV))


def ebitda_yield_and_multiple(ebitda, enterprise_value):
    """Return yield then multiple from entry valuation, with independent rounding."""
    return ebitda / enterprise_value, enterprise_value / ebitda


def holding(statement, entry_day, exit_day, lookup, bankruptcy=False):
    """One book row of a company, or None: the book-row rule of latest and dated books.

    Report equity is rescaled at entry. A latest holding (exit_day None) is
    valued at the entry session itself, never at a stopped stock's old price,
    and has no exit, return or status. A dated holding enters up to ENTRY_SLACK
    days later and keeps a stopped stock at its last price. The status records
    only how the holding exited: 'Scheduled exit' for a normal exit, 'Last
    available price' or 'Bankruptcy'. A stored book serves every schedule with
    the same entry and exit, so the run, not the book, labels its final mark
    (portfolio_results.evaluate_into).

    Return [fiscal, known, entry, entry price, exit, cap, EV, EBITDA, yield,
    multiple, return, status].
    """
    latest=exit_day is None
    slack=0 if latest else ENTRY_SLACK
    valuation=entry_valuation(statement,entry_day,lookup,slack)
    if valuation is None:
        return None
    fiscal_px,entry_px,cap,ev,ebitda=valuation
    start=lookup(entry_px[0],'adjusted',True,slack)
    if start is None:
        return None
    if latest:
        if ebitda<=0:return None
        end,ret,status=None,None,None
    else:
        if start[0]>=exit_day:return None
        end=lookup(exit_day,'adjusted',False,10)
        status='Scheduled exit'
        if end is None:
            end=lookup(exit_day,'adjusted',False,100000)
            if end is None or end[0]<start[0]:
                return None
            status='Last available price'
        if end[0]<start[0]:return None
        ret=-1. if bankruptcy else end[1]/start[1]-1
        if bankruptcy:
            status='Bankruptcy'
    return [str(statement['fiscal']),str(statement['known']),str(start[0]),start[1],None if end is None else str(end[0]),
            cap,ev,ebitda,*ebitda_yield_and_multiple(ebitda,ev),ret,status]


def snapshot(statement, entry_day, exit_day, lookup, bankruptcy):
    """A dated holding() in the daily cache's row shape (no known date or entry price)."""
    row=holding(statement,entry_day,exit_day,lookup,bankruptcy)
    return None if row is None else [row[0],row[2],*row[4:]]


def book(reports, entry, exit_day, pool, cached, facts, checkpoint=lambda: None):
    """Compute one pool of a book: its record, rows, ranking pairs and filter values.

    This is the admission rule of a book: an available report (with the legacy
    pre-price buffer), cached prices, holding() and pool eligibility. reports
    is (broad, legacy) from pools(); a latest book (exit_day None) passes listed
    companies only. cached holds the companies with a saved price file.

    facts is the one price-lookup interface over prepared facts:
    price(symbol, day, column, forward, slack) with column 'price' or
    'adjusted', spy(day) on an exact session, treasury(day) (3-month, as a
    fraction, on or before), ten_year(day) (percent, on or before) and
    legacy_annual(symbol). Books read legacy annual values and the 10-year
    yield only here.
    """
    statements,ranks=candidates(reports,entry)
    treasury=facts.treasury(entry)
    treasury=0. if treasury is None else treasury
    ten_year=facts.ten_year(entry)
    rows,pairs,filters=[],[],[]
    for symbol,statement in statements[pool].items():
        checkpoint()
        if symbol not in cached or (pool=='legacy' and symbol not in ranks):continue
        def lookup(day,column,forward,slack,symbol=symbol):
            return facts.price(symbol,day,column,forward,slack)
        row=holding(statement,entry,exit_day,lookup,exit_day is not None and run.bankrupt(symbol,entry,exit_day))
        if row is None:continue
        fiscal,known,start,price,end,cap,ev,ebitda,yield_value,multiple,ret,status=row
        if not eligible(pool,cap,ev):continue
        rows.append((symbol,ranks.get(symbol),fiscal,known,start,price,end,cap,ev,ebitda,yield_value,multiple,
                     yield_spread(yield_value,treasury),ret,status))
        observation=dict(symbol=symbol,fiscal=fiscal,market_cap=cap,enterprise_value=ev,ev_ebitda=multiple,ebitda_yield=yield_value)
        history=[dict(report,fiscal=str(report['fiscal']),known=str(report['known'])) for report in reports[0][symbol]]
        evaluated=metrics.evaluate(observation,history)
        values=metrics.filter_values(observation,evaluated,entry,lookup,facts.legacy_annual(symbol),ten_year)
        filters.extend((symbol,key,value) for key,value in values.items())
        pairs.extend((symbol,metric,multiple,value) for metric,(multiple,value) in evaluated.items())
    spy=None if exit_day is None else benchmark_return(facts.spy(entry),facts.spy(exit_day))
    exit_text=None if exit_day is None else str(exit_day)
    return dict(entry=str(entry),exit=exit_text,pool=pool,
                book=(str(entry),exit_text,spy,treasury,len(ranks),len(statements['cached'])),
                rows=rows,metrics=pairs,filters=filters)


def entry_valuation(statement, entry_day, lookup, slack=ENTRY_SLACK):
    """Return fiscal and entry observations, cap, EV and EBITDA without an exit.

    The entry price is the first on or after entry_day within slack days; a
    latest book passes 0, the exact session.
    """
    fiscal_px=lookup(statement['fiscal'],'price',False,7)
    entry_px=lookup(entry_day,'price',True,slack)
    if fiscal_px is None or entry_px is None:
        return None
    cap=statement['market_cap']*(entry_px[1]/fiscal_px[1])
    ev=cap+(statement['enterprise']-statement['market_cap'])
    if ev<=0 or cap<=0:
        return None
    ebitda=statement['yield']*statement['enterprise']
    return fiscal_px,entry_px,cap,ev,ebitda


def benchmark_return(entry_price, exit_price):
    return exit_price/entry_price-1


def yield_spread(earnings_yield, treasury_yield):
    return earnings_yield-treasury_yield
