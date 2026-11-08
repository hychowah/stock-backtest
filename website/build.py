"""Build the standalone website from the latest book of the prepared daily cache."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backtest.runtime import cache_access
from website.rendering.state import LOCAL_OUTPUT, SNAPSHOT_OUTPUT
from website.rendering.build import build


def cli():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',action='store_true',help='Write an untracked portable website export to website/dist')
    args=parser.parse_args()
    with cache_access.access():
        build(SNAPSHOT_OUTPUT if args.snapshot else LOCAL_OUTPUT)


if __name__=='__main__':cli()
