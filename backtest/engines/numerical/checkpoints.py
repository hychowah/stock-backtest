"""Disposable completed calculations, separate from queue/library user evidence.

Store.open(binding) returns an Experiment. load(number) returns a detached
complete result or None; save(number, result) returns a retention outcome.
Version 2 also retains sealed codec trials as BLOBs. replay_into/save_from use
bounded I/O. Legacy canonical TEXT rows remain unchanged and readable.
The binding contains the exact generation, policy, schema, result version,
implementation/execution identity and full recorded configuration. Its canonical
finite JSON is verified as hashed. A hash is only an index.

Each save owns one SQLite transaction, including retention. It checks cancellation
before commit. Commit precedes progress/capture. Callers hold source then cache
ownership until this store, providers and input attachments close. This module
acquires no financial lock, starts no worker and opens no application store.
"""
from backtest import portfolio_results
from backtest.runtime import backtest_control

from copy import deepcopy
from contextlib import contextmanager
from datetime import date
import struct
import hashlib
import json
from pathlib import Path
import sqlite3

from backtest.runtime import backtest_control as backtest_control
from backtest import portfolio_results as portfolio_results
from backtest import calendar_requests as numerical_calendar
from backtest import result_evidence as result_evidence
from backtest.engines.numerical.legacy_checkpoints import LegacyTrial

STORE_VERSION = 2
STREAM_MAGIC = b'CBTRIAL\x00\x02'
DEFAULT_PAYLOAD_BYTES = 256*1024**2
DEFAULT_EXPERIMENTS = 32
BINDING_FIELDS = frozenset(('generation','policy','schema','result_contract',
                            'implementation','execution','configuration'))


def canonical(value):
    """Accept JSON values only, with finite numbers and string object keys."""
    def check(item):
        if type(item) is dict:
            if any(type(key) is not str for key in item):raise ValueError('JSON keys must be strings.')
            for part in item.values():check(part)
        elif type(item) is list:
            for part in item:check(part)
        elif item is not None and type(item) not in (str,int,float,bool):
            raise ValueError('Checkpoint evidence must be detached JSON values.')
    check(value)
    try:return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
    except (ValueError,TypeError,OverflowError) as error:raise ValueError('Checkpoint JSON must be finite.') from error


def digest(payload):return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def binding_json(binding):
    if (type(binding) is not dict or set(binding) != BINDING_FIELDS
            or any(type(binding[key]) is not str or not binding[key] for key in ('generation','policy','schema'))
            or type(binding['result_contract']) is not int
            or binding['result_contract'] not in (portfolio_results.CONTRACT_VERSION,2)
            or not isinstance(binding['implementation'],dict) or not binding['implementation']
            or not isinstance(binding['execution'],dict) or not binding['execution']):
        raise ValueError('Incomplete calculation binding.')
    config=binding['configuration']
    if (not isinstance(config,dict) or type(config.get('requested')) is not int
            or not 1 <= config['requested'] <= 100
            or not isinstance(config.get('samples'),list) or len(config['samples']) != config['requested']
            or any(not isinstance(row,list) or not row for row in config['samples'])
            or not isinstance(config.get('options'),dict)
            or type(config.get('seed')) is not int or not 0 <= config['seed'] <= 4294967295
            or any(type(config.get(key)) is not str for key in ('window_start','window_end'))):
        raise ValueError('Incomplete recorded random plan.')
    numerical_calendar.metadata(config)
    numerical_calendar.decode_request(numerical_calendar.request_fields(config))
    if binding['result_contract']==2:
        from backtest.application import strategy_requests
        scalar=binding['execution'].get('scalar')
        if type(scalar) is not dict or 'capture' not in scalar:
            raise ValueError('Scalar checkpoints require complete submitted capture.')
        strategy_requests.require_strategy(strategy_requests.CapturedStrategy(
            strategy_requests._encode(scalar['capture'],strategy_requests.STRATEGY_BYTES)))
    return canonical(binding)


def trial_options(binding):
    """Current capture is separate from the unchanged recorded date plan."""
    options=deepcopy(binding['configuration']['options'])
    if binding['result_contract']==2:options['strategy']=deepcopy(binding['execution']['scalar']['capture'])
    return options


