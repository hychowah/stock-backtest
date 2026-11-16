"""Add the converted tests and variables of proof/convert.py to the new site, once, at the switch.

    python3 proof/import_tests.py CONVERTED URL

CONVERTED is the folder that proof/convert.py wrote (`strategies/`, `tests.jsonl`, `variables.jsonl`) and URL the
address of a running `bt serve`, such as http://127.0.0.1:3000. It sends only the site's own routes, with no
`Origin` header, and reads nothing else. It adds, in this order:
- the current revision of each variable of `variables.jsonl`, in file order, the oldest first:
  `POST /api/variables {name, formula, display, favourite}`. A variable whose current revision did not convert
  (no revision of its line is current) is not added, and no older revision is sent;
- each saved test of `tests.jsonl`, the oldest first (the file lists the newest first), then each queued test that still
  waited (state `queued` or `held`; a test of another state is not added) and each test of a request file, in file
  order: `POST /api/runs {name, market, schedule, strategy}`. The schedule is
  the line's `run` with `interval` as `every`: `start`, `end`, `every`, `dates`, and `trials` and `seed` of a test
  with random dates. The strategy is the JSON of the line's strategy file. A locked test then gets
  `PATCH /api/runs/{id} {"locked": true}`. A held test is added waiting, like the rest.
It then reads `GET /api/runs` every 2 s until none of the runs it added waits or runs, or the queue is paused, and
prints each variable and test not added as `not added: NAME: WHY`, the counts of its runs by state, the name and
error of each failed run, the counts of the lines not added and the time taken. It exits with 1
when a run failed or did not finish.

The first refused request stops it: it prints the status, the server's message and place, and the variables and
tests already added, and exits with 2. A second run stops at the first variable, which the library already holds; with
no variables it adds the tests again.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request


class Refused(Exception):
    """A request that the server refused, or that got no reply: what to print."""


def send(url, method, path, body=None):
    """The JSON reply of one request; a refusal raises Refused with the status, message and place."""
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url + path, data, {'Content-Type': 'application/json'}, method=method)
    try:
        with urllib.request.urlopen(request) as reply:
            return json.load(reply)
    except urllib.error.HTTPError as error:
        text = error.read().decode(errors='replace')
        try:
            found = json.loads(text)['error']
            text = f"{found['message']} (place: {found['place']})"
        except (ValueError, KeyError, TypeError):
            pass
        raise Refused(f'{method} {path} gave {error.code}: {text}') from None
    except OSError as error:
        raise Refused(f'{method} {path} got no reply: {error}') from None


def lines(path):
    """The JSON lines of a file."""
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def schedule(run):
    """The schedule of a line's run settings, as the server takes it."""
    keys = dict(interval='every', dates='dates', trials='trials', seed='seed')
    return dict(start=run['start'], end=run['end'], **{keys[key]: run[key] for key in keys if key in run})


def main():
    parser = argparse.ArgumentParser(description='Add converted tests and variables to the new site.')
    parser.add_argument('converted', type=Path)
    parser.add_argument('url')
    args = parser.parse_args()
    url, folder, began = args.url.rstrip('/'), args.converted, time.monotonic()
    tests = lines(folder / 'tests.jsonl')
    ordered = [test for test in tests if test['source'] == 'saved'][::-1] + [test for test in tests if test['source'] != 'saved']
    added, ids, skipped = [], {}, Counter()
    try:
        for line in lines(folder / 'variables.jsonl'):
            current = next((revision for revision in line['revisions'] if revision['current']), None)
            if current is None:
                print(f"not added: {line['name']}: its current revision is in unconverted.jsonl")
                skipped['variables'] += 1
                continue
            send(url, 'POST', '/api/variables', dict(name=line['name'], formula=current['formula'],
                                                     display=current['display'], favourite=line['favourite']))
            added.append('variable ' + line['name'])
        for test in ordered:
            if test['source'] == 'queue' and test['state'] not in ('queued', 'held'):
                print(f"not added: {test['name']}: the old queue line was {test['state']}")
                skipped['tests'] += 1
                continue
            strategy = json.loads((folder / test['strategy']).read_text(encoding='utf-8'))
            run = send(url, 'POST', '/api/runs', dict(name=test['name'], market=test['run']['market'],
                                                      schedule=schedule(test['run']), strategy=strategy))
            ids[run['id']] = test['name']
            added.append('test ' + test['name'])
            if test.get('locked'):
                send(url, 'PATCH', f"/api/runs/{run['id']}", dict(locked=True))
        print(f'added {len(added) - len(ids)} variables and {len(ids)} tests; waiting for the runs')
        while True:
            reply = send(url, 'GET', '/api/runs')
            mine = [run for run in reply['runs'] if run['id'] in ids]
            if not any(run['state'] in ('waiting', 'running') for run in mine):
                break
            if reply['paused']:
                print('the queue is paused: the waiting runs do not start')
                break
            time.sleep(2)
    except Refused as error:
        print(f'refused: {error}')
        print('already added: ' + (', '.join(added) or 'nothing'))
        return 2
    states = Counter(run['state'] for run in mine)
    print(', '.join(f'{state} {count}' for state, count in dict(dict(complete=0, failed=0), **states).items()))
    for run in mine:
        if run['state'] == 'failed':
            error = run.get('error') or {}
            print(f"failed: {run['name']}: {error.get('message')} (place: {error.get('place')})")
    print(f"not added: {skipped['variables']} variables, {skipped['tests']} tests")
    print(f'{time.monotonic() - began:.1f} s')
    return int(states['complete'] != len(ids))


if __name__ == '__main__':
    sys.exit(main())
