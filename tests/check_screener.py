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
    dict(first=2015, last=2020),
    dict(first=2015, last=2020, rank_to=100),
    dict(first=2015, last=2020, rank_from=10, rank_to=20),
    dict(first=2015, last=2020, pool='cached', min_cap=500e6, max_cap=5e9, min_yield=.15, rank_to=100),
    dict(first=2015, last=2020, pool='cached', sector='Technology', exchange='NASDAQ', max_multiple=8, rank_to=10),
    dict(first=2015, last=2020, sector='No matching sector'),
    dict(first=1996, last=1996, rank_to=100),
    dict(first=2026, last=2026, rank_from=10, rank_to=10),
]

def main():
    db = research.connect()
    try:
        expected = [research.screen(db, **options) for options in CASES]
    finally:
        db.close()
    with tempfile.TemporaryDirectory() as folder:
        fixture = Path(folder) / 'sql-expectations.json'
        fixture.write_text(json.dumps(expected))
        subprocess.run(['node', str(ROOT / 'tests/check-screener.cjs'), str(fixture)], check=True, cwd=ROOT)

if __name__ == '__main__':
    main()
