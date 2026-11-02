"""Translate private native numerical entries through the installed audit guard.

This test bootstrap imports only the standard library. It never replaces or
calls the guard's raw predecessor. Real entry files retain source-before-import
ownership, arguments, environment, handles and containment. Qualification covers
their entry logic under translated launcher syntax, not literal script syntax.
"""
from pathlib import Path
import os
import subprocess
import sys


_ENTRIES = ('runtime_child.py', 'trial_worker.py')


def translated(command, source):
    """Return an exact-entry guarded-c command; reject other script entries."""
    if isinstance(command, (str, bytes)):
        raise ValueError('Private qualification requires an argument vector.')
    command = list(map(str, command))
    if not command or Path(command[0]).resolve() != Path(sys.executable).resolve():
        raise ValueError('Private qualification requires its Python interpreter.')
    if '-c' in command:
        return command
    source = Path(source).resolve()
    allowed = {str((source/'backtest/engines/numerical'/name).resolve()) for name in _ENTRIES}
    # Current production owners have exactly these isolation/bytecode flags.
    # Unexpected syntax must receive a new review rather than a permissive scan.
    if len(command) < 5 or command[1:3] != ['-I', '-B']:
        raise ValueError('Unrecognized private numerical entry command.')
    entry = Path(command[3]).resolve()
    if str(entry) not in allowed:
        raise ValueError('Unrecognized private numerical entry file.')
    helper = source/'tests/guarded_numerical_entries.py'
    code = (
        'import runpy,sys;'
        'runpy.run_path('+repr(str(helper))+",run_name='_private_numerical_entries')['install']("+repr(str(source))+');'
        'sys.argv[0]='+repr(str(entry))+';'
        'runpy.run_path('+repr(str(entry))+",run_name='__main__')"
    )
    # -I implies safe_path: literal file entry does not prepend its directory.
    # The isolated -c bootstrap has the same stdlib/site path. Adding the
    # numerical directory would shadow the stdlib random module before source.
    return [*command[:3], '-c', code, *command[4:]]


def install(source):
    """Keep the existing guard authoritative in this process and descendants."""
    current = subprocess.Popen
    if getattr(current, '_private_numerical_entries', False):
        return current
    if sys.platform != 'win32' or current.__name__ != 'GuardedPopen' or current.__module__ != '_private_native_guard':
        raise ValueError('Install only after the unchanged private native guard.')
    source = Path(source).resolve()
    private = source.parent
    if (source.name != 'source' or not private.name.startswith('cv-phase6-') or
            not (private/'control/guard.py').is_file()):
        raise ValueError('A guarded private export is required.')
    # Windows resolves NUL to a device outside the export. Keep the guard
    # unchanged by retaining discarded output in one exact private test sink.
    # This applies to Popen's DEVNULL and the worker's own native-output sink.
    # It does not redirect either JSON protocol stream or any financial asset.
    sink = private/'logs'/('native-discard-'+str(os.getpid())+'.bin')
    sink.touch(exist_ok=True)
    os.devnull = str(sink)

    class PrivateNumericalPopen(current):
        _private_numerical_entries = True

        def __init__(self, command, *args, **kwargs):
            # Delegate kwargs without interpretation: CREATE_SUSPENDED, parent
            # sentinels, process handles, pipe descriptors and env stay owned by
            # the real RuntimeProcess/TrialPool implementations.
            super().__init__(translated(command, source), *args, **kwargs)

    subprocess.Popen = PrivateNumericalPopen
    return PrivateNumericalPopen
