"""Private spawned reader fixture; source ownership precedes app imports."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    reference_path, ready, stop, done = map(Path, sys.argv[2:6])
    if sys.argv[1] == 'parent':
        # A intentionally orphaned reader proves its own OS pin survives loss
        # of the spawning process. CB-19C must supply real parent monitoring.
        child = subprocess.Popen([sys.executable, '-B', __file__, 'reader',
                                  *sys.argv[2:6]], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 30
        while not ready.exists():
            if child.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Delegated child did not attach.')
            time.sleep(.02)
        os._exit(0)
    sys.path[:0] = [str(ROOT / 'website')]
    import runtime_access
    with runtime_access.ownership(ROOT):
        sys.path[:0] = [str(ROOT / 'scripts')]
        from unittest.mock import patch
        import schedules
        import numerical_generation as ng
        def forbidden(*args, **kwargs):
            raise AssertionError('Worker entered financial coordination or current-input preparation.')
        with patch.object(ng.cache_access.WorkspaceAccess, 'hold', forbidden), \
             patch.object(ng.GenerationStore, '_binding', forbidden), \
             patch.object(ng.GenerationStore, '_recover', forbidden), \
             patch.object(schedules, 'connect', forbidden), \
             patch.object(schedules.r, 'connect', forbidden):
            with ng.open_delegated(json.loads(reference_path.read_text()), schedules,
                                   checkpoint=lambda: None) as inputs:
                inputs.validate()
                ready.write_text(json.dumps(dict(pid=os.getpid(), identity=inputs.signature,
                    symbols=inputs.symbols, sample=inputs.raw_values.tolist())))
                while not stop.exists(): time.sleep(.02)
                inputs.validate()
            done.write_text('closed')


if __name__ == '__main__': main()
