"""Durable test queue, independent of rebuildable caches and the saved library.

One consumer owns the queue file lock across server instances. Queue database
transactions end before financial ownership is requested. The consumer retains
both queue ownership and server lifetime ownership through engine cleanup.
Only waiting items can change settings or order. Held items are excluded from
execution while a user edits them. Results remain until explicit deletion.
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

import backtest_control
import backtest_jobs
import cache_access
import diagnostics
import saved_backtests

DATABASE=Path(__file__).resolve().parents[1]/'data'/'backtest-queue.sqlite'
LIMIT=100
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
'''


class Conflict(ValueError):pass
class Missing(ValueError):pass


def now():return datetime.now(timezone.utc).isoformat()


def encode(value):return json.dumps(value,allow_nan=False,separators=(',',':'),sort_keys=True)


class Store:
    def __init__(self,path=DATABASE):self.path=Path(path)

    @contextmanager
    def database(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        try:
            db.executescript(SCHEMA)
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
    def metadata(row):
        spec=json.loads(row['spec'])
        result={key:row[key] for key in ('id','name','position','revision','state','created_at','started','finished','error','cagr')}
        return dict(**result,mode=spec['mode'],options=spec['options'],
                    progress=json.loads(row['progress']) if row['progress'] else None,
                    configuration=json.loads(row['configuration']) if row['configuration'] else None)

    @staticmethod
    def specification(request):
        if not isinstance(request,dict):raise ValueError('Expected a queued test.')
        name=request.get('name','').strip() if isinstance(request.get('name',''),str) else ''
        if not 1<=len(name)<=120:raise ValueError('Use a test name with 1–120 characters.')
        if request.get('mode') not in ('custom','random') or not isinstance(request.get('options'),dict):
            raise ValueError('Queue a fixed or random-date backtest from Custom trade date and frequency.')
        for key in ('catalog','presentation'):
            if not isinstance(request.get(key),dict):raise ValueError('The test display labels are required.')
        if any(not isinstance(request['catalog'].get(key),dict) for key in ('metrics','filters')):
            raise ValueError('The test metric and filter labels are required.')
        options=request['options']
        if not isinstance(options.get('start'),str) or not isinstance(options.get('end'),str):
            raise ValueError('Choose start and end dates.')
        spec={key:request[key] for key in ('mode','options','catalog','presentation')}
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
        name,spec,seed=self.specification(request)
        identity=hashlib.sha256((name+'\n'+spec).encode()).hexdigest()
        with self.database() as db:
            previous=db.execute(f'SELECT {COLUMNS} FROM jobs WHERE id=?',(identifier,)).fetchone()
            if previous:
                if previous['state']=='deleted':raise Conflict('This test was deleted. Add it again as a new test.')
                if previous['original_hash']!=identity:raise Conflict('This queue ID already belongs to a different submission.')
                return self.metadata(previous)
            if db.execute("SELECT COUNT(*) FROM jobs WHERE state!='deleted'").fetchone()[0]>=LIMIT:
                raise Conflict('The queue has 100 records. Delete a chosen record before adding another.')
            position=db.execute('SELECT COALESCE(MAX(position),0)+1 FROM jobs').fetchone()[0]
            db.execute('INSERT INTO jobs(id,name,spec,original_hash,position,state,created_at,seed) VALUES(?,?,?,?,?,?,?,?)',
                       (identifier,name,spec,identity,position,'queued',now(),seed))
            return self.metadata(self.row(db,identifier))

    def listing(self):
        with self.database() as db:
            return dict(limit=LIMIT,paused=bool(db.execute('SELECT paused FROM control').fetchone()[0]),
                        records=[self.metadata(row) for row in db.execute(f"SELECT {COLUMNS} FROM jobs WHERE state!='deleted' ORDER BY position,id")])

    def get(self,identifier):
        with self.database() as db:
            row=self.row(db,identifier,include_snapshot=True);result=self.metadata(row)
            packed=row['snapshot']
        if packed is not None:result['snapshot']=json.loads(zlib.decompress(packed))
        return result

    def pause(self,paused):
        if type(paused) is not bool:raise ValueError('Choose pause or resume.')
        with self.database() as db:db.execute('UPDATE control SET paused=?',(int(paused),))
        return dict(paused=paused)

    def change(self,identifier,action,request):
        with self.database() as db:
            row=self.row(db,identifier)
            if request.get('revision')!=row['revision']:raise Conflict('This test changed in another browser. Refresh the queue.')
            state=row['state']
            if action=='delete':
                if state in ('running','stopping'):raise Conflict('Stop the running test before deleting it.')
                # Keep only the submission receipt, so a lost-ack retry cannot
                # resurrect an explicitly deleted test or its holdings.
                db.execute("UPDATE jobs SET state='deleted',name='',spec='{}',snapshot=NULL,progress=NULL,configuration=NULL,plan=NULL,seed=NULL,error=NULL,cagr=NULL,revision=revision+1 WHERE id=?",(identifier,))
                return dict(id=identifier,deleted=True)
            if action=='stop':
                target='stopping' if state in ('running','stopping') else 'cancelled' if state in ('queued','held') else state
                db.execute('UPDATE jobs SET state=?,revision=revision+1 WHERE id=?',(target,identifier))
            elif action in ('hold','release','update','move'):
                if state not in ('queued','held'):raise Conflict('Only waiting tests can be edited or moved.')
                if action=='hold':
                    db.execute("UPDATE jobs SET state='held',revision=revision+1 WHERE id=?",(identifier,))
                elif action=='release':
                    db.execute("UPDATE jobs SET state='queued',revision=revision+1 WHERE id=?",(identifier,))
                elif action=='update':
                    if state!='held':raise Conflict('Select Edit before changing this test.')
                    name,spec,seed=self.specification(request)
                    old,new=json.loads(row['spec']),json.loads(spec)
                    same=old['mode']==new['mode'] and old['options']==new['options']
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
            return self.metadata(self.row(db,identifier))

    def recover(self):
        """Only the exclusive consumer may recover an interrupted predecessor."""
        with self.database() as db:
            db.execute("UPDATE jobs SET state='queued',started=NULL,progress=NULL,error=NULL,revision=revision+1 WHERE state='running'")
            db.execute("UPDATE jobs SET state='cancelled',finished=?,revision=revision+1 WHERE state='stopping'",(now(),))

    def claim(self):
        with self.database() as db:
            if db.execute('SELECT paused FROM control').fetchone()[0]:return None
            row=db.execute(f"SELECT {COLUMNS} FROM jobs WHERE state='queued' ORDER BY position,id LIMIT 1").fetchone()
            if row is None:return None
            db.execute("UPDATE jobs SET state='running',started=?,finished=NULL,error=NULL,progress=NULL,revision=revision+1 WHERE id=?",(now(),row['id']))
            return dict(self.row(db,row['id'],include_plan=True))

    def stopped(self,identifier):
        with self.database() as db:return self.row(db,identifier)['state']=='stopping'

    def progress(self,identifier,field,value):
        if field not in ('progress','configuration'):raise ValueError('Invalid queue progress field.')
        with self.database() as db:
            if field=='configuration':
                summary={key:value[key] for key in ('seed','requested','start','end','months') if key in value}
                db.execute('UPDATE jobs SET configuration=?,plan=? WHERE id=?',(encode(summary),encode(value),identifier))
            else:db.execute('UPDATE jobs SET progress=? WHERE id=?',(encode(value),identifier))

    def finish(self,identifier,state,*,snapshot=None,error=None):
        packed=zlib.compress(encode(snapshot).encode(),3) if snapshot is not None else None
        cagr=saved_backtests.information(snapshot)['cagr'] if snapshot else None
        with self.database() as db:
            current=self.row(db,identifier)['state']
            if current=='stopping':state='cancelled';packed=None;cagr=None
            db.execute('UPDATE jobs SET state=?,snapshot=?,cagr=?,error=?,finished=?,revision=revision+1 WHERE id=?',
                       (state,packed,cagr,error,now() if state!='queued' else None,identifier))


class Queue:
    """One durable consumer; UI mutations remain available during calculation."""
    def __init__(self,store=None):
        self.store=store or Store();self.stopping=Event();self.wake=Event();self.lock=Lock();self.thread=None
        self.owner=cache_access.WorkspaceAccess(self.store.path.with_suffix('.lock'))

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
                        job=self.store.claim()
                        if job is None:self.wake.wait(.5);self.wake.clear();continue
                        self._run(job)
            except ValueError:
                self.stopping.wait(.5)
            except Exception as error:
                diagnostics.failure('queue.worker_failed',error)
                self.stopping.wait(1)

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
            if stamp-last_progress>.3:
                self.store.progress(identifier,'progress',event);last_progress=stamp
        @contextmanager
        def financial():
            # A long manual run or data rebuild must defer queued work, rather
            # than consume the queue as failures after the usual lock timeout.
            waiting=False
            while True:
                backtest_control.checkpoint()
                ownership=cache_access.access(timeout=.25)
                try:ownership.__enter__()
                except ValueError:
                    if not waiting:
                        self.store.progress(identifier,'progress',dict(type='waiting',message='Waiting for another backtest or data operation.'));waiting=True
                    self.stopping.wait(.1);continue
                break
            try:
                if waiting:self.store.progress(identifier,'progress',None)
                yield
            finally:ownership.__exit__(None,None,None)
        try:
            with backtest_control.cancel_when(stopped):
                with financial():
                    result=backtest_jobs.calculate(spec['mode'],options,progress,lambda value:self.store.progress(identifier,'configuration',value),
                                                   planned=json.loads(job['plan']) if job['plan'] else None)
                backtest_control.checkpoint()
            snapshot=dict(version=2,kind=spec['mode'],settings=dict(mode=spec['mode'],**spec['options']),
                          result=result,catalog=spec['catalog'],presentation=spec['presentation'],captured_at=now())
            saved_backtests.validate(snapshot)
            self.store.finish(identifier,'complete',snapshot=snapshot)
        except backtest_control.Cancelled:
            self.store.finish(identifier,'queued' if self.stopping.is_set() else 'cancelled')
        except Exception as error:
            diagnostics.failure('queue.test_failed',error)
            message=str(error) if isinstance(error,(ValueError,TypeError)) else 'Test failed. Check the server development log.'
            self.store.finish(identifier,'failed',error=message)

    def close(self):
        self.stopping.set();self.wake.set()
        if self.thread:self.thread.join()
