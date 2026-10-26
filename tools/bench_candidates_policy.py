"""Compatibility alias for the shared source-derived numerical policy."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from numerical_decisions import *  # noqa: F401,F403
