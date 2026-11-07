"""Publish one Git commit to the registered native Windows workspace.

The WSL checkout owns source history. Windows owns data and its verified report.
Publication stops authenticated servers, owns source exclusively, then owns the
financial cache. An unfinished journal blocks startup and is completed on retry.
Only manifest-owned source can be replaced or deleted. No working-tree bytes,
credentials, raw assets, databases or environments enter ordinary deployment.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import time
import uuid
from datetime import datetime, timedelta, timezone

# Extracted native helpers use explicit stage/target paths until support is bound.
ROOT = (None if '--native-publish' in sys.argv else Path(__file__).resolve().parents[2])
_SUPPORT_ROOT = ROOT
# The frozen January report. Only the development check reads it, on the bench.
# The runtime keeps its own copy, which deployment never installs, replaces or
# removes.
REPORT = 'results/summary-exits.txt'
MANIFEST = 'data/deployment.json'
PENDING = 'data/deployment.pending.json'
CONFIG = 'data/workspace.json'
UPDATE_POLL_SECONDS = 2
UPDATE_HOUR = 7
HONG_KONG = timezone(timedelta(hours=8), 'Hong Kong')
SUPERVISOR_ENV = 'EBITDA_WEB_SUPERVISOR'
REFRESH_ENV = 'EBITDA_WEB_REFRESH'


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def source_path(name):
    """Validate a portable source path before applying ownership policy."""
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        raise ValueError('Invalid deployment path.')
    parts = PurePosixPath(name).parts
    if name.startswith('/') or any(p in ('.', '..') for p in parts) or '/'.join(parts) != name:
        raise ValueError('Invalid deployment path.')
    return name


def managed(name):
    name = source_path(name)
    canonical = name.casefold()
    parts = PurePosixPath(name).parts
    if any(p.lower() in ('.git', '.git-local', '.venv', '__pycache__', 'node_modules') for p in parts):
        return False
    if parts[0].casefold() in ('tmp', '.deployment') or canonical == REPORT:
        return False
    if parts[0].casefold() in ('raw', 'data'):
        return canonical in ('raw/readme.md', 'raw/archive/readme.md', 'data/readme.md')
    if canonical.startswith(('website/local/', 'website/.openai/', 'results/baseline-history/')):
        return False
    if parts[-1].casefold() == 'fmp_api_key' or (parts[-1].casefold().startswith('.env') and parts[-1].casefold() != '.env.example'):
        return False
    return True


def target_path(root, name):
    root = Path(root).resolve()
    path = root / source_path(name)
    # Reject junction/symlink escapes and source-file links before reading them.
    if not path.resolve().is_relative_to(root):
        raise ValueError('A deployment path escapes the runtime workspace.')
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink() or getattr(parent, 'is_junction', lambda: False)():
            raise ValueError('A deployment source path must not contain links or junctions.')
    return path


def replace(source, target):
    """Bounded Windows sharing-lock retries, without changing the source bytes."""
    for attempt in range(8):
        try:
            os.replace(source, target)
            return
        except OSError as error:
            transient = isinstance(error, PermissionError) or getattr(error, 'winerror', None) in (5, 32, 33)
            if not transient or attempt == 7:
                raise
            time.sleep(.01 * 2 ** attempt)


def atomic_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path, value):
    atomic_bytes(path, (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def validate_manifest(value):
    if (not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1
            or not isinstance(value.get('commit'), str) or not re.fullmatch(r'[0-9a-f]{40}', value['commit'])):
        raise ValueError('Invalid deployment manifest.')
    if not isinstance(value.get('files'), dict):
        raise ValueError('Invalid deployment inventory.')
    folded = set()
    for name, sha in value['files'].items():
        if not managed(name) or not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha):
            raise ValueError('Invalid deployment source ownership.')
        if name.casefold() in folded:
            raise ValueError('Deployment paths collide on Windows.')
        folded.add(name.casefold())
    return value


def unpack(stage):
    """Read a Git archive as plain files; never extract links or special paths."""
    stage = Path(stage)
    request = read_json(stage / 'request.json')
    if digest(stage / 'source.tar') != request['archive_sha256']:
        raise ValueError('The source archive changed during transfer.')
    payload = stage / 'payload'
    payload.mkdir(exist_ok=True)
    hashes = {}
    seen = set()
    with tarfile.open(stage / 'source.tar') as archive:
        for entry in archive:
            if entry.isdir():
                continue
            name = source_path(entry.name)
            if not entry.isfile():
                raise ValueError('Deployment accepts plain Git files only.')
            if name.casefold() in seen:
                raise ValueError('Deployment paths collide on Windows.')
            seen.add(name.casefold())
            if not managed(name):
                continue
            destination = target_path(payload, name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(entry) as source, destination.open('wb') as output:
                shutil.copyfileobj(source, output)
            hashes[name] = digest(destination)
    manifest = dict(version=1, commit=request['commit'], files=hashes,
                    source=request['source'], distro=request['distro'])
    return payload, validate_manifest(manifest)


def support(path):
    global _SUPPORT_ROOT
    _SUPPORT_ROOT = Path(path).resolve()
    sys.path.insert(0, str(_SUPPORT_ROOT))


def support_module(name):
    """Load canonical support only from the explicitly selected source tree."""
    import importlib
    module = importlib.import_module(name)
    expected = _SUPPORT_ROOT.joinpath(*name.split('.')).with_suffix('.py')
    if Path(module.__file__).resolve() != expected.resolve():
        raise ValueError('Deployment support came from a different source tree.')
    return module


def stop_servers(root):
    """Stop only token-authenticated instances belonging to this exact root."""
    launcher = support_module('website.server.launcher')
    root = Path(root).resolve()
    for path in sorted((root / 'data').glob('website-server-*.json')):
        state = read_json(path)
        if not isinstance(state, dict):
            raise ValueError('Invalid runtime identity; inspect the runtime terminal.')
        try:
            health = launcher.request(state, '/api/launcher')
        except (OSError, ValueError, KeyError):
            # A dead PID is safe; an unreachable live process is not proof of exit.
            launcher.wait_legacy_process(state.get('pid'), timeout=.1)
            continue
        same = os.path.normcase(str(root)) == os.path.normcase(str(Path(health.get('project', '')).resolve()))
        if not same or health.get('token') != state.get('token') or health.get('pid') != state.get('pid'):
            raise ValueError('A recorded listener cannot be authenticated as this runtime.')
        launcher.request(state, '/api/launcher', 'POST')
        # Waiting for process exit covers listeners, request threads and the
        # source reader lock. Do not interpret a stopped endpoint as cleanup.
        launcher.wait_legacy_process(state['pid'])


@contextmanager
def cache_ownership(root):
    cache_access = support_module('backtest.runtime.cache_access')
    with cache_access.WorkspaceAccess(Path(root) / 'data' / 'website-data-0.lock').hold():
        yield


def verify_payload(payload, manifest):
    for name, sha in manifest['files'].items():
        if digest(target_path(payload, name)) != sha:
            raise ValueError('A staged source file failed verification.')


def install_file(source, destination):
    if destination.is_file() and digest(destination) == digest(source):
        return  # Preserve timestamps used by prepared-cache freshness checks.
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.deploy-' + uuid.uuid4().hex)
    try:
        shutil.copy2(source, temporary)
        replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def apply_pending(root):
    """Idempotently finish a verified publication while exclusive locks are held."""
    root = Path(root)
    journal = read_json(root / PENDING)
    if not journal:
        return
    manifest = validate_manifest(journal['manifest'])
    old = validate_manifest(journal['previous']) if journal['previous'] else {'files': {}}
    relative = source_path(journal['payload'])
    if not relative.startswith('.deployment/'):
        raise ValueError('Invalid publication staging location.')
    payload = target_path(root, relative)
    verify_payload(payload, manifest)
    # Recovery permits only the old and new known generations, never local edits.
    for name in old['files'].keys() | manifest['files'].keys():
        destination = target_path(root, name)
        if destination.exists() and (not destination.is_file() or digest(destination) not in (old['files'].get(name), manifest['files'].get(name))):
            raise ValueError('Installed source changed outside deployment; existing files were kept.')
    for name in manifest['files']:
        install_file(target_path(payload, name), target_path(root, name))
    for name in old['files'].keys() - manifest['files'].keys():
        target_path(root, name).unlink(missing_ok=True)
    verify_payload(root, manifest)
    write_json(root / MANIFEST, manifest)
    (root / PENDING).unlink()


def publish(root, payload, manifest):
    """Publish source under exclusive runtime then financial-cache ownership."""
    root, payload = Path(root).resolve(), Path(payload).resolve()
    manifest = validate_manifest(manifest)
    if (root / '.git').exists() or (root / '.git-local').exists():
        raise ValueError('The runtime target must not be a source repository.')
    if not payload.is_relative_to(root / '.deployment'):
        raise ValueError('Stage the payload inside the runtime deployment directory.')
    verify_payload(payload, manifest)
    runtime_access = support_module('website.runtime_access')
    stop_servers(root)
    with runtime_access.ownership(root, exclusive=True, allow_pending=True), cache_ownership(root):
        apply_pending(root)
        previous = read_json(root / MANIFEST)
        if previous:
            validate_manifest(previous)
        owned = previous['files'] if previous else {}
        old_names = {name.casefold(): name for name in owned}
        if any(name.casefold() in old_names and old_names[name.casefold()] != name for name in manifest['files']):
            raise ValueError('Deploy a case-only source rename through an intermediate committed name.')
        # Validate every collision before creating a pending transaction.
        for name in owned.keys() | manifest['files'].keys():
            destination = target_path(root, name)
            if name in owned:
                if not destination.is_file() or digest(destination) != owned[name]:
                    raise ValueError('Installed source was edited outside Git; deployment stopped.')
            elif destination.exists() and (not destination.is_file() or digest(destination) != manifest['files'][name]):
                raise ValueError('An unowned runtime file conflicts with source; deployment stopped.')
        journal = dict(manifest=manifest, previous=previous,
                       payload=payload.relative_to(root).as_posix())
        write_json(root / PENDING, journal)
        apply_pending(root)
    return manifest


def git_command(*arguments):
    return ['/usr/bin/git', '--git-dir=' + str(ROOT / '.git-local'), '--work-tree=' + str(ROOT), *arguments]


def git(*arguments):
    return subprocess.check_output(git_command(*arguments))


def windows_path(path):
    return subprocess.check_output(['wslpath', '-w', str(path)], text=True).strip()


def linux_path(path):
    return Path(subprocess.check_output(['wslpath', '-u', str(path)], text=True).strip())


def configuration():
    config = read_json(ROOT / CONFIG)
    if not isinstance(config, dict) or config.get('source') != str(ROOT):
        raise ValueError('Configure data/workspace.json for this WSL checkout first; see docs/workspaces.md.')
    return config


def native(config, *arguments):
    executable = linux_path(config['python'])
    return subprocess.run([str(executable), '-X', 'utf8', '-B', *arguments], cwd=linux_path(config['runtime']), check=True)


def main_revision():
    """Read the committed main tip; unavailable Git never means an update."""
    try:
        commit = subprocess.check_output(git_command('rev-parse', '--verify', '--end-of-options',
                            'refs/heads/main^{commit}'), stderr=subprocess.DEVNULL, timeout=5).decode().strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return commit if re.fullmatch(r'[0-9a-f]{40}', commit) else None


def install_latest(config, commit, *, before_publish=None):
    """Finish recorded publication intent before selecting the newer main tip."""
    if (linux_path(config['runtime']) / PENDING).exists():
        recorded = deployment_revision(config)
        deploy(config, before_publish=before_publish)
        if recorded == commit:
            return
    deploy(config, commit, before_publish=before_publish)


def spawn_server(config, arguments, supervisor):
    """Keep native output in this terminal; mark only this controller's child."""
    # Older main revisions ignore the maintenance environment instead of
    # rejecting a new command-line flag when main is deliberately moved back.
    env = dict(os.environ, **{SUPERVISOR_ENV: supervisor,
                             REFRESH_ENV:'1' if '--refresh-data' in arguments else '0'})
    arguments=[argument for argument in arguments if argument!='--refresh-data']
    # WSL forwards custom variables to Windows only when WSLENV names them.
    shared = [part for part in env.get('WSLENV', '').split(':') if part]
    for name in (SUPERVISOR_ENV,REFRESH_ENV):
        if not any(part.split('/')[0].upper() == name for part in shared):shared.append(name)
    env['WSLENV'] = ':'.join(shared)
    return subprocess.Popen([str(linux_path(config['python'])), '-X', 'utf8', '-B',
                             config['runtime'] + '/website/serve.py', '--managed', *arguments],
                            cwd=linux_path(config['runtime']),
                            env=env)


