"""Restore fixed entry-source bytes. Expected artifacts are never regenerated."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import hashlib
import io
import json
import unittest
from unittest.mock import patch
from backtest.variables import definitions as d, library, reference
from backtest.application import strategy_requests as s, evidence_views
from backtest import calendar_requests, result_evidence

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'phase08_compatibility'


def read(name):
    return (FIXTURES / name).read_text()


class CompatibilityTests(unittest.TestCase):
    def test_fixture_provenance_and_every_raw_byte_hash(self):
        # This digest pins the separately generated untouched-entry manifest.
        manifest=(FIXTURES/'manifest.json').read_bytes()
        self.assertEqual(hashlib.sha256(manifest).hexdigest(),
                         'c56edcf09e27d30760278aed54082266e26db2e2efcc0ec51e285e43f7945e4f')
        value=json.loads(manifest)
        self.assertEqual(value['entry_commit'],'3dccd88a0697c0e05054707ab1c1a5f897797805')
        self.assertEqual(len(value['files']),8)
        for name,evidence in value['files'].items():
            data=(FIXTURES/name).read_bytes()
            self.assertEqual(len(data),evidence['bytes'],name)
            self.assertEqual(hashlib.sha256(data).hexdigest(),evidence['sha256'],name)

    def test_old_definitions_revisions_projection_and_repeated_roots(self):
        authored=json.loads(read('authored.json'))
        for value in authored['definitions']:
            self.assertEqual(d.revision(value['definition']),value['revision'])
        program=d.validate(dict(format='variable-bundle',version=1,
            definitions=authored['definitions'],roots=authored['roots']))
        self.assertEqual(program.to_json(),read('program.json'))
        self.assertEqual(d.canonical(d.require_program(d.FormulaProgram(read('program.json')))),read('program.json'))
        self.assertEqual(d.authored_bundle(program)['roots'],authored['roots'])
        self.assertEqual(reference.require_program(program),program.to_dict())

    def test_variable_and_strategy_capture_bytes_without_library_or_capability(self):
        with patch.object(library.Store,'_transaction',side_effect=AssertionError('No current library')), \
             patch.object(reference,'require_program',side_effect=AssertionError('No execution admission')), \
             patch.object(s,'builtin_catalog',side_effect=AssertionError('No current catalog')):
            variable=library.VariableCapture(read('variable-capture.json'))
            strategy=s.CapturedStrategy(read('strategy-capture.json'))
            self.assertEqual(d.canonical(library.require_capture(variable)),read('variable-capture.json'))
            self.assertEqual(d.canonical(s.require_strategy(strategy)),read('strategy-capture.json'))
            self.assertEqual(variable.to_json(),read('variable-capture.json'))
            self.assertEqual(strategy.to_json(),read('strategy-capture.json'))
        authored=json.loads(read('authored.json'))
        regenerated=library.capture_submitted(authored['roots'],submitted=authored['definitions'],labels=authored['labels'])
        self.assertEqual(regenerated.to_json(),read('variable-capture.json'))

    def test_queued_intent_and_real_recorded_plan_remain_accepted_without_rewrite(self):
        request=json.loads(read('queued-request.json'))
        plan=json.loads(read('recorded-plan.json'))
        before=d.canonical(request),d.canonical(plan)
        self.assertEqual(s.check_request(request),json.loads(read('strategy-capture.json')))
        s.validate_recorded(request['options'],plan)
        from datetime import date
        self.assertEqual(calendar_requests.validate_plan([date(2015,1,2),date(2015,1,5)],plan),plan)
        self.assertEqual((d.canonical(request),d.canonical(plan)),before)

    def test_old_completed_scalar_bytes_open_and_export_without_current_state(self):
        data=(FIXTURES/'completed-scalar.bin').read_bytes()
        with patch.object(reference,'require_program',side_effect=AssertionError('No execution admission')), \
             patch.object(s,'builtin_catalog',side_effect=AssertionError('No current catalog')), \
             patch.object(library.Store,'_transaction',side_effect=AssertionError('No current library')):
            reader=result_evidence.open_reader(io.BytesIO(data),max_bytes=16*1024**2)
            self.assertEqual(reader.format_version,2)
            self.assertEqual(d.canonical(reader.manifest),read('completed-manifest.json'))
            rows=list(evidence_views.holdings(reader,1,1))
            self.assertEqual(len(rows),5)
            self.assertEqual([item['symbol'] for item in rows],['A0007','A0006','A0005','A0004','A0003'])
            list(reader.verified_records())
            from backtest.application import result_exports
            self.assertEqual(b''.join(result_exports.prepare(reader,'evidence').chunks()),data)


if __name__=='__main__':unittest.main()
