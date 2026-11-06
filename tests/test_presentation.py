"""Detached latest build data, one acquired connection and source-only recovery assets."""
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
        with ExitStack() as context:
            db=Mock();latest_stocks=[dict(symbol='A')]
            acquired=context.enter_context(patch.object(data,'connect',return_value=db))
            compact=context.enter_context(patch.object(data,'load_screening_data',return_value={'latest':{'metadata':{'asof':'2026-10-21'}}}))
            latest=context.enter_context(patch.object(data.screening,'latest',return_value=latest_stocks))
            page=data.load_page_data()
            acquired.assert_called_once_with();db.close.assert_called_once_with()
            compact.assert_called_once_with(db);latest.assert_called_once_with(db)
            self.assertEqual(page.latest_stocks,latest_stocks)

    def test_failed_projection_still_closes_its_connection(self):
        with ExitStack() as context:
            db=Mock()
            context.enter_context(patch.object(data,'connect',return_value=db))
            context.enter_context(patch.object(data,'load_screening_data',side_effect=ValueError('invalid projection')))
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
