"""Prepared inputs held unchanged for one Original scalar operation.

held() connects the daily cache; that connection verifies the complete daily
fingerprint once (raw input metadata, research content and price binding, bound
engine source). Inside the context, require_unchanged() is the between-step
freshness check. It costs one file-status read, whatever the cache size, and
fails if the research database was rewritten or replaced since entry. A normal
exit computes the complete fingerprint once more and compares it with the
admitted one, so any change that fingerprint detects during the operation still
fails it before the caller seals a result. Leaving by an exception skips that
comparison and only closes connections.

The caller holds cache ownership around held(). research() opens at most one
read-only research connection, closed with the context.
"""
from contextlib import contextmanager
import json
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
        # daily.connect() has just proved that this stored binding equals fingerprint().
        self._accepted = json.loads(db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()[0])
        self._research_status = _status(research.DATABASE)
        self._research = None

    def research(self):
        """Return the operation's read-only research connection, opening it once."""
        if self._research is None:
            self._research = research.connect()
        return self._research

    def require_unchanged(self):
        """Raise ValueError if the research database was rewritten or replaced since entry."""
        self._checkpoint()
        if _status(research.DATABASE) != self._research_status:
            raise ValueError(CHANGED)


@contextmanager
def held(*, checkpoint):
    """Yield HeldInputs; compare the complete fingerprint again on normal exit."""
    db = daily.connect()
    inputs = None
    try:
        inputs = HeldInputs(db, checkpoint)
        yield inputs
        checkpoint()
        if daily.fingerprint() != inputs._accepted:
            raise ValueError(CHANGED)
    finally:
        if inputs is not None and inputs._research is not None:
            inputs._research.close()
        db.close()
