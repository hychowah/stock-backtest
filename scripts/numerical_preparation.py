"""Closed candidate preparation, independent of application calculation routing.

The caller owns source before importing this module and through close(). A
successful report describes a verified, CLOSED runtime, never an admission
capability. Status uses fresh inventories; a saved report cannot prove freshness.
No dependency installation or market-data request occurs here.
"""
from copy import deepcopy
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
from threading import Lock
import uuid

import backtest_control
import baseline
import cache_access
from cache_assets import write_json
import diagnostics
import research
import schedules

PINS = {'numpy': '2.5.4', 'numba': '0.68.0', 'llvmlite': '0.50.0'}
DEFAULT_PROFILE='numba_compiled'
PROFILES=(DEFAULT_PROFILE,)
_dependency_warning = None
_dependency_warning_lock = Lock()
_metrics_lock=Lock()
_metrics=dict(environment_checks=0)


def measurements():
    """Process-local dependency diagnostics; never part of readiness identity."""
    with _metrics_lock:return dict(_metrics)


MESSAGES = {
    'dependencies unavailable': 'Candidate dependencies are unavailable. Follow docs/candidate-startup.md; setup is a separate offline operation.',
    'saved inputs need repair': 'Saved inputs need repair. Use the data panel or restore verified files.',
    'publication needs recovery': 'Publication needs recovery. Retry preparation; preserve its journal.',
    'preparation failed': 'Candidate preparation failed. Stored results remain available. Check the development log and retry.',
    'closure unconfirmed': 'Candidate closure is unconfirmed. Keep this owner and retry close before continuing.',
}


class PreparationError(ValueError):
    def __init__(self, category):
        self.category = category
        super().__init__(MESSAGES[category])


