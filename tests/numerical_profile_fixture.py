"""Selected compiled preparation on a fictional root."""
import json
import os
from pathlib import Path
import sys


def main():
    source,output=map(Path,sys.argv[1:3]);sys.path[:0]=[str(source),str(source/'website'),str(source/'scripts')]
    from website import runtime_access
    with runtime_access.ownership(source):
        from backtest.financial import rules
        from backtest.inputs import market, fmp_download, cache_assets
        from backtest.engines.reference import legacy
        fmp_download.KEY_PATH=source/'nonexistent-profile-key'
        from backtest.application import preparation as preparation
        from backtest.engines.numerical.runtime import NumericalRuntime
        from backtest.runtime import cache_access as cache_access
        options=dict(start='2015-01-02',end='2016-12-30',months=12,pool='cached',rank_to=5)
        profiles={};checks=[]
        compiled=preparation.Preparation(source,profile='numba_compiled')
        profiles['numba_compiled']=compiled.prepare()
        assert compiled.status()['state']=='current'
        assert profiles['numba_compiled']['dependencies']['rust_required'] is False
        assert 'native' not in profiles['numba_compiled']['dependencies']
        assert profiles['numba_compiled']['runtime']['provider']['backend']=='numba'
        assert not (source/'data/numerical-native').exists()
        for profile,value in (('numba_compiled',compiled),):
            assert value.status()['state']=='current'
            # Historical native-profile metadata cannot establish readiness.
            saved=value.path.read_bytes();wrong_report=json.loads(saved);wrong_report['profile']='rust'
            value.path.write_text(json.dumps(wrong_report))
            try:assert value.status()['state']!='current'
            finally:value.path.write_bytes(saved)
            for kind,path in (('input',source/'raw/px/ZZ000.json'),('source',source/'backtest/financial/metrics.py'),
                              ('pending',source/'data/research.sqlite.publication.json')):
                existed=path.exists();saved=path.read_bytes() if existed else None;stamp=path.stat() if existed else None
                child=value._runtime();child.configuration['preparation_status']=True
                try:
                    child.start()
                    path.write_bytes(saved+b' ' if existed else b'{}')
                    assert value.status()['state']!='current',(profile,kind)
                    try:child.calculate('custom',options)
                    except ValueError:pass
                    else:raise AssertionError('Child accepted stale '+kind+' under '+profile)
                finally:
                    child.close()
                    if existed:
                        path.write_bytes(saved)
                        os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
                    else:path.unlink(missing_ok=True)
                assert child.closure()['state']=='closed'
                checks.append(dict(profile=profile,change=kind,parent_rejected=True,child_rejected=True,closed=True))
            assert value.status()['state']=='current'
        assert compiled.status()['state']=='current'
        result=compiled._runtime();result.configuration['preparation_status']=True
        try:
            actual=result.calculate('custom',options)
            assert actual['periods']
            assert result.last_stats['provider_constructions']==1
            assert result.last_stats['factor_kernel_compilation_requests']==1
        finally:result.close()
        wrong=compiled._runtime();wrong.configuration['preparation_profile']='rust'
        try:
            try:wrong.start()
            except ValueError:pass
            else:raise AssertionError('Child accepted an execution/profile mismatch')
        finally:wrong.close()
        from backtest.engines.numerical import random as numerical_random
        source_identity=numerical_random.source_identity()
        assert not any('rust' in name or 'toolchain' in name for name in source_identity)
        output.write_text(json.dumps(dict(profiles={key:dict(profile=row['profile'],generation=row['generation'],
            dependencies=row['dependencies'],provider=row['runtime']['provider']['backend'],closure=row['closure'])
            for key,row in profiles.items()},checks=checks,no_managed_installation=True,
            historical_profile_rejected=True,source_without_rust_dependency=True,numba_zero_rust=True,
            positive_provider_constructions=1,positive_factor_compilations=1,
            child_profile_mismatch_rejected=True)))

if __name__=='__main__':main()
