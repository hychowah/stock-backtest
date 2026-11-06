"""Validated raw assets and download evidence tied to their saved contents.

A completed request is evidence only for the exact valid file we published.
Missing, damaged, manually replaced and legacy assets retain their usable rows,
but cannot inherit empty-request evidence from a different file generation.
"""
from datetime import date, timedelta
import hashlib
import json
import time

from backtest.runtime import diagnostics as diagnostics
from backtest.financial import rules

PUBLISH_RETRY_DELAYS=(.05,.1,.2,.4,.4,.4,.4)


def replace(temporary,path,content=None):
    """Replace path with temporary atomically, first writing content to temporary when given.

    The one replace helper of saved files and the research database. File
    indexers can briefly deny either the temporary write or the replacement:
    Windows sharing/access locks are retried for under 2s. Keep the old
    destination and the pending file on failure. Other OS errors fail
    immediately. The caller retains cache ownership throughout these retries.
    """
    for attempt in range(len(PUBLISH_RETRY_DELAYS)+1):
        try:
            if content is not None:temporary.write_bytes(content)
            temporary.replace(path)
            return
        except PermissionError as error:
            if getattr(error,'winerror',None) not in (5,32,33) or attempt==len(PUBLISH_RETRY_DELAYS):raise
            diagnostics.event('cache.publish_retry',asset=diagnostics.relative_path(path),attempt=attempt+1,
                              winerror=error.winerror,delay=PUBLISH_RETRY_DELAYS[attempt])
            time.sleep(PUBLISH_RETRY_DELAYS[attempt])


def publish_bytes(path,content):
    """Write content to a '.download' file beside path and replace path with it (replace)."""
    path.parent.mkdir(parents=True,exist_ok=True)
    replace(path.with_name(path.name+'.download'),path,content)


def read_json(path, default=None):
    if not path.exists():return default
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    publish_bytes(path,json.dumps(value,allow_nan=False).encode('utf-8'))


def financial_records(path):
    """Return mapping-only annual rows and count damaged JSONL records.

    Valid annual rows in an otherwise damaged record remain available. Repair
    can preserve them without making preparation guess how to handle scalars.
    A malformed outer record is omitted so its symbol can be downloaded again.
    """
    records={};invalid=0
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():continue
            try:
                record=json.loads(line)
                if not isinstance(record,dict) or not isinstance(record.get('symbol'),str) or not record['symbol'] or not isinstance(record.get('rows'),list):raise ValueError()
                rows=[row for row in record['rows'] if isinstance(row,dict)]
                invalid+=len(rows)!=len(record['rows'])
                records[record['symbol']]={**record,'rows':rows}
            except (ValueError,TypeError):invalid+=1
    return records,invalid


def series(rows, field):
    """Return usable dated values, in date order, with one record per date."""
    if not isinstance(rows,list):return []
    result={}
    for row in rows:
        if not isinstance(row,dict):continue
        day=rules.parse_day(row.get('date'));value=rules.num(row.get(field))
        if day and value is not None and (field=='month3' or value>0):result[str(day)]=row
    return [result[day] for day in sorted(result)]


def valid_series(payload,field,*,stock=False):
    """Whether one parsed price or yield file is a valid asset; builds no rows.

    A stock file keeps its rows under 'div'. Valid rows are all mappings, and
    a nonempty response with no usable data is an invalid asset, not a valid
    empty history. Real empty histories are represented by [].
    """
    values=payload.get('div') if stock and isinstance(payload,dict) else payload if not stock else None
    return (isinstance(values,list) and all(isinstance(row,dict) for row in values)
            and (not values or any(series([row],field) for row in values)))


def checked_series(payload,field,*,stock=False):
    """Return (valid_series(), usable rows) of one parsed price or yield file."""
    values=payload.get('div',[]) if stock and isinstance(payload,dict) else payload if not stock else []
    return valid_series(payload,field,stock=stock),series(values,field)


