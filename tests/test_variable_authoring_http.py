"""Private loopback variable authoring HTTP; no real cache/store or downloads."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import json
import subprocess
import sqlite3
from contextlib import closing
import unittest
from unittest.mock import patch
from backtest.variables import library, definitions
from backtest.application import variable_authoring, strategy_requests
from backtest.application import queue, library as saved
from threading import Event
from types import SimpleNamespace
from test_custom_strategy_http import HttpTests as ExistingHttp
import test_variable_definitions as language
import test_strategy_requests as strategy


class AuthoringHttpTests(ExistingHttp):
    def test_inspection_rejects_non_object_strategy_before_financial_work(self):
        with patch.object(self.calc,'coverage',side_effect=AssertionError('Malformed inspection must not enter coverage')) as inspect:
            for strategy in (None,False,0,'strategy',[]):
                status,body,_=self.request('/api/variable-coverage/inspect',dict(strategy=strategy,scope='not a scope'))
                self.assertEqual(status,400,body)
            inspect.assert_not_called()
        self.assertFalse(self.manager.runs);self.assertFalse(self.opened)
    def test_coverage_transport_is_exact_and_allocates_no_job(self):
        status,listing,_=self.request('/api/variable-coverage/scopes',{})
        self.assertEqual(status,200,listing);listing=json.loads(listing)
        scope=next(item for item in listing['scopes'] if item['pool']=='cached' and item['mode']=='latest')
        payload=dict(strategy=self.capture.to_dict(),scope=dict(scope,generation=listing['generation']))
        status,result,_=self.request('/api/variable-coverage/inspect',payload)
        self.assertEqual(status,200,result);self.assertEqual(json.loads(result)['population'],12)
        for bad in (dict(payload,extra=True),dict(payload,scope=dict(payload['scope'],book=False)),
                    dict(payload,scope=dict(payload['scope'],generation='0'*64)),
                    dict(payload,scope=dict(payload['scope'],book=float('nan'))),
                    dict(payload,scope=dict(payload['scope'],unexpected=1)),
                    dict(payload,scope=[])):
            status,_,_=self.request('/api/variable-coverage/inspect',bad);self.assertEqual(status,400)
        with patch.object(strategy_requests,'REQUEST_BYTES',16):
            status,_,_=self.request('/api/variable-coverage/inspect',payload);self.assertEqual(status,400)
        self.assertFalse(self.manager.runs);self.assertFalse(self.opened)
    def setUp(self):
        super().setUp();self.server.variable_store=library.Store(Path(self.folder.name)/'variables.sqlite')
    def post(self,path,value):
        status,body,_=self.request('/api/variables'+path,value)
        return status,json.loads(body)
    def test_list_catalog_and_validation_leave_absent_library_absent(self):
        store=self.server.variable_store
        status,body,_=self.request('/api/variables',method='GET');self.assertEqual(status,200);self.assertEqual(json.loads(body),{'entries':[]})
        status,body,_=self.request('/api/variables/catalog',method='GET');self.assertEqual(status,200);self.assertEqual(len(json.loads(body)['parameters']),4)
        with patch.object(self.calc,'preview',side_effect=AssertionError('Validation must not calculate')):
            status,value=self.post('/validate',dict(definition=language.definition(),name='Unsaved'))
        self.assertEqual(status,200,value);self.assertFalse(store.path.exists());self.assertFalse(self.manager.runs)
    def test_create_atomic_edit_favourite_and_delete_with_exact_authored_reads(self):
        definition=language.definition(language.constant('1e100'))
        status,entry=self.post('',dict(name='Exact value',definition=definition));self.assertEqual(status,200,entry)
        old={key:entry[key] for key in ('variable_id','revision')}
        status,snapshot=self.post('/authored',old);self.assertEqual(status,200);self.assertEqual(snapshot['authored'][0]['definition'],definition)
        status,changed=self.post('/'+entry['variable_id']+'/save',dict(name='Edited',version=entry['version'],definition=language.definition(language.constant('2'))));self.assertEqual(status,200,changed)
        status,value=self.post('/'+entry['variable_id']+'/save',dict(name='Stale',version=entry['version'],definition=definition));self.assertEqual(status,409,value)
        status,starred=self.post('/'+entry['variable_id']+'/favourite',dict(version=changed['version'],favourite=True));self.assertEqual(status,200);self.assertTrue(starred['favourite'])
        status,deleted=self.post('/'+entry['variable_id']+'/delete',dict(version=starred['version']));self.assertEqual(status,200);self.assertTrue(deleted['deleted'])
        status,retained=self.post('/authored',old);self.assertEqual(status,200);self.assertTrue(retained['entry']['deleted']);self.assertEqual(retained['selected'],old)
    def test_capture_is_complete_before_submission_and_unchanged_after_concurrent_edit(self):
        status,entry=self.post('',dict(name='Submitted',definition=language.definition()))
        exact={key:entry[key] for key in ('variable_id','revision')}
        status,snapshot=self.post('/authored',exact)
        request=dict(intent=strategy.intent(dict(kind='formula',**exact)),detached=[snapshot['capture']])
        status,captured=self.post('/capture',request);self.assertEqual(status,200,captured)
        self.server.variable_store.rename(entry['variable_id'],entry['version'],'Later name')
        self.assertEqual(captured['strategy']['variables']['presentation'][0]['name'],'Submitted')
        with patch.object(strategy_requests,'builtin_catalog',side_effect=AssertionError('Unchanged restore must not use live catalog')):
            status,restored=self.post('/capture',dict(intent=variable_authoring.intent(captured['strategy']),original=captured['strategy']))
        self.assertEqual(status,200,restored);self.assertEqual(restored,captured);self.assertFalse(self.manager.runs)
    def test_structured_units_and_unsupported_parameters_are_not_generic_failures(self):
        status,error=self.post('/validate',dict(definition=language.definition(dict(op='parameter',id='quarterly.revenue'))))
        self.assertEqual(status,400);self.assertEqual(error['code'],'UNKNOWN_PARAMETER');self.assertTrue(error['errors']);self.assertIn('/expression',error['path'])
        status,error=self.post('/validate',dict(definition=language.definition(dict(op='parameter',id='annual.revenue'))))
        self.assertEqual(status,400);self.assertEqual(error['code'],'UNIT_MISMATCH')
    def test_group_and_time_errors_leave_the_editor_request_unchanged_without_work(self):
        for expression in [dict(op='add',left=dict(op='parameter',id='annual.revenue'),right=dict(op='parameter',id='annual.operating_margin')),
                           dict(op='annual',parameter='market.enterprise_value',stat='mean',count=3),
                           dict(op='annual',parameter='annual.operating_margin',stat='mean',count=0)]:
            definition=language.definition(expression);before=json.dumps(definition)
            with patch.object(self.calc,'preview',side_effect=AssertionError('Authoring is financial-free')):
                status,error=self.post('/validate',dict(definition=definition,name='Kept draft'))
            self.assertEqual(status,400,error);self.assertIn('/expression',error['path']);self.assertEqual(json.dumps(definition),before)
        self.assertFalse(self.manager.runs);self.assertFalse(self.server.variable_store.path.exists())
    def test_origin_and_complete_request_bounds_precede_mutation(self):
        status,body,_=self.request('/api/variables',dict(name='Rejected',definition=language.definition()),headers={'Origin':'http://foreign.test'})
        self.assertEqual(status,403);self.assertFalse(self.server.variable_store.path.exists())
        status,error=self.post('/validate',dict(definition=language.definition(),unused='x'*(256*1024)))
        self.assertEqual(status,400);self.assertFalse(self.server.variable_store.path.exists())
    def test_missing_dependency_save_rejects_and_does_not_drop_local_definition(self):
        dep=language.entry(identity='local:dependency');definition=language.definition(language.reference(dep))
        before=json.dumps(definition)
        status,error=self.post('',dict(name='Missing dependency',definition=definition))
        self.assertEqual(status,400);self.assertEqual(error['code'],'MISSING_REFERENCE');self.assertEqual(json.dumps(definition),before)
        self.assertEqual(self.server.variable_store.list(),[])
    def test_detached_exact_edit_roundtrip_has_no_library_read_after_deletion(self):
        status,entry=self.post('',dict(name='Original captured name',definition=language.definition(language.constant('1e100'))))
        exact={key:entry[key] for key in ('variable_id','revision')};status,snapshot=self.post('/authored',exact)
        self.server.variable_store.path.unlink()
        with patch.object(library.Store,'_transaction',side_effect=AssertionError('Detached opening never reads storage')):
            status,opened=self.post('/detached',dict(root=exact,capture=snapshot['capture']))
        self.assertEqual(status,200,opened);self.assertEqual(opened['name'],'Original captured name');self.assertEqual(opened['selected'],exact)
        definition=opened['authored'][0]['definition'];self.assertEqual(definition['expression']['value'],'1e100')
        status,checked=self.post('/validate',dict(variable_id=exact['variable_id'],definition=definition,name=opened['name'],detached=[opened['capture']]))
        self.assertEqual(status,200,checked);self.assertEqual(checked['root'],exact);self.assertFalse(self.server.variable_store.path.exists());self.assertFalse(self.manager.runs)
    def test_damaged_store_is_preserved_and_reported(self):
        self.server.variable_store.path.write_bytes(b'not a sqlite library')
        before=self.server.variable_store.path.read_bytes()
        status,body,_=self.request('/api/variables',method='GET')
        self.assertEqual(status,503);self.assertEqual(self.server.variable_store.path.read_bytes(),before)

    def test_actual_draft_wire_preserves_large_restores_repeated_apply_and_threshold_units(self):
        # One valid 255-node tree exceeds half the HTTP ceiling only after the
        # canonical literals expand. Its strategy itself stays below 192 KiB.
        nodes=[language.constant('1.7976931348623157e308') for _ in range(128)]
        while len(nodes)>1:
            nodes=[language.binary('add',nodes[i],nodes[i+1]) for i in range(0,len(nodes),2)]
        entry=language.entry(language.definition(nodes[0]),'draft:large')
        source=dict(kind='formula',**language.root(entry))
        large=strategy_requests.capture_strategy(strategy.intent(source),submitted=[entry]).to_dict()
        old_payload=dict(intent=variable_authoring.intent(large),original=large,detached=[large['variables']])
        self.assertGreater(len(json.dumps(old_payload,separators=(',',':')).encode()),256*1024)
        self.assertLess(len(json.dumps(large,separators=(',',':')).encode()),192*1024)
        small_entry=language.entry(language.definition(language.constant('2')),entry['variable_id'])
        small=strategy_requests.capture_strategy(strategy.intent(dict(kind='formula',**language.root(small_entry))),submitted=[small_entry]).to_dict()
        two_intent=strategy.intent(source)
        two_intent['selection']['conditions']=[dict(source=source,op='gt',threshold=dict(value='0',unit='number'))]
        two=strategy_requests.capture_strategy(two_intent,submitted=[entry]).to_dict()
        # Eight independent roots share one expanded-literal dependency. Their
        # complete captures exceed the wire bound; their union remains small.
        nodes=[language.constant('1.7976931348623157e308') for _ in range(64)]
        while len(nodes)>1:nodes=[language.binary('add',nodes[i],nodes[i+1]) for i in range(0,len(nodes),2)]
        dep=language.entry(language.definition(nodes[0]),'draft:shared')
        roots=[language.entry(language.definition(language.reference(dep)),'draft:reference-'+str(i)) for i in range(8)]
        labels=[dict(language.root(item),name='Captured '+item['variable_id']) for item in [dep,*roots]]
        references=[]
        for item in roots:
            capture=library.capture_submitted([language.root(item)],submitted=[dep,item],labels=[label for label in labels if label['variable_id'] in (dep['variable_id'],item['variable_id'])])
            authored=definitions.authored_bundle(capture.program)['definitions']
            source=dict(kind='formula',**language.root(item))
            snapshot=dict(entry=dict(language.root(item),name='Captured '+item['variable_id'],version=1,favourite=False,deleted=False),selected=language.root(item),authored=authored,capture=capture.to_dict())
            references.append(dict(source=source,capture=capture.to_dict(),authored=authored,snapshot=snapshot))
        shared_intent=strategy.intent(references[0]['source'])
        shared_intent['selection']['conditions']=[dict(source=item['source'],op='gt',threshold=dict(value='0',unit='number')) for item in references[1:]]
        combined=strategy_requests.capture_strategy(shared_intent,submitted=[dep,*roots],labels=labels).to_dict()
        duplicated=dict(intent=shared_intent,detached=[item['capture'] for item in references])
        self.assertGreater(len(json.dumps(duplicated,separators=(',',':')).encode()),256*1024)
        self.assertLess(len(json.dumps(combined,separators=(',',':')).encode()),192*1024)
        expressions=[language.reference(item) for item in roots]
        while len(expressions)>1:expressions=[language.binary('add',expressions[i],expressions[i+1]) for i in range(0,len(expressions),2)]
        editor_definition=language.definition(expressions[0]);editor_id='draft:editor'
        editor_expected=variable_authoring.validate(dict(definition=editor_definition,variable_id=editor_id,name='Editor shared references',submitted=[dep,*roots],labels=labels),self.server.variable_store)
        shared=dict(references=references,strategy=combined,editor_source=dict(kind='formula',**editor_expected['root']),editor_expected=editor_expected)
        payload=dict(large=large,small=small,two=two,builtins=strategy_requests.builtin_catalog(),shared=shared)
        with patch.object(self.calc,'calculate',side_effect=AssertionError('Draft capture never calculates')),patch.object(library.Store,'_transaction',side_effect=AssertionError('Complete local authoring never reads an archive')):
            for script in ['check-strategy-draft.cjs','check-variable-workspace.cjs']:
                process=subprocess.run(['node','tests/'+script,'--wire','http://127.0.0.1:'+str(self.server.server_port)],
                    input=json.dumps(payload),text=True,capture_output=True,timeout=60)
                self.assertEqual(process.returncode,0,process.stdout+process.stderr)
        self.assertFalse(self.manager.runs);self.assertFalse(self.server.variable_store.path.exists())

    def test_real_javascript_json_roundtrip_preview_submission_retry_and_queue(self):
        def browser(value):
            process=subprocess.run(['node','-e','let s="";process.stdin.on("data",c=>s+=c);process.stdin.on("end",()=>process.stdout.write(JSON.stringify(JSON.parse(s))));'],
                input=json.dumps(value),text=True,capture_output=True,check=True)
            return json.loads(process.stdout)
        status,checked=self.post('/validate',dict(definition=language.definition(),name='Browser meaning'))
        self.assertEqual(status,200,checked)
        status,prepared=self.post('/capture',browser(dict(intent=strategy.intent(dict(kind='formula',**checked['root'])),detached=[checked['capture']])))
        self.assertEqual(status,200,prepared)
        wire=browser(prepared['strategy']);self.assertIs(type(wire['bounds']['min_cap']),int)
        status,body,_=self.request('/api/variable-preview',browser(dict(strategy=wire,roots=[dict(symbol='A0000',pool='legacy',mode='historical',date='2015-01-02')])))
        self.assertEqual(status,200,body);self.assertFalse(self.manager.runs)
        # A stale tab or an API client that still sends January is refused, never converted.
        payload=browser(dict(mode='january',options=dict(strategy=wire,first=2015,last=2015)))
        status,body,_=self.request('/api/backtest-runs/'+'9'*32,payload)
        body=json.loads(body)
        self.assertEqual((status,body['code'],body['path']),(400,'UNSUPPORTED_CAPABILITY','/mode'),body)
        self.assertIn('January backtests were removed',body['error']);self.assertFalse(self.manager.runs)
        for index,mode in enumerate(('latest','custom','random')):
            options=dict(strategy=wire)
            if mode in ('custom','random'):options.update(start='2015-01-02',end='2015-01-05',months=12)
            if mode=='random':options.update(trials=1,seed=42)
            identifier=str(index+1)*32;payload=browser(dict(mode=mode,options=options))
            status,body,_=self.request('/api/backtest-runs/'+identifier,payload);self.assertEqual(status,202,body)
            self.manager.runs[identifier]['thread'].join(10)
            result=self.manager.snapshot(identifier,include_result=False);self.assertEqual(result['state'],'complete',result)
            status,retried,_=self.request('/api/backtest-runs/'+identifier,payload);self.assertEqual(status,202,retried)
        store=queue.Store(Path(self.folder.name)/'wire-queue.sqlite')
        self.server.backtest_queue=SimpleNamespace(store=store,start=lambda:None,wake=Event())
        payload=browser(dict(id='a'*32,name='Exact browser retry',mode='custom',options=dict(strategy=wire,start='2015-01-02',end='2015-01-05',months=12),catalog=dict(metrics={},filters={}),presentation={}))
        status,body,_=self.request('/api/backtest-queue',payload);self.assertEqual(status,200,body)
        before=store.get('a'*32)
        status,body,_=self.request('/api/backtest-queue',payload);self.assertEqual(status,200,body)
        self.assertEqual(store.get('a'*32),before)
        self.assertEqual(before['options']['strategy'],prepared['strategy'])
        with patch.object(strategy_requests,'builtin_catalog',side_effect=AssertionError('Accepted retries do not read catalog')):
            status,body,_=self.request('/api/backtest-queue',payload)
        self.assertEqual(status,200,body)


def load_tests(loader,tests,pattern):
    names=[name for name in AuthoringHttpTests.__dict__ if name.startswith('test_')]
    return unittest.TestSuite(AuthoringHttpTests(name) for name in names)

if __name__=='__main__':unittest.main()
