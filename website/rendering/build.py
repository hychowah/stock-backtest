"""Build all local presentation outputs from detached page data."""
import csv
import json
from pathlib import Path
from website.rendering.data import load_page_data
from website.rendering.page import render
from website.rendering.assets import data_page
from website.rendering.state import LOCAL_OUTPUT, inputs, record_build


def build(output=LOCAL_OUTPUT):
    output=Path(output)
    data=load_page_data()
    page=render(data)
    output.mkdir(parents=True,exist_ok=True)
    (output/'index.html').write_text(page,encoding='utf-8',newline='\n')
    with (output/'latest-picks.csv').open('w',newline='',encoding='utf-8') as handle:
        fields=['rank','symbol','name','exchange','sector','price','market_cap','enterprise_value','ebitda_yield','ev_ebitda','fiscal','known','price_date']
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction='ignore',lineterminator='\n')
        writer.writeheader();writer.writerows(data.latest_stocks)
    print(f'Built the latest screen ({len(data.latest_stocks)} default picks) with a static table, plus optional interactions.')
    (output/'data.html').write_text(data_page(),encoding='utf-8',newline='\n')
    provenance=dict(latest_asof=data.screening_data['latest']['metadata']['asof'],sources=inputs()['sources'])
    (output/'snapshot.json').write_text(json.dumps(provenance,indent=2)+'\n',encoding='utf-8',newline='\n')
    if output==LOCAL_OUTPUT:record_build()
    print('Website output: '+str(output))
