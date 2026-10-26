"""Ordinary fictional preparation followed by offline export. No live assets."""
import json
from pathlib import Path
import subprocess
import shutil
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tests'), str(ROOT/'tools')]
from bench_source_service_fixture import FictionalWorkspace, sha, SPEC


CHILD = r'''
import json,sys,time,tracemalloc,os
from pathlib import Path
from contextlib import closing
source=Path(sys.argv[1]); tests=Path(sys.argv[2]); result=Path(sys.argv[3])
sys.path[:0]=[str(tests),str(tests.parent/'tools')]
from bench_source_service_fixture import dependency_guard
dependency_guard(source)
sys.path[:0]=[str(source/'scripts'),str(source/'website')]
import runtime_access
with runtime_access.ownership(source):
    import run
    run.KEY_PATH=source.parent/'nonexistent-key'
    import schedules as s
    s.prepare()
    import numerical_generation as ng
    import numpy as np
    store=ng.GenerationStore(s)
    report=ng._sha(source/'results/summary-exits.txt')
    tracemalloc.start()
    published=store.prepare()
    _,python_peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    with store.open_current() as inputs:
        inputs.validate()
        from bench_candidates import NumericInputs
        with closing(s.connect()) as db:
            old=NumericInputs(db,s)
            try:
                for name in ng.ARRAYS:
                    if name=='symbol_sort':
                        assert [inputs.symbols[int(i)] for i in inputs.symbol_sort]==sorted(old.symbols)
                    elif name.startswith(('cached_','legacy_')) and name!='cached_mask':
                        pool,field=name.split('_',1)
                        np.testing.assert_array_equal(getattr(inputs,'pool_'+field)[pool],getattr(old,'pool_'+field)[pool])
                    else:np.testing.assert_array_equal(getattr(inputs,name),getattr(old,name))
                assert inputs.symbols==old.symbols
                assert list(inputs.report_rows)==list(old.report_rows)
                assert dict(inputs.histories)==old.histories
                assert dict(inputs.financials)==old.financials
                assert inputs.sessions==old.sessions and inputs.companies==old.companies
            finally:old.close()
        stats=dict(inputs.stats)
    assert store.prepare()['reused']
    assert ng._sha(source/'results/summary-exits.txt')==report
    price=source/'raw/px/ZZ000.json'; saved=price.read_bytes(); previous=price.stat()
    try:
        price.write_bytes(saved+b' ')
        try:store.open_current()
        except ValueError:pass
        else:raise AssertionError('Direct edit did not reject stale inputs')
    finally:
        price.write_bytes(saved)
        os.utime(price,ns=(previous.st_atime_ns,previous.st_mtime_ns))
    assert not ng._attachments
    result.write_text(json.dumps(dict(published=published,attachment=stats,
        traced_export_python_peak=python_peak,financial_agreement='exact',
        maximum_absolute=0.,maximum_relative=0.,report_unchanged=True,
        direct_edit_rejected=True,closed=True),sort_keys=True))
'''

MOVED_CHILD = r'''
import sys,json
from pathlib import Path
source=Path(sys.argv[1]);tests=Path(sys.argv[2])
sys.path[:0]=[str(tests),str(tests.parent/'tools')]
from bench_source_service_fixture import dependency_guard
dependency_guard(source)
sys.path[:0]=[str(source/'scripts'),str(source/'website')]
import runtime_access
with runtime_access.ownership(source):
    import run
    run.KEY_PATH=source.parent/'nonexistent-key'
    import schedules,numerical_generation as ng
    with ng.GenerationStore(schedules).open_current() as inputs:
        inputs.validate()
        assert inputs.signature==sys.argv[3]
        assert len(inputs.symbols)==64
    assert not ng._attachments
print('Moved project attachment passed',flush=True)
'''


class PreparationTests(unittest.TestCase):
    def test_ordinary_preparation_export_attach_and_freshness(self):
        with FictionalWorkspace() as workspace:
            result=workspace.root/'numerical-result.json'
            output=workspace.root/'numerical.log'
            with output.open('wb') as stream:
                process=subprocess.run([sys.executable,'-I','-B','-c',CHILD,str(workspace.source),
                    str(ROOT/'tests'),str(result)],stdout=stream,stderr=subprocess.STDOUT,timeout=120)
            if process.returncode:
                self.fail(output.read_text(encoding='utf-8',errors='replace'))
            evidence=json.loads(result.read_bytes())
            moved=workspace.root/'relocated-application'
            shutil.move(workspace.source,moved); workspace.source=moved
            with output.open('ab') as stream:
                process=subprocess.run([sys.executable,'-I','-B','-c',MOVED_CHILD,str(workspace.source),
                    str(ROOT/'tests'),evidence['published']['identity']],stdout=stream,
                    stderr=subprocess.STDOUT,timeout=30)
            if process.returncode:self.fail(output.read_text(encoding='utf-8',errors='replace'))
            evidence['moved_project_attached']=True
            self.assertEqual(workspace.inputs,workspace.input_inventory())
            self.assertEqual(workspace.sources,{name:sha(workspace.source/name) for name in workspace.sources})
            self.assertTrue(evidence['closed'])
            print(json.dumps(dict(check='numerical-preparation',platform=sys.platform,
                specification=SPEC,**evidence)),flush=True)


if __name__ == '__main__':unittest.main()
