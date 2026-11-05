"""Operation-held prepared inputs: one fingerprint at entry, cheap between-step checks."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import io
import json
import os
import sqlite3
import unittest
from unittest.mock import patch

from backtest.application import strategy_requests
from backtest.application.original_calculations import Original
from backtest.inputs import daily, observation_inputs, operation_inputs, research
from backtest.runtime import backtest_control
from prepared_inputs_fixture import PreparedInputs, history
import test_strategy_requests as intent
import test_variable_definitions as language


def long_window_capture():
    """Three-year mean operating income over dated enterprise value, ranked highest."""
    base = language.entry(language.definition(dict(op='annual', stat='mean', count=3,
        parameter='annual.operating_income'), 'USD', 'usd_million'), 'qualification:annual')
    signal = language.entry(language.definition(language.binary('div', language.reference(base),
        dict(op='parameter', id='market.enterprise_value')), 'scalar', 'percent'), 'qualification:yield')
    value = intent.intent(intent.formula(signal)); value['pool'] = 'cached'
    return strategy_requests.capture_strategy(value, submitted=[base, signal])


def counted():
    """Count complete fingerprints and complete content verifications."""
    return (patch.object(daily, 'fingerprint', wraps=daily.fingerprint),
            patch.object(observation_inputs, 'content_identity', wraps=observation_inputs.content_identity))


def closed(db):
    try:
        db.execute('SELECT 1')
    except sqlite3.ProgrammingError:
        return True
    return False


class HeldInputsTests(unittest.TestCase):
    def setUp(self):
        self.prepared = PreparedInputs()
        self.addCleanup(self.prepared.close)

    def test_unchanged_inputs_pass_each_step_and_close_on_exit(self):
        with operation_inputs.held(checkpoint=lambda: None) as inputs:
            inputs.require_unchanged(); inputs.require_unchanged()
            source = inputs.research()
            self.assertIs(inputs.research(), source)
            self.assertEqual(source.execute("SELECT count(*) FROM companies WHERE symbol='TEST'").fetchone()[0], 1)
            db = inputs.db
        self.assertTrue(closed(db) and closed(source))

    def test_rewritten_or_replaced_research_database_fails_the_next_step(self):
        path = self.prepared.source
        def rewritten():
            content = path.read_bytes()
            with path.open('r+b') as handle: handle.write(content)
        def replaced():
            copy = path.with_name('replacement.sqlite'); copy.write_bytes(path.read_bytes()); os.replace(copy, path)
        for change in (rewritten, replaced):
            with self.subTest(change=change.__name__):
                with self.assertRaisesRegex(ValueError, 'changed during the operation'):
                    with operation_inputs.held(checkpoint=lambda: None) as inputs:
                        change(); inputs.require_unchanged()

    def test_cancellation_closes_connections_after_one_fingerprint(self):
        def cancel(): raise backtest_control.Cancelled()
        fingerprints, _ = counted()
        with fingerprints as fingerprint, self.assertRaises(backtest_control.Cancelled):
            with operation_inputs.held(checkpoint=cancel) as inputs:
                source = inputs.research(); db = inputs.db
                inputs.require_unchanged()
        self.assertEqual(fingerprint.call_count, 1)
        self.assertTrue(closed(db) and closed(source))


class OriginalScaleTests(unittest.TestCase):
    def test_input_checks_do_not_grow_with_schedule_length(self):
        with PreparedInputs(configure=history(4, 2023, 2026)):
            through = json.loads((research.RAW/'spy-div.json').read_bytes())[-1]['date']
            capture = long_window_capture().to_dict()
            for mode, options, periods in [
                    ('custom', dict(strategy=capture, start='2025-01-02', end=through, months=12), 2),
                    ('custom', dict(strategy=capture, start='2023-01-02', end=through, months=12), 4),
                    ('latest', dict(strategy=capture), None)]:
                fingerprints, contents = counted()
                with self.subTest(mode=mode, periods=periods), fingerprints as fingerprint, contents as content:
                    result = Original().calculate_into(mode, options, io.BytesIO(), None, None)
                    # One entry fingerprint; no prepared row is rescanned.
                    self.assertEqual((fingerprint.call_count, content.call_count), (1, 0))
                    if periods is not None:
                        self.assertEqual(result['manifest']['periods'], periods)
                        self.assertGreater(result['manifest']['holdings'], 0)


if __name__ == '__main__':
    unittest.main()
