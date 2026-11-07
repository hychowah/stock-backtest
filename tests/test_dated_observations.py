"""Saved dated sources, their typed facts and all-52 formula evidence.

Private synthetic inputs only. Expected fields come from the independent
parameter oracle; old immutable fixture files are never regenerated or rewritten.
"""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from contextlib import closing
from datetime import date
import hashlib
import json
import math
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
from backtest.inputs import facts, research
from backtest.variables import definitions, parameters
from prepared_inputs_fixture import PreparedInputs
import test_annual_observations as annual
from test_annual_observations import field, formulas, values, explained, root
from test_parameter_contract import ORACLE


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)/'A.json'

    def resolve(self, rows, endpoint=facts.STOCK):
        self.path.write_text(json.dumps(dict(div=rows) if endpoint==facts.STOCK else rows))
        return facts.resolve(self.path,endpoint,stock=endpoint==facts.STOCK)

    def test_equal_null_duplicates_and_fractional_zero_volume(self):
        rows=[dict(date='2015-01-02',adjClose=10,volume=0),dict(date='2015-01-02',adjClose=None),
              dict(date='2015-01-02',adjClose=10,volume=0),dict(date='2015-01-03',adjClose=11,volume=.25)]
        resolved=self.resolve(rows)
        self.assertEqual(resolved['dated']['2015-01-02']['adjClose']['value'],10)
        self.assertEqual(resolved['dated']['2015-01-02']['volume']['value'],0)
        self.assertEqual(resolved['dated']['2015-01-03']['volume']['value'],.25)
        self.assertEqual(resolved['source'],dict(endpoint=facts.STOCK,
            sha256=hashlib.sha256(self.path.read_bytes()).hexdigest(),disposition='valid'))

    def test_price_volume_currency_and_conflicts_are_independent(self):
        dated=self.resolve([dict(date='2015-01-02',adjClose=10,volume=7,currency='EUR'),
            dict(date='2015-01-03',adjClose=-1,volume=0),dict(date='2015-01-04',adjClose=10,volume=3),
            dict(date='2015-01-04',adjClose=11,volume=3)])['dated']
        self.assertEqual(dated['2015-01-02']['adjClose']['reason'],'NON_USD_INPUT')
        self.assertEqual(dated['2015-01-02']['volume']['value'],7)
        self.assertEqual(dated['2015-01-03']['adjClose']['reason'],'INVALID_INPUT')
        self.assertEqual(dated['2015-01-03']['volume']['value'],0)
        self.assertEqual(dated['2015-01-04']['adjClose']['reason'],'CONFLICTING_INPUT')
        self.assertEqual(dated['2015-01-04']['volume']['value'],3)

    def test_invalid_values_and_undated_rows_are_unavailable(self):
        for value in (True,False,[],{},'nan','inf','invalid',10**500):
            with self.subTest(value=repr(value)[:20]):
                resolved=self.resolve([dict(date='2015-01-02',adjClose=value,volume=value),dict(date='invalid'),None])
                self.assertEqual(set(resolved['dated']),{'2015-01-02'})
                self.assertEqual(resolved['dated']['2015-01-02']['adjClose']['reason'],'INVALID_INPUT')
                self.assertEqual(resolved['dated']['2015-01-02']['volume']['reason'],'INVALID_INPUT')
                facts.encoded(resolved)

    def test_explicit_reported_currency_survives_absent_null_and_conflicting_route_currency(self):
        for route in ({},dict(currency=None),dict(currency='USD')):
            resolved=self.resolve([dict(route,date='2015-01-02',reportedCurrency='EUR',adjClose=10,volume=1)])
            self.assertEqual(resolved['dated']['2015-01-02']['adjClose']['reason'],'NON_USD_INPUT')
            self.assertEqual(resolved['dated']['2015-01-02']['volume']['value'],1)

    def test_one_read_binds_the_digest_to_the_facts(self):
        # Another saved key, here an old light series, is no price series.
        self.path.write_text(json.dumps(dict(div=[dict(date='2015-01-02',adjClose=10)],
                                             light=[dict(date='2015-01-02',price=4)])))
        with patch.object(Path,'read_bytes',autospec=True,side_effect=Path.read_bytes) as read:
            resolved=facts.resolve(self.path,facts.STOCK,stock=True)
        read.assert_called_once()
        self.assertEqual(resolved['source']['sha256'],hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(resolved['dated'],{'2015-01-02':dict(adjClose=dict(value=10.,valid=True,reason=None),
                                                              volume=dict(value=None,valid=False,reason='MISSING_INPUT'))})

    def test_signed_rates_and_latest_null_field_states(self):
        dated=self.resolve([dict(date='2015-01-01',month3=-1,year10=0),
            dict(date='2015-01-02',month3=None,year10=-2)],facts.TREASURY)['dated']
        self.assertEqual(dated['2015-01-01']['month3']['value'],-1)
        self.assertEqual(dated['2015-01-01']['year10']['value'],0)
        self.assertEqual(dated['2015-01-02']['month3']['reason'],'MISSING_INPUT')
        self.assertEqual(dated['2015-01-02']['year10']['value'],-2)

    def test_salvaged_source_keeps_volume_facts(self):
        # Raw volume facts survive an asset which proves no valid price response.
        resolved=self.resolve([dict(date='2015-01-02',volume=1)])
        self.assertEqual(resolved['source']['disposition'],'salvaged')
        self.assertEqual(resolved['source']['sha256'],hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(resolved['dated']['2015-01-02']['volume']['value'],1)
        self.assertEqual(resolved['dated']['2015-01-02']['adjClose']['reason'],'MISSING_INPUT')

    def test_missing_unreadable_source_no_repairs(self):
        self.assertEqual(facts.resolve(self.path,facts.STOCK,stock=True),
                         dict(source=dict(endpoint=facts.STOCK,sha256=None,disposition='missing'),dated={}))
        # Invalid JSON, a stock file that is no mapping, and a missing or non-list 'div' are unreadable.
        for content in (b'{invalid',b'[{"date":"2015-01-02","adjClose":10}]',b'{}',b'{"div":{"date":"2015-01-02"}}'):
            with self.subTest(content=content):
                self.path.write_bytes(content);before=self.path.read_bytes()
                resolved=facts.resolve(self.path,facts.STOCK,stock=True)
                self.assertEqual(resolved['source'],dict(endpoint=facts.STOCK,sha256=hashlib.sha256(before).hexdigest(),disposition='unreadable'))
                self.assertEqual(resolved['dated'],{})
                self.assertEqual(self.path.read_bytes(),before)

    def test_history_bound_and_cancellation(self):
        self.path.write_text(json.dumps(dict(div=[dict(date=f'2015-01-0{day}',volume=1) for day in (2,3,4,5)])))
        with patch.object(facts,'MAX_HISTORY',3),self.assertRaisesRegex(ValueError,'history'):
            facts.resolve(self.path,facts.STOCK,stock=True)
        with self.assertRaisesRegex(RuntimeError,'cancel'):
            facts.resolve(self.path,facts.STOCK,stock=True,checkpoint=Mock(side_effect=RuntimeError('cancel')))

    def test_typed_rows_keep_values_reasons_signed_zero_and_sources(self):
        stock=self.resolve([dict(date='2015-01-02',adjClose=10,volume=-0.0),dict(date='2015-01-03',adjClose=-1),
                            dict(date='2015-01-04',adjClose=10),dict(date='2015-01-04',adjClose=11,volume=2)])
        folder=Path(self.folder.name)
        (folder/'treasury.json').write_text(json.dumps([dict(date='2015-01-02',month3=-1,year10=None),dict(date='2015-01-05',month3=2,year10=3)]))
        (folder/'spy-div.json').write_text(json.dumps([dict(date='2015-01-02',adjClose=100),dict(date='2015-01-03',adjClose=0)]))
        shared=facts.shared(folder)
        with closing(sqlite3.connect(':memory:')) as db:
            db.executescript(facts.SCHEMA)
            facts.store_stock(db,'A',stock)
            facts.store_market(db,shared)
            rows=db.execute('SELECT * FROM stock_days ORDER BY day').fetchall()
            # A conflicting day has no adjusted close, only its reason.
            self.assertEqual(rows,[('A','2015-01-02',10,None,0,None),('A','2015-01-03',None,'INVALID_INPUT',None,'MISSING_INPUT'),
                                   ('A','2015-01-04',None,'CONFLICTING_INPUT',2,None)])
            self.assertEqual(math.copysign(1,rows[0][4]),-1)
            # Only valid SPY sessions are market days; Treasury days keep their reasons.
            self.assertEqual(db.execute('SELECT * FROM market_days ORDER BY day').fetchall(),
                             [('2015-01-02',100,-1,None,None,'MISSING_INPUT'),('2015-01-05',None,2,None,3,None)])
            self.assertEqual(db.execute('SELECT * FROM fact_sources ORDER BY symbol,endpoint').fetchall(),
                [('','spy-calendar',hashlib.sha256((folder/'spy-div.json').read_bytes()).hexdigest(),'valid'),
                 ('','treasury-rates',hashlib.sha256((folder/'treasury.json').read_bytes()).hexdigest(),'valid'),
                 ('A',facts.STOCK,hashlib.sha256(self.path.read_bytes()).hexdigest(),'valid')])


def configure(change=None):
    """Every statement field, a volume of 12.5 and a 10-year rate of -1, then change(inputs)."""
    def apply(inputs):
        annual.publish_all(inputs)
        path=research.RAW/'px/TEST.json'
        payload=json.loads(path.read_text())
        for row in payload['div']:row['volume']=12.5
        path.write_text(json.dumps(payload))
        treasury=json.loads((research.RAW/'treasury.json').read_text())
        for row in treasury:row['year10']=-1
        (research.RAW/'treasury.json').write_text(json.dumps(treasury))
        if change is not None:change(inputs)
    return apply


def extend(name, rows):
    """A change that appends rows to one saved dated file."""
    def change(inputs):
        path=research.RAW/name
        payload=json.loads(path.read_text())
        (payload['div'] if name.startswith('px/') else payload).extend(rows)
        path.write_text(json.dumps(payload))
    return change


def changes(*items):
    def change(inputs):
        for item in items:item(inputs)
    return change


HISTORICAL=root('TEST','cached')
LATEST=root('TEST','cached','latest','2015-10-20')
DATED=('market.volume','market.adjusted_price','treasury.us_3m','treasury.us_10y')


class TransportTests(unittest.TestCase):
    def prepared(self, change=None):
        """Prepare a private fictional cache; return its PreparedInputs."""
        inputs=PreparedInputs(configure=configure(change))
        self.addCleanup(inputs.close)
        return inputs

    def view(self, inputs):
        context=inputs.view();view=context.__enter__()
        self.addCleanup(context.__exit__,None,None,None)
        return view

    def _assert_spy_wrapper(self, key):
        def wrap(inputs):
            spy=research.RAW/'spy-div.json'
            rows=json.loads(spy.read_bytes())
            self.payload=({'historical':rows,'data':[dict(date='2099-01-01',adjClose=999)]}
                          if key=='historical' else {'historical':[],'data':rows})
            spy.write_text(json.dumps(self.payload))
        view=self.view(self.prepared(wrap))
        spy=research.RAW/'spy-div.json'
        self.assertEqual(view.source('',facts.CALENDAR),dict(endpoint=facts.CALENDAR,
            sha256=hashlib.sha256(spy.read_bytes()).hexdigest(),disposition='salvaged'))
        self.assertEqual(view.session(date(2015,1,2)),'2015-01-02')
        self.assertEqual(values(formulas(field('market.adjusted_price'),field('market.volume')),view,[HISTORICAL]),
                         [[(20.,None),(12.5,None)]])
        self.assertEqual(json.loads(spy.read_bytes()),self.payload)

    def test_retained_historical_spy_wrapper_prepares_sessions(self):
        self._assert_spy_wrapper('historical')

    def test_retained_data_spy_wrapper_prepares_sessions(self):
        self._assert_spy_wrapper('data')

    def test_source_digests_and_dispositions_survive_preparation(self):
        view=self.view(self.prepared())
        for symbol,endpoint,name in (('TEST',facts.STOCK,'px/TEST.json'),('',facts.TREASURY,'treasury.json'),
                                     ('',facts.CALENDAR,'spy-div.json')):
            self.assertEqual(view.source(symbol,endpoint),dict(endpoint=endpoint,
                sha256=hashlib.sha256((research.RAW/name).read_bytes()).hexdigest(),disposition='valid'))
        block=explained(formulas(field('market.volume'),field('treasury.us_3m')),view,[HISTORICAL])
        sources=[result['members'][0]['evidence']['source'] for result in block['observations']['results']]
        self.assertEqual(sources,[view.source('TEST',facts.STOCK),view.source('',facts.TREASURY)])

    def test_all_52_actual_preparation_and_formulas(self):
        view=self.view(self.prepared())
        rows=annual.annual_rows()
        expected={identity:rows[endpoint][0][name] for endpoint,fields in ORACLE.items()
                  for name,identity in fields.items() if identity.startswith('annual.')}
        expected.update({'market.adjusted_price':20,'market.volume':12.5,'treasury.us_3m':.02,'treasury.us_10y':-.01})
        self.assertEqual(len(expected),52)
        units={identity:('share' if name in ('weightedAverageShsOut','weightedAverageShsOutDil','volume') else 'USD/share' if name=='adjClose' else 'scalar' if endpoint=='treasury-rates' else 'USD')
               for endpoint,fields in ORACLE.items() for name,identity in fields.items()}
        self.assertEqual({identity:annual.UNITS[identity] for identity in expected},units)
        identities=list(expected)
        for start in range(0,len(identities),16):
            chunk=identities[start:start+16]
            program=formulas(*[field(identity,catalog=parameters.V2) for identity in chunk])
            for context,results in zip((HISTORICAL,LATEST),values(program,view,[HISTORICAL,LATEST])):
                for identity,result in zip(chunk,results):
                    want=22 if identity=='market.adjusted_price' and context is LATEST else expected[identity]
                    self.assertEqual(result,(want,None),identity)

    def test_at_and_lookback_without_annual_anchor_and_future_exclusion(self):
        view=self.view(self.prepared(changes(extend('px/TEST.json',[dict(date='2010-01-04',adjClose=8,volume=0)]),
            extend('spy-div.json',[dict(date='2010-01-04',adjClose=80)]),
            extend('treasury.json',[dict(date='2010-01-04',month3=-2,year10=0)]))))
        for wrap in (dict(op='at',date='2010-01-04'),dict(op='lookback',months=60)):
            program=formulas(*[field(identity,wrap=wrap) for identity in ('market.volume','market.adjusted_price','treasury.us_3m','annual.revenue')])
            block=explained(program,view,[HISTORICAL])
            results=[(result['value'],result['reason']) for result in block['results']]
            if wrap['op']=='at':
                self.assertEqual(results[:3],[(0,None),(8,None),(-.02,None)])
                self.assertIsNone(block['observations']['results'][0]['anchor'])
            self.assertEqual(results[-1][1],'NO_ELIGIBLE_REPORT')
        with self.assertRaises(definitions.FormulaError) as caught:
            formulas(field('market.volume',wrap=dict(op='at',date='2015-01-03'))).require_contexts([HISTORICAL])
        self.assertEqual(caught.exception.code,'FUTURE_DATE')

    def test_session_seven_day_boundary_exact_stock_and_volume_without_price(self):
        inputs=self.prepared()
        program=formulas(*[field('market.volume',wrap=dict(op='at',date=day)) for day in ('2015-01-09','2015-01-10')])
        with inputs.view() as view:
            self.assertEqual(values(program,view,[LATEST]),[[(12.5,None),(None,'MISSING_SESSION')]])
        # Removing only own-stock exact row never carries its earlier row. The
        # same stock days value the entry, so the historical root is denied too.
        with closing(sqlite3.connect(inputs.source)) as db:
            db.execute("DELETE FROM stock_days WHERE symbol='TEST' AND day='2015-01-02'");db.commit()
        with inputs.view() as view:
            self.assertEqual(values(formulas(field('market.volume',wrap=dict(op='at',date='2015-01-02'))),view,[LATEST]),
                             [[(None,'MISSING_INPUT')]])
            self.assertEqual(view.admit([HISTORICAL])[0]['reason'],'MISSING_PRICE')
            self.assertEqual(values(formulas(field('market.volume')),view,[HISTORICAL]),[[(None,'ROOT_NOT_ADMITTED')]])

    def test_treasury_latest_date_null_conflict_and_no_older_field_fallback(self):
        def change(inputs):
            path=research.RAW/'treasury.json'
            rows=[r for r in json.loads(path.read_text()) if r['date'] not in ('2015-01-02','2015-10-20')]
            rows.extend([dict(date='2015-01-01',month3=3,year10=1),dict(date='2015-01-02',month3=None,year10=-2),
                         dict(date='2015-10-20',month3=5,year10=0),dict(date='2015-10-20',month3=6,year10=0)])
            path.write_text(json.dumps(rows))
        view=self.view(self.prepared(change))
        program=formulas(field('treasury.us_3m'),field('treasury.us_10y'))
        for context,reason,rate in ((HISTORICAL,'MISSING_INPUT',-.02),(LATEST,'CONFLICTING_INPUT',0)):
            block=explained(program,view,[context])
            self.assertEqual([(r['value'],r['reason']) for r in block['results']],[(None,reason),(rate,None)])
            self.assertEqual([r['members'][0]['observation_date'] for r in block['observations']['results']],[context['date']]*2)

    def test_actual_independent_volume_foreign_price_and_future_only_stock_row(self):
        view=self.view(self.prepared(changes(
            extend('px/TEST.json',[dict(date='2015-10-19',volume=0),dict(date='2015-10-16',volume=.5,adjClose=99,currency='EUR'),
                                   dict(date='2015-10-15',volume=3,adjClose=88)]),
            extend('spy-div.json',[dict(date='2015-10-19',adjClose=100),dict(date='2015-10-16',adjClose=100),
                                   dict(date='2015-10-14',adjClose=100)]))))
        cases=(('2015-10-19',[(None,'MISSING_INPUT'),(0,None)]),('2015-10-16',[(None,'NON_USD_INPUT'),(.5,None)]),
               ('2015-10-14',[(None,'MISSING_INPUT'),(None,'MISSING_INPUT')]))
        for day,expected in cases:
            program=formulas(*[field(identity,wrap=dict(op='at',date=day)) for identity in ('market.adjusted_price','market.volume')])
            block=explained(program,view,[LATEST])
            self.assertEqual([(r['value'],r['reason']) for r in block['results']],expected,day)
            self.assertEqual([r['members'][0]['observation_date'] for r in block['observations']['results']],[day]*2)

    def test_at_and_lookback_dated_inputs_from_a_latest_root(self):
        view=self.view(self.prepared(changes(extend('px/TEST.json',[dict(date='2010-01-04',adjClose=8,volume=.25)]),
            extend('spy-div.json',[dict(date='2010-01-04',adjClose=80)]),
            extend('treasury.json',[dict(date='2010-01-04',month3=-2,year10=0)]))))
        for wrap in (dict(op='at',date='2010-01-04'),dict(op='lookback',months=60)):
            # The lookback resolves to 20 October 2010. Treasury has no age
            # ceiling; stock/session uses seven days and therefore is absent.
            program=formulas(field('treasury.us_3m',wrap=wrap,catalog=parameters.V2),field('market.volume',wrap=wrap,catalog=parameters.V2))
            [[rate,volume]]=values(program,view,[LATEST])
            self.assertEqual(rate,(-.02,None))
            self.assertEqual(volume,(None,'MISSING_SESSION') if wrap['op']=='lookback' else (.25,None))

    def test_failed_publication_preserves_previous(self):
        inputs=self.prepared()
        before=inputs.source.read_bytes()
        with patch.object(research.facts,'shared',side_effect=RuntimeError('private dated failure')):
            with self.assertRaisesRegex(RuntimeError,'private dated failure'):research.prepare(inputs.source,force=True)
        self.assertEqual(inputs.source.read_bytes(),before)
        self.assertFalse(inputs.source.with_name(inputs.source.name+'.building').exists())

    def test_dated_reads_keep_two_freshness_checks_and_close(self):
        view=self.view(self.prepared())
        with patch.object(view,'validate',wraps=view.validate) as freshness:
            results=values(formulas(*[field(identity) for identity in DATED]),view,[HISTORICAL])
        self.assertEqual(results,[[(12.5,None),(20,None),(.02,None),(-.01,None)]])
        self.assertEqual(freshness.call_count,2)
        with patch.object(view,'validate',side_effect=AssertionError('whole database scan')):
            self.assertEqual(view.session(date(2015,1,2)),'2015-01-02')
            self.assertEqual(view.stock('TEST',date(2015,1,2))['volume']['value'],12.5)
            self.assertIsNotNone(view.source('',facts.TREASURY))
        view.close()
        with self.assertRaisesRegex(ValueError,'closed'):view.validate()

    def test_dated_only_formulas_do_not_read_annual_history(self):
        view=self.view(self.prepared())
        with patch.object(view,'company',side_effect=AssertionError('Unexpected annual read')):
            self.assertEqual(values(formulas(field('market.volume')),view,[HISTORICAL]),[[(12.5,None)]])

    def test_other_research_versions_are_rejected(self):
        inputs=self.prepared()
        with closing(sqlite3.connect(inputs.source)) as db:
            for version in (research.SCHEMA_VERSION-1,research.SCHEMA_VERSION+1):
                db.execute('UPDATE metadata SET value=? WHERE key=?',(json.dumps(version),'version'))
                with self.assertRaisesRegex(ValueError,'version changed'):research.identity(db)


if __name__=='__main__':unittest.main()
