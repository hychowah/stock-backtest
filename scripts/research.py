"""Documented executable entry. Library code lives in backtest."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if __name__=="__main__":
    from backtest.inputs.research import main
    import sqlite3
    try:
        main()
    except (ValueError,sqlite3.Error) as error:
        raise SystemExit(str(error))
