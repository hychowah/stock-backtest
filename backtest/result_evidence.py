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

The legacy codec-1 writer/reader and eager admission retain their meaning.
open_reader() also dispatches the separate scalar codec 2; its application
artifact version and durable container belong to their application owners.
"""

from copy import deepcopy
from datetime import date
import hashlib
import json
import math
import struct

from backtest import portfolio_results as portfolio_results

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
    def __init__(self, first_trial=1):
        self.first_trial = first_trial
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
                    or type(record['number']) is not int or record['number'] != self.first_trial+self.trials):
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
        self._initialize(stream,max_bytes,piece_bytes,record_bytes,checkpoint)
        self._write(dict(type='header',format_version=FORMAT_VERSION,
            result_contract=portfolio_results.CONTRACT_VERSION,trials=trials,metadata=metadata))

    def _initialize(self,stream,max_bytes,piece_bytes,record_bytes,checkpoint):
        """Shared physical writer state; standalone trials omit the batch header."""
        _limits(max_bytes,piece_bytes,record_bytes)
        if stream.tell() != 0 or stream.seek(0,2) != 0:
            raise ValueError('Evidence output must be empty.')
        self.stream, self.max_bytes = stream, max_bytes
        self.piece_bytes, self.record_bytes = piece_bytes, record_bytes
        self.checkpoint = checkpoint
        self.bytes_written = self.peak_piece_bytes = self.peak_record_bytes = 0
        self.failed = False
        self._order, self._digest = _Order(), hashlib.sha256()
        self._trial_start = self._trial_digest = None

    def _write(self, record):
        if self.failed or self._order.footer is not None:
            raise ValueError('Evidence writer is failed or complete.')
        try:
            self.stream.seek(self.bytes_written)
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
                if self._trial_digest is not None:
                    for part in (header,data,checksum):self._trial_digest.update(part)
                self.bytes_written += size
                self.peak_piece_bytes = max(self.peak_piece_bytes,len(data))
                buffer.clear()

            # The C encoder writes the same ASCII bytes as the incremental one.
            # Pieces fill at fixed byte boundaries, so the frames are unchanged.
            data = json.dumps(record, allow_nan=False, separators=(',',':')).encode('ascii')
            record_size = len(data)
            if record_size > self.record_bytes:
                raise ValueError('Evidence exceeds its record byte bound.')
            record_digest.update(data)
            for offset in range(0, len(data), self.piece_bytes):
                if len(buffer) == self.piece_bytes: piece(0)
                buffer.extend(data[offset:offset+self.piece_bytes])
            piece(1)
            self.peak_record_bytes = max(self.peak_record_bytes,record_size)
            if record['type'] != 'complete': self._digest.update(record_digest.digest())
        except BaseException:
            self.failed = True
            raise

    @property
    def expected_trials(self):return self._order.header['trials']

    def start_trial(self, number):
        self.stream.seek(self.bytes_written)
        self._trial_start = self.bytes_written
        self._trial_digest = hashlib.sha256()
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
        # The writer already checked every record. Sealing must remain usable
        # with write-only streams; traversal later requires readable pinned bytes.
        view=TrialView._from_writer(self,summary)
        self._trial_digest = None
        return view

    def finish(self, summary):
        """Bind original batch metadata and return the completed manifest."""
        manifest = dict(type='complete',trials=self._order.trials,periods=self._order.periods,
            holdings=self._order.holdings,records=self._order.records,
            sha256=self._digest.hexdigest(),summary=summary)
        self._write(manifest)
        return deepcopy(manifest)


class SingleTrialWriter:
    """Seal one actual recorded trial using the existing TrialView encoding.

    The caller owns the empty binary stream. finish() returns a sealed view,
    not a batch manifest or committed checkpoint. No placeholder trials, batch
    header or completion record are written. On any failure discard the bytes.
    """
    def __init__(self,stream,*,number,max_bytes,piece_bytes=MAX_PIECE_BYTES,
                 record_bytes=MAX_RECORD_BYTES,checkpoint=None):
        if type(number) is not int or not 1<=number<=100:
            raise ValueError('Invalid sealed trial number.')
        self._writer=object.__new__(Writer)
        self._writer._initialize(stream,max_bytes,piece_bytes,record_bytes,checkpoint)
        self._writer._order=_Order(first_trial=number)
        self._writer._order.accept(dict(type='header',format_version=FORMAT_VERSION,
            result_contract=portfolio_results.CONTRACT_VERSION,trials=1,metadata={}),None)
        self._finished=False
        self._writer.start_trial(number)

    @property
    def failed(self):return self._writer.failed

    @failed.setter
    def failed(self,value):self._writer.failed=value

    @property
    def bytes_written(self):return self._writer.bytes_written

    @property
    def peak_piece_bytes(self):return self._writer.peak_piece_bytes

    @property
    def peak_record_bytes(self):return self._writer.peak_record_bytes

    def period(self,value):
        if self._finished:raise ValueError('Single-trial evidence is already sealed.')
        self._writer.period(value)

    def finish(self,summary):
        if self._finished:raise ValueError('Single-trial evidence is already sealed.')
        view=self._writer.end_trial(summary)
        self._finished=True
        return view


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
        physical = hashlib.sha256()
        for record in self._records(physical=physical):
            if record['type'] == 'header': self._header = record
            elif record['type'] == 'complete': self._manifest = record
        # Bind the proof to the exact pieces consumed by complete validation.
        self._proof = (self.bytes_read, physical.digest())

    def reopen(self, stream):
        """Open an independent reader after its complete bytes match this proof.

        The caller owns stream lifetime and immutability. No record collection
        or seek position is shared. Initial construction still validates every
        record; this operation verifies exact content, including unread suffixes.
        """
        if stream is self.stream:raise ValueError('An independent evidence stream is required.')
        self._verify_stream(stream)
        reader=object.__new__(type(self))
        reader.stream,reader.max_bytes=stream,self.max_bytes
        reader.piece_bytes,reader.record_bytes=self.piece_bytes,self.record_bytes
        reader.checkpoint=self.checkpoint
        reader.bytes_read=reader.peak_piece_bytes=reader.peak_record_bytes=0
        reader._header,reader._manifest=deepcopy(self._header),deepcopy(self._manifest)
        reader._proof=self._proof
        return reader

    def _verify_stream(self,stream):
        length, expected = self._proof
        stream.seek(0);physical=hashlib.sha256();size=0
        while True:
            if self.checkpoint is not None:self.checkpoint()
            data=stream.read(min(65536,length-size+1))
            if not data:break
            size+=len(data)
            if size>length:raise ValueError('Evidence changed after validation.')
            physical.update(data)
        if size!=length or physical.digest()!=expected:
            raise ValueError('Evidence changed after validation.')
        stream.seek(0)

    def verified_records(self):
        """Traverse exact, completely validated contents through bounded records.

        Before yielding, verify the entire stream, including an unvisited suffix.
        The original semantic validation remains authoritative. The caller owns
        stream lifetime and immutable bytes. records() keeps its independent
        validation behavior. No record collection or index is retained.
        """
        self._verify_stream(self.stream)
        for record,_,_,end in _physical_records(self.stream,0,self._proof[0],
                self.piece_bytes,self.record_bytes,self.checkpoint,
                observe=self._observe,validate_values=False):
            self.bytes_read=end
            yield record

    @property
    def format_version(self): return self._header['format_version']

    @property
    def metadata(self): return deepcopy(self._header['metadata'])

    @property
    def manifest(self): return deepcopy(self._manifest)

    def records(self):
        return self._records()

    def _observe(self,piece,record):
        self.peak_piece_bytes=max(self.peak_piece_bytes,piece)
        self.peak_record_bytes=max(self.peak_record_bytes,record)

    def _records(self, *, physical=None):
        order, digest = _Order(), hashlib.sha256()
        for record,raw_digest,start,end in _physical_records(self.stream,0,self.max_bytes,
                self.piece_bytes,self.record_bytes,self.checkpoint,observe=self._observe,physical=physical):
            self.bytes_read=end
            order.accept(record,digest.hexdigest())
            if record['type']=='complete':
                if self._manifest is not None and record != self._manifest:
                    raise ValueError('Evidence changed after validation.')
                if self.stream.read(1):raise ValueError('Evidence has trailing bytes.')
            else:digest.update(raw_digest)
            yield record
        if order.footer is None:raise ValueError('Evidence ended before completion.')

    def trials(self):
        """Yield sealed trial views while retaining no earlier trial evidence."""
        for _ in self._records():pass
        start=None
        for record,_,left,right in _physical_records(self.stream,0,self.max_bytes,
                self.piece_bytes,self.record_bytes,self.checkpoint):
            if record['type']=='trial':start=left;number=record['number']
            elif record['type']=='end_trial':
                sha=_range_digest(self.stream,start,right,self.checkpoint)
                yield TrialView(self.stream,start=start,end=right,sha256=sha,number=number,
                    piece_bytes=self.piece_bytes,record_bytes=self.record_bytes,checkpoint=self.checkpoint)
                self.stream.seek(right)


def _range_digest(stream,start,end,checkpoint):
    position=stream.tell();stream.seek(start);digest=hashlib.sha256()
    try:
        remaining=end-start
        while remaining:
            if checkpoint is not None:checkpoint()
            data=stream.read(min(65536,remaining))
            if not data:raise ValueError('Truncated trial evidence.')
            digest.update(data);remaining-=len(data)
        return digest.hexdigest()
    finally:stream.seek(position)


def _physical_records(stream,start,end,piece_bytes,record_bytes,checkpoint,observe=None,physical=None,validate_values=True):
    """Decode bounded physical records; owners supply structural validation."""
    stream.seek(start);position=start;buffer=bytearray();digest=hashlib.sha256();left=start
    while position<end:
        if checkpoint is not None:checkpoint()
        stream.seek(position)
        header=stream.read(_FRAME.size)
        if not header:
            if buffer:raise ValueError('Evidence ended before completion.')
            return
        if len(header)!=_FRAME.size:raise ValueError('Truncated evidence frame.')
        size,last=_FRAME.unpack(header)
        if not 1<=size<=piece_bytes or last not in (0,1):
            raise ValueError('Evidence frame exceeds its piece bound or has invalid flags.')
        position+=_FRAME.size+size+_CHECKSUM_BYTES
        if position>end:raise ValueError('Evidence exceeds its total byte bound.')
        if len(buffer)+size>record_bytes:raise ValueError('Evidence exceeds its record byte bound.')
        data=stream.read(size);checksum=stream.read(_CHECKSUM_BYTES)
        if len(data)!=size or len(checksum)!=_CHECKSUM_BYTES:raise ValueError('Truncated evidence frame.')
        if physical is not None:
            physical.update(header);physical.update(data);physical.update(checksum)
        if hashlib.sha256(bytes([last])+data).digest()!=checksum:
            raise ValueError('Evidence piece checksum differs.')
        buffer.extend(data);digest.update(data)
        if observe is not None:observe(size,len(buffer))
        if not last:continue
        try:record=json.loads(buffer,object_pairs_hook=_object)
        except (ValueError,UnicodeError,RecursionError) as error:raise ValueError('Invalid evidence JSON.') from error
        if validate_values:_json_value(record,record_bytes)
        yield record,digest.digest(),left,position
        left=position;buffer.clear();digest=hashlib.sha256()
    if buffer:raise ValueError('Evidence ended before completion.')


class TrialView:
    """A sealed range of caller-owned evidence, independent of batch completion.

    Preserve its bytes through reading. Traversal retains bounded records and
    the current complete period. This object owns no path or financial resource.
    Append operations cannot change its range. A changed range fails validation.
    """
    def __init__(self,stream,*,start,end,sha256,number,piece_bytes=MAX_PIECE_BYTES,
                 record_bytes=MAX_RECORD_BYTES,checkpoint=None):
        _limits(end-start,piece_bytes,record_bytes)
        if type(number) is not int or not 1<=number<=100:raise ValueError('Invalid sealed trial number.')
        self.stream,self.start,self.end,self.sha256=stream,start,end,sha256
        self.number,self.piece_bytes,self.record_bytes=number,piece_bytes,record_bytes
        self.checkpoint=checkpoint
        self._summary=None;self.period_count=0
        for record in self.records():
            if record['type']=='end_trial':
                self._summary=record['summary'];self.period_count=record['periods']

    @classmethod
    def _from_writer(cls,writer,summary):
        view=object.__new__(cls)
        view.stream,view.start,view.end=writer.stream,writer._trial_start,writer.bytes_written
        view.sha256=writer._trial_digest.hexdigest()
        view.number=writer._order.first_trial+writer._order.trials-1
        view.piece_bytes,view.record_bytes=writer.piece_bytes,writer.record_bytes
        view.checkpoint=writer.checkpoint
        view._summary=deepcopy(summary);view.period_count=writer._order.trial_periods
        return view

    @property
    def summary(self):return deepcopy(self._summary)

    def records(self):
        if _range_digest(self.stream,self.start,self.end,self.checkpoint)!=self.sha256:
            raise ValueError('Sealed trial evidence changed.')
        order=_Order()
        order.accept(dict(type='header',format_version=FORMAT_VERSION,
            result_contract=portfolio_results.CONTRACT_VERSION,trials=1,metadata={}),None)
        for record,_,_,_ in _physical_records(self.stream,self.start,self.end,
                self.piece_bytes,self.record_bytes,self.checkpoint):
            if record['type'] in ('header','complete'):raise ValueError('Invalid sealed trial record.')
            checked=record
            if record['type']=='trial':
                if type(record['number']) is not int or record['number']!=self.number:raise ValueError('Sealed trial number differs.')
                checked=dict(record,number=1)
            order.accept(checked,None)
            yield record
        if order.trials!=1 or order.active_trial or order.active_period:
            raise ValueError('Sealed trial ended before completion.')

    def periods(self):
        period=None
        for record in self.records():
            kind=record['type']
            if kind=='period':period=dict(record['value'],holdings=[])
            elif kind=='holding':period['holdings'].append(record['value'])
            elif kind=='end_period':
                yield period
                period=None

    def copy_into(self,emit_period):
        for period in self.periods():emit_period(period)
        return self.summary


def open_reader(stream, *, max_bytes, piece_bytes=MAX_PIECE_BYTES, record_bytes=MAX_RECORD_BYTES, checkpoint=None):
    """Dispatch explicit codec versions; old Reader always retains codec-1 meaning."""
    first = next(_physical_records(stream,0,max_bytes,piece_bytes,record_bytes,checkpoint),None)
    if first is None:raise ValueError('Evidence header is missing.')
    version = first[0].get('format_version') if type(first[0]) is dict else None
    if type(version) is not int:raise ValueError('Unsupported evidence format.')
    if version == 1:owner = Reader
    elif version == 2:
        from backtest.scalar_result_evidence import Reader as owner
    else:raise ValueError('Unsupported evidence format.')
    return owner(stream,max_bytes=max_bytes,piece_bytes=piece_bytes,record_bytes=record_bytes,checkpoint=checkpoint)
