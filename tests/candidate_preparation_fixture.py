"""Actual offline preparation runner, copied-source inputs only."""
from pathlib import Path
import json
import sys


def main():
    source,tests,output=map(Path,sys.argv[1:4])
    sys.path[:0]=[str(tests),str(tests.parent/'tools')]
    from bench_source_service_fixture import dependency_guard
    dependency_guard(source)
    sys.path[:0]=[str(source),str(source/'scripts'),str(source/'website')]
    import runtime_access
    with runtime_access.ownership(source):
        from backtest.financial import rules
        from backtest.inputs import market, fmp_download, cache_assets
        from backtest.engines.reference import legacy
        fmp_download.KEY_PATH=source.parent/'nonexistent-offline-key'
        from backtest.application.preparation import Preparation
        from backtest.inputs import baseline as baseline
        from backtest.inputs import research as research
        from backtest.inputs import daily
        from unittest.mock import patch
        import os
        ambient_builds=source/'tmp/ignored-ambient-builds'
        os.environ['BACKTEST_RUST_BUILDS']=str(ambient_builds)
        from build_state import ensure_presentation
        candidate=Preparation(source,python=sys.executable,ensure_presentation=ensure_presentation)
        initial=candidate.prepare()
        assert not ambient_builds.exists(),'Ambient benchmark build path redirected ordinary preparation'
        assert not (source/'data/numerical-native').exists(),'Normal selected preparation created unused Rust state'
        assert initial['runtime']['provider']['candidate_assembly']=='compiled'
        assert initial['runtime']['provider']['nopython_signatures']['materialize']
        assert candidate.runtime is None and initial['closure']['state']=='closed'
        assert initial['closure']['process']['descendants_empty']
        assert candidate.status()['state']=='current'
        if len(sys.argv)>4:
            assert initial['generation']['identity']==sys.argv[4]
            assert initial['generation']['reused']
            output.write_text(json.dumps(dict(moved=True,generation=initial['generation'],closure=initial['closure'])))
            return
        # Actual application dispatch and equivalent child-owned freshness.
        from candidate_calculations import Candidate
        from backtest.runtime import cache_access as cache_access
        owner=Candidate(candidate)
        options=dict(start='2015-01-02',end='2016-12-30',months=12,pool='cached',rank_to=5)
        result=owner.calculate('custom',options,None,None)
        assert owner.runtime is None
        assert owner.status()['state']=='current'
        from backtest.engines.numerical.portfolio import compare_results
        assert compare_results(owner.calculate('custom',options,None,None),result)['exact']
        assert owner.runtime is None
        checks=[source/'requirements-numerical.txt',source/'website/serve_app.py',
                source/'results/summary-exits.txt',source/'raw/px/ZZ000.json',
                source/'data/numerical/current.json']
        for path in checks:
            saved=path.read_bytes();stamp=path.stat()
            if path.name=='current.json':
                path.write_text(json.dumps(dict(json.loads(saved),fixture_change=True)))
            else:path.write_bytes(saved+b' ')
            assert owner.status()['state']!='current',path
            path.write_bytes(saved)
            import os
            os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            assert owner.status()['state']=='current',path
        prices=source/'raw/px';directory_stamp=prices.stat()
        extra=prices/'UNUSED.json';extra.write_text('{}')
        assert owner.status()['state']=='stale'
        extra.unlink()
        import os
        os.utime(prices,ns=(directory_stamp.st_atime_ns,directory_stamp.st_mtime_ns))
        removed=prices/'ZZ001.json';saved=removed.read_bytes();stamp=removed.stat();removed.unlink()
        assert owner.status()['state']=='stale'
        removed.write_bytes(saved);os.utime(removed,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        os.utime(prices,ns=(directory_stamp.st_atime_ns,directory_stamp.st_mtime_ns))
        assert owner.status()['state']=='current'
        for name in ('deployment.pending.json','research.sqlite.publication.json','numerical/publication.json'):
            journal=source/'data'/name;journal.write_text('{}')
            assert owner.status()['state']=='stale'
            journal.unlink()
        # Stale request rejection occurs before a cached numerical result.
        journal=source/'data/numerical/publication.json';journal.write_text('{}')
        import backtest_jobs
        try:owner.calculate('custom',options,None,None)
        except backtest_jobs.Unavailable:pass
        else:raise AssertionError('Stale result reuse admitted')
        assert owner.runtime is None
        journal.unlink()
        owner.calculate('custom',options,None,None)
        with owner.parent_operation():
            assert owner.runtime is None
            with cache_access.access(timeout=0):pass
        owner.close();owner.retire()
        pointer=source/'data/numerical'/initial['generation']['identity']
        inventory={p.name:(p.stat().st_mtime_ns,p.read_bytes()) for p in pointer.iterdir()}
        unchanged=candidate.prepare()
        assert unchanged['generation']['reused']
        assert inventory=={p.name:(p.stat().st_mtime_ns,p.read_bytes()) for p in pointer.iterdir()}
        # In-place raw edits leave directory metadata and report cutoff intact.
        # Research must invalidate daily prices before a new numeric export.
        from contextlib import closing
        from backtest.engines.original import schedules as schedules
        from backtest.engines.numerical.generation import GenerationStore
        import os
        prices=source/'raw/px';directory_stamp=prices.stat()
        price=prices/'ZZ000.json';payload=json.loads(price.read_bytes())
        for row in payload['div']:
            if row['date']>='2015-02-01':row['adjClose']*=1.2
        price.write_text(json.dumps(payload),encoding='utf-8')
        os.utime(prices,ns=(directory_stamp.st_atime_ns,directory_stamp.st_mtime_ns))
        cutoff=baseline.cutoff((source/'results/summary-exits.txt').read_text())
        with cache_access.access():
            research.prepare()
            assert baseline.cutoff((source/'results/summary-exits.txt').read_text())==cutoff
            try:GenerationStore().prepare()
            except ValueError as error:assert 'Daily cache changed' in str(error)
            else:raise AssertionError('Stale daily prices were exported as a new generation')
        price_changed=candidate.prepare()
        assert price_changed['generation']['identity']!=initial['generation']['identity']
        owner=Candidate(candidate)
        updated_result=owner.calculate('custom',options,None,None)
        assert updated_result['cagr']!=result['cagr']
        owner.close();owner.retire()
        daily_path=source/'data/schedules.sqlite';daily_content=daily_path.read_bytes()
        with cache_access.access(),patch.object(research,'price_sources',side_effect=AssertionError('Daily connect scanned raw inventory')):
            with closing(daily.connect()) as db:
                actual=db.execute("SELECT adjusted FROM prices WHERE symbol='ZZ000' AND day='2015-02-02'").fetchone()[0]
                assert actual==next(row['adjClose'] for row in payload['div'] if row['date']=='2015-02-02')
        with patch.object(research,'bars',side_effect=AssertionError('Unchanged restart reparsed raw prices')):
            assert candidate.prepare()['generation']['reused']
        assert daily_path.read_bytes()==daily_content
        print(json.dumps(dict(check='in-place-price-preparation',original_cagr=result['cagr'],
            updated_cagr=updated_result['cagr'],generation=price_changed['generation']['identity'],
            daily_adjusted=actual,unchanged_daily_bytes=True)),flush=True)
        import os
        prices=source/'raw/px';original_directory=prices.stat()
        extra=prices/'UNUSED.json';extra.write_text('{}')
        assert candidate.status()['state']=='stale'
        extra.unlink();os.utime(prices,ns=(original_directory.st_atime_ns,original_directory.st_mtime_ns))
        assert candidate.status()['state']=='current'
        removed=prices/'ZZ001.json';saved=removed.read_bytes();stamp=removed.stat();removed.unlink()
        assert candidate.status()['state']=='stale'
        removed.write_bytes(saved);os.utime(removed,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        os.utime(prices,ns=(original_directory.st_atime_ns,original_directory.st_mtime_ns))
        assert candidate.status()['state']=='current'
        price=source/'raw/px/ZZ000.json';price.write_bytes(price.read_bytes()+b' ')
        assert candidate.status()['state']=='stale'
        original=baseline._replace
        def interrupted(left,right):
            if right==research.DATABASE:raise OSError('fictional interrupted publication')
            return original(left,right)
        with patch.object(baseline,'_replace',side_effect=interrupted):
            try:research.prepare(force=True)
            except ValueError:pass
            else:raise AssertionError('Publication interruption was not reached')
        assert (source/'data/research.sqlite.publication.json').exists()
        changed=candidate.prepare()
        assert not (source/'data/research.sqlite.publication.json').exists()
        assert changed['generation']['identity']!=initial['generation']['identity']
        assert not changed['generation']['reused']
        # A pending numerical pointer is recovered before the verified restart.
        from backtest.inputs.cache_assets import write_json
        current=source/'data/numerical/current.json'
        write_json(source/'data/numerical/publication.json',dict(
            candidate=changed['generation']['identity'],prior=json.loads(current.read_bytes())))
        assert candidate.status()['state']=='stale'
        recovered=candidate.prepare()
        assert recovered['generation']['reused'] and candidate.status()['state']=='current'
        candidate.close()
        output.write_text(json.dumps(dict(initial=initial['generation'],unchanged=unchanged['generation'],
            changed=changed['generation'],recovered=recovered['generation'],closure=recovered['closure'],
            offline=True,publication_recovered=True)))


if __name__=='__main__':main()
