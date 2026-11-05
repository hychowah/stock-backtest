"""Heavy tier: the Original-only long-window custom-variable workload.

64 fictional companies, 1996-2026, the long-window capture and an annual
custom schedule give 31 periods. The operation must complete with one entry
fingerprint and no rescan of prepared rows. The receipt prints elapsed seconds;
nothing asserts a time.
Run the file directly to see the receipt; tests/run.py shows output only for a
failed file.
"""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import io
import json
import time
import unittest

from backtest.application.original_calculations import Original
from backtest.inputs import research
from prepared_inputs_fixture import PreparedInputs, history
from test_operation_inputs import counted, long_window_capture


class LongWindowTests(unittest.TestCase):
    def test_long_window_completes_with_boundary_checks_only(self):
        began = time.perf_counter()
        with PreparedInputs(configure=history(64, 1996, 2026)):
            preparation = time.perf_counter() - began
            through = json.loads((research.RAW/'spy-div.json').read_bytes())[-1]['date']
            options = dict(strategy=long_window_capture().to_dict(), start='1996-01-02', end=through, months=12)
            fingerprints, contents = counted()
            with fingerprints as fingerprint, contents as content:
                began = time.perf_counter()
                result = Original().calculate_into('custom', options, io.BytesIO(), None, None)
                seconds = time.perf_counter() - began
            self.assertEqual(result['manifest']['periods'], 31)
            self.assertGreater(result['manifest']['holdings'], 0)
            self.assertEqual((fingerprint.call_count, content.call_count), (1, 0))
        # The preparation fixture captures standard output until it closes.
        print('ORIGINAL_LONG_WINDOW_RECEIPT ' + json.dumps(dict(preparation_seconds=preparation,
            calculation_seconds=seconds, periods=result['manifest']['periods'],
            holdings=result['manifest']['holdings'], bytes=result['transfer']['bytes'])), flush=True)


if __name__ == '__main__':
    unittest.main()
