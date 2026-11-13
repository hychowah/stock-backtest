"""Complete stored-evidence CSVs, streamed as bounded UTF-8 attachment bytes.

Formatting matches the existing JavaScript downloads: every cell is quoted,
records have CRLF separators, and there is no final separator. Reading needs
no current input generation, candidate readiness or financial calculation.
"""
import math
import re
import json
from backtest.application import evidence_views as evidence_views
CHUNK_BYTES=65536
HOLDINGS=['period_start','period_end','rank','symbol','name','exchange','sector',
    'market_cap','enterprise_value','metric','metric_multiple','metric_yield',
    'fiscal','entry','exit','return_value','weight','contribution_pp','status']
RETURNS=['entry','exit','names','portfolio','spy']
RANDOM=['trial','start','first_trade','end','cash_days','periods','cagr','spy_cagr',
    'excess_cagr','total_return','growth','spy_growth','empty_periods','short_periods','seed']


def number(value):
    """ECMAScript decimal spelling of a finite float64, including exponent bounds."""
    value=float(value)
    if not math.isfinite(value):raise ValueError('CSV values must be finite.')
    if value==0:return '0'
    sign='-' if value<0 else '';value=abs(value)
    mantissa,_,exponent=repr(value).lower().partition('e')
    digits=mantissa.replace('.','').lstrip('0')
    exponent=int(exponent or 0)
    decimal=(mantissa.find('.') if '.' in mantissa else len(mantissa))+exponent
    # Leading fractional zeroes shift the significant decimal position.
    decimal-=len(mantissa.replace('.',''))-len(mantissa.replace('.','').lstrip('0'))
    digits=digits.rstrip('0') or '0'
    if 0<decimal<=21:
        text=digits[:decimal]+('.'+digits[decimal:] if decimal<len(digits) else '0'*(decimal-len(digits)))
    elif -6<decimal<=0:text='0.'+'0'*(-decimal)+digits
    else:
        exp=decimal-1
        text=digits[0]+('.'+digits[1:] if len(digits)>1 else '')+'e'+('+' if exp>=0 else '')+str(exp)
    return sign+text


def string(value):
    if value is None:return ''
    if type(value) is bool:return 'true' if value else 'false'
    if isinstance(value,(int,float)):return number(value)
    if isinstance(value,list):return ','.join('' if v is None else string(v) for v in value)
    if isinstance(value,dict):return '[object Object]'
    return str(value)


def _selection(reader,kind,trial):
    if reader.format_version==2 and kind in ('evidence','screen'):
        return ('scalar-complete.evidence' if kind=='evidence' else 'scalar-screen.csv'),None
    if reader.format_version==2 and reader.metadata['mode']=='latest':raise ValueError('Latest screen has no historical export.')
    if kind=='random':
        configuration=reader.manifest['summary'].get('configuration')
        if not configuration:raise ValueError('This result has no random-trial summary.')
        return 'random-dates-seed-'+string(configuration['seed'])+'.csv',None
    if kind not in ('holdings','returns'):raise ValueError('Unknown complete export.')
    summary,_=reader.trial_summary(trial)
    return ('scheduled-'+kind+'-'+summary['start']+'-'+summary['end']+'.csv',
            summary['options'].get('metric','ev_ebitda'))


def rows(reader,kind,trial):
    yield from _rows(reader,kind,trial,_selection(reader,kind,trial)[1])


