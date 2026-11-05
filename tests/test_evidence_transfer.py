"""Exact private plan references; fictional bytes only."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backtest.application import evidence_transfer as transfer


class PlanTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name)

    def test_bounded_plan_content_replacement_escape_nonfinite_and_duplicate_keys(self):
        original={'samples':[['2010-01-04']*3000]*30,'extension':None}
        reference=transfer.stage_plan(self.root,original)
        self.assertGreater(reference['bytes'],1024**2)
        self.assertEqual(transfer.read_plan(self.root,reference),original)
        self.assertEqual(transfer.plan_identity(dict(reversed(list(original.items())))),reference['sha256'])
        path=self.root/'recorded-plan.json';raw=path.read_bytes()
        for changed in (raw[:-1],raw+b'x',raw.replace(b'2010',b'2011')):
            path.write_bytes(changed)
            with self.assertRaises(ValueError):transfer.read_plan(self.root,reference)
        path.unlink();path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'replaced'):transfer.read_plan(self.root,reference)
        reference=transfer.stage_plan(self.root,original)
        for extra in ({'path':'../outside'},{'version':2},{'bytes':transfer.MAX_PLAN_BYTES+1}):
            with self.assertRaises(ValueError):transfer.read_plan(self.root,dict(reference,**extra))
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}'):
            path.write_bytes(raw)
            ref=dict(version=1,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),file_identity=transfer._fingerprint(path.stat()))
            with self.assertRaises(ValueError):transfer.read_plan(self.root,ref)
        with patch.object(Path,'is_symlink',return_value=True):
            with self.assertRaisesRegex(ValueError,'escapes'):transfer.read_plan(self.root,reference)
        with self.assertRaisesRegex(ValueError,'byte bound'):transfer.stage_plan(self.root,{'x':'x'*(transfer.MAX_PLAN_BYTES+1)})
        self.assertFalse((self.root/'recorded-plan.pending').exists())


if __name__=='__main__':unittest.main()
