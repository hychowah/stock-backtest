"""Independent-engine agreement, priced revisions and recoverable publication."""

import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0,str(_PackagePath(__file__).resolve().parents[1]))
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest import screening
from contextlib import closing
from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
import sqlite3
import shutil
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from backtest.inputs import baseline as b
from backtest.inputs import research as r
import test_research as fixtures

VERIFY=r.verify_reference


class BaselineTests(unittest.TestCase):
    verify_fixture=fixtures.PreparationTests.verify_fixture

    def setUp(self):
        fixtures.PreparationTests.setUp(self)
        self.context.enter_context(patch.object(r,'verify_reference',VERIFY))
        self.context.enter_context(patch.object(r.revalue,'RAW',r.RAW))
        self.owner=b.Baseline(r.RESULTS,self.path)

    def result(self):
        with closing(r.connect(self.path)) as db:
            return json.loads(db.execute("SELECT value FROM metadata WHERE key='baseline_result'").fetchone()[0])

    def history(self):return sorted(self.owner.history.iterdir())

    def update_price(self,value=24):
        path=r.RAW/'px/TEST.json';rows=json.loads(path.read_text())
        rows['div'][-1]['adjClose']=value;path.write_text(json.dumps(rows))

    def test_new_price_refreshes_both_engines_and_preserves_exact_previous_evidence(self):
        original=self.owner.report.read_bytes()
        r.prepare(self.path)
        self.assertEqual(self.result()['years'][0]['holdings'][0]['exit_price'],22)
        initial=self.history()[0]
        self.assertEqual((initial/'previous-report.txt').read_bytes(),original)
        self.assertIsNone(json.loads((initial/'previous-snapshot.json').read_text()))
        old=self.owner.report.read_bytes()
        self.update_price()
        r.prepare(self.path)
        self.assertIn('2015,0.2000,0.1000,1,0,0',self.owner.report.read_text())
        with closing(r.connect(self.path)) as db:audit=self.owner.audit(db)
        folder=r.RESULTS/audit['summary']['audit']
        details=audit['details']['years'][0]['holdings'][0]
        self.assertEqual(details['symbol'],'TEST')
        self.assertEqual(details['fields']['exit_price'],dict(before=22,after=24))
        self.assertEqual((folder.parent/'previous-report.txt').read_bytes(),old)
        self.assertFalse(self.owner.journal.exists())

    def test_latest_only_update_preserves_historical_report_and_revision(self):
        r.prepare(self.path);report=self.owner.report.read_bytes();folders=self.history()
        path=r.RAW/'spy-div.json';rows=json.loads(path.read_text());rows.append(dict(date='2016-01-04',adjClose=120));path.write_text(json.dumps(rows))
        path=r.RAW/'px/TEST.json';rows=json.loads(path.read_text());rows['div'].append(dict(date='2016-01-04',adjClose=24));path.write_text(json.dumps(rows))
        r.prepare(self.path)
        self.assertEqual(self.owner.report.read_bytes(),report);self.assertEqual(self.history(),folders)
        with closing(r.connect(self.path)) as db:self.assertEqual(screening.latest(db)[0]['price_date'],'2016-01-04')
        self.assertEqual(self.result()['through'],'2015-10-20')

    def test_unchanged_inputs_start_neither_engine(self):
        r.prepare(self.path)
        with patch.object(r.revalue,'calculate',side_effect=AssertionError('Unneeded reference parse')):r.prepare(self.path)

    def test_equal_average_cannot_hide_holding_price_or_coverage_disagreement(self):
        r.prepare(self.path);result=self.result()
        for key,value in [('entry_price',99),('return_value',float('nan')),('rank',2),('symbol','OTHER'),('status','Bankruptcy')]:
            altered=deepcopy(result);altered['years'][0]['holdings'][0][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'engines disagree'):b.agree(result,altered)
        altered=deepcopy(result);altered['years']=[]
        with self.assertRaisesRegex(ValueError,'coverage'):b.agree(result,altered)

    def test_disagreement_keeps_report_database_and_history_unchanged(self):
        r.prepare(self.path);old=self.path.read_bytes();report=self.owner.report.read_bytes();history=self.history()
        self.update_price()
        wrong=deepcopy(self.result());wrong['years'][0]['holdings'][0]['symbol']='WRONG'
        with patch.object(r.revalue,'calculate',return_value=wrong),self.assertRaisesRegex(ValueError,'engines disagree'):r.prepare(self.path)
        self.assertEqual(self.path.read_bytes(),old);self.assertEqual(self.owner.report.read_bytes(),report)
        self.assertEqual(self.history(),history);self.assertFalse(self.owner.journal.exists())

    def test_recovery_before_and_after_each_canonical_replacement(self):
        r.prepare(self.path)
        for target in ('report','database'):
            for after in (False,True):
                self.update_price(24 if not after else 26)
                original=b._replace;fired=[]
                destination=getattr(self.owner,target)
                def interrupt(source,dest):
                    if dest==destination and not fired:
                        fired.append(True)
                        if after:original(source,dest)
                        raise RuntimeError('Simulated interruption')
                    return original(source,dest)
                with self.subTest(target=target,after=after):
                    with patch.object(b,'_replace',side_effect=interrupt),self.assertRaisesRegex(RuntimeError,'interruption'):r.prepare(self.path,force=True)
                    self.assertTrue(self.owner.journal.exists())
                    with self.assertRaisesRegex(ValueError,'unfinished'):r.connect(self.path,check=False)
                    self.owner.recover();self.owner.recover()
                    self.assertFalse(self.owner.journal.exists())
                    with closing(r.connect(self.path,full_prices=True)) as db:self.owner.check_ready(db)

    def test_recovery_rejects_tampered_staging_before_changing_either_target(self):
        r.prepare(self.path);old=self.path.read_bytes();report=self.owner.report.read_bytes();self.update_price()
        original=b._replace
        def interrupt(source,dest):
            if dest==self.owner.report:raise RuntimeError('interrupted')
            return original(source,dest)
        with patch.object(b,'_replace',side_effect=interrupt),self.assertRaises(RuntimeError):r.prepare(self.path)
        journal=json.loads(self.owner.journal.read_text());(self.owner.history/journal['generation']/journal['artifacts'][1]['source']).write_bytes(b'damaged')
        with self.assertRaisesRegex(ValueError,'receipts'):self.owner.recover()
        self.assertEqual(self.path.read_bytes(),old);self.assertEqual(self.owner.report.read_bytes(),report)

    def test_legacy_prices_are_unavailable_instead_of_read_from_revised_raw(self):
        r.prepare(self.path)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("DELETE FROM metadata WHERE key='baseline_result'")
        self.update_price()
        r.prepare(self.path)
        with closing(r.connect(self.path)) as db:audit=self.owner.audit(db)
        self.assertTrue(audit['summary']['bootstrap'])
        holding=audit['details']['years'][0]['holdings'][0]
        self.assertIsNone(holding['fields']['exit_price']['before'])
        self.assertEqual(holding['fields']['exit_price']['after'],24)

    def test_windows_revision_locator_can_be_opened_and_normalized_on_any_os(self):
        r.prepare(self.path)
        with closing(sqlite3.connect(self.path)) as db,db:
            revision=json.loads(db.execute("SELECT value FROM metadata WHERE key='baseline_revision'").fetchone()[0])
            self.assertNotIn(chr(92),revision['audit'])
            revision['audit']=revision['audit'].replace('/',chr(92))
            db.execute("UPDATE metadata SET value=? WHERE key='baseline_revision'",(json.dumps(revision),))
        with closing(r.connect(self.path)) as db:
            self.assertEqual(self.owner.audit(db)['summary']['audit'],revision['audit'].replace(chr(92),'/'))
        r.prepare(self.path,force=True)
        with closing(r.connect(self.path)) as db:self.assertNotIn(chr(92),self.owner.audit(db)['summary']['audit'])

    def test_interrupted_publication_recovers_after_project_relocation(self):
        r.prepare(self.path);self.update_price();original=b._replace
        def interrupt(source,target):
            if target==self.path:raise RuntimeError('interrupted')
            return original(source,target)
        with patch.object(b,'_replace',side_effect=interrupt),self.assertRaises(RuntimeError):r.prepare(self.path)
        journal=self.owner.journal.read_text()
        self.assertNotIn(str(r.ROOT),journal)
        moved=r.ROOT/'moved-project'
        shutil.copytree(r.ROOT,moved,ignore=shutil.ignore_patterns('moved-project'))
        owner=b.Baseline(moved/'results',moved/'data/research.sqlite')
        owner.recover();owner.recover()
        self.assertFalse(owner.journal.exists())
        with closing(sqlite3.connect(owner.database)) as db:
            owner.check_ready(db)
            result=json.loads(db.execute("SELECT value FROM metadata WHERE key='baseline_result'").fetchone()[0])
            self.assertEqual(result['years'][0]['holdings'][0]['exit_price'],24)
            self.assertTrue(owner.audit(db)['details']['years'])

    def test_changed_inputs_during_independent_verification_preserve_previous_generation(self):
        r.prepare(self.path);old=self.path.read_bytes();report=self.owner.report.read_bytes()
        calculate=r.revalue.calculate
        def changed(through):
            result=calculate(through);self.update_price();return result
        with patch.object(r.revalue,'calculate',side_effect=changed),self.assertRaisesRegex(ValueError,'Inputs changed'):
            r.prepare(self.path,force=True)
        self.assertEqual(self.path.read_bytes(),old);self.assertEqual(self.owner.report.read_bytes(),report)

    @unittest.skipUnless(os.name=='nt','Native Windows reader sharing lock')
    def test_native_windows_database_reader_closes_before_recovery(self):
        r.prepare(self.path);self.update_price()
        handle=self.path.open('rb')
        try:
            with patch.object(b.time,'sleep',side_effect=lambda delay:handle.close()) as sleep:
                r.prepare(self.path)
            self.assertTrue(sleep.called)
            self.assertFalse(self.owner.journal.exists())
            self.assertEqual(self.result()['years'][0]['holdings'][0]['exit_price'],24)
        finally:handle.close()

    def test_windows_sharing_failure_retries_and_retains_recovery_receipt(self):
        r.prepare(self.path);self.update_price();original=Path.replace;attempts=[]
        error=PermissionError('locked');error.winerror=32
        def locked(path,target):
            if Path(target)==self.path:attempts.append(1);raise error
            return original(path,target)
        with patch.object(Path,'replace',locked),patch.object(b.time,'sleep'),self.assertRaisesRegex(ValueError,'interrupted'):r.prepare(self.path)
        self.assertEqual(len(attempts),8);self.assertTrue(self.owner.journal.exists())
        self.owner.recover()
        self.assertEqual(self.result()['years'][0]['holdings'][0]['exit_price'],24)


if __name__=='__main__':unittest.main()
