"""Private bounded decoder for canonical version-1 checkpoint JSON TEXT.

Only trials.payload compatibility uses this reader. Metadata and each holding
fit one codec record; complete periods may be larger. It opens no resources.
Canonical spelling, key order and duplicate rejection preserve the v1 contract.
"""
from backtest.runtime import backtest_control
import json

from backtest.runtime import backtest_control as backtest_control
from backtest import result_evidence as result_evidence


class Decoder:
    def __init__(self,stream,canonical):
        self.stream,self.canonical=stream,canonical
        self.buffer=b'';self.position=0;self.pending=None
        self.limit=result_evidence.MAX_RECORD_BYTES

    def byte(self):
        if self.pending is not None:
            value=self.pending;self.pending=None;return value
        if self.position==len(self.buffer):
            backtest_control.checkpoint()
            self.buffer=self.stream.read(65536);self.position=0
        if not self.buffer:return b''
        value=self.buffer[self.position:self.position+1];self.position+=1
        return value

    def expect(self,value):
        if self.byte()!=value:raise ValueError('Malformed legacy checkpoint JSON.')

    def value(self):
        raw=bytearray();depth=0;quoted=escaped=False
        first=self.byte()
        if not first:raise ValueError('Truncated legacy checkpoint JSON.')
        byte=first
        while True:
            if not quoted and depth==0 and raw and byte in (b',',b'}',b']',b''):
                self.pending=byte;break
            raw.extend(byte)
            if len(raw)>self.limit:raise ValueError('Legacy checkpoint exceeds its record byte bound.')
            if quoted:
                if escaped:escaped=False
                elif byte==b'\\':escaped=True
                elif byte==b'"':quoted=False
            elif byte==b'"':quoted=True
            elif byte in (b'{',b'['):
                depth+=1
                if depth>result_evidence.MAX_DEPTH:raise ValueError('Legacy checkpoint exceeds its nesting bound.')
            elif byte in (b'}',b']'):depth-=1
            if not quoted and depth==0 and first in (b'{',b'[',b'"'):break
            byte=self.byte()
            if not byte and (quoted or depth):raise ValueError('Truncated legacy checkpoint JSON.')
        try:
            text=raw.decode('utf8');value=json.loads(text)
            result_evidence._json_value(value,self.limit)
            if self.canonical(value)!=text:raise ValueError('Noncanonical legacy checkpoint evidence.')
            return value
        except (UnicodeError,TypeError,RecursionError) as error:
            raise ValueError('Malformed legacy checkpoint JSON.') from error

    def fields(self):
        self.expect(b'{');previous=None
        byte=self.byte()
        if byte==b'}':return
        self.pending=byte
        while True:
            key=self.value()
            if type(key) is not str or previous is not None and key<=previous:
                raise ValueError('Noncanonical legacy checkpoint keys.')
            previous=key;self.expect(b':')
            yield key
            byte=self.byte()
            if byte==b'}':return
            if byte!=b',':raise ValueError('Malformed legacy checkpoint object.')

    def array(self,read):
        self.expect(b'[');byte=self.byte()
        if byte==b']':return
        self.pending=byte
        while True:
            yield read()
            byte=self.byte()
            if byte==b']':return
            if byte!=b',':raise ValueError('Malformed legacy checkpoint array.')

    def period(self):
        value={}
        for key in self.fields():
            value[key]=list(self.array(self.value)) if key=='holdings' else self.value()
        return value


class LegacyTrial:
    def __init__(self,stream,canonical):
        self.stream,self.canonical=stream,canonical
        self._summary=None
        for _ in self.periods():pass

    @property
    def summary(self):return dict(self._summary)

    def periods(self):
        self.stream.seek(0);decoder=Decoder(self.stream,self.canonical);summary={};found=False;size=0
        for key in decoder.fields():
            if key=='periods':
                found=True
                yield from decoder.array(decoder.period)
            else:
                value=decoder.value();summary[key]=value
                size+=len(self.canonical({key:value}).encode('utf8'))
                if size>decoder.limit:raise ValueError('Legacy summary exceeds its record byte bound.')
        if not found or decoder.byte():raise ValueError('Incomplete or trailing legacy checkpoint evidence.')
        self._summary=summary
