"""Real numerical entry tests under unchanged guarded native verification.

The adapter translates launch syntax and retains discarded output privately.
No network/HTTP/browser or literal production command syntax is qualified.
"""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import os
import subprocess
import unittest
from guarded_numerical_entries import install
import test_numerical_scalar_process as process

ROOT=Path(__file__).resolve().parents[1]


def guarded_setup(case,setup=process.offline.ActualScopeTests.setUp):
    case.assertEqual(sys.platform,'win32','Select only in guarded native verification.')
    original,original_null=subprocess.Popen,os.devnull
    install(ROOT)
    case.addCleanup(setattr,subprocess,'Popen',original)
    case.addCleanup(setattr,os,'devnull',original_null)
    setup(case)


class NativeScalarPoolTests(process.ScalarPoolTests):
    setUp=guarded_setup


class NativeScalarCandidateTests(process.ScalarCandidateTests):
    setUp=guarded_setup


class NativeWorkerMarkerTests(process.WorkerMarkerTests):
    def setUp(self):guarded_setup(self,process.WorkerMarkerTests.setUp)


if __name__=='__main__':unittest.main()
