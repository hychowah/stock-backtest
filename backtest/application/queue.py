"""Durable test queue, independent of rebuildable caches and the saved library.

One consumer owns the queue file lock across server instances. Queue database
transactions end before financial ownership is requested. The consumer retains
both queue ownership and server lifetime ownership through engine cleanup.
Only waiting items can change settings or order. Held items are excluded from
execution while a user edits them. Complete results transfer to the library
before duplicate queue evidence is released. Failed transfers keep their source.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
from threading import Event, Lock, Thread
import time
import zlib

from backtest.runtime import backtest_control as backtest_control
from backtest.application.calculation_contract import Busy, Unavailable, engine_id
from backtest.application.original_calculations import Original
from backtest.application import artifacts, strategy_requests, temporary_evidence
from backtest.paths import ROOT
from backtest.runtime import cache_access as cache_access
from backtest.runtime import diagnostics as diagnostics
from backtest.application import durable_evidence as durable_evidence
from backtest.application import library as saved_backtests
DATABASE=ROOT/'data'/'backtest-queue.sqlite'
LIMIT=100
SCALAR_FAILURE='scalar-failure/1\n'
COLUMNS='id,name,spec,original_hash,position,revision,state,created_at,started,finished,seed,progress,configuration,error,cagr'
SCHEMA='''
CREATE TABLE IF NOT EXISTS control (id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL);
INSERT OR IGNORE INTO control VALUES(1,0);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, spec TEXT NOT NULL, original_hash TEXT NOT NULL,
 position INTEGER NOT NULL, revision INTEGER NOT NULL DEFAULT 1, state TEXT NOT NULL,
 created_at TEXT NOT NULL, started TEXT, finished TEXT, seed INTEGER,
 progress TEXT, configuration TEXT, error TEXT, cagr REAL, snapshot BLOB, plan TEXT
);
CREATE TABLE IF NOT EXISTS transfers (
 job_id TEXT PRIMARY KEY, state TEXT NOT NULL, saved_id TEXT, error TEXT, completion TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edits (
 job_id TEXT PRIMARY KEY, id TEXT NOT NULL UNIQUE, revision INTEGER NOT NULL,
 state TEXT NOT NULL, request_hash TEXT
);
'''


class Conflict(ValueError):pass
class Missing(ValueError):pass


def now():return datetime.now(timezone.utc).isoformat()


def encode(value):return json.dumps(value,allow_nan=False,separators=(',',':'),sort_keys=True)


class Store:
    def __init__(self,path=DATABASE,*,evidence_budget=durable_evidence.DEFAULT_BUDGET):
        self.path=Path(path);self.evidence_budget=evidence_budget

    @contextmanager
    def database(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        try:
            db.executescript(SCHEMA)
            durable_evidence.install(db)
            with db:
                db.execute('BEGIN IMMEDIATE')
                yield db
        finally:db.close()

    @staticmethod
    def row(db,identifier,*,include_snapshot=False,include_plan=False):
        fields=COLUMNS+(',snapshot' if include_snapshot else '')+(',plan' if include_plan else '')
        row=db.execute(f"SELECT {fields} FROM jobs WHERE id=? AND state!='deleted'",(identifier,)).fetchone()
        if row is None:raise Missing('Queued test not found. Refresh the queue.')
        return row

    @staticmethod
    def metadata(db,row):
        spec=json.loads(row['spec'])
        result={key:row[key] for key in ('id','name','position','revision','state','created_at','started','finished','error','cagr')}
        if ('strategy' in spec['options'] and isinstance(result['error'],str)
                and result['error'].startswith(SCALAR_FAILURE)):
            failure=json.loads(result['error'][len(SCALAR_FAILURE):])
            result.update((key,failure[key]) for key in ('error','code','path','errors'))
        edit=db.execute('SELECT id,revision,state FROM edits WHERE job_id=?',(row['id'],)).fetchone()
        transfer=db.execute('SELECT state,saved_id,error FROM transfers WHERE job_id=?',(row['id'],)).fetchone()
        return dict(**result,mode=spec['mode'],options=spec['options'],transfer=dict(transfer) if transfer else None,
                    edit=dict(edit) if edit else None,
                    progress=json.loads(row['progress']) if row['progress'] else None,
                    configuration=json.loads(row['configuration']) if row['configuration'] else None)

    @staticmethod
    def specification(request, *, admit=True):
        if not isinstance(request,dict):raise ValueError('Expected a queued test.')
        name=request.get('name','').strip() if isinstance(request.get('name',''),str) else ''
        if not 1<=len(name)<=120:raise ValueError('Use a test name with 1–120 characters.')
        if request.get('mode') not in ('custom','random') or not isinstance(request.get('options'),dict):
            raise ValueError('Queue a fixed or random-date backtest from Custom trade date and frequency.')
        for key in ('catalog','presentation'):
            if not isinstance(request.get(key),dict):raise ValueError('The test display labels are required.')
        if any(not isinstance(request['catalog'].get(key),dict) for key in ('metrics','filters')):
            raise ValueError('The test metric and filter labels are required.')
        if admit:strategy_requests.check_request(request)
        elif 'strategy' in request.get('options',{}):
            strategy_requests._encode(request,strategy_requests.REQUEST_BYTES)
        options=strategy_requests.canonical_options(request['options'])
        engine_id(options)
        dates=options.get('calendar',options)
        if not isinstance(dates,dict) or not isinstance(dates.get('start'),str) or not isinstance(dates.get('end'),str):
            raise ValueError('Choose start and end dates.')
        spec={key:request[key] for key in ('mode','options','catalog','presentation')}
        spec['options']=options
        packed=encode(spec)
        if len(packed.encode())>262144:raise ValueError('The test settings are too large.')
        seed=options.get('seed') if request['mode']=='random' else None
        if request['mode']=='random' and seed is None:seed=secrets.randbits(32)
        if seed is not None and (type(seed) is not int or not 0<=seed<=4294967295):
            raise ValueError('Choose a whole-number seed between 0 and 4294967295.')
        return name,packed,seed

    def enqueue(self,request):
        identifier=request.get('id') if isinstance(request,dict) else None
        if not isinstance(identifier,str) or not re.fullmatch('[0-9a-f]{32}',identifier):raise ValueError('Invalid queue item ID.')
        name,spec,seed=self.specification(request,admit=not self.accepted(identifier))
        identity=hashlib.sha256((name+'\n'+spec).encode()).hexdigest()
        with self.database() as db:
            previous=db.execute(f'SELECT {COLUMNS} FROM jobs WHERE id=?',(identifier,)).fetchone()
            if previous:
                if previous['state']=='deleted':raise Conflict('This test was deleted. Add it again as a new test.')
                if previous['original_hash']!=identity:raise Conflict('This queue ID already belongs to a different submission.')
                return self.metadata(db,previous)
            if db.execute("SELECT COUNT(*) FROM jobs WHERE state NOT IN ('deleted','archived')").fetchone()[0]>=LIMIT:
                raise Conflict('The queue has 100 records. Delete a chosen record before adding another.')
            position=db.execute('SELECT COALESCE(MAX(position),0)+1 FROM jobs').fetchone()[0]
            db.execute('INSERT INTO jobs(id,name,spec,original_hash,position,state,created_at,seed) VALUES(?,?,?,?,?,?,?,?)',
                       (identifier,name,spec,identity,position,'queued',now(),seed))
            return self.metadata(db,self.row(db,identifier))

    def accepted(self,identifier):
        """Read only submission presence; enqueue still checks the exact receipt."""
        if not isinstance(identifier,str):return False
        with self.database() as db:
            return db.execute("SELECT 1 FROM jobs WHERE id=? AND state!='deleted'",(identifier,)).fetchone() is not None

    def listing(self):
        with self.database() as db:
            return dict(limit=LIMIT,paused=bool(db.execute('SELECT paused FROM control').fetchone()[0]),
                        library_revision=db.execute("SELECT COUNT(*) FROM jobs WHERE state='archived'").fetchone()[0],
                        records=[self.metadata(db,row) for row in db.execute(f"SELECT {COLUMNS} FROM jobs WHERE state NOT IN ('deleted','archived') ORDER BY position,id")])

    def get(self,identifier):
        with self.database() as db:
            row=self.row(db,identifier,include_snapshot=True);result=self.metadata(db,row)
            packed=row['snapshot']
        if packed is not None:
            durable_evidence.eager_guard(packed)
            result['snapshot']=json.loads(zlib.decompress(packed))
        return result

    def pause(self,paused):
        if type(paused) is not bool:raise ValueError('Choose pause or resume.')
        with self.database() as db:db.execute('UPDATE control SET paused=?',(int(paused),))
        return dict(paused=paused)

    def change(self,identifier,action,request):
        """An edit version protects settings; ordinary revisions also track order.

        Keep the latest edit and its completion receipt per job. Retrying its
        exact Save/Cancel is safe after execution starts. A newer hold replaces
        that receipt and invalidates the previous editor, without losing jobs.
        Legacy clients still use the ordinary revision for every mutation.
        """
        with self.database() as db:
            row=self.row(db,identifier)
            edit=db.execute('SELECT * FROM edits WHERE job_id=?',(identifier,)).fetchone()
            token=request.get('edit_id')
            fingerprint=None
            if token is not None:
                if not isinstance(token,str) or not re.fullmatch('[0-9a-f]{32}',token):raise ValueError('Invalid queue edit ID.')
                if action=='hold' and edit and edit['id']==token:
                    return self.metadata(db,row)
                if action in ('update','release'):
                    if not edit or edit['id']!=token or request.get('edit_revision')!=edit['revision']:
                        raise Conflict('This edit has ended or was replaced. Refresh the queue.')
                    content={key:request.get(key) for key in ('name','mode','options','catalog','presentation')} if action=='update' else {}
                    fingerprint=hashlib.sha256(encode(dict(action=action,content=content)).encode()).hexdigest()
                    if edit['state']!='active':
                        if edit['request_hash']==fingerprint:return self.metadata(db,row)
                        raise Conflict('This edit has already ended. Refresh the queue.')
            if not (token is not None and action in ('update','release')) and request.get('revision')!=row['revision']:
                raise Conflict('This test changed in another browser. Refresh the queue.')
            state=row['state']
            if action=='delete':
                transfer=db.execute('SELECT state FROM transfers WHERE job_id=?',(identifier,)).fetchone()
                if transfer and transfer['state']=='reserved':raise Conflict('This completed result is moving to Saved backtests. Refresh and retry after the transfer finishes.')
                if state=='archived':raise Conflict('This result moved to Saved backtests. Delete it from the saved library.')
                if state in ('running','stopping'):raise Conflict('Stop the running test before deleting it.')
                # Keep only the submission receipt, so a lost-ack retry cannot
                # resurrect an explicitly deleted test or its holdings.
                db.execute("UPDATE jobs SET state='deleted',name='',spec='{}',snapshot=NULL,progress=NULL,configuration=NULL,plan=NULL,seed=NULL,error=NULL,cagr=NULL,revision=revision+1 WHERE id=?",(identifier,))
                durable_evidence.delete(db,identifier)
                db.execute('DELETE FROM edits WHERE job_id=?',(identifier,))
                db.execute('DELETE FROM transfers WHERE job_id=?',(identifier,))
                return dict(id=identifier,deleted=True)
            if action=='stop':
                target='stopping' if state in ('running','stopping') else 'cancelled' if state in ('queued','held') else state
                db.execute('UPDATE jobs SET state=?,revision=revision+1 WHERE id=?',(target,identifier))
                db.execute("UPDATE edits SET state='ended',request_hash=NULL WHERE job_id=? AND state='active'",(identifier,))
            elif action in ('hold','release','update','move'):
                if state not in ('queued','held'):raise Conflict('Only waiting tests can be edited or moved.')
                if action=='hold':
                    db.execute("UPDATE jobs SET state='held',revision=revision+1 WHERE id=?",(identifier,))
                    db.execute('INSERT OR REPLACE INTO edits(job_id,id,revision,state) VALUES(?,?,?,?)',
                               (identifier,token or secrets.token_hex(16),row['revision']+1,'active'))
                elif action=='release':
                    db.execute("UPDATE jobs SET state='queued',revision=revision+1 WHERE id=?",(identifier,))
                elif action=='update':
                    if state!='held':raise Conflict('Select Edit before changing this test.')
                    name,spec,seed=self.specification(request)
                    old,new=json.loads(row['spec']),json.loads(spec)
                    # A legacy omission means filter-first. Exposing that
                    # default during a name-only edit must retain recorded dates.
                    same=old['mode']==new['mode'] and strategy_requests.options_calculation_equal(old['options'],new['options'])
                    if same:seed=row['seed']
                    db.execute("UPDATE jobs SET name=?,spec=?,seed=?,state='queued',progress=NULL,configuration=CASE WHEN ? THEN configuration ELSE NULL END,plan=CASE WHEN ? THEN plan ELSE NULL END,error=NULL,started=NULL,finished=NULL,revision=revision+1 WHERE id=?",
                               (name,spec,seed,same,same,identifier))
                else:
                    direction=request.get('direction')
                    if type(direction) is not int or direction not in (-1,1):raise ValueError('Choose move up or move down.')
                    relation,order=('<','DESC') if direction==-1 else ('>','ASC')
                    neighbor=db.execute(f"SELECT id,position FROM jobs WHERE state IN ('queued','held') AND position {relation} ? ORDER BY position {order} LIMIT 1",(row['position'],)).fetchone()
                    if neighbor:
                        db.execute('UPDATE jobs SET position=?,revision=revision+1 WHERE id=?',(row['position'],neighbor['id']))
                        db.execute('UPDATE jobs SET position=?,revision=revision+1 WHERE id=?',(neighbor['position'],identifier))
            else:raise ValueError('Unknown queue action.')
            if action in ('update','release'):
                db.execute('UPDATE edits SET state=?,request_hash=? WHERE job_id=? AND state=\'active\'',
                           ('saved' if action=='update' else 'cancelled',fingerprint,identifier))
            return self.metadata(db,self.row(db,identifier))

    def recover(self):
        """Only the exclusive consumer may recover an interrupted predecessor."""
        with self.database() as db:
            db.execute("UPDATE transfers SET state='pending' WHERE state='reserved'")
            db.execute("UPDATE jobs SET state='queued',started=NULL,progress=NULL,error=NULL,revision=revision+1 WHERE state='running'")
            db.execute("UPDATE jobs SET state='cancelled',finished=?,revision=revision+1 WHERE state='stopping'",(now(),))

    def claim(self,engines=None):
        with self.database() as db:
            if db.execute('SELECT paused FROM control').fetchone()[0]:return None
            rows=db.execute(f"SELECT {COLUMNS} FROM jobs WHERE state='queued' ORDER BY position,id")
            row=next((row for row in rows if engines is None or engine_id(json.loads(row['spec'])['options']) in engines),None)
            if row is None:return None
            db.execute("UPDATE jobs SET state='running',started=?,finished=NULL,error=NULL,progress=NULL,revision=revision+1 WHERE id=?",(now(),row['id']))
            return dict(self.row(db,row['id'],include_plan=True))

    def stopped(self,identifier):
        """Poll committed Stop intent through a short read-only connection.

        Callers must not hold their own publication transaction while polling.
        """
        if not self.path.exists():raise Missing('Queued test not found. Refresh the queue.')
        db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
        db.row_factory=sqlite3.Row
        try:return self.row(db,identifier)['state']=='stopping'
        finally:db.close()

    def progress(self,identifier,field,value):
        if field not in ('progress','configuration'):raise ValueError('Invalid queue progress field.')
        with self.database() as db:
            if field=='configuration':
                summary={key:value[key] for key in ('seed','requested','start','end','months','calendar') if key in value}
                db.execute('UPDATE jobs SET configuration=?,plan=? WHERE id=?',(encode(summary),encode(value),identifier))
            else:db.execute('UPDATE jobs SET progress=? WHERE id=?',(encode(value),identifier))

    @staticmethod
    def completion_identity(metadata,reader=None,*,evidence=None):
        """Bind exact completed meaning and bytes, including after archival."""
        if reader is not None:
            size=reader.stream.seek(0,2)
            evidence=dict(bytes=size,sha256=durable_evidence._digest(reader.stream,size),
                piece_bytes=reader.piece_bytes,record_bytes=reader.record_bytes,manifest=reader.manifest)
        if evidence is not None:
            evidence={key:evidence[key] for key in ('bytes','sha256','piece_bytes','record_bytes','manifest')}
        return hashlib.sha256(encode(dict(metadata=metadata,evidence=evidence)).encode()).hexdigest()

    def completed(self):
        """Small identities only; never load holdings while enumerating work."""
        with self.database() as db:
            return [row[0] for row in db.execute("SELECT id FROM jobs WHERE state='complete' ORDER BY position,id")]

    def reserve_completed(self,identifier):
        """Fence explicit deletion before detaching a transfer's immutable source."""
        with self.database() as db:
            row=self.row(db,identifier,include_snapshot=True)
            if row['state']!='complete':raise Conflict('Only a completed result can move to Saved backtests.')
            transfer=db.execute('SELECT * FROM transfers WHERE job_id=?',(identifier,)).fetchone()
            if transfer is None:
                if durable_evidence.is_evidence(row['snapshot']):
                    metadata,evidence=durable_evidence._unpack(row['snapshot'],identifier,durable_evidence.MAX_EVIDENCE_BYTES)
                    identity=self.completion_identity(metadata,evidence=evidence)
                else:identity=self.completion_identity(json.loads(zlib.decompress(row['snapshot'])))
                db.execute("INSERT INTO transfers(job_id,state,completion) VALUES(?,'reserved',?)",(identifier,identity))
            else:db.execute("UPDATE transfers SET state='reserved',error=NULL WHERE job_id=?",(identifier,))
            return self.metadata(db,row)

    @contextmanager
    def completed_source(self,identifier):
        """Yield an independent source after closing the queue read transaction."""
        with self.database() as db:
            row=self.row(db,identifier,include_snapshot=True)
            transfer=db.execute('SELECT state FROM transfers WHERE job_id=?',(identifier,)).fetchone()
            if row['state']!='complete' or not transfer or transfer['state']!='reserved':
                raise Conflict('Completed result transfer is not reserved.')
            packed=row['snapshot']
        if durable_evidence.is_evidence(packed):
            with self.open_evidence(identifier) as source:yield source
        else:yield json.loads(zlib.decompress(packed))

    def transfer_failed(self,identifier,reason):
        with self.database() as db:
            db.execute("UPDATE transfers SET state='pending',error=? WHERE job_id=? AND state='reserved'",(reason,identifier))

    def archive_completed(self,identifier,saved_id):
        """A durable library receipt precedes releasing duplicate result bytes."""
        saved_backtests.Store.check_id(saved_id)
        with self.database() as db:
            row=self.row(db,identifier)
            previous=db.execute('SELECT * FROM transfers WHERE job_id=?',(identifier,)).fetchone()
            if row['state']=='archived' and previous and previous['saved_id']==saved_id:return
            if row['state']!='complete' or not previous or previous['state']!='reserved':
                raise Conflict('Completed result transfer is not reserved.')
            db.execute("UPDATE transfers SET state='archived',saved_id=?,error=NULL WHERE job_id=?",(saved_id,identifier))
            db.execute("UPDATE jobs SET state='archived',snapshot=NULL,progress=NULL,plan=NULL,revision=revision+1 WHERE id=?",(identifier,))
            durable_evidence.delete(db,identifier)

    def finish_evidence(self,identifier,metadata,reader):
        """Explicit dormant completion. Queue intent owns publication precedence.

        No engine or financial resource is acquired under this transaction.
        Exact completion retries preserve the first bytes and revision.
        """
        with self.database() as db:
            row=self.row(db,identifier,include_snapshot=True,include_plan=True)
            if row['state']=='archived':
                receipt=db.execute('SELECT completion FROM transfers WHERE job_id=?',(identifier,)).fetchone()
                if receipt and receipt['completion']==self.completion_identity(metadata,reader):
                    return dict(id=identifier,state='archived')
                raise Conflict('Completed evidence differs from the original snapshot.')
            if row['state']=='stopping':
                db.execute("UPDATE jobs SET state='cancelled',finished=?,revision=revision+1 WHERE id=?",(now(),identifier))
                return dict(id=identifier,state='cancelled')
            if row['state']=='complete' and durable_evidence.is_evidence(row['snapshot']):
                if not durable_evidence.matches(db,identifier,row['snapshot'],metadata,reader):
                    raise Conflict('Completed evidence differs from the original snapshot.')
                return dict(id=identifier,state='complete')
            if row['state']!='running':raise Conflict('Only a running test can complete its evidence.')
            spec=json.loads(row['spec'])
            if (not durable_evidence.same(metadata.get('settings'),dict(mode=spec['mode'],**spec['options']))
                    or not durable_evidence.same(metadata.get('catalog'),spec['catalog'])
                    or not durable_evidence.same(metadata.get('presentation'),spec['presentation'])
                    or metadata.get('kind')!=spec['mode']):
                raise Conflict('Snapshot differs from the submitted queued test.')
            plan=json.loads(row['plan']) if row['plan'] else None
            if (not durable_evidence.same(reader.metadata.get('configuration'),plan)
                    or spec['mode']=='random' and reader.metadata.get('options',{}).get('seed')!=row['seed']):
                raise Conflict('Snapshot differs from the recorded queue plan.')
            with durable_evidence.publication(db,identifier,metadata,reader,budget=self.evidence_budget) as packed:
                db.execute("UPDATE jobs SET state='complete',snapshot=?,cagr=?,error=NULL,finished=?,revision=revision+1 WHERE id=?",
                    (packed,artifacts.information(metadata)['cagr'],now(),identifier))
                backtest_control.checkpoint();db.commit()
            return dict(id=identifier,state='complete')

    @contextmanager
    def open_evidence(self,identifier):
        """Detach a complete stored result before exposing an independent reader."""
        if not self.path.exists():raise Missing('Queued test not found. Refresh the queue.')
        db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
        opened=None
        try:
            db.execute('BEGIN')
            row=db.execute("SELECT substr(snapshot,1,?) FROM jobs WHERE id=? AND state='complete'",
                (durable_evidence.MAX_ENVELOPE_BYTES+1,identifier)).fetchone()
            if row is None:raise Missing('Completed queued evidence not found.')
            opened=durable_evidence.detach(db,identifier,row[0],budget=self.evidence_budget)
        finally:db.close()
        try:yield opened
        finally:opened.close()

    def finish(self,identifier,state,*,snapshot=None,error=None,diagnostic=None):
        """Retain new scalar failure details in the existing error column.

        Metadata exposes the original text plus additive diagnostics. Old error
        strings and records are neither migrated nor rewritten.
        """
        packed=zlib.compress(encode(snapshot).encode(),3) if snapshot is not None else None
        cagr=artifacts.information(snapshot)['cagr'] if snapshot else None
        with self.database() as db:
            current=self.row(db,identifier)['state']
            transfer=db.execute('SELECT * FROM transfers WHERE job_id=?',(identifier,)).fetchone()
            if current=='archived' or transfer and transfer['state']=='reserved':
                if state=='complete' and snapshot is not None and transfer['completion']==self.completion_identity(snapshot):return
                raise Conflict('Completed result differs from the original snapshot.')
            if current=='stopping':state='cancelled';packed=None;cagr=None
            stored_error=SCALAR_FAILURE+encode(dict(error=error,**diagnostic)) if state=='failed' and diagnostic else error
            db.execute('UPDATE jobs SET state=?,snapshot=?,cagr=?,error=?,finished=?,revision=revision+1 WHERE id=?',
                       (state,packed,cagr,stored_error,now() if state!='queued' else None,identifier))


