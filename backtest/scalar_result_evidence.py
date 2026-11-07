"""Scalar codec 2 on the existing bounded/checksummed physical evidence framing.

Application artifact 4 and financial contract 2 are independently allocated.
Owners retain streams and all lifetime/resource charges. No input/library access
is required to read, copy or export a completed scalar result.
"""
import hashlib

from backtest import result_evidence as framing, portfolio_results
from backtest.application import strategy_requests

FORMAT_VERSION = 2
EXTRA = frozenset(('scope','evaluation','admission','lanes','selection'))


class Order(framing._Order):
    def accept(self, record, digest):
        kind = record.get('type') if type(record) is dict else None
        if self.footer is not None:
            raise ValueError('Scalar evidence follows completion.')
        if self.header is None:
            if (kind != 'header' or set(record) != {'type','format_version','result_contract','trials','metadata'}
                    or type(record['format_version']) is not int or record['format_version'] != FORMAT_VERSION
                    or type(record['result_contract']) is not int or record['result_contract'] != 2
                    or type(record['metadata']) is not dict or record['metadata'].get('mode') not in ('latest','january','custom','random')
                    or type(record['trials']) is not int
                    or (record['trials'] != 0 if record['metadata']['mode']=='latest' else not 1 <= record['trials'] <= 100)):
                raise ValueError('Unsupported scalar evidence header.')
            strategy_requests.require_strategy(strategy_requests.CapturedStrategy(
                strategy_requests._encode(record['metadata'].get('options',{}).get('strategy'), strategy_requests.STRATEGY_BYTES)))
            self.header = record; self.records += 1; self.screens = 0
            self.scope=None;self.receipt=None;self.chunks={};self.selected=None
            self.seen_scopes=set()
            return
        if kind in EXTRA:
            if set(record) != {'type','value'} or type(record['value']) is not dict:
                raise ValueError('Malformed scalar explanation record.')
            value = record['value']
            scope=value.get('id') if kind=='scope' else value.get('scope')
            if type(scope) is not str or not scope or self.scope is not None and scope!=self.scope:
                raise ValueError('Scalar scope explanation identity differs.')
            if self.scope is None:
                if scope in self.seen_scopes or len(self.seen_scopes)>=16384:
                    raise ValueError('Scalar scope identity is repeated or exceeds its bound.')
                self.seen_scopes.add(scope)
            self.scope=scope
            if kind == 'evaluation':
                if type(value.get('scope')) is not str or type(value.get('chunk')) is not int or type(value.get('block')) is not dict:
                    raise ValueError('Malformed scalar evaluation block.')
                block = value['block']
                if block.get('format') != 'formula-evaluation' or block.get('version') != 1:
                    raise ValueError('Unsupported detached formula evaluation.')
                if value['chunk']!=len(self.chunks) or type(block.get('requests')) is not list or not block['requests']:
                    raise ValueError('Scalar evaluation chunk sequence differs.')
                self.chunks[value['chunk']]=len(block['requests'])
            elif kind == 'scope':
                if value.get('population') != 'complete-prepared-scope' or type(value.get('rows')) is not int or not 0 <= value['rows'] <= 8192:
                    raise ValueError('Malformed complete scope receipt.')
                if self.receipt is not None:raise ValueError('Duplicate scalar scope receipt.')
                self.receipt=value
            elif kind=='selection':
                if self.receipt is None or self.selected is not None or type(value.get('selected',{}).get('selected')) is not list:
                    raise ValueError('Scalar selection receipt differs.')
                self.selected=len(value['selected']['selected'])
            self.records += 1
            return
        if kind == 'screen':
            if self.header['metadata']['mode'] != 'latest' or set(record) != {'type','value'}:
                raise ValueError('Screen evidence is only valid for latest mode.')
            row = record['value']
            self._links(row)
            portfolio_results.validate_scalar_row(row)
            if any(key in row for key in ('return_value','contribution_pp','weight','exit')):
                raise ValueError('Latest scalar evidence contains future return fields.')
            self.holdings += 1; self.screens += 1; self.records += 1
            return
        if kind == 'holding':
            if (not self.active_period or self.period_holdings >= self.expected_holdings
                    or type(record) is not dict or set(record) != {'type','value'}):
                raise ValueError('Scalar holding ordering differs.')
            self._links(record['value'])
            portfolio_results.validate_scalar_row(record['value'])
            if not portfolio_results.SCALAR_HOLDING_FIELDS.union(('weight','contribution_pp')) <= record['value'].keys():
                raise ValueError('Scalar holding is missing financial fields.')
            self.period_holdings += 1; self.holdings += 1; self.records += 1
            return
        if kind == 'complete' and self.header['metadata']['mode'] == 'latest':
            if (set(record) != {'type','trials','periods','holdings','records','sha256','summary'}
                    or any(type(record[key]) is not int or record[key] != getattr(self,key) for key in ('trials','periods','holdings','records'))
                    or record['sha256'] != digest or type(record['summary']) is not dict):
                raise ValueError('Scalar screen completion differs.')
            if self.selected is None or self.selected!=self.screens:raise ValueError('Incomplete scalar screen selection.')
            self.footer = record; self.records += 1
            return
        if kind=='period':
            if self.receipt is None or self.selected!=record.get('value',{}).get('names'):raise ValueError('Period has no complete scalar selection.')
        if kind=='complete' and self.scope is not None:raise ValueError('Unconsumed scalar scope evidence.')
        super().accept(record, digest)
        if kind=='end_period':
            self.scope=None;self.receipt=None;self.chunks={};self.selected=None

    def _links(self,row):
        evidence=row.get('scalar_evidence',{}) if type(row) is dict else {}
        if self.receipt is None or self.selected is None or evidence.get('scope')!=self.scope or type(evidence.get('lanes')) is not dict:
            raise ValueError('Scalar selected row has no complete scope evidence.')
        for link in evidence['lanes'].values():
            if type(link) is not dict or link.get('scope')!=self.scope:raise ValueError('Scalar evidence scope reference differs.')
            if 'chunk' in link and (link['chunk'] not in self.chunks or type(link.get('request')) is not int or not 0<=link['request']<self.chunks[link['chunk']]):
                raise ValueError('Scalar evaluation reference is unresolved.')


