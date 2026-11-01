"""Compatibility alias for the source-owned numerical_numba module."""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).absolute().parents[1]/'scripts'))
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.engines.numerical import numba as _implementation
sys.modules[__name__] = _implementation
