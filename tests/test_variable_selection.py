"""Reference-backed scalar selection, detached evidence and private admission."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from datetime import date
import json
import math
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock,patch
from backtest import observations
from backtest.financial import books
from backtest.inputs import observation_inputs as source
from backtest.variables import definitions as d, reference as r, selection as s
import test_observations as fixtures
import test_variable_definitions as language
import test_variable_evaluation as expressions


def specification(program, *, direction='highest', order='filter_first', conditions=None, **changes):
    p=program.to_dict();definition=p['definitions'][p['roots'][0]]
    return dict(ranking=dict(variable_id=definition['variable_id'],revision=definition['revision'],direction=direction),
                selection_order=order,conditions=[] if conditions is None else conditions,**changes)


def condition(program, value='0', unit='scalar', op='gt'):
    spec=specification(program)['ranking']
    return dict(variable_id=spec['variable_id'],revision=spec['revision'],op=op,threshold=dict(value=value,unit=unit))


class VariableSelectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def roots(self, **changes):
        return [dict(dict(symbol='A',pool='legacy',mode='historical',date=self.fixture.root_date),**changes)]

    def run_selection(self,program=None,**settings):
        program=program or expressions.program(language.constant('-3'))
        return s.evaluate(s.plan(program,self.roots(),specification(program,**settings)),self.fixture.view()).to_dict()

    def error(self,code,call,*args,**kwargs):
        with self.assertRaises(d.FormulaError) as caught:call(*args,**kwargs)
        self.assertEqual(caught.exception.code,code)
        return caught.exception

    def test_real_evaluator_signed_values_both_pools_orders_directions(self):
        program=expressions.program(language.constant('-3'))
        for pool in ('legacy','cached'):
            for order in ('filter_first','rank_first'):
                for direction in ('highest','lowest'):
                    result=s.evaluate(s.plan(program,self.roots(pool=pool),specification(program,direction=direction,order=order)),self.fixture.view()).to_dict()
                    row=result['scopes'][0]['selected'][0]
                    self.assertEqual((row['ranking_value'],row['weight'],row['rank']),(-3.,1.,1))
                    self.assertEqual(row['direction'],direction)
                    self.assertNotIn('metric_yield',row);self.assertNotIn('metric_multiple',row)
                    self.assertEqual(result['population'],'explicit-request-scopes')

    def test_threshold_exact_decimal_scaling_and_captured_submission(self):
        program=expressions.program(language.constant('.1'))
        submitted=condition(program,'+8e0','percent')
        result=self.run_selection(program,conditions=[submitted])
        normalized=result['specification']['conditions'][0]
        self.assertEqual(normalized['submitted_threshold'],dict(value='+8e0',unit='percent'))
        self.assertEqual(normalized['threshold'],dict(value='0.08',unit='scalar'))
        self.assertEqual(normalized['comparison_value'],.08)
        self.assertFalse(result['scopes'][0]['empty'])
        self.assertEqual(d.normalize_quantity(dict(value='-1.25',unit='usd_million'),'USD')['comparison_value'],-1250000.)
        self.assertEqual(d.normalize_quantity(dict(value='12',unit='usd_per_share'),'USD/share')['comparison_value'],12.)
        self.assertEqual(d.normalize_quantity(dict(value='-0',unit='scalar'),'scalar')['threshold']['value'],'0')

    def test_threshold_unit_literal_agreement_and_explicit_direction_validation(self):
        program=expressions.program()
        for quantity in (dict(value='1',unit='usd'),dict(value='NaN',unit='scalar'),dict(value='1e9999999',unit='scalar'),dict(value='1'*65,unit='scalar'),dict(value='5e-324',unit='percent')):
            with self.assertRaises(d.FormulaError):s.plan(program,self.roots(),specification(program,conditions=[dict(condition(program),threshold=quantity)]))
        bad=dict(condition(program),submitted_threshold=dict(value='8',unit='percent'),threshold=dict(value='0.09',unit='scalar'))
        self.error('INVALID_STRATEGY',s.plan,program,self.roots(),specification(program,conditions=[bad]))
        spec=specification(program);spec['ranking'].pop('direction')
        self.error('INVALID_STRATEGY',s.plan,program,self.roots(),spec)
        spec=specification(program);spec['ranking']['revision']='other'
        self.error('INVALID_STRATEGY',s.plan,program,self.roots(),spec)
        self.error('INVALID_STRATEGY',s.plan,program,self.roots(),specification(program,conditions=[dict(condition(program),op='ge')]))

    def test_threshold_range_is_checked_after_exact_canonical_scaling(self):
        for value,display,unit,canonical in (
                ('1e310','percent','scalar','1e308'),
                ('1e-325','usd_million','USD','1e-319')):
            with self.subTest(value=value,display=display):
                converted=d.normalize_quantity(dict(value=value,unit=display),unit)
                direct=d.normalize_quantity(dict(value=canonical,unit=unit),unit)
                self.assertEqual(converted['threshold'],direct['threshold'])
                self.assertEqual(converted['comparison_value'],float(canonical))
                self.assertEqual(converted['submitted_threshold'],dict(value=value,unit=display))
                program=expressions.program(language.constant('1',unit),unit,
                    'number' if unit=='scalar' else 'usd')
                planned=s.plan(program,self.roots(),specification(program,
                    conditions=[condition(program,value,display)]))
                self.assertEqual(planned.to_dict()['specification']['conditions'][0]['comparison_value'],float(canonical))
        for value,display,unit in (
                ('1e309','scalar','scalar'),('1e-325','scalar','scalar'),
                ('1e308','usd_million','USD'),('5e-324','percent','scalar')):
            self.error('INVALID_LITERAL',d.normalize_quantity,dict(value=value,unit=display),unit)
        # Formula constants already use canonical units and retain their range checks.
        for value in ('1e310','1e-325'):
            self.error('INVALID_LITERAL',expressions.program,language.constant(value))

    def test_missing_rank_and_active_conditions_and_empty_scopes(self):
        missing=language.entry(language.definition(expressions.parameter('annual.operating_margin')),'draft:missing')
        constant=language.entry(language.definition(language.constant('-2')),'draft:rank')
        program=d.validate(language.bundle(constant,missing,roots=[language.root(constant),language.root(missing)]))
        self.fixture.annual['2014-06-30']['operatingIncome']=fixtures.state(None,'CONFLICTING_INPUT')
        result=self.run_selection(program)
        self.assertFalse(result['scopes'][0]['empty'])
        spec=specification(program,conditions=[dict(variable_id=missing['variable_id'],revision=missing['revision'],op='gt',threshold=dict(value='0',unit='scalar'))])
        block=s.evaluate(s.plan(program,self.roots(),spec),self.fixture.view()).to_dict()
        self.assertTrue(block['scopes'][0]['empty']);self.assertEqual(block['scopes'][0]['selected'],[])
        spec['ranking'].update(language.root(missing))
        block=s.evaluate(s.plan(program,self.roots(),spec),self.fixture.view()).to_dict()
        self.assertTrue(block['scopes'][0]['empty'])
        self.assertEqual(block['evaluation']['results'][1]['reason'],'CONFLICTING_INPUT')

    def test_independent_scopes_and_duplicate_company_rejection(self):
        program=expressions.program()
        roots=self.roots()+self.roots(pool='cached')+self.roots(mode='latest',date=self.fixture.latest_date)
        block=s.evaluate(s.plan(program,roots,specification(program)),self.fixture.view()).to_dict()
        self.assertEqual([scope['selected'][0]['rank'] for scope in block['scopes']],[1,1,1])
        self.assertEqual([scope['requests'] for scope in block['scopes']],[[0],[1],[2]])
        self.error('INVALID_STRATEGY',s.plan,program,self.roots()*2,specification(program))

    def test_admission_denials_survive_constant_only_selection(self):
        program=expressions.program(language.constant('7'))
        roots=self.roots(mode='latest',date=self.fixture.latest_date)
        result=s.evaluate(s.plan(program,roots,specification(program)),self.fixture.view(admitted=False)).to_dict()
        self.assertTrue(result['scopes'][0]['empty'])
        self.assertEqual(result['scopes'][0]['admitted'],0)
        self.assertEqual(result['evaluation']['results'][0]['reason'],'ROOT_NOT_ADMITTED')
        self.assertEqual(result['evaluation']['observations']['roots'][0]['reason'],'NOT_LISTED')

    def test_immutable_checked_plan_rejects_forgery_before_inputs(self):
        program=expressions.program();plan=s.plan(program,self.roots(),specification(program))
        for field,value in [('version',True),('format','other'),('reference',{}),('scalar_policy',{}),('scopes',[]),('reservations',{})]:
            forged=plan.to_dict();forged[field]=value;inputs=Mock()
            with self.assertRaises(d.FormulaError):s.evaluate(s.SelectionPlan(d.canonical(forged)),inputs)
            self.assertEqual(inputs.mock_calls,[])
        for forged in ({},s.SelectionPlan('invalid'),s.SelectionPlan('{}'),s.SelectionPlan('{"nested":NaN}')):
            with self.assertRaises(d.FormulaError):s.require_plan(forged)
        with self.assertRaises(AttributeError):plan.document='{}'
        detached=plan.to_dict();detached['scopes'].clear()
        self.assertEqual(len(plan.to_dict()['scopes']),1)

    def test_condition_count_and_limit_shapes(self):
        program=expressions.program()
        s.plan(program,self.roots(),specification(program,conditions=[condition(program)]*50))
        self.error('WORK_LIMIT',s.plan,program,self.roots(),specification(program,conditions=[condition(program)]*51))
        for name,maximum in s.CEILINGS.items():
            for value in (True,0,maximum+1):
                self.error('INVALID_SHAPE',s.plan,program,self.roots(),specification(program),{name:value})
        self.error('INVALID_SHAPE',s.plan,program,self.roots(),specification(program),dict(other=1))

    def test_exact_plan_output_retained_bounds_with_evidence(self):
        program=expressions.program(expressions.parameter(),'USD','usd');view=self.fixture.view()
        for name in ('plan_bytes','output_bytes','retained_bytes'):
            low,high=1,s.CEILINGS[name]
            while low<high:
                middle=(low+high)//2
                try:s.evaluate(s.plan(program,self.roots(),specification(program),{name:middle}),view)
                except (d.FormulaError,observations.ObservationError,ValueError):low=middle+1
                else:high=middle
            self.assertFalse(s.evaluate(s.plan(program,self.roots(),specification(program),{name:low}),view).to_dict()['scopes'][0]['empty'])
            with self.assertRaises((d.FormulaError,observations.ObservationError,ValueError)):
                s.evaluate(s.plan(program,self.roots(),specification(program),{name:low-1}),view)

    def test_heavy_evidence_complete_or_bounded_before_publication(self):
        self.fixture.annual['2014-06-30']['revenue']['rows']=[dict(index=i,sha256='a'*64) for i in range(300)]
        program=expressions.program(expressions.parameter(),'USD','usd')
        result=self.run_selection(program)
        self.assertEqual(len(result['evaluation']['observations']['results'][0]['members'][0]['evidence']['fields']['revenue']['rows']),300)
        with self.assertRaises((d.FormulaError,observations.ObservationError,ValueError)):
            s.evaluate(s.plan(program,self.roots(),specification(program),dict(retained_bytes=50000)),self.fixture.view())

    def test_evidence_targets_detach_and_identity_changes_with_selection(self):
        program=expressions.program(language.constant('0'))
        block=s.evaluate(s.plan(program,self.roots(),specification(program,conditions=[condition(program,'-1')])),self.fixture.view())
        result=block.to_dict();selected=result['scopes'][0]['selected'][0]
        self.assertEqual(selected['evidence']['ranking_result'],selected['evidence']['condition_results'][0])
        self.assertEqual(result['evaluation']['results'][selected['evidence']['ranking_result']]['value'],selected['ranking_value'])
        self.assertIn(selected['evidence']['admission'],{row['root'] for row in result['evaluation']['observations']['roots']})
        changed=self.run_selection(program,direction='lowest')
        self.assertNotEqual(result['calculation_identity'],changed['calculation_identity'])
        snapshot=block.to_json();self.fixture.doCleanups()
        self.assertEqual(block.to_dict(),json.loads(snapshot));result['scopes'].clear()
        self.assertEqual(len(block.to_dict()['scopes']),1)

    def test_cancellation_closed_stale_and_final_encoding_changes_abort(self):
        program=expressions.program();plan=s.plan(program,self.roots(),specification(program));view=self.fixture.view()
        def stop():raise RuntimeError('fixture cancellation')
        with patch.object(r,'evaluate',side_effect=AssertionError('must not evaluate')):
            with self.assertRaisesRegex(RuntimeError,'fixture cancellation'):s.evaluate(plan,view,stop)
        original=s._encode
        def stale(value,maximum,checkpoint=lambda:None):
            text=original(value,maximum,checkpoint)
            if type(value) is dict and value.get('format')=='scalar-selection' and value.get('evaluation'):
                self.fixture.stale=True
            return text
        with patch.object(s,'_encode',side_effect=stale):
            with self.assertRaisesRegex(ValueError,'stale'):s.evaluate(plan,view)
        self.fixture.stale=False;view.close()
        with self.assertRaisesRegex(ValueError,'closed'):s.evaluate(plan,view)

    def test_cancellation_inside_selection_and_final_encoding(self):
        program=expressions.program();plan=s.plan(program,self.roots(),specification(program));view=self.fixture.view()
        def stop():raise RuntimeError('selection interrupted')
        original=s.policy.select
        def cancelled(*args):return original(args[0],args[1],stop)
        with patch.object(s.policy,'select',side_effect=cancelled):
            with self.assertRaisesRegex(RuntimeError,'selection interrupted'):s.evaluate(plan,view)
        encode=s._encode
        def cancel_final(value,maximum,checkpoint=lambda:None):
            if type(value) is dict and value.get('format')=='scalar-selection' and value.get('evaluation'):
                checkpoint=stop
            return encode(value,maximum,checkpoint)
        with patch.object(s,'_encode',side_effect=cancel_final):
            with self.assertRaisesRegex(RuntimeError,'selection interrupted'):s.evaluate(plan,view)

    def test_loaded_source_policy_and_generation_changes_abort(self):
        program=expressions.program();plan=s.plan(program,self.roots(),specification(program));view=self.fixture.view()
        for owner,attribute in ((s,'_LOADED_SELECTION'),(s.policy,'_LOADED_POLICY')):
            with patch.object(owner,attribute,'changed'):
                self.error('STALE_INPUT_GENERATION',s.evaluate,plan,view)
        original=r.evaluate
        def changed(*args):
            block=original(*args);view.identity='changed';return block
        with patch.object(r,'evaluate',side_effect=changed):
            self.error('STALE_INPUT_GENERATION',s.evaluate,plan,view)


class PopulationAdmissionSelectionTests(unittest.TestCase):
    def test_complete_population_and_legacy_buffer_cannot_expand(self):
        fixture=fixtures.PopulationAdmissionTests('test_complete_population_buffer_order_and_uncached_names')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.add_population()
        roots=[dict(symbol=symbol,pool=pool,mode='historical',date='2015-01-02') for symbol,pool in [('Z249','legacy'),('Z250','legacy'),('Z005','legacy'),('Z250','cached')]]
        program=expressions.program(language.constant('5'))
        block=s.evaluate(s.plan(program,roots,specification(program)),fixture.view())
        values=block.to_dict()
        self.assertEqual([[row['symbol'] for row in scope['selected']] for scope in values['scopes']],[['Z249'],['Z250']])
        self.assertEqual(values['scopes'][0]['selected'][0]['candidate_rank'],250)
        self.assertEqual([row['reason'] for row in values['evaluation']['observations']['roots']],[None,'OUTSIDE_LEGACY_BUFFER','MISSING_CACHED_PRICES',None])
        self.assertEqual(block.to_dict(),json.loads(block.to_json()))


class PopulationSelectionTests(unittest.TestCase):
    """Several companies pass through the actual provider and evaluator together."""
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.db.executescript(source.SCHEMA+'CREATE TABLE companies(symbol TEXT PRIMARY KEY);')
        self.scores={'A':3.,'B':2.,'C':1.,'NEG':-2.,'PZERO':0.,'ZERO':-0.,'MISSING':None}
        self.reports={symbol:[fixtures.statement('2014-06-30')] for symbol in self.scores}
        for symbol,score in self.scores.items():
            self.db.execute('INSERT INTO companies VALUES(?)',(symbol,))
            values=fixtures.annual(100. if symbol=='A' else 200.,score)
            if score is None:values['operatingIncome']=fixtures.state(None,'MISSING_INPUT')
            self.db.execute('INSERT INTO observation_annual VALUES(?,?,?,?)',(symbol,'income-statement','2014-06-30',source.encoded(values)))
            self.db.execute('INSERT INTO observation_sources VALUES(?,?,?)',(symbol,'income-statement',source.encoded(dict(disposition='valid',sha256='a'*64))))
            for pool in ('legacy','cached'):
                source.store_latest(self.db,symbol,pool,dict(root_date='2015-01-05',admitted=True,reason=None,
                    candidate_rank=None if symbol in ('PZERO','ZERO') else 1,
                    statement=source.ReadView._statement(self.reports[symbol][0]),
                    valuation=dict(market_cap=150e6,enterprise_value=180e6,ebitda=54e6),
                    adjusted_price=['2015-01-05',10.],fiscal_price=['2014-06-30',10.],valuation_price=['2015-01-05',10.]))
        metadata=source.finish(self.db,'2015-01-05')
        self.view=source.ReadView('private-population',self.db,lambda:None,
            lambda symbol,pool:[source.ReadView._statement(row) for row in self.reports.get(symbol,[])],
            lambda symbol,day,*args:(day,10.),expected=metadata,max_history=16384,max_record_bytes=4*1024*1024,
            bounds=dict(historical_through='2015-01-02',latest_date='2015-01-05',population=7,report_rows=7,max_reports=1,max_annual=1),
            populations=lambda checkpoint:books.pools(self.reports),cached=lambda symbol:symbol in self.reports,
            session=lambda day:str(day)=='2015-01-02')
        self.addCleanup(self.view.close)
        self.rank=language.entry(language.definition(expressions.parameter('annual.operating_income'),'USD','usd'),'draft:rank')
        self.gate=language.entry(language.definition(expressions.parameter(),'USD','usd'),'draft:gate')
        self.program=d.validate(language.bundle(self.rank,self.gate,roots=[language.root(self.rank),language.root(self.gate)]))

    def roots(self,pool,mode):
        return [dict(symbol=symbol,pool=pool,mode=mode,date='2015-01-02' if mode=='historical' else '2015-01-05') for symbol in reversed(self.scores)]

    def test_actual_provider_both_modes_pools_orders_directions_no_refill(self):
        conditions=[dict(**language.root(self.gate),op='gt',threshold=dict(value='150',unit='USD'))]
        for pool in ('legacy','cached'):
            for mode in ('historical','latest'):
                for direction in ('highest','lowest'):
                    for order in ('filter_first','rank_first'):
                        settings=specification(self.program,direction=direction,order=order,conditions=conditions,rank_to=2)
                        result=s.evaluate(s.plan(self.program,self.roots(pool,mode),settings),self.view).to_dict()['scopes'][0]
                        rows=result['selected']
                        if direction=='highest':
                            self.assertEqual([(row['symbol'],row['rank']) for row in rows],[('B',1),('C',2)] if order=='filter_first' else [('B',2)])
                        else:
                            self.assertEqual([(row['symbol'],row['rank']) for row in rows],[('NEG',1),('PZERO',2)])
                        self.assertEqual([row['weight'] for row in rows],[1/len(rows)]*len(rows))
                        self.assertNotIn('MISSING',[row['symbol'] for row in rows])

    def test_provider_null_rank_and_signed_zero_ties_remain_available(self):
        settings=specification(self.program,rank_from=4,rank_to=5)
        block=s.evaluate(s.plan(self.program,self.roots('cached','latest'),settings),self.view).to_dict()
        rows=block['scopes'][0]['selected']
        self.assertEqual([row['symbol'] for row in rows],['PZERO','ZERO'])
        self.assertEqual([row['candidate_rank'] for row in rows],[None,None])
        self.assertEqual([math.copysign(1,row['ranking_value']) for row in rows],[1.,-1.])


if __name__=='__main__':unittest.main()
