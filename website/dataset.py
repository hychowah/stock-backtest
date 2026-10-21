"""Export compact prepared January records for the offline browser screener."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import json
from research import connect

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
        return dict(companies=companies, periods=periods, pools=pools, latest=latest)
    finally:
        db.close()
