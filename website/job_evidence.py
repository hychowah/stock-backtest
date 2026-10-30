"""Temporary byte and reader lifetimes inside backtest_jobs.Jobs.

No job registry, scheduler, financial ownership or durable user store. Expiry
ends new access. Existing readers pin immutable bytes, which remain charged
until closure. Failed file cleanup retains its entry and charge for retry.
"""
from contextlib import contextmanager
from pathlib import Path
from threading import Condition, RLock
import tempfile
import uuid
import hashlib
from copy import deepcopy
import json
import re

import numerical_transfer as transfer
import result_evidence


class Workspace:
    def __init__(self, root=None, *, max_bytes=1024**3):
        if type(max_bytes) is not int or max_bytes<=0:raise ValueError('Invalid temporary evidence budget.')
        self.root=Path(root) if root is not None else None
        self.max_bytes=max_bytes;self.entries={};self.condition=Condition(RLock());self.closed=False
        self.initialized=False

    def reserve(self, *, max_bytes, planned, piece_bytes, record_bytes):
        result_evidence._limits(max_bytes,piece_bytes,record_bytes)
        # Producer + receiver, staged input copies, and atomic slot replacement.
        charge=2*max_bytes+(2*transfer.MAX_PLAN_BYTES if planned is not None else 0)+2*transfer.PIECE_BYTES
        with self.condition:
            self.collect()
            if self.closed:raise ValueError('Temporary evidence workspace is closed.')
            if sum(e['charge'] for e in self.entries.values())+charge>self.max_bytes:
                raise ValueError('Temporary evidence retention budget is exhausted.')
            if not self.initialized:
                if self.root is None:self.root=Path(tempfile.mkdtemp(prefix='backtest-evidence-'))
                else:self.root.mkdir(parents=True,exist_ok=False)
                self.initialized=True
            if self.root.is_symlink():raise ValueError('Temporary evidence root is not private.')
            path=self.root/uuid.uuid4().hex;path.mkdir()
            entry=dict(path=path,charge=charge,pins=0,retired=False,staging=True,bytes=0,
                       limits=dict(max_bytes=max_bytes,piece_bytes=piece_bytes,record_bytes=record_bytes),reference=None)
            self.entries[path.name]=entry
            try:
                if planned is not None:entry['reference']=transfer.stage_plan(path,planned)
            except BaseException:
                self.discard(entry);raise
            return entry

    def plan(self, entry):
        return transfer.read_plan(entry['path'],entry['reference']) if entry['reference'] is not None else None

    def destination(self, entry):return (entry['path']/'receiving.evidence').open('x+b')

    def publish(self, entry, completion):
        """Publish only after calculation owner and complete validation succeed."""
        with self.condition:
            path=entry['path']/'receiving.evidence'
            with path.open('rb') as stream:
                self._verify(stream,completion)
                receiver=result_evidence.Reader(stream,**entry['limits'])
                if receiver.manifest!=completion['manifest']:raise ValueError('Completed evidence manifest differs.')
            if path.stat().st_size!=completion['transfer']['bytes']:raise ValueError('Completed evidence size differs.')
            path.replace(entry['path']/'completed.evidence')
            entry.update(staging=False,bytes=completion['transfer']['bytes'],completion=completion)
            self._release_input(entry)
            entry['charge']=entry['bytes']+self._input_bytes(entry)
            return dict(format_version=result_evidence.FORMAT_VERSION,bytes=entry['bytes'],
                        sha256=completion['transfer']['sha256'],manifest=completion['manifest'])

    def _verify(self,stream,completion):
        digest=hashlib.sha256();size=0
        for part in iter(lambda:stream.read(transfer.PIECE_BYTES),b''):
            digest.update(part);size+=len(part)
            if size>completion['transfer']['bytes']:raise ValueError('Completed evidence grew.')
        if size!=completion['transfer']['bytes'] or digest.hexdigest()!=completion['transfer']['sha256']:
            raise ValueError('Completed evidence content differs.')
        stream.seek(0)

    def _input_bytes(self,entry):
        return sum(p.stat().st_size for p in entry['path'].iterdir() if p.name.startswith('recorded-plan.'))

    def _release_input(self,entry):
        for name in ('recorded-plan.json','recorded-plan.pending'):
            try:(entry['path']/name).unlink(missing_ok=True)
            except OSError:pass  # Keep the actual surviving bytes charged.

    def discard(self, entry):
        with self.condition:
            entry['retired']=True;entry['staging']=False
            self.collect()

    def collect(self):
        with self.condition:
            for key,entry in list(self.entries.items()):
                if not entry['retired'] or entry['pins'] or entry['staging']:continue
                try:
                    for name in ('receiving.evidence','completed.evidence','recorded-plan.json','recorded-plan.pending'):
                        (entry['path']/name).unlink(missing_ok=True)
                    entry['path'].rmdir()
                except OSError:continue
                del self.entries[key]
            self.condition.notify_all()

    @contextmanager
    def pin(self, entry):
        """Acquire a read lifetime without decoding under the Jobs state lock."""
        with self.condition:
            if entry['retired'] or entry['staging'] or self.closed:raise ValueError('Temporary evidence is unavailable.')
            stream=(entry['path']/'completed.evidence').open('rb');entry['pins']+=1
        try:
            yield stream
        finally:
            stream.close()
            with self.condition:
                entry['pins']-=1;self.collect()

    def read(self, entry, stream):
        self._verify(stream,entry['completion'])
        return result_evidence.Reader(stream,**entry['limits'])

    @contextmanager
    def fork_pinned(self,entry):
        """An acquired display pin keeps retired bytes alive for independent reads."""
        with self.condition:
            if not entry['pins'] or entry['staging']:raise ValueError('Evidence has no owning pin.')
            stream=(entry['path']/'completed.evidence').open('rb')
        try:yield self.read(entry,stream)
        finally:stream.close()

    @contextmanager
    def reader(self, entry):
        with self.pin(entry) as stream:yield self.read(entry,stream)

    def measurements(self):
        with self.condition:
            self.collect()
            return dict(budget_bytes=self.max_bytes,reserved_bytes=sum(e['charge'] for e in self.entries.values()),
                staging_bytes=sum(e['charge'] for e in self.entries.values() if e['staging']),
                retained_bytes=sum(e['charge'] for e in self.entries.values() if not e['staging']),
                active_readers=sum(e['pins'] for e in self.entries.values()),
                pending_cleanup=sum(e['retired'] for e in self.entries.values()))

    def close(self):
        with self.condition:
            self.closed=True
            for entry in self.entries.values():entry['retired']=True
            while any(entry['pins'] for entry in self.entries.values()):self.condition.wait(.05)
            self.collect()
            if self.entries:raise OSError('Temporary evidence cleanup is incomplete. Retry Jobs.close().')
            if self.root is not None and self.initialized:self.root.rmdir();self.root=None;self.initialized=False


