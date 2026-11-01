"""Documented executable entry. Library code lives in backtest."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if __name__=="__main__":
    from backtest.inputs.research import prepare
    from backtest.paths import RESULTS
    prepare(force=True)
    print((RESULTS/"summary-exits.txt").read_text(encoding="utf-8"),flush=True)
