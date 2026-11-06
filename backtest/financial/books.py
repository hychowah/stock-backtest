"""Financial policy shared by latest and dated books: one admission rule, one book loop.

Screen(day, facts) is the admission state of one entry day, and
Screen.decide() the per-company decision, with its denial reason, of an open
(latest) book, a dated book and a formula root (fact_view.View). book() computes
one pool of a book from prepared facts through the facts port
(facts.BookFacts); daily preparation writes the latest book and
schedules.prepare_period and the book workers write the dated books with it.
Price lookups return (date, positive dividend-adjusted close) or None within
the given tolerance. Storage, calendar planning and SQL insertion stay outside
this module. A change to book policy must pass the development check
(python3 scripts/check.py) on the real-data bench.
"""
from datetime import timedelta
import math

from backtest.financial import metrics
from backtest.financial import rules as run

# The entry price is the first session up to ENTRY_SLACK days after the entry
# day. No book reads a price later than max(exit, entry+FORWARD_REACH).
ENTRY_SLACK=4
FORWARD_REACH=timedelta(days=ENTRY_SLACK)

# The denial reasons of Screen.decide, in gate order. A company has a book
# row, and a formula root is admitted, only when every gate passes.
REASONS=(
    'UNKNOWN_COMPANY',        # not a saved company
    'NOT_LISTED',             # open book only: the company is not listed now
    'NO_ELIGIBLE_REPORT',     # no report known before the entry day within MAX_AGE (legacy: none above the report floors)
    'OUTSIDE_LEGACY_BUFFER',  # legacy pool: outside the BUFFER highest report yields
    'MISSING_CACHED_PRICES',  # no saved price file
    'MISSING_PRICE',          # no price within 7 days before the fiscal date, or no entry session within the slack
    'NONPOSITIVE_VALUATION',  # the rescaled market cap or EV is not positive
    'NONFINITE_RESULT',       # the rescaled valuation is not finite
    'INELIGIBLE_VALUATION',   # below the pool's size floors at entry
    'ENTRY_NOT_BEFORE_EXIT',  # dated: the entry session is on or after the exit day
    'MISSING_EXIT_PRICE',     # dated: no exit price on or after the entry session
)


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


def admit(statement, day, lookup, slack):
    """(reason, valuation) of the entry valuation, the one valuation gate.

    Report equity is rescaled at entry: the fiscal price is the last on or
    before the fiscal date within 7 days, the entry price the first on or after
    day within slack days. lookup(day, forward, slack) reads one company's
    adjusted closes; both lookups always run, so an explanation records both.
    valuation is (fiscal price, entry price, cap, EV, EBITDA), or None with a
    reason: MISSING_PRICE, NONPOSITIVE_VALUATION or NONFINITE_RESULT.
    """
    fiscal_px=lookup(statement['fiscal'],False,7)
    entry_px=lookup(day,True,slack)
    if fiscal_px is None or entry_px is None:
        return 'MISSING_PRICE',None
    cap=statement['market_cap']*(entry_px[1]/fiscal_px[1])
    ev=cap+(statement['enterprise']-statement['market_cap'])
    if ev<=0 or cap<=0:
        return 'NONPOSITIVE_VALUATION',None
    ebitda=statement['yield']*statement['enterprise']
    if not all(math.isfinite(value) for value in (cap,ev,ebitda)):
        return 'NONFINITE_RESULT',None
    return None,(fiscal_px,entry_px,cap,ev,ebitda)


def close(start, exit_day, lookup, bankruptcy):
    """(reason, (exit price, return, status)) of a dated holding bought at start.

    A stopped stock keeps its last price. The status records only how the
    holding exited: 'Scheduled exit', 'Last available price' or 'Bankruptcy'.
    A stored book serves every schedule with the same entry and exit, so the
    run, not the book, labels its final mark (portfolio_results.evaluate_into).
    """
    if start[0]>=exit_day:
        return 'ENTRY_NOT_BEFORE_EXIT',None
    end=lookup(exit_day,False,10)
    status='Scheduled exit'
    if end is None:
        end=lookup(exit_day,False,100000)
        status='Last available price'
    if end is None or end[0]<start[0]:
        return 'MISSING_EXIT_PRICE',None
    if bankruptcy:
        return None,(end,-1.,'Bankruptcy')
    return None,(end,end[1]/start[1]-1,status)