def request_child_stop(config, supervisor):
    marker = linux_path(config['runtime']) / 'data' / ('website-update-stop-' + supervisor)
    atomic_bytes(marker, b'stop\n')
    return marker


def stop_child(config, child, supervisor):
    """Ask this child to stop, including while it is still preparing to bind.

    The native entry observes its unique marker and performs ordinary Ctrl+C
    cleanup. Never kill a process or release ownership on a wait timeout.
    """
    marker = linux_path(config['runtime']) / 'data' / ('website-update-stop-' + supervisor)
    if child.poll() is None:
        request_child_stop(config, supervisor)
        child.wait(timeout=30)
    marker.unlink(missing_ok=True)


def verify_installed(config):
    native(config, config['runtime'] + '/tools/deploy.py', '--native-check')
    local = str(linux_path(config['runtime']) / 'website/local')
    subprocess.run(['node', str(ROOT / 'tests/check-range.cjs'), local], check=True, cwd=ROOT)


def say(message, *, error=False):
    """Print one line that starts with the local time, like the server's terminal lines."""
    print(time.strftime('%Y-%m-%d %H:%M:%S ') + message, file=sys.stderr if error else sys.stdout, flush=True)


def next_update_time(now):
    """The first 07:00 Hong Kong time after now, without a catch-up launch."""
    if now.tzinfo is not None:now=now.astimezone(HONG_KONG)
    due = now.replace(hour=UPDATE_HOUR, minute=0, second=0, microsecond=0)
    return due if due > now else due + timedelta(days=1)


