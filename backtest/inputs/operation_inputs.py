"""Prepared inputs held unchanged for one Original scalar operation.

held() connects the daily cache; that connection checks the daily binding once
(the research record with its accepted raw-file signature and the book code)
and attaches the research database read-only for books, facts, sessions and
company names. It is the operation's one connection. Inside the context,
require_unchanged() is the between-step check. It costs one file-status read
and fails if the research database was rewritten or replaced since entry. The
caller holds cache ownership around held(), so no preparation or download can
write the inputs during the operation.
"""
from contextlib import contextmanager
import os

from backtest.inputs import daily, research

CHANGED = 'Scalar inputs changed during the operation.'


def _status(path):
    """Identify the file at path by device, inode, size and modification time."""
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return None
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


class HeldInputs:
    """The admitted daily connection and the operation's between-step check."""

    def __init__(self, db, checkpoint):
        self.db = db
        self._checkpoint = checkpoint
        self._research_status = _status(research.DATABASE)

    def require_unchanged(self):
        """Raise ValueError if the research database was rewritten or replaced since entry."""
        self._checkpoint()
        if _status(research.DATABASE) != self._research_status:
            raise ValueError(CHANGED)


@contextmanager
def held(*, checkpoint):
    """Yield HeldInputs for one operation and close its connection."""
    db = daily.connect()
    try:
        yield HeldInputs(db, checkpoint)
        checkpoint()
    finally:
        db.close()
