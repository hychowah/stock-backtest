"""Prepare immutable numerical inputs under source and financial ownership."""
import importlib.util
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('_backtest_source_owner',ROOT/'website'/'runtime_access.py')
owner=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=owner
spec.loader.exec_module(owner)
if __name__=='__main__':
    with owner.ownership(ROOT):
        sys.path.insert(0,str(ROOT))
        from backtest.engines.numerical.generation import main
        main()
