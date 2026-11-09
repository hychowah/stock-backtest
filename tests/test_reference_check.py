"""Same-input regression failure and informational frozen-report differences."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))

from copy import deepcopy
from contextlib import redirect_stdout
from datetime import date
import io
import json
import unittest
from unittest.mock import patch

from backtest.engines.reference import check, legacy, revalue
from backtest.inputs import research
from backtest.runtime import cache_access
from prepared_inputs_fixture import PreparedInputs, history


class ReferenceCheckTests(unittest.TestCase):
    def setUp(self):
        inputs = PreparedInputs(configure=history(12, 2014, 2016))
        self.inputs = inputs
        self.addCleanup(inputs.close)
        # The reference engine reads the fixture and follows its study years.
        for owner, name, value in ((revalue, 'RAW', research.RAW), (legacy, 'RAW', research.RAW),
                                   (legacy, 'FIRST_YEAR', 2014), (legacy, 'LAST_YEAR', 2016)):
            inputs.context.enter_context(patch.object(owner, name, value))
        self.through = date(2016, 10, 20)
        with cache_access.access():
            self.result = check.dated(self.through)
            self.reference = revalue.calculate(self.through)
        self.adapted = check.adapt(self.result, self.through)

    def test_dated_run_equals_the_independent_reference(self):
        self.assertEqual(check.options(self.through), dict(start='2014-01-01', end='2016-10-20', months=12,
                         pool='legacy', metric='ev_ebitda', rank_from=1, rank_to=50))
        self.assertEqual([year['year'] for year in self.adapted['years']], [2014, 2015, 2016])
        self.assertEqual([len(year['holdings']) for year in self.adapted['years']], [12, 12, 12])
        self.assertEqual(check.differences(self.adapted, self.reference), [])

    def test_each_difference_is_named(self):
        altered = deepcopy(self.reference)
        year = altered['years'][1]
        year['holdings'][0]['return_value'] += 1e-9
        year['holdings'][1]['symbol'] = 'OTHER'
        year['spy'] += 1e-9
        del altered['years'][2]
        found = check.differences(self.adapted, altered)
        first, second = self.adapted['years'][1]['holdings'][0], self.adapted['years'][1]['holdings'][1]
        self.assertEqual(found, [
            dict(kind='year_field', year=2015, field='spy', dated=self.adapted['years'][1]['spy'], reference=year['spy']),
            dict(kind='holding_only_dated', year=2015, symbol=second['symbol'], rank=second['rank']),
            dict(kind='holding_only_reference', year=2015, symbol='OTHER', rank=second['rank']),
            dict(kind='holding_field', year=2015, symbol=first['symbol'], field='return_value',
                 dated=first['return_value'], reference=year['holdings'][0]['return_value']),
            dict(kind='year_missing', year=2016, side='reference')])

    def test_frozen_report_rows_compare_at_four_decimals(self):
        rows = ''.join(f'{y["year"]},{y["portfolio"]:.4f},{y["spy"]:.4f},{len(y["holdings"])},0,0\n'
                       for y in self.adapted['years'])
        text = 'Through 2016-10-20\n\nyear,portfolio,spy,names,stopped,bankrupt\n' + rows
        self.assertEqual(check.report_through(text), self.through)
        self.assertEqual(check.report_rows(self.adapted, text), [])
        changed = text.replace('2016,', '2016,9', 1)
        self.assertEqual([(item['year'], item['field']) for item in check.report_rows(self.adapted, changed)],
                         [(2016, 'portfolio')])

    def test_cli_reports_frozen_drift_but_fails_only_calculation_differences(self):
        results = self.inputs.root/'records'
        results.mkdir()
        report = results/'summary-exits.txt'
        rows = ''.join(f'{y["year"]},{9 if y["year"]==2016 else y["portfolio"]:.4f},'
                       f'{y["spy"]:.4f},{len(y["holdings"])},0,0\n' for y in self.adapted['years'])
        report.write_text('Through 2016-10-20\n\nyear,portfolio,spy,names,stopped,bankrupt\n'+rows)
        original = report.read_bytes()
        output = results/'check.json'
        for mismatch in (False, True):
            with self.subTest(calculation_mismatch=mismatch):
                reference = deepcopy(self.reference)
                if mismatch:reference['years'][0]['holdings'][0]['return_value'] += .01
                console = io.StringIO()
                with patch('backtest.paths.RESULTS', results), patch.object(check, 'dated', return_value=self.result), \
                     patch.object(revalue, 'calculate', return_value=reference), \
                     patch.object(_test_sys, 'argv', ['scripts/check.py', '--json', str(output)]), redirect_stdout(console):
                    with self.assertRaises(SystemExit) as stopped:check.main()
                self.assertEqual(stopped.exception.code, int(mismatch))
                recorded = json.loads(output.read_text())
                self.assertEqual(len(recorded['differences']), int(mismatch))
                self.assertEqual([(item['year'], item['field']) for item in recorded['report']], [(2016, 'portfolio')])
                self.assertIn('frozen report (informational): 1 differences', console.getvalue())
                self.assertEqual(report.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
