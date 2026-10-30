"""Complete durable snapshots inside the existing queue and library databases.

A durable snapshot owns every byte required to read its original result.
Completion binds its application metadata and complete ordered evidence.
Reading never calculates or checks current financial inputs. The stores own
transactions, record limits and mutations; this module owns no database path.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from threading import RLock

import backtest_control
import result_evidence

MAGIC = b'CBDSNAPSHOT\x00\x03'
CHUNK_BYTES = 65536
MAX_EVIDENCE_BYTES = 256*1024**2
MAX_METADATA_BYTES = 8*1024**2
MAX_ENVELOPE_BYTES = 32*1024**2
SCHEMA = '''CREATE TABLE IF NOT EXISTS evidence_chunks (
 record_id TEXT NOT NULL, ordinal INTEGER NOT NULL, payload BLOB NOT NULL,
 PRIMARY KEY(record_id,ordinal)
)'''


class CapacityError(ValueError):
    pass


class RequiresReader(ValueError):
    pass


def install(db):
    db.execute(SCHEMA)


def is_evidence(packed):
    return isinstance(packed,bytes) and packed.startswith(MAGIC)


def eager_guard(packed):
    if is_evidence(packed):
        raise RequiresReader('This version-3 snapshot requires the explicit evidence reader. Its stored record was kept.')


def encode(value, limit):
    result_evidence._json_value(value,limit)
    data=bytearray()
    for token in json.JSONEncoder(allow_nan=False,separators=(',',':'),ensure_ascii=True).iterencode(value):
        for offset in range(0,len(token),CHUNK_BYTES):
            part=token[offset:offset+CHUNK_BYTES].encode('ascii')
            if len(data)+len(part)>limit:
                raise CapacityError('Durable snapshot metadata exceeds its encoded byte limit.')
            data.extend(part)
    return bytes(data)


def decode(data):
    value=json.loads(data,object_pairs_hook=result_evidence._object)
    result_evidence._json_value(value,MAX_ENVELOPE_BYTES)
    return value


def same(left,right):
    # Preserve number types, signed zero and missing fields; object key order
    # does not change the meaning of submitted settings.
    return json.dumps(left,sort_keys=True,allow_nan=False,separators=(',',':')) == json.dumps(right,sort_keys=True,allow_nan=False,separators=(',',':'))


def validate_metadata(metadata,reader):
    """Bind submitted display meaning to the original complete result."""
    if (type(metadata) is not dict or type(metadata.get('version')) is not int or metadata['version']!=3
            or metadata.get('kind') not in ('custom','random')
            or type(metadata.get('settings')) is not dict
            or metadata['settings'].get('mode')!=metadata['kind']
            or type(metadata.get('catalog')) is not dict
            or any(type(metadata['catalog'].get(k)) is not dict for k in ('metrics','filters'))
            or type(metadata.get('presentation')) is not dict
            or not same(metadata.get('result'),reader.manifest['summary'])):
        raise ValueError('Version-3 snapshot metadata or result summary differs.')
    header=reader.metadata
    if header.get('mode')!=metadata['kind'] or type(header.get('options')) is not dict:
        raise ValueError('Snapshot mode differs from original evidence.')
    if metadata['kind']=='random' and (type(header.get('configuration')) is not dict
            or not same(header['configuration'],metadata['result'].get('configuration'))):
        raise ValueError('Snapshot recorded plan differs from original evidence.')
    settings={k:v for k,v in metadata['settings'].items() if k!='mode'}
    options=header['options']
    # Settings preserve omissions. In particular an unseeded submission may
    # keep seed=None while the original recorded plan owns the generated seed.
    for key,value in settings.items():
        if key=='seed' and value is None and metadata['kind']=='random':continue
        if key not in options or not same(value,options[key]):
            raise ValueError('Snapshot settings differ from original evidence.')
    return metadata


def _unpack(packed,identifier, max_bytes):
    if not is_evidence(packed):raise RequiresReader('This record uses the existing eager snapshot reader.')
    if len(packed)>MAX_ENVELOPE_BYTES:raise ValueError('Invalid durable envelope size.')
    envelope=decode(packed[len(MAGIC):])
    if type(envelope) is not dict or set(envelope)!={'version','record_id','snapshot','evidence','sha256'}:
        raise ValueError('Invalid durable completion envelope.')
    body={k:v for k,v in envelope.items() if k!='sha256'}
    if (type(envelope['version']) is not int or envelope['version']!=3 or envelope['record_id']!=identifier
            or hashlib.sha256(encode(body,MAX_ENVELOPE_BYTES)).hexdigest()!=envelope['sha256']
            or type(envelope['snapshot']) is not str):
        raise ValueError('Durable envelope binding differs.')
    metadata_bytes=envelope['snapshot'].encode('ascii')
    if len(metadata_bytes)>MAX_METADATA_BYTES:raise ValueError('Invalid durable metadata size.')
    metadata=decode(metadata_bytes);evidence=envelope['evidence']
    expected={'bytes','sha256','chunks','chunk_bytes','piece_bytes','record_bytes','manifest'}
    if (type(evidence) is not dict or set(evidence)!=expected
            or type(evidence['bytes']) is not int or not 0<evidence['bytes']<=max_bytes
            or type(evidence['chunks']) is not int
            or evidence['chunks']!=(evidence['bytes']+CHUNK_BYTES-1)//CHUNK_BYTES
            or type(evidence['chunk_bytes']) is not int or evidence['chunk_bytes']!=CHUNK_BYTES):
        raise ValueError('Durable evidence counts or limits differ.')
    result_evidence._limits(evidence['bytes'],evidence['piece_bytes'],evidence['record_bytes'])
    return metadata,evidence


class Budget:
    """Process-shared reservations, not a filesystem or machine-wide quota.

    Publication reserves existing files twice plus four times new payload and
    envelope bytes, plus 1 MiB. This covers simultaneous destination staging,
    conservative page/index growth and rollback journals. Jobs sources and
    detached sources retain their own charges. External disk races can still
    fail SQLite writes; the owning transaction must roll back.
    """
    def __init__(self,max_bytes=4*1024**3):
        if type(max_bytes) is not int or max_bytes<=0:raise ValueError('Invalid durable storage budget.')
        self.max_bytes=max_bytes;self.lock=RLock();self.charges={};self.pending=[]

    def collect(self):
        with self.lock:
            for lease in self.pending[:]:
                try:lease.close()
                except OSError:continue

    def reserve(self,path,size):
        with self.lock:
            self.collect()
            if sum(self.charges.values())+size>self.max_bytes:raise CapacityError('Durable evidence reservation budget is exhausted.')
            if shutil.disk_usage(path).free<size:raise CapacityError('Available storage cannot cover durable evidence staging and journals.')
            token=object();self.charges[token]=size
            return token

    def release(self,token):
        with self.lock:self.charges.pop(token)

    def measurements(self):
        with self.lock:
            return dict(budget_bytes=self.max_bytes,reserved_bytes=sum(self.charges.values()),
                        reservations=len(self.charges),pending_cleanup=len(self.pending))


DEFAULT_BUDGET=Budget()


def files(db):
    path=Path(db.execute('PRAGMA database_list').fetchone()[2])
    def size(p):return p.stat().st_size if p.exists() else 0
    page_size=db.execute('PRAGMA page_size').fetchone()[0]
    return dict(file_bytes=size(path),journal_bytes=size(Path(str(path)+'-journal')),
                wal_bytes=size(Path(str(path)+'-wal')),shm_bytes=size(Path(str(path)+'-shm')),
                sqlite_page_bytes=page_size*db.execute('PRAGMA page_count').fetchone()[0],
                sqlite_free_bytes=page_size*db.execute('PRAGMA freelist_count').fetchone()[0])


@contextmanager
def _reservation(db,size,budget):
    path=Path(db.execute('PRAGMA database_list').fetchone()[2])
    token=budget.reserve(path.parent,size)
    try:yield
    finally:budget.release(token)


class ChunkStream:
    """Seekable view of fixed chunks; never load a whole SQLite payload."""
    def __init__(self,db,identifier,size):
        self.db,self.identifier,self.size=db,identifier,size;self.position=0
        count=(size+CHUNK_BYTES-1)//CHUNK_BYTES
        row=db.execute('SELECT COUNT(*),MIN(ordinal),MAX(ordinal),COALESCE(SUM(length(payload)),0) FROM evidence_chunks WHERE record_id=?',(identifier,)).fetchone()
        if tuple(row)!=(count,0,count-1,size):raise ValueError('Durable chunks are missing, duplicated or truncated.')
        self.cache_number=None;self.cache=None

    def tell(self):return self.position

    def seek(self,offset,whence=0):
        position=offset if whence==0 else self.position+offset if whence==1 else self.size+offset if whence==2 else -1
        if type(position) is not int or position<0:raise ValueError('Invalid evidence seek.')
        self.position=position;return position

    def read(self,size=-1):
        # Codec requests are bounded. Refuse accidental whole-evidence reads.
        if type(size) is not int or size<0 or size>result_evidence.MAX_PIECE_BYTES:
            raise ValueError('Durable evidence reads require a bounded buffer.')
        remaining=min(size,max(0,self.size-self.position));parts=[]
        while remaining:
            number,offset=divmod(self.position,CHUNK_BYTES)
            if number!=self.cache_number:
                row=self.db.execute('SELECT typeof(payload),length(payload) FROM evidence_chunks WHERE record_id=? AND ordinal=?',(self.identifier,number)).fetchone()
                expected=min(CHUNK_BYTES,self.size-number*CHUNK_BYTES)
                if row is None or tuple(row)!=('blob',expected):raise ValueError('Invalid durable chunk type or size.')
                self.cache=self.db.execute('SELECT payload FROM evidence_chunks WHERE record_id=? AND ordinal=?',(self.identifier,number)).fetchone()[0]
                self.cache_number=number
            count=min(remaining,len(self.cache)-offset);parts.append(self.cache[offset:offset+count])
            self.position+=count;remaining-=count
        return b''.join(parts)


def _digest(stream,size):
    stream.seek(0);digest=hashlib.sha256();count=0
    while count<size:
        backtest_control.checkpoint()
        part=stream.read(min(CHUNK_BYTES,size-count))
        if not part:raise ValueError('Durable evidence ended before completion.')
        digest.update(part);count+=len(part)
    if stream.read(1):raise ValueError('Durable evidence has trailing bytes.')
    stream.seek(0);return digest.hexdigest()


def _reader(stream,metadata,evidence):
    if _digest(stream,evidence['bytes'])!=evidence['sha256']:raise ValueError('Durable evidence content differs.')
    reader=result_evidence.Reader(stream,max_bytes=evidence['bytes'],piece_bytes=evidence['piece_bytes'],
        record_bytes=evidence['record_bytes'],checkpoint=backtest_control.checkpoint)
    if not same(reader.manifest,evidence['manifest']):raise ValueError('Durable evidence manifest differs.')
    validate_metadata(metadata,reader)
    return reader


@contextmanager
def publication(db,identifier,metadata,reader,*,budget=DEFAULT_BUDGET,max_bytes=MAX_EVIDENCE_BYTES):
    """Consume a pinned immutable reader through bounded buffers.

    The caller retains source ownership until this operation ends, and owns an
    IMMEDIATE transaction through envelope/record publication. Any failure must
    roll that transaction back. Stored validation precedes the yielded envelope.
    Commit inside this scope. The reservation lasts through commit or rollback.
    """
    if not db.in_transaction:raise ValueError('Durable publication requires a transaction.')
    if type(max_bytes) is not int or not 0<max_bytes<=MAX_EVIDENCE_BYTES:raise ValueError('Invalid durable evidence ceiling.')
    metadata_bytes=encode(metadata,MAX_METADATA_BYTES)
    metadata=decode(metadata_bytes)
    validate_metadata(metadata,reader)
    stream=reader.stream;size=stream.seek(0,2)
    if not 0<size<=max_bytes:raise CapacityError('Durable evidence exceeds its per-copy ceiling.')
    envelope_allowance=2*len(metadata_bytes)+len(encode(reader.manifest,MAX_ENVELOPE_BYTES))+4096
    stored=files(db);charge=2*sum(stored[k] for k in ('file_bytes','journal_bytes','wal_bytes','shm_bytes'))+4*(size+envelope_allowance)+1024**2
    with _reservation(db,charge,budget):
        try:
            stream.seek(0);digest=hashlib.sha256();ordinal=0;offset=0
            while offset<size:
                backtest_control.checkpoint()
                part=stream.read(min(CHUNK_BYTES,size-offset))
                if len(part)!=min(CHUNK_BYTES,size-offset):raise ValueError('Source evidence was truncated.')
                db.execute('INSERT INTO evidence_chunks VALUES(?,?,?)',(identifier,ordinal,part))
                digest.update(part);ordinal+=1;offset+=len(part)
            if stream.read(1):raise ValueError('Source evidence grew during copy.')
            evidence=dict(bytes=size,sha256=digest.hexdigest(),chunks=ordinal,chunk_bytes=CHUNK_BYTES,
                piece_bytes=reader.piece_bytes,record_bytes=reader.record_bytes,manifest=reader.manifest)
            copied=_reader(ChunkStream(db,identifier,size),metadata,evidence)
            if not same(copied.metadata,reader.metadata):raise ValueError('Original evidence header differs.')
            body=dict(version=3,record_id=identifier,snapshot=metadata_bytes.decode('ascii'),evidence=evidence)
            envelope=dict(body,sha256=hashlib.sha256(encode(body,MAX_ENVELOPE_BYTES)).hexdigest())
            packed=MAGIC+encode(envelope,MAX_ENVELOPE_BYTES-len(MAGIC))
            backtest_control.checkpoint()
            yield packed
            if db.in_transaction:raise ValueError('Durable publication was not committed.')
        finally:
            if db.in_transaction:db.rollback()


class Opened:
    """Independent read lifetime; source deletion cannot change this reader."""
    def __init__(self,stream,path,token,budget,metadata,reader):
        self.stream,self.path,self.token,self.budget=stream,path,token,budget
        self._metadata,self.reader=metadata,reader;self.closed=False

    @property
    def metadata(self):return deepcopy(self._metadata)

    @contextmanager
    def open_reader(self):
        """Borrow an independent seek position while this lifetime stays owned."""
        if self.closed:raise ValueError('Evidence reader is closed.')
        with self.path.open('rb') as stream:
            yield self.reader.reopen(stream)

    def close(self):
        if self.closed:return
        try:
            self.stream.close();self.path.unlink()
        except OSError:
            with self.budget.lock:
                if self not in self.budget.pending:self.budget.pending.append(self)
            raise
        with self.budget.lock:
            if self in self.budget.pending:self.budget.pending.remove(self)
            self.budget.release(self.token);self.closed=True


def detach(db,identifier,packed,*,budget=DEFAULT_BUDGET,max_bytes=MAX_EVIDENCE_BYTES):
    """Copy a consistent read transaction; close that transaction before yield.

    The store closes its dedicated database connection before exposing Opened.
    Active readers retain only their charged private temporary stream.
    """
    if not db.in_transaction:raise ValueError('Durable reading requires a consistent transaction.')
    metadata,evidence=_unpack(packed,identifier,max_bytes)
    path=Path(db.execute('PRAGMA database_list').fetchone()[2]).parent
    token=budget.reserve(path,evidence['bytes']);stream=None;lease=None
    try:
        stream=tempfile.NamedTemporaryFile(mode='w+b',prefix='.evidence-reader-',dir=path,delete=False)
        lease=Opened(stream,Path(stream.name),token,budget,metadata,None)
        source=ChunkStream(db,identifier,evidence['bytes'])
        while True:
            backtest_control.checkpoint();part=source.read(CHUNK_BYTES)
            if not part:break
            if stream.write(part)!=len(part):raise OSError('Durable reader copy was incomplete.')
        stream.flush();lease.reader=_reader(stream,metadata,evidence)
        return lease
    except BaseException:
        if lease is not None:lease.close()
        else:
            if stream is not None:stream.close()
            budget.release(token)
        raise


def delete(db,identifier):
    db.execute('DELETE FROM evidence_chunks WHERE record_id=?',(identifier,))


def matches(db,identifier,packed,metadata,reader):
    metadata=decode(encode(metadata,MAX_METADATA_BYTES))
    original,evidence=_unpack(packed,identifier,MAX_EVIDENCE_BYTES)
    existing=_reader(ChunkStream(db,identifier,evidence['bytes']),original,evidence)
    return (same(original,metadata) and same(existing.metadata,reader.metadata)
            and same(evidence['manifest'],reader.manifest)
            and reader.stream.seek(0,2)==evidence['bytes']
            and _digest(reader.stream,evidence['bytes'])==evidence['sha256'])
