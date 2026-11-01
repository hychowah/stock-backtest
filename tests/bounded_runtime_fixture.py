"""Fictional provider for the bounded runtime pilot; source Session is unchanged.

This fixture defines prices/books, not financial reduction or evidence encoding.
It opens no market data. Runtime ownership still belongs to the real bootstrap.
"""
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.runtime import backtest_control as backtest_control
from backtest.engines.numerical import random as numerical_random
from backtest.engines.numerical import session as numerical_session
from backtest.engines.numerical.portfolio import NumericalPortfolio
from backtest.engines.original import schedules as schedules
from backtest.engines.numerical import checkpoints as trial_checkpoints
from backtest.runtime.process_owner import process_metrics


def input_record(long=False):
    companies=[('FICTION'+str(n).zfill(3),'Fictional 測試 '+str(n) if n%2 else None,'NYSE',None) for n in range(1,51)]
    first,days=(date(1997,1,1),10592) if long else (date(2010,1,4),113)
    sessions={str(first+timedelta(days=n)):100.+n/100 for n in range(days)
              if (first+timedelta(days=n)).weekday()<5}
    return dict(companies=[list(c) for c in companies],sessions=sessions,
        formula='return=((rank%11)-5)/1000+duration_days/1000000; yield=.3+rank/10000; spy=duration_days/10000')


class Inputs:
    def __init__(self,long=False):
        record=input_record(long);self.s=schedules;self.sessions=record['sessions'];self.companies=record['companies']
        self.symbols=[c[0] for c in self.companies];self.closed=False;self.bankrupt=set()
        self.signature=hashlib.sha256(trial_checkpoints.canonical(record).encode()).hexdigest()
        self.policy=SimpleNamespace(signature='fictional-policy-1',field_schema='fictional-schema-1',fields={'fictional':True})
    def validate(self):
        if self.closed:raise ValueError('Fictional inputs closed.')
    def close(self):self.closed=True


class Provider:
    def __init__(self,inputs):
        self.inputs=inputs;self.limits={'max_candidate_rows':50};self.stats={'threads':1,'books':0};self.closed=False
        self.digest=hashlib.sha256()
    def begin(self,request):pass
    def evaluate(self,requests):
        result=[]
        for entry,exit_day,pool in requests:
            delta=(date.fromisoformat(exit_day)-date.fromisoformat(entry)).days;rows=[];metrics=[]
            for rank,symbol in enumerate(self.inputs.symbols,1):
                score=.3+rank/10000;ret=((rank%11)-5)/1000+delta/1000000
                rows.append((symbol,rank if rank%2 else None,'2009-06-30',entry,exit_day,150e6,180e6,60e6,
                             1/3,3.,.3,ret,'Marked to date'))
                metrics.append((symbol,'ev_ebitda',1/score,score))
            book=dict(entry=entry,exit=exit_day,pool=pool,period=(entry,exit_day,delta/10000,.01,50,50),
                      snapshots=rows,metrics=metrics,filters=[])
            self.digest.update(json.dumps(book,sort_keys=True,separators=(',',':'),allow_nan=False).encode());self.stats['books']+=1;result.append(book)
        return result
    def close(self):self.closed=True;self.inputs=None


class Session(numerical_session.Session):
    def __init__(self,configuration):
        self.configuration=configuration;self.loaded_source=numerical_random.source_identity();self.closed=False
        self.inputs=Inputs(configuration.get('long_plan',False));self.provider=Provider(self.inputs)
        self.portfolio=NumericalPortfolio(self.inputs,self.provider,result_workspace_bytes=64*1024**2)
        self.checkpoints=trial_checkpoints.Store(configuration['checkpoint_path'],max_payload_bytes=16*1024**2)
        self.results={};self.stats={'result_retained_bytes':0}
        self.marker=Path(configuration['scratch'])/'fixture-state.json'
    def validate(self):
        backtest_control.checkpoint()
        if self.closed:raise ValueError('Session closed.')
        if numerical_random.source_identity()!=self.loaded_source:raise ValueError('Loaded calculation source changed.')
        self.inputs.validate()
    def measurements(self):
        return dict(**process_metrics(),provider=self.provider.stats,checkpoints=self.checkpoints.measurements(),
                    generation=self.inputs.signature,book_sha256=self.provider.digest.hexdigest())
    def close(self):
        books=self.provider.stats['books'] if self.provider is not None else None
        super().close()
        self.marker.write_text(json.dumps(dict(closed=self.closed,books=books,borrowers_closed=self.portfolio is None,
            provider_closed=self.provider is None,inputs_closed=self.inputs is None,checkpoints_closed=self.checkpoints is None)))
