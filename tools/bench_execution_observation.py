"""Current request evidence; capture receipts supply expectations only.

Coordinated observations require the participating cache-access source. This
module offers no runtime discovery, admission flag or real execution command.
Blocking OS calls remain outside the cooperative handoff guarantee.
"""
from contextlib import ExitStack
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

from bench_comparison import ComparisonError
from bench_generation import signature, metadata, file_hash


class CurrentObservation:
    """Observe the current coordinated input set for one request.

    Compare it with the captured generation, close all observation handles, and
    release live ownership before calculation. Historical receipts do not
    establish current freshness. Cooperative yielding is not zero-delay access.
    """
    def __init__(self, request, schedules, *, cancel=lambda: False, seconds=5.):
        self.request, self.s = request, schedules
        self.root = Path(request['observation_root'])
        self.coordinated = request.get('observation_mode', 'fixture') == 'coordinated'
        self.cancel, self.seconds = cancel, seconds

    def _coordinator(self):
        import cache_access
        import runtime_access
        # Bind actual code, not an attribute/marker asserted by the target root.
        for module, name in ((cache_access, 'scripts/cache_access.py'),
                             (runtime_access, 'website/runtime_access.py')):
            expected = self.request['sources'].get(name)
            if (not expected or file_hash(module.__file__) != expected
                    or file_hash(self.root / name) != expected):
                raise ComparisonError('unsupported')
        if cache_access.OBSERVATION_PROTOCOL != 1:
            raise ComparisonError('unsupported')
        return cache_access.WorkspaceAccess(self.root / 'data/website-data-0.lock'), runtime_access

    def live_pending(self):
        if not self.coordinated:
            return False
        access, _ = self._coordinator()
        return access.live_pending()

    def current(self):
        started = time.monotonic()
        def check():
            if self.cancel(): raise ComparisonError('cancelled')
            if time.monotonic() - started > self.seconds: raise ComparisonError('limit')
        try:
            with ExitStack() as scope:
                checkpoint = check
                if self.coordinated:
                    access, runtime = self._coordinator()
                    scope.enter_context(runtime.ownership(self.root, timeout=0))
                    conflict = scope.enter_context(access.observe())
                    def checkpoint():
                        check(); conflict()
                checkpoint()
                observed = self._read(checkpoint)
                checkpoint()
            # No source/cache ownership or SQLite connection escapes this call.
            return observed
        except ComparisonError:
            raise
        except (FileNotFoundError, KeyError):
            raise ComparisonError('stale') from None
        except sqlite3.Error as error:
            code = getattr(error, 'sqlite_errorcode', 0) & 255
            raise ComparisonError('busy' if code in (5, 6) else 'stale') from None
        except (ValueError, RuntimeError):
            raise ComparisonError('busy') from None

    def _read(self, checkpoint):
        root, request = self.root, self.request
        def journals():
            checkpoint()
            for journal in ('deployment.pending.json', 'research.sqlite.publication.json'):
                if (root / 'data' / journal).exists(): raise ComparisonError('stale')
        journals()
        names = ('baseline', 'metrics', 'books', 'cache_assets', 'run', 'revalue', 'financial_inputs')
        modules = {name: SimpleNamespace(__file__=str(root / 'scripts' / (name + '.py'))) for name in names}
        modules['baseline'].cutoff = self.s.r.baseline.cutoff
        observed = signature(SimpleNamespace(ROOT=root, RAW=root / 'raw', RESULTS=root / 'results',
            __file__=str(root / 'scripts/research.py'), **modules), checkpoint)
        for relative, expected in request['sources'].items():
            checkpoint()
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or file_hash(path, checkpoint) != expected:
                raise ComparisonError('stale')
        expected = request['captured_freshness']
        research = metadata(root / 'data/research.sqlite', checkpoint)
        daily = metadata(root / 'data/schedules.sqlite', checkpoint)
        engine = {}
        for name in ('schedules.py', 'book_batch.py'):
            checkpoint(); info = (root / 'scripts' / name).stat()
            engine[name] = [info.st_size, info.st_mtime_ns]
        report = file_hash(root / 'results/summary-exits.txt', checkpoint)
        if (observed != expected['inputs'] or research != request['captured_metadata']['research']
                or daily.get('daily_inputs') != expected['daily_inputs']
                or daily['daily_inputs'].get('engine') != engine
                or research.get('inputs') != observed or report != research.get('baseline_report_sha')):
            raise ComparisonError('stale')
        journals()
        return observed
