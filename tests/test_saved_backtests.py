"""Complete saved results survive cache changes, restart, capacity races and deletion."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import copy
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT),str(ROOT/'scripts')]
from backtest.application import library as saved
from website.server import app as serve
def snapshot(kind='january'):
    holding=dict(symbol='A',name='A & B',rank=1,entry='2015-01-02',exit='2016-01-04',return_value=-1.,price=None,weight=1.,contribution_pp=-100.)
    period=dict(year=2015,entry=holding['entry'],exit=holding['exit'],names=1,holdings=[holding],portfolio=-1.,spy=.1)
    result=dict(options=dict(rank_from=1,rank_to=1,metric='ev_ebitda'),cagr=-1.,spy_cagr=.1,growth=0.,first=holding['entry'],start=holding['entry'],end=holding['exit'],years=[period])
    settings=dict(mode=kind,rank_from=1,rank_to=1,first=2015,last=2015,min_cap=100e6,filters=[dict(field='fcf',op='lt',value=-2.)])
    if kind!='january':
        result['periods']=result.pop('years');settings.update(start=holding['entry'],end=holding['exit'],months=12)
    if kind=='random':
        detail=copy.deepcopy(result)
        result=dict(completed=1,configuration=dict(start=holding['entry'],end=holding['exit'],seed=42),trials=[dict(trial=1,periods=1,cagr=-1.,dates=[holding['entry']])],trial_results=[detail],distributions=dict(cagr=dict(mean=-1.)))
        settings.update(trials=1)
    return dict(version=1,kind=kind,settings=settings,result=result,catalog=dict(metrics=dict(ev_ebitda=dict(label='EV/EBITDA')),filters={}),context=dict(notes=[],pill='2015'))


class StoreTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'saved-backtests.sqlite';self.store=saved.Store(self.path)

    def test_complete_results_reopen_verbatim_after_restart(self):
        for kind in ('january','custom','random'):
            original=snapshot(kind);before=copy.deepcopy(original)
            record=self.store.save('Test '+kind,original)
            self.assertEqual(original,before)
            restored=saved.Store(self.path).get(record['id'])
            self.assertEqual(restored['snapshot'],original)
            self.assertEqual(restored['name'],'Test '+kind)
            self.assertNotIn('snapshot',self.store.list()[0])
        self.assertEqual(len(self.store.list()),3)

    def test_40_mib_inline_random_result_opens_over_http(self):
        value=snapshot('random');value['result']['extension']='x'*(40*1024**2)
        record=self.store.save('Large inline result',value)
        status,opened=self.request('GET','/api/backtests/'+record['id'])
        self.assertEqual(status,200);self.assertEqual(opened['snapshot'],value)

    def test_inline_save_refuses_response_over_limit_including_metadata(self):
        value=snapshot('custom');record=self.store.save('Kept',value)
        snapshot_bytes=len(json.dumps(value,allow_nan=False,separators=(',',':')).encode('utf-8'))
        self.assertEqual(saved.MAX_BYTES,128*1024**2)
        with patch.object(saved,'MAX_BYTES',snapshot_bytes):
            with self.assertRaisesRegex(saved.InlineTooLarge,'128 MiB save and open limit'):
                self.store.save('Too large',value)
            status,error=self.request('POST',body=dict(name='Too large',snapshot=value))
            self.assertEqual(status,413);self.assertEqual(error['error'],saved.INLINE_LIMIT_MESSAGE)
            status,error=self.request('GET','/api/backtests/'+record['id'])
            self.assertEqual(status,400);self.assertEqual(error['error'],saved.INLINE_LIMIT_MESSAGE)
        self.assertEqual(self.store.list(),[dict(record,market='us',locked=False)]);self.assertEqual(self.store.get(record['id'])['snapshot'],value)

    def test_both_formats_roundtrip_without_rewriting_legacy_records(self):
        legacy=self.store.save('Legacy',snapshot())
        with closing(sqlite3.connect(self.path)) as db:
            original=db.execute('SELECT snapshot FROM records WHERE id=?',(legacy['id'],)).fetchone()[0]
        modern=snapshot();modern['version']=2;modern.pop('context')
        modern['presentation']=dict(coverage='Original coverage',notice=dict(text='Warning',severity='warning'),rangeNote='Original dates',periodLabel='2015')
        record=self.store.save('Modern',modern)
        self.assertEqual(self.store.get(record['id'])['snapshot'],modern)
        self.assertEqual(self.store.get(legacy['id'])['snapshot'],snapshot())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT snapshot FROM records WHERE id=?',(legacy['id'],)).fetchone()[0],original)

    def test_list_shows_the_market_of_the_stored_settings(self):
        from test_durable_evidence import source
        hong_kong=snapshot('custom');hong_kong['settings']['market']='hk'
        records=[self.store.save('Older US',snapshot()),self.store.save('Hong Kong',hong_kong),
                 self.store.save_evidence('Tokyo evidence',*reversed(source('custom',market='jp')[:2])),
                 self.store.save_evidence('US evidence',*reversed(source('random')[:2])),self.store.save('Corrupt',snapshot())]
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE records SET snapshot=? WHERE id=?',(b'corrupt',records[-1]['id']))
        listed={row['name']:row['market'] for row in saved.Store(self.path).list()}
        self.assertEqual(listed,{'Older US':'us','Hong Kong':'hk','Tokyo evidence':'jp','US evidence':'us','Corrupt':None})

    def test_limit_never_evicts_and_deleting_one_frees_one_slot(self):
        records=[self.store.save('Book '+str(i),snapshot()) for i in range(100)]
        with self.assertRaises(saved.Full):self.store.save('Overflow',snapshot())
        self.assertEqual({r['id'] for r in self.store.list()},{r['id'] for r in records})
        self.store.delete(records[7]['id'])
        with self.assertRaises(saved.Missing):self.store.get(records[7]['id'])
        added=self.store.save('Replacement',snapshot())
        self.assertEqual(len(self.store.list()),100)
        self.assertEqual(self.store.get(records[0]['id'])['name'],'Book 0')
        self.assertEqual(self.store.get(added['id'])['name'],'Replacement')

    def test_capacity_is_atomic_across_independent_connections(self):
        self.store.save('Initial',snapshot())
        def save(i):
            try:return saved.Store(self.path).save(str(i),snapshot())['id']
            except saved.Full:return None
        with ThreadPoolExecutor(max_workers=8) as workers:identifiers=list(workers.map(save,range(108)))
        self.assertEqual(sum(identifier is not None for identifier in identifiers),99)
        self.assertEqual(len(self.store.list()),100)

    def test_rename_preserves_identity_evidence_and_created_time(self):
        for kind in ('january','custom','random'):
            original=self.store.save('Original',snapshot(kind))
            with closing(sqlite3.connect(self.path)) as db:
                before=db.execute('SELECT * FROM records WHERE id=?',(original['id'],)).fetchone()
            renamed=self.store.rename(original['id'],'  New <name>  ')
            self.assertEqual(renamed,dict(original,name='New <name>'))
            with closing(sqlite3.connect(self.path)) as db:
                after=db.execute('SELECT * FROM records WHERE id=?',(original['id'],)).fetchone()
            self.assertEqual(before[:1]+before[2:],after[:1]+after[2:])
            self.assertEqual(saved.Store(self.path).get(original['id'])['name'],'New <name>')
            for name in ('',' ',None,'a'*121):
                with self.assertRaises(ValueError):self.store.rename(original['id'],name)
            self.assertEqual(self.store.get(original['id'])['snapshot'],snapshot(kind))
        with self.assertRaises(saved.Missing):self.store.rename('f'*32,'Missing')

    def test_rename_keeps_version_three_evidence_chunks_verbatim(self):
        from test_durable_evidence import source
        reader,metadata,_=source('random')
        original=self.store.save_evidence('Evidence',metadata,reader)
        def stored_bytes():
            with closing(sqlite3.connect(self.path)) as db:
                return (db.execute('SELECT id,created_at,info,snapshot FROM records WHERE id=?',(original['id'],)).fetchone(),
                        db.execute('SELECT * FROM evidence_chunks ORDER BY record_id,ordinal').fetchall())
        before=stored_bytes()
        renamed=self.store.rename(original['id'],'Evidence renamed')
        self.assertEqual(renamed,dict(original,name='Evidence renamed'))
        self.assertEqual(stored_bytes(),before)

    def test_http_rename_changes_metadata_without_financial_access(self):
        original=self.store.save('Original',snapshot())
        target='/api/backtests/'+original['id']
        status,record=self.request('POST',target,body=dict(name='Renamed'))
        self.assertEqual(status,200);self.assertEqual(record,dict(original,name='Renamed'))
        self.assertEqual(self.request('GET',target)[1]['snapshot'],snapshot())
        for value in ({},dict(name=' '),dict(name='a'*121),[]):
            self.assertEqual(self.request('POST',target,body=value)[0],400)
        self.assertEqual(self.request('POST',target,length=5000)[0],400)
        self.assertEqual(self.request('POST',target,body=dict(name='Foreign'),origin='http://foreign.example')[0],403)
        self.assertEqual(self.request('POST','/api/backtests/'+'f'*32,body=dict(name='Missing'))[0],404)

    def test_failed_publication_keeps_all_existing_records(self):
        record=self.store.save('Original',snapshot())
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT,'blocked'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.save('Failed',snapshot())
        self.assertEqual([row['id'] for row in self.store.list()],[record['id']])
        self.assertEqual(self.store.get(record['id'])['snapshot'],snapshot())

    def test_partial_random_and_missing_holdings_are_not_saved(self):
        partial=snapshot('random');partial['result'].pop('trial_results')
        empty=snapshot();empty['result']['years'][0]['holdings']=[]
        for value in (None,{},partial,empty):
            with self.assertRaises(ValueError):self.store.save('Invalid',value)
        invalid=snapshot();invalid['settings']['min_cap']=float('nan')
        with self.assertRaises(ValueError):self.store.save('Invalid',invalid)
        self.assertEqual(self.store.list(),[])

    def test_corrupt_record_is_kept_until_explicit_deletion(self):
        record=self.store.save('Original',snapshot())
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE records SET snapshot=?',(b'corrupt',))
        with self.assertRaisesRegex(ValueError,'kept'):self.store.get(record['id'])
        self.assertEqual(len(self.store.list()),1)
        self.store.delete(record['id']);self.assertEqual(self.store.list(),[])

    def test_names_and_identifiers_are_bounded(self):
        for name in ('',' ',None,'a'*121):
            with self.assertRaises(ValueError):self.store.save(name,snapshot())
        for identifier in ('../other','missing',None):
            with self.assertRaises(saved.Missing):self.store.get(identifier)
        self.assertEqual(self.store.list(),[])

    def request(self,method,path='/api/backtests',body=None,origin=None,length=None):
        handler=object.__new__(serve.Handler);handler.command=method;handler.path=path
        handler.server=SimpleNamespace(lifecycle=None)
        packed=json.dumps(body).encode() if body is not None else b''
        handler.headers={'Host':'127.0.0.1:3000','Content-Length':str(len(packed) if length is None else length)}
        if origin:handler.headers['Origin']=origin
        handler.rfile=io.BytesIO(packed);responses=[]
        handler.reply=lambda code,payload:responses.append((code,payload))
        handler.json_reply=lambda code,body:responses.append((code,json.loads(body)))
        with patch.object(serve,'SAVED_BACKTESTS',self.store),patch.object(serve.cache_access,'access',side_effect=AssertionError('Library must not acquire financial cache')):
            getattr(handler,'do_'+method)()
        return responses[0]

    def test_http_lock_keeps_a_record_until_it_is_unlocked(self):
        record=self.store.save('Keep',snapshot());target='/api/backtests/'+record['id']
        self.assertEqual(self.store.list()[0]['locked'],False)
        status,reply=self.request('POST',target,body=dict(locked=True))
        self.assertEqual(status,200);self.assertEqual(reply,dict(id=record['id'],locked=True))
        self.assertEqual(self.store.list()[0]['locked'],True)
        status,reply=self.request('DELETE',target)
        self.assertEqual(status,400);self.assertIn('Unlock',reply['error'])
        self.assertEqual(self.store.get(record['id'])['snapshot'],snapshot())
        self.assertEqual(self.request('POST','/api/backtests/'+'f'*32,body=dict(locked=True))[0],404)
        self.assertEqual(self.request('POST',target,body=dict(locked=False))[0],200)
        self.assertEqual(self.store.list()[0]['locked'],False)
        self.assertEqual(self.request('DELETE',target)[0],200)

    def test_http_save_list_get_delete_and_foreign_origin(self):
        status,record=self.request('POST',body=dict(name='My strategy',snapshot=snapshot()))
        self.assertEqual(status,201)
        status,index=self.request('GET');self.assertEqual(status,200);self.assertEqual(index['limit'],100)
        self.assertEqual(index['records'][0]['id'],record['id'])
        target='/api/backtests/'+record['id']
        self.assertEqual(self.request('GET',target)[1]['snapshot'],snapshot())
        self.assertEqual(self.request('DELETE',target,origin='http://foreign.example')[0],403)
        self.assertEqual(self.request('DELETE',target)[0],200)
        self.assertEqual(self.request('GET',target)[0],404)

    def test_http_full_oversize_and_invalid_requests(self):
        self.assertEqual(self.request('POST',length=saved.MAX_BYTES+1)[0],413)
        self.assertEqual(self.request('POST',body={})[0],400)
        for i in range(100):self.store.save(str(i),snapshot())
        self.assertEqual(self.request('POST',body=dict(name='Overflow',snapshot=snapshot()))[0],409)
        self.assertEqual(len(self.store.list()),100)


if __name__=='__main__':unittest.main()
