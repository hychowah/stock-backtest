"""Compatibility alias for the source-owned numerical_numba module."""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).absolute().parents[1]/'scripts'))
import numerical_numba as _implementation
sys.modules[__name__] = _implementation
