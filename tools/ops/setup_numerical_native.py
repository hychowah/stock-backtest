"""Comparison-only offline Rust installation; neither application engine uses it."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).absolute().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--components',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    args=parser.parse_args()
    from website import runtime_access
    with runtime_access.ownership(ROOT):
        from backtest.engines.numerical.toolchain import setup_toolchain, SetupClosureError
        import time
        try:value=setup_toolchain(ROOT,args.components,json.loads(args.manifest.read_bytes()))
        except SetupClosureError as error:
            while True:
                try:error.installation.close();break
                except (SetupClosureError,KeyboardInterrupt):
                    try:time.sleep(.05)
                    except KeyboardInterrupt:pass
            if error.primary_error is not None:raise error.primary_error
            raise
    print(json.dumps(dict(state='verified',signature=value['signature'],target=value['target'])))

if __name__=='__main__':main()