def starting_commit(config, latest):
    """Choose the revision a launch serves.

    A plain launch serves the installed revision, so a restart never rebuilds
    data for a newer commit. A recorded journal is finished first. Only
    `latest`, or a runtime with nothing installed, installs the main tip.
    """
    runtime = linux_path(config['runtime'])
    if not latest:
        if (runtime / PENDING).exists():
            deploy(config)
        if (runtime / MANIFEST).exists():
            return deployment_revision(config)
    commit = main_revision()
    if commit is None:
        raise ValueError('Cannot read committed main. Check the source Git history and retry the launcher.')
    install_latest(config, commit)
    return commit


def follow_main(config, arguments, *, check=False, latest=False):
    """Update source and refresh inputs once a day at 07:00 Hong Kong time.

    A launch with `latest` installs the main tip first. Publication owns
    shutdown, worker cleanup and source/cache locks. A failed update retries its
    recorded journal before switching revisions. A child stopped outside an
    update ends this controller, so an older terminal cannot bring its server
    back. Cleanup targets this controller's identity only.
    """
    commit = starting_commit(config, latest)
    if check:
        verify_installed(config)
    supervisor = uuid.uuid4().hex
    due = next_update_time(datetime.now(HONG_KONG))
    say('Daily updates on: committed main and FMP data are checked at 07:00 Hong Kong time. Missed schedules wait until the next day. Ctrl+C stops this server.')
    child = spawn_server(config, arguments, supervisor)
    pending = None
    warned = None
    try:
        while True:
            if pending is None and child.poll() is not None:
                return child.returncode
            time.sleep(UPDATE_POLL_SECONDS)
            if pending is None:
                now = datetime.now(HONG_KONG)
                if now < due:
                    continue
                scheduled=due
                due=next_update_time(now)
                if now-scheduled>=timedelta(minutes=1):
                    say('Daily update was missed; waiting until the next 07:00 Hong Kong time.')
                    continue
                tip = main_revision()
                if child.poll() is not None:
                    return child.returncode
                pending = tip or commit
                say('Daily maintenance: checking source and refreshing FMP data before restarting the website.')
            try:
                if pending!=commit or (linux_path(config['runtime']) / PENDING).exists():
                    install_latest(config, pending, before_publish=lambda: stop_child(config, child, supervisor))
                stop_child(config, child, supervisor)
            except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                notice = (pending, type(error).__name__)
                if warned != notice:
                    say('Website update could not finish (' + notice[1] + '). Retrying automatically; publication recovery is retained.')
                    warned = notice
                continue
            commit, pending, warned = pending, None, None
            # The first launch opens the browser. Subsequent replacements keep
            # the terminal visible without opening another tab for every commit.
            restart_arguments = [*arguments]
            for flag in ('--no-browser','--refresh-data'):
                if flag not in restart_arguments:restart_arguments.append(flag)
            supervisor = uuid.uuid4().hex
            child = spawn_server(config, restart_arguments, supervisor)
    except KeyboardInterrupt:
        return 130
    finally:
        if child.poll() is None:
            stop_child(config, child, supervisor)


