"""Compatibility alias for the source-owned process_owner module."""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).absolute().parents[1]/'scripts'))
import process_owner as _implementation
sys.modules[__name__] = _implementation
