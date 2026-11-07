"""Annual statement assets and dated financial filter inputs. No network here."""
import functools
from collections import Counter
import hashlib
import json

from backtest.inputs import cache_assets as cache_assets
from backtest.financial import rules
from backtest.inputs import market
from backtest.variables import parameters

ENDPOINTS = {
    'income-statement': ('revenue','operatingIncome','netIncome','epsDiluted','ebit','interestExpense'),
    'balance-sheet-statement': ('totalStockholdersEquity','totalCurrentAssets','totalCurrentLiabilities','totalDebt'),
    'cash-flow-statement': ('freeCashFlow',),
    'key-metrics': (),
    'ratios': (),
}


def observation_fields():
    """Derive endpoint-qualified annual meaning without widening raw admission.

    ENDPOINTS remains the legacy validation/values contract. Semantic additions
    are inspected only after that unchanged asset admission has succeeded.
    """
    return dict(_observation_fields())


@functools.cache
def _observation_fields():
    # The loaded catalog cannot change in a running process.
    fields = {}
    for item in parameters.catalog(parameters.V3):
        if item['kind'] == 'direct' and item['id'].startswith('annual.'):
            source = item['source']
            names = fields.setdefault(source['endpoint'], [])
            if source['field'] not in names:
                names.append(source['field'])
    return {endpoint: tuple(names) for endpoint, names in fields.items()}


def _observation_number(value):
    # bool is numeric to Python, but never an admitted financial observation.
    if isinstance(value, bool): return None
    try:
        return rules.num(value)
    except OverflowError:
        return None


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


def _asset(raw, symbol, endpoint):
    """Read once and identify admitted rows, including damaged saved assets.

    The content hash identifies bytes. Only a valid asset also supplies the
    completion digest used by read()/completed(); salvaged bytes prove no download.
    """
    path=asset_path(raw,symbol,endpoint)
    evidence=dict(endpoint=endpoint, disposition='missing', sha256=None, rows=[])
    try:
        content=path.read_bytes()
    except FileNotFoundError:
        return [], None, evidence
    evidence.update(sha256=hashlib.sha256(content).hexdigest(), disposition='unreadable')
    try:
        record=json.loads(content)
        if record.get('version') not in (1,2) or record.get('symbol')!=symbol or record.get('endpoint')!=endpoint:raise ValueError()
        rows=record['rows']
        if not isinstance(rows,list):raise ValueError()
    except (ValueError,TypeError,KeyError,AttributeError):return [],None,evidence
    try:
        normalize(rows,symbol,endpoint)
        usable=list(enumerate(rows));digest=evidence['sha256'];evidence['disposition']='valid'
    except (ValueError,TypeError):
        # Preserve usable reports during repair; damaged assets prove no completion.
        usable=[];digest=None;evidence['disposition']='salvaged'
        for index,row in enumerate(rows):
            try:
                normalize([row],symbol,endpoint)
                usable.append((index,row))
            except (ValueError,TypeError):continue
    evidence['rows']=[dict(index=index,sha256=hashlib.sha256(json.dumps(row,sort_keys=True,
        separators=(',',':'),allow_nan=False).encode()).hexdigest()) for index,row in usable]
    return [row for _,row in usable],digest,evidence


def read(raw,symbol,endpoint):
    rows,digest,_=_asset(raw,symbol,endpoint)
    return rows,digest


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
    """Publish the full response and return its admitted rows."""
    rows=normalize(rows,symbol,endpoint)
    path=asset_path(raw,symbol,endpoint)
    old,digest=read(raw,symbol,endpoint)
    if path.exists() and digest is None:
        backup=path.with_suffix('.json.before-repair')
        if not backup.exists():cache_assets.publish_bytes(backup,path.read_bytes())
    # Keep the complete response, including repeated dates and exact duplicates.
    # Keep prior variants and their duplicate counts too. Rechecking an identical
    # response must not accumulate another copy of every report each night.
    merged=list(rows)
    saved=Counter(json.dumps(row,sort_keys=True,allow_nan=False) for row in merged)
    seen=Counter()
    for row in old:
        identity=json.dumps(row,sort_keys=True,allow_nan=False)
        seen[identity]+=1
        if seen[identity]>saved[identity]:
            merged.append(row);saved[identity]+=1
    content=json.dumps(dict(version=2,full_response=True,symbol=symbol,endpoint=endpoint,rows=merged),allow_nan=False).encode()
    key=path.relative_to(raw).as_posix();previous=ledger.get(key,{})
    receipt=dict(sha256=hashlib.sha256(content).hexdigest())
    if receipt['sha256']==digest and isinstance(previous,dict) and any(
            isinstance(entry,dict) and entry.get('sha256')==digest for entry in (previous,previous.get('previous',{}))):return rows
    if isinstance(previous,dict):
        for candidate in (previous,previous.get('previous',{})):
            if isinstance(candidate,dict) and digest and candidate.get('sha256')==digest:
                receipt['previous']={k:v for k,v in candidate.items() if k!='previous'}
                break
    ledger[key]=receipt
    cache_assets.write_json(ledger_path,ledger)
    if receipt['sha256']!=digest:cache_assets.publish_bytes(path,content)
    return rows


def resolve_history(raw,symbol):
    """Resolve annual values and independent field evidence in one authority.

    Multiple records can describe the same fiscal date. Equal nonmissing input
    values agree. Conflicting values omit that input instead of picking a revision
    by response order. Nulls do not replace known values. All admitted fiscal dates
    survive in evidence, including dates with no usable field. Raw assets stay intact.
    """
    reports={};sources={};annual={}
    semantic = observation_fields()
    for endpoint,legacy_fields in ENDPOINTS.items():
        fields = tuple(dict.fromkeys((*legacy_fields, *semantic.get(endpoint, ()))))
        if not fields:continue
        rows,_,source=_asset(raw,symbol,endpoint)
        sources[endpoint]={key:value for key,value in source.items() if key!='rows'}
        candidates={}
        for row,identity in zip(rows,source['rows']):
            day=str(rules.parse_day(row['date']))
            candidates.setdefault(day,[]).append((row,identity))
        annual[endpoint]={}
        for day,members in candidates.items():
            values={};states={}
            for field in fields:
                inputs=[dict(identity,currency=row.get('reportedCurrency'),
                             value=_observation_number(row.get(field))) for row,identity in members]
                numbers={item['value'] for item in inputs if item['currency']=='USD' and item['value'] is not None}
                if len(numbers)==1:
                    value=next(iter(numbers));values[field]=value;reason=None
                else:
                    value=None
                    reason=('CONFLICTING_INPUT' if len(numbers)>1 else
                            'NON_USD_INPUT' if any(isinstance(item['currency'],str) and item['currency']
                                and item['currency']!='USD' and item['value'] is not None for item in inputs)
                            else 'INVALID_INPUT' if any(row.get(field) is not None
                                and row.get(field) != '' and _observation_number(row.get(field)) is None
                                for row, _ in members) else 'MISSING_INPUT')
                states[field]=dict(value=value,valid=reason is None,reason=reason,rows=inputs)
            annual[endpoint][day]=states
            # Endpoint order and the values-only field list are immutable legacy
            # policy. New observations cannot leak into financial calculations.
            legacy = {field: values[field] for field in legacy_fields if field in values}
            if legacy:reports.setdefault(day,{}).update(legacy)
    return dict(values=reports,sources=sources,annual=annual)


def history(raw,symbol):
    """Return the unchanged values-only projection of annual USD resolution."""
    return resolve_history(raw,symbol)['values']