def dependencies(profile=DEFAULT_PROFILE):
    """Inspect installed metadata without importing the native stack or networking."""
    if profile not in PROFILES:raise ValueError('Unsupported internal preparation profile.')
    with _metrics_lock:_metrics['environment_checks']+=1
    global _dependency_warning
    implementation = platform.python_implementation()
    python = platform.python_version()
    supported = implementation == 'CPython' and sys.version_info[:2] in ((3, 12), (3, 14))
    versions = {}
    for name in PINS:
        try: versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError: versions[name] = None
    problems = [f'{name} is missing (required {expected})' if versions[name] is None
                else f'{name} has version {versions[name]} (required {expected})'
                for name, expected in PINS.items() if versions[name] != expected]
    if not supported:
        problems.append(f'{implementation} {python} is unsupported (required CPython 3.12 or 3.14)')
    with _dependency_warning_lock:
        if problems:
            signature = (implementation, python, sys.executable, tuple(versions.items()))
            if signature != _dependency_warning:
                diagnostics.warning('candidate.dependencies_unavailable',
                                    interpreter=sys.executable, implementation=implementation,
                                    python=python, required=PINS, installed=versions,
                                    supported_python=supported)
                print('WARNING: Experimental engine dependencies are unavailable: '
                      + '; '.join(problems) + '. Python interpreter: '
                      + json.dumps(sys.executable) + '. Install requirements-numerical.txt '
                      'in this environment, then select Prepare experimental engine in Manage backtest data. '
                      'Original and stored results remain available.', file=sys.stderr, flush=True)
                _dependency_warning = signature
        else:
            _dependency_warning = None
    if problems: raise PreparationError('dependencies unavailable')
    return dict(python=python,packages=versions,profile=profile,rust_required=False)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class Preparation:
    def __init__(self, root, *, python=None, profile=DEFAULT_PROFILE):
        self.root = Path(root).absolute()
        if self.root != Path(research.ROOT).absolute():
            raise ValueError('Candidate root must match the loaded application source. Use a new source-owned process.')
        self.python = str(python or sys.executable)  # Preserve the venv entry path.
        if profile not in PROFILES:raise ValueError('Unsupported internal preparation profile.')
        self.profile=profile
        self.path = self.root / 'data' / 'numerical-preparation.json'
        self.gate = cache_access.WorkspaceAccess(self.path.with_suffix('.lock'))
        self.runtime = None
        self.last_closure = None

    def common_inventory(self):
        """Equivalent path/size/mtime checks, plus report/source/pointer content."""
        sources = {}
        for folder in ('scripts', 'website', 'tools'):
            for path in sorted((self.root / folder).glob('*.py')):
                sources[path.relative_to(self.root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        pins = self.root / 'requirements-numerical.txt'
        sources[pins.name] = hashlib.sha256(pins.read_bytes()).hexdigest()
        pointer = self.root / 'data' / 'numerical' / 'current.json'
        return _digest(dict(inputs=research.signature(), prices=research.price_sources(),
            report=hashlib.sha256((research.RESULTS / 'summary-exits.txt').read_bytes()).hexdigest(),
            sources=sources,
            pointer=json.loads(pointer.read_bytes()) if pointer.exists() else None))

    def inventory(self):
        """Selected compiled-provider readiness over the complete common inventory."""
        return _digest(dict(common=self.common_inventory(),profile=self.profile,
            dependencies=dict(rust_required=False)))

    def status(self):
        """Small detached status; missing dependencies do not prevent this read."""
        if self.runtime is not None:
            return dict(state='unavailable',category='closure unconfirmed')
        ownership=cache_access.access(timeout=0)
        try:ownership.__enter__()
        except ValueError:
            return dict(state='unavailable',category='preparation failed',busy=True)
        try:
            try:installed=dependencies(self.profile)
            except PreparationError:return dict(state='unavailable',category='dependencies unavailable')
            report = json.loads(self.path.read_bytes())
            if not isinstance(report,dict) or report.get('state') not in ('current','stale','failed'):
                raise ValueError('Invalid candidate preparation report.')
            if report.get('state') != 'current': return deepcopy(report)
            if report.get('profile')!=self.profile or report.get('dependencies')!=installed:
                return dict(state='unavailable',category='dependencies unavailable',profile=self.profile)
            provider=report['runtime']['provider']
            if provider.get('backend')!='numba' or provider.get('candidate_assembly')!='compiled':
                raise ValueError('Compiled preparation provider differs.')
            if not all(provider.get('nopython_signatures',{}).get(name) for name in ('reports','prices','factors','decisions','materialize')):
                raise ValueError('Compiled preparation has no genuine kernel evidence.')
            if any((self.root / 'data' / name).exists() for name in
                   ('deployment.pending.json', 'research.sqlite.publication.json')):
                return dict(state='stale', category='publication needs recovery')
            if (self.root / 'data' / 'numerical' / 'publication.json').exists():
                return dict(state='stale', category='publication needs recovery')
            if report.get('inventory') != self.inventory():
                return dict(state='stale', category='saved inputs need repair')
            return deepcopy(report)
        except (OSError, ValueError, RuntimeError, KeyError, ImportError):
            return dict(state='unavailable', category='preparation failed')
        finally:ownership.__exit__(None,None,None)

    def invalidate(self):
        """Called inside coordinated mutation ownership, including partial writes."""
        write_json(self.path, dict(state='stale', category='saved inputs need repair'))

    def _store(self):
        from numerical_generation import GenerationStore
        return GenerationStore(schedules, self.root / 'data' / 'numerical')

    def _runtime(self):
        from numerical_runtime import NumericalRuntime
        return NumericalRuntime(source_root=self.root,
            scratch=self.root / 'tmp' / ('candidate-runtime-' + uuid.uuid4().hex),
            python=self.python, coordinator=cache_access.workspace,preparation_profile=self.profile,
            session_options=dict(execution=dict(backend=self.profile)))

    def prepare(self, progress=lambda **kw: None, cancelled=lambda: False):
        """Recover, prepare, publish, attach/prewarm, CLOSE, verify and build."""
        def check():
            backtest_control.checkpoint()
            if cancelled(): raise backtest_control.Cancelled()
        def stage(name):
            check(); progress(message=name)
        category = 'preparation failed'
        with self.gate.hold(timeout=120):
            try:
                self.close()
                stage('Checking candidate dependencies (offline)…')
                installed = dependencies(self.profile)
                with cache_access.access():
                    self.invalidate()
                    category = 'publication needs recovery'
                    stage('Recovering verified January publication…')
                    baseline.Baseline(research.RESULTS, research.DATABASE).recover()
                    category = 'saved inputs need repair'
                    from data_manager import source_problem
                    if source_problem(): raise PreparationError(category)
                    stage('Preparing January and custom-date databases…')
                    schedules.prepare()
                    category = 'publication needs recovery'
                    stage('Publishing numerical inputs…')
                    generation = self._store().prepare(check)
                    expected = self.inventory()
                category = 'preparation failed'
                stage('Attaching and prewarming candidate runtime…')
                self.runtime = self._runtime()
                try:
                    self.runtime.start(cancelled=cancelled)
                    verification=self.runtime.calculate('__prepare__', {}, cancelled=cancelled)
                    if (not isinstance(verification,dict) or verification.get('verified') is not True
                            or verification.get('profile')!=self.profile):
                        raise PreparationError('preparation failed')
                    runtime_stats = deepcopy(self.runtime.last_stats)
                    if runtime_stats.get('generation') != generation['identity']:
                        raise PreparationError('saved inputs need repair')
                finally:
                    self.close()
                # The child no longer owns financial access. Ordinary owners
                # cannot start until this closure proof and build have finished.
                with cache_access.access():
                    stage('Verifying current inputs and website…')
                    if self.inventory() != expected: raise PreparationError('saved inputs need repair')
                    from build_state import current_build
                    if not current_build():
                        stage('Rebuilding the website…')
                        subprocess.run([self.python, '-X', 'utf8', str(self.root / 'website' / 'build.py'),
                                        '--cache-owned'], cwd=self.root, check=True,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    check()
                    if self.inventory() != expected: raise PreparationError('saved inputs need repair')
                    report = dict(state='current', profile=self.profile,inventory=expected, generation=generation,
                                  dependencies=installed, runtime=runtime_stats, closure=self.last_closure)
                    write_json(self.path, report)
                    return deepcopy(report)
            except BaseException as error:
                # ClosureError keeps the strong retryable runtime. It must not
                # be downgraded into an ordinary panel recovery condition.
                from numerical_runtime import ClosureError
                if isinstance(error, ClosureError): raise
                self.close()
                diagnostics.failure('candidate.preparation_failed', error)
                if isinstance(error, (KeyboardInterrupt, backtest_control.Cancelled)): raise
                if isinstance(error, PreparationError): category = error.category
                with cache_access.access():
                    write_json(self.path, dict(state='failed', category=category))
                raise PreparationError(category) from None

    def close(self):
        """Never discard an uncertain owner or infer closure from a message."""
        if self.runtime is None: return
        self.runtime.close()
        self.last_closure = deepcopy(self.runtime.closure())
        self.runtime = None
