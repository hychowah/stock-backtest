"""Durable result snapshots, independent of rebuildable financial caches."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import uuid
import zlib

from backtest.runtime import backtest_control as backtest_control
from backtest.application import durable_evidence as durable_evidence
from backtest.application import artifacts
from backtest.paths import ROOT
DATABASE = ROOT/'data'/'saved-backtests.sqlite'
LIMIT = 100
MAX_BYTES = 128*1024*1024
INLINE_LIMIT_MESSAGE = 'This inline backtest exceeds the 128 MiB save and open limit.'
SCHEMA = '''CREATE TABLE IF NOT EXISTS records (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL,
 info TEXT NOT NULL, snapshot BLOB NOT NULL
)'''


# The stored settings of a record never change, so each server process reads the
# market of a record one time.
_markets={}


def _market(identifier,packed):
    """The market of the stored settings; None when the stored bytes cannot be read."""
    try:
        settings=(durable_evidence.settings(packed,identifier) if durable_evidence.is_evidence(packed)
                  else json.loads(zlib.decompress(packed))['settings'])
        return settings.get('market','us')
    except (ValueError,KeyError,zlib.error):return None


class Full(ValueError):
    pass


class Missing(ValueError):
    pass


class InlineTooLarge(ValueError):
    pass


def inline_response(record):
    """Encode the complete eager HTTP response under its transport ceiling."""
    body=json.dumps(record,allow_nan=False,separators=(',',':')).encode('utf-8')
    if len(body)>MAX_BYTES:raise InlineTooLarge(INLINE_LIMIT_MESSAGE)
    return body



class Store:
    def __init__(self,path=DATABASE,*,evidence_budget=durable_evidence.DEFAULT_BUDGET):
        self.path=Path(path);self.evidence_budget=evidence_budget

    def connect(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        try:
            db.execute(SCHEMA)
            db.execute("CREATE TABLE IF NOT EXISTS queue_imports (source_id TEXT PRIMARY KEY, saved_id TEXT NOT NULL)")
            # A locked record cannot be deleted. Older library files gain this table on open.
            db.execute("CREATE TABLE IF NOT EXISTS locked_backtests (id TEXT PRIMARY KEY)")
            durable_evidence.install(db)
            return db
        except BaseException:
            db.close();raise

    @staticmethod
    def metadata(row):
        return dict(id=row['id'],name=row['name'],created_at=row['created_at'],**json.loads(row['info']))

    def list(self):
        """Every record's metadata, its lock and the market of its stored settings."""
        if not self.path.exists():return []
        db=self.connect()
        try:
            rows=db.execute('SELECT id,name,created_at,info FROM records ORDER BY created_at DESC,id DESC').fetchall()
            locked={row[0] for row in db.execute('SELECT id FROM locked_backtests')}
            for row in rows:
                if row['id'] not in _markets:
                    _markets[row['id']]=_market(row['id'],db.execute('SELECT snapshot FROM records WHERE id=?',(row['id'],)).fetchone()[0])
            return [dict(self.metadata(row),market=_markets[row['id']],locked=row['id'] in locked) for row in rows]
        finally:db.close()

    def save(self,name,snapshot):
        if not isinstance(name,str) or not name.strip() or len(name.strip())>120:
            raise ValueError('Use a backtest name with 1–120 characters.')
        artifacts.validate(snapshot)
        info=artifacts.information(snapshot)
        record=dict(id=uuid.uuid4().hex,name=name.strip(),created_at=datetime.now(timezone.utc).isoformat(),**info)
        inline_response(dict(record,snapshot=snapshot))
        packed=json.dumps(snapshot,allow_nan=False,separators=(',',':')).encode('utf-8')
        compressed=zlib.compress(packed,3)
        db=self.connect()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT COUNT(*) FROM records').fetchone()[0]>=LIMIT:
                    raise Full(f'All {LIMIT} saved slots are used. Delete a saved backtest before saving another.')
                db.execute('INSERT INTO records VALUES(?,?,?,?,?)',
                           (record['id'],record['name'],record['created_at'],json.dumps(info,allow_nan=False),compressed))
            return record
        finally:db.close()

    def save_evidence(self,name,metadata,reader):
        """Atomically save a complete pinned source; never evict another record."""
        if not isinstance(name,str) or not 1<=len(name.strip())<=120:
            raise ValueError('Use a backtest name with 1–120 characters.')
        if metadata.get('kind')=='latest':raise ValueError('Run a historical backtest before saving it.')
        info=artifacts.information(metadata)
        record=dict(id=uuid.uuid4().hex,name=name.strip(),created_at=datetime.now(timezone.utc).isoformat(),**info)
        db=self.connect()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT COUNT(*) FROM records').fetchone()[0]>=LIMIT:
                    raise Full(f'All {LIMIT} saved slots are used. Delete a saved backtest before saving another.')
                with durable_evidence.publication(db,record['id'],metadata,reader,budget=self.evidence_budget) as packed:
                    db.execute('INSERT INTO records VALUES(?,?,?,?,?)',
                        (record['id'],record['name'],record['created_at'],json.dumps(info,allow_nan=False),packed))
                    backtest_control.checkpoint();db.commit()
            return record
        finally:db.close()

    def accept_queue_result(self,source_id,name,open_source):
        """Admit one completed queue source exactly once, without financial access.

        Open the independent source lazily, only when no receipt exists and a
        slot is available. Close the short preflight before opening the source.
        Publication rechecks both conditions atomically. Receipts survive
        deletion; retries keep the first ID and later rename or deletion.
        """
        self.check_id(source_id)
        def admission(db):
            previous=db.execute('SELECT saved_id FROM queue_imports WHERE source_id=?',(source_id,)).fetchone()
            if previous:
                row=db.execute('SELECT id,name,created_at,info FROM records WHERE id=?',(previous['saved_id'],)).fetchone()
                return dict(saved_id=previous['saved_id'],deleted=row is None,record=self.metadata(row) if row else None)
            if db.execute('SELECT COUNT(*) FROM records').fetchone()[0]>=LIMIT:
                raise Full(f'All {LIMIT} saved slots are used. Delete a saved backtest before saving another.')
        db=self.connect()
        try:previous=admission(db)
        finally:db.close()
        if previous is not None:return previous
        with open_source() as source:
            db=self.connect()
            try:
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    previous=admission(db)
                    if previous is not None:return previous
                    if not isinstance(name,str) or not 1<=len(name.strip())<=120:
                        raise ValueError('Use a backtest name with 1–120 characters.')
                    metadata=source if isinstance(source,dict) else source.metadata
                    info=artifacts.information(metadata)
                    record=dict(id=uuid.uuid4().hex,name=name.strip(),created_at=datetime.now(timezone.utc).isoformat(),**info)
                    def insert(packed):
                        db.execute('INSERT INTO records VALUES(?,?,?,?,?)',
                            (record['id'],record['name'],record['created_at'],json.dumps(info,allow_nan=False),packed))
                        db.execute('INSERT INTO queue_imports VALUES(?,?)',(source_id,record['id']))
                    if isinstance(source,dict):
                        artifacts.validate(source)
                        inline_response(dict(record,snapshot=source))
                        packed=json.dumps(source,allow_nan=False,separators=(',',':')).encode('utf-8')
                        insert(zlib.compress(packed,3))
                    else:
                        with source.open_reader() as reader:
                            with durable_evidence.publication(db,record['id'],metadata,reader,budget=self.evidence_budget) as packed:
                                insert(packed);backtest_control.checkpoint();db.commit()
                    return dict(saved_id=record['id'],deleted=False,record=record)
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
            try:snapshot=artifacts.validate(json.loads(zlib.decompress(row['snapshot'])))
            except (ValueError,TypeError,zlib.error) as error:
                raise ValueError('This saved backtest cannot be read. Its stored record was kept.') from error
            return dict(**self.metadata(row),snapshot=snapshot)
        finally:db.close()

    def rename(self,identifier,name):
        """Change the display name only; preserve identity and complete evidence."""
        self.check_id(identifier)
        if not isinstance(name,str) or not 1<=len(name.strip())<=120:
            raise ValueError('Use a backtest name with 1–120 characters.')
        if not self.path.exists():raise Missing('Saved backtest not found.')
        db=self.connect()
        try:
            with db:
                if db.execute('UPDATE records SET name=? WHERE id=?',(name.strip(),identifier)).rowcount!=1:
                    raise Missing('Saved backtest not found.')
                row=db.execute('SELECT id,name,created_at,info FROM records WHERE id=?',(identifier,)).fetchone()
            return self.metadata(row)
        finally:db.close()

    def lock(self,identifier,locked):
        """Lock or unlock a record; the record itself does not change."""
        self.check_id(identifier)
        if not self.path.exists():raise Missing('Saved backtest not found.')
        db=self.connect()
        try:
            with db:
                if db.execute('SELECT 1 FROM records WHERE id=?',(identifier,)).fetchone() is None:
                    raise Missing('Saved backtest not found.')
                if locked:db.execute('INSERT OR IGNORE INTO locked_backtests VALUES(?)',(identifier,))
                else:db.execute('DELETE FROM locked_backtests WHERE id=?',(identifier,))
            return dict(id=identifier,locked=locked)
        finally:db.close()

    def delete(self,identifier):
        self.check_id(identifier)
        if not self.path.exists():raise Missing('Saved backtest not found.')
        db=self.connect()
        try:
            with db:
                if db.execute('SELECT 1 FROM locked_backtests WHERE id=?',(identifier,)).fetchone():
                    raise ValueError('Unlock this saved backtest before deleting it.')
                durable_evidence.delete(db,identifier)
                if db.execute('DELETE FROM records WHERE id=?',(identifier,)).rowcount!=1:
                    raise Missing('Saved backtest not found.')
        finally:db.close()

    @staticmethod
    def check_id(identifier):
        if not isinstance(identifier,str) or not re.fullmatch('[0-9a-f]{32}',identifier):
            raise Missing('Saved backtest not found.')
