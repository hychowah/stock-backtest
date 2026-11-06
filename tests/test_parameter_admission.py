"""The language check (definitions.require_program) is the one formula gate.

Captured formulas restore and run without a second gate, so the column
evaluator must implement the whole language; the guard test evaluates every
operation, statistic and /3 parameter through columns.Formulas.
"""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import subprocess
import unittest
from unittest.mock import Mock
from backtest.variables import columns, definitions as d, parameters, library
from backtest.application import strategy_requests as s, scalar_execution, variable_authoring
from test_columns import Company, annual
from test_variable_definitions import definition, constant, entry, root, bundle, binary
from test_strategy_requests import intent, formula, condition
from test_parameter_contract import expanded

ROOTS=[dict(symbol='A',pool='cached',mode='historical',date='2015-01-02')]


def capture(entries):
    return s.capture_strategy(intent(formula(entries[0])),submitted=entries)


def expanded_cases():
    yield [entry(expanded())]
    yield [entry(expanded(dict(op='parameter',id='annual.revenue'),'USD','usd'))]
    for identity,unit,display in (
        ('annual.net_income','USD','usd'),('annual.equity','USD','usd'),
        ('annual.net_acquisitions','USD','usd'),('market.volume','share','shares'),
        ('treasury.us_3m','scalar','percent'),('market.adjusted_price','USD/share','usd_per_share')):
        yield [entry(expanded(dict(op='parameter',id=identity),unit,display))]
    yield [entry(definition(),'old-root'),entry(expanded(),'unused-new')]


