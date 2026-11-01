"""Compatibility alias for the shared source-derived numerical policy."""
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.engines.numerical.decisions import *