def deployment_revision(config, requested=None):
    """Resolve one committed publication revision before runtime changes.

    Ordinary publication retains the installed revision. An unfinished publication
    resumes its recorded commit. Explicit selection cannot replace a pending transaction.
    """
    if (not isinstance(config, dict) or config.get('source') != str(ROOT)
            or not isinstance(config.get('distro'), str) or not config['distro'].strip()
            or not isinstance(config.get('runtime'), str) or not config['runtime'].strip()):
        raise ValueError('Deployment registration does not identify this source and distro.')
    runtime = linux_path(config['runtime'])
    missing = object()

    def registered_manifest(value):
        value = validate_manifest(value)
        if any(value.get(field) != config[field] for field in ('source', 'distro')):
            raise ValueError('Deployment evidence does not match the source and distro registration.')
        return value

    installed = read_json(runtime / MANIFEST, missing)
    if installed is not missing:
        registered_manifest(installed)
    journal = read_json(runtime / PENDING, missing)
    pending = None
    if journal is not missing:
        if not isinstance(journal, dict) or not {'manifest', 'previous', 'payload'} <= journal.keys():
            raise ValueError('Invalid pending publication journal; retain it for recovery.')
        pending = registered_manifest(journal['manifest'])
        previous = journal['previous']
        if previous is not None:
            registered_manifest(previous)
        relative = source_path(journal['payload'])
        if not relative.startswith('.deployment/'):
            raise ValueError('Invalid publication staging location.')
        if installed is not missing and installed not in (previous, pending):
            raise ValueError('Installed evidence conflicts with the pending publication.')

    if requested is None:
        if pending is not None:
            requested = pending['commit']
        elif installed is not missing:
            requested = installed['commit']
        else:
            raise ValueError('A fresh runtime requires an explicit --revision <commit>.')
    if not isinstance(requested, str) or not requested:
        raise ValueError('An explicit revision must identify a committed revision.')
    commit = git('rev-parse', '--verify', '--end-of-options', requested + '^{commit}').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Git did not resolve an exact committed revision.')
    if pending is not None and commit != pending['commit']:
        raise ValueError('Explicit revision conflicts with pending publication; retry its recorded commit first.')
    return commit


