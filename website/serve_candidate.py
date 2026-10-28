"""Start candidate preparation in an explicitly isolated private source export."""
import argparse
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).absolute().parents[1]


def close_before_source_release(preparation, *, pause=time.sleep):
    """Repeated terminal interrupts cannot turn unknown closure into completion."""
    from numerical_runtime import ClosureError
    while True:
        try:
            try:
                preparation.close()
                return
            except ClosureError:
                print('Candidate closure is unconfirmed; retaining source ownership and retrying.',
                      file=sys.stderr, flush=True)
            pause(.25)
        except KeyboardInterrupt:
            continue


def private_root(value):
    root = Path(value).absolute()
    if root != ROOT or root.is_symlink():
        raise ValueError('Choose this isolated source export explicitly with --private-root.')
    if (root / '.git').exists() or (root / '.git-local').exists():
        raise ValueError('Candidate startup requires a private source export, separate from a source checkout.')
    if any((root / 'data' / name).exists() for name in
           ('workspace.json', 'deployment.json', 'deployment.pending.json')):
        raise ValueError('Candidate startup refuses registered or installed source roots.')
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-root', required=True)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    try:
        root = private_root(args.private_root)
        if not 0 <= args.port <= 65535 or args.port == 3000:
            raise ValueError('Use an ephemeral or explicit private port other than 3000.')
    except ValueError as error: parser.error(str(error))
    import runtime_access
    source = runtime_access.ownership(root)
    source.__enter__()
    preparation = None
    try:
        # Disable credentials before any application import. An explicit panel
        # download reports missing setup; candidate startup never downloads.
        sys.path.insert(0, str(root / 'scripts'))
        import run
        run.KEY_PATH = root / 'tmp' / ('candidate-no-credentials-' + uuid.uuid4().hex)
        if run.KEY_PATH.exists():raise RuntimeError('Candidate offline credential path is not empty.')
        from numerical_preparation import Preparation
        preparation = Preparation(root)
        import serve_app
        serve_app.main(candidate=preparation, arguments=['--host', '127.0.0.1', '--port', str(args.port),
            *(['--no-browser'] if args.no_browser else [])])
    finally:
        if preparation is not None:
            # Uncertain closure cannot release source or start a recovery
            # listener. Keep the strong owner and retry until exit is proved.
            close_before_source_release(preparation)
        source.__exit__(None, None, None)


if __name__ == '__main__': main()
