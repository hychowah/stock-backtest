"""Actual backend-specific preparation, source/input guards and closed providers."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
ROOT=Path(__file__).absolute().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'scripts'),str(ROOT/'website')]
from bench_source_service_fixture import FictionalWorkspace
import numerical_preparation as preparation
from numerical_runtime import NumericalRuntime


class ProfileTests(unittest.TestCase):
    def test_profiles_are_fixed_internal_choices_and_runtime_rejects_mismatch(self):
        with self.assertRaises(ValueError):preparation.Preparation(ROOT,profile='arbitrary')
        with self.assertRaises(ValueError):NumericalRuntime(source_root=ROOT,scratch=ROOT/'tmp/not-started-profile',
            session_options={'execution':{'backend':'rust'}},preparation_profile='numba_compiled')
        inferred=NumericalRuntime(source_root=ROOT,scratch=ROOT/'tmp/not-started-profile',
            session_options={'execution':{'backend':'numba_compiled'}})
        self.assertEqual(inferred.configuration['preparation_profile'],'numba_compiled')

    def test_genuine_profiles_keep_all_freshness_and_numba_uses_no_rust(self):
        with FictionalWorkspace() as workspace:
            tests=workspace.source/'tests';tests.mkdir()
            shutil.copy2(ROOT/'tests/numerical_profile_fixture.py',tests/'numerical_profile_fixture.py')
            output=workspace.root/'profiles.json';log=workspace.root/'profiles.log'
            with log.open('wb') as stream:
                result=subprocess.run([sys.executable,'-I','-B',str(tests/'numerical_profile_fixture.py'),str(workspace.source),str(output)],stdout=stream,stderr=subprocess.STDOUT)
            if result.returncode:self.fail(log.read_text(encoding='utf8',errors='replace'))
            evidence=json.loads(output.read_bytes())
            self.assertEqual(len(evidence['checks']),3)
            self.assertTrue(evidence['numba_zero_rust']);self.assertTrue(evidence['no_managed_installation'])
            self.assertTrue(evidence['source_without_rust_dependency'])
            self.assertEqual(evidence['positive_provider_constructions'],1)
            self.assertEqual(evidence['positive_factor_compilations'],1)
            print(json.dumps(dict(check='genuine-backend-preparation-profiles',**evidence)),flush=True)

if __name__=='__main__':unittest.main()