class AdmissionTests(unittest.TestCase):
    def test_every_v2_case_restores_and_is_admitted(self):
        for entries in expanded_cases():
            with self.subTest(parameter=entries[0]['definition']['expression']):
                captured=capture(entries)
                self.assertEqual(s.require_strategy(captured),captured.to_dict())
                variable=library.VariableCapture(d.canonical(captured.to_dict()['variables']))
                self.assertEqual(library.require_capture(variable),variable.to_dict())
                program=variable.program
                self.assertEqual(d.require_program(program),program.to_dict())
                options=dict(strategy=captured.to_dict(),engine='original')
                self.assertEqual(s.check_options(options),captured.to_dict())

    def test_column_evaluator_accepts_constants_old_inputs_and_unused_v2_definitions(self):
        # Evaluation of these programs reaches input admission.
        for entries in (list(expanded_cases())[0],list(expanded_cases())[1],list(expanded_cases())[-1]):
            program=d.validate(bundle(*entries,roots=[root(entries[0])]))
            inputs=Mock();inputs.admit.side_effect=AssertionError('Column evaluation reached inputs')
            with self.assertRaisesRegex(AssertionError,'Column evaluation reached inputs'):
                scalar_execution.evaluate_preview(d.require_program(program),ROOTS,inputs)
            inputs.admit.assert_called_once()

    def test_the_evaluator_implements_every_operation_statistic_and_parameter(self):
        # Development guard: a language addition fails here until columns.py implements it.
        self.assertEqual({item['id'] for item in columns.catalog()},
                         {item['id'] for item in parameters.catalog(parameters.V3)})
        units=parameters.units(parameters.V3)
        def version3(expression,unit='scalar',identity=None):
            value=dict(definition(expression,unit,units[unit]['displays'][0]),version=3,parameter_catalog=parameters.V3)
            return entry(value,identity or 'draft:'+expression['op'])
        one,two=constant('1'),constant('2')
        target=version3(one)
        revenue=dict(op='parameter',id='annual.revenue')
        operations={op:([version3(binary(op,one,two))],value) for op,value in (
            ('add',3.),('sub',-1.),('mul',2.),('div',.5),('positive_div',.5))}
        operations.update(constant=([target],1.),neg=([version3(dict(op='neg',arg=one))],-1.),
            at=([version3(dict(op='at',date='2014-01-02',arg=one))],1.),
            lookback=([version3(dict(op='lookback',months=12,arg=one))],1.),
            parameter=([version3(revenue,'USD')],400.),
            annual=([version3(dict(op='annual',stat='mean',count=2,parameter='annual.revenue'),'USD')],300.),
            ref=([target,version3(dict(op='ref',**root(target)))],1.))
        self.assertEqual(set(operations),d.OPERATIONS)
        statistics={'mean':700/3,'min':100.,'max':400.,'growth':3.,'cagr':1.}
        self.assertEqual(set(statistics),{stat for item in parameters.catalog(parameters.V3)
                                          for stat in item['history']['statistics']})
        cases=[(('op',op),entries,value) for op,(entries,value) in operations.items()]
        for stat,value in statistics.items():
            unit='scalar' if stat in ('growth','cagr') else 'USD'
            cases.append((('stat',stat),[version3(dict(op='annual',stat=stat,count=3,parameter='annual.revenue'),unit)],value))
        for item in parameters.catalog(parameters.V3):
            cases.append((('parameter',item['id']),[version3(dict(op='parameter',id=item['id']),item['unit'])],None))
            if item['id'].startswith('annual.'):
                cases.append((('annual',item['id']),[version3(dict(op='annual',stat='mean',count=2,
                                                                   parameter=item['id']),item['unit'])],None))
        company=Company()
        company.annual={f'{year}-06-30':annual(revenue,10.) for year,revenue in ((2012,100.),(2013,200.),(2014,400.))}
        self.addCleanup(company.close)
        roots=[dict(symbol='A',pool='legacy',mode='historical',date=company.root_date)]
        with company.view() as view:
            decisions=view.admit(roots)
            self.assertTrue(decisions[0]['admitted'])
            for name,entries,expected in cases:
                with self.subTest(case=name):
                    formulas=columns.Formulas(d.require_program(d.validate(bundle(*entries))))
                    formulas.require_contexts(roots)
                    values=formulas.evaluate(roots,view,lambda:None,decisions=decisions)[0]
                    block=formulas.explain(roots,view,lambda:None,decisions=decisions)
                    (result,)=block['results']
                    self.assertEqual(values[result['variable_id'],result['revision']],
                                     (result['value'],result['valid'],result['reason']))
                    if expected is not None:
                        self.assertEqual((result['value'],result['reason']),(expected,None))
                    else:
                        self.assertTrue(result['valid'] or result['reason'])

    def test_legacy_catalog_stays_four_while_expanded_authoring_supports_shares(self):
        expected=['annual.revenue','annual.operating_income','annual.operating_margin','market.enterprise_value']
        self.assertEqual(len(columns.catalog()),77)
        self.assertEqual([item['id'] for item in columns.catalog()][:4],expected)
        value=variable_authoring.catalog()
        self.assertEqual([item['id'] for item in value['parameters']],expected)
        self.assertEqual(value['operations'],sorted(d.OPERATIONS))
        self.assertEqual(value['displays']['share'],parameters.units(parameters.V3)['share']['displays'])
        for catalog in (parameters.V1,parameters.V2):
            quantity=entry(dict(definition(constant('100','USD'),'USD','usd'),parameter_catalog=catalog))
            captured=s.capture_strategy(intent(formula(quantity),[condition(formula(quantity),'0.0001','usd_million')]),submitted=[quantity])
            self.assertEqual(captured.to_dict()['selection']['conditions'][0]['threshold'],dict(value='100',unit='USD'))
        shares=entry(expanded(constant('100','share'),'share','shares'))
        captured=s.capture_strategy(intent(formula(shares),[condition(formula(shares),'1.25e2','shares')]),submitted=[shares])
        self.assertEqual(captured.to_dict()['selection']['conditions'][0]['threshold'],dict(value='125',unit='share'))
        self.assertEqual(s.require_strategy(captured),captured.to_dict())

    def test_semantic_validation_restore_and_original_admission_need_no_optional_packages(self):
        code='''import importlib.abc,sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,name,*args):
  if name.split('.')[0] in ('numpy','numba','llvmlite'):raise AssertionError(name)
sys.meta_path.insert(0,Block())
from test_parameter_admission import expanded_cases,capture
from backtest.application import strategy_requests as s
from backtest.variables import library,definitions as d,columns
for entries in expanded_cases():
 c=capture(entries);s.check_options(dict(strategy=c.to_dict(),engine='original'))
 columns.Formulas(d.require_program(library.VariableCapture(d.canonical(c.to_dict()['variables'])).program))
'''
        subprocess.run([sys.executable,'-B','-c',code],cwd=Path(__file__).resolve().parent,
                       env={**__import__('os').environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1])},check=True)


if __name__=='__main__':unittest.main()
