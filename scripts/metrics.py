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
            for metric,calculate in CALCULATORS.items():
                pair=calculate(observation,histories.get(row['symbol'],[]))
                if pair is not None:
                    values.append((mode,row['pool'],observation.get('year',0),row['symbol'],metric,*pair))
        db.executemany('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',values)
