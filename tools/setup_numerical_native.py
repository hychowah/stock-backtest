"""Documented command entry for tools.ops.setup_numerical_native."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.ops.setup_numerical_native import main

if __name__ == "__main__":
    main()
