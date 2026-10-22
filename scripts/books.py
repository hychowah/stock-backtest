"""Financial policy shared by January and arbitrary dated books.

Price adapters return (date, positive price) or None within the given tolerance.
Storage, calendar planning and SQL insertion stay outside this module.
"""
import run


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


def snapshot(statement, entry_day, exit_day, lookup, bankruptcy):
    """Rescale report equity at entry and retain stopped holdings at last price."""
    fiscal_px=lookup(statement['fiscal'],'price',False,7)
    entry_px=lookup(entry_day,'price',True,4)
    if fiscal_px is None or entry_px is None:
        return None
    cap=statement['market_cap']*(entry_px[1]/fiscal_px[1])
    ev=cap+(statement['enterprise']-statement['market_cap'])
    if ev<=0 or cap<=0:
        return None
    ebitda=statement['yield']*statement['enterprise']
    start=lookup(entry_px[0],'adjusted',True,4)
    if start is None or start[0]>=exit_day:
        return None
    end=lookup(exit_day,'adjusted',False,10)
    status='Scheduled exit' if exit_day.year>entry_day.year else 'Marked to date'
    if end is None:
        end=lookup(exit_day,'adjusted',False,100000)
        if end is None or end[0]<start[0]:
            return None
        status='Last available price'
    if end[0]<start[0]:return None
    ret=-1. if bankruptcy else end[1]/start[1]-1
    if bankruptcy:
        status='Bankruptcy'
    return [str(statement['fiscal']),str(start[0]),str(end[0]),cap,ev,ebitda,ebitda/ev,ev/ebitda,ret,status]

