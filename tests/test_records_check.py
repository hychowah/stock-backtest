"""The records check rejects process sprawl and accepts compliant records."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import check_records  # noqa: E402

PHASE = 'docs/plans/demo/phases/phase-12/'
GOOD_AGENTS = '# Rules\n\n## Demo work: current state\n\nOne status section.\n'
POLICY = '# Records policy\n\nShort.\n'


def words(count):
    return ' '.join(['word'] * count) + '\n'


class RecordsCheck(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.write('AGENTS.md', GOOD_AGENTS)
        self.write('docs/records-policy.md', POLICY)

    def tearDown(self):
        self.scratch.cleanup()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')

    def problems(self):
        return check_records.check(self.root)

    def test_compliant_phase_passes(self):
        self.write(PHASE + 'README.md', '# Phase 12\n\n' + words(300))
        self.write(PHASE + 'decisions/0001-use-one-owner.md', '# Decision\n\n' + words(200))
        self.write('docs/plans/demo/contract.md', '# Contract\n\nSee [phase](phases/phase-12/README.md).\n')
        self.assertEqual(self.problems(), [])

    def test_process_files_are_rejected(self):
        for name in ('slice-01-design.md', 'slice-01.md', 'handoffs/slice-02.md',
                     'slice-01-audit.md', 'execution-plan-2026-11-04.md', 'addendum.md'):
            self.write(PHASE + name, '# Process record\n')
        found = self.problems()
        self.assertEqual(len(found), 6)
        self.assertTrue(all('not an allowed record' in item for item in found))

    def test_size_limits(self):
        self.write(PHASE + 'README.md', words(901))
        self.write(PHASE + 'decisions/0001-too-long.md', words(701))
        self.write('docs/plans/demo/huge.md', words(3001))
        self.assertEqual(len(self.problems()), 3)

    def test_untracked_path_and_broken_link(self):
        self.write(PHASE + 'README.md', 'Timings are in `tmp/run/timings.log`.\n[gone](missing.md)\n')
        found = ' | '.join(self.problems())
        self.assertIn('untracked path', found)
        self.assertIn('broken link missing.md', found)

    def test_agents_chronology_and_length(self):
        self.write('AGENTS.md', GOOD_AGENTS + '\n## Phase 12 resumption — 4 November 2026\n\n'
                   'Phase 12 resumes on 4 November 2026 from `abc1234`.\n' + 'x\n' * 700)
        found = ' | '.join(self.problems())
        self.assertIn('dated phase chronology', found)
        self.assertIn('exceeds 700', found)

    def test_baseline_files_are_exempt(self):
        self.write('docs/plans/demo/phases/phase-01/handoffs/old.md', '# Legacy\n')
        self.write('tests/records_baseline.txt', 'docs/plans/demo/phases/phase-01/handoffs/old.md\n')
        self.assertEqual(self.problems(), [])

    def test_missing_policy_is_reported(self):
        (self.root / 'docs/records-policy.md').unlink()
        self.assertIn('docs/records-policy.md is missing.', self.problems())


if __name__ == '__main__':
    unittest.main()
