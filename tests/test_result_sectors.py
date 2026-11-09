"""Sector views over fictional original books; no cache or current catalog."""
from copy import deepcopy
from datetime import date
import io
import json
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from backtest import portfolio_results, result_evidence
from backtest.application import result_sectors
from backtest.runtime import backtest_control
from test_portfolio_results import holding


def original(books):
    days = [date(2015 + n, 1, 2) for n in range(len(books) + 1)]
    def book(entry, exit_day):
        labels = books[days.index(entry)]
        rows = [dict(holding('S' + str(n), n, .1, entry=str(entry), exit=str(exit_day)), sector=sector)
            for n, sector in enumerate(labels, 1)]
        return dict(entry=str(entry), exit=str(exit_day), holdings=rows, spy=.05)
    result = portfolio_results.evaluate(list(zip(days, days[1:])), book)
    result.update(options=dict(rank_from=1, rank_to=50), seconds=0.)
    return result


def encoded(trials):
    stream = io.BytesIO()
    writer = result_evidence.Writer(stream, trials=len(trials), metadata=dict(mode='random'), max_bytes=8*1024**2)
    for number, result in enumerate(trials, 1):
        writer.start_trial(number)
        for period in result['periods']:
            writer.period(period)
        writer.end_trial({k: v for k, v in result.items() if k != 'periods'})
    writer.finish(dict(completed=len(trials)))
    return result_evidence.Reader(stream, max_bytes=8*1024**2)


def sectors(rows):
    return {row['name']: row for row in rows}


class SectorTests(unittest.TestCase):
    def setUp(self):
        self.first = original([['Energy'] * 40 + [None] * 10, ['Energy', None], []])
        self.second = original([['Energy']])
        self.batch = dict(trial_results=[self.first, self.second], completed=2)

    def test_equal_rebalances_then_equal_trials_and_cash(self):
        result = result_sectors.eager(self.batch)
        first = result['trials'][0]
        energy = sectors(first['sectors'])['Energy']
        self.assertAlmostEqual(energy['mean'], (40/50 + 1/2) / 3)
        self.assertEqual((energy['minimum'], energy['maximum'], energy['present']), (0., .8, 2))
        self.assertEqual(first['cash'], 1/3)
        combined = sectors(result['sectors'])
        self.assertAlmostEqual(combined['Energy']['mean'], (energy['mean'] + 1) / 2)
        self.assertAlmostEqual(result['cash'], 1/6)
        self.assertAlmostEqual(sum(row['mean'] for row in combined.values()) + result['cash'], 1.)
        self.assertEqual(combined[None]['minimum'], 0.)

    def test_inline_and_evidence_parity_without_changing_original_bytes(self):
        original_json = json.dumps(self.batch)
        reader = encoded(self.batch['trial_results'])
        original_bytes = reader.stream.getvalue()
        for trial in ('all', 1, 2):
            self.assertEqual(result_sectors.evidence(reader, trial), result_sectors.eager(self.batch, trial))
        self.assertEqual(json.dumps(self.batch), original_json)
        self.assertEqual(reader.stream.getvalue(), original_bytes)
        detail = result_sectors.evidence(reader, 1)
        self.assertEqual([row['names'] for row in detail['periods']], [50, 2, 0])
        self.assertEqual(detail['periods'][2]['sectors'], [])

    def test_incomplete_trials_stay_visible_but_do_not_change_combined_mean(self):
        self.second['cagr'] = None
        result = result_sectors.eager(self.batch)
        self.assertEqual((result['complete'], result['incomplete']), (1, 1))
        self.assertFalse(result['trials'][1]['complete'])
        self.assertAlmostEqual(sectors(result['sectors'])['Energy']['mean'], (40/50 + 1/2) / 3)
        self.first['cagr'] = None
        empty = result_sectors.eager(self.batch)
        self.assertEqual((empty['complete'], empty['sectors'], empty['cash']), (0, [], None))
        self.assertEqual(result_sectors.eager(self.batch, 2)['periods'][0]['names'], 1)

    def test_missing_sectors_and_whole_cash_trial(self):
        result = result_sectors.eager(original([[None, '', 'Energy'], []]), 1)
        self.assertEqual(sectors(result['periods'][0]['sectors'])[None]['count'], 2)
        self.assertAlmostEqual(sectors(result['trials'][0]['sectors'])[None]['mean'], 1/3)
        cash = result_sectors.eager(original([[], []]))
        self.assertEqual((cash['sectors'], cash['cash'], cash['complete']), ([], 1., 1))

    def test_sector_pages_keep_original_rank_weight_and_exact_rows(self):
        result = original([['Energy' if n % 2 else None for n in range(150)]])
        reader = encoded([result])
        for sector in ('Energy', None, 'Absent'):
            expected = [row for row in result['periods'][0]['holdings'] if (row['sector'] or None) == sector]
            rows = []
            cursor = 0
            while cursor is not None:
                page = result_sectors.holdings(reader, 1, 1, sector, cursor)
                self.assertLessEqual(len(page['rows']), 64)
                rows.extend(page['rows'])
                cursor = page['next']
            self.assertEqual(rows, expected)

    def test_current_reader_freshness_and_cancellation_remain_in_force(self):
        reader = encoded(self.batch['trial_results'])
        with backtest_control.cancel_when(lambda: False):
            self.assertEqual(result_sectors.evidence(reader)['complete'], 2)
        with self.assertRaises(backtest_control.Cancelled):
            with backtest_control.cancel_when(lambda: True):
                result_sectors.evidence(reader)
        reader.stream.seek(-1, 2)
        reader.stream.write(b'x')
        with self.assertRaisesRegex(ValueError, 'changed'):
            result_sectors.evidence(reader)

    def test_invalid_selection_or_missing_old_details_fails_explicitly(self):
        for trial in (0, True, 1.5, 'other', 3):
            with self.subTest(trial=trial), self.assertRaises(ValueError):
                result_sectors.eager(self.batch, trial)
        missing = deepcopy(self.batch)
        missing.pop('trial_results')
        with self.assertRaises(ValueError):
            result_sectors.eager(missing)
        with self.assertRaises(ValueError):
            result_sectors.holdings(encoded([self.first]), 1, 1, ['Energy'])


if __name__ == '__main__':
    unittest.main()