def deploy(config, revision=None, *, before_publish=None):
    # A pending transaction owns publication intent until recovery finishes.
    # Resolve its commit before staging; native publication verifies and completes
    # its retained payload under the existing locks.
    commit = deployment_revision(config, revision)
    runtime = linux_path(config['runtime'])
    stage = runtime / '.deployment' / ('stage-' + uuid.uuid4().hex)
    stage.mkdir(parents=True)
    try:
        helper = git('show', commit + ':tools/deploy.py')
        (stage / 'bootstrap.py').write_bytes(helper)
        with (stage / 'source.tar').open('wb') as handle:
            subprocess.run(git_command('archive', '--format=tar', commit), stdout=handle, check=True)
        write_json(stage / 'request.json', dict(commit=commit, archive_sha256=digest(stage / 'source.tar'),
                   source=str(ROOT), distro=config['distro']))
        if before_publish is not None:
            before_publish()
        native(config, windows_path(stage / 'bootstrap.py'), '--native-publish', windows_path(stage), config['runtime'])
    except BaseException:
        # A native journal may refer to this payload. Retry must retain it.
        raise
    else:
        shutil.rmtree(stage)
    say('Deployed committed source ' + commit)
    say('Runtime: ' + config['runtime'])


def native_launch(arguments, revision=None, latest=False):
    config = read_json(ROOT / CONFIG)
    if config:
        selection = ['--revision', revision] if revision is not None else []
        if latest:
            selection.append('--latest')
        return subprocess.call(['wsl.exe', '-d', config['distro'], '--cd', config['source'],
                                '--exec', 'python3', 'tools/deploy.py', '--start', *selection, *arguments])
    if revision is not None:
        raise ValueError('Explicit revision selection requires a registered WSL source checkout.')
    return subprocess.call([sys.executable, str(ROOT / 'website/serve.py'), '--managed', *arguments])


