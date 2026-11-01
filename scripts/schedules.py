"""Documented executable entry. Library code lives in backtest."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["prepare"])
    parser.parse_args()
    from backtest.inputs.daily import prepare
    prepare()
