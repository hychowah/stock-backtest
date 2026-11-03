"""Check that project records stay short, current and self-contained.

Run from the WSL source checkout before every commit:
    python3 tests/check_records.py [--root PATH]

The rules are in docs/records-policy.md. Files listed in tests/records_baseline.txt
existed when the policy began. They are exempt from shape and size rules. Remove
entries as files are deleted. Never add an entry.
"""
import argparse
from pathlib import Path
import posixpath
import re
import subprocess
import sys

AGENTS_MAX_LINES = 700
POLICY_MAX_WORDS = 800
PLANS = 'docs/plans/'
PHASE = r'docs/plans/[^/]+/phases/phase-\d{2}/'
# (shape name, path pattern, word limit). A new file under docs/plans must match one.
SHAPES = (
    ('phase record', re.compile(PHASE + r'README\.md\Z'), 900),
    ('decision record', re.compile(PHASE + r'decisions/\d{4}-[a-z0-9-]+\.md\Z'), 700),
    ('initiative document', re.compile(r'docs/plans/[^/]+/[^/]+\.md\Z'), 3000),
)
DATED_HEADING = re.compile(r'^#+ .*\b(resumption|resumes)\b', re.I)
DATED_PARAGRAPH = re.compile(r'^Phase \d+ (resumes|completes|starts)\b')
LINK = re.compile(r'\]\(([^)\s]+)\)')
UNTRACKED_PATH = re.compile(r'(?<![\w./-])/?tmp/[\w./-]+')


def listed(root):
    """Return files that git tracks or would add, so the check sees uncommitted work."""
    try:
        out = subprocess.run(['git', '-C', str(root), 'ls-files', '--cached', '--others',
                              '--exclude-standard', '-z'], capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        sys.exit('check_records: git is unavailable here. Run it in the WSL source checkout.')
    return sorted(p for p in out.decode().split('\0') if p and (Path(root) / p).is_file())


def broken_links(root, path):
    """Yield relative links in a Markdown file whose target is absent."""
    text = (Path(root) / path).read_text(encoding='utf-8', errors='replace')
    for target in LINK.findall(text):
        if target.startswith(('http:', 'https:', 'mailto:', '#')):
            continue
        local = target.split('#', 1)[0]
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), local))
        if not (Path(root) / resolved).exists():
            yield target


def check(root):
    root = Path(root)
    problems = []
    baseline_file = root / 'tests' / 'records_baseline.txt'
    baseline = set(baseline_file.read_text().split('\n')) if baseline_file.is_file() else set()
    files = listed(root)

    agents = root / 'AGENTS.md'
    if agents.is_file():
        lines = agents.read_text(encoding='utf-8').split('\n')
        if len(lines) > AGENTS_MAX_LINES:
            problems.append(f'AGENTS.md: {len(lines)} lines exceeds {AGENTS_MAX_LINES}. Move detail to a contract document.')
        for number, line in enumerate(lines, 1):
            if DATED_HEADING.match(line) or DATED_PARAGRAPH.match(line):
                problems.append(f'AGENTS.md:{number}: dated phase chronology. Replace the status section instead.')
        problems += [f'AGENTS.md: broken link {t}' for t in broken_links(root, 'AGENTS.md')]
    else:
        problems.append('AGENTS.md is missing.')

    policy = root / 'docs' / 'records-policy.md'
    if not policy.is_file():
        problems.append('docs/records-policy.md is missing.')
    else:
        words = len(policy.read_text(encoding='utf-8').split())
        if words > POLICY_MAX_WORDS:
            problems.append(f'docs/records-policy.md: {words} words exceeds {POLICY_MAX_WORDS}.')
        problems += [f'docs/records-policy.md: broken link {t}' for t in broken_links(root, 'docs/records-policy.md')]

    for path in files:
        if not path.startswith(PLANS) or path in baseline:
            continue
        shape = next(((name, limit) for name, pattern, limit in SHAPES if pattern.match(path)), None)
        if shape is None:
            problems.append(f'{path}: not an allowed record. Use a phase README, a decision record or an '
                            f'initiative document. Put reports, audits and handoffs in the commit message.')
            continue
        text = (root / path).read_text(encoding='utf-8', errors='replace')
        words = len(text.split())
        if words > shape[1]:
            problems.append(f'{path}: {words} words exceeds the {shape[1]}-word limit for a {shape[0]}.')
        for match in UNTRACKED_PATH.finditer(text):
            problems.append(f'{path}: links to untracked path {match.group(0)}. Quote the result instead.')
            break
        problems += [f'{path}: broken link {t}' for t in broken_links(root, path)]
    return problems


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--root', default=Path(__file__).resolve().parents[1])
    problems = check(parser.parse_args().root)
    for problem in problems:
        print(problem)
    if problems:
        sys.exit(f'{len(problems)} record problem(s). See docs/records-policy.md.')
    print('Project records follow the policy.')
