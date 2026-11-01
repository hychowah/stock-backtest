"""Stable deployment command and old-controller native-publication bootstrap."""
import hashlib
import json
from pathlib import Path
import runpy
import sys
import tarfile
import uuid

HELPER_MEMBER = 'tools/ops/deploy.py'
MAX_HELPER_BYTES = 1024 * 1024


def native_bootstrap(arguments):
    """Run only the request-bound operations helper from the selected archive."""
    if len(arguments) != 3 or arguments[0] != '--native-publish':
        raise ValueError('Invalid native publication arguments.')
    stage = Path(arguments[1]).resolve()
    request = json.loads((stage / 'request.json').read_bytes())
    archive_path = stage / 'source.tar'
    digest = hashlib.sha256()
    with archive_path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != request['archive_sha256']:
        raise ValueError('The source archive changed during transfer.')
    with tarfile.open(archive_path) as archive:
        members = [entry for entry in archive if entry.name == HELPER_MEMBER]
        if len(members) != 1 or not members[0].isfile() or not 0 < members[0].size <= MAX_HELPER_BYTES:
            raise ValueError('Invalid selected deployment helper.')
        with archive.extractfile(members[0]) as source:
            content = source.read(MAX_HELPER_BYTES + 1)
        if len(content) != members[0].size:
            raise ValueError('Incomplete selected deployment helper.')
    helper = stage / ('operations-helper-' + uuid.uuid4().hex + '.py')
    # A stage-owned regular file prevents following an existing link.
    with helper.open('xb') as output:
        output.write(content)
    sys.argv = [str(helper), *arguments]
    runpy.run_path(str(helper), run_name='__main__')


def main():
    if sys.argv[1:2] == ['--native-publish']:
        try:
            native_bootstrap(sys.argv[1:])
        except (OSError, ValueError, KeyError, tarfile.TarError) as error:
            print('Deployment stopped: ' + (str(error) if isinstance(error, ValueError) else type(error).__name__), file=sys.stderr)
            raise SystemExit(1)
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.ops.deploy import main as command
    command()


if __name__ == '__main__':
    main()
