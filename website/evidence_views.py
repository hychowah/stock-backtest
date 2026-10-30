"""Bounded presentation scans of immutable evidence. No financial dependencies.

A page limits retained presentation data, never stored evidence. Following all
cursors visits every matching row exactly once in original order. Scans retain
no index and never assemble a complete period or trial.
"""
import json

PAGE_ROWS=64
PAGE_BYTES=256*1024
RESPONSE_BYTES=32*1024**2


def encode(value,limit=RESPONSE_BYTES):
    """Size and send identical UTF-8 JSON, escaping lone surrogates losslessly.

    ASCII escaping can expand a codec-valid UTF-8 record beyond its byte bound.
    This serializer is shared by page sizing and actual HTTP response output.
    """
    body=bytearray()
    for piece in json.JSONEncoder(ensure_ascii=False,allow_nan=False,separators=(',',':')).iterencode(value):
        for offset in range(0,len(piece),65536):
            data=piece[offset:offset+65536].encode('utf-8',errors='backslashreplace')
            if len(body)+len(data)>limit:raise ValueError('Evidence response exceeds its byte limit.')
            body.extend(data)
    return bytes(body)


def integer(value,minimum=0):
    if type(value) is not int or value<minimum:raise ValueError('Invalid evidence selection.')
    return value


def records(reader,trial):
    integer(trial,1)
    if trial>reader.manifest['trials']:raise ValueError('Stored trial not found.')
    active=False
    for record in reader.records():
        if record['type']=='trial':active=record['number']==trial
        if active:yield record
        if active and record['type']=='end_trial':return
    raise ValueError('Stored trial is incomplete.')


def trial(reader,number):
    count=empty=short=0
    # The original trial summary owns its requested rank slice.
    for record in records(reader,number):
        if record['type']=='end_trial':summary=record['summary']
    requested=summary['options'].get('rank_to',50)-summary['options'].get('rank_from',1)+1
    for record in records(reader,number):
        if record['type']=='period':
            names=record['value']['names'];count+=1;empty+=names==0;short+=names<requested
    return dict(summary=summary,periods=count,empty=empty,short=short)


def periods(reader,number):
    for record in records(reader,number):
        if record['type']=='period':yield dict(number=record['number'],value=record['value'])


def holdings(reader,number,period):
    integer(period,1);active=False;found=False
    for record in records(reader,number):
        if record['type']=='period':
            active=record['number']==period;found=found or active
        elif active and record['type']=='holding':yield record['value']
        elif active and record['type']=='end_period':return
    if not found:raise ValueError('Stored period not found.')


def page(rows,cursor=0):
    integer(cursor)
    result=[];size=0;total=0;full=False
    for row in rows:
        index=total;total+=1
        if index<cursor or full:continue
        encoded=len(encode(row,16*1024**2))
        if result and (len(result)>=PAGE_ROWS or size+encoded>PAGE_BYTES):
            full=True;continue
        result.append(row);size+=encoded
    if cursor>total:raise ValueError('Invalid evidence cursor.')
    end=cursor+len(result)
    return dict(rows=result,cursor=cursor,next=end if end<total else None,total=total)


def read(reader,selection):
    operation=selection.get('operation');number=selection.get('trial',1)
    if operation=='trial':return trial(reader,number)
    if operation=='periods':return page(periods(reader,number),selection.get('cursor',0))
    if operation=='holdings':return page(holdings(reader,number,selection.get('period')),selection.get('cursor',0))
    raise ValueError('Unknown evidence inspection.')
