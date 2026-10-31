"""Durable result snapshots, independent of rebuildable financial caches."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import uuid
import zlib

import backtest_control
import durable_evidence

DATABASE = Path(__file__).resolve().parents[1]/'data'/'saved-backtests.sqlite'
LIMIT = 20
MAX_BYTES = 512*1024*1024
SCHEMA = '''CREATE TABLE IF NOT EXISTS records (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL,
 info TEXT NOT NULL, snapshot BLOB NOT NULL
)'''


class Full(ValueError):
    pass


class Missing(ValueError):
    pass


def validate(snapshot):
    """Check completeness, without reinterpreting financial calculations."""
    if not isinstance(snapshot,dict) or snapshot.get('version') not in (1,2):
        raise ValueError('Unsupported saved backtest format.')
    kind=snapshot.get('kind')
    if kind not in ('january','custom','random'):
        raise ValueError('Run a historical backtest before saving it.')
    settings=snapshot.get('settings');result=snapshot.get('result')
    if not isinstance(settings,dict) or settings.get('mode')!=kind or not isinstance(result,dict):
        raise ValueError('The result and its submitted settings are required.')
    groups=result.get('years' if kind=='january' else 'periods')
    if kind=='random':
        details=result.get('trial_results');trials=result.get('trials')
        if not isinstance(details,list) or not isinstance(trials,list) or not trials or len(details)!=len(trials) or len(trials)!=result.get('completed'):
            raise ValueError('All random trials must include their traded stocks before saving.')
        groups=[]
        for trial,detail in zip(trials,details):
            if not isinstance(trial,dict):raise ValueError('Missing random-trial summary.')
            if not isinstance(detail,dict) or not isinstance(detail.get('periods'),list):
                raise ValueError('Missing random-trial holdings.')
            if len(detail['periods'])!=trial.get('periods'):
                raise ValueError('Incomplete random-trial holdings.')
            groups.extend(detail['periods'])
    if not isinstance(groups,list) or not groups:
        raise ValueError('The complete holding periods are required.')
    for group in groups:
        if not isinstance(group,dict) or not isinstance(group.get('holdings'),list) or len(group['holdings'])!=group.get('names'):
            raise ValueError('Each holding period must contain all traded stocks.')
        if 'portfolio' not in group or 'spy' not in group or any(not isinstance(h,dict) or 'symbol' not in h or 'return_value' not in h for h in group['holdings']):
            raise ValueError('Stock and period returns are required.')
    catalog=snapshot.get('catalog')
    if catalog is not None and (not isinstance(catalog,dict) or not isinstance(catalog.get('metrics'),dict) or not isinstance(catalog.get('filters'),dict)):
        raise ValueError('Saved display labels are invalid.')
    if snapshot['version']==2 and not isinstance(snapshot.get('presentation'),dict):
        raise ValueError('Saved presentation context is required.')
    return snapshot


def information(snapshot):
    result=snapshot['result'];kind=snapshot['kind']
    configuration=result.get('configuration',{}) if kind=='random' else result
    dates=configuration.get('calendar',configuration)
    return dict(kind=kind,start=dates.get('start',result.get('first')),
                end=dates.get('end',result.get('end')),
                cagr=result.get('cagr') if kind!='random' else result.get('distributions',{}).get('cagr',{}).get('mean'),
                trials=result.get('completed') if kind=='random' else None)


class Store:
    def __init__(self,path=DATABASE,*,evidence_budget=durable_evidence.DEFAULT_BUDGET):
        self.path=Path(path);self.evidence_budget=evidence_budget

    def connect(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        try:
            db.execute(SCHEMA)
            durable_evidence.install(db)
            return db
        except BaseException:
            db.close();raise

    @staticmethod
    def metadata(row):
        return dict(id=row['id'],name=row['name'],created_at=row['created_at'],**json.loads(row['info']))

    def list(self):
        if not self.path.exists():return []
        db=self.connect()
        try:return [self.metadata(row) for row in db.execute('SELECT id,name,created_at,info FROM records ORDER BY created_at DESC,id DESC')]
        finally:db.close()

    def save(self,name,snapshot):
        if not isinstance(name,str) or not name.strip() or len(name.strip())>120:
            raise ValueError('Use a backtest name with 1–120 characters.')
        validate(snapshot)
        packed=json.dumps(snapshot,allow_nan=False,separators=(',',':')).encode('utf-8')
        if len(packed)>MAX_BYTES:raise ValueError('This backtest is too large to save as one record.')
        compressed=zlib.compress(packed,3)
        info=information(snapshot)
        record=dict(id=uuid.uuid4().hex,name=name.strip(),created_at=datetime.now(timezone.utc).isoformat(),**info)
        db=self.connect()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT COUNT(*) FROM records').fetchone()[0]>=LIMIT:
                    raise Full('All 20 saved slots are used. Delete a saved backtest before saving another.')
                db.execute('INSERT INTO records VALUES(?,?,?,?,?)',
                           (record['id'],record['name'],record['created_at'],json.dumps(info,allow_nan=False),compressed))
            return record
        finally:db.close()

    def save_evidence(self,name,metadata,reader):
        """Atomically save a complete pinned source; never evict another record."""
        if not isinstance(name,str) or not 1<=len(name.strip())<=120:
            raise ValueError('Use a backtest name with 1–120 characters.')
        info=information(metadata)
        record=dict(id=uuid.uuid4().hex,name=name.strip(),created_at=datetime.now(timezone.utc).isoformat(),**info)
        db=self.connect()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT COUNT(*) FROM records').fetchone()[0]>=LIMIT:
                    raise Full('All 20 saved slots are used. Delete a saved backtest before saving another.')
                with durable_evidence.publication(db,record['id'],metadata,reader,budget=self.evidence_budget) as packed:
                    db.execute('INSERT INTO records VALUES(?,?,?,?,?)',
                        (record['id'],record['name'],record['created_at'],json.dumps(info,allow_nan=False),packed))
                    backtest_control.checkpoint();db.commit()
            return record
        finally:db.close()

    @contextmanager
    def open_evidence(self,identifier):
        """Yield independent complete evidence without financial access.

        The consistent database copy closes before yield. Deletion cannot
        invalidate an active reader. The caller closes this context explicitly.
        """
        self.check_id(identifier)
        if not self.path.exists():raise Missing('Saved backtest not found.')
        db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
        opened=None
        try:
            db.execute('BEGIN')
            row=db.execute('SELECT substr(snapshot,1,?) FROM records WHERE id=?',
                (durable_evidence.MAX_ENVELOPE_BYTES+1,identifier)).fetchone()
            if row is None:raise Missing('Saved backtest not found.')
            opened=durable_evidence.detach(db,identifier,row[0],budget=self.evidence_budget)
        finally:
            db.close()
        try:yield opened
        finally:opened.close()

    def get(self,identifier):
        self.check_id(identifier)
        if not self.path.exists():raise Missing('Saved backtest not found.')
        db=self.connect()
        try:
            row=db.execute('SELECT * FROM records WHERE id=?',(identifier,)).fetchone()
            if row is None:raise Missing('Saved backtest not found.')
            durable_evidence.eager_guard(row['snapshot'])
            try:snapshot=validate(json.loads(zlib.decompress(row['snapshot'])))
            except (ValueError,TypeError,zlib.error) as error:
                raise ValueError('This saved backtest cannot be read. Its stored record was kept.') from error
            return dict(**self.metadata(row),snapshot=snapshot)
        finally:db.close()

    def delete(self,identifier):
        self.check_id(identifier)
        if not self.path.exists():raise Missing('Saved backtest not found.')
        db=self.connect()
        try:
            with db:
                durable_evidence.delete(db,identifier)
                if db.execute('DELETE FROM records WHERE id=?',(identifier,)).rowcount!=1:
                    raise Missing('Saved backtest not found.')
        finally:db.close()

    @staticmethod
    def check_id(identifier):
        if not isinstance(identifier,str) or not re.fullmatch('[0-9a-f]{32}',identifier):
            raise Missing('Saved backtest not found.')
