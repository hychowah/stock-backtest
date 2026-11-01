"""Managed offline native availability, integrity and contained setup."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).absolute().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import numerical_toolchain as native


class NativeInventoryTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name);self.first=self.root/'first';self.first.write_bytes(b'one')

    def test_hardlink_aliases_hash_once_each_call_and_changed_content_is_rechecked(self):
        alias=self.root/'alias';os.link(self.first,alias)
        expected=native.sha(self.first);files={'first':expected,'alias':expected}
        with patch.object(native,'sha',wraps=native.sha) as hashing:
            native._files(self.root,files,complete=True);self.assertEqual(hashing.call_count,1)
            native._files(self.root,files,complete=True);self.assertEqual(hashing.call_count,2)
            self.first.write_bytes(b'two')
            with self.assertRaises(ImportError):native._files(self.root,files,complete=True)
            self.assertEqual(hashing.call_count,3)

    def test_distinct_files_and_zero_inode_each_receive_content_hashes(self):
        second=self.root/'second';second.write_bytes(b'one');expected=native.sha(self.first)
        with patch.object(native,'sha',wraps=native.sha) as hashing:
            native._files(self.root,{'first':expected,'second':expected});self.assertEqual(hashing.call_count,2)
        second.unlink();os.link(self.first,second)
        original=Path.stat
        def no_inode(path,*args,**kwargs):
            from types import SimpleNamespace
            value=original(path,*args,**kwargs)
            return SimpleNamespace(st_ino=0,**{name:getattr(value,name) for name in
                ('st_dev','st_size','st_mode','st_mtime_ns','st_ctime_ns')})
        with patch.object(Path,'stat',no_inode),patch.object(native,'sha',wraps=native.sha) as hashing:
            native._files(self.root,{'first':expected,'second':expected});self.assertEqual(hashing.call_count,2)

    def test_metadata_change_during_hash_and_extra_inventory_are_rejected(self):
        expected=native.sha(self.first);original=native.sha
        def changed(path):
            value=original(path);stamp=path.stat()
            os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+1_000_000));return value
        with patch.object(native,'sha',side_effect=changed):
            with self.assertRaises(ImportError):native._files(self.root,{'first':expected})
        (self.root/'extra').write_bytes(b'untracked')
        with self.assertRaises(ImportError):native._files(self.root,{'first':expected},complete=True)
        with self.assertRaises(ValueError):native._files(self.root,{'../escape':expected})


class NativeInstallationTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)

    def test_missing_is_offline_and_ambient_rust_does_not_supply_installation(self):
        from unittest.mock import patch
        with patch.dict(os.environ,BACKTEST_RUSTC='private-ambient',BACKTEST_RUST_LINKER='private-ambient'):
            with self.assertRaises(ImportError):native.inspect_toolchain(self.root)

    def test_actual_setup_probe_receipt_content_and_changed_component_rejection(self):
        installed=native.inspect_toolchain(ROOT)
        manifest={key:deepcopy(installed['receipt'][key]) for key in
            ('schema','platform','machine','compiler','target','files','linker','provenance')}
        result=native.setup_toolchain(self.root,installed['directory'],manifest)
        self.assertTrue(result['receipt']['probe']['closed'])
        self.assertTrue(result['receipt']['probe']['library_closed'])
        self.assertEqual(result['receipt']['probe']['answer'],19)
        self.assertEqual(result['receipt']['files'],manifest['files'])
        component=Path(result['compiler']);saved=component.read_bytes()
        component.write_bytes(saved+b'changed')
        with self.assertRaises(ImportError):native.inspect_toolchain(self.root)
        component.write_bytes(saved)
        self.assertEqual(native.inspect_toolchain(self.root)['signature'],result['signature'])
        missing=next(Path(result['directory'])/name for name in manifest['files'] if name.endswith('.rmeta'))
        missing.unlink()
        with self.assertRaises(ImportError):native.inspect_toolchain(self.root)
        print(json.dumps(dict(check='managed-offline-native-installation',platform=sys.platform,
            target=result['target'],files=len(manifest['files']),contained_probe=result['receipt']['probe'],
            changed_and_missing_rejected=True)),flush=True)

    def test_bad_checksum_and_foreign_platform_never_publish(self):
        installed=native.inspect_toolchain(ROOT)
        manifest={key:deepcopy(installed['receipt'][key]) for key in
            ('schema','platform','machine','compiler','target','files','linker','provenance')}
        manifest['files'][manifest['compiler']]='0'*64
        with self.assertRaises(ImportError):native.setup_toolchain(self.root,installed['directory'],manifest)
        self.assertFalse((native.location(self.root)/'installation.json').exists())
        manifest['platform']='other'
        with self.assertRaises(ImportError):native.setup_toolchain(self.root,installed['directory'],manifest)

    def fixture_manifest(self):
        components=self.root/'components';(components/'bin').mkdir(parents=True)
        compiler=components/'bin/rustc';compiler.write_bytes(b'fictional compiler bytes')
        return components,dict(schema=2,platform=sys.platform,machine='fixture',compiler='bin/rustc',target='fixture',
            files={'bin/rustc':native.sha(compiler)},linker={'path':'bin/rustc','environment':{}},provenance={'fixture':True})

    def test_constructor_retained_owner_and_failed_close_keep_installation_until_retry(self):
        from unittest.mock import patch,Mock
        components,manifest=self.fixture_manifest()
        owner=Mock();owner.close.side_effect=[TimeoutError('private'),None]
        error=RuntimeError('private');error.owned_process=owner
        operation=native.Installation(self.root/'application',components,manifest,None)
        with patch.object(native,'_requirements'),patch.object(native,'environment',return_value={}),patch('process_owner.OwnedProcess',side_effect=error):
            with self.assertRaises(native.SetupClosureError) as caught:operation.run()
        self.assertIs(caught.exception.installation,operation)
        self.assertTrue(operation.directory.is_dir());self.assertIs(operation.owner,owner)
        self.assertIn(id(operation),native._PENDING)
        operation.close();self.assertFalse(operation.directory.exists());self.assertNotIn(id(operation),native._PENDING)

    def test_failure_after_receipt_publication_never_removes_current_installation(self):
        from unittest.mock import patch,Mock
        components,manifest=self.fixture_manifest()
        operation=native.Installation(self.root/'application',components,manifest,None)
        owner=Mock(closed=True);owner.process.returncode=0
        def started():
            (operation.scratch/'verified.json').write_text(json.dumps(dict(answer=19,library_closed=True,version='host: fixture\n')))
        owner.process.stdin.flush.side_effect=started
        with patch.object(native,'_requirements'),patch.object(native,'environment',return_value={}),patch('process_owner.OwnedProcess',return_value=owner),patch.object(native,'inspect_toolchain',side_effect=ImportError('changed after publication')):
            with self.assertRaises(ImportError):operation.run()
        self.assertTrue(operation.published);self.assertTrue(operation.closed)
        self.assertTrue(operation.directory.is_dir())
        self.assertEqual(json.loads((operation.base/'installation.json').read_bytes())['directory'],operation.directory.name)

    def test_interrupt_after_durable_replace_preserves_current_installation(self):
        from unittest.mock import patch,Mock
        import numerical_runtime
        components,manifest=self.fixture_manifest()
        operation=native.Installation(self.root/'application',components,manifest,None)
        owner=Mock(closed=True);owner.process.returncode=0
        owner.process.stdin.flush.side_effect=lambda:(operation.scratch/'verified.json').write_text(json.dumps(dict(answer=19,library_closed=True,version='host: fixture\n')))
        original=numerical_runtime.write_payload
        def interrupted(*args,**kwargs):original(*args,**kwargs);raise KeyboardInterrupt()
        with patch.object(native,'_requirements'),patch.object(native,'environment',return_value={}),patch('process_owner.OwnedProcess',return_value=owner),patch.object(numerical_runtime,'write_payload',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):operation.run()
        self.assertTrue(operation.published);self.assertTrue(operation.directory.is_dir());self.assertTrue(operation.closed)

    def test_ambient_benchmark_build_root_cannot_redirect_selected_storage(self):
        from unittest.mock import patch
        import numerical_rust
        expected=numerical_rust._build_root()
        with patch.dict(os.environ,BACKTEST_RUST_BUILDS=str(self.root/'unexpected-builds')):
            self.assertEqual(numerical_rust._build_root(),expected)
            self.assertNotIn('BACKTEST_RUST_BUILDS',native.environment(native.inspect_toolchain(ROOT)))

if __name__=='__main__':unittest.main()
