"""Annual statement assets and dated financial filter inputs. No network here."""
import hashlib
import json

from backtest.inputs import cache_assets as cache_assets
from backtest.financial import rules
from backtest.inputs import market

ENDPOINTS = {
    'income-statement': ('revenue','operatingIncome','netIncome','epsDiluted','ebit','interestExpense'),
    'balance-sheet-statement': ('totalStockholdersEquity','totalCurrentAssets','totalCurrentLiabilities','totalDebt'),
    'cash-flow-statement': ('freeCashFlow',),
    'key-metrics': (),
    'ratios': (),
}


def asset_path(raw, symbol, endpoint):
    return raw/'financial-inputs'/endpoint/market.cache_path_for(symbol).name


def normalize(rows, symbol, endpoint):
    """Validate the response without trimming any fields, metadata or currencies."""
    if not isinstance(rows,list):raise ValueError('Invalid annual statement response. Saved files were kept.')
    for row in rows:
        if not isinstance(row,dict) or not (day:=rules.parse_day(row.get('date'))):
            raise ValueError('Invalid annual statement date. Saved files were kept.')
        if row.get('symbol',symbol)!=symbol or row.get('period','FY')!='FY':
            raise ValueError('Unexpected annual statement identity. Saved files were kept.')
        for field in ENDPOINTS[endpoint]:
            number=row.get(field)
            if number is not None and (isinstance(number,bool) or rules.num(number) is None):
                raise ValueError('Invalid annual statement number. Saved files were kept.')
    json.dumps(rows,allow_nan=False)
    return rows


def read(raw,symbol,endpoint):
    path=asset_path(raw,symbol,endpoint)
    try:
        content=path.read_bytes();record=json.loads(content)
        if record.get('version') not in (1,2) or record.get('symbol')!=symbol or record.get('endpoint')!=endpoint:raise ValueError()
        rows=record['rows']
        if not isinstance(rows,list):raise ValueError()
    except (ValueError,TypeError,KeyError,AttributeError,FileNotFoundError):return [],None
    try:
        normalize(rows,symbol,endpoint)
        return rows,hashlib.sha256(content).hexdigest()
    except (ValueError,TypeError):
        # Preserve usable reports during repair; damaged assets prove no completion.
        usable=[]
        for row in rows:
            try:
                normalize([row],symbol,endpoint)
                usable.append(row)
            except (ValueError,TypeError):continue
        return usable,None


def completed(raw,symbol,endpoint,ledger):
    _,digest=read(raw,symbol,endpoint)
    key=asset_path(raw,symbol,endpoint).relative_to(raw).as_posix()
    entry=ledger.get(key,{})
    if not isinstance(entry,dict) or not digest:return False
    # Old trimmed assets do not prove a full-response download.
    record=cache_assets.read_json(asset_path(raw,symbol,endpoint),{})
    if record.get('version')!=2 or record.get('full_response') is not True:return False
    return any(isinstance(e,dict) and e.get('sha256')==digest for e in (entry,entry.get('previous',{})))


def publish(raw,symbol,endpoint,rows,ledger,ledger_path):
    rows=normalize(rows,symbol,endpoint)
    path=asset_path(raw,symbol,endpoint)
    old,digest=read(raw,symbol,endpoint)
    if path.exists() and digest is None:
        backup=path.with_suffix('.json.before-repair')
        if not backup.exists():cache_assets.publish_bytes(backup,path.read_bytes())
    # Keep the complete response, including repeated dates and exact duplicates.
    # Repair also retains every distinct saved variant. Never collapse by date.
    merged=list(rows)
    saved={json.dumps(row,sort_keys=True,allow_nan=False) for row in merged}
    for row in old:
        identity=json.dumps(row,sort_keys=True,allow_nan=False)
        if identity not in saved:
            merged.append(row);saved.add(identity)
    content=json.dumps(dict(version=2,full_response=True,symbol=symbol,endpoint=endpoint,rows=merged),allow_nan=False).encode()
    key=path.relative_to(raw).as_posix();previous=ledger.get(key,{})
    receipt=dict(sha256=hashlib.sha256(content).hexdigest())
    if isinstance(previous,dict):
        for candidate in (previous,previous.get('previous',{})):
            if isinstance(candidate,dict) and digest and candidate.get('sha256')==digest:
                receipt['previous']={k:v for k,v in candidate.items() if k!='previous'}
                break
    ledger[key]=receipt
    cache_assets.write_json(ledger_path,ledger)
    cache_assets.publish_bytes(path,content)


def history(raw,symbol):
    """Prepare only unambiguous USD inputs; retain every raw report variant.

    Multiple records can describe the same fiscal date. Equal nonmissing input
    values agree. Conflicting values omit that input instead of picking a revision
    by response order. Nulls do not replace known values. Metadata stays in raw.
    """
    reports={}
    for endpoint,fields in ENDPOINTS.items():
        if not fields:continue
        candidates={}
        for row in read(raw,symbol,endpoint)[0]:
            if row.get('reportedCurrency')!='USD':continue
            day=str(rules.parse_day(row['date']))
            candidates.setdefault(day,[]).append(row)
        for day,rows in candidates.items():
            values={}
            for field in fields:
                numbers={rules.num(row[field]) for row in rows if row.get(field) is not None}
                if len(numbers)==1:values[field]=numbers.pop()
            if values:reports.setdefault(day,{}).update(values)
    return reports
