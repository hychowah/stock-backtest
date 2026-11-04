"""Committed-main updates and cooperative native shutdown. Synthetic inputs only."""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))
from contextlib import ExitStack
import json
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import time
from threading import Thread
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tools.ops.deploy as d
from website import runtime_access
class Child:
    def __init__(self,code=None):self.returncode=code;self.waits=[]
    def poll(self):return self.returncode
    def wait(self,timeout=None):
        self.waits.append(timeout)
        self.returncode=0
        return self.returncode


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.context=ExitStack();self.addCleanup(self.context.close)
        self.root=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.config=dict(runtime=str(self.root),python=sys.executable,source='/fixture/source',distro='Fixture')
        self.context.enter_context(patch.object(d,'linux_path',side_effect=Path))

    def test_main_poll_uses_committed_branch_and_bounds_git_wait(self):
        with patch.object(d.subprocess,'check_output',return_value=b'a'*40+b'\n') as git:
            self.assertEqual(d.main_revision(),'a'*40)
        self.assertEqual(git.call_args.args[0][-1],'refs/heads/main^{commit}')
        self.assertEqual(git.call_args.kwargs['timeout'],5)
        for failure in (OSError(),subprocess.CalledProcessError(1,['git']),subprocess.TimeoutExpired(['git'],5)):
            with patch.object(d.subprocess,'check_output',side_effect=failure):self.assertIsNone(d.main_revision())
        with patch.object(d.subprocess,'check_output',return_value=b'not-a-commit'):self.assertIsNone(d.main_revision())

    def test_update_replaces_once_and_unknown_git_keeps_serving(self):
        old,new=Child(),Child(0);tokens=[];installed=[]
        def spawn(config,arguments,token):tokens.append(token);return old if len(tokens)==1 else new
        def install(config,commit,**options):
            installed.append(commit)
            if options:
                options['before_publish']()
                self.assertEqual(old.waits,[30])
                self.assertFalse((self.root/'data'/('website-update-stop-'+tokens[0])).exists())
                old.returncode=0
        with patch.object(d,'main_revision',side_effect=['a'*40,None,'a'*40,'b'*40]),patch.object(d,'install_latest',side_effect=install),patch.object(d,'spawn_server',side_effect=spawn) as run,patch.object(d.time,'sleep'):
            self.assertEqual(d.follow_main(self.config,['--port','4312']),0)
        self.assertEqual(installed,['a'*40,'b'*40]);self.assertEqual(run.call_count,2)
        self.assertEqual(run.call_args.args[1],['--port','4312','--no-browser'])
        self.assertNotEqual(tokens[0],tokens[1])
        self.assertFalse((self.root/'data'/('website-update-stop-'+tokens[0])).exists())

    def test_failed_update_retries_exact_intent_before_following_new_tip(self):
        old,new=Child(),Child(0);attempts=[]
        def install(config,commit,**options):
            attempts.append(commit)
            if len(attempts)==2:raise OSError('fixture staging failure')
            if options:options['before_publish']();old.returncode=0
        with patch.object(d,'main_revision',side_effect=['a'*40,'b'*40,'c'*40]),patch.object(d,'install_latest',side_effect=install),patch.object(d,'spawn_server',side_effect=[old,new]),patch.object(d.time,'sleep'):
            self.assertEqual(d.follow_main(self.config,[]),0)
        self.assertEqual(attempts,['a'*40,'b'*40,'b'*40])

    def test_pending_publication_finishes_before_new_main_selection(self):
        pending=self.root/d.PENDING;pending.parent.mkdir();pending.write_text('fixture intent')
        callback=Mock()
        def publish(config,revision=None,**kwargs):
            if revision is None:pending.unlink()
        with patch.object(d,'deployment_revision',return_value='b'*40),patch.object(d,'deploy',side_effect=publish) as publish:
            d.install_latest(self.config,'c'*40,before_publish=callback)
        self.assertEqual([call.args for call in publish.call_args_list],[(self.config,),(self.config,'c'*40)])
        self.assertTrue(all(call.kwargs['before_publish'] is callback for call in publish.call_args_list))

    def test_interrupt_stops_only_this_child_and_preserves_other_markers(self):
        child=Child();token='a'*32
        foreign=self.root/'data'/('website-update-stop-'+'b'*32)
        foreign.parent.mkdir();foreign.write_text('keep')
        with patch.object(d,'main_revision',return_value='a'*40),patch.object(d,'install_latest'),patch.object(d,'spawn_server',return_value=child),patch.object(d.uuid,'uuid4',return_value=Mock(hex=token)),patch.object(d.time,'sleep',side_effect=KeyboardInterrupt):
            self.assertEqual(d.follow_main(self.config,[]),130)
        self.assertEqual(child.waits,[30]);self.assertEqual(foreign.read_text(),'keep')
        self.assertFalse((foreign.parent/('website-update-stop-'+token)).exists())

    def test_external_child_exit_ends_the_old_controller(self):
        child=Child(7)
        with patch.object(d,'main_revision',return_value='a'*40) as tip,patch.object(d,'install_latest') as install,patch.object(d,'spawn_server',return_value=child):
            self.assertEqual(d.follow_main(self.config,[]),7)
        self.assertEqual(tip.call_count,1);self.assertEqual(install.call_count,1)

    def test_spawn_keeps_native_terminal_and_private_stop_identity(self):
        with patch.object(d.subprocess,'Popen',return_value=Child()) as run:
            d.spawn_server(self.config,['--no-browser'],'a'*32)
        command=run.call_args.args[0]
        self.assertEqual(command[0],sys.executable)
        self.assertEqual(command[-2:],['--managed','--no-browser'])
        self.assertEqual(run.call_args.kwargs['env'][d.SUPERVISOR_ENV],'a'*32)
        self.assertIn(d.SUPERVISOR_ENV,run.call_args.kwargs['env']['WSLENV'].split(':'))
        self.assertNotIn('stdout',run.call_args.kwargs)

    def test_start_defaults_to_following_main_and_explicit_revision_is_fixed(self):
        for selection in ([],['--revision','a'*40]):
            with patch.object(sys,'argv',['deploy.py','--start','--no-browser',*selection]),patch.object(d.os,'name','posix'),patch.object(d,'configuration',return_value=self.config),patch.object(d,'follow_main',return_value=0) as follow,patch.object(d,'deploy') as publish,patch.object(d,'native') as native:
                if selection:
                    d.main();follow.assert_not_called();publish.assert_called_once_with(self.config,'a'*40)
                    self.assertEqual(native.call_args.args[-2:],('--managed','--no-browser'))
                else:
                    with self.assertRaises(SystemExit) as result:d.main()
                    self.assertEqual(result.exception.code,0)
                    follow.assert_called_once_with(self.config,['--no-browser'],check=False)
                    publish.assert_not_called();native.assert_not_called()