class Readers:
    """Read lifetimes inside Jobs, independent of calculation-run retention.

    Acquisition preserves complete immutable evidence independently of its
    source record. Release ends new access; active request pins retain their
    bytes through closure. No financial inputs or calculation belong here.
    """
    def __init__(self,limit=16,requests=32):
        self.limit=limit;self.request_limit=requests;self.entries={};self.condition=Condition(RLock());self.closed=False
        self.released=[]

    def acquire(self,identifier,source,opener):
        if not isinstance(identifier,str) or not re.fullmatch('[0-9a-f]{32}',identifier):
            raise ValueError('Invalid evidence reader identity.')
        identity=json.dumps(source,sort_keys=True,allow_nan=False,separators=(',',':'))
        with self.condition:
            if self.closed:raise ValueError('The server is stopping.')
            if identifier in self.released:raise ValueError('This evidence reader was released.')
            entry=self.entries.get(identifier)
            if entry is not None:
                if entry['identity']!=identity:raise ValueError('This reader ID has a different source.')
                while entry['opening']:self.condition.wait()
                if entry.get('error'):raise ValueError('Evidence acquisition failed.') from entry['error']
                if entry['released']:raise ValueError('This evidence reader was released.')
                return deepcopy(entry['artifact'])
            if len(self.entries)>=self.limit:raise ValueError('Evidence reader capacity is exhausted. Close an earlier view or restart the service.')
            entry=dict(identity=identity,opening=True,released=False,pins=0,owner=None,cleaning=False)
            self.entries[identifier]=entry
        try:
            context=opener()
            opened=context.__enter__()
            with self.condition:entry.update(owner=context,opened=opened)
            metadata=deepcopy(opened.metadata)
            reader=opened.reader
            artifact=dict(metadata,evidence=dict(id=identifier,format_version=result_evidence.FORMAT_VERSION,
                trials=reader.manifest['trials'],periods=reader.manifest['periods'],
                holdings=reader.manifest['holdings'],sha256=reader.manifest['sha256']))
            with self.condition:
                entry.update(owner=context,opened=opened,artifact=artifact,opening=False)
                self.condition.notify_all()
                retired=entry['released'] or self.closed
            if retired:
                self.release(identifier)
                raise ValueError('This evidence reader was released.')
            return deepcopy(artifact)
        except BaseException as error:
            with self.condition:
                # A successful enter belongs to the entry until cleanup succeeds.
                entry.update(opening=False,error=error,released=True)
                self.condition.notify_all()
            self._collect(identifier,entry)
            raise

    def _collect(self,identifier,entry):
        with self.condition:
            if entry['opening'] or entry['pins'] or not entry['released'] or entry['cleaning']:return
            entry['cleaning']=True
        try:
            if entry['owner'] is not None:
                owner=entry['owner'];entry['owner']=None
                owner.__exit__(None,None,None)
            elif entry.get('opened') is not None:
                entry['opened'].close()
        except BaseException:
            with self.condition:entry['cleaning']=False;self.condition.notify_all()
            raise
        with self.condition:
            self.entries.pop(identifier,None)
            self.released.append(identifier);self.released=self.released[-128:]
            self.condition.notify_all()

    @contextmanager
    def pin(self,identifier):
        with self.condition:
            entry=self.entries.get(identifier)
            if self.closed or entry is None or entry['opening'] or entry['released']:
                raise ValueError('This evidence reader is no longer available.')
            if sum(e['pins'] for e in self.entries.values())>=self.request_limit:
                raise ValueError('Evidence request capacity is exhausted. Retry after an active read finishes.')
            entry['pins']+=1
        try:
            with entry['opened'].open_reader() as reader:
                yield deepcopy(entry['opened'].metadata),reader
        finally:
            with self.condition:entry['pins']-=1;self.condition.notify_all()
            self._collect(identifier,entry)

    def release(self,identifier):
        with self.condition:
            entry=self.entries.get(identifier)
            if entry is None:return
            entry['released']=True
        self._collect(identifier,entry)

    def close(self):
        with self.condition:
            self.closed=True
            for entry in self.entries.values():entry['released']=True
            while any(e['opening'] or e['pins'] or e['cleaning'] for e in self.entries.values()):
                self.condition.wait(.05)
        for identifier,entry in list(self.entries.items()):self._collect(identifier,entry)

    def measurements(self):
        with self.condition:
            return dict(limit=self.limit,readers=len(self.entries),
                requests=sum(e['pins'] for e in self.entries.values()),
                acquiring=sum(e['opening'] for e in self.entries.values()))
