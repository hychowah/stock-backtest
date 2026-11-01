"""Package boundaries, query-free validation and source closure contracts."""
from copy import deepcopy
import importlib
import inspect
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest import screening
from backtest.financial import metrics
from backtest.engines.numerical.random import _source_closure, source_identity


class PackageTests(unittest.TestCase):
    def test_validation_has_no_storage_or_mutation_and_preserves_precedence(self):
        submitted=dict(rank_from=2,rank_to=9,pool='cached',selection_order='rank_first',
                       filters=[dict(field='fcf',op='lt',value=-4)])
        original=deepcopy(submitted)
        with patch.object(sqlite3,'connect',side_effect=AssertionError('No database access')):
            screening.validate_selection(**submitted)
            for options,message in ((dict(rank_from=0,pool='bad'),'ranks'),
                                    (dict(pool='bad',metric='bad'),'Pool'),
                                    (dict(metric='bad',selection_order='bad'),'ranking'),
                                    (dict(filters=[{}],selection_order='bad'),'Each filter')):
                with self.subTest(options=options),self.assertRaisesRegex(ValueError,message):
                    screening.validate_selection(**options)
        self.assertEqual(submitted,original)
        self.assertNotIn('db',inspect.signature(screening.validate_selection).parameters)

    def test_preparation_catalog_rejects_before_first_database_operation(self):
        from backtest.inputs import research as research
        class NoDatabase:
            def execute(self,*args):raise AssertionError('Catalog validation must precede SQL')
        with patch.dict(metrics.METRICS,{'unsupported':dict(label='Unsupported')}):
            with self.assertRaisesRegex(ValueError,'Every catalog'):
                research.prepare_metrics(NoDatabase())

    def test_package_relative_closure_includes_initializers_without_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            files={'entry.py':'from localpkg import branch\n',
                   'localpkg/__init__.py':"raise RuntimeError('must never execute')\n",
                   'localpkg/branch.py':'from . import policy\nfrom .nested.leaf import VALUE\n',
                   'localpkg/policy.py':'VALUE=1\n',
                   'localpkg/nested/__init__.py':'from .. import policy\n',
                   'localpkg/nested/leaf.py':'from ..policy import VALUE\n'}
            for name,content in files.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)
            before=_source_closure(root,['entry.py'])
            self.assertEqual(set(before),set(files))
            path=root/'localpkg/policy.py';path.write_text('VALUE=2\n')
            after=_source_closure(root,['entry.py'])
            self.assertNotEqual(before,after)
            self.assertEqual([k for k in before if before[k]!=after[k]],['localpkg/policy.py'])

    def test_current_identity_keeps_new_and_conservative_source_coverage(self):
        sources=source_identity()
        self.assertTrue({'backtest/__init__.py','backtest/financial/__init__.py',
            'backtest/financial/rules.py','backtest/financial/books.py','backtest/financial/metrics.py',
            'backtest/screening.py','backtest/calendar.py','backtest/calendar_requests.py',
            'backtest/portfolio_results.py','backtest/inputs/research.py','backtest/engines/reference/legacy.py','backtest/engines/reference/revalue.py',
            'backtest/engines/numerical/policy.py','backtest/runtime/cache_access.py','website/runtime_access.py'}<=sources.keys())
        self.assertTrue(all('\\' not in name and not name.startswith('/') for name in sources))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'website').mkdir()
            owner=root/'website/runtime_access.py'
            owner.write_bytes((ROOT/'website/runtime_access.py').read_bytes())
            entry=root/'entry.py'
            entry.write_text('import importlib.util\n')
            before=_source_closure(root,['entry.py','website/runtime_access.py'])
            owner.write_bytes(owner.read_bytes()+b'\n# private ownership mutation\n')
            after=_source_closure(root,['entry.py','website/runtime_access.py'])
            self.assertEqual(set(before),set(after))
            self.assertEqual(before['entry.py'],after['entry.py'])
            self.assertNotEqual(before['website/runtime_access.py'],after['website/runtime_access.py'])

    def test_private_source_fixture_contains_nested_financial_package(self):
        from bench_source_service_fixture import FictionalWorkspace
        with FictionalWorkspace() as fixture:
            self.assertTrue({'backtest/financial/__init__.py','backtest/financial/rules.py',
                'backtest/financial/books.py','backtest/financial/metrics.py'}<=fixture.sources.keys())
            self.assertFalse(any('/local/' in name or '/dist/' in name for name in fixture.sources))

    def test_private_bootstrap_fixture_import_does_not_load_backtest(self):
        code="""
import sys
from pathlib import Path
root=Path(sys.argv[1])
sys.path[:0]=[str(root/'tests'),str(root/'tools')]
from bench_source_service_fixture import dependency_guard
assert not any(name=='backtest' or name.startswith('backtest.') for name in sys.modules)
"""
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_core_imports_do_not_load_command_or_optional_modules(self):
        code="""
import importlib,sys
sys.path.insert(0,sys.argv[1])
for name in ('backtest.financial.rules','backtest.financial.books','backtest.financial.metrics',
             'backtest.screening','backtest.calendar','backtest.calendar_requests','backtest.portfolio_results'):
    importlib.import_module(name)
assert not any(name.split('.')[0] in ('scripts','tools','website','numpy','numba') for name in sys.modules)
assert not any(name in sys.modules for name in ('run','research','schedules','numerical_policy'))
"""
        with tempfile.TemporaryDirectory() as folder:
            result=subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT)],cwd=folder,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_documented_entry_imports_and_cli_shapes_from_other_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            for script in ('research.py','schedules.py'):
                result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts'/script),'--help'],cwd=folder,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('usage:',result.stdout)
            code="""
import runpy,sys
from pathlib import Path
root=Path(sys.argv[1])
sys.path.insert(0,str(root/'scripts'))
for name in ('run','revalue','list_stops','classify_stops'):
    runpy.run_path(str(root/'scripts'/(name+'.py')),run_name='offline_import')
assert 'numpy' not in sys.modules and 'numba' not in sys.modules
"""
            result=subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT)],cwd=folder,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)


class ExecutableErrors(unittest.TestCase):
    def test_research_missing_private_database_is_clean_from_another_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            missing=Path(folder)/'PRIVATE-never-created.sqlite'
            result=subprocess.run([sys.executable,'-I','-B',str(ROOT/'scripts/research.py'),
                '--database',str(missing),'status'],cwd=folder,capture_output=True,text=True)
            self.assertEqual(result.returncode,1,result.stdout+result.stderr)
            self.assertNotIn('Traceback',result.stderr)
            self.assertIn('missing',result.stderr.lower())
            self.assertIn('scripts/research.py prepare',result.stderr)
            self.assertFalse(missing.exists())


if __name__=='__main__':unittest.main()