class NativeStopTests(unittest.TestCase):
    def setUp(self):
        self.context=ExitStack();self.addCleanup(self.context.close)
        self.root=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        website=self.root/'website';website.mkdir(); (website/'server').mkdir(); (website/'__init__.py').write_text(''); (website/'server/__init__.py').write_text('')
        for name in ('serve.py','runtime_access.py'):shutil.copy2(ROOT/'website'/name,website/name)
        self.website=website;self.token='c'*32
        self.config=dict(runtime=str(self.root))
        self.context.enter_context(patch.object(d,'linux_path',side_effect=Path))

    def spawn(self,app):
        (self.website/'server/app.py').write_text(app)
        child=subprocess.Popen([sys.executable,'-B',str(self.website/'serve.py')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                               env=dict(os.environ,**{d.SUPERVISOR_ENV:self.token}))
        def close():
            if child.poll() is None:child.kill()
            child.communicate()
        self.addCleanup(close);self.child=child;return child

    def until(self,path):
        deadline=time.monotonic()+5
        while not path.exists() and time.monotonic()<deadline:time.sleep(.02)
        if not path.exists() and self.child.poll() is not None:
            output,error=self.child.communicate()
            self.fail(error.decode())
        self.assertTrue(path.exists())

    def test_stop_during_source_wait_never_imports_application(self):
        with runtime_access.ownership(self.root,exclusive=True):
            child=self.spawn('from pathlib import Path\nPath(__file__).parents[2].joinpath("imported").write_text("yes")\ndef main(): pass\n')
            time.sleep(.2)
            d.request_child_stop(self.config,self.token)
            output,error=child.communicate(timeout=5)
        self.assertEqual(child.returncode,0,error)
        self.assertFalse((self.root/'imported').exists())

    def test_cleanup_retains_source_ownership_until_application_finishes(self):
        child=self.spawn('from pathlib import Path\nimport time\nroot=Path(__file__).parents[2]\n'
                        'def main():\n root.joinpath("ready").write_text("yes")\n try:\n  while True:time.sleep(.02)\n'
                        ' finally:\n  root.joinpath("closing").write_text("yes")\n  while not root.joinpath("release").exists():time.sleep(.02)\n')
        self.until(self.root/'ready');d.request_child_stop(self.config,self.token);self.until(self.root/'closing')
        with self.assertRaises(RuntimeError):
            with runtime_access.ownership(self.root,exclusive=True,timeout=.05):pass
        (self.root/'release').write_text('yes');output,error=child.communicate(timeout=5)
        self.assertEqual(child.returncode,0,error)
        with runtime_access.ownership(self.root,exclusive=True,timeout=.1):pass

    def test_supervisor_joins_queue_before_releasing_source(self):
        # Use current application owners with a slow synthetic calculation.
        # The bootstrap and all durable output stay in this disposable root.
        app=f'''import importlib.util,sys,time,json
from pathlib import Path
from unittest.mock import patch
source=Path({str(ROOT)!r});root=Path(__file__).parents[2]
sys.path.insert(0,str(source))
import website,website.server
website.__path__.insert(0,str(source/'website'))
website.server.__path__.insert(0,str(source/'website/server'))
spec=importlib.util.spec_from_file_location('website.server._integrated_app',source/'website/server/app.py')
app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
from backtest.runtime import backtest_control
from backtest.application import queue as backtest_queue
store=backtest_queue.Store(root/'queue.sqlite')
options=dict(engine='original',start='2015-01-01',end='2016-12-30',months=3,trials=2,seed=42)
plan=dict(options={{}},start=options['start'],end=options['end'],months=3,requested=2,seed=42,samples=[['2015-01-02']])
item=store.enqueue(dict(id='a'*32,name='Interrupted',mode='random',options=options,catalog=dict(metrics={{}},filters={{}}),presentation={{}}))
def slow(mode,options,progress,configuration,**kwargs):
 configuration(plan);root.joinpath('ready').write_text('yes')
 try:
  while True:backtest_control.checkpoint();time.sleep(.02)
 finally:
  root.joinpath('closing').write_text('yes')
  while not root.joinpath('release').exists():time.sleep(.02)
Base=app.Server
class Server(Base):
 def __init__(self,*args,**kwargs):
  with patch.object(app.backtest_queue,'Store',return_value=store):super().__init__(*args,**kwargs)
  self.calculations.calculate=slow
app.Server=Server
def main():
 with patch.object(app.cache_access,'access',side_effect=lambda:__import__('contextlib').nullcontext()),patch.object(app.cache_assets,'source_problem',return_value=False),patch.object(app,'ensure_ready'),patch.object(app.diagnostics,'configure',return_value=None):
  app.main(arguments=['--host','127.0.0.1','--port','0','--no-browser'])
 value=store.get(item['id']);replayed=store.claim()
 assert value['state']=='queued' and value['options']==options
 assert json.loads(replayed['plan'])==plan
 root.joinpath('recovered.json').write_text(json.dumps(dict(state=value['state'],engine=value['options']['engine'],plan=json.loads(replayed['plan']))))
'''
        child=self.spawn(app)
        self.until(self.root/'ready')
        d.request_child_stop(self.config,self.token)
        self.until(self.root/'closing')
        with self.assertRaises(RuntimeError):
            with runtime_access.ownership(self.root,exclusive=True,timeout=.05):pass
        (self.root/'release').write_text('yes')
        output,error=child.communicate(timeout=10)
        self.assertEqual(child.returncode,0,error.decode(errors='replace'))
        recovered=json.loads((self.root/'recovered.json').read_text())
        self.assertEqual((recovered['state'],recovered['engine'],recovered['plan']['seed']),('queued','original',42))
        with runtime_access.ownership(self.root,exclusive=True,timeout=.1):pass


@unittest.skipUnless(shutil.which('git'),'Private committed-source integration check requires Git.')
class CommittedUpdateTests(unittest.TestCase):
    def test_running_native_child_automatically_moves_to_the_next_main_commit(self):
        from website.server import launcher
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';runtime=root/'runtime';source.mkdir();runtime.mkdir()
            git=shutil.which('git')
            def command(*arguments):
                return [git,'--git-dir='+str(source/'.git-local'),'--work-tree='+str(source),*arguments]
            subprocess.run([git,'init','-q','--initial-branch=main','--separate-git-dir',str(source/'.git-local'),str(source)],check=True)
            for key,value in [('user.name','Fixture'),('user.email','fixture@example.invalid')]:
                subprocess.run(command('config',key,value),check=True)
            website=source/'website';website.mkdir(); (website/'server').mkdir(); (website/'__init__.py').write_text(''); (website/'server/__init__.py').write_text('')
            shutil.copytree(ROOT/'tools',source/'tools',ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(ROOT/'backtest',source/'backtest',ignore=shutil.ignore_patterns('__pycache__'))
            for name in ('serve.py','runtime_access.py','server/launcher.py'):shutil.copy2(ROOT/'website'/name,website/name)
            def app(version):
                return ('from pathlib import Path\nfrom http.server import BaseHTTPRequestHandler,ThreadingHTTPServer\nfrom website.server import launcher\n'
                        'def main():\n'
                        ' class Handler(BaseHTTPRequestHandler):\n'
                        '  def do_GET(self): launcher_owner.control(self)\n'
                        '  def do_POST(self): launcher_owner.control(self)\n'
                        '  def reply(self,status,value):\n'
                        '   import json\n   body=json.dumps(value).encode()\n'
                        '   self.send_response(status)\n   self.end_headers()\n   self.wfile.write(body)\n'
                        '  def log_message(self,*args): pass\n'
                        ' with launcher.Lifecycle(0,"127.0.0.1") as launcher_owner:\n'
                        '  server=ThreadingHTTPServer(("127.0.0.1",0),Handler)\n'
                        '  launcher_owner.attach(server)\n'
                        f'  Path(__file__).parents[2].joinpath("served-version").write_text({version!r})\n'
                        '  server.serve_forever()\n')
            path=website/'server/app.py';path.write_text(app('first'))
            subprocess.run(command('add','website','tools'),check=True)
            subprocess.run(command('commit','-qm','First fixture'),check=True)
            first=subprocess.check_output(command('rev-parse','HEAD')).decode().strip()
            for name in ('raw/keep.json','data/research.sqlite','data/saved-backtests.sqlite','data/backtest-queue.sqlite','results/summary-exits.txt'):
                saved=runtime/name;saved.parent.mkdir(exist_ok=True,parents=True);saved.write_bytes(b'preserve fixture')
            config=dict(source=str(source),distro='Fixture',runtime=str(runtime),python=sys.executable)
            outcome=[]
            def publish(config,bootstrap,operation,stage,target):
                self.assertEqual(operation,'--native-publish')
                payload,manifest=d.unpack(Path(stage))
                d.publish(Path(target),payload,manifest)
            def run():
                try:outcome.append(d.follow_main(config,['--no-browser']))
                except BaseException as error:outcome.append(error)
            def until(predicate):
                deadline=time.monotonic()+10
                while time.monotonic()<deadline:
                    if predicate():return
                    if outcome:break
                    time.sleep(.02)
                self.fail('Automatic update did not complete: '+repr(outcome))
            def version(expected):
                try:return (runtime/'served-version').read_text()==expected
                except FileNotFoundError:return False
            with patch.object(d,'ROOT',source),patch.object(d,'git_command',side_effect=command),patch.object(d,'windows_path',side_effect=str),patch.object(d,'linux_path',side_effect=Path),patch.object(d,'native',side_effect=publish),patch.object(d,'UPDATE_POLL_SECONDS',.03):
                thread=Thread(target=run,daemon=True);thread.start()
                try:
                    until(lambda:version('first'))
                    self.assertEqual(d.read_json(runtime/d.MANIFEST)['commit'],first)
                    path.write_text(app('second'))
                    time.sleep(.15)
                    self.assertTrue(version('first'),'Uncommitted source must not be published')
                    subprocess.run(command('add','website/server/app.py'),check=True)
                    subprocess.run(command('commit','-qm','Second fixture'),check=True)
                    second=subprocess.check_output(command('rev-parse','HEAD')).decode().strip()
                    until(lambda:version('second'))
                    self.assertEqual(d.read_json(runtime/d.MANIFEST)['commit'],second)
                    for name in ('raw/keep.json','data/research.sqlite','data/saved-backtests.sqlite','data/backtest-queue.sqlite','results/summary-exits.txt'):
                        self.assertEqual((runtime/name).read_bytes(),b'preserve fixture')
                finally:
                    state=d.read_json(runtime/'data'/'website-server-0.json')
                    if state:
                        try:launcher.request(state,'/api/launcher','POST')
                        except (OSError,ValueError):pass
                    thread.join(10)
                self.assertFalse(thread.is_alive());self.assertEqual(outcome,[0])


@unittest.skipUnless(os.name=='posix' and os.environ.get('WSL_INTEROP'),'WSL/native launch check requires WSL.')
class WslInteropTests(unittest.TestCase):
    def test_real_windows_child_observes_its_wsl_stop_marker(self):
        registered=d.read_json(ROOT/d.CONFIG)
        if not registered:self.skipTest('No registered native Python interpreter.')
        executable=d.linux_path(registered['python'])
        if not executable.is_file():self.skipTest('Registered native Python is unavailable.')
        temporary=subprocess.check_output([str(executable),'-c','import tempfile; print(tempfile.gettempdir())'],text=True).strip()
        with tempfile.TemporaryDirectory(prefix='ebitda-wsl-stop-',dir=d.linux_path(temporary)) as folder:
            root=Path(folder);website=root/'website';website.mkdir(); (website/'server').mkdir(); (website/'__init__.py').write_text(''); (website/'server/__init__.py').write_text('')
            for name in ('serve.py','runtime_access.py'):shutil.copy2(ROOT/'website'/name,website/name)
            (website/'server/app.py').write_text('from pathlib import Path\nimport time\nroot=Path(__file__).parents[2]\n'
                'def main():\n root.joinpath("ready").write_text("yes")\n try:\n  while True:time.sleep(.02)\n'
                ' finally:root.joinpath("closed").write_text("yes")\n')
            config=dict(registered,runtime=d.windows_path(root));token='d'*32
            child=d.spawn_server(config,['--no-browser'],token)
            try:
                deadline=time.monotonic()+10
                while not (root/'ready').exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue((root/'ready').exists())
            finally:d.stop_child(config,child,token)
            self.assertEqual(child.returncode,0);self.assertTrue((root/'closed').exists())


if __name__=='__main__':unittest.main()
