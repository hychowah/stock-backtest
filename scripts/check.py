"""Documented executable entry for the development check. Library code lives in backtest."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if __name__=="__main__":
    from backtest.engines.reference.check import main
    main()
