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
sys.path[:0]=[str(ROOT/'website'),str(ROOT/'scripts')]
import saved_backtests as saved
import serve


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

    def test_limit_never_evicts_and_deleting_one_frees_one_slot(self):
        records=[self.store.save('Book '+str(i),snapshot()) for i in range(20)]
        with self.assertRaises(saved.Full):self.store.save('Overflow',snapshot())
        self.assertEqual({r['id'] for r in self.store.list()},{r['id'] for r in records})
        self.store.delete(records[7]['id'])
        with self.assertRaises(saved.Missing):self.store.get(records[7]['id'])
        added=self.store.save('Replacement',snapshot())
        self.assertEqual(len(self.store.list()),20)
        self.assertEqual(self.store.get(records[0]['id'])['name'],'Book 0')
        self.assertEqual(self.store.get(added['id'])['name'],'Replacement')

    def test_capacity_is_atomic_across_independent_connections(self):
        self.store.save('Initial',snapshot())
        def save(i):
            try:return saved.Store(self.path).save(str(i),snapshot())['id']
            except saved.Full:return None
        with ThreadPoolExecutor(max_workers=8) as workers:identifiers=list(workers.map(save,range(28)))
        self.assertEqual(sum(identifier is not None for identifier in identifiers),19)
        self.assertEqual(len(self.store.list()),20)

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
        with patch.object(serve,'SAVED_BACKTESTS',self.store),patch.object(serve.cache_access,'daily',side_effect=AssertionError('Library must not acquire financial cache')):
            getattr(handler,'do_'+method)()
        return responses[0]

    def test_http_save_list_get_delete_and_foreign_origin(self):
        status,record=self.request('POST',body=dict(name='My strategy',snapshot=snapshot()))
        self.assertEqual(status,201)
        status,index=self.request('GET');self.assertEqual(status,200);self.assertEqual(index['limit'],20)
        self.assertEqual(index['records'][0]['id'],record['id'])
        target='/api/backtests/'+record['id']
        self.assertEqual(self.request('GET',target)[1]['snapshot'],snapshot())
        self.assertEqual(self.request('DELETE',target,origin='http://foreign.example')[0],403)
        self.assertEqual(self.request('DELETE',target)[0],200)
        self.assertEqual(self.request('GET',target)[0],404)

    def test_http_full_oversize_and_invalid_requests(self):
        self.assertEqual(self.request('POST',length=saved.MAX_BYTES+1)[0],413)
        self.assertEqual(self.request('POST',body={})[0],400)
        for i in range(20):self.store.save(str(i),snapshot())
        self.assertEqual(self.request('POST',body=dict(name='Overflow',snapshot=snapshot()))[0],409)
        self.assertEqual(len(self.store.list()),20)


if __name__=='__main__':unittest.main()
