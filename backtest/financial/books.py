"""Financial policy shared by latest and dated books: one admission rule, one book loop.

Screen(day, facts) is the admission state of one entry day, and
Screen.decide() the per-company decision, with its denial reason, of an open
(latest) book, a dated book and a formula root (fact_view.View). book() computes
one pool of a book from prepared facts through the facts port
(facts.BookFacts); daily preparation writes the latest book and
schedules.prepare_period and the book workers write the dated books with it.
owner_values() is the per-company owner-value composition of a book row and
of a formula context without a stored book. valuation_days() folds the
running valuation sums that daily preparation stores and owner_values reads.
Price lookups return (date, positive dividend-adjusted close) or None within
the given tolerance. Storage, calendar planning and SQL
insertion stay outside this module. A change to book policy must pass the development check
(python3 scripts/check.py) on the real-data bench.
"""
from bisect import bisect_right
import math
from datetime import timedelta

from backtest.financial import metrics
from backtest.financial import rules as run

# Historical entry prices can roll forward by four calendar days.
ENTRY_SLACK=4


def affected_entries(changes, facts):
    """First affected entry per company; shared changes reach their actual users.

    These conservative tails include entry roll-forward and later lookbacks.
    A company revision never invalidates another company's numerical rows.
    """
    code=facts.market;companies=facts.companies();affected={}
    def note(symbol,day):
        text=str(day)
        if symbol not in affected or text<affected[symbol]:affected[symbol]=text
    def shared(day):
        for symbol in companies:note(symbol,day)
    for symbol,markets in changes['companies'].items():
        if code in markets:note(symbol,run.FIRST_DAY)
    for symbol,day in changes['prices'].items():
        if symbol in companies:note(symbol,run.parse_day(day)-timedelta(days=ENTRY_SLACK))
    for kind in ('annual','reports'):
        for symbol,known in changes[kind].items():
            if symbol in companies:note(symbol,run.parse_day(known)+timedelta(days=1))
    if changes['treasury'] is not None:
        shared(run.parse_day(changes['treasury'])+timedelta(days=0 if code=='us' else 1))
    if code!='us':
        if code in changes['sessions']:
            shared(run.parse_day(changes['sessions'][code])-timedelta(days=ENTRY_SLACK))
        if changes['fx']:
            users=facts.currency_users()
            for currency,day in changes['fx'].items():
                if currency=='USD':continue
                for symbol in users.get(currency,()):note(symbol,run.parse_day(day)-timedelta(days=ENTRY_SLACK))
    return affected

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


def rescaled_cap(statement, fiscal_px, entry_px):
    """The report's market cap rescaled from the fiscal price to the entry price: admit() and valuation_days()."""
    return statement['market_cap']*(entry_px[1]/fiscal_px[1])


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
    cap=rescaled_cap(statement,fiscal_px,entry_px)
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
    An entry sheet serves many exits. The run labels its final mark
    (portfolio_results.evaluate_into).
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

    day must be a saved market session on or after rules.FIRST_DAY: the one date
    rule of books and formula roots. The open book (the latest book, with no
    exit) ranks listed companies only and values each at the exact session;
    every other screen enters up to ENTRY_SLACK days later. statements[pool]
    and ranks are candidates() of that day. facts is the facts port
    (facts.BookFacts): reports(), cached(), companies() and price().
    """
    def __init__(self, day, facts, *, open_book=False):
        if day<run.FIRST_DAY or (facts.spy(day) is None if getattr(facts,'market','us')=='us' else not facts.session(day)):
            session='SPY' if getattr(facts,'market','us')=='us' else 'local market'
            raise ValueError(f'The entry day is not a saved {session} session from {run.FIRST_DAY}.')
        self.day,self.facts,self.open=day,facts,open_book
        self.slack=0 if open_book else ENTRY_SLACK
        reports=facts.reports() if getattr(facts,'market','us')=='us' else facts.reports(day)
        if open_book:
            companies=facts.companies()
            reports=tuple({symbol:rows for symbol,rows in pool.items() if companies.get(symbol)} for pool in reports)
        self.statements,self.ranks=candidates(reports,day)

    def decide(self, symbol, pool):
        """(holding, None) or (None, reason) of one company: every gate, in REASONS order.

        This admits an entry only. The run restricts actual entry before exit
        before ranking, then closes selected rows. fiscal_price and entry
        are (day, adjusted close) pairs.
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
        usd_entry=start
        if getattr(self.facts,'market','us')!='us':
            value=self.facts.convert(start[1],self.facts.quote_currency(symbol),start[0])
            if value is None:return None,'MISSING_PRICE'
            usd_entry=start[0],value
        return dict(statement=statement,rank=rank,fiscal_price=fiscal_px,entry=start,usd_entry=usd_entry,market_cap=cap,
                    enterprise_value=ev,ebitda=ebitda),None


