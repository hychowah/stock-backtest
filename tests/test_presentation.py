"""Detached build data, one acquired connection and source-only recovery assets."""
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from website.rendering import data


class PageDataTests(unittest.TestCase):
    def test_one_connection_closes_before_detached_data_is_returned(self):
        with tempfile.TemporaryDirectory() as temporary,ExitStack() as context:
            website=Path(temporary)/'website';website.mkdir()
            results=website.parent/'results';results.mkdir()
            report=b'Through 2026-10-21\nyear,portfolio,spy,names\n2025,0.1,0.2,1\n'
            (results/'summary-exits.txt').write_bytes(report)
            db=Mock();stocks={2025:dict(holdings=[dict(market_cap=100e6,return_value=.1)])}
            context.enter_context(patch.object(data,'ROOT',website))
            acquired=context.enter_context(patch.object(data,'connect',return_value=db))
            holdings=context.enter_context(patch.object(data,'load_holdings',return_value=stocks))
            compact=context.enter_context(patch.object(data,'load_screening_data',return_value={'latest':{'metadata':{'asof':'2026-10-21'}}}))
            latest=context.enter_context(patch.object(data.screening,'latest',return_value=[]))
            page=data.load_page_data()
            acquired.assert_called_once_with();db.close.assert_called_once_with()
            holdings.assert_called_once_with(db);compact.assert_called_once_with(db);latest.assert_called_once_with(db)
            self.assertEqual(page.report_bytes,report)
            self.assertEqual(page.holdings[2025]['median_market_cap'],100e6)
            self.assertEqual(page.annual,[dict(year=2025,portfolio=.1,spy=.2)])

    def test_failed_projection_still_closes_its_connection(self):
        with tempfile.TemporaryDirectory() as temporary,ExitStack() as context:
            website=Path(temporary)/'website';website.mkdir()
            results=website.parent/'results';results.mkdir()
            (results/'summary-exits.txt').write_text('Through 2026-10-21\nyear,portfolio,spy,names\n2025,0.1,0.2,1\n')
            db=Mock()
            context.enter_context(patch.object(data,'ROOT',website))
            context.enter_context(patch.object(data,'connect',return_value=db))
            context.enter_context(patch.object(data,'load_holdings',side_effect=ValueError('invalid projection')))
            with self.assertRaisesRegex(ValueError,'invalid projection'):data.load_page_data()
            db.close.assert_called_once_with()

    def test_source_recovery_page_needs_no_inputs_credentials_or_numerical_imports(self):
        code="""import sys
sys.path.insert(0,sys.argv[1])
from website.rendering.assets import data_page
page=data_page()
assert '__DATA_STYLE__' not in page and '__DATA_SCRIPT__' not in page
assert 'Manage backtest data' in page
assert not any(name.split('.')[0] in ('backtest','numpy','numba','tools') for name in sys.modules)
"""
        subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT)],cwd=tempfile.gettempdir(),check=True)


if __name__=='__main__':unittest.main()
