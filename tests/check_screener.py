"""Compare browser latest-screen filtering with independent queries against the latest book of the daily cache."""

import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0,str(_PackagePath(__file__).resolve().parents[1]))
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest import screening
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from backtest.inputs import daily

def main():
    db = daily.connect()
    try:
        latest_cases=[{},dict(pool='cached',rank_to=100),dict(pool='cached',min_cap=500e6,max_cap=5e9,min_yield=.15),dict(pool='cached',sector='Technology',exchange='NASDAQ',max_multiple=8),dict(rank_from=10,rank_to=20),dict(sector='No matching sector'),dict(pool='cached',metric='ev_ebitda_3y',rank_to=100,max_multiple=8)]
        latest_cases.append(dict(pool='cached',filters=[dict(field='fcf_yield',op='gt',value=5)]))
        latest_cases.append(dict(pool='cached',filters=[dict(field='return_1y',op='gt',value=-10),dict(field='return_3y',op='lt',value=100)]))
        latest_cases.append(dict(pool='cached',filters=[dict(field='operating_yield_spread_3y',op='gt',value=5)]))
        latest_cases.append(dict(filters=[dict(field='pe',op='lt',value=20)]))
        latest_cases.append(dict(pool='cached',filters=[dict(field='roe',op='gt',value=10),dict(field='debt_equity',op='lt',value=1)]))
        latest_cases.append(dict(filters=[dict(field='market_cap',op='gt',value=500),dict(field='market_cap',op='lt',value=500)]))
        latest_cases += [dict(options,selection_order='rank_first') for options in latest_cases]
        expected = dict(latest=[screening.latest(db,**options) for options in latest_cases])
    finally:
        db.close()
    with tempfile.TemporaryDirectory() as folder:
        fixture = Path(folder) / 'sql-expectations.json'
        fixture.write_text(json.dumps(expected))
        subprocess.run(['node', str(ROOT / 'tests/check-screener.cjs'), str(fixture), str(Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'website'/'local')], check=True, cwd=ROOT)

if __name__ == '__main__':
    main()