class Writer(framing.Writer):
    def __init__(self, stream, *, trials, metadata, max_bytes,
                 piece_bytes=framing.MAX_PIECE_BYTES, record_bytes=framing.MAX_RECORD_BYTES, checkpoint=None):
        self._initialize(stream,max_bytes,piece_bytes,record_bytes,checkpoint)
        self._order = Order()
        self._write(dict(type='header',format_version=FORMAT_VERSION,result_contract=2,trials=trials,metadata=metadata))
    def evidence(self, record):
        if record.get('type') not in EXTRA:
            raise ValueError('Unknown scalar explanation record.')
        self._write(record)
    def screen(self, row):
        self._write(dict(type='screen',value=row))


class Reader(framing.Reader):
    def _records(self, *, physical=None):
        order, digest = Order(), hashlib.sha256()
        for record, raw_digest, start, end in framing._physical_records(
                self.stream,0,self.max_bytes,self.piece_bytes,self.record_bytes,self.checkpoint,observe=self._observe,physical=physical):
            self.bytes_read = end
            order.accept(record,digest.hexdigest())
            if record['type'] == 'complete':
                if self._manifest is not None and record != self._manifest:
                    raise ValueError('Scalar evidence changed after validation.')
                if self.stream.read(1):raise ValueError('Scalar evidence has trailing bytes.')
            else:digest.update(raw_digest)
            yield record
        if order.footer is None:raise ValueError('Scalar evidence ended before completion.')

