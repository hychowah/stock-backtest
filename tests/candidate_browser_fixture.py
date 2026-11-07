"""Owned, fictional candidate service for actual browser qualification."""
import re
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'tools'),str(ROOT/'tests')]
from source_service_fixture import FictionalWorkspace
from process_owner import OwnedProcess, ProcessLimits


class CandidateService:
    def __init__(self,workspace,scenario):
        self.fixture=workspace;self.scenario=scenario
        self.closed=False;self.ready=False;self.port=None;self.owner=None;workspace.own(self)

    def start(self):
        self.owner=OwnedProcess([sys.executable,'-I','-B',str(ROOT/'tests/candidate_service_fixture.py'),
            str(self.fixture.source),str(ROOT/'tests'),self.scenario],
            limits=ProcessLimits(2*1024**3,16,25,close_seconds=15.,user_cpu_seconds=360.))
        logs=[];deadline=time.monotonic()+180
        try:
            while time.monotonic()<deadline:
                event=self.owner.event(.05)
                if event is None:break
                logs.append(event)
                text=event.get('text','')
                match=re.search(r'Open http://127\.0\.0\.1:(\d+)',text)
                if match:
                    self.port=int(match[1]);self.ready=True;return self
            raise AssertionError(logs)
        except BaseException:self.close();raise

    def close(self):
        if self.closed:return
        if self.owner is not None:
            if self.owner.process.poll() is None:
                self.owner.process.stdin.write('close\n');self.owner.process.stdin.flush()
            deadline=time.monotonic()+30
            while self.owner.process.poll() is None and time.monotonic()<deadline:
                self.owner.event(.05)
            self.owner.close()
            assert self.owner.closed and self.owner.descendants_empty and self.owner.eof
            assert self.owner.process.returncode==0,self.owner.closure()
        self.closed=True
