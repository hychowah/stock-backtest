"""Private explicit evidence jobs for the fictional native browser pilot.

Ordinary submission stays eager. This helper runs only in the test service's
explicit evidence scenario, after real candidate preparation and before HTTP.
"""

# Resolve the importable package for direct-file commands and spawned fixtures.
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[1]))
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
from threading import local


def seed(server,source):
    from backtest.application import temporary_evidence as job_evidence
    from backtest.application import durable_evidence as durable_evidence
    from website.server import app as serve_app
    from backtest.financial import metrics as metrics
    from backtest.application import library as saved_backtests
    from backtest.engines.numerical.portfolio import compare_results
    from backtest.runtime.process_owner import process_metrics
    from backtest.application import result_exports as result_exports
    server.backtest_jobs.evidence=job_evidence.Workspace(source/'tmp'/'browser-evidence-jobs',max_bytes=128*1024**2)
    budget=durable_evidence.Budget(96*1024**2)
    library=saved_backtests.Store(evidence_budget=budget)
    serve_app.SAVED_BACKTESTS.evidence_budget=budget
    server.backtest_queue.store.evidence_budget=budget
    settings=dict(start='2015-01-02',end='2015-05-01',months=1,
                  pool='cached',metric='ev_ebitda',rank_from=1,rank_to=5)
    catalog=dict(metrics=deepcopy(metrics.METRICS),filters=deepcopy(metrics.FILTERS))
    catalog['metrics']['ev_ebitda']['label']='Original fictional EV / EBITDA'
    presentation=dict(periodLabel='Original fictional period',coverage='Original cached coverage',notice=dict(text='',severity='info'))
    records=[]
    for index,kind in enumerate(('random','custom')):
        options=dict(settings,**(dict(trials=4,seed=42) if kind=='random' else {}))
        identifier=('a' if kind=='random' else 'b')*32
        # Bounded evidence for ordinary settings is numerical. The router passes
        # options without the engine key, so recorded settings stay engine-free.
        # Evidence summaries carry no producer; compare the same eager fields.
        pinned=dict(options,engine='experimental')
        eager=server.calculations.calculate(kind,pinned,None,None);eager.pop('producer')
        began=time.perf_counter()
        server.backtest_jobs.start_evidence(identifier,kind,pinned,max_bytes=16*1024**2,record_bytes=1024**2)
        server.backtest_jobs.runs[identifier]['thread'].join(120)
        status=server.backtest_jobs.snapshot(identifier)
        assert status['state']=='complete',status
        production_seconds=time.perf_counter()-began
        maximum_absolute=maximum_relative=0.
        metadata=dict(version=3,kind=kind,settings=dict(mode=kind,**options),catalog=catalog,
                      presentation=presentation,captured_at='2026-10-30T00:00:0'+str(index)+'Z',
                      result=status['evidence']['manifest']['summary'])
        with server.backtest_jobs.open_evidence(identifier) as reader:
            expected=eager['trial_results'] if kind=='random' else [eager]
            for original,view in zip(expected,reader.trials(),strict=True):
                observed=dict(view.summary,periods=list(view.periods()))
                agreement=compare_results(original,observed);assert agreement['exact'],agreement
                maximum_absolute=max(maximum_absolute,agreement['maximum_absolute'])
                maximum_relative=max(maximum_relative,agreement['maximum_relative'])
            saved=library.save_evidence(kind+' original',metadata,reader)
            if kind=='random':
                queue=server.backtest_queue.store
                request=dict(id='c'*32,name='Queued original evidence',mode=kind,options=options,catalog=catalog,presentation=presentation)
                queue.enqueue(request);queue.claim();queue.progress(request['id'],'configuration',reader.metadata['configuration'])
                queue.finish_evidence(request['id'],metadata,reader)
            golden={}
            for number in range(1,reader.manifest['trials']+1):
                for export in ('holdings','returns'):
                    data=b''.join(result_exports.csv(reader,export,number))
                    golden[export+str(number)]=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),filename=result_exports.filename(reader,export,number))
            if kind=='random':
                data=b''.join(result_exports.csv(reader,'random'))
                golden['random']=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),filename=result_exports.filename(reader,'random'))
        # Eager originals supply actual browser CSV goldens, independent of the exporter.
        legacy=dict(metadata,version=2,result=eager)
        eager_record=library.save(kind+' eager original',legacy)
        records.append(dict(kind=kind,id=identifier,options=options,saved=saved,eager=eager_record,
                            metadata=metadata,golden=golden,production_seconds=production_seconds,
                            production_copy_and_goldens_seconds=time.perf_counter()-began,
                            maximum_absolute=maximum_absolute,maximum_relative=maximum_relative,evidence=status['evidence'],memory=process_metrics()))
    Path(source/'data/evidence-fixture.json').write_text(json.dumps(records,allow_nan=False),encoding='utf-8')
    # Test-only transport pause after headers and the first bounded piece.
    # The counting pass is unchanged. Exact bytes and Content-Length are kept.
    original_chunks=result_exports.Prepared.chunks;state=local()
    def controlled_chunks(export):
        state.calls=getattr(state,'calls',0)+1
        controlled=(source/'data/evidence-export-pause').exists() and state.calls%2==0
        first=True
        for chunk in original_chunks(export):
            if not controlled:yield chunk;continue
            for offset in range(0,len(chunk),128):
                if not first:
                    deadline=time.monotonic()+15
                    while (source/'data/evidence-export-pause').exists():
                        if time.monotonic()>deadline:raise TimeoutError('Fictional export pause expired')
                        time.sleep(.01)
                first=False;yield chunk[offset:offset+128]
    result_exports.Prepared.chunks=controlled_chunks


def forbid_read_dependencies(context,serve_app):
    """Assert real ordinary HTTP reads do not use readiness or financial access."""
    from unittest.mock import patch
    state=local();access=serve_app.cache_access.access;ready=serve_app.backtests.require_calculation
    def guarded_access(*args,**kwargs):
        if getattr(state,'reading',False):raise AssertionError('Stored read requested financial access')
        return access(*args,**kwargs)
    def guarded_ready(handler,*args,**kwargs):
        if getattr(state,'reading',False):raise AssertionError('Stored read requested readiness')
        return ready(handler,*args,**kwargs)
    context.enter_context(patch.object(serve_app.cache_access,'access',guarded_access))
    context.enter_context(patch.object(serve_app.backtests,'require_calculation',guarded_ready))
    for name in ('evidence_request','saved_backtest_request'):
        call=getattr(serve_app.results,name)
        def guarded(handler,*args,_call=call,**kwargs):
            state.reading=True
            try:return _call(handler,*args,**kwargs)
            finally:state.reading=False
        context.enter_context(patch.object(serve_app.results,name,guarded))
