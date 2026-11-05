"""Restore fixed entry-source bytes. Expected artifacts are never regenerated."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import hashlib
import io
import json
import sqlite3
import tempfile
from contextlib import closing
import unittest
from unittest.mock import patch
from backtest.variables import definitions as d, library, selection
from backtest.application import strategy_requests as s, evidence_views, queue, library as saved, result_exports
from backtest import calendar_requests, result_evidence
from backtest.inputs import research, daily
from backtest.application import original_calculations

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
        self.assertEqual(selection.require_program(program),program.to_dict())

    def test_variable_and_strategy_capture_bytes_without_library_or_capability(self):
        with patch.object(library.Store,'_transaction',side_effect=AssertionError('No current library')), \
             patch.object(selection,'require_program',side_effect=AssertionError('No execution admission')), \
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

    def test_historical_definition_reopens_in_private_variable_library(self):
        # Historical expected content is fixed; this test exercises current readers and stores without regenerating expectations.
        old=json.loads(read('authored.json'))['definitions'][0]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'variables.sqlite';store=library.Store(path)
            record=store.create('Historical variable',old['definition'],favourite=True)
            self.assertEqual(record['revision'],old['revision'])
            with closing(sqlite3.connect(path)) as db:
                before=(db.execute('SELECT * FROM entries').fetchall(),db.execute('SELECT * FROM revisions').fetchall())
            reopened=library.Store(path)
            self.assertEqual(reopened.get(record['variable_id']),record)
            program=reopened.resolve([dict(variable_id=record['variable_id'],revision=record['revision'])])
            self.assertEqual(d.authored_bundle(program)['definitions'][0]['definition'],old['definition'])
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual((db.execute('SELECT * FROM entries').fetchall(),db.execute('SELECT * FROM revisions').fetchall()),before)

    def test_historical_request_and_plan_reopen_in_private_queue(self):
        # Historical expected content is fixed; this test exercises current readers and stores without regenerating expectations.
        old=json.loads(read('queued-request.json'))
        plan=json.loads(read('recorded-plan.json'))
        request=dict(id='1'*32,name='Historical labels',mode=old['kind'],
                     options=old['options'],catalog=dict(metrics={},filters={}),presentation={})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'queue.sqlite';store=queue.Store(path)
            store.enqueue(request)
            store.claim();store.progress(request['id'],'configuration',plan)
            waiting=dict(request,id='2'*32,name='Waiting historical labels')
            store.enqueue(waiting)
            store.recover()
            with closing(sqlite3.connect(path)) as db:
                before=db.execute('SELECT id,spec,configuration,plan,state FROM jobs ORDER BY id').fetchall()
            with patch.object(library.Store,'_transaction',side_effect=AssertionError('No variable library')), \
                 patch.object(s,'builtin_catalog',side_effect=AssertionError('No current catalog')), \
                 patch.object(selection,'require_program',side_effect=AssertionError('No calculation')), \
                 patch.object(original_calculations.Original,'calculate',side_effect=AssertionError('No calculation')), \
                 patch.object(original_calculations.Original,'calculate_into',side_effect=AssertionError('No calculation')), \
                 patch.object(research,'prepare',side_effect=AssertionError('No preparation')), \
                 patch.object(daily,'prepare',side_effect=AssertionError('No preparation')):
                reopened=queue.Store(path)
                first=reopened.get(request['id']);second=reopened.get(waiting['id'])
                self.assertEqual(first['options'],old['options'])
                self.assertEqual(first['configuration'],{key:plan[key] for key in ('seed','requested','start','end','months','calendar') if key in plan})
                with reopened.database() as db:
                    self.assertEqual(json.loads(reopened.row(db,request['id'],include_plan=True)['plan']),plan)
                self.assertEqual(first['name'],request['name'])
                self.assertEqual(second['options'],old['options'])
                self.assertEqual(second['name'],waiting['name'])
                self.assertEqual((first['state'],second['state']),('queued','queued'))
                self.assertIsNone(second['configuration'])
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT id,spec,configuration,plan,state FROM jobs ORDER BY id').fetchall(),before)

    def test_historical_evidence_reopens_and_exports_through_saved_library(self):
        # Historical expected content is fixed; this test exercises current readers and stores without regenerating expectations.
        data=(FIXTURES/'completed-scalar.bin').read_bytes()
        reader=result_evidence.open_reader(io.BytesIO(data),max_bytes=16*1024**2)
        metadata=dict(version=4,kind='custom',settings=dict(mode='custom',**reader.metadata['options']),
                      result=reader.manifest['summary'],catalog=dict(metrics={},filters={}),
                      presentation=dict(periodLabel='Historical label'))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'saved.sqlite';store=saved.Store(path)
            record=store.save_evidence('Historical result',metadata,reader)
            with closing(sqlite3.connect(path)) as db:
                before=(db.execute('SELECT * FROM records').fetchall(),db.execute('SELECT * FROM evidence_chunks').fetchall())
            with patch.object(library.Store,'_transaction',side_effect=AssertionError('No variable library')), \
                 patch.object(s,'builtin_catalog',side_effect=AssertionError('No current catalog')), \
                 patch.object(selection,'require_program',side_effect=AssertionError('No calculation')), \
                 patch.object(original_calculations.Original,'calculate',side_effect=AssertionError('No calculation')), \
                 patch.object(original_calculations.Original,'calculate_into',side_effect=AssertionError('No calculation')), \
                 patch.object(research,'prepare',side_effect=AssertionError('No preparation')), \
                 patch.object(daily,'prepare',side_effect=AssertionError('No preparation')):
                reopened=saved.Store(path)
                self.assertEqual(reopened.list()[0]['name'],'Historical result')
                with reopened.open_evidence(record['id']) as opened:
                    self.assertEqual(opened.metadata,metadata)
                    self.assertEqual(b''.join(result_exports.prepare(opened.reader,'evidence').chunks()),data)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual((db.execute('SELECT * FROM records').fetchall(),db.execute('SELECT * FROM evidence_chunks').fetchall()),before)

    def test_old_completed_scalar_bytes_open_and_export_without_current_state(self):
        data=(FIXTURES/'completed-scalar.bin').read_bytes()
        with patch.object(selection,'require_program',side_effect=AssertionError('No execution admission')), \
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
