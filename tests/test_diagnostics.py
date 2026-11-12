"""Persistent, bounded development logs with safe exception traces and timings."""
from contextlib import redirect_stderr
import errno
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT)]
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.runtime import backtest_control
from backtest.runtime import diagnostics as d
from tools.ops import log_summary
from website.server import app as serve
namespace_implementation=d._process_namespace


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.namespace='a'*32
        namespace_patch=patch.object(d,'_process_namespace',return_value=self.namespace)
        namespace_patch.start();self.addCleanup(namespace_patch.stop)
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.addCleanup(d.close)
        self.path=d.configure(Path(self.folder.name))

    def test_file_preserves_error_chains_codes_and_frames_without_secrets(self):
        private='PRIVATE-CREDENTIAL-CANARY'
        url='https://provider.invalid/prices?apikey='+private
        try:
            try:raise OSError(errno.EACCES,private,url)
            except OSError as cause:
                cause.winerror=5
                raise RuntimeError(url) from cause
        except RuntimeError as error:
            d.failure('download.publish_failed',error,asset='px/ACR.json',start='2005-01-01',end='2014-12-31')
        content=self.path.read_text()
        self.assertIn('download.publish_failed',content)
        self.assertIn('px/ACR.json',content)
        self.assertIn('test_diagnostics.py',content)
        self.assertIn('"type": "RuntimeError"',content)
        self.assertIn('"type": "PermissionError"',content)
        self.assertIn('"winerror": 5',content)
        self.assertNotIn(private,content);self.assertNotIn('https:',content)
        self.assertNotIn('raise RuntimeError',content)

    def test_logs_rotate_and_do_not_grow_without_a_bound(self):
        with patch.object(d,'MAX_BYTES',350):
            d.configure(Path(self.folder.name))
        for count in range(30):d.event('download.saved',asset='px/ACR.json',count=count)
        files=list(Path(self.folder.name).glob('*.log*'))
        self.assertEqual(len(files),3)
        self.assertIn('"count": 29',self.path.read_text())

    def test_unavailable_log_directory_does_not_raise(self):
        file=Path(self.folder.name)/'file';file.write_text('occupied')
        self.assertIsNone(d.configure(file))
        d.event('server.starting',port=3000)
        self.assertIsNone(d.log_path())

    def saved_log(self,name,age=0,size=10):
        if name.startswith('website-'):name=name.replace('website-',f'website-{self.namespace}-',1)
        path=Path(self.folder.name)/name
        path.write_bytes(b'x'*size)
        stamp=time.time()-age*86400
        os.utime(path,(stamp,stamp))
        return path

    def test_cleanup_removes_expired_logs_and_backups_only(self):
        old=self.saved_log('website-123456.log',15)
        backup=self.saved_log('website-123456.log.2',15)
        recent=self.saved_log('website-123457.log',1)
        unrelated=self.saved_log('other.log',30)
        with patch.object(d,'_process_running',return_value=False):d.cleanup(self.folder.name)
        self.assertFalse(old.exists());self.assertFalse(backup.exists())
        self.assertTrue(recent.exists());self.assertTrue(unrelated.exists())

    def test_cleanup_size_target_removes_oldest_and_preserves_running_logs(self):
        active=self.saved_log('website-123450.log',30,20)
        oldest=self.saved_log('website-123451.log',3,20)
        newest=self.saved_log('website-123452.log',1,20)
        with patch.object(d,'TOTAL_BYTES',40),patch.object(d,'_process_running',side_effect=lambda pid:pid==123450):
            d.cleanup(self.folder.name)
        self.assertTrue(active.exists());self.assertFalse(oldest.exists());self.assertTrue(newest.exists())

    def test_cleanup_locked_file_does_not_block_other_cleanup_or_startup(self):
        locked=self.saved_log('website-123456.log',30)
        other=self.saved_log('website-123457.log',30)
        unlink=Path.unlink
        def remove(path,*args,**kwargs):
            if path==locked:raise PermissionError('locked')
            return unlink(path,*args,**kwargs)
        with patch.object(d,'_process_running',return_value=False),patch.object(Path,'unlink',remove):
            self.assertIsNotNone(d.configure(self.folder.name))
        self.assertTrue(locked.exists());self.assertFalse(other.exists())

    def test_foreign_and_legacy_logs_are_pruned_by_age_only_without_pid_checks(self):
        folder=Path(self.folder.name);foreign='website-'+('b'*32)
        for name,age in [('website-123456.log',15),(foreign+'-123456.log.1',15),
                         ('website-123457.log',1),(foreign+'-123457.log',1)]:
            path=folder/name;path.write_bytes(b'old')
            stamp=time.time()-age*86400;os.utime(path,(stamp,stamp))
        # A Linux reboot starts a new namespace; its old logs still expire.
        with patch.object(d,'TOTAL_BYTES',0),patch.object(d,'MAX_FILES',0),patch.object(d,'_process_running') as running:
            d.cleanup(folder)
            self.assertTrue(all(call.args==(os.getpid(),) for call in running.call_args_list))
        self.assertEqual(sorted(path.name for path in folder.glob('*.log*')),
                         sorted([self.path.name,'website-123457.log',foreign+'-123457.log']))

    def test_recent_age_only_logs_do_not_use_the_namespace_targets(self):
        stopped=self.saved_log('website-123456.log',1)
        for number in range(3):
            path=Path(self.folder.name)/f'website-{"b"*32}-12346{number}.log';path.write_bytes(b'x')
        # Three recent previous-boot logs must not force out a fresh crash log.
        with patch.object(d,'MAX_FILES',2),patch.object(d,'_process_running',side_effect=lambda pid:pid==os.getpid()):
            d.cleanup(self.folder.name)
        self.assertTrue(stopped.exists())
        self.assertEqual(len(list(Path(self.folder.name).glob('*.log*'))),5)

    def test_unknown_namespace_prunes_by_age_only(self):
        old=self.saved_log('website-123456.log',30)
        recent=self.saved_log('website-123457.log',1)
        with patch.object(d,'_process_namespace',return_value=None),patch.object(d,'TOTAL_BYTES',0),\
                patch.object(d,'_process_running') as running:
            d.cleanup(self.folder.name)
            running.assert_not_called()
        self.assertFalse(old.exists());self.assertTrue(recent.exists())

    def test_cleanup_file_count_target_removes_oldest_stopped_logs(self):
        logs=[self.saved_log(f'website-12345{number}.log',5-number) for number in range(4)]
        with patch.object(d,'MAX_FILES',3),patch.object(d,'_process_running',side_effect=lambda pid:pid in (123450,os.getpid())):
            d.cleanup(self.folder.name)
        # Five files with this process's log: the running oldest stays, the next two go.
        self.assertEqual([path.exists() for path in logs],[True,False,False,True])
        self.assertTrue(self.path.exists())

    def events(self,name):
        return [record for record in d.records(self.folder.name) if record['event']==name]

    def test_operation_records_outcome_time_stages_counts_and_notes(self):
        with d.operation('prepare.example'):
            d.note(force=False)
            with d.stage('books'):time.sleep(.01)
            with d.stage('books'):pass
            d.lap('inputs');d.count('books_calculated');d.count('books_calculated',2)
            d.note(outcome='current',companies=3)
        # Outside an operation the helpers do nothing.
        with d.stage('books'):d.lap('inputs');d.note(companies=4);d.count('books_calculated')
        record,=self.events('prepare.example')
        self.assertEqual((record['outcome'],record['force'],record['companies'],record['level']),('current',False,3,'INFO'))
        self.assertEqual(record['counts'],{'books_calculated':3})
        self.assertEqual(set(record['stages']),{'books','inputs'})
        self.assertGreaterEqual(record['stages']['books'],.01)
        self.assertGreaterEqual(record['seconds'],record['stages']['inputs'])
        self.assertGreaterEqual(record['cpu_seconds'],0)

    def test_operation_failure_keeps_only_the_error_type_and_operations_nest(self):
        @d.operation('outer.example')
        def outer():
            with d.operation('inner.example'):d.count('inner')
            d.count('outer')
            raise RuntimeError('PRIVATE-OPERATION-CANARY')
        with self.assertRaises(RuntimeError):outer()
        with self.assertRaises(backtest_control.Cancelled):
            with d.operation('cancelled.example'):
                d.note(outcome='prepared');raise backtest_control.Cancelled()
        with d.operation('odd.example'):d.note(value=object())
        inner,=self.events('inner.example');failed,=self.events('outer.example');cancelled,=self.events('cancelled.example')
        self.assertEqual((inner['outcome'],inner['counts']),('completed',{'inner':1}))
        self.assertEqual((failed['outcome'],failed['error'],failed['level'],failed['counts']),('failed','RuntimeError','WARNING',{'outer':1}))
        self.assertEqual(cancelled['outcome'],'cancelled')
        self.assertEqual(self.events('diagnostics.unserializable')[0]['operation'],'odd.example')
        self.assertNotIn('PRIVATE-OPERATION-CANARY',self.path.read_text())

    def progress(self):
        return [record for record in d.records(self.folder.name) if 'state' in record]

    def test_long_operation_reports_progress_and_hands_over_to_its_outer_operation(self):
        with patch.object(d,'PROGRESS_SECONDS',.3),patch.object(d,'REPEAT_SECONDS',.3):
            with d.operation('quick.example'):pass
            with d.operation('startup.example'):
                with d.operation('prepare.example'):
                    d.count('prices_parsed',3);d.lap('inputs');d.work(stage='sheets',completed=4,total=9)
                    with d.stage('observation_identity'):time.sleep(1)
                    d.lap('scan')
                d.lap('prepare')  # The inner end line already covers this step.
                time.sleep(.1)
        *running,step,handover=self.progress()
        # Only the innermost operation reports, naming the operations around it, then repeats.
        self.assertGreaterEqual(len(running),2)
        for line in running:
            self.assertEqual({key:line[key] for key in ('event','state','within','last_step','stage','counts','work')},
                             dict(event='prepare.example',state='running',within=['startup.example'],last_step='inputs',
                                  stage='observation_identity',counts=dict(prices_parsed=3),work=dict(stage='sheets',completed=4,total=9)))
            self.assertIn('process_cpu_seconds',line)
        self.assertEqual((step['event'],step['state'],step['step']),('prepare.example','step','scan'))
        self.assertGreaterEqual(step['step_seconds'],.3)
        self.assertEqual((handover['event'],handover['state'],handover['last_step']),('startup.example','running','prepare'))
        ends=[record for record in d.records(self.folder.name) if 'outcome' in record]
        self.assertEqual([record['event'] for record in ends],['quick.example','prepare.example','startup.example'])
        self.assertEqual(handover['op'],ends[2]['op'])
        self.assertEqual({line['op'] for line in running+[step]},{ends[1]['op']})

    def test_outer_operation_of_short_inner_operations_reports_progress(self):
        with patch.object(d,'PROGRESS_SECONDS',.3),patch.object(d,'REPEAT_SECONDS',60):
            with d.operation('queue.example'):
                for _ in range(40):
                    with d.operation('backtest.example'):time.sleep(.03)
        line,=self.progress()
        self.assertEqual((line['event'],line['state']),('queue.example','running'))

    def test_terminal_lines_start_with_the_local_time_once(self):
        output=io.StringIO();terminal=d.Stamped(output)
        with patch.object(d.time,'strftime',return_value='2026-11-05 10:58:12 '):
            print('Prepared daily prices 200/6974',file=terminal)
            terminal.write('two\nlines\n');terminal.write('partial ');terminal.write('line\n\n')
        self.assertEqual(output.getvalue().splitlines(),
            ['2026-11-05 10:58:12 Prepared daily prices 200/6974','2026-11-05 10:58:12 two','2026-11-05 10:58:12 lines',
             '2026-11-05 10:58:12 partial line',''])
        handler=object.__new__(serve.Handler);handler.client_address=('127.0.0.1',5000)
        errors=io.StringIO()
        with patch.object(serve.sys,'stderr',errors):handler.log_message('"%s" %s','GET /\x1b[31m HTTP/1.1',200)
        # The request line drops its own date and still escapes control characters.
        self.assertEqual(errors.getvalue(),'127.0.0.1 "GET /\\x1b[31m HTTP/1.1" 200\n')

    def test_slow_request_logs_route_and_status_without_identifiers_or_query(self):
        self.assertEqual(serve.route('/api/backtest-runs/'+'a'*32+'/evidence?token=PRIVATE'),'/api/backtest-runs/{id}/evidence')
        self.assertEqual(serve.route('/api/backtest-queue/1234'),'/api/backtest-queue/{id}')
        self.assertEqual(serve.route('/data.html?x=1'),'/data.html')
        self.assertEqual(serve.route('http://host/private'),'{other}')
        server=ThreadingHTTPServer(('127.0.0.1',0),serve.Handler);server.daemon_threads=False
        thread=Thread(target=server.serve_forever);thread.start()
        # Joining the handler threads keeps the threshold patch active until they log.
        with patch.object(serve,'SLOW_REQUEST_SECONDS',0),redirect_stderr(io.StringIO()):
            try:
                connection=HTTPConnection('127.0.0.1',server.server_address[1],timeout=10)
                connection.request('GET','/api/launcher');connection.getresponse().read();connection.close()
            finally:
                server.shutdown();server.server_close();thread.join()
        record,=self.events('http.slow')
        self.assertEqual((record['method'],record['route'],record['status']),('GET','/api/launcher',404))

    def test_summary_groups_operations_with_stage_shares_slow_requests_and_failures(self):
        run=dict(event='backtest.run',pid=1,mode='random',strategy=False,pool='legacy',trials=24,periods=480,counts={})
        lines=['2026-11-05T09:59:00Z INFO '+json.dumps(dict(event='backtest.run',pid=1,op=1,state='running',seconds=60.,counts={})),
               '2026-11-05T10:00:00Z INFO '+json.dumps(dict(run,op=1,outcome='completed',seconds=10.,stages=dict(observation_identity=4.,selection=3.))),
               '2026-11-05T10:08:00Z INFO '+json.dumps(dict(event='prepare.research',pid=2,op=3,state='running',seconds=3600.,last_step='commit',
                   since_step_seconds=420.,stage='observation_identity',within=['startup.prepare','prepare.daily'],counts={})),
               # Two runs share a name: the end line of op 5 leaves op 4 unfinished.
               '2026-11-05T10:09:00Z INFO '+json.dumps(dict(event='backtest.run',pid=3,op=4,state='step',step='companies',step_seconds=120.,seconds=600.)),
               '2026-11-05T10:09:30Z INFO '+json.dumps(dict(event='backtest.run',pid=3,op=5,mode='latest',outcome='completed',seconds=1.,stages={},counts={})),
               # A later server reuses pid 4: its operation 1 does not end the earlier one.
               '2026-11-05T10:10:00Z INFO '+json.dumps(dict(event='data.job',pid=4,op=1,state='running',seconds=60.,counts={})),
               '2026-11-05T10:11:00Z INFO '+json.dumps(dict(event='server.starting',pid=4)),
               '2026-11-05T10:12:00Z INFO '+json.dumps(dict(event='data.job',pid=4,op=1,outcome='completed',seconds=5.,stages={},counts={})),
               '2026-11-05T10:05:00Z WARNING '+json.dumps(dict(run,outcome='failed',error='OSError',seconds=2.,stages=dict(selection=1.))),
               '2026-11-05T10:06:00Z INFO '+json.dumps(dict(event='http.slow',pid=1,method='GET',route='/api/backtests/{id}',status=200,seconds=1.5)),
               '2026-11-05T10:07:00Z ERROR '+json.dumps(dict(event='queue.test_failed',pid=1,errors=[dict(type='OSError',frames=[])])),
               'not an event line']
        (Path(self.folder.name)/f'website-{self.namespace}-123.log').write_text('\n'.join(lines)+'\n')
        text='\n'.join(log_summary.summarize(list(d.records(self.folder.name))))
        self.assertRegex(text,r'backtest\.run random legacy completed +1 +10\.0s .*observation_identity 40%, selection 30%')
        self.assertRegex(text,r'backtest\.run random legacy failed +1 +2\.00s .*selection 50%')
        self.assertIn('periods=480 trials=24',text)
        self.assertRegex(text,r'GET /api/backtests/\{id\} +1 +median 1\.50s')
        self.assertRegex(text,r'queue\.test_failed +OSError +1 +last 2026-11-05T10:07:00Z')
        # A running line with a later end line is finished; one without is listed.
        self.assertIn('2026-11-05T10:08:00Z  prepare.research  pid 2  3600.0s in  after step commit (420.0s ago)  in observation_identity'
                      '  within startup.prepare > prepare.daily',text)
        self.assertIn('2026-11-05T10:09:00Z  backtest.run  pid 3  600.0s in  step companies ended after 120.0s',text)
        self.assertIn('2026-11-05T10:10:00Z  data.job  pid 4  60.0s in',text)
        self.assertNotIn('backtest.run  pid 1',text)
        only=dict(event='prepare.daily',pid=5,op=1,state='running',seconds=90.,counts={},time='2026-11-05T11:00:00Z',level='INFO')
        self.assertEqual(log_summary.summarize([only])[1:],['2026-11-05T11:00:00Z  prepare.daily  pid 5  90.0s in','',
                                                            'No timed operation has finished yet.'])

    def test_native_namespace_is_stable(self):
        # Exercise the real OS implementation despite the retention fixture.
        with patch.object(d,'_process_namespace',namespace_implementation):
            first=d._process_namespace()
            self.assertEqual(first,d._process_namespace())
            if os.name=='nt' or sys.platform.startswith('linux'):
                self.assertRegex(first,r'^[0-9a-f]{32}$')

    def test_live_and_exited_child_process(self):
        child=subprocess.Popen([sys.executable,'-c','import sys; sys.stdin.read()'],stdin=subprocess.PIPE)
        try:
            self.assertTrue(d._process_running(child.pid))
            child.communicate(timeout=10)
            self.assertFalse(d._process_running(child.pid))
        finally:
            if child.poll() is None:
                child.kill();child.communicate(timeout=10)

    @unittest.skipUnless(os.name=='nt','Windows process API')
    def test_windows_inaccessible_and_uncertain_process_is_protected(self):
        import ctypes
        from unittest.mock import MagicMock
        kernel=MagicMock()
        with patch.object(ctypes,'WinDLL',return_value=kernel),patch.object(ctypes,'get_last_error',return_value=5):
            kernel.OpenProcess.return_value=0
            self.assertTrue(d._process_running(123456))
            kernel.OpenProcess.return_value=42
            kernel.WaitForSingleObject.return_value=0xffffffff
            self.assertTrue(d._process_running(123456))
            kernel.CloseHandle.assert_called_once_with(42)

    def test_current_process_is_protected_and_unknown_state_is_conservative(self):
        self.assertTrue(d._process_running(os.getpid()))
        if os.name!='nt':
            with patch.object(d.os,'kill',side_effect=PermissionError):self.assertTrue(d._process_running(123456))
            with patch.object(d.os,'kill',side_effect=ProcessLookupError):self.assertFalse(d._process_running(123456))

    def test_http_failure_supports_python310_without_sys_exception(self):
        server=object.__new__(serve.Server)
        legacy_sys=SimpleNamespace(exc_info=sys.exc_info,stderr=io.StringIO())
        with patch.object(serve,'sys',legacy_sys):
            self.assertFalse(hasattr(serve.sys,'exception'))
            try:raise RuntimeError('PRIVATE-REQUEST-CANARY')
            except RuntimeError:server.handle_error(None,None)
        content=self.path.read_text()
        self.assertIn('http.failed',content)
        self.assertNotIn('PRIVATE-REQUEST-CANARY',content)


if __name__=='__main__':unittest.main()
