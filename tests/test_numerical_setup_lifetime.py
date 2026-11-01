"""Actual setup-probe owner death during a contained synthetic compilation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
ROOT=Path(__file__).absolute().parents[1]
sys.path.insert(0,str(ROOT))
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.engines.numerical import toolchain as native
from website import runtime_access

FAKE=r'''
use std::{env,fs,process::{self,Command,Stdio},thread,time::Duration};
fn main(){
 let args:Vec<String>=env::args().collect();
 if args.iter().any(|v|v=="-vV"){println!("host: fixture");return;}
 if args.iter().any(|v|v=="--descendant"){loop{thread::sleep(Duration::from_millis(100));}}
 let child=Command::new(env::current_exe().unwrap()).arg("--descendant").stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn().unwrap();
 let out=args.iter().position(|v|v=="-o").unwrap();
 let parent=std::path::Path::new(&args[out+1]).parent().unwrap();
 fs::write(parent.join("compiling.json"),format!("{{\"compiler\":{},\"descendant\":{}}}",process::id(),child.id())).unwrap();
 loop{thread::sleep(Duration::from_millis(100));}
}
'''

OWNER=r'''
import json,sys,time
from pathlib import Path
root,request,state=map(Path,sys.argv[1:])
sys.path.insert(0,str(root))
from website import runtime_access
with runtime_access.ownership(root):
 sys.path.insert(0,str(root))
 from backtest.runtime.cache_access import WorkspaceAccess
 from backtest.runtime.process_owner import OwnedProcess
 with WorkspaceAccess(root/'data/numerical-native/setup.lock').hold():
  owner=OwnedProcess([sys.executable,'-I','-B',str(root/'backtest/engines/numerical/toolchain_probe.py'),str(request)])
  owner.process.stdin.write('GO\n');owner.process.stdin.flush()
  state.write_text(json.dumps({'probe':owner.process.pid}))
  while True:time.sleep(.05)
'''


class SetupLifetimeTests(unittest.TestCase):
    def test_installer_death_drains_compiler_descendant_and_releases_own_source_guard(self):
        from backtest.runtime.process_owner import OwnedProcess, windows_processes
        with tempfile.TemporaryDirectory(prefix='cb19g-setup-death-') as folder:
            root=Path(folder)/'source';root.mkdir()
            for name in ('backtest/engines/numerical/toolchain_probe.py','backtest/runtime/process_owner.py','backtest/runtime/cache_access.py','backtest/__init__.py','backtest/paths.py','website/runtime_access.py'):
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
            descriptor=native.inspect_toolchain(ROOT)
            fake=root/('fake-compiler.exe' if os.name=='nt' else 'fake-compiler')
            source=root/'fake.rs';source.write_text(FAKE)
            command=[descriptor['compiler'],'--edition=2021','-C','linker='+str(Path(descriptor['directory'])/descriptor['linker']['path']),str(source),'-o',str(fake)]
            subprocess.run(command,env=native.environment(descriptor),check=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            scratch=root/'data/numerical-native/unpublished';scratch.mkdir(parents=True)
            request=scratch/'request.json'
            request.write_text(json.dumps(dict(scratch=str(scratch),descriptor=dict(compiler=str(fake),directory=str(root),linker={'path':'unused'}))))
            state=root/'owner.json';log=root/'owner.log'
            with log.open('wb') as output:
                parent=subprocess.Popen([sys.executable,'-I','-B','-c',OWNER,str(root),str(request),str(state)],stdout=output,stderr=subprocess.STDOUT)
                try:
                    until=time.monotonic()+30
                    while not (scratch/'compiling.json').exists():
                        if parent.poll() is not None or time.monotonic()>until:self.fail('Synthetic setup compilation did not start: '+log.read_text(errors='replace'))
                        time.sleep(.025)
                    pids=dict(json.loads(state.read_bytes()),**json.loads((scratch/'compiling.json').read_bytes()))
                    with self.assertRaises(RuntimeError):
                        with runtime_access.ownership(root,exclusive=True,timeout=0):pass
                    parent.kill();parent.wait(timeout=10)
                    def alive(pid):
                        if os.name=='nt':return str(pid) in windows_processes(include_pids=[pid])
                        try:return Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[0]!='Z'
                        except FileNotFoundError:return False
                    until=time.monotonic()+35
                    while any(alive(pid) for pid in pids.values()):
                        if time.monotonic()>until:self.fail('Setup descendants survived installer death.')
                        time.sleep(.025)
                    with runtime_access.ownership(root,exclusive=True,timeout=0):pass
                    self.assertFalse((root/'data/numerical-native/installation.json').exists())
                    self.assertFalse((scratch/'verified.json').exists())
                    print(json.dumps(dict(check='setup-owner-death-during-compilation',platform=sys.platform,pids=pids,
                        all_exited=True,source_released=True,unpublished=True)),flush=True)
                finally:
                    if parent.poll() is None:parent.kill();parent.wait(timeout=10)

if __name__=='__main__':unittest.main()
