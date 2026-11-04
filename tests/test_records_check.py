"""The records check accepts the plan lifecycle and rejects process sprawl."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import check_records  # noqa: E402

PLAN = 'docs/plans/demo/'
PHASE = PLAN + 'phases/phase-12/'
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
        if isinstance(text, bytes):
            target.write_bytes(text)
        else:
            target.write_text(text, encoding='utf-8')

    def plan(self, state, extra=''):
        self.write(PLAN + 'master-plan.md', f'# Demo\n\nStatus: {state}\n\n{extra}')

    def problems(self):
        return check_records.check(self.root)

    def test_active_plan_with_working_notes_passes(self):
        self.plan('active', 'See [phase](phases/phase-12/README.md).\n')
        self.write(PHASE + 'README.md', '# Phase 12\n\n' + words(300))
        self.write(PHASE + 'decisions/0001-use-one-owner.md', '# Decision\n\n' + words(200))
        self.write(PHASE + 'working/design.md', '# Design\n\n' + words(2500))
        self.write(PHASE + 'working/handoffs/implement.md', '# Handoff\n')
        self.write(PHASE + 'working/evidence.json', '{"checks": 12}\n')
        self.write(PLAN + 'contract.md', '# Contract\n\n' + words(100))
        self.assertEqual(self.problems(), [])

    def test_complete_plan_keeps_only_summary_contracts_and_decisions(self):
        self.plan('complete', words(400))
        self.write(PLAN + 'contract.md', '# Contract\n')
        self.write(PHASE + 'decisions/0001-use-one-owner.md', '# Decision\n')
        self.assertEqual(self.problems(), [])
        self.write(PHASE + 'README.md', '# Phase 12\n')
        self.write(PHASE + 'working/design.md', '# Design\n')
        found = self.problems()
        self.assertEqual(len(found), 2)
        self.assertTrue(all('complete initiative keeps no' in item for item in found))

    def test_status_line_is_required(self):
        self.write(PLAN + 'master-plan.md', '# Demo\n\nNo status here.\n')
        self.write(PLAN + 'notes.md', '# Notes\n')
        self.assertIn('Status: active', ' | '.join(self.problems()))

    def test_process_files_are_rejected(self):
        self.plan('active')
        for name in ('slice-01-design.md', 'handoffs/slice-02.md', 'CB-14.results.json',
                     'run.log.gz', 'checkpoints.sqlite', 'working/trace.log'):
            self.write(PHASE + name, '# Process record\n')
        found = self.problems()
        self.assertEqual(len(found), 6)
        self.assertTrue(all('not an allowed record' in item for item in found))

    def test_size_limits(self):
        self.plan('active')
        self.write(PHASE + 'README.md', words(901))
        self.write(PHASE + 'decisions/0001-too-long.md', words(701))
        self.write(PHASE + 'working/notes.md', words(3001))
        self.write(PHASE + 'working/big.json', b'0' * (64 * 1024 + 1))
        self.write(PLAN + 'huge.md', words(3001))
        self.assertEqual(len(self.problems()), 5)

    def test_complete_summary_limit(self):
        self.plan('complete', words(1001))
        self.assertIn('complete summary', ' | '.join(self.problems()))

    def test_experiment_results_stay_small_text(self):
        self.write('results/experiments/summary.json', '{"seconds": 43.2}\n')
        self.assertEqual(self.problems(), [])
        self.write('results/experiments/run/profile.json.gz', b'\x1f\x8b')
        self.write('results/experiments/raw.json', b'0' * (64 * 1024 + 1))
        self.write('results/experiments/runtime-baseline-0123456789ab.json', b'0' * (64 * 1024 + 1))
        found = self.problems()
        self.assertEqual(len(found), 2)
        self.assertIn('text summaries only', ' | '.join(found))
        self.assertIn('raw.json', ' | '.join(found))

    def test_untracked_path_and_broken_link(self):
        self.plan('active')
        self.write(PHASE + 'README.md', 'Timings are in `tmp/run/timings.log`.\n[gone](missing.md)\n')
        self.write('docs/guide.md', '[also gone](nowhere.md)\n')
        found = ' | '.join(self.problems())
        self.assertIn('untracked path', found)
        self.assertIn('broken link missing.md', found)
        self.assertIn('docs/guide.md: broken link nowhere.md', found)

    def test_agents_chronology_and_length(self):
        self.write('AGENTS.md', GOOD_AGENTS + 'Updated 3 November 2026.\n\n'
                   '## Phase 12 resumption\n\nPhase 12 resumes from `abc1234`.\n' + words(3500))
        found = ' | '.join(self.problems())
        self.assertIn('dated chronology', found)
        self.assertIn('exceeds 3500', found)

    def test_retired_baseline_is_reported(self):
        self.write('tests/records_baseline.txt', 'docs/plans/demo/old.md\n')
        self.assertIn('exemption list is retired', ' | '.join(self.problems()))

    def test_missing_policy_is_reported(self):
        (self.root / 'docs/records-policy.md').unlink()
        self.assertIn('docs/records-policy.md is missing.', self.problems())


if __name__ == '__main__':
    unittest.main()
