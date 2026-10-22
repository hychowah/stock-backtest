"""Validated raw assets and download evidence tied to their saved contents.

A completed request is evidence only for the exact valid file we published.
Missing, damaged, manually replaced and legacy assets retain their usable rows,
but cannot inherit empty-request evidence from a different file generation.
"""
from datetime import date, timedelta
import hashlib
import json

import run


def read_json(path, default=None):
    if not path.exists():return default
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.download')
    temporary.write_bytes(json.dumps(value,allow_nan=False).encode('utf-8'))
    temporary.replace(path)


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
        day=run.parse_day(row.get('date'));value=run.num(row.get(field))
        if day and value is not None and (field=='month3' or value>0):result[str(day)]=row
    return [result[day] for day in sorted(result)]


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

    Publication preserves saved values and light prices. Evidence names the
    expected file content and original saved span. A half-published update
    cannot match the wrong file. Unfinished managed windows remain missing
    even if parallel results extend the actual date span on both sides.
    """
    def __init__(self,path,field,*,stock=False):
        self.path=path;self.field=field;self.stock=stock
        self.key='px/'+path.name if stock else path.name
        self.payload={} if stock else [];self.valid=False;self.digest=None
        if path.exists():
            content=path.read_bytes()
            try:
                self.payload=json.loads(content)
                values=self.payload.get('div') if stock and isinstance(self.payload,dict) else self.payload if not stock else None
                self.valid=isinstance(values,list) and all(isinstance(row,dict) for row in values)
                if self.valid:self.digest=hashlib.sha256(content).hexdigest()
            except (ValueError,UnicodeDecodeError):pass
        values=self.payload.get('div',[]) if stock and isinstance(self.payload,dict) else self.payload if not stock else []
        self.rows=series(values,field)
        # A nonempty response with no usable data is an invalid asset, not a
        # valid empty history. Real empty histories are represented by [].
        if values and not self.rows:self.valid=False;self.digest=None

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

    def publish(self,batch,start,end,ledger,ledger_path):
        valid=series(batch,self.field)
        if not isinstance(batch,list) or (batch and len(valid)!=len(batch)):
            raise ValueError('The provider returned invalid dated values. Saved files were kept.')
        if any(not start<=row['date'][:10]<=end for row in valid):
            raise ValueError('The provider returned values outside the requested dates. Saved files were kept.')
        windows=self.checked(ledger)+[[start,end]]
        by_day={row['date'][:10]:row for row in self.rows}
        for row in valid:by_day.setdefault(row['date'][:10],row)
        merged=[by_day[day] for day in sorted(by_day,reverse=True)]
        self._store(merged,windows,ledger,ledger_path)

    def repair(self,ledger,ledger_path):
        """Normalize salvageable rows without claiming any new requested dates."""
        if self.path.exists() and not self.valid and self.rows:
            self._store(self.rows,[],ledger,ledger_path)

    def _store(self,merged,windows,ledger,ledger_path):
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
        previous=self.evidence(ledger)
        if previous:entry['previous']={key:value for key,value in previous.items() if key!='previous'}
        # Evidence can only apply when the exact corresponding asset exists.
        # Publish its expected hash first: a crash before asset replacement
        # leaves a mismatch, while a crash after it retains all known holes.
        write_json(ledger_path,{**ledger,self.key:entry})
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_name(self.path.name+'.download')
        temporary.write_bytes(content);temporary.replace(self.path)
        self.payload=value;self.rows=series(merged,self.field);self.valid=True;self.digest=digest
        ledger[self.key]=entry
