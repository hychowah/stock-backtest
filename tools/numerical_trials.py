"""Compatibility alias for the source-owned numerical_random module."""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).absolute().parents[1]/'scripts'))
import numerical_random as _implementation
sys.modules[__name__] = _implementation
