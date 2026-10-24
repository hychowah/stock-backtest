"""Stable native entry point: own installed source before application imports."""
from pathlib import Path
import sys


def _own_source():
    from runtime_access import ownership
    owner = ownership(Path(__file__).resolve().parents[1])
    try:
        owner.__enter__()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
    except OSError as error:
        print('Cannot acquire source ownership (' + type(error).__name__ + '). Retry deployment.', file=sys.stderr)
        raise SystemExit(1) from None
    return owner


if __name__ == '__main__':
    _source_owner = _own_source()
    try:
        import serve_app
        serve_app.main()
    finally:
        _source_owner.__exit__(None, None, None)
elif __name__ == '__mp_main__':
    # Spawned calculation workers keep their own reader until process exit.
    # This also protects their imports if the owning server is killed.
    import atexit
    _source_owner = _own_source()
    atexit.register(_source_owner.__exit__, None, None, None)
    import serve_app
else:
    # Keep existing imports and unittest patch targets on the actual module.
    import serve_app
    sys.modules[__name__] = serve_app
