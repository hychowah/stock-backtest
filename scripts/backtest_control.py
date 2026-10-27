"""Request-local cooperative cancellation; standalone calculations run normally."""
from contextlib import contextmanager
from contextvars import ContextVar

_cancelled = ContextVar('backtest_cancelled', default=None)


class Cancelled(Exception):
    """The caller no longer needs this calculation."""


def checkpoint():
    cancelled = _cancelled.get()
    if cancelled is not None and cancelled():
        raise Cancelled()


@contextmanager
def cancel_when(cancelled):
    token = _cancelled.set(cancelled)
    try:
        checkpoint()
        yield
    finally:
        _cancelled.reset(token)
