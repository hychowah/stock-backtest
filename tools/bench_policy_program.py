"""Compatibility alias for the shared source-derived numerical policy."""
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))
from numerical_policy import *  # noqa: F401,F403