class Queue:
    """One durable consumer; UI mutations remain available during calculation."""
    def __init__(self,store=None,*,calculations=None,library=None):
        self.store=store or Store();self.library=library if library is not None else saved_backtests.Store();self.stopping=Event();self.wake=Event();self.lock=Lock();self.thread=None
        self.owner=cache_access.WorkspaceAccess(self.store.path.with_suffix('.lock'))
        self.calculations=calculations if calculations is not None else Original()
        self.evidence=temporary_evidence.Workspace()

    @property
    def ready(self):return self.calculations.ready

    @ready.setter
    def ready(self,value):self.calculations.ready=value

    def start(self):
        with self.lock:
            if self.stopping.is_set():raise Conflict('The server is stopping. Reopen the queue after restart.')
            if self.thread is None:
                self.thread=Thread(target=self._worker,name='backtest-queue',daemon=False);self.thread.start()

    def _worker(self):
        while not self.stopping.is_set():
            try:
                with self.owner.hold(timeout=.1):
                    self.store.recover()
                    while not self.stopping.is_set():
                        self.reconcile_completed()
                        if not self.ready():self.wake.wait(.5);self.wake.clear();continue
                        engines=self.calculations.queue_engines() if hasattr(self.calculations,'queue_engines') else None
                        job=self.store.claim(engines)
                        if job is None:self.wake.wait(.5);self.wake.clear();continue
                        self._run(job)
            except ValueError:
                self.stopping.wait(.5)
            except Exception as error:
                diagnostics.failure('queue.worker_failed',error)
                self.stopping.wait(1)

    def reconcile_completed(self):
        """Retry storage independently of calculation readiness, pause and errors."""
        for identifier in self.store.completed():
            if self.stopping.is_set():break
            try:
                job=self.store.reserve_completed(identifier)
                receipt=self.library.accept_queue_result(identifier,job['name'],lambda:self.store.completed_source(identifier))
                self.store.archive_completed(identifier,receipt['saved_id'])
            except Missing:
                continue  # An explicit deletion won before reservation.
            except saved_backtests.Full:
                self.store.transfer_failed(identifier,'full')
            except Exception as error:
                diagnostics.failure('queue.transfer_failed',error)
                self.store.transfer_failed(identifier,'retry')

    def _run(self,job):
        identifier=job['id'];last_check=last_progress=0.;cancelled=False
        spec=json.loads(job['spec']);options=dict(spec['options'])
        if spec['mode']=='random':options['seed']=job['seed']
        def stopped():
            nonlocal last_check,cancelled
            if self.stopping.is_set():return True
            stamp=time.monotonic()
            if stamp-last_check>.2:
                cancelled=self.store.stopped(identifier);last_check=stamp
            return cancelled
        def progress(event):
            nonlocal last_progress
            stamp=time.monotonic()
            if event is None or event.get('type')=='waiting' or stamp-last_progress>.3:
                self.store.progress(identifier,'progress',event);last_progress=stamp
        entry=None
        try:
            if 'strategy' in options:
                limits=dict(max_bytes=256*1024**2,piece_bytes=1024*1024,record_bytes=8*1024*1024)
                entry=self.evidence.reserve(planned=json.loads(job['plan']) if job['plan'] else None,**limits)
                with backtest_control.cancel_when(stopped):
                    with self.evidence.destination(entry) as destination:
                        completion=self.calculations.calculate_into(spec['mode'],options,destination,progress,
                            lambda value:self.store.progress(identifier,'configuration',value),
                            planned=self.evidence.plan(entry),admission='queue',**limits)
                    backtest_control.checkpoint()
                    self.evidence.publish(entry,completion)
                    with self.evidence.reader(entry) as reader:
                        snapshot=dict(version=4,kind=spec['mode'],settings=dict(mode=spec['mode'],**spec['options']),
                            result=reader.manifest['summary'],catalog=spec['catalog'],presentation=spec['presentation'],captured_at=now())
                        # Publication checks committed Stop intent under its own
                        # writer. A spill can block another reader in this thread.
                        with backtest_control.cancel_when(self.stopping.is_set):
                            self.store.finish_evidence(identifier,snapshot,reader)
                return
            with backtest_control.cancel_when(stopped):
                result=self.calculations.calculate(spec['mode'],options,progress,lambda value:self.store.progress(identifier,'configuration',value),
                                               planned=json.loads(job['plan']) if job['plan'] else None,
                                               admission='queue')
                backtest_control.checkpoint()
            snapshot=dict(version=2,kind=spec['mode'],settings=dict(mode=spec['mode'],**spec['options']),
                          result=result,catalog=spec['catalog'],presentation=spec['presentation'],captured_at=now())
            artifacts.validate(snapshot)
            self.store.finish(identifier,'complete',snapshot=snapshot)
        except backtest_control.Cancelled:
            self.store.finish(identifier,'queued' if self.stopping.is_set() else 'cancelled')
        except (Unavailable,Busy):
            self.store.finish(identifier,'queued')
        except Exception as error:
            diagnostics.failure('queue.test_failed',error)
            message=str(error) if isinstance(error,(ValueError,TypeError)) else 'Test failed. Check the server development log.'
            diagnostic=strategy_requests.failure_details(error) if 'strategy' in options else None
            self.store.finish(identifier,'failed',error=message,**({'diagnostic':diagnostic} if diagnostic else {}))
        finally:
            if entry is not None:self.evidence.discard(entry)

    def request_stop(self):
        """Publish shutdown intent before shared admission can wake a waiter."""
        self.stopping.set();self.wake.set()

    def close(self):
        self.request_stop()
        if self.thread:self.thread.join()
        self.evidence.close()
