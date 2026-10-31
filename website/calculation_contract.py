"""Execution identity and lifecycle shared by adapters, without job ownership.

Omitted request identity means Original. Historical result provenance must come
from stored producer evidence, never from this default. Closing admission is
separate from draining accepted work; the application owns that drain.
"""
from threading import Event, RLock
import backtest_control


class Busy(ValueError):
    pass


class Unavailable(ValueError):
    """No calculation began because admitted inputs are not ready."""


ENGINES={'original':'Original','experimental':'New engine — experimental'}


def engine_id(options):
    """Omitted request choice always means Original, never historical provenance."""
    if not isinstance(options,dict):raise ValueError('Expected backtest options.')
    value=options.get('engine','original')
    if not isinstance(value,str) or value not in ENGINES:raise ValueError('Choose Original or New engine — experimental.')
    return value


class Control:
    def __init__(self):
        self.ready=lambda:True
        self.lock=RLock()
        self.closed=Event()

    def close(self):
        with self.lock:self.closed.set()

    def _checkpoint(self):
        backtest_control.checkpoint()
        if self.closed.is_set():raise backtest_control.Cancelled()
