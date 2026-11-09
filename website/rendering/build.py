"""Build all local presentation outputs from detached page data."""
import csv
import json
import os
from pathlib import Path
from backtest.inputs import cache_assets
from website.rendering.data import load_page_data
from website.rendering.page import render
from website.rendering.assets import data_page
from website.rendering.state import LOCAL_OUTPUT, STAMP, OUTPUTS, inputs, record_build


def build(output=LOCAL_OUTPUT, *, progress=lambda **kw:None):
    output=Path(output)
    progress(kind='website',completed=0,total=6)
    data=load_page_data()
    progress(kind='website',completed=1,total=6)
    page=render(data)
    output.mkdir(parents=True,exist_ok=True)
    if output==LOCAL_OUTPUT:
        STAMP.unlink(missing_ok=True);cache_assets.sync_directory(output)
    (output/'index.html').write_text(page,encoding='utf-8',newline='\n')
    progress(kind='website',completed=2,total=6)
    with (output/'latest-picks.csv').open('w',newline='',encoding='utf-8') as handle:
        fields=['rank','symbol','name','exchange','sector','price','market_cap','enterprise_value','ebitda_yield','ev_ebitda','fiscal','known','price_date']
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction='ignore',lineterminator='\n')
        writer.writeheader();writer.writerows(data.latest_stocks)
    progress(kind='website',completed=3,total=6)
    print(f'Built the latest screen ({len(data.latest_stocks)} default picks) with a static table, plus optional interactions.')
    (output/'data.html').write_text(data_page(),encoding='utf-8',newline='\n')
    progress(kind='website',completed=4,total=6)
    provenance=dict(latest_asof=data.screening_data['latest']['metadata']['asof'],latest_dates={code:value['latest']['metadata']['asof'] for code,value in {'us':data.screening_data,**data.screening_data['markets']}.items()},sources=inputs()['sources'])
    (output/'snapshot.json').write_text(json.dumps(provenance,indent=2)+'\n',encoding='utf-8',newline='\n')
    progress(kind='website',completed=5,total=6)
    for name in OUTPUTS:
        with (output/name).open('r+b') as handle:os.fsync(handle.fileno())
    if output==LOCAL_OUTPUT:record_build()
    progress(kind='website',completed=6,total=6)
    print('Website output: '+str(output))
