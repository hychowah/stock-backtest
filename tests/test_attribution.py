"""Check the no-JavaScript attribution fallback and its signed percentages."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'website'))
from attribution import render


class AttributionFallbackTests(unittest.TestCase):
    def test_mixed_returns_and_escaped_names(self):
        page = render([
            dict(symbol='A', name='A & <Company>', return_value=1.),
            dict(symbol='B', name='B', return_value=.5),
            dict(symbol='C', name='C', return_value=-.6),
        ], 2015)
        self.assertIn('Portfolio return<strong>+30.00%', page)
        self.assertIn('Top 3 contribution<strong>+30.00 pp', page)
        self.assertIn('Other 0 contribution<strong>+0.00 pp', page)
        self.assertIn('A &amp; &lt;Company&gt;', page)
        self.assertIn('66.7%', page)
        self.assertEqual(page.count('role="img"'), 2)
        self.assertNotIn('NaN', page)

    def test_empty_and_zero_returns(self):
        self.assertIn('No selected stocks', render([], 2015))
        page = render([dict(symbol='A', name='A', return_value=0)], 2015)
        self.assertIn('No gains this year', page)
        self.assertIn('No losses this year', page)
        self.assertNotIn('conic-gradient', page)

    def test_top_ten_and_all_losses(self):
        stocks = [dict(symbol=str(i).zfill(2), name=str(i), return_value=-(i+1)/10) for i in range(11)]
        page = render(stocks, 2026)
        self.assertIn('2026 return contributions · partial year', page)
        self.assertIn('Top 10 contributors · 10 stocks', page)
        self.assertIn('<td>00</td>', page)
        self.assertIn('<td>01</td>', page)
        self.assertNotIn('<td>10</td>', page)
        self.assertIn('No gains this year', page)


if __name__ == '__main__':
    unittest.main()
