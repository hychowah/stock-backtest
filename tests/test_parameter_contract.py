"""Independent field oracle and versioned semantic validation; no live data."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from copy import deepcopy
import hashlib
import json
import subprocess
import unittest
from unittest.mock import patch
from backtest.variables import definitions as d, parameters as p
from test_variable_definitions import definition, constant, entry, root, reference, binary, bundle

# Transcribed independently from parameter-catalog.md's four direct-input tables.
# This is deliberately not generated from parameters.py or provider capabilities.
ORACLE = {
 'income-statement': {
  'revenue': 'annual.revenue',
  'costOfRevenue': 'annual.cost_of_revenue',
  'sellingGeneralAndAdministrativeExpenses': 'annual.selling_general_administrative_expense',
  'researchAndDevelopmentExpenses': 'annual.research_development_expense',
  'operatingIncome': 'annual.operating_income',
  'interestIncome': 'annual.interest_income',
  'interestExpense': 'annual.interest_expense',
  'incomeBeforeTax': 'annual.pretax_income',
  'incomeTaxExpense': 'annual.income_tax_expense',
  'netIncome': 'annual.net_income',
  'weightedAverageShsOut': 'annual.weighted_average_basic_shares',
  'weightedAverageShsOutDil': 'annual.weighted_average_diluted_shares'},
 'balance-sheet-statement': {
  'cashAndCashEquivalents': 'annual.cash_and_equivalents',
  'shortTermInvestments': 'annual.short_term_investments',
  'longTermInvestments': 'annual.long_term_investments',
  'netReceivables': 'annual.net_receivables',
  'accountsReceivables': 'annual.accounts_receivable',
  'inventory': 'annual.inventory',
  'prepaids': 'annual.prepaid_expenses',
  'totalCurrentAssets': 'annual.current_assets',
  'propertyPlantEquipmentNet': 'annual.property_plant_equipment_net',
  'goodwill': 'annual.goodwill',
  'intangibleAssets': 'annual.intangible_assets',
  'totalAssets': 'annual.total_assets',
  'accountPayables': 'annual.accounts_payable',
  'accruedExpenses': 'annual.accrued_expenses',
  'deferredRevenue': 'annual.current_deferred_revenue',
  'deferredRevenueNonCurrent': 'annual.noncurrent_deferred_revenue',
  'totalCurrentLiabilities': 'annual.current_liabilities',
  'totalLiabilities': 'annual.total_liabilities',
  'shortTermDebt': 'annual.short_term_debt',
  'longTermDebt': 'annual.long_term_debt',
  'capitalLeaseObligations': 'annual.lease_obligations',
  'totalStockholdersEquity': 'annual.equity',
  'preferredStock': 'annual.preferred_stock',
  'minorityInterest': 'annual.noncontrolling_interests'},
 'cash-flow-statement': {
  'depreciationAndAmortization': 'annual.depreciation_amortization',
  'stockBasedCompensation': 'annual.stock_based_compensation',
  'operatingCashFlow': 'annual.operating_cash_flow',
  'capitalExpenditure': 'annual.capital_expenditure',
  'acquisitionsNet': 'annual.net_acquisitions',
  'incomeTaxesPaid': 'annual.income_taxes_paid',
  'interestPaid': 'annual.interest_paid',
  'netDebtIssuance': 'annual.net_debt_issuance',
  'commonDividendsPaid': 'annual.common_dividends_paid',
  'preferredDividendsPaid': 'annual.preferred_dividends_paid',
  'commonStockRepurchased': 'annual.common_stock_repurchased',
  'commonStockIssuance': 'annual.common_stock_issuance'},
 'historical-price-eod/dividend-adjusted': {
  'adjClose': 'market.adjusted_price', 'volume': 'market.volume'},
 'treasury-rates': {'month3': 'treasury.us_3m', 'year10': 'treasury.us_10y'},
}


def expanded(expression=None, unit='scalar', display='number'):
    return dict(definition(expression, unit, display), parameter_catalog=p.V2)


class ParameterTests(unittest.TestCase):
    def error(self, code, function, *args, **kwargs):
        with self.assertRaises(d.FormulaError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_exact_52_mapping_and_two_adapters(self):
        actual = p.catalog(p.V2)
        self.assertEqual(len(actual), 54)
        self.assertEqual(len({item['id'] for item in actual}), 54)
        direct = [item for item in actual if item['kind'] == 'direct']
        self.assertEqual(len(direct), 52)
        expected = {(endpoint, field): identity for endpoint, fields in ORACLE.items()
                    for field, identity in fields.items()}
        self.assertEqual({(item['source']['endpoint'], item['source']['field']): item['id']
                          for item in direct}, expected)
        self.assertEqual({item['id'] for item in actual if item['kind'] == 'adapter'},
                         {'annual.operating_margin', 'market.enterprise_value'})
        self.assertEqual([len(ORACLE[key]) for key in ('income-statement', 'balance-sheet-statement',
                          'cash-flow-statement')], [12, 24, 12])

    def test_every_field_units_sign_history_and_omissions(self):
        share_ids = {'annual.weighted_average_basic_shares',
                     'annual.weighted_average_diluted_shares', 'market.volume'}
        for item in p.catalog(p.V2):
            expected_unit = ('share' if item['id'] in share_ids else 'scalar'
                if item['id'] in ('annual.operating_margin', 'treasury.us_3m', 'treasury.us_10y')
                else 'USD/share' if item['id'] == 'market.adjusted_price' else 'USD')
            self.assertEqual(item['unit'], expected_unit, item['id'])
            self.assertEqual(item['contexts'], ['root', 'at', 'lookback'])
            annual = item['id'].startswith('annual.')
            self.assertEqual(item['counts'], dict(minimum=1, maximum=10 if annual else 1))
            self.assertEqual(item['history']['statistics'], ['mean', 'min', 'max'] if annual else [])
            if annual:
                self.assertTrue(item['history']['complete'])
                self.assertTrue(item['history']['consecutive'])
                self.assertEqual(item['timing'], dict(availability='fiscal-plus-90-strict-before-context', anchor_max_days=800))
            self.assertIn('unavailable-with-reason', item['omission'])
            self.assertIn('no zero', item['omission'])
            if item['kind'] == 'direct':
                self.assertEqual(item['sign'], 'reported; no absolute value or sign inversion')
                self.assertEqual(item['conversion'], 'provider-percent-divided-by-100'
                    if item['id'].startswith('treasury.') else 'identity')
        self.assertEqual(p.parameter(p.V2, 'market.volume')['sampling'], 'session-volume')
        self.assertEqual(p.parameter(p.V2, 'annual.weighted_average_basic_shares')['sampling'],
                         'annual-period-weighted-average')
        self.assertEqual(p.parameter(p.V2, 'annual.depreciation_amortization')['source']['endpoint'], 'cash-flow-statement')

    def test_exclusions_and_frozen_v1_vocabulary(self):
        self.assertEqual([item['id'] for item in p.catalog(p.V1)],
            ['annual.revenue', 'annual.operating_income', 'annual.operating_margin', 'market.enterprise_value'])
        self.assertEqual(set(p.units(p.V1)), {'scalar', 'USD', 'USD/share'})
        self.assertEqual(set(p.units(p.V2)), {'scalar', 'USD', 'USD/share', 'share'})
        for identity in ('annual.ebitda', 'annual.total_debt', 'annual.free_cash_flow',
            'annual.depreciation', 'annual.amortization', 'annual.restricted_cash',
            'annual.gross_borrowing', 'annual.gross_acquisitions', 'market.shares_outstanding',
            'market.unadjusted_price', 'annual.common_net_income'):
            with self.assertRaises(ValueError):p.parameter(p.V2, identity)
        with self.assertRaises(ValueError):p.parameter(p.V1, 'annual.net_income')
        for version in ('financial-parameters/4', None, [], 2):
            with self.assertRaises(ValueError):p.catalog(version)
            self.error('UNKNOWN_VERSION', d.revision, dict(definition(), parameter_catalog=version))
        first=p.catalog(p.V2);first[0]['source']['field']='forged'
        units=p.units(p.V2);units['share']['dimensions']['share']=99
        self.assertEqual(p.catalog(p.V2)[0]['source']['field'], 'revenue')
        self.assertEqual(p.unit(p.V2,'share'), dict(dimensions={'share':1},displays=['shares']))

    def test_every_direct_parameter_normalizes_and_lowers_under_its_catalog(self):
        for endpoint, fields in ORACLE.items():
            for field, identity in fields.items():
                unit=('share' if field in ('volume','weightedAverageShsOut','weightedAverageShsOutDil')
                      else 'USD/share' if field=='adjClose' else 'scalar' if endpoint=='treasury-rates' else 'USD')
                display={'share':'shares','USD':'usd','USD/share':'usd_per_share','scalar':'number'}[unit]
                value=entry(expanded(dict(op='parameter',id=identity),unit,display))
                checked=d.require_program(d.validate(bundle(value)))
                self.assertEqual(checked['nodes'][0]['dimensions'],p.unit(p.V2,unit)['dimensions'])
                self.assertEqual(checked['requirements'],[dict(node='n0',parameter=identity,count=1)])
                if identity.startswith('annual.'):
                    for stat in ('mean','min','max'):
                        value=entry(expanded(dict(op='annual',parameter=identity,stat=stat,count=10),unit,display))
                        self.assertEqual(d.validate(bundle(value)).to_dict()['nodes'][0]['count'],10)
                    self.error('INVALID_SHAPE',d.revision,expanded(dict(op='annual',parameter=identity,stat='mean',count=11),unit,display))
                else:
                    self.error('UNSUPPORTED_OPERATION',d.revision,expanded(dict(op='annual',parameter=identity,stat='mean',count=1),unit,display))

    def test_share_arithmetic_and_exact_thresholds(self):
        price=constant('12.5','USD/share');shares=constant('100','share')
        examples=[(binary('mul',price,shares),'USD','usd'),
                  (binary('div',constant('1250','USD'),shares),'USD/share','usd_per_share'),
                  (binary('div',constant('1250','USD'),price),'share','shares'),
                  (binary('div',shares,shares),'scalar','number'),
                  (binary('sub',shares,shares),'share','shares')]
        for expression,unit,display in examples:
            program=d.validate(bundle(entry(expanded(expression,unit,display))))
            self.assertEqual(d.require_program(program)['definitions'][0]['unit'],unit)
        self.error('UNIT_MISMATCH',d.validate,bundle(entry(expanded(binary('add',price,shares)))))
        self.error('UNSUPPORTED_OUTPUT_UNIT',d.validate,bundle(entry(expanded(binary('mul',shares,shares)))))
        for value in ('share','shares'):
            normalized=d.normalize_quantity(dict(value='+001.2300e2',unit=value),'share')
            self.assertEqual(normalized['threshold'],dict(value='123',unit='share'))
            self.assertEqual(normalized['comparison_value'],123.)
        self.error('INVALID_LITERAL',d.normalize_quantity,dict(value='1e309',unit='shares'),'share')
        self.error('INVALID_LITERAL',d.normalize_quantity,dict(value='1e-324',unit='shares'),'share')
        self.error('UNIT_MISMATCH',d.normalize_quantity,dict(value='1',unit='usd'),'share')

    def test_v1_does_not_acquire_share_constants_outputs_or_parameters(self):
        self.error('UNIT_MISMATCH',d.revision,definition(constant('1','share')))
        self.error('UNSUPPORTED_OUTPUT_UNIT',d.revision,definition(constant(), 'share','shares'))
        self.error('UNKNOWN_PARAMETER',d.revision,definition(dict(op='parameter',id='annual.net_income'),'USD','usd'))
        self.error('UNIT_MISMATCH',d.revision,expanded(constant('1','share'),'share','number'))

    def test_mixed_catalog_references_use_owning_root_vocabulary(self):
        old=entry(definition(constant('12.5','USD/share'),'USD/share','usd_per_share'),'old')
        new=entry(expanded(binary('mul',reference(old),constant('100','share')),'USD','usd'),'new')
        old_root=entry(definition(reference(new),'USD','usd'),'old-root')
        program=d.validate(bundle(old,new,old_root))
        self.assertEqual([v['unit'] for v in d.require_program(program)['definitions']],['USD/share','USD','USD'])
        share=entry(expanded(constant('100','share'),'share','shares'),'shares')
        # /1 can cancel share dimensions internally but cannot expose share roots.
        cancel=entry(definition(binary('div',reference(share),reference(share))),'cancel')
        d.validate(bundle(share,cancel))
        bad=entry(definition(binary('div',constant('100','USD'),reference(old))),'bad')
        self.error('UNSUPPORTED_OUTPUT_UNIT',d.validate,bundle(old,bad))

    def test_checked_restore_rebuilds_all_derived_content(self):
        value=entry(expanded(dict(op='parameter',id='annual.weighted_average_basic_shares'),'share','shares'))
        original=d.validate(bundle(value))
        for change in (lambda x:x['nodes'][0]['dimensions'].update(share=2),
                       lambda x:x['requirements'][0].update(parameter='annual.revenue'),
                       lambda x:x['definitions'][0].update(unit='USD'),
                       lambda x:x['bundle']['definitions'][0]['definition'].update(parameter_catalog=p.V1)):
            changed=original.to_dict();change(changed)
            with self.assertRaises(d.FormulaError):d.require_program(d.FormulaProgram(d.canonical(changed)))

    def test_source_binding_and_financial_free_semantic_import(self):
        old=d.policy_fingerprint()
        with patch.object(p,'policy_fingerprint',return_value='a'*64):
            self.assertNotEqual(d.policy_fingerprint(),old)
        code='''import importlib.abc,sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,name,*args):
  if name.startswith(('numpy','numba','llvmlite','backtest.financial','backtest.inputs','backtest.runtime','backtest.variables.library')):raise AssertionError(name)
sys.meta_path.insert(0,Block())
from backtest.variables import parameters,definitions
assert len(parameters.catalog(parameters.V2))==54
'''
        subprocess.run([sys.executable,'-B','-c',code],cwd=Path(__file__).resolve().parents[1],check=True)


if __name__=='__main__':unittest.main()
