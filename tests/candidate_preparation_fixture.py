"""Actual offline preparation runner, copied-source inputs only."""
from pathlib import Path
import json
import sys


def main():
    source,tests,output=map(Path,sys.argv[1:4])
    sys.path[:0]=[str(tests),str(tests.parent/'tools')]
    from bench_source_service_fixture import dependency_guard
    dependency_guard(source)
    sys.path[:0]=[str(source/'scripts'),str(source/'website')]
    import runtime_access
    with runtime_access.ownership(source):
        import run
        run.KEY_PATH=source.parent/'nonexistent-offline-key'
        from numerical_preparation import Preparation
        import baseline
        import research
        from unittest.mock import patch
        candidate=Preparation(source,python=sys.executable)
        initial=candidate.prepare()
        assert candidate.runtime is None and initial['closure']['state']=='closed'
        assert initial['closure']['process']['descendants_empty']
        assert candidate.status()['state']=='current'
        if len(sys.argv)>4:
            assert initial['generation']['identity']==sys.argv[4]
            assert initial['generation']['reused']
            output.write_text(json.dumps(dict(moved=True,generation=initial['generation'],closure=initial['closure'])))
            return
        pointer=source/'data/numerical'/initial['generation']['identity']
        inventory={p.name:(p.stat().st_mtime_ns,p.read_bytes()) for p in pointer.iterdir()}
        unchanged=candidate.prepare()
        assert unchanged['generation']['reused']
        assert inventory=={p.name:(p.stat().st_mtime_ns,p.read_bytes()) for p in pointer.iterdir()}
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
        from cache_assets import write_json
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
