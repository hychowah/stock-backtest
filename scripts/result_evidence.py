"""Version-1 bounded financial evidence, separate from financial contract 1.

Completed evidence binds every piece and its original metadata. Reading evidence
neither calculates nor accesses financial inputs. Its owner controls storage and
lifetime. Streams are caller-owned binary files, initially empty for writing and
immutable/seekable for reading. This module opens no file, database, job or lock.

A period is a header followed by individual holdings and an end marker. Thus a
period may exceed a piece or record limit. JSON records can span pieces; scalars
and individual holdings must fit the declared record bound. No field is projected
or rounded. Piece checksums and an ordered record digest bind the final manifest.

Limits bound encoded bytes, not Python allocations, filesystem blocks or process
memory. Encoding/decoding retains bounded records and header/final metadata,
plus scalar encoder temporaries. The reducer retains its current book separately.
The caller declares a total byte ceiling and controls publication and cleanup.
A failed writer is unusable; its incomplete output must never be published.

This is an unconnected building block. It changes no application protocol,
snapshot, checkpoint, routing or admission limit.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
import math
import struct

import portfolio_results

FORMAT_VERSION = 1
MAX_PIECE_BYTES = 1024*1024
MAX_RECORD_BYTES = 8*1024*1024
MAX_DEPTH = 64
_FRAME = struct.Struct('!IB')  # payload length, last piece of this JSON record
_CHECKSUM_BYTES = 32


def _limits(max_bytes, piece_bytes, record_bytes):
    if (type(max_bytes) is not int or max_bytes <= 0
            or type(piece_bytes) is not int or not 1 <= piece_bytes <= MAX_PIECE_BYTES
            or type(record_bytes) is not int or not 1 <= record_bytes <= MAX_RECORD_BYTES):
        raise ValueError('Invalid evidence byte limits.')


def _json_value(value, record_bytes, depth=0):
    if depth > MAX_DEPTH:
        raise ValueError('Evidence exceeds its nesting bound.')
    if type(value) is dict:
        for key, part in value.items():
            if type(key) is not str:
                raise ValueError('Evidence object keys must be strings.')
            _json_value(key, record_bytes, depth+1)
            _json_value(part, record_bytes, depth+1)
    elif type(value) is list:
        for part in value:
            _json_value(part, record_bytes, depth+1)
    elif type(value) is str:
        if len(value) > record_bytes:
            raise ValueError('Evidence exceeds its record byte bound.')
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError('Evidence numbers must be finite.')
    elif value is not None and type(value) not in (int, bool):
        raise ValueError('Evidence must contain detached JSON values.')


def _day(value):
    if type(value) is not str:
        raise ValueError('Evidence dates must be canonical ISO dates.')
    try: parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError('Evidence dates must be canonical ISO dates.') from None
    if str(parsed) != value:
        raise ValueError('Evidence dates must be canonical ISO dates.')
    return value


class _Order:
    """Structural completeness only; financial arithmetic stays in the reducer."""
    def __init__(self):
        self.header = self.footer = None
        self.trials = self.periods = self.holdings = self.records = 0
        self.active_trial = self.active_period = False
        self.trial_periods = self.period_holdings = self.expected_holdings = 0
        self.first_entry = self.last_exit = None
        self.final_period = False

    def accept(self, record, digest):
        if type(record) is not dict or self.footer is not None:
            raise ValueError('Evidence follows completion or has an invalid record.')
        kind = record.get('type')
        fields = dict(header={'type','format_version','result_contract','trials','metadata'},
            trial={'type','number'}, period={'type','number','value'}, holding={'type','value'},
            end_period={'type'}, end_trial={'type','periods','summary'},
            complete={'type','trials','periods','holdings','records','sha256','summary'})
        if type(kind) is not str or kind not in fields or set(record) != fields[kind]:
            raise ValueError('Unsupported evidence record.')
        if self.header is None:
            if (kind != 'header' or type(record['format_version']) is not int
                    or record['format_version'] != FORMAT_VERSION
                    or type(record['result_contract']) is not int
                    or record['result_contract'] != portfolio_results.CONTRACT_VERSION
                    or type(record['trials']) is not int or not 1 <= record['trials'] <= 100
                    or type(record['metadata']) is not dict):
                raise ValueError('Unsupported evidence header.')
            self.header = record
        elif kind == 'trial':
            if (self.active_trial or self.trials >= self.header['trials']
                    or type(record['number']) is not int or record['number'] != self.trials+1):
                raise ValueError('Evidence trials must be contiguous and ordered.')
            self.active_trial = True
            self.trial_periods = 0
            self.first_entry = self.last_exit = None
            self.final_period = False
        elif kind == 'period':
            value = record['value']
            if (not self.active_trial or self.active_period or self.final_period
                    or type(record['number']) is not int or record['number'] != self.trial_periods+1
                    or type(value) is not dict or 'holdings' in value
                    or not {'entry','exit','names','portfolio','spy','is_final_period'} <= value.keys()
                    or type(value['names']) is not int or value['names'] < 0
                    or type(value['is_final_period']) is not bool):
                raise ValueError('Evidence period identity or ordering differs.')
            entry, exit_day = _day(value['entry']), _day(value['exit'])
            if entry >= exit_day or self.last_exit is not None and entry != self.last_exit:
                raise ValueError('Evidence period dates are not contiguous.')
            self.first_entry = self.first_entry or entry
            self.last_exit = exit_day
            self.final_period = value['is_final_period']
            self.expected_holdings = value['names']
            self.period_holdings = 0
            self.active_period = True
        elif kind == 'holding':
            if (not self.active_period or self.period_holdings >= self.expected_holdings
                    or type(record['value']) is not dict
                    or not portfolio_results.HOLDING_FIELDS.union(('weight','contribution_pp')) <= record['value'].keys()):
                raise ValueError('Evidence holding count or schema differs.')
            self.period_holdings += 1
            self.holdings += 1
        elif kind == 'end_period':
            if not self.active_period or self.period_holdings != self.expected_holdings:
                raise ValueError('Evidence period has incomplete holdings.')
            self.active_period = False
            self.trial_periods += 1
            self.periods += 1
        elif kind == 'end_trial':
            summary = record['summary']
            if (not self.active_trial or self.active_period or not self.final_period
                    or not self.trial_periods or type(record['periods']) is not int
                    or record['periods'] != self.trial_periods or type(summary) is not dict
                    or 'periods' in summary
                    or not {'start','end','growth','spy_growth','cagr','spy_cagr','coverage'} <= summary.keys()
                    or _day(summary['start']) > self.first_entry or _day(summary['end']) != self.last_exit):
                raise ValueError('Evidence trial is incomplete or its summary differs.')
            self.active_trial = False
            self.trials += 1
        elif kind == 'complete':
            if (self.active_trial or self.trials != self.header['trials']
                    or any(type(record[key]) is not int or record[key] != getattr(self,key)
                           for key in ('trials','periods','holdings','records'))
                    or record['sha256'] != digest or type(record['summary']) is not dict
                    or 'trial_results' in record['summary']):
                raise ValueError('Evidence completion manifest differs.')
            self.footer = record
        else:
            raise ValueError('Evidence header may occur only once.')
        self.records += 1


class Writer:
    """Write ordered complete evidence to an empty caller-owned binary stream.

    Calls are synchronous backpressure boundaries. finish() writes the completion
    manifest only after all declared trials are complete. It does not publish,
    flush, fsync or close the stream; those operations belong to its owner.
    """
    def __init__(self, stream, *, trials, metadata, max_bytes,
                 piece_bytes=MAX_PIECE_BYTES, record_bytes=MAX_RECORD_BYTES, checkpoint=None):
        _limits(max_bytes,piece_bytes,record_bytes)
        if stream.tell() != 0 or stream.seek(0,2) != 0:
            raise ValueError('Evidence output must be empty.')
        self.stream, self.max_bytes = stream, max_bytes
        self.piece_bytes, self.record_bytes = piece_bytes, record_bytes
        self.checkpoint = checkpoint
        self.bytes_written = self.peak_piece_bytes = self.peak_record_bytes = 0
        self.failed = False
        self._order, self._digest = _Order(), hashlib.sha256()
        self._write(dict(type='header',format_version=FORMAT_VERSION,
            result_contract=portfolio_results.CONTRACT_VERSION,trials=trials,metadata=metadata))

    def _write(self, record):
        if self.failed or self._order.footer is not None:
            raise ValueError('Evidence writer is failed or complete.')
        try:
            if self.checkpoint is not None: self.checkpoint()
            _json_value(record,self.record_bytes)
            self._order.accept(record,self._digest.hexdigest())
            buffer = bytearray()
            record_size = 0
            record_digest = hashlib.sha256()

            def piece(last):
                if self.checkpoint is not None: self.checkpoint()
                data = bytes(buffer)
                header = _FRAME.pack(len(data),last)
                checksum = hashlib.sha256(bytes([last])+data).digest()
                size = len(header)+len(data)+len(checksum)
                if self.bytes_written+size > self.max_bytes:
                    raise ValueError('Evidence exceeds its total byte bound.')
                for part in (header,data,checksum):
                    if self.stream.write(part) != len(part):
                        raise OSError('Evidence stream write was incomplete.')
                self.bytes_written += size
                self.peak_piece_bytes = max(self.peak_piece_bytes,len(data))
                buffer.clear()

            encoder = json.JSONEncoder(allow_nan=False,separators=(',',':'))
            for token in encoder.iterencode(record):
                # iterencode can return an entire escaped string scalar. Slice
                # it before byte encoding; the separate scalar/record cap is
                # still needed to bound the encoder's own string temporary.
                for offset in range(0,len(token),self.piece_bytes):
                    data = token[offset:offset+self.piece_bytes].encode('ascii')
                    record_size += len(data)
                    if record_size > self.record_bytes:
                        raise ValueError('Evidence exceeds its record byte bound.')
                    record_digest.update(data)
                    position = 0
                    while position < len(data):
                        if len(buffer) == self.piece_bytes: piece(0)
                        count = min(self.piece_bytes-len(buffer),len(data)-position)
                        buffer.extend(data[position:position+count]); position += count
            piece(1)
            self.peak_record_bytes = max(self.peak_record_bytes,record_size)
            if record['type'] != 'complete': self._digest.update(record_digest.digest())
        except BaseException:
            self.failed = True
            raise

    def start_trial(self, number):
        self._write(dict(type='trial',number=number))

    def period(self, value):
        """Accept one detached complete period; never retain its holding rows."""
        try:
            if type(value) is not dict or type(value.get('holdings')) is not list:
                raise ValueError('Evidence requires a complete period.')
            self._write(dict(type='period',number=self._order.trial_periods+1,
                value={key:part for key,part in value.items() if key != 'holdings'}))
            for holding in value['holdings']:
                self._write(dict(type='holding',value=holding))
            self._write(dict(type='end_period'))
        except BaseException:
            self.failed = True
            raise

    def end_trial(self, summary):
        self._write(dict(type='end_trial',periods=self._order.trial_periods,summary=summary))

    def finish(self, summary):
        """Bind original batch metadata and return the completed manifest."""
        manifest = dict(type='complete',trials=self._order.trials,periods=self._order.periods,
            holdings=self._order.holdings,records=self._order.records,
            sha256=self._digest.hexdigest(),summary=summary)
        self._write(manifest)
        return deepcopy(manifest)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Duplicate evidence object key.')
        result[key] = value
    return result


class Reader:
    """Validate completion before exposing immutable stored evidence.

    records() rereads bounded records in order, without collecting periods or
    trials. The caller pins immutable bytes through each read. This sequential
    codec is shared infrastructure; random-access indexes belong to its stores.
    No current financial generation is required. The stream remains caller-owned.
    """
    def __init__(self, stream, *, max_bytes, piece_bytes=MAX_PIECE_BYTES,
                 record_bytes=MAX_RECORD_BYTES, checkpoint=None):
        _limits(max_bytes,piece_bytes,record_bytes)
        self.stream, self.max_bytes = stream, max_bytes
        self.piece_bytes, self.record_bytes = piece_bytes, record_bytes
        self.checkpoint = checkpoint
        self.bytes_read = self.peak_piece_bytes = self.peak_record_bytes = 0
        self._header = self._manifest = None
        for record in self._records():
            if record['type'] == 'header': self._header = record
            elif record['type'] == 'complete': self._manifest = record

    @property
    def metadata(self): return deepcopy(self._header['metadata'])

    @property
    def manifest(self): return deepcopy(self._manifest)

    def records(self):
        return self._records()

    def _records(self):
        self.stream.seek(0)
        order, digest = _Order(), hashlib.sha256()
        self.bytes_read = 0
        buffer = bytearray()
        record_digest = hashlib.sha256()
        while True:
            if self.checkpoint is not None: self.checkpoint()
            header = self.stream.read(_FRAME.size)
            if not header:
                if buffer or order.footer is None:
                    raise ValueError('Evidence ended before completion.')
                return
            if len(header) != _FRAME.size:
                raise ValueError('Truncated evidence frame.')
            size,last = _FRAME.unpack(header)
            if not 1 <= size <= self.piece_bytes or last not in (0,1):
                raise ValueError('Evidence frame exceeds its piece bound or has invalid flags.')
            self.bytes_read += _FRAME.size+size+_CHECKSUM_BYTES
            if self.bytes_read > self.max_bytes:
                raise ValueError('Evidence exceeds its total byte bound.')
            if len(buffer)+size > self.record_bytes:
                raise ValueError('Evidence exceeds its record byte bound.')
            data = self.stream.read(size)
            checksum = self.stream.read(_CHECKSUM_BYTES)
            if len(data) != size or len(checksum) != _CHECKSUM_BYTES:
                raise ValueError('Truncated evidence frame.')
            if hashlib.sha256(bytes([last])+data).digest() != checksum:
                raise ValueError('Evidence piece checksum differs.')
            buffer.extend(data);record_digest.update(data)
            self.peak_piece_bytes = max(self.peak_piece_bytes,size)
            self.peak_record_bytes = max(self.peak_record_bytes,len(buffer))
            if not last: continue
            try: record = json.loads(buffer,object_pairs_hook=_object)
            except (ValueError,UnicodeError,RecursionError) as error:
                raise ValueError('Invalid evidence JSON.') from error
            _json_value(record,self.record_bytes)
            order.accept(record,digest.hexdigest())
            if record['type'] == 'complete':
                if self._manifest is not None and record != self._manifest:
                    raise ValueError('Evidence changed after validation.')
                # Completion cannot be exposed until EOF proves there are no
                # trailing bytes, including an incomplete next frame.
                if self.stream.read(1):
                    raise ValueError('Evidence has trailing bytes.')
            else: digest.update(record_digest.digest())
            buffer.clear();record_digest = hashlib.sha256()
            yield record