def missing_spans(rows,field,start,end,checked):
    """Find unrequested ranges outside the actual saved span.

    Caller supplies only checked windows belonging to this valid asset. This
    span contract makes no promise about IPOs, stops or internal session gaps.
    """
    valid=series(rows,field)
    covered=[tuple(window) for window in checked]
    if valid:covered.append((valid[0]['date'][:10],valid[-1]['date'][:10]))
    cursor=start;gaps=[]
    for a,b in sorted(covered):
        a,b=date.fromisoformat(a),date.fromisoformat(b)
        if b<cursor or a>end:continue
        if a>cursor:gaps.append((cursor,min(end,a-timedelta(days=1))))
        cursor=max(cursor,b+timedelta(days=1))
        if cursor>end:break
    if cursor<=end:gaps.append((cursor,end))
    return gaps


class SeriesAsset:
    """Own one price/yield file, its normalized rows and request provenance.

    Publication preserves saved values and the file's other keys. Evidence names the
    expected file content and original saved span. A half-published update
    cannot match the wrong file. Unfinished managed windows remain missing
    even if parallel results extend the actual date span on both sides.
    """
    def __init__(self,path,field,*,stock=False):
        self.path=path;self.field=field;self.stock=stock
        self.key='px/'+path.name if stock else path.name
        self.payload={} if stock else [];self.valid=False;self.digest=None
        content=None
        if path.exists():
            content=path.read_bytes()
            try:
                self.payload=json.loads(content)
            except (ValueError,UnicodeDecodeError):content=None
        valid,self.rows=checked_series(self.payload,field,stock=stock)
        if content is not None and valid:
            self.valid=True;self.digest=hashlib.sha256(content).hexdigest()

    def evidence(self,ledger):
        if not self.valid:return {}
        entry=ledger.get(self.key,{})
        if not isinstance(entry,dict):return {}
        for candidate in (entry,entry.get('previous',{})):
            if isinstance(candidate,dict) and candidate.get('sha256')==self.digest:return candidate
        return {}

    def checked(self,ledger):
        entry=self.evidence(ledger)
        if not entry:return []
        windows=entry.get('windows',[])
        if not isinstance(windows,list):return []
        try:
            if any(not isinstance(w,list) or len(w)!=2 or date.fromisoformat(w[0])>date.fromisoformat(w[1]) for w in windows):return []
        except (TypeError,ValueError):return []
        return windows

    def base_span(self,ledger):
        entry=self.evidence(ledger)
        if 'base_span' in entry:
            value=entry['base_span']
            if value is None:return []
            try:
                if isinstance(value,list) and len(value)==2 and date.fromisoformat(value[0])<=date.fromisoformat(value[1]):return [value]
            except (TypeError,ValueError):pass
            return []
        return [[self.rows[0]['date'][:10],self.rows[-1]['date'][:10]]] if self.rows else []

    def missing(self,start,end,ledger):
        return missing_spans([],self.field,start,end,self.base_span(ledger)+self.checked(ledger))

    def skipped_dates(self,ledger):
        """Return excluded price dates tied to this exact saved asset."""
        values=self.evidence(ledger).get('skipped_dates',[])
        if not isinstance(values,list):return []
        return sorted({str(day) for value in values if (day:=rules.parse_day(value))})

    def publish(self,batch,start,end,ledger,ledger_path):
        """Save usable values and record dated price exclusions, even if all.

        A checked request can have no usable prices. Exclusion dates distinguish
        that result from an empty provider response without making prices up.
        Malformed records, missing/nonfinite values and out-of-window dates
        still fail before publication.
        """
        def fail(reason):
            raise ValueError(f'{self.key}, {start} to {end}: {reason} Saved files were kept.')
        if not isinstance(batch,list):fail('The provider returned invalid dated values.')
        candidates=[];skipped=[]
        for row in batch:
            if not isinstance(row,dict) or not (day:=rules.parse_day(row.get('date'))):
                fail('The provider returned invalid dated values.')
            if not start<=str(day)<=end:
                fail('The provider returned values outside the requested dates.')
            value=rules.num(row.get(self.field))
            if self.field=='adjClose' and value is not None and value<=0:
                skipped.append(str(day))
            else:candidates.append(row)
        valid=series(candidates,self.field)
        if len(valid)!=len(candidates):fail('The provider returned invalid or duplicate dated values.')
        windows=self.checked(ledger)+[[start,end]]
        by_day={row['date'][:10]:row for row in self.rows}
        for row in valid:by_day.setdefault(row['date'][:10],row)
        merged=[by_day[day] for day in sorted(by_day,reverse=True)]
        skipped=sorted(set(skipped)-by_day.keys())
        exclusions=sorted((set(self.skipped_dates(ledger))|set(skipped))-by_day.keys())
        self._store(merged,windows,ledger,ledger_path,skipped_dates=exclusions)
        return skipped

    def repair(self,ledger,ledger_path):
        """Normalize salvageable rows without claiming any new requested dates."""
        if self.path.exists() and not self.valid and self.rows:
            self._store(self.rows,[],ledger,ledger_path)

    def _store(self,merged,windows,ledger,ledger_path,*,skipped_dates=None):
        if self.stock:
            value=dict(self.payload) if isinstance(self.payload,dict) else {}
            value['div']=merged
        else:value=merged
        if self.path.exists() and not self.valid:
            backup=ledger_path.parent/'archive'/(self.path.name+'.before-data-repair')
            if not backup.exists():backup.parent.mkdir(parents=True,exist_ok=True);backup.write_bytes(self.path.read_bytes())
        base=self.base_span(ledger)
        content=json.dumps(value,allow_nan=False).encode('utf-8')
        digest=hashlib.sha256(content).hexdigest()
        entry=dict(sha256=digest,windows=windows,base_span=base[0] if base else None)
        if skipped_dates:entry['skipped_dates']=skipped_dates
        previous=self.evidence(ledger)
        if previous:entry['previous']={key:value for key,value in previous.items() if key!='previous'}
        # Evidence can only apply when the exact corresponding asset exists.
        # Publish its expected hash first: a crash before asset replacement
        # leaves a mismatch, while a crash after it retains all known holes.
        write_json(ledger_path,{**ledger,self.key:entry})
        publish_bytes(self.path,content)
        self.payload=value;self.rows=series(merged,self.field);self.valid=True;self.digest=digest
        ledger[self.key]=entry

def financial_record(symbol: str, payload: object) -> dict:
    """Keep every provider field. Prepared calculations select their own inputs."""
    if not isinstance(payload,list) or any(not isinstance(row,dict) for row in payload):
        raise ValueError('Invalid annual financial response. Saved files were kept.')
    record={"symbol":symbol,"rows":payload,"full_response":True}
    # Reject nonfinite JSON values without discarding unknown fields or nulls.
    json.dumps(record,allow_nan=False)
    return record



def source_problem(raw=None):
    """Inspect essential saved inputs without preparation or network access."""
    from backtest.paths import RAW
    raw=RAW if raw is None else raw
    for name in ('universe.json','metrics.jsonl','spy-div.json','treasury.json'):
        path=raw/name
        if not path.is_file() or not path.stat().st_size:return True
    try:
        rows=read_json(raw/'universe.json',[])
        if not isinstance(rows,list) or not any(isinstance(row,dict) and isinstance(row.get('symbol'),str) for row in rows) or financial_records(raw/'metrics.jsonl')[1]:return True
        for file,field in [('spy-div.json','adjClose'),('treasury.json','month3')]:
            if not series(read_json(raw/file,[]),field):return True
    except (ValueError,OSError):return True
    return not any((raw/'px').glob('*.json'))
