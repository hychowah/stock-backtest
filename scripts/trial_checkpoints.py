"""Disposable completed calculations, separate from queue/library user evidence.

Store.open(binding) returns an Experiment. load(number) returns a detached
complete result or None; save(number, result) returns a retention outcome.
The binding contains the exact generation, policy, schema, result version,
implementation/execution identity and full recorded configuration. Its canonical
finite JSON is verified as well as hashed. A hash is only an index.

Each save owns one SQLite transaction, including retention. It checks cancellation
before commit. Commit precedes progress/capture. Callers hold source then cache
ownership until this store, providers and input attachments close. This module
acquires no financial lock, starts no worker and opens no application store.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3

import backtest_control
import portfolio_results
import numerical_calendar

STORE_VERSION = 1
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
            or binding['result_contract'] != portfolio_results.CONTRACT_VERSION
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
    return canonical(binding)


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
        self.db=sqlite3.connect(self.path,timeout=60,isolation_level=None)
        try:
            self.db.execute('PRAGMA foreign_keys=ON')
            version=self.db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,STORE_VERSION):raise ValueError('Unsupported checkpoint store version.')
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
        self._number(number);self._verify_binding()
        row=self.store.db.execute('SELECT payload,sha256,bytes FROM trials WHERE experiment=? AND number=?',
                                  (self.identity,number)).fetchone()
        if row is None:return None
        payload,sha,size=row
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

    def save(self,number,result):
        self._number(number);self.store._open();self._result(number,result)
        payload=canonical(result);size=len(payload.encode('utf-8'));db=self.store.db
        backtest_control.checkpoint()
        db.execute('BEGIN IMMEDIATE')
        try:
            existing=self.load(number)
            if existing is not None:
                left,right=deepcopy(existing),deepcopy(result)
                left.pop('seconds');right.pop('seconds')
                if canonical(left) != canonical(right):raise ValueError('Conflicting completed trial evidence.')
                retained=True;evicted=0
            elif size > self.store.max_payload_bytes:
                retained=False;evicted=0
            else:
                touched=db.execute('SELECT COALESCE(MAX(touched),0)+1 FROM experiments').fetchone()[0]
                db.execute('INSERT INTO experiments VALUES(?,?,?) ON CONFLICT(identity) DO UPDATE SET touched=excluded.touched',
                           (self.identity,self._encoded,touched))
                # The current experiment may itself exceed the budget. In that
                # case skip this row; do not erase its earlier completed work.
                own=db.execute('SELECT COALESCE(SUM(bytes),0) FROM trials WHERE experiment=?',(self.identity,)).fetchone()[0]
                if own+size > self.store.max_payload_bytes:
                    retained=False;evicted=0
                else:
                    evicted=0
                    while True:
                        total=db.execute('SELECT COALESCE(SUM(bytes),0) FROM trials').fetchone()[0]
                        count=db.execute('SELECT COUNT(*) FROM experiments').fetchone()[0]
                        if total+size <= self.store.max_payload_bytes and count <= self.store.max_experiments:break
                        oldest=db.execute('SELECT identity FROM experiments WHERE identity<>? ORDER BY touched,identity LIMIT 1',
                                          (self.identity,)).fetchone()
                        if oldest is None:raise ValueError('Checkpoint retention cannot satisfy its bounds.')
                        db.execute('DELETE FROM experiments WHERE identity=?',oldest);evicted+=1
                    db.execute('INSERT INTO trials VALUES(?,?,?,?,?)',(self.identity,number,payload,digest(payload),size))
                    retained=True
            backtest_control.checkpoint()
            db.commit()
        except BaseException:
            db.rollback();raise
        return dict(retained=retained,payload_bytes=size,evicted_experiments=evicted)
