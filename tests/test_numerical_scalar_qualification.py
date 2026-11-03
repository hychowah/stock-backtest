"""Complete scalar evidence parity and test-only native process qualification."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from copy import deepcopy
import os
import subprocess
import unittest

from backtest import result_evidence
from backtest.application import scalar_execution
from backtest.engines.numerical import formulas
from backtest.variables import library,reference,definitions
from guarded_numerical_entries import install
from scalar_qualification import Scenario,compare_artifacts,compare_blocks,artifact_meaning
from test_scalar_execution import Fixture

ROOT=Path(__file__).resolve().parents[1]


class ComparatorTests(unittest.TestCase):
    def test_explicit_owner_scope_is_part_of_complete_meaning(self):
        import test_variable_definitions as language
        fixture=Fixture(1);self.addCleanup(fixture.db.close)
        capture=fixture.capture(language.constant('1')).to_dict()
        program=library.VariableCapture(definitions.canonical(capture['variables'])).program
        base=dict(symbol='A0000',pool='cached',mode='latest',date='2015-01-05')
        roots=[dict(base,owner_scope=dict(kind='prepared',book=0)),
               dict(base,owner_scope=dict(kind='dated'))]
        with fixture.view() as view:
            original=reference.evaluate(reference.plan(program,roots),view).to_dict()
        compare_blocks([original],[deepcopy(original)])
        for group in ('roots','contexts'):
            changed=deepcopy(original)
            changed['observations'][group][0]['owner_scope']=dict(kind='dated')
            with self.subTest(group=group),self.assertRaises(AssertionError):
                compare_blocks([original],[changed])

    def test_complete_blocks_include_unselected_missing_values_and_every_operation(self):
        fixture=Fixture(300);self.addCleanup(fixture.db.close)
        capture=fixture.capture().to_dict()
        program=library.VariableCapture(definitions.canonical(capture['variables'])).program
        roots=[dict(symbol=f'A{i:04d}',pool='cached',mode='historical',date='2015-01-02') for i in range(300)]
        plans=scalar_execution._plans(program,roots,8*1024**2,lambda:None)
        with fixture.view() as view,formulas.Evaluator() as evaluator:
            expected=[reference.evaluate(plan,view).to_dict() for plan in plans]
            actual=[evaluator.evaluate(plan,view).to_dict() for plan in plans]
            rechunked=[evaluator.evaluate(reference.plan(program,group),view).to_dict()
                for group in (roots[:128],roots[128:])]
        compare_blocks(expected,actual)
        compare_blocks(expected,rechunked)
        self.assertGreater(len(actual),1)
        for target,key,value in [('operations','value',-1.),('operations','reason','MISSING_INPUT'),
                ('operations','inputs',[]),('results','unit','scalar'),('results','revision','sha256:'+'0'*64)]:
            changed=deepcopy(actual);changed[-1][target][-1][key]=value
            with self.subTest(target=target,key=key),self.assertRaises(AssertionError):compare_blocks(expected,changed)
        changed=deepcopy(actual);changed[-1]['operations'].pop()
        with self.assertRaises((AssertionError,KeyError)):compare_blocks(expected,changed)
        changed=deepcopy(actual);changed[-1]['unrecognized']='must not disappear'
        with self.assertRaises(AssertionError):compare_blocks(expected,changed)
        changed=deepcopy(actual);changed[-1]['observations']['contexts'][0]['unrecognized']=True
        with self.assertRaises(AssertionError):compare_blocks(expected,changed)
        changed=deepcopy(actual);changed[-1]['observations']['results'][0]['members'][0]['fiscal_date']='2013-06-30'
        with self.assertRaises(AssertionError):compare_blocks(expected,changed)

    def test_denominator_rule_is_not_normalized_away(self):
        import test_variable_definitions as language
        fixture=Fixture(1);self.addCleanup(fixture.db.close)
        capture=fixture.capture(language.binary('div',language.constant('1'),language.constant('2'))).to_dict()
        program=library.VariableCapture(definitions.canonical(capture['variables'])).program
        roots=[dict(symbol='A0000',pool='cached',mode='historical',date='2015-01-02')]
        with fixture.view() as view:
            original=reference.evaluate(reference.plan(program,roots),view).to_dict()
        changed=deepcopy(original)
        next(item for item in changed['operations'] if 'denominator_rule' in item)['denominator_rule']='changed'
        with self.assertRaises(AssertionError):compare_blocks([original],[changed])

    def test_chunk_local_identifiers_do_not_change_resolved_meaning(self):
        fixture=Fixture(2);self.addCleanup(fixture.db.close)
        program=library.VariableCapture(definitions.canonical(fixture.capture().to_dict()['variables'])).program
        roots=[dict(symbol='A0000',pool='cached',mode='historical',date='2015-01-02')]
        with fixture.view() as view:original=reference.evaluate(reference.plan(program,roots),view).to_dict()
        changed=deepcopy(original)
        contexts={item['id']:'context:'+item['id'] for item in changed['observations']['contexts']}
        tasks={item['id']:'task:'+item['id'] for item in changed['operations']}
        observed={item['id']:'observation:'+item['id'] for item in changed['observations']['results']}
        for item in changed['observations']['roots']:item['root']=contexts[item['root']]
        for item in changed['observations']['contexts']:
            item['id']=contexts[item['id']];item['root']=contexts[item['root']]
        for item in changed['observations']['results']:
            item['id']=observed[item['id']];item['context']=contexts[item['context']];item['root']=contexts[item['root']]
        for item in changed['operations']:
            item['id']=tasks[item['id']];item['context']=contexts[item['context']]
            item['operands']=[tasks[key] for key in item['operands']]
            if 'observation' in item:item['observation']=observed[item['observation']]
        for item in changed['results']:
            item['root']=contexts[item['root']]
            item['evidence']['admission']=contexts[item['evidence']['admission']]
            item['evidence']['operation']=tasks[item['evidence']['operation']]
        compare_blocks([original],[changed])

    def test_signed_zero_difference_is_not_hidden_by_python_numeric_equality(self):
        import test_variable_definitions as language
        fixture=Fixture(1);self.addCleanup(fixture.db.close)
        capture=fixture.capture(dict(op='neg',arg=language.constant('0'))).to_dict()
        program=library.VariableCapture(definitions.canonical(capture['variables'])).program
        roots=[dict(symbol='A0000',pool='cached',mode='historical',date='2015-01-02')]
        with fixture.view() as view:original=reference.evaluate(reference.plan(program,roots),view).to_dict()
        changed=deepcopy(original)
        changed['results'][0]['value']=0.0
        with self.assertRaises(AssertionError):compare_blocks([original],[changed])


class ApplicationQualificationTests(unittest.TestCase):
    def setUp(self):
        if sys.platform=='win32':
            before,original_null=subprocess.Popen,os.devnull
            install(ROOT)
            self.addCleanup(setattr,subprocess,'Popen',before)
            self.addCleanup(setattr,os,'devnull',original_null)

    def test_all_four_application_modes_compare_complete_artifact_meaning(self):
        with Scenario(companies=12,first=2015,last=2016) as scenario:
            for mode in ('latest','january','custom','random'):
                with self.subTest(mode=mode):
                    options=scenario.options(mode,**(dict(trials=2) if mode=='random' else {}))
                    left,_,_=scenario.run_backend('original',mode,options)
                    right,measured,_=scenario.run_backend('experimental',mode,options)
                    compared=compare_artifacts(left,right)
                    self.assertGreater(compared['holdings'],0)
                    self.assertGreater(compared['operations'],0)
                    self.assertEqual(measured['closure']['state'],'closed')
                    if mode=='latest':
                        self.assertEqual(compared['trials'],0)
                        self.assertTrue(all('return_value' not in row['value'] for row in right.records() if row['type']=='screen'))
                    if mode=='custom':
                        # These are semantic comparator probes, not forged codec
                        # input. Actual readers separately verify physical hashes.
                        class Altered:
                            metadata=right.metadata;manifest=right.manifest
                            def records(self):return iter(self.rows)
                        for kind,field,value in [('holding','rank',999),('holding','weight',.99),
                                ('holding','return_value',-.99)]:
                            altered=Altered();altered.rows=deepcopy(list(right.records()))
                            next(row['value'] for row in altered.rows if row['type']==kind)[field]=value
                            with self.subTest(field=field),self.assertRaises(AssertionError):compare_artifacts(left,altered)
                        altered=Altered();altered.rows=deepcopy(list(right.records()))
                        result=next(item for row in altered.rows if row['type']=='evaluation'
                            for item in row['value']['block']['results'] if not item['valid'])
                        result['reason']='CHANGED_UNAVAILABLE_REASON'
                        with self.assertRaises(AssertionError):compare_artifacts(left,altered)

    def test_complete_scope_over_multiple_chunks_keeps_old_revisions_and_missing_evidence(self):
        with Scenario(companies=300,first=2015,last=2015) as scenario:
            options=scenario.options('custom')
            left,_,_=scenario.run_backend('original','custom',options)
            right,_,_=scenario.run_backend('experimental','custom',options)
            comparison=compare_artifacts(left,right)
            self.assertGreater(comparison['evaluations'],1)
            self.assertGreater(comparison['operations'],300)
            results=[item for row in right.records() if row['type']=='evaluation' for item in row['value']['block']['results']]
            self.assertTrue(any(not item['valid'] for item in results))
            self.assertTrue(any(item['valid'] and item['value']<0 for item in results))
            identities={(item['variable_id'],item['revision']) for item in results}
            self.assertEqual(identities,{(item['variable_id'],item['revision'])
                for item in scenario.capture.to_dict()['variables']['program']['bundle']['roots']})


if __name__=='__main__':unittest.main()
