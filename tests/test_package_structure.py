"""Package boundaries, query-free validation and the frozen-code boundary."""
from copy import deepcopy
import ast
import importlib.util
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

# Frozen experimental-engine source (AGENTS.md, Tests). Live tests never import it.
FROZEN_SOURCE=('backtest.engines.numerical','backtest.application.calculations',
               'backtest.application.candidate_calculations','backtest.application.preparation')


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

    def test_private_source_fixture_contains_nested_financial_package(self):
        from source_service_fixture import FictionalWorkspace
        with FictionalWorkspace() as fixture:
            self.assertTrue({'backtest/financial/__init__.py','backtest/financial/rules.py',
                'backtest/financial/books.py','backtest/financial/metrics.py'}<=fixture.sources.keys())
            self.assertFalse(any('/local/' in name or '/dist/' in name for name in fixture.sources))

    def test_private_bootstrap_fixture_import_does_not_load_backtest(self):
        code="""
import sys
from pathlib import Path
root=Path(sys.argv[1])
sys.path[:0]=[str(root/'tests'),str(root)]
from source_service_fixture import dependency_guard
import candidate_service_fixture
assert not any(name=='backtest' or name.startswith('backtest.') for name in sys.modules)
"""
        result=subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_live_tests_never_import_frozen_code(self):
        """A live test entry and every test module it reaches, at any import
        level, import no frozen source and no file that tests/run.py FROZEN names."""
        spec=importlib.util.spec_from_file_location('tier_table',ROOT/'tests'/'run.py')
        runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
        tests=ROOT/'tests'
        frozen_tests={name.removesuffix('.py') for name in runner.FROZEN}
        def frozen(module):
            return module in frozen_tests or any(module==name or module.startswith(name+'.') for name in FROZEN_SOURCE)
        def imports(name):
            """Yield each imported module with the names its statement binds."""
            for node in ast.walk(ast.parse((tests/(name+'.py')).read_text(encoding='utf-8'))):
                if isinstance(node,ast.Import):
                    for alias in node.names:yield alias.name,[]
                elif isinstance(node,ast.ImportFrom) and node.module and not node.level:
                    yield node.module,[node.module+'.'+alias.name for alias in node.names]
        problems=[]
        for path in sorted(tests.glob('test_*.py')):
            if path.name in runner.FROZEN|runner.NOT_ENTRIES:continue
            pending,seen=[[path.stem]],set()
            while pending:
                chain=pending.pop()
                if chain[-1] in seen:continue
                seen.add(chain[-1])
                for module,names in imports(chain[-1]):
                    found=[name for name in [module,*names] if frozen(name)]
                    if found:problems.append(' > '.join(chain+[found[0]]))
                    elif (tests/(module+'.py')).is_file():pending.append(chain+[module])
        self.assertEqual(problems,[])

    def test_server_and_original_imports_load_no_frozen_or_numerical_module(self):
        """The server entry and every module Original imports, including its
        lazy imports, load no frozen source and no numerical package."""
        code="""
import importlib,sys
sys.path.insert(0,sys.argv[1])
for name in ('website.server.app','backtest.application.original_calculations',
             'backtest.application.strategy_requests','backtest.application.scalar_execution',
             'backtest.application.scalar_runs','backtest.application.variable_coverage',
             'backtest.inputs.research','backtest.inputs.sqlite_observations','backtest.scalar_result_evidence'):
    importlib.import_module(name)
frozen=tuple(sys.argv[2:])
loaded=[name for name in sys.modules if name.split('.')[0] in ('numpy','numba','llvmlite')
        or any(name==item or name.startswith(item+'.') for item in frozen)]
assert not loaded,loaded
"""
        with tempfile.TemporaryDirectory() as folder:
            result=subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT),*FROZEN_SOURCE],
                                  cwd=folder,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_canonical_storage_has_no_original_engine_dependency(self):
        for path in (ROOT/'backtest/inputs').glob('*.py'):
            tree=ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom):
                    self.assertFalse((node.module or '').startswith(('scripts','tools','website','backtest.engines.original')),path)
        for path in (ROOT/'backtest').rglob('__init__.py'):
            self.assertTrue(all(isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) for n in ast.parse(path.read_text(encoding="utf-8")).body),path)

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