def _rows(reader,kind,trial,metric):
    options=reader.metadata.get('options',{})
    context=dict(market=options['market'],currency='USD') if 'market' in options else {}
    if reader.format_version==2 and kind in ('holdings','screen'):
        keys=list(context)+['rank','symbol','name','exchange','sector','ranking_value','ranking_unit','ranking_display','ranking_direction','market_cap','enterprise_value','fiscal','scalar_evidence']
        if kind=='holdings':keys+=['period_start','period_end','entry','exit','return_value','weight','contribution_pp','status']
        # A chain adds each step's value and its rank or pass; older results have no step trail.
        # A sleeve strategy adds one column: each picking sleeve and its final rank there.
        strategy=options.get('strategy',{})
        steps=strategy['steps'] if strategy.get('version')==2 else []
        sleeves=strategy.get('sleeves',[])
        keys+=[f'step_{i}_{part}' for i in range(1,len(steps)+1) for part in ('value','outcome')]+(['sleeves'] if sleeves else [])
        yield keys
        source=reader.verified_records() if kind=='screen' else evidence_views.records(reader,trial)
        for record in source:
            if record['type']=='period':period=record['value']
            elif record['type']==('screen' if kind=='screen' else 'holding'):
                row=dict(record['value'],**context)
                if kind=='holdings':row.update(period_start=period['entry'],period_end=period['exit'])
                evidence=row['scalar_evidence']
                for i,step in enumerate(steps):
                    # A field step's value is the holding's own field; others are in lane 's<i>'.
                    lane=evidence['lanes'].get('s'+str(i),{})
                    row[f'step_{i+1}_value']=row[step['source']['field']] if step['source']['kind']=='field' else lane.get('canonical',lane.get('value'))
                    row[f'step_{i+1}_outcome']='pass' if step['kind']=='filter' else evidence['steps'][i]
                if sleeves:
                    row['sleeves']='; '.join(sleeves[pick['sleeve']]['name']+' #'+str(next(rank for rank in reversed(pick['steps']) if rank is not None))
                                             for pick in evidence['sleeves'])
                row['scalar_evidence']=json.dumps(evidence,sort_keys=True,separators=(',',':'))
                yield [row.get(k) for k in keys]
        return
    if kind=='random':
        summary=reader.manifest['summary'];configuration=summary.get('configuration')
        if not configuration:raise ValueError('This result has no random-trial summary.')
        keys=list(context)+RANDOM+(['interval_unit','interval_count'] if configuration.get('calendar') else ['months'])+['dates']
        yield keys
        for row in summary['trials']:
            values=dict(row,**context,seed=configuration['seed'],dates=';'.join(row['dates']))
            if configuration.get('calendar'):
                values.update(interval_unit=configuration['calendar']['interval']['unit'],interval_count=configuration['calendar']['interval']['count'])
            else:values['months']=configuration['months']
            yield [values.get(k) for k in keys]
    elif kind in ('holdings','returns'):
        keys=list(context)+(HOLDINGS if kind=='holdings' else RETURNS);yield keys
        for record in evidence_views.records(reader,trial):
            if record['type']=='period':
                period=record['value']
                if kind=='returns':
                    value=dict(period,**context)
                    yield [value.get(k) for k in keys]
            elif kind=='holdings' and record['type']=='holding':
                value=dict(record['value'],**context,period_start=period['entry'],period_end=period['exit'],metric=metric)
                yield [value.get(k) for k in keys]
    else:raise ValueError('Unknown complete export.')


def filename(reader,kind,trial=1):
    return _selection(reader,kind,trial)[0]


class Prepared:
    """One attachment borrowing a pinned reader; no rows or bytes are retained.

    Resolve selection once and count exact output before headers. chunks() starts
    a fresh bounded traversal with identical formatting. Passes are sequential;
    the caller owns reader lifetime and transport closure. Never share requests.
    """
    def __init__(self,reader,kind,trial):
        self.reader,self.kind,self.trial=reader,kind,trial
        self.filename,self.metric=_selection(reader,kind,trial)
        self.content_length=sum(len(chunk) for chunk in self.chunks())

    @property
    def content_type(self):
        return 'application/octet-stream' if self.kind=='evidence' else 'text/csv; charset=utf-8'

    def chunks(self):
        if self.kind=='evidence':return self._evidence()
        return _csv(_rows(self.reader,self.kind,self.trial,self.metric))

    def _evidence(self):
        # Validate every record before exposing bytes, then stream the original
        # framed file. Header capture plus complete records resolve all links.
        for record in self.reader.verified_records():pass
        self.reader.stream.seek(0)
        while True:
            chunk=self.reader.stream.read(CHUNK_BYTES)
            if not chunk:return
            yield chunk


def prepare(reader,kind,trial=1):
    return Prepared(reader,kind,trial)


def csv(reader,kind,trial=1):
    """Retain at most one codec record, one cell spelling and a 64 KiB byte chunk."""
    yield from _csv(rows(reader,kind,trial))


def _csv(rows):
    buffer=bytearray();first_row=True
    for row in rows:
        tokens=[] if first_row else ['\r\n'];first_row=False
        for index,value in enumerate(row):
            if index:tokens.append(',')
            tokens.append('"')
            text=re.sub('[\ud800-\udfff]','\ufffd',string(value))
            # Splitting before escaping keeps large valid fields bounded too.
            for offset in range(0,len(text),8192):
                tokens.append(text[offset:offset+8192].replace('"','""'))
                if len(tokens)>8:
                    for token in tokens:
                        data=token.encode('utf-8',errors='replace')
                        while data:
                            take=min(CHUNK_BYTES-len(buffer),len(data));buffer.extend(data[:take]);data=data[take:]
                            if len(buffer)==CHUNK_BYTES:yield bytes(buffer);buffer.clear()
                    tokens=[]
            tokens.append('"')
        for token in tokens:
            data=token.encode('utf-8',errors='replace')
            while data:
                take=min(CHUNK_BYTES-len(buffer),len(data));buffer.extend(data[:take]);data=data[take:]
                if len(buffer)==CHUNK_BYTES:yield bytes(buffer);buffer.clear()
    if buffer:yield bytes(buffer)
