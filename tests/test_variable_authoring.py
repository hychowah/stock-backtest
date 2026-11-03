"""Offline exact authoring snapshots and detached editable conversion."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from contextlib import closing
from copy import deepcopy
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from backtest.variables import definitions as d, library, measures, selection
from backtest.application import variable_authoring as a
from backtest.application import strategy_requests as s
import test_variable_definitions as language
import test_strategy_requests as strategy


class AuthoringTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.store=library.Store(Path(self.folder.name)/'variables.sqlite')
    def test_all_exact_measures_validate_save_reopen_capture_without_import(self):
        catalog=a.catalog();descriptors=catalog['measures'];self.assertEqual(len(descriptors),33)
        self.assertEqual({item['id'] for item in catalog['expanded_parameters']},set(selection.QUALIFIED_PARAMETERS))
        self.assertTrue(all(all(item['support'].values()) for item in catalog['expanded_parameters']+descriptors))
        for measure in descriptors:
            with self.subTest(measure=measure['id']):
                root=measure['root']
                definition=dict(format='variable-definition',version=3,parameter_catalog='financial-parameters/3',
                    temporal_policy=d.TEMPORAL_POLICY,expression=dict(op='ref',**root),
                    output=dict(unit=measure['unit'],display=measure['display']))
                validated=a.validate(dict(definition=definition,name=measure['name'],
                    submitted=measure['submitted'],labels=measure['labels']),self.store)
                saved=self.store.create(measure['name'],definition)
                selected={key:saved[key] for key in ('variable_id','revision')}
                reopened=self.store.authoring_snapshot(selected)
                self.assertEqual(reopened['authored'][0]['definition'],definition)
                capture=self.store.capture([selected]).to_dict()
                self.assertEqual(capture,reopened['capture'])
                with patch.object(measures,'exact',side_effect=AssertionError('Detached restore read registry')):
                    self.assertEqual(a.detached(dict(root=selected,capture=capture))['selected'],selected)
                self.assertEqual(validated['output']['unit'],measure['unit'])
        self.assertEqual(len(self.store.list()),33)
    def test_measure_wrong_revision_and_corrupt_archive_are_never_hidden(self):
        measure=a.catalog()['measures'][0];root=measure['root']
        definition=dict(format='variable-definition',version=3,parameter_catalog='financial-parameters/3',
            temporal_policy=d.TEMPORAL_POLICY,expression=dict(op='ref',**root),
            output=dict(unit=measure['unit'],display=measure['display']))
        wrong=deepcopy(definition);wrong['expression']['revision']='sha256:'+'0'*64
        with self.assertRaises(d.FormulaError) as failure:self.store.create('Wrong',wrong)
        self.assertEqual(failure.exception.code,'MISSING_REFERENCE')
        saved=self.store.create('Correct',definition)
        with closing(sqlite3.connect(self.store.path)) as db:
            db.execute('INSERT INTO revisions VALUES(?,?,?,?)',(root['variable_id'],root['revision'],'null','fixture'));db.commit()
        with self.assertRaises(library.InvalidStore):self.store.authoring_snapshot({key:saved[key] for key in ('variable_id','revision')})
    def test_compaction_retains_extreme_exact_revisions_without_float_roundtrip(self):
        for literal in ['1e100','5e-324','1.7976931348623157e308','-0','123456789012345678901234567890123456789012345678901234567890e-60']:
            item=language.entry(language.definition(language.constant(literal)))
            program=d.validate(language.bundle(item));authored=d.authored_bundle(program)
            self.assertEqual(authored['definitions'][0]['revision'],item['revision'])
            self.assertLessEqual(len(authored['definitions'][0]['definition']['expression']['value']),64)
            self.assertEqual(d.validate(authored).to_dict(),program.to_dict())
    def test_compaction_rejects_forged_program(self):
        value=language.entry();program=d.validate(language.bundle(value)).to_dict();program['nodes'][0]['value']='2'
        with self.assertRaises(d.FormulaError):d.authored_bundle(d.FormulaProgram(d.canonical(program)))
    def test_editable_subset_keeps_repeated_exact_roots_and_reachable_dependencies(self):
        dep=language.entry(language.definition(language.constant('1e100')),'draft:dep')
        root=language.entry(language.definition(language.reference(dep)),'draft:root')
        unused=language.entry(identity='draft:unused')
        program=d.validate(language.bundle(dep,root,unused,roots=[language.root(root),language.root(root)]))
        subset=d.authored_bundle(program,[language.root(root),language.root(root)])
        self.assertEqual([x['variable_id'] for x in subset['definitions']],['draft:dep','draft:root'])
        self.assertEqual(subset['roots'],[language.root(root)]*2)
    def test_authored_snapshot_preserves_raw_exponent_and_current_pointer_separately(self):
        entry=self.store.create('Original',language.definition(language.constant('1e100')))
        selected={key:entry[key] for key in ('variable_id','revision')}
        current=self.store.edit(entry['variable_id'],entry['version'],language.definition(language.constant('2')))
        snapshot=self.store.authoring_snapshot(selected)
        self.assertEqual(snapshot['authored'][0]['definition']['expression']['value'],'1e100')
        self.assertEqual(snapshot['entry']['revision'],current['revision']);self.assertEqual(snapshot['selected'],selected)
        self.store.delete(current['variable_id'],current['version'])
        self.assertTrue(self.store.authoring_snapshot(selected)['entry']['deleted'])
    def test_snapshot_resolves_complete_archived_closure(self):
        dep=self.store.create('Dependency',language.definition(language.constant('2')))
        root=self.store.create('Root',language.definition(dict(op='ref',variable_id=dep['variable_id'],revision=dep['revision'])))
        snapshot=self.store.authoring_snapshot({key:root[key] for key in ('variable_id','revision')})
        self.assertEqual(len(snapshot['authored']),2)
        self.assertEqual(snapshot['capture']['presentation'][1]['name'],'Dependency')
    def test_snapshot_closes_connection_on_failure(self):
        entry=self.store.create('Value',language.definition())
        with self.assertRaises(d.FormulaError):self.store.authoring_snapshot(dict(variable_id=entry['variable_id'],revision='sha256:'+'0'*64))
        with closing(sqlite3.connect(self.store.path,timeout=.01)) as db:db.execute('BEGIN EXCLUSIVE');db.rollback()
    def test_atomic_editor_save_checks_version_and_preserves_all_fields_on_invalid_content(self):
        entry=self.store.create('Before',language.definition())
        changed=self.store.save(entry['variable_id'],entry['version'],'After',language.definition(language.constant('3')))
        self.assertEqual(changed['version'],entry['version']+1);self.assertEqual(changed['name'],'After')
        with self.assertRaises(library.Conflict):self.store.save(entry['variable_id'],entry['version'],'Stale',language.definition())
        with self.assertRaises(d.FormulaError):self.store.save(changed['variable_id'],changed['version'],'Lost',language.definition(dict(op='unknown')))
        self.assertEqual(self.store.get(changed['variable_id']),changed)
    def test_validation_does_not_create_library(self):
        result=a.validate(dict(definition=language.definition(language.constant('1e100')),name='Local'),self.store)
        self.assertFalse(self.store.path.exists());self.assertEqual(result['output']['unit'],'scalar')
        self.assertEqual(result['authored'][0]['definition']['expression']['value'],'1e100')
    def test_validation_retains_ordered_units_and_time_diagnostics(self):
        value=language.definition(dict(op='add',left=language.constant('1','USD'),right=language.constant('1')))
        with self.assertRaises(d.FormulaError) as failure:a.validate(dict(definition=value),self.store)
        self.assertEqual(failure.exception.code,'UNIT_MISMATCH')
        self.assertTrue(failure.exception.path.endswith('/expression'))
    def test_prepare_and_edit_detached_program_without_library_access(self):
        validated=a.validate(dict(definition=language.definition(language.constant('1e100')),name='Original'),self.store)
        source=dict(kind='formula',**validated['root']);intent=strategy.intent(source)
        prepared=a.prepare(dict(intent=intent,detached=[validated['capture']]),self.store)['strategy']
        with patch.object(self.store,'capture',side_effect=AssertionError('No library on unchanged restore')):
            same=a.prepare(dict(intent=a.intent(prepared),original=prepared),self.store)['strategy']
        self.assertEqual(prepared,same)
        editable=d.authored_bundle(library.VariableCapture(d.canonical(prepared['variables'])).program)
        edited=deepcopy(editable['definitions'][0]['definition']);edited['expression']=dict(op='neg',arg=edited['expression'])
        validated2=a.validate(dict(definition=edited,detached=[prepared['variables']],name='Edited'),self.store)
        fresh=a.prepare(dict(intent=strategy.intent(dict(kind='formula',**validated2['root'])),detached=[validated2['capture']]),self.store)
        self.assertNotEqual(fresh['strategy']['variables']['program']['bundle_revision'],prepared['variables']['program']['bundle_revision'])
        self.assertFalse(self.store.path.exists())
    def test_missing_archived_dependency_save_fails_and_keeps_detached_content(self):
        dep=language.entry(identity='local:dependency');root=language.entry(language.definition(language.reference(dep)),'local:root')
        captured=library.capture_submitted([language.root(root)],submitted=[dep,root]).to_dict();before=deepcopy(captured)
        result=a.validate(dict(definition=root['definition'],variable_id=root['variable_id'],detached=[captured]),self.store)
        with self.assertRaises(d.FormulaError) as failure:self.store.create('Root',root['definition'])
        self.assertEqual(failure.exception.code,'MISSING_REFERENCE');self.assertEqual(captured,before)
        self.assertEqual(result['root'],language.root(root));self.assertEqual(self.store.list(),[])
    def test_snapshot_names_and_raw_content_share_one_concurrent_read(self):
        from threading import Event, Thread, current_thread
        entry=self.store.create('Before',language.definition(language.constant('1e100')))
        exact={key:entry[key] for key in ('variable_id','revision')}
        updated=Event();outcome=[];original_connect=sqlite3.connect;original_lookup=library.Store._lookup;started=[False]
        def connect(*args,**kwargs):
            db=original_connect(*args,**kwargs)
            if current_thread().name=='authoring-writer':
                db.set_trace_callback(lambda sql:updated.set() if sql.startswith('UPDATE entries') else None)
            return db
        def write():
            try:outcome.append(self.store.rename(entry['variable_id'],entry['version'],'After'))
            except BaseException as error:outcome.append(error)
        writer=Thread(target=write,name='authoring-writer')
        def lookup(*args):
            result=original_lookup(*args)
            if not started[0]:
                started[0]=True;writer.start();self.assertTrue(updated.wait(2))
            return result
        with patch.object(library.sqlite3,'connect',side_effect=connect),patch.object(library.Store,'_lookup',side_effect=lookup):
            snapshot=self.store.authoring_snapshot(exact)
            writer.join(3)
        self.assertFalse(writer.is_alive());self.assertEqual(snapshot['entry']['name'],'Before')
        self.assertEqual(snapshot['capture']['presentation'][0]['name'],'Before')
        self.assertEqual(snapshot['authored'][0]['definition']['expression']['value'],'1e100')
        self.assertEqual(outcome[0]['name'],'After')
    def test_multi_root_capture_uses_two_exact_revisions_after_archive_deletion(self):
        first=self.store.create('First',language.definition(language.constant('1')))
        old={key:first[key] for key in ('variable_id','revision')}
        second=self.store.edit(first['variable_id'],first['version'],language.definition(language.constant('2')))
        new={key:second[key] for key in ('variable_id','revision')}
        captured=self.store.capture([old,new,old]);self.store.delete(second['variable_id'],second['version'])
        captured_value=captured.to_dict();oldsource=dict(kind='formula',**old);newsource=dict(kind='formula',**new)
        intent=strategy.intent(oldsource,[strategy.condition(newsource,'0','number')])
        self.store.path.unlink()
        result=a.prepare(dict(intent=intent,detached=[captured_value]),self.store)['strategy']
        self.assertEqual(result['variables']['program']['bundle']['roots'],[old,new])
        self.assertEqual(len(result['variables']['program']['bundle']['definitions']),2)

    def test_legacy_catalog_retains_four_parameters_and_stored_builtin_adapters(self):
        catalog=a.catalog();self.assertEqual(len(catalog['parameters']),4)
        self.assertTrue(any(item['id']=='filter:profit_margin' for item in catalog['builtins']))
    def test_selected_dependencies_dont_accumulate_unrelated_editor_revisions(self):
        old=a.validate(dict(definition=language.definition(language.constant('1'))),self.store)
        new=a.validate(dict(definition=language.definition(language.constant('2')),detached=[old['capture']]),self.store)
        self.assertEqual(len(new['capture']['program']['bundle']['definitions']),1)

    def test_transport_numeric_spelling_restores_to_strict_content_without_lookup(self):
        capture=s.capture_strategy(strategy.intent(conditions=[strategy.condition(strategy.builtin(),'100','percent')]))
        wire=capture.to_dict();wire['bounds']['min_cap']=100000000;wire['bounds']['min_ev']=50000000
        wire['selection']['conditions'][0]['comparison_value']=1
        wire['selection']['conditions'][0]['storage_comparison_value']=1
        with patch.object(s,'builtin_catalog',side_effect=AssertionError('No live catalog')):
            restored=s.from_wire(wire)
        self.assertEqual(restored,capture)
        with self.assertRaises(d.FormulaError):s.require_strategy(s.CapturedStrategy(d.canonical(wire)))
        self.assertEqual(wire['bounds']['min_cap'],100000000)
        self.assertIs(type(wire['bounds']['min_cap']),int)

    def test_transport_rejects_integer_type_and_derived_content_forgeries(self):
        capture=s.capture_strategy(strategy.intent(conditions=[strategy.condition(strategy.builtin(),'100','percent')]))
        for change in [lambda v:v.update(version=1.0),lambda v:v['selection'].update(rank_from=1.0),
                       lambda v:v['limits'].update(bytes=float(s.STRATEGY_BYTES)),
                       lambda v:v['selection']['conditions'][0].update(comparison_value=True),
                       lambda v:v['selection']['conditions'][0].update(storage_comparison_value=2),
                       lambda v:v['selection']['conditions'][0].pop('comparison_value'),
                       lambda v:v['bounds'].update(min_ev='50000000')]:
            with self.subTest(change=change):
                wire=capture.to_dict();change(wire)
                with self.assertRaises((d.FormulaError,ValueError,TypeError)):s.from_wire(wire)

    def test_unchanged_wire_restore_needs_no_archive_and_preserves_all_labels(self):
        entry=self.store.create('Submitted',language.definition())
        capture=s.capture_strategy(strategy.intent(strategy.formula(entry)),self.store)
        wire=capture.to_dict();wire['bounds']['min_cap']=100000000;wire['bounds']['min_ev']=50000000
        self.store.path.unlink()
        with patch.object(library.Store,'_transaction',side_effect=AssertionError('No archive')):
            result=a.prepare(dict(intent=a.intent(wire),original=wire),self.store)
        self.assertEqual(result['strategy'],capture.to_dict())

    def test_detached_selected_edit_keeps_exact_decimal_and_dependencies_without_archive(self):
        dep=self.store.create('Submitted dependency',language.definition(language.constant('1e100')))
        entry=self.store.create('Submitted root',language.definition(language.reference(dep)))
        exact=language.root(entry);capture=self.store.capture([exact]);self.store.path.unlink()
        with patch.object(library.Store,'_transaction',side_effect=AssertionError('No archive lookup')):
            opened=a.detached(dict(root=exact,capture=capture.to_dict()))
            definition=next(item['definition'] for item in opened['authored'] if item['variable_id']==exact['variable_id'])
            edited=a.validate(dict(variable_id=exact['variable_id'],definition=definition,detached=[opened['capture']]),self.store)
        self.assertEqual(opened['name'],'Submitted root');self.assertEqual(edited['root'],exact)
        self.assertEqual(len(opened['authored']),2)
        dependency=next(item for item in opened['authored'] if item['variable_id']==dep['variable_id'])
        self.assertEqual(dependency['definition']['expression']['value'],'1e100')
        self.assertFalse(self.store.path.exists())

    def test_detached_edit_rejects_missing_or_forged_root_and_complete_capture(self):
        entry=language.entry();capture=library.capture_submitted([language.root(entry)],submitted=[entry])
        wrong=dict(variable_id='variable:missing',revision=entry['revision'])
        with self.assertRaises(d.FormulaError):a.detached(dict(root=wrong,capture=capture.to_dict()))
        corrupt=capture.to_dict();corrupt['program']['nodes'][0]['value']='3'
        with self.assertRaises(d.FormulaError):a.detached(dict(root=language.root(entry),capture=corrupt))


if __name__=='__main__':unittest.main()
