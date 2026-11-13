"""Screening metric catalog and point-in-time annual-ratio calculations.

Add a descriptor and its preparation calculator here. Selection and browser
controls consume the catalog, rather than branching on metric identifiers.
"""
from calendar import monthrange
from datetime import date, timedelta
import statistics
import math

from backtest.financial import rules

METRICS = {
    'ev_ebitda': dict(label='EV / EBITDA'),
    'ev_ebitda_3y': dict(label='EV / 3-year average EBITDA'),
}
DEFAULT_METRIC = 'ev_ebitda'


def annual_average(rows, fiscal, years):
    """Average consecutive annual EBITDA ending at the selected report.

    Rows have already passed currency and positive-ratio checks. Missing fiscal
    years exclude the observation; a future report never fills a missing year.
    One latest fiscal report per calendar year prevents duplicate-year weighting.
    """
    fiscal=date.fromisoformat(fiscal)
    by_year={}
    for row in rows:
        day=date.fromisoformat(row['fiscal'])
        if day<=fiscal:
            by_year[day.year]=row
    selected=[by_year.get(fiscal.year-i) for i in range(years)]
    if any(row is None for row in selected):
        return None
    return statistics.mean(row['ebitda'] for row in selected)


def current_multiple(observation, history):
    # Preserve both saved values exactly, including their floating-point rounding.
    return observation['ev_ebitda'], observation['ebitda_yield']


def three_year_multiple(observation, history):
    average=annual_average(history,observation['fiscal'],3)
    if average is None or average<=0:
        return None
    multiple=observation['enterprise_value']/average
    return multiple, 1/multiple


# Calculation dispatch is private to preparation. Consumers see only METRICS
# display metadata and prepared (multiple, yield) pairs. Missing data omits a pair.
CALCULATORS = {
    'ev_ebitda': current_multiple,
    'ev_ebitda_3y': three_year_multiple,
}


def validate_catalog():
    """Reject catalog/calculator mismatch before preparation reads or writes."""
    if METRICS.keys()!=CALCULATORS.keys():
        raise ValueError('Every catalog metric must have exactly one calculator.')


def evaluate(observation, history):
    """Resolve every registered metric into ready-to-rank values or omit it."""
    validate_catalog()
    return {metric:pair for metric,calculate in CALCULATORS.items()
            if (pair:=calculate(observation,history)) is not None}


# Threshold values use display units: millions of dollars, percent, or multiples.
FILTERS = {
    'pb': dict(label='P/B (×)', available=True),
    'pe': dict(label='P/E (×)', available=True),
    'ps': dict(label='P/S (×)', available=True),
    'pe_avg_3y': dict(label='P/E 3-year average (×)', available=True),
    'pe_avg_5y': dict(label='P/E 5-year average (×)', available=True),
    'ps_avg_3y': dict(label='P/S 3-year average (×)', available=True),
    'ps_avg_5y': dict(label='P/S 5-year average (×)', available=True),
    'pb_avg_3y': dict(label='P/B 3-year average (×)', available=True),
    'pb_avg_5y': dict(label='P/B 5-year average (×)', available=True),
    'pe_vs_avg_3y': dict(label='P/E vs its 3-year average (×)', available=True),
    'pe_vs_avg_5y': dict(label='P/E vs its 5-year average (×)', available=True),
    'ps_vs_avg_3y': dict(label='P/S vs its 3-year average (×)', available=True),
    'ps_vs_avg_5y': dict(label='P/S vs its 5-year average (×)', available=True),
    'pb_vs_avg_3y': dict(label='P/B vs its 3-year average (×)', available=True),
    'pb_vs_avg_5y': dict(label='P/B vs its 5-year average (×)', available=True),
    'fcf': dict(label='Free cash flow ($ million)', available=True),
    'fcf_yield': dict(label='Free cash flow yield (%)', available=True),
    'price_fcf': dict(label='Price / free cash flow (×)', available=True),
    'dividend_yield': dict(label='Dividend yield (%)', available=True),
    'profit_margin': dict(label='Net profit margin (%)', available=True),
    'operating_yield_spread_3y': dict(label='Sales × 3-year avg operating margin / EV − US 10Y (pp)', available=True),
    'peg': dict(label='PEG — 3-year EPS growth (×)', available=True),
    'roe': dict(label='Return on average equity (%)', available=True),
    'current_ratio': dict(label='Current ratio (×)', available=True),
    'interest_coverage': dict(label='Interest coverage — EBIT / interest (×)', available=True),
    'debt_equity': dict(label='Debt / equity (×)', available=True),
    'return_1y': dict(label='1-year trailing return (%)', available=True),
    'return_3y': dict(label='3-year trailing return (%)', available=True),
    'turnover_1w': dict(label='Turnover rate — 1-week average (%)', available=True),
    'market_cap': dict(label='Market cap ($ million)', available=True),
    'enterprise_value': dict(label='Enterprise value ($ million)', available=True),
    'ev_ebitda': dict(label='EV / EBITDA (×)', available=True),
    'ev_ebitda_3y': dict(label='EV / 3-year average EBITDA (×)', available=True),
    'ebitda_yield': dict(label='EBITDA / EV (%)', available=True),
}


