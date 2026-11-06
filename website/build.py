"""Build the standalone website from the prepared research database."""
import argparse
import sys
from contextlib import nullcontext
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backtest.runtime import cache_access
from website.rendering.state import LOCAL_OUTPUT, SNAPSHOT_OUTPUT
from website.rendering.build import build


def cli():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',action='store_true',help='Write an untracked portable website export to website/dist')
    parser.add_argument('--cache-owned',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    with nullcontext() if args.cache_owned else cache_access.access():
        build(SNAPSHOT_OUTPUT if args.snapshot else LOCAL_OUTPUT)


if __name__=='__main__':cli()
