"""Stored-book random trials in worker processes: the serial result stream, and the runs that stay serial."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from datetime import date
import io
import json
import pickle
import unittest
from unittest.mock import patch

from backtest import portfolio_results, result_evidence
from backtest.application import evidence_views, scalar_runs, strategy_requests
from backtest.application.original_calculations import Original
from backtest.inputs import research
from backtest.variables import definitions
from prepared_inputs_fixture import PreparedInputs, history
from test_strategy_requests import builtin, formula, pipeline, sleeves, rank_step
import test_variable_definitions as language


def capture(*others):
    """A size filter, a built-in rank and a final rank by a formula over annual and dated facts.

    With other chains, the strategy has this chain and then each other chain as sleeves.
    """
    base = language.entry(language.definition(dict(op='annual', stat='mean', count=3,
        parameter='annual.operating_income'), 'USD', 'usd_million'), 'trials:annual')
    signal = language.entry(language.definition(language.binary('div', language.reference(base),
        dict(op='parameter', id='market.enterprise_value')), 'scalar', 'percent'), 'trials:yield')
    chain = [dict(kind='filter', source=dict(kind='field', field='market_cap'), op='ge', threshold=dict(value='0', unit='usd')),
             rank_step(builtin(), 1, 6), rank_step(formula(signal), 1, 3)]
    return strategy_requests.capture_strategy(sleeves(chain, *others) if others else pipeline(*chain),
                                              submitted=[base, signal]).to_dict()


def periods(reader, trial):
    """Each period's dates, returns and (symbol, return) holdings in order."""
    result = []
    for record in evidence_views.records(reader, trial):
        if record['type'] == 'period':
            value = record['value']
            result.append((value['entry'], value['exit'], value['portfolio'], value['spy'], []))
        elif record['type'] == 'holding':
            result[-1][-1].append((record['value']['symbol'], record['value']['return_value']))
    return result


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


    def test_sleeves_equal_their_chains_run_alone_and_joined_per_period(self):
        energy = [dict(kind='filter', source=dict(kind='field', field='sector'), op='eq', threshold='Energy'), rank_step(builtin(), 1, 2)]
        strategies = [capture(energy), capture(), strategy_requests.capture_strategy(pipeline(*energy)).to_dict()]
        with PreparedInputs(configure=history(8, 2023, 2026)):
            through = json.loads((research.RAW/'spy-div.json').read_bytes())[-1]['date']
            def run(strategy, mode, **options):
                stream, plans = io.BytesIO(), []
                Original().calculate_into(mode, dict(strategy=strategy, **options), stream, None, plans.append)
                return result_evidence.open_reader(stream, max_bytes=256*1024**2), plans
            screens = [[record['value']['symbol'] for record in run(strategy, 'latest')[0].verified_records()
                        if record['type'] == 'screen'] for strategy in strategies]
            self.assertEqual(screens[0], list(dict.fromkeys(screens[1] + screens[2])))
            for mode, options in (('custom', dict(start='2023-01-02', end=through, months=3)),
                                  ('random', dict(start='2023-01-02', end=through, months=6, trials=4, seed=11))):
                with self.subTest(mode=mode):
                    alone = [run(strategy, mode, **options) for strategy in strategies[1:]]
                    # The sleeve run takes the worker path once the chains have stored every book.
                    with patch.object(scalar_runs, 'MIN_PARALLEL_PERIODS', 1), patch.object(scalar_runs, 'TRIAL_WORKERS', 2):
                        joined, plans = run(strategies[0], mode, **options)
                    if mode == 'random':
                        self.assertEqual(joined.manifest['summary']['execution']['workers'], 2)
                        self.assertTrue(all(found[0]['samples'] == plans[0]['samples'] for _, found in alone))
                    dropped = 0
                    for trial in range(1, joined.manifest['trials'] + 1):
                        expected = []
                        for parts in zip(*(periods(reader, trial) for reader, _ in alone)):
                            self.assertEqual(len({part[:2] for part in parts}), 1)
                            held = {}
                            for symbol, value in sum((part[-1] for part in parts), []):
                                held.setdefault(symbol, value)
                            dropped += sum(len(part[-1]) for part in parts) - len(held)
                            expected.append((*parts[0][:2], portfolio_results.mean_return(held.values()), parts[0][3], list(held.items())))
                        self.assertEqual(periods(joined, trial), expected)
                        summary = evidence_views.trial(joined, trial)['summary']
                        totals = portfolio_results.reduce_returns(((period[2], period[3]) for period in expected),
                            start=date.fromisoformat(summary['start']), end=date.fromisoformat(summary['end']))
                        self.assertEqual({key: summary[key] for key in totals}, totals)
                    # Some stock was picked by both sleeves and held once.
                    self.assertGreater(dropped, 0)

    def test_formula_error_from_a_worker_keeps_its_issues(self):
        error = definitions.FormulaError(errors=[dict(code='FUTURE_DATE', path='/a', message='first'), dict(code='WORK_LIMIT', path='/b', message='second')])
        returned = pickle.loads(pickle.dumps(error))
        self.assertEqual((returned.to_dict(), str(returned), returned.code, returned.path), (error.to_dict(), 'first', 'FUTURE_DATE', '/a'))


if __name__ == '__main__':
    unittest.main()
