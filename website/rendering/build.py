"""Build all local presentation outputs from detached page data."""
import csv
import hashlib
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
    holdings=data.holdings
    csv_text=data.csv_text
    output.mkdir(parents=True,exist_ok=True)
    (output/'index.html').write_text(page,encoding='utf-8',newline='\n')
    with (output/'latest-picks.csv').open('w',newline='',encoding='utf-8') as handle:
        fields=['rank','symbol','name','exchange','sector','price','market_cap','enterprise_value','ebitda_yield','ev_ebitda','fiscal','known','price_date']
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction='ignore',lineterminator='\n')
        writer.writeheader();writer.writerows(data.latest_stocks)
    with (output / 'holdings.csv').open('w',newline='',encoding='utf-8') as handle:
        fields = ['year']+list(next(iter(holdings.values()))['holdings'][0])
        writer = csv.DictWriter(handle,fieldnames=fields,lineterminator='\n')
        writer.writeheader()
        for year, group in holdings.items():
            for h in group['holdings']:
                writer.writerow(dict(year=year,**h))
    (output / 'valuations.json').write_text(json.dumps(holdings,indent=2),encoding='utf-8',newline='\n')
    print('Verified every annual holding count and return against summary-exits.txt.')
    (output / 'returns.csv').write_text(csv_text,encoding='utf-8',newline='\n')
    print(f'Built {len(data.annual)} years with static chart and table, plus optional interactions.')


    (output/'data.html').write_text(data_page(),encoding='utf-8',newline='\n')
    provenance=dict(report_sha256=hashlib.sha256(data.report_bytes).hexdigest(),
        historical_through=data.historical_through,
        latest_asof=data.screening_data['latest']['metadata']['asof'],sources=inputs()['sources'])
    (output/'snapshot.json').write_text(json.dumps(provenance,indent=2)+'\n',encoding='utf-8',newline='\n')
    if output==LOCAL_OUTPUT:record_build()
    print('Website output: '+str(output))
