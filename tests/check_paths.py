"""Verify moved entry points resolve paths without credentials or downloads."""
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'website'))

with tempfile.TemporaryDirectory() as scratch:
    # Run imports from another directory and forbid credential reads and network access.
    original = Path.read_text
    def cached_only(path, *args, **kwargs):
        assert path.name != 'fmp_api_key', 'Offline imports must not read credentials'
        return original(path, *args, **kwargs)
    previous = Path.cwd()
    try:
        os.chdir(scratch)
        with patch.object(Path, 'read_text', cached_only), patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected network request')):
            modules = [importlib.import_module(name) for name in ['paths', 'run', 'revalue', 'list_stops', 'classify_stops', 'holdings']]
            paths, run, revalue, stops, classify, holdings = modules
            assert run.RAW == ROOT / 'raw'
            assert revalue.RESULTS == ROOT / 'results'
            assert stops.STOPS == classify.STOPS == ROOT / 'results/stops'
            assert run.LEGACY == ROOT / 'results/legacy'
            assert run.cache_path_for('TEST.A') == ROOT / 'raw/px/TEST.A.json'
            for file in ['universe.json', 'metrics.jsonl', 'treasury.json', 'spy-div.json']:
                assert (run.RAW / file).is_file()
            for file in ['summary-exits.txt', 'legacy/summary.txt', 'legacy/picks.csv', 'stops/stops.json', 'stops/stops-class.json']:
                assert (paths.RESULTS / file).is_file()
    finally:
        os.chdir(previous)

# Every Python source must still compile after moving.
for folder in ['scripts', 'tools', 'website', 'tests']:
    for source in (ROOT / folder).glob('*.py'):
        compile(source.read_text(), str(source), 'exec')
print('Passed: relocated imports, external working directory, cache and report paths, no credentials/network, and Python syntax.')