def validate_filters(filters):
    import math
    if filters is None:
        return []
    if not isinstance(filters, list) or len(filters)>50:
        raise ValueError('Use a list of at most 50 filter conditions.')
    for condition in filters:
        if not isinstance(condition, dict) or set(condition)!={'field','op','value'}:
            raise ValueError('Each filter needs a field, comparison and value.')
        field,op,value=(condition[k] for k in ('field','op','value'))
        if not isinstance(field,str) or not FILTERS.get(field,{}).get('available'):
            raise ValueError('Choose an available filter metric.')
        if op not in ('lt','gt'):
            raise ValueError('Choose less than or more than.')
        if type(value) not in (int,float) or not math.isfinite(value):
            raise ValueError('Filter values must be finite numbers.')
    return filters


def anniversary(day, years):
    """The same calendar day years earlier; Feb 29 clamps to Feb 28."""
    year=day.year-years
    return day.replace(year=year,day=min(day.day,monthrange(year,day.month)[1]))


def filter_values(observation, pairs, day, lookup, financials=None, treasury10=None, *, sums, dividends, shares, volumes):
    """Prepare threshold inputs at the screen date, never the future exit.

    Annual lookbacks use the same calendar day (anniversary).
    Each endpoint uses an adjusted close on or before that day, within 7 days:
    lookup(day, forward, slack) returns (day, adjusted close) or None.
    Missing endpoints omit the value and exclude a stock only if filtered on it.
    treasury10 is the saved 10-year yield in percent; None omits its spread.
    sums(day) gives the stored running valuation sums (facts.valuation) at
    the last priced day on or before day, or zeros. An average
    multiple is 1 / the mean daily yield over the priced days in
    (anniversary, day]; it needs a sum on or before the anniversary and a
    positive mean. A relative is the current multiple / its average.
    dividends is the selected report's common dividends paid, signed as
    reported (a payment is negative), or None; the dividend yield is
    -dividends / market cap. volumes(start, end) gives the saved session
    volumes from start through end. The 1-week turnover rate is their mean over
    the 7 calendar days ending on day / shares, the selected report's annual
    weighted-average basic shares (None or not positive omits it).
    """
    values={k:observation[k]/1e6 for k in ('market_cap','enterprise_value')}
    values['ebitda_yield']=observation['ebitda_yield']*100
    values.update({k:pair[0] for k,pair in pairs.items() if k in FILTERS})
    cap=observation['market_cap']
    if dividends is not None:values['dividend_yield']=-dividends/cap*100
    if shares is not None and shares>0 and (traded:=volumes(day-timedelta(days=6),day)):
        values['turnover_1w']=sum(traded)/len(traded)/shares*100
    end=lookup(day,False,7)
    for years in (1,3):
        start=lookup(anniversary(day,years),False,7)
        if end and start and start[1]>0:
            values[f'return_{years}y']=(end[1]/start[1]-1)*100
    if financials:
        values.update(financial_values(observation,financials))
        spread=operating_yield_spread(observation,financials,treasury10)
        if spread is not None:values['operating_yield_spread_3y']=spread
    current=sums(day)
    for years in (3,5):
        before=sums(anniversary(day,years))
        for k,(key,_) in enumerate(rules.VALUATIONS):
            count=current[3+k]-before[3+k]
            if before[3+k]==0 or count==0:continue
            mean=(current[k]-before[k])/count
            if mean<=0 or not math.isfinite(1/mean):continue
            values[f'{key}_avg_{years}y']=average=1/mean
            if key in values and math.isfinite(relative:=values[key]/average):
                values[f'{key}_vs_avg_{years}y']=relative
    return values


