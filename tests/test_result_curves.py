"""Asset curves read from fictional saved periods; no cache or financial inputs."""
from datetime import date
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from backtest import portfolio_results, result_evidence
from backtest.application import result_curves
from backtest.runtime import backtest_control
from test_portfolio_results import holding

START = date(2020, 1, 2)
DAYS = [date(2020, 1, day) for day in (6, 7, 8, 9, 10, 13)]


def trial(first, returns, *, curves=True):
    """One trial that trades on DAYS from index first: one holding whose return to date grows by its period's rate each day."""
    days = DAYS[first:]
    periods = [(days[0], days[2]), (days[2], days[-1])] if len(days) > 3 else [(days[0], days[-1])]
    def book(entry, exit_day):
        rate = returns[periods.index((entry, exit_day))]
        inside = [day for day in DAYS if entry < day <= exit_day]
        path = [rate*(n+1)/len(inside) for n in range(len(inside))]
        row = holding('A', 1, path[-1], entry=str(entry), exit=str(exit_day))
        found = dict(entry=str(entry), exit=str(exit_day), holdings=[row], spy=.01*len(inside))
        if curves:
            found['curve'] = dict(days=[str(day) for day in inside], portfolio=path,
                                  spy=[.01*(n+1) for n in range(len(inside))], exits=[path[-1]])
        return found
    result = portfolio_results.evaluate(periods, book, common_start=START)
    result.update(options=dict(rank_from=1, rank_to=1), seconds=0.)
    return result


def encoded(trials, mode='random'):
    stream = io.BytesIO()
    writer = result_evidence.Writer(stream, trials=len(trials), metadata=dict(mode=mode), max_bytes=8*1024**2)
    for number, result in enumerate(trials, 1):
        writer.start_trial(number)
        for period in result['periods']:
            writer.period(period)
        writer.end_trial({key: value for key, value in result.items() if key != 'periods'})
    writer.finish(dict(completed=len(trials)))
    return result_evidence.Reader(stream, max_bytes=8*1024**2)


class CurveTests(unittest.TestCase):
    def setUp(self):
        self.early = trial(0, [.2, -.1])
        self.late = trial(3, [.3])
        self.reader = encoded([self.early, self.late])

    def test_a_trial_compounds_its_periods_to_the_saved_growth(self):
        curve = result_curves.evidence(self.reader, 1)
        self.assertTrue(curve['available'])
        # Cash from the common start to the first trade, then every session.
        self.assertEqual(curve['days'], ['2020-01-02'] + [str(day) for day in DAYS])
        self.assertEqual(curve['strategy'][:4], [1., 1., 1+.2/2, 1+.2])
        self.assertEqual(curve['strategy'][4:], [1.2*(1+-.1*n/3) for n in (1, 2, 3)])
        self.assertEqual(curve['spy'], [1., 1., 1+.01, 1+.02] + [(1+.02)*(1+.01*n) for n in (1, 2, 3)])
        self.assertEqual((curve['strategy'][-1], curve['spy'][-1]), (self.early['growth'], self.early['spy_growth']))
        late = result_curves.evidence(self.reader, 2)
        self.assertEqual(late['days'], ['2020-01-02', '2020-01-09', '2020-01-10', '2020-01-13'])
        self.assertEqual((late['strategy'][-1], late['spy'][-1]), (self.late['growth'], self.late['spy_growth']))

    def test_all_trials_give_the_median_lowest_and_highest_value_on_each_day(self):
        band = result_curves.evidence(self.reader)
        first, second = result_curves.evidence(self.reader, 1), result_curves.evidence(self.reader, 2)
        self.assertEqual(band['days'], first['days'])
        # The late trial holds cash at 1 until its first trade on 9 January.
        held = [1.]*4 + second['strategy'][1:]
        paired = [1.]*4 + second['spy'][1:]
        self.assertEqual(band['lowest'], [min(pair) for pair in zip(first['strategy'], held)])
        self.assertEqual(band['highest'], [max(pair) for pair in zip(first['strategy'], held)])
        self.assertEqual(band['median'], [(a+b)/2 for a, b in zip(first['strategy'], held)])
        self.assertEqual(band['spy'], [(a+b)/2 for a, b in zip(first['spy'], paired)])
        single = result_curves.evidence(encoded([self.late], 'custom'))
        self.assertEqual((single['median'], single['lowest'], single['highest']), (second['strategy'],)*3)

    def test_a_result_saved_without_curves_reports_that_none_is_available(self):
        plain = trial(0, [.2, -.1], curves=False)
        for selection in (1, 'all'):
            self.assertEqual(result_curves.evidence(encoded([plain]), selection), dict(available=False))

    def test_missing_trial_and_cancellation(self):
        with self.assertRaisesRegex(ValueError, 'Stored trial not found'):
            result_curves.evidence(self.reader, 3)
        with patch.object(backtest_control, 'checkpoint', side_effect=backtest_control.Cancelled()):
            with self.assertRaises(backtest_control.Cancelled):
                result_curves.evidence(self.reader)


if __name__ == '__main__':
    unittest.main()
