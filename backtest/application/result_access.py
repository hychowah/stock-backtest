"""Original-result acquisition and request pins, separate from calculation jobs.

Release fences crossing acquisition requests. Existing request pins retain their
own reader position and original bytes until their operation closes.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
import re
from threading import Condition, RLock
from backtest import result_evidence


class ResultAccess:
    """Acquired immutable results, independent of calculation-run retention.

    Acquisition preserves complete immutable evidence independently of its
    source record. Release ends new access; active request pins retain their
    bytes through closure. No financial inputs or calculation belong here.
    """
    def __init__(self,jobs,library,queue_store,*,limit=16,requests=32):
        self.jobs=jobs;self.library=library;self.queue_store=queue_store
        self.limit=limit;self.request_limit=requests;self.entries={};self.condition=Condition(RLock());self.closed=False
        self.released=[]

    def acquire(self,identifier,request):
        """Acquire original evidence. Capture the entire request as retry identity.

        Validation never opens a source or consults calculation readiness.
        Durable display metadata belongs to the saved record, never the caller.
        """
        if not isinstance(request,dict):raise ValueError('Expected an evidence request.')
        source=request.get('source')
        if not isinstance(source,dict):raise ValueError('Expected an evidence source.')
        kind=source.get('kind');record_id=source.get('id')
        if kind not in ('run','saved','queue'):raise ValueError('Unknown evidence source.')
        if not isinstance(record_id,str) or not re.fullmatch('[0-9a-f]{32}',record_id):
            raise ValueError('Invalid evidence source identity.')
        if not isinstance(request.get('display',{}),dict):raise ValueError('Expected evidence display context.')
        captured=deepcopy(request)
        if kind=='run':opener=lambda:self.jobs.display_evidence(record_id,captured.get('display',{}))
        elif kind=='saved':opener=lambda:self.library.open_evidence(record_id)
        else:opener=lambda:self.queue_store.open_evidence(record_id)
        return self._acquire(identifier,captured,opener)

    def save_reader(self,name,identifier):
        with self.read(identifier) as (metadata,reader):
            return self.library.save_evidence(name,metadata,reader)

    def _acquire(self,identifier,source,opener):
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
            entry=dict(identity=identity,opening=True,released=False,pins=0,owner=None,cleaning=False,exit_attempted=False)
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
                # Keep both owners strongly referenced until cleanup succeeds.
                # Generator contexts cannot rerun a failing finally block; the
                # detached source's close operation remains explicitly retryable.
                if not entry['exit_attempted']:
                    entry['exit_attempted']=True
                    entry['owner'].__exit__(None,None,None)
                else:entry['opened'].close()
            elif entry.get('opened') is not None:entry['opened'].close()
        except BaseException:
            with self.condition:entry['cleaning']=False;self.condition.notify_all()
            raise
        with self.condition:
            self.entries.pop(identifier,None)
            self.released.append(identifier);self.released=self.released[-128:]
            self.condition.notify_all()

    @contextmanager
    def read(self,identifier):
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
            if not isinstance(identifier,str) or not re.fullmatch('[0-9a-f]{32}',identifier):
                raise ValueError('Invalid evidence reader identity.')
            entry=self.entries.get(identifier)
            if identifier not in self.released:
                self.released.append(identifier);self.released=self.released[-128:]
            if entry is None:return
            entry['released']=True
        self._collect(identifier,entry)

    @property
    def closing(self):return self.closed

    def close_admission(self):
        with self.condition:
            self.closed=True
            self.condition.notify_all()

    def close(self):
        self.close_admission()
        with self.condition:
            for entry in self.entries.values():entry['released']=True
            while any(e['opening'] or e['pins'] or e['cleaning'] for e in self.entries.values()):
                self.condition.wait(.05)
        for identifier,entry in list(self.entries.items()):self._collect(identifier,entry)

    def measurements(self):
        with self.condition:
            return dict(limit=self.limit,readers=len(self.entries),
                requests=sum(e['pins'] for e in self.entries.values()),
                acquiring=sum(e['opening'] for e in self.entries.values()))
