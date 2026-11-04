"""Optional dependency failures explain setup in the terminal and safe log."""
from contextlib import ExitStack, redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT)]
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.runtime import diagnostics as diagnostics
from backtest.application import preparation as preparation
class DependencyDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        folder = self.context.enter_context(tempfile.TemporaryDirectory())
        self.path = diagnostics.configure(folder)
        self.addCleanup(diagnostics.close)
        self.stderr = self.context.enter_context(redirect_stderr(io.StringIO()))
        self.context.enter_context(patch.object(preparation, '_dependency_warning', None))
        self.context.enter_context(patch.object(preparation.platform, 'python_implementation', return_value='CPython'))
        self.context.enter_context(patch.object(preparation.platform, 'python_version', return_value='3.12.1'))
        self.context.enter_context(patch.object(preparation.sys, 'version_info', (3, 12, 1)))
        self.versions = dict(preparation.PINS)
        self.context.enter_context(patch.object(preparation.metadata, 'version', side_effect=self.version))

    def version(self, name):
        if name not in self.versions:
            raise preparation.metadata.PackageNotFoundError('PRIVATE-EXCEPTION-CANARY')
        return self.versions[name]

    def unavailable(self):
        with self.assertRaises(preparation.PreparationError) as raised:
            preparation.dependencies()
        self.assertEqual(raised.exception.category, 'dependencies unavailable')

    def warnings(self):
        return [json.loads(line.split(' WARNING ', 1)[1])
                for line in self.path.read_text().splitlines() if ' WARNING ' in line]

    def test_all_missing_packages_are_named_with_required_versions_and_interpreter(self):
        self.versions.clear()
        self.unavailable()
        terminal = self.stderr.getvalue()
        warning, = self.warnings()
        self.assertEqual(warning['event'], 'candidate.dependencies_unavailable')
        self.assertEqual(warning['interpreter'], sys.executable)
        self.assertEqual(warning['required'], preparation.PINS)
        self.assertEqual(warning['installed'], dict.fromkeys(preparation.PINS))
        for name, version in preparation.PINS.items():
            self.assertIn(f'{name} is missing (required {version})', terminal)
        self.assertIn(json.dumps(sys.executable), terminal)
        self.assertIn('Install requirements-numerical.txt', terminal)
        self.assertIn('Prepare experimental engine', terminal)
        self.assertIn('Original and stored results remain available', terminal)
        self.assertNotIn('PRIVATE-EXCEPTION-CANARY', terminal + self.path.read_text())

    def test_wrong_version_is_distinguished_from_missing_package(self):
        self.versions['numpy'] = '2.0.0'
        del self.versions['numba']
        self.unavailable()
        self.assertIn('numpy has version 2.0.0 (required 2.5.4)', self.stderr.getvalue())
        self.assertIn('numba is missing (required 0.68.0)', self.stderr.getvalue())
        self.assertEqual(self.warnings()[0]['installed']['llvmlite'], preparation.PINS['llvmlite'])

    def test_unsupported_python_explains_compatible_versions(self):
        with patch.object(preparation.sys, 'version_info', (3, 11, 0)), \
                patch.object(preparation.platform, 'python_version', return_value='3.11.0'):
            self.unavailable()
        self.assertIn('CPython 3.11.0 is unsupported (required CPython 3.12 or 3.14)', self.stderr.getvalue())
        self.assertFalse(self.warnings()[0]['supported_python'])

    def test_status_polling_deduplicates_warning_but_changes_and_recurrence_are_reported(self):
        del self.versions['numpy']
        self.unavailable()
        self.unavailable()
        self.assertEqual(len(self.warnings()), 1)
        self.assertEqual(self.stderr.getvalue().count('WARNING:'), 1)
        del self.versions['numba']
        self.unavailable()
        self.assertEqual(len(self.warnings()), 2)
        self.versions.update(preparation.PINS)
        self.assertEqual(preparation.dependencies()['packages'], preparation.PINS)
        del self.versions['numpy']
        self.unavailable()
        self.assertEqual(len(self.warnings()), 3)

    def test_current_packages_have_no_warning(self):
        self.assertEqual(preparation.dependencies(), dict(python='3.12.1', packages=preparation.PINS,profile='numba_compiled',rust_required=False))
        self.assertEqual(self.stderr.getvalue(), '')
        self.assertEqual(self.warnings(), [])

    def test_selected_dependencies_never_import_or_require_comparison_rust(self):
        with patch.dict(sys.modules,{'numerical_toolchain':None,'numerical_rust':None}):
            installed=preparation.dependencies()
            self.assertFalse(installed['rust_required']);self.assertNotIn('native',installed)
        with self.assertRaises(ValueError):preparation.dependencies('rust')


if __name__ == '__main__':
    unittest.main()