class Screen:
    """The admission state of one entry day of a book or a formula root.

    day must be a saved SPY session on or after rules.FIRST_DAY: the one date
    rule of books and formula roots. The open book (the latest book, with no
    exit) ranks listed companies only and values each at the exact session;
    every other screen enters up to ENTRY_SLACK days later. statements[pool]
    and ranks are candidates() of that day. facts is the facts port
    (facts.BookFacts): reports(), cached(), companies() and price().
    """
    def __init__(self, day, facts, *, open_book=False):
        if day<run.FIRST_DAY or facts.spy(day) is None:
            raise ValueError(f'The entry day is not a saved SPY session from {run.FIRST_DAY}.')
        self.day,self.facts,self.open=day,facts,open_book
        self.slack=0 if open_book else ENTRY_SLACK
        reports=facts.reports()
        if open_book:
            companies=facts.companies()
            reports=tuple({symbol:rows for symbol,rows in pool.items() if companies.get(symbol)} for pool in reports)
        self.statements,self.ranks=candidates(reports,day)

    def decide(self, symbol, pool, exit_day=None):
        """(holding, None) or (None, reason) of one company: every gate, in REASONS order.

        Without exit_day this is the admission alone, as the open book and a
        formula root need. holding is dict(statement, rank, fiscal_price, entry,
        market_cap, enterprise_value, ebitda, exit, return_value, status), with
        fiscal_price, entry and exit as (day, adjusted close).
        """
        listed=self.facts.companies().get(symbol)
        if listed is None:
            return None,'UNKNOWN_COMPANY'
        if self.open and not listed:
            return None,'NOT_LISTED'
        statement=self.statements[pool].get(symbol)
        if statement is None:
            return None,'NO_ELIGIBLE_REPORT'
        rank=self.ranks.get(symbol)
        if pool=='legacy' and rank is None:
            return None,'OUTSIDE_LEGACY_BUFFER'
        if symbol not in self.facts.cached():
            return None,'MISSING_CACHED_PRICES'
        def lookup(day,forward,slack):
            return self.facts.price(symbol,day,forward,slack)
        reason,valuation=admit(statement,self.day,lookup,self.slack)
        if reason is not None:
            return None,reason
        fiscal_px,start,cap,ev,ebitda=valuation
        if not eligible(pool,cap,ev):
            return None,'INELIGIBLE_VALUATION'
        holding=dict(statement=statement,rank=rank,fiscal_price=fiscal_px,entry=start,market_cap=cap,
                     enterprise_value=ev,ebitda=ebitda,exit=None,return_value=None,status=None)
        if exit_day is not None:
            reason,ending=close(start,exit_day,lookup,run.bankrupt(symbol,self.day,exit_day))
            if reason is not None:
                return None,reason
            holding.update(zip(('exit','return_value','status'),ending))
        return holding,None


def book(entry, exit_day, pool, facts, checkpoint=lambda: None):
    """Compute one pool of a book: its record, rows, ranking pairs and filter values.

    exit_day None is the open (latest) book. The rows are the companies with an
    available report that Screen.decide admits. facts is the facts port
    (facts.BookFacts); the book also reads spy(day) on an exact session,
    treasury(day) (3-month, as a fraction, on or before), ten_year(day)
    (percent, on or before) and legacy_annual(symbol). candidates counts the
    cached-pool reports of the entry day.
    """
    screen=Screen(entry,facts,open_book=exit_day is None)
    treasury=facts.treasury(entry)
    treasury=0. if treasury is None else treasury
    ten_year=facts.ten_year(entry)
    broad=facts.reports()[0]
    rows,pairs,filters=[],[],[]
    for symbol in screen.statements[pool]:
        checkpoint()
        held,_=screen.decide(symbol,pool,exit_day)
        if held is None:continue
        statement,cap,ev,ebitda,end=held['statement'],held['market_cap'],held['enterprise_value'],held['ebitda'],held['exit']
        fiscal=str(statement['fiscal'])
        yield_value,multiple=ebitda_yield_and_multiple(ebitda,ev)
        rows.append((symbol,held['rank'],fiscal,str(statement['known']),str(held['entry'][0]),held['entry'][1],
                     None if end is None else str(end[0]),cap,ev,ebitda,yield_value,multiple,
                     yield_spread(yield_value,treasury),held['return_value'],held['status']))
        observation=dict(symbol=symbol,fiscal=fiscal,market_cap=cap,enterprise_value=ev,ev_ebitda=multiple,ebitda_yield=yield_value)
        history=[dict(report,fiscal=str(report['fiscal']),known=str(report['known'])) for report in broad[symbol]]
        evaluated=metrics.evaluate(observation,history)
        def lookup(day,forward,slack,symbol=symbol):
            return facts.price(symbol,day,forward,slack)
        values=metrics.filter_values(observation,evaluated,entry,lookup,facts.legacy_annual(symbol),ten_year)
        filters.extend((symbol,key,value) for key,value in values.items())
        pairs.extend((symbol,metric,multiple,value) for metric,(multiple,value) in evaluated.items())
    spy=None if exit_day is None else benchmark_return(facts.spy(entry),facts.spy(exit_day))
    return dict(entry=str(entry),exit=None if exit_day is None else str(exit_day),pool=pool,spy=spy,
                candidates=len(screen.statements['cached']),rows=rows,metrics=pairs,filters=filters)


def benchmark_return(entry_price, exit_price):
    return exit_price/entry_price-1


def yield_spread(earnings_yield, treasury_yield):
    return earnings_yield-treasury_yield