def operating_margin(income, revenue):
    """Operating income / revenue, or None when revenue is not positive; signed income stays signed."""
    return income/revenue if revenue>0 else None


def operating_yield_spread(observation, reports, treasury10):
    """Selected annual sales × mean of three annual margins / current EV.

    Margins are operating income / revenue, with equal weight per fiscal year.
    Require three consecutive years ending at the selected report. Treasury is
    the screen-date 10-year yield in percent; the result is percentage points.
    Missing inputs omit only this filter. Signed operating income stays signed.
    """
    if treasury10 is None or not math.isfinite(treasury10):return None
    fiscal=str(observation['fiscal']);by_year={}
    for day,row in sorted(reports.items()):
        if day<=fiscal:by_year[int(day[:4])]=row
    current=reports.get(fiscal,{})
    sales=current.get('revenue');ev=observation.get('enterprise_value')
    if sales is None or sales<=0 or ev is None or ev<=0:return None
    margins=[]
    for year in range(int(fiscal[:4])-2,int(fiscal[:4])+1):
        report=by_year.get(year,{})
        revenue=report.get('revenue');income=report.get('operatingIncome')
        margin=None if revenue is None or income is None else operating_margin(income,revenue)
        if margin is None:return None
        margins.append(margin)
    value=sales*statistics.mean(margins)/ev*100-treasury10
    return value if math.isfinite(value) else None


def financial_values(observation,reports):
    """Use the selected annual report only; no newer report fills missing fields."""
    fiscal=str(observation['fiscal']);current=reports.get(fiscal,{})
    # Annual year-end dates can move. Select the latest date in each earlier year.
    by_year={}
    for day,row in sorted(reports.items()):
        if day<=fiscal:by_year[int(day[:4])]=row
    previous=by_year.get(int(fiscal[:4])-1,{})
    result={};cap=observation['market_cap']
    def ratio(key,numerator,denominator,scale=1):
        if numerator is not None and denominator is not None and denominator>0:
            value=numerator/denominator*scale
            if math.isfinite(value):result[key]=value
    income=current.get('netIncome');equity=current.get('totalStockholdersEquity');fcf=current.get('freeCashFlow')
    ratio('pe',cap,income);ratio('ps',cap,current.get('revenue'));ratio('pb',cap,equity)
    if fcf is not None:result['fcf']=fcf/1e6
    ratio('fcf_yield',fcf,cap,100);ratio('price_fcf',cap,fcf)
    ratio('profit_margin',income,current.get('revenue'),100)
    old_equity=previous.get('totalStockholdersEquity')
    if equity is not None and old_equity is not None and equity>0 and old_equity>0:
        ratio('roe',income,(equity+old_equity)/2,100)
    ratio('current_ratio',current.get('totalCurrentAssets'),current.get('totalCurrentLiabilities'))
    ratio('interest_coverage',current.get('ebit'),current.get('interestExpense'))
    ratio('debt_equity',current.get('totalDebt'),equity)
    eps=[by_year.get(int(fiscal[:4])-i,{}).get('epsDiluted') for i in range(4)]
    if 'pe' in result and all(e is not None and e>0 for e in eps):
        growth=((eps[0]/eps[3])**(1/3)-1)*100
        ratio('peg',result['pe'],growth)
    return result
