"""Export compact prepared January records for the offline browser screener."""

# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import json
from backtest.inputs.research import connect
from backtest.financial.metrics import METRICS, FILTERS

FIELDS = ['year','symbol','candidate_rank','fiscal','entry','exit',
          'market_cap','enterprise_value','ebitda_yield','ev_ebitda',
          'return_value','status']


def load_screening_data():
    db = connect()
    try:
        companies = {r['symbol']: [r['name'], r['exchange'], r['sector']]
                     for r in db.execute('SELECT * FROM companies WHERE symbol IN (SELECT symbol FROM snapshots UNION SELECT symbol FROM latest_snapshots)')}
        periods = {r['year']: dict(r) for r in db.execute('SELECT * FROM periods ORDER BY year')}
        pools = {}
        for pool in ['legacy', 'cached']:
            pools[pool] = [list(row) for row in db.execute(
                'SELECT '+','.join(FIELDS)+' FROM snapshots WHERE pool=? ORDER BY year,symbol', (pool,))]
        latest_fields=['symbol','candidate_rank','fiscal','known','price_date','price','market_cap','enterprise_value','ebitda_yield','ev_ebitda','spread']
        latest={pool:[list(row) for row in db.execute('SELECT '+','.join(latest_fields)+' FROM latest_snapshots WHERE pool=? ORDER BY symbol',(pool,))] for pool in ['legacy','cached']}
        latest['metadata']=json.loads(db.execute("SELECT value FROM metadata WHERE key='latest'").fetchone()[0])
        metric_values={}
        for r in db.execute('SELECT * FROM screening_metrics'):
            key=f"{r['mode']}:{r['pool']}:{r['year']}:{r['symbol']}"
            metric_values.setdefault(key,{})[r['metric']]=[r['multiple'],r['yield_value']]
        filter_values={}
        for r in db.execute('SELECT * FROM filter_values'):
            key=f"{r['mode']}:{r['pool']}:{r['year']}:{r['symbol']}"
            filter_values.setdefault(key,{})[r['field']]=r['value']
        return dict(filter_catalog=FILTERS, filter_values=filter_values, companies=companies, periods=periods, pools=pools, latest=latest,
                    metrics=METRICS, metric_values=metric_values)
    finally:
        db.close()