def _decode(payload):
    try:
        result=json.loads(payload)
        if canonical(result) != payload:raise ValueError('Noncanonical checkpoint evidence.')
        return result
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError('Corrupt checkpoint evidence.') from error


class Store:
    """One explicit disposable path; bounds concern payload, not file quota.

    SQLite page overhead, free pages and rollback journals can exceed the payload
    bound. Empty stores may be discarded by their owner after closure. Eviction
    removes only whole derived experiments from this store, never user records.
    """
    def __init__(self,path,*,max_payload_bytes=DEFAULT_PAYLOAD_BYTES,max_experiments=DEFAULT_EXPERIMENTS):
        if (type(max_payload_bytes) is not int or max_payload_bytes < 0
                or type(max_experiments) is not int or max_experiments < 1):
            raise ValueError('Invalid checkpoint retention bounds.')
        self.path=Path(path)
        self.max_payload_bytes,self.max_experiments=max_payload_bytes,max_experiments
        self.closed=False
        self._coordinator_identity=None
        self.db=sqlite3.connect(self.path,timeout=60,isolation_level=None)
        try:
            self.db.execute('PRAGMA foreign_keys=ON')
            version=self.db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1,STORE_VERSION):raise ValueError('Unsupported checkpoint store version.')
            tables={row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables-{'experiments','trials'}:
                raise ValueError('The checkpoint path belongs to a different database.')
            self.db.execute('PRAGMA journal_mode=DELETE')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('''CREATE TABLE IF NOT EXISTS experiments(
                identity TEXT PRIMARY KEY,binding TEXT NOT NULL,touched INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS trials(
                experiment TEXT NOT NULL REFERENCES experiments(identity) ON DELETE CASCADE,
                number INTEGER NOT NULL,payload TEXT NOT NULL,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,
                PRIMARY KEY(experiment,number));''')
            self.db.execute('PRAGMA user_version='+str(STORE_VERSION))
        except BaseException:
            self.close();raise

    def _open(self):
        if self.closed:raise ValueError('Checkpoint store is closed.')

    @contextmanager
    def coordinating(self,experiment):
        """One parent operation may save only its active experiment.

        This guards callback reentrancy, not a storage pin or another writer.
        The caller still owns the financial session and this connection.
        """
        self._open()
        if experiment.store is not self or self._coordinator_identity is not None:
            raise ValueError('Checkpoint store already has an active coordinator.')
        self._coordinator_identity=experiment.identity
        try:yield
        finally:self._coordinator_identity=None

    def _writer(self,identity):
        if self._coordinator_identity not in (None,identity):
            raise ValueError('Another experiment cannot write during active trial coordination.')

    def open(self,binding):
        self._open()
        encoded=binding_json(binding)
        experiment=Experiment(self,encoded)
        experiment._verify_binding()
        return experiment

    def measurements(self):
        """Current payload, SQLite pages/free pages and observed journal bytes.

        Sample during save with an independent connection for journal high-water
        evidence. A post-commit journal size of zero is not its high-water size.
        """
        self._open()
        page_size=self.db.execute('PRAGMA page_size').fetchone()[0]
        return dict(payload_bytes=self.db.execute('SELECT COALESCE(SUM(bytes),0) FROM trials').fetchone()[0],
            experiments=self.db.execute('SELECT COUNT(*) FROM experiments').fetchone()[0],
            trials=self.db.execute('SELECT COUNT(*) FROM trials').fetchone()[0],
            sqlite_page_bytes=page_size*self.db.execute('PRAGMA page_count').fetchone()[0],
            sqlite_free_bytes=page_size*self.db.execute('PRAGMA freelist_count').fetchone()[0],
            file_bytes=self.path.stat().st_size,
            journal_bytes=Path(str(self.path)+'-journal').stat().st_size if Path(str(self.path)+'-journal').exists() else 0)

    def close(self):
        if not self.closed:
            self.db.close();self.closed=True

    def __enter__(self):return self
    def __exit__(self,*exc):self.close()


class Experiment:
    """A verified binding handle, not a pin against derived eviction."""
    def __init__(self,store,encoded):
        self.store=store
        self._encoded=encoded
        self.identity=digest(encoded)

    @property
    def binding(self):return _decode(self._encoded)

    def _verify_binding(self):
        self.store._open()
        row=self.store.db.execute('SELECT binding FROM experiments WHERE identity=?',(self.identity,)).fetchone()
        if row is not None and (row[0] != self._encoded or digest(row[0]) != self.identity):
            raise ValueError('Stored experiment binding differs.')
        if row is None and self.store.db.execute('SELECT 1 FROM trials WHERE experiment=? LIMIT 1',
                                                 (self.identity,)).fetchone() is not None:
            raise ValueError('Completed checkpoint has no experiment binding.')

    def _number(self,number):
        if type(number) is not int or not 1 <= number <= self.binding['configuration']['requested']:
            raise ValueError('Trial number is outside the recorded plan.')

    def _result(self,number,result):
        portfolio_results.validate_completed(result)
        config=self.binding['configuration']
        if (result['start'] != config['window_start'] or result['end'] != config['window_end']
                or numerical_calendar.metadata(result) != numerical_calendar.metadata(config) or canonical(result['options']) != canonical(config['options'])
                or [period['entry'] for period in result['periods']] != config['samples'][number-1]):
            raise ValueError('Completed trial differs from its recorded plan.')

    def load(self,number):
        if self.binding['result_contract']==2:raise ValueError('Scalar checkpoints require complete evidence replay.')
        self._number(number);self._verify_binding()
        row=self.store.db.execute('SELECT payload,sha256,bytes FROM trials WHERE experiment=? AND number=?',
                                  (self.identity,number)).fetchone()
        if row is None:return None
        payload,sha,size=row
        if type(payload) is bytes:
            periods=[]
            summary=self.replay_into(number,periods.append)
            return dict(periods=periods,**summary)
        if type(payload) is not str or digest(payload) != sha or len(payload.encode('utf-8')) != size:
            raise ValueError('Corrupt completed checkpoint.')
        result=_decode(payload);self._result(number,result)
        return result

    def read(self):
        """Return completed entries in trial order, including gaps after interruption."""
        self.store._open();db=self.store.db;owned=not db.in_transaction
        if owned:db.execute('BEGIN')
        try:
            self._verify_binding()
            numbers=[row[0] for row in db.execute('SELECT number FROM trials WHERE experiment=? ORDER BY number',
                                                 (self.identity,))]
            return [(number,self.load(number)) for number in numbers]
        finally:
            if owned:db.rollback()

    def _retain(self,number,size,publish):
        """One retention policy for TEXT and streamed BLOB evidence; transaction owned upstream."""
        db=self.store.db
        if size>self.store.max_payload_bytes:return False,0
        touched=db.execute('SELECT COALESCE(MAX(touched),0)+1 FROM experiments').fetchone()[0]
        db.execute('INSERT INTO experiments VALUES(?,?,?) ON CONFLICT(identity) DO UPDATE SET touched=excluded.touched',
                   (self.identity,self._encoded,touched))
        own=db.execute('SELECT COALESCE(SUM(bytes),0) FROM trials WHERE experiment=?',(self.identity,)).fetchone()[0]
        if own+size>self.store.max_payload_bytes:return False,0
        evicted=0
        while True:
            total=db.execute('SELECT COALESCE(SUM(bytes),0) FROM trials').fetchone()[0]
            count=db.execute('SELECT COUNT(*) FROM experiments').fetchone()[0]
            if total+size<=self.store.max_payload_bytes and count<=self.store.max_experiments:break
            oldest=db.execute('SELECT identity FROM experiments WHERE identity<>? ORDER BY touched,identity LIMIT 1',
                              (self.identity,)).fetchone()
            if oldest is None:raise ValueError('Checkpoint retention cannot satisfy its bounds.')
            db.execute('DELETE FROM experiments WHERE identity=?',oldest);evicted+=1
        publish()
        return True,evicted

    def save(self,number,result):
        if self.binding['result_contract']==2:raise ValueError('Scalar checkpoints require sealed complete evidence.')
        self.store._writer(self.identity)
        self._number(number);self.store._open();self._result(number,result)
        payload=canonical(result);size=len(payload.encode('utf-8'));db=self.store.db
        backtest_control.checkpoint();db.execute('BEGIN IMMEDIATE')
        try:
            existing=self.load(number)
            if existing is not None:
                left,right=deepcopy(existing),deepcopy(result)
                left.pop('seconds');right.pop('seconds')
                if canonical(left)!=canonical(right):raise ValueError('Conflicting completed trial evidence.')
                retained,evicted=True,0
            else:
                retained,evicted=self._retain(number,size,lambda:db.execute('INSERT INTO trials VALUES(?,?,?,?,?)',
                    (self.identity,number,payload,digest(payload),size)))
            backtest_control.checkpoint();db.commit()
        except BaseException:
            db.rollback();raise
        return dict(retained=retained,payload_bytes=size,evicted_experiments=evicted)

    @contextmanager
    def _trial(self,number):
        self._number(number);self.store._open();db=self.store.db;owned=not db.in_transaction
        if owned:db.execute('BEGIN')
        blob=None
        try:
            self._verify_binding()
            row=db.execute('SELECT rowid,typeof(payload),sha256,bytes FROM trials WHERE experiment=? AND number=?',
                           (self.identity,number)).fetchone()
            if row is None:
                yield None;return
            rowid,kind,sha,size=row
            blob=db.blobopen('trials','payload',rowid,readonly=True)
            if type(size) is not int or size!=len(blob) or result_evidence._range_digest(blob,0,size,backtest_control.checkpoint)!=sha:
                raise ValueError('Corrupt completed checkpoint.')
            blob.seek(0)
            if kind=='text':view=LegacyTrial(blob,canonical)
            elif kind=='blob':
                if blob.read(len(STREAM_MAGIC))!=STREAM_MAGIC:raise ValueError('Unsupported checkpoint evidence version.')
                length=blob.read(4)
                if len(length)!=4:raise ValueError('Truncated checkpoint envelope.')
                length=struct.unpack('!I',length)[0]
                if not 1<=length<=result_evidence.MAX_RECORD_BYTES:raise ValueError('Checkpoint envelope exceeds its bound.')
                raw=blob.read(length)
                try:header=_decode(raw.decode('utf8'))
                except UnicodeError:raise ValueError('Invalid checkpoint envelope.') from None
                if (type(header) is not dict or set(header)!=({'format','experiment','number','sha256','piece_bytes','record_bytes'} | ({'metadata'} if header.get('format')==2 else set()))
                        or type(header['format']) is not int or header['format'] not in (1,2)
                        or header['experiment']!=self.identity or type(header['number']) is not int or header['number']!=number):
                    raise ValueError('Checkpoint envelope identity differs.')
                owner=result_evidence.TrialView;extra={}
                if header['format']==2:
                    from backtest.scalar_result_evidence import TrialView as owner
                    extra['metadata']=header['metadata']
                if header['format']!=self.binding['result_contract']:
                    raise ValueError('Checkpoint codec differs from its scalar/legacy contract.')
                view=owner(blob,start=blob.tell(),end=size,sha256=header['sha256'],number=number,
                    piece_bytes=header['piece_bytes'],record_bytes=header['record_bytes'],checkpoint=backtest_control.checkpoint,**extra)
            else:raise ValueError('Unsupported checkpoint payload type.')
            yield view
        finally:
            if blob is not None:blob.close()
            if owned:db.rollback()

    def _validate_view(self,number,view,emit_period=None):
        summary=view.summary;config=self.binding['configuration'];dates=config['samples'][number-1]
        if (summary.get('start')!=config['window_start'] or summary.get('end')!=config['window_end']
                or numerical_calendar.metadata(summary)!=numerical_calendar.metadata(config)
                or canonical(summary.get('options'))!=canonical(trial_options(self.binding))):
            raise ValueError('Completed trial differs from its recorded plan.')
        days=[date.fromisoformat(day) for day in dates]+[date.fromisoformat(config['window_end'])]
        pairs=list(zip(days,days[1:]))
        if self.binding['result_contract']==2:
            expected=trial_options(self.binding)
            if (getattr(view,'codec',1)!=2 or view.metadata.get('options')!=expected):
                raise ValueError('Scalar checkpoint capture differs.')
        return portfolio_results.validate_completed_into(summary,view.periods(),pairs,emit_period,
            checkpoint=backtest_control.checkpoint,contract=self.binding['result_contract'])

    def replay_into(self,number,emit_period):
        """Validate binding, recorded dates and finances before reporting completion.

        Missing returns None. Corruption raises. Emitted periods are provisional
        until return; the owner must not publish partial output as a trial.
        """
        with self._trial(number) as view:
            if view is None:return None
            self._validate_view(number,view)
            return self._validate_view(number,view,emit_period)

    def replay_evidence(self,number,writer):
        """Replay complete scalar records under a short checkpoint read scope."""
        with self._trial(number) as view:
            if view is None:return None
            self._validate_view(number,view)
            if getattr(view,'codec',1)!=2:raise ValueError('Expected scalar checkpoint evidence.')
            return view.replay_into(writer)

    def save_from(self,number,view):
        """Atomically retain a sealed trial; never collect its complete holdings."""
        self.store._writer(self.identity)
        self._number(number);self.store._open()
        if view.number!=number:raise ValueError('Checkpoint trial number differs.')
        self._validate_view(number,view)
        header=dict(format=getattr(view,'codec',1),experiment=self.identity,number=number,sha256=view.sha256,
            piece_bytes=view.piece_bytes,record_bytes=view.record_bytes)
        if header['format']==2:header['metadata']=view.metadata
        header=canonical(header).encode('utf8')
        prefix=STREAM_MAGIC+struct.pack('!I',len(header))+header
        size=len(prefix)+view.end-view.start;db=self.store.db
        backtest_control.checkpoint();db.execute('BEGIN IMMEDIATE')
        try:
            with self._trial(number) as existing:
                duplicate=existing is not None
                if duplicate:
                    self._validate_view(number,existing)
                    if _semantic_digest(existing)!=_semantic_digest(view):
                        raise ValueError('Conflicting completed trial evidence.')
            def publish():
                cursor=db.execute('INSERT INTO trials VALUES(?,?,zeroblob(?),?,?)',
                    (self.identity,number,size,'pending',size))
                sha=hashlib.sha256()
                with db.blobopen('trials','payload',cursor.lastrowid) as target:
                    target.write(prefix);sha.update(prefix)
                    position=view.stream.tell();view.stream.seek(view.start)
                    try:
                        remaining=view.end-view.start
                        while remaining:
                            backtest_control.checkpoint()
                            data=view.stream.read(min(65536,remaining))
                            if not data:raise ValueError('Truncated sealed trial evidence.')
                            target.write(data);sha.update(data);remaining-=len(data)
                    finally:view.stream.seek(position)
                db.execute('UPDATE trials SET sha256=? WHERE experiment=? AND number=?',
                           (sha.hexdigest(),self.identity,number))
                # Revalidate copied bytes before atomic completion.
                with self._trial(number) as copied:self._validate_view(number,copied)
            retained,evicted=(True,0) if duplicate else self._retain(number,size,publish)
            backtest_control.checkpoint();db.commit()
        except BaseException:
            db.rollback();raise
        return dict(retained=retained,payload_bytes=size,evicted_experiments=evicted)


def _semantic_digest(view):
    """Canonical per-row identity across representations; only root seconds differ."""
    sha=hashlib.sha256();summary=view.summary;summary.pop('seconds')
    if getattr(view,'codec',1)==2:
        for record in view.records():
            if record['type']=='end_trial':record=dict(record,summary={k:v for k,v in record['summary'].items() if k!='seconds'})
            sha.update(hashlib.sha256(canonical(record).encode('utf8')).digest())
        sha.update(hashlib.sha256(canonical(view.metadata).encode('utf8')).digest())
        return sha.hexdigest()
    def add(value):sha.update(hashlib.sha256(canonical(value).encode('utf8')).digest())
    add(summary)
    for period in view.periods():
        add({k:v for k,v in period.items() if k!='holdings'})
        for holding in period['holdings']:add(holding)
        add(None)
    return sha.hexdigest()
