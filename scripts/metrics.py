"""Screening metric catalog and point-in-time annual-ratio calculations.

Add a descriptor and its preparation calculator here. Selection and browser
controls consume the catalog, rather than branching on metric identifiers.
"""
from datetime import date
import statistics

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


def evaluate(observation, history):
    """Resolve every registered metric into ready-to-rank values or omit it."""
    if METRICS.keys()!=CALCULATORS.keys():
        raise ValueError('Every catalog metric must have exactly one calculator.')
    return {metric:pair for metric,calculate in CALCULATORS.items()
            if (pair:=calculate(observation,history)) is not None}


def prepare_metrics(db):
    """Publish ready-to-rank values for each mode, pool, date and company.

    The selected fiscal report bounds history; its availability and screening
    eligibility were established when preparing the observation. Latest uses
    year 0, while historical observations use their January book year.
    """
    if METRICS.keys()!=CALCULATORS.keys():
        raise ValueError('Every catalog metric must have exactly one calculator.')
    histories={}
    for row in db.execute('SELECT * FROM statements ORDER BY symbol,fiscal'):
        histories.setdefault(row['symbol'],[]).append(dict(row))
    db.execute('DELETE FROM screening_metrics')
    for mode,table in [('historical','snapshots'),('latest','latest_snapshots')]:
        values=[]
        for row in db.execute('SELECT * FROM '+table):
            observation=dict(row)
            for metric,pair in evaluate(observation,histories.get(row['symbol'],[])).items():
                values.append((mode,row['pool'],observation.get('year',0),row['symbol'],metric,*pair))
        db.executemany('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',values)


# Threshold values use display units: millions of dollars, percent, or multiples.
FILTERS = {
    'pb': dict(label='P/B', available=False),
    'pe': dict(label='P/E', available=False),
    'return_1y': dict(label='1-year trailing return (%)', available=True),
    'return_3y': dict(label='3-year trailing return (%)', available=True),
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


def filter_values(observation, pairs, day, lookup):
    """Prepare threshold inputs at the screen date, never the future exit.

    Annual lookbacks use the same calendar day (Feb 29 clamps to Feb 28).
    Each endpoint uses an adjusted close on or before that day, within 7 days.
    Missing endpoints omit the value and exclude a stock only if filtered on it.
    """
    from calendar import monthrange
    values={k:observation[k]/1e6 for k in ('market_cap','enterprise_value')}
    values['ebitda_yield']=observation['ebitda_yield']*100
    values.update({k:pair[0] for k,pair in pairs.items() if k in FILTERS})
    end=lookup(day,'adjusted',False,7)
    for years in (1,3):
        target=day.replace(year=day.year-years,day=min(day.day,monthrange(day.year-years,day.month)[1]))
        start=lookup(target,'adjusted',False,7)
        if end and start and start[1]>0:
            values[f'return_{years}y']=(end[1]/start[1]-1)*100
    return values
