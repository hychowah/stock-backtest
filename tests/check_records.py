"""Check that project records stay short, current and self-contained.

Run from the WSL source checkout before every commit:
    python3 tests/check_records.py [--root PATH]

The rules are in docs/records-policy.md. An active initiative may hold phase
records and working notes. A complete initiative holds only its summary,
contract documents and decision records.
"""
import argparse
from pathlib import Path
import posixpath
import re
import subprocess
import sys

AGENTS_MAX_WORDS = 3500
POLICY_MAX_WORDS = 1000
PLANS = 'docs/plans/'
EXPERIMENTS = 'results/experiments/'
SUMMARY_MAX_WORDS = 1000
CONTRACT_MAX_WORDS = 3000
JSON_MAX_BYTES = 64 * 1024
EXPERIMENT_TYPES = ('.md', '.json', '.csv', '.txt')
INITIATIVE = re.compile(r'docs/plans/([^/]+)/(.+)\Z')
PHASE = r'phases/phase-\d{2}/'
# (shape name, pattern relative to the initiative, word limit, allowed when complete)
SHAPES = (
    ('master plan', re.compile(r'master-plan\.md\Z'), CONTRACT_MAX_WORDS, True),
    ('initiative document', re.compile(r'[^/]+\.md\Z'), CONTRACT_MAX_WORDS, True),
    ('decision record', re.compile(PHASE + r'decisions/\d{4}-[a-z0-9-]+\.md\Z'), 700, True),
    ('phase record', re.compile(PHASE + r'README\.md\Z'), 900, False),
    ('working note', re.compile(PHASE + r'working/.+\.md\Z'), 3000, False),
    ('working data', re.compile(PHASE + r'working/.+\.json\Z'), None, False),
)
STATUS = re.compile(r'Status: (active|complete)\b')
DATED_HEADING = re.compile(r'^#+ .*\b(resumption|resumes)\b', re.I)
DATED_PARAGRAPH = re.compile(r'^(Phase \d+ (resumes|completes|starts)\b|Updated \d{1,2} [A-Z][a-z]+ \d{4})')
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


def read(root, path):
    return (Path(root) / path).read_text(encoding='utf-8', errors='replace')


def broken_links(root, path):
    """Yield relative links in a Markdown file whose target is absent."""
    for target in LINK.findall(read(root, path)):
        if target.startswith(('http:', 'https:', 'mailto:', '#')):
            continue
        local = target.split('#', 1)[0]
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), local))
        if not (Path(root) / resolved).exists():
            yield target


def status(root, path):
    """Return the status named on the first non-empty line after the title."""
    lines = [line.strip() for line in read(root, path).splitlines() if line.strip()]
    match = STATUS.fullmatch(lines[1]) if len(lines) > 1 and lines[0].startswith('# ') else None
    return match.group(1) if match else None


def check_agents(root, problems):
    agents = Path(root) / 'AGENTS.md'
    if not agents.is_file():
        problems.append('AGENTS.md is missing.')
        return
    text = agents.read_text(encoding='utf-8')
    if len(text.split()) > AGENTS_MAX_WORDS:
        problems.append(f'AGENTS.md: {len(text.split())} words exceeds {AGENTS_MAX_WORDS}. '
                        'Move detail to a standing document.')
    for number, line in enumerate(text.split('\n'), 1):
        if DATED_HEADING.match(line) or DATED_PARAGRAPH.match(line):
            problems.append(f'AGENTS.md:{number}: dated chronology. Replace the status section instead.')


def check_plans(root, files, problems):
    plans = [p for p in files if p.startswith(PLANS)]
    initiatives = sorted({INITIATIVE.match(p).group(1) for p in plans if INITIATIVE.match(p)})
    states = {}
    for name in initiatives:
        plan = f'{PLANS}{name}/master-plan.md'
        states[name] = status(root, plan) if plan in files else None
        if states[name] is None:
            problems.append(f'{plan}: missing, or its first line after the title is not '
                            '"Status: active" or "Status: complete".')
    for path in plans:
        match = INITIATIVE.match(path)
        if match is None:
            problems.append(f'{path}: put plan records inside docs/plans/<initiative>/.')
            continue
        name, relative = match.groups()
        shape = next((s for s in SHAPES if s[1].match(relative)), None)
        if shape is None:
            problems.append(f'{path}: not an allowed record. See the plan workspace layout in '
                            'docs/records-policy.md. Keep logs and dumps in tmp/.')
            continue
        label, _, limit, kept = shape
        if states.get(name) == 'complete' and not kept:
            problems.append(f'{path}: a complete initiative keeps no {label}. Close it out: '
                            'fold what matters into master-plan.md, then delete it.')
            continue
        if label == 'working data':
            size = (Path(root) / path).stat().st_size
            if size > JSON_MAX_BYTES:
                problems.append(f'{path}: {size} bytes exceeds {JSON_MAX_BYTES} for working data.')
            continue
        text = read(root, path)
        words = len(text.split())
        if label == 'master plan' and states.get(name) == 'complete':
            label, limit = 'complete summary', SUMMARY_MAX_WORDS
        if words > limit:
            problems.append(f'{path}: {words} words exceeds the {limit}-word limit for a {label}.')
        found = UNTRACKED_PATH.search(text)
        if found:
            problems.append(f'{path}: links to untracked path {found.group(0)}. Quote the result instead.')


def check_experiments(root, files, problems):
    for path in files:
        if not path.startswith(EXPERIMENTS):
            continue
        if not path.endswith(EXPERIMENT_TYPES):
            problems.append(f'{path}: results/experiments holds text summaries only. Keep raw output in tmp/.')
            continue
        size = (Path(root) / path).stat().st_size
        if size > JSON_MAX_BYTES:
            problems.append(f'{path}: {size} bytes exceeds {JSON_MAX_BYTES}. Summarize it; keep raw output in tmp/.')


def check(root):
    root = Path(root)
    problems = []
    files = listed(root)
    check_agents(root, problems)
    policy = root / 'docs' / 'records-policy.md'
    if not policy.is_file():
        problems.append('docs/records-policy.md is missing.')
    elif len(policy.read_text(encoding='utf-8').split()) > POLICY_MAX_WORDS:
        problems.append(f'docs/records-policy.md: exceeds {POLICY_MAX_WORDS} words.')
    if (root / 'tests' / 'records_baseline.txt').exists():
        problems.append('tests/records_baseline.txt: the exemption list is retired. Delete it.')
    check_plans(root, files, problems)
    check_experiments(root, files, problems)
    for path in files:
        if path.endswith('.md'):
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