def check_runtime():
    """Run saved-data and lifecycle checks against the installed Windows code."""
    support(ROOT)
    runtime_access = support_module('website.runtime_access')
    with runtime_access.ownership(ROOT):
        for name in ('test_deployment.py', 'test_launcher.py', 'test_startup.py',
                     'test_cache_access.py', 'check_paths.py'):
            subprocess.run([sys.executable, '-B', str(ROOT / 'tests' / name)], cwd=ROOT, check=True)
        subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/schedules.py'), 'prepare'], cwd=ROOT, check=True)
        subprocess.run([sys.executable, '-B', str(ROOT / 'website/build.py')], cwd=ROOT, check=True)
        subprocess.run([sys.executable, '-B', str(ROOT / 'tests/check_screener.py')], cwd=ROOT, check=True)


def main():
    if os.name == 'nt':
        # Match start.cmd and propagate UTF-8 to native test/build children.
        os.environ['PYTHONUTF8'] = '1'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', help='Select a committed revision; with --start, freeze this launch instead of following main')
    parser.add_argument('--start', action='store_true', help='Update committed main and FMP data daily at 07:00 Hong Kong time; --revision freezes the launch')
    parser.add_argument('--latest', action='store_true', help='With --start, install the latest committed main now instead of the installed revision')
    parser.add_argument('--check', action='store_true', help='Deploy, then check installed native Windows paths and lifecycle')
    parser.add_argument('--native-publish', nargs=2, help=argparse.SUPPRESS)
    parser.add_argument('--native-launch', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--native-check', action='store_true', help=argparse.SUPPRESS)
    options, server_arguments = parser.parse_known_args()
    try:
        if options.native_publish:
            stage, root = map(Path, options.native_publish)
            payload, manifest = unpack(stage)
            support(payload)
            publish(root, payload, manifest)
            say('Verified native source publication: ' + manifest['commit'])
        elif options.native_launch:
            raise SystemExit(native_launch(server_arguments, options.revision, options.latest))
        elif options.native_check:
            check_runtime()
        else:
            if os.name == 'nt':
                raise ValueError('Run deployment from the authoritative WSL source checkout.')
            config = configuration()
            if server_arguments and not options.start:
                parser.error('Server arguments require --start.')
            if options.latest and (not options.start or options.revision is not None):
                parser.error('--latest requires --start and cannot be combined with --revision.')
            if options.start and options.revision is None:
                raise SystemExit(follow_main(config, server_arguments, check=options.check, latest=options.latest))
            deploy(config, options.revision)
            if options.check:
                verify_installed(config)
            if options.start:
                native(config, config['runtime'] + '/website/serve.py', '--managed', *server_arguments)
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        say('Deployment stopped: ' + (str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__), error=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
