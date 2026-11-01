"""Documented command entry for tools.experiments.probe_list."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.experiments.probe_list import main

if __name__ == "__main__":
    main()
