"""Stable native entry point: own installed source before application imports."""
from pathlib import Path
from contextlib import contextmanager
import sys


@contextmanager
def _supervised_stop():
    """Translate this launch's stop marker into ordinary Ctrl+C cleanup.

    Start before preparation, so a new commit can also replace a server that
    has not bound its listener. Workers keep their existing shutdown protocol.
    """
    import _thread
    import os
    import re
    from threading import Event, Thread

    token=os.environ.get('EBITDA_WEB_SUPERVISOR','')
    if not re.fullmatch(r'[0-9a-f]{32}',token):
        yield;return
    marker=Path(__file__).resolve().parents[1]/'data'/('website-update-stop-'+token)
    done=Event()
    def poll():
        while not done.wait(.1):
            if marker.exists():
                _thread.interrupt_main()
                return
    thread=Thread(target=poll,name='website-update-stop',daemon=True)
    thread.start()
    try:yield
    finally:
        done.set();thread.join()


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
    try:
        with _supervised_stop():
            _source_owner = _own_source()
            try:
                sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
                import serve_app
                serve_app.main()
            finally:
                _source_owner.__exit__(None, None, None)
    except KeyboardInterrupt:
        pass
elif __name__ == '__mp_main__':
    # Spawned calculation workers keep their own reader until process exit.
    # This also protects their imports if the owning server is killed.
    import atexit
    _source_owner = _own_source()
    atexit.register(_source_owner.__exit__, None, None, None)
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    import serve_app
else:
    # Keep existing imports and unittest patch targets on the actual module.
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    import serve_app
    sys.modules[__name__] = serve_app