def book(entry, pool, facts, checkpoint=lambda: None, *, latest=False, symbols=None):
    """Build one entry/pool sheet, without exit prices or future returns.

    latest serves the exact-session, listed-only screen. Historical sheets
    use dated admission and can serve every later exit. A restricted repair
    retains full-screen admission/ranking metadata while pricing only its symbols.
    """
    screen=Screen(entry,facts,open_book=latest)
    treasury=facts.treasury(entry)
    treasury=0. if treasury is None else treasury
    ten_year=facts.ten_year(entry)
    rows,pairs,filters=[],[],[]
    wanted=None if symbols is None else set(symbols)
    for symbol in screen.statements[pool]:
        if wanted is not None and symbol not in wanted:continue
        checkpoint()
        held,_=screen.decide(symbol,pool)
        if held is None:continue
        statement,cap,ev,ebitda=held['statement'],held['market_cap'],held['enterprise_value'],held['ebitda']
        fiscal=str(statement['fiscal'])
        yield_value,multiple,evaluated,values=owner_values(symbol,fiscal,entry,cap,ev,ebitda,facts,ten_year)
        rows.append((symbol,held['rank'],fiscal,str(statement['known']),str(held['usd_entry'][0]),held['usd_entry'][1],
                     cap,ev,ebitda,yield_value,multiple,yield_spread(yield_value,treasury)))
        filters.extend((symbol,key,value) for key,value in values.items())
        pairs.extend((symbol,metric,multiple,value) for metric,(multiple,value) in evaluated.items())
    result=dict(entry=str(entry),latest=latest,pool=pool,candidates=len(screen.statements['cached']),
                rows=rows,metrics=pairs,filters=filters)
    if getattr(facts,'market','us')!='us':result['market']=facts.market
    if wanted is not None:result['ranks']=screen.ranks
    return result


def owner_values(symbol, fiscal, day, cap, ev, ebitda, facts, ten_year):
    """(yield, multiple, pairs, filters) of one company valued at day: the owner values a book row stores.

    fiscal is the selected report's fiscal date as text; cap, ev and ebitda
    are its entry valuation (admit). pairs are metrics.evaluate over the
    company's accepted reports, filters metrics.filter_values with its legacy
    annual values and ten_year, the 10-year yield in percent on or before day
    (None omits its spread). book() and a formula context without a stored
    book (measure_observations.dated) call it; prices are read on or before day.
    The daily cache is an input here: the valuation averages read the
    valuation_sums table (facts.valuation), which daily.prepare keeps current
    for the attached research before it builds any book.
    """
    yield_value,multiple=ebitda_yield_and_multiple(ebitda,ev)
    observation=dict(fiscal=fiscal,market_cap=cap,enterprise_value=ev,ev_ebitda=multiple,ebitda_yield=yield_value)
    reports=facts.reports() if getattr(facts,'market','us')=='us' else facts.reports(day,symbol=symbol)
    history=[dict(report,fiscal=str(report['fiscal']),known=str(report['known'])) for report in reports[0][symbol]
             if getattr(facts,'market','us')=='us' or report['known']<day]
    pairs=metrics.evaluate(observation,history)
    def lookup(when,forward,slack):
        return facts.price(symbol,when,forward,slack) if getattr(facts,'market','us')=='us' else facts.usd_price(symbol,when,forward,slack)
    annual=facts.legacy_annual(symbol) if getattr(facts,'market','us')=='us' else facts.legacy_annual(symbol,day)
    return yield_value,multiple,pairs,metrics.filter_values(observation,pairs,day,lookup,annual,ten_year,
                                                            lambda when:facts.valuation(symbol,when))


def valuation_days(symbol, facts, start, sums):
    """[(day, earnings, sales, equity, earnings_days, sales_days, equity_days)]: one company's running valuation sums.

    Each priced day on or after start (every day when None) adds the signed
    daily yields (metrics.valuation_yields) of the cached-pool report that a
    book selects that day (facts.report_at), at the cap that admit() gives
    there, and counts them. A day without a report, a fiscal price within 7
    days or a positive finite cap, or without any yield, adds no row. sums is
    the state before start. The sums add in day order from +0.0, so a tail that
    continues from the stored state equals a cold fold bit for bit; daily
    repairs refold from the sheet cutoffs (affected_entries).
    """
    closes=facts.closes(symbol,None if start is None else start-run.MAX_AGE-timedelta(days=7))
    days=[day for day,_ in closes]
    total=list(sums);rows=[]
    for day,close in closes:
        if start is not None and day<start:continue
        found=facts.report_at(symbol,day)
        if found is None:continue
        statement,values=found
        i=bisect_right(days,statement['fiscal'])-1
        if i<0 or (statement['fiscal']-days[i]).days>7:continue
        cap=rescaled_cap(statement,closes[i],(day,close))
        if not (cap>0 and math.isfinite(cap)):continue
        yields=metrics.valuation_yields(cap,values)
        if all(value is None for value in yields):continue
        for k,value in enumerate(yields):
            if value is not None:
                total[k]+=value;total[3+k]+=1
        rows.append((str(day),*total))
    return rows


def benchmark_return(entry_price, exit_price):
    return exit_price/entry_price-1


def yield_spread(earnings_yield, treasury_yield):
    return earnings_yield-treasury_yield
