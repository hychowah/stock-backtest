"""Compare browser filtering with independent queries against prepared SQLite."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import research

CASES = [
    dict(first=2015,last=2020,filters=[dict(field='pe',op='lt',value=20)]),
    dict(first=2015,last=2020,pool='cached',filters=[dict(field='roe',op='gt',value=10),dict(field='debt_equity',op='lt',value=1)]),
    dict(first=2015, last=2020),
    dict(first=2015, last=2020, rank_to=100),
    dict(first=2015, last=2020, rank_from=10, rank_to=20),
    dict(first=2015, last=2020, pool='cached', min_cap=500e6, max_cap=5e9, min_yield=.15, rank_to=100),
    dict(first=2015, last=2020, pool='cached', sector='Technology', exchange='NASDAQ', max_multiple=8, rank_to=10),
    dict(first=2015, last=2020, sector='No matching sector'),
    dict(first=1996, last=1996, rank_to=100),
    dict(first=2026, last=2026, rank_from=10, rank_to=10),
    dict(first=2015,last=2020,pool='cached',metric='ev_ebitda_3y',max_multiple=8),
    dict(first=2015,last=2020,pool='cached',filters=[dict(field='return_1y',op='gt',value=-10),dict(field='return_3y',op='lt',value=100),dict(field='ev_ebitda',op='lt',value=10)]),
    dict(first=2015,last=2020,filters=[dict(field='market_cap',op='gt',value=500),dict(field='market_cap',op='lt',value=500)]),
]

def main():
    db = research.connect()
    try:
        latest_cases=[{},dict(pool='cached',rank_to=100),dict(pool='cached',min_cap=500e6,max_cap=5e9,min_yield=.15),dict(pool='cached',sector='Technology',exchange='NASDAQ',max_multiple=8),dict(rank_from=10,rank_to=20),dict(sector='No matching sector'),dict(pool='cached',metric='ev_ebitda_3y',rank_to=100,max_multiple=8)]
        latest_cases.append(dict(pool='cached',filters=[dict(field='fcf_yield',op='gt',value=5)]))
        latest_cases.append(dict(pool='cached',filters=[dict(field='return_1y',op='gt',value=-10),dict(field='return_3y',op='lt',value=100)]))
        expected = dict(historical=[research.screen(db, **options) for options in CASES],latest=[research.latest_screen(db,**options) for options in latest_cases])
    finally:
        db.close()
    with tempfile.TemporaryDirectory() as folder:
        fixture = Path(folder) / 'sql-expectations.json'
        fixture.write_text(json.dumps(expected))
        subprocess.run(['node', str(ROOT / 'tests/check-screener.cjs'), str(fixture), str(Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'website'/'local')], check=True, cwd=ROOT)

if __name__ == '__main__':
    main()
