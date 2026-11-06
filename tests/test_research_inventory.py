"""Differential fresh-inventory contracts across filesystem changes and errors."""
import sys as _root_sys
from pathlib import Path as _RootPath
_root_sys.path.insert(0,str(_RootPath(__file__).resolve().parents[1]))
from backtest.financial import rules
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import errno
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from backtest.inputs import research as r


def original_signature():
    paths=[r.RAW/n for n in ('universe.json','metrics.jsonl','spy-div.json','treasury.json')]
    paths += [r.RAW/'px',Path(r.__file__),Path(r.metrics.__file__),Path(r.books.__file__),Path(r.rules.__file__),Path(r.cache_assets.__file__),Path(r.market.__file__)]
    paths += [Path(r.financial_inputs.__file__),Path(r.financial_inputs.parameters.__file__),Path(r.facts.__file__)]
    paths += sorted((r.RAW/'financial-inputs').glob('*/*.json'))
    return dict({p.relative_to(r.ROOT).as_posix():['directory' if p.is_dir() else p.stat().st_size,p.stat().st_mtime_ns] for p in paths})


def original_prices():
    return {p.name:[p.stat().st_size,p.stat().st_mtime_ns] for p in sorted((r.RAW/'px').glob('*.json'))}


def prior_signature():
    """Pre-projection-repair boundary: collect metadata before building keys."""
    paths=[r.RAW/n for n in ('universe.json','metrics.jsonl','spy-div.json','treasury.json')]
    paths += [r.RAW/'px',r.Path(r.__file__),r.Path(r.metrics.__file__),r.Path(r.books.__file__),r.Path(r.rules.__file__),r.Path(r.cache_assets.__file__),r.Path(r.market.__file__)]
    paths += [r.Path(r.financial_inputs.__file__),r.Path(r.financial_inputs.parameters.__file__),r.Path(r.facts.__file__)]
    entries=[(p,p.stat()) for p in paths]
    entries += r._metadata_entries(r.RAW/'financial-inputs','*/*.json')
    return dict({p.relative_to(r.ROOT).as_posix():['directory' if stat.S_ISDIR(info.st_mode) else info.st_size,info.st_mtime_ns] for p,info in entries})


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.context=ExitStack();self.addCleanup(self.context.close)
        self.root=Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.raw=self.root/'raw';self.px=self.raw/'px';self.financial=self.raw/'financial-inputs'
        self.px.mkdir(parents=True);(self.financial/'income').mkdir(parents=True)
        for n in ('universe.json','metrics.jsonl','spy-div.json','treasury.json'):(self.raw/n).write_text('[]')
        for module,name in ((r,'research.py'),(r.metrics,'metrics.py'),(r.books,'books.py'),(r.rules,'rules.py'),(r.cache_assets,'cache_assets.py'),(r.financial_inputs,'financial_inputs.py'),(r.market,'market.py'),(r.financial_inputs.parameters,'parameters.py'),(r.facts,'facts.py')):
            p=self.root/name;p.write_text('source');self.context.enter_context(patch.object(module,'__file__',str(p)))
        for name,value in (('ROOT',self.root),('RAW',self.raw)):self.context.enter_context(patch.object(r,name,value))
        for p in (self.px/'A.json',self.px/'z.json',self.financial/'income/A.json'):p.write_text('[]')

    def agree(self):
        for old,new in ((original_signature,r.signature),(original_prices,r.price_sources)):
            expected=old();actual=new();self.assertEqual(list(actual.items()),list(expected.items()))
            self.assertEqual([(type(k),type(v)) for k,v in actual.items()],[(type(k),type(v)) for k,v in expected.items()])
            self.assertEqual(json.dumps(actual),json.dumps(expected))
            self.assertEqual([[type(x) for x in v] for v in actual.values() if isinstance(v,list)],[[type(x) for x in v] for v in expected.values() if isinstance(v,list)])

    def assert_same_failure(self,expected_type):
        errors=[]
        for call in (prior_signature,r.signature):
            with self.assertRaises(expected_type) as caught:call()
            error=caught.exception
            errors.append((type(error),str(error),getattr(error,'errno',None),getattr(error,'filename',None)))
        self.assertEqual(*errors)

    def test_coverage_ledger_does_not_bind_freshness(self):
        # No preparation reads the download receipts.
        before=r.signature();path=self.raw/'download-coverage.json'
        path.write_text('{}');self.assertEqual(before,r.signature());self.agree()
        path.write_text('{"new":{}}');self.assertEqual(before,r.signature())
        path.unlink();self.assertEqual(before,r.signature())

    def test_outside_dependency_and_metadata_failure_precedence(self):
        outside=self.root.parent/(self.root.name+'-outside.py')
        outside.write_text('outside');self.addCleanup(outside.unlink)
        with patch.object(r.metrics,'__file__',str(outside)):
            self.assert_same_failure(ValueError)
            (self.root/'financial_inputs.py').unlink()
            self.assert_same_failure(FileNotFoundError)

    def test_financial_projection_containment(self):
        # An exact string prefix is not lexical path containment.
        lookalike=self.root.parent/(self.root.name+'-lookalike')
        with tempfile.TemporaryDirectory(dir=self.root.parent,prefix=lookalike.name) as name:
            folder=Path(name);asset=folder/'A.json';asset.write_text('[]')
            info=asset.stat()
            with patch.object(r,'_metadata_entries',return_value=[(asset,info)]):
                self.assert_same_failure(ValueError)

    def test_absent_financial_parent_is_not_projected(self):
        with patch.object(r,'_metadata_entries',return_value=[]):
            self.assertEqual(list(r.signature().items()),list(prior_signature().items()))

    def test_root_entry_and_root_parent_projection_fallback(self):
        # Synthetic discovery also exercises a path whose parent is outside ROOT.
        for asset in (self.root,self.root/'research.py'):
            with patch.object(r,'_metadata_entries',return_value=[(asset,asset.stat())]):
                self.assertEqual(list(r.signature().items()),list(prior_signature().items()))

    @unittest.skipUnless(os.name=='nt','Native Windows lexical path spelling')
    def test_native_case_distinct_parents_keep_exact_keys(self):
        from pathlib import PureWindowsPath
        paths=[PureWindowsPath('D:/Owned/raw/financial-inputs/Income/A.json'),
               PureWindowsPath('D:/Owned/raw/financial-inputs/income/B.json')]
        info=SimpleNamespace(st_mode=stat.S_IFREG,st_size=2,st_mtime_ns=11)
        # These exact spellings can compare equal as Windows Paths. Metadata
        # discovery has separate tests; projection must not coalesce prefixes.
        with patch.object(r,'ROOT',PureWindowsPath('D:/Owned')),patch.object(r,'RAW',PureWindowsPath('D:/Owned/raw')),patch.object(r,'Path',PureWindowsPath),patch.object(PureWindowsPath,'stat',create=True,return_value=info),patch.object(PureWindowsPath,'exists',create=True,return_value=False),patch.object(r,'_metadata_entries',return_value=[(p,info) for p in paths]):
            for module in (r,r.metrics,r.books,r.rules,r.cache_assets,r.market,r.financial_inputs,r.financial_inputs.parameters,r.facts):
                self.context.enter_context(patch.object(module,'__file__','D:/Owned/source.py'))
            self.assertEqual(list(r.signature().items()),list(prior_signature().items()))

    def test_exact_discovery_order_types_hidden_case_directory_and_depth(self):
        for folder in (self.px,self.financial/'income'):
            for name in ('.hidden.json','Mixed.JSON','omit.txt'):(folder/name).write_text(name)
            (folder/'directory.json').mkdir();(folder/'deeper').mkdir();(folder/'deeper/omit.json').write_text('ignored')
        self.agree();self.assertEqual(r.signature()['raw/financial-inputs/income/directory.json'][0],'directory')
        self.assertIsInstance(r.price_sources()['directory.json'][0],int)

    def test_each_call_observes_add_remove_rename_size_and_time_changes(self):
        for folder in (self.px,self.financial/'income'):
            path=folder/'fresh.json';path.write_text('a');self.agree()
            old=r.signature() if folder!=self.px else r.price_sources()
            path.write_text('longer');self.agree();self.assertNotEqual(old,r.signature() if folder!=self.px else r.price_sources())
            stamp=path.stat();os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+2_000_000_000));self.agree()
            target=folder/'renamed.json';path.rename(target);self.agree();target.unlink();self.agree()

    def test_missing_glob_roots_remain_empty_but_explicit_dependencies_fail(self):
        self.px.rename(self.raw/'old-px');self.assertEqual(r.price_sources(),original_prices());self.px.mkdir()
        self.financial.rename(self.raw/'old-financial');self.agree()
        (self.raw/'universe.json').unlink()
        for call in (original_signature,r.signature):
            with self.assertRaises(FileNotFoundError) as caught:call()
            self.assertEqual(caught.exception.errno,errno.ENOENT)

    def test_extra_enumeration_failure_uses_original_metadata_access(self):
        expected=original_prices();scan=os.scandir;counts={}
        def changed(path):
            key=str(Path(path));counts[key]=counts.get(key,0)+1
            if key==str(self.px) and counts[key]==2:raise PermissionError(errno.EACCES,'fixture',key)
            return scan(path)
        with patch.object(os,'scandir',changed):self.assertEqual(r.price_sources(),expected)
        self.assertEqual(counts[str(self.px)],2)

    def test_disappearing_discovered_asset_is_not_silently_dropped(self):
        scan=os.scandir;counts={};target=self.px/'z.json'
        def changed(path):
            key=str(Path(path));counts[key]=counts.get(key,0)+1
            if key==str(self.px) and counts[key]==2:target.unlink()
            return scan(path)
        with patch.object(os,'scandir',changed),self.assertRaises(FileNotFoundError) as caught:r.price_sources()
        self.assertEqual(caught.exception.errno,errno.ENOENT)
        self.assertEqual(Path(caught.exception.filename),target)

    def test_directory_iterators_close_on_success_and_metadata_failure(self):
        scan=os.scandir;active=[]
        class Scan:
            def __init__(self,path):self.inner=scan(path)
            def __enter__(self):active.append(self);return self.inner.__enter__()
            def __exit__(self,*args):
                try:return self.inner.__exit__(*args)
                finally:active.remove(self)
        with patch.object(os,'scandir',Scan):self.agree();self.assertEqual(active,[])
        entry=SimpleNamespace(name='A.json',stat=lambda:(_ for _ in ()).throw(PermissionError(errno.EACCES,'fixture')))
        class FailedScan:
            def __enter__(self):active.append(self);return iter([entry])
            def __exit__(self,*args):active.remove(self)
        with patch.object(Path,'glob',return_value=iter([self.px/'A.json'])),patch.object(os,'scandir',return_value=FailedScan()),self.assertRaises(PermissionError):r.price_sources()
        self.assertEqual(active,[])

    def test_case_equivalent_path_sort_does_not_merge_metadata(self):
        parent=self.px;values={'a.json':SimpleNamespace(st_size=1,st_mtime_ns=11),'A.json':SimpleNamespace(st_size=2,st_mtime_ns=22)}
        class CasePath:
            def __init__(self,name):self.name=name;self.parent=parent
            def __str__(self):return str(parent/self.name)
            def __lt__(self,other):return self.name.casefold()<other.name.casefold()
            def stat(self):return values[self.name]
        paths=[CasePath('a.json'),CasePath('A.json')]
        class Scan:
            def __enter__(self):return iter([SimpleNamespace(name=n,stat=lambda n=n:values[n]) for n in values])
            def __exit__(self,*args):pass
        with patch.object(Path,'glob',side_effect=lambda *a:iter(paths)),patch.object(os,'scandir',return_value=Scan()):
            self.assertEqual(list(r.price_sources().items()),list(original_prices().items()))
            self.assertEqual(list(r.price_sources().values()),[[1,11],[2,22]])

    def test_metadata_errors_keep_sorted_path_precedence(self):
        paths=[self.px/'z.json',self.px/'A.json']
        def missing(path,*args,**kwargs):raise FileNotFoundError(errno.ENOENT,'fixture',str(path))
        class Scan:
            def __enter__(self):return iter([SimpleNamespace(name=p.name,stat=lambda p=p:missing(p)) for p in paths])
            def __exit__(self,*args):pass
        for call in (original_prices,r.price_sources):
            with patch.object(Path,'glob',side_effect=lambda *a:iter(paths)),patch.object(Path,'stat',missing),patch.object(os,'scandir',return_value=Scan()),self.assertRaises(FileNotFoundError) as caught:call()
            self.assertEqual(Path(caught.exception.filename),self.px/'A.json')

    @unittest.skipUnless(os.name=='nt','Native Windows junction fixture')
    def test_actual_native_junction_matches_existing_discovery(self):
        target=self.financial/'income';link=self.financial/'junction'
        subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(link),str(target)],
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=10)
        try:self.agree();self.assertIn('raw/financial-inputs/junction/A.json',r.signature())
        finally:link.rmdir()

    def test_actual_link_targets_and_linked_intermediate_discovery(self):
        target=self.root/'target.json';target.write_text('actual target')
        try:
            (self.px/'linked.json').symlink_to(target)
            (self.financial/'linked-income').symlink_to(self.financial/'income',target_is_directory=True)
        except OSError as error:self.skipTest('Native symlink creation unavailable: '+str(error.errno))
        self.agree();self.assertEqual(r.price_sources()['linked.json'][0],target.stat().st_size)
        target.write_text('different target length');self.agree()
        target.unlink()
        for call in (original_prices,r.price_sources):
            with self.assertRaises(FileNotFoundError) as caught:call()
            self.assertEqual(caught.exception.errno,errno.ENOENT)


if __name__=='__main__':unittest.main()
