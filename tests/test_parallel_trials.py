"""Stored-book random trials in worker processes: the serial result stream, and the runs that stay serial."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import io
import json
import pickle
import unittest
from unittest.mock import patch

from backtest import result_evidence
from backtest.application import scalar_runs, strategy_requests
from backtest.application.original_calculations import Original
from backtest.inputs import research
from backtest.variables import definitions
from prepared_inputs_fixture import PreparedInputs, history
from test_strategy_requests import builtin, formula, pipeline, rank_step
import test_variable_definitions as language


def capture():
    """A size filter, a built-in rank and a final rank by a formula over annual and dated facts."""
    base = language.entry(language.definition(dict(op='annual', stat='mean', count=3,
        parameter='annual.operating_income'), 'USD', 'usd_million'), 'trials:annual')
    signal = language.entry(language.definition(language.binary('div', language.reference(base),
        dict(op='parameter', id='market.enterprise_value')), 'scalar', 'percent'), 'trials:yield')
    return strategy_requests.capture_strategy(pipeline(
        dict(kind='filter', source=dict(kind='field', field='market_cap'), op='ge', threshold=dict(value='0', unit='usd')),
        rank_step(builtin(), 1, 6), rank_step(formula(signal), 1, 3)), submitted=[base, signal]).to_dict()


def comparable(value):
    """A record without elapsed times, the worker count and the stream digest that follows from the times."""
    if type(value) is list:
        return [comparable(item) for item in value]
    if type(value) is not dict:
        return value
    return {key: comparable(item) for key, item in value.items()
            if key not in ('seconds', 'workers') and (key != 'sha256' or value.get('type') != 'complete')}


class ParallelTrialTests(unittest.TestCase):
    def test_stored_books_run_in_workers_with_the_serial_stream_and_other_runs_stay_serial(self):
        serial = patch.object(scalar_runs, 'ProcessPoolExecutor', side_effect=AssertionError('This run is serial'))
        with PreparedInputs(configure=history(8, 2023, 2026)):
            through = json.loads((research.RAW/'spy-div.json').read_bytes())[-1]['date']
            options = dict(strategy=capture(), start='2023-01-02', end=through, months=6, trials=6, seed=7)
            plans = []
            def run(planned=None):
                stream = io.BytesIO()
                Original().calculate_into('random', options, stream, None, plans.append, planned=planned)
                reader = result_evidence.open_reader(stream, max_bytes=256*1024**2)
                return list(reader.verified_records()), reader.manifest['summary']['execution']
            # Two workers and a window of four trials, so the six trials refill it.
            with patch.object(scalar_runs, 'MIN_PARALLEL_PERIODS', 1), patch.object(scalar_runs, 'TRIAL_WORKERS', 2):
                # A missing book keeps the serial path.
                with serial:
                    _, execution = run()
                self.assertGreater(execution['missing_books'], 0)
                parallel, execution = run(plans[0])
                self.assertEqual((execution['workers'], execution['missing_books']), (2, 0))
            # A run below the size threshold keeps the serial path.
            with serial:
                expected, execution = run(plans[0])
            self.assertEqual((execution['workers'], execution['missing_books']), (0, 0))
            self.assertEqual(len({tuple(sample) for sample in plans[0]['samples']}), 6)
            self.assertGreater(sum(record['type'] == 'holding' for record in expected), 3 * 6)
            self.assertEqual(len(parallel), len(expected))
            for actual, record in zip(parallel, expected):
                self.assertEqual(comparable(actual), comparable(record))


    def test_formula_error_from_a_worker_keeps_its_issues(self):
        error = definitions.FormulaError(errors=[dict(code='FUTURE_DATE', path='/a', message='first'), dict(code='WORK_LIMIT', path='/b', message='second')])
        returned = pickle.loads(pickle.dumps(error))
        self.assertEqual((returned.to_dict(), str(returned), returned.code, returned.path), (error.to_dict(), 'first', 'FUTURE_DATE', '/a'))


if __name__ == '__main__':
    unittest.main()
