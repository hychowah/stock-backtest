"""The single qualified scalar gate for Original formula execution.

require_program(program) admits a captured program before readiness or any
financial input: a fixed inventory of parameter IDs, operations, annual
statistics and definition namespaces. Recognized meaning or evaluator support
alone grants no application qualification.
"""
from backtest.variables import columns, definitions

# Fixed qualification inventory. Provider or language expansion alone does not
# qualify application execution. Admission remains closed until verified.
QUALIFIED_PARAMETERS = ('annual.revenue',
 'annual.operating_income',
 'annual.operating_margin',
 'market.enterprise_value',
 'annual.report_ebitda',
 'owner.market_cap',
 'owner.profit_margin',
 'owner.pe',
 'owner.pb',
 'owner.fcf_yield',
 'owner.price_fcf',
 'owner.peg',
 'owner.roe',
 'owner.current_ratio',
 'owner.interest_coverage',
 'owner.debt_equity',
 'owner.return_1y',
 'owner.return_3y',
 'owner.ev_ebitda',
 'owner.ev_ebitda_3y',
 'owner.ebitda_yield',
 'owner.operating_yield_spread_3y',
 'annual.cost_of_revenue',
 'annual.selling_general_administrative_expense',
 'annual.research_development_expense',
 'annual.interest_income',
 'annual.interest_expense',
 'annual.pretax_income',
 'annual.income_tax_expense',
 'annual.net_income',
 'annual.weighted_average_basic_shares',
 'annual.weighted_average_diluted_shares',
 'annual.cash_and_equivalents',
 'annual.short_term_investments',
 'annual.long_term_investments',
 'annual.net_receivables',
 'annual.accounts_receivable',
 'annual.inventory',
 'annual.prepaid_expenses',
 'annual.current_assets',
 'annual.property_plant_equipment_net',
 'annual.goodwill',
 'annual.intangible_assets',
 'annual.total_assets',
 'annual.accounts_payable',
 'annual.accrued_expenses',
 'annual.current_deferred_revenue',
 'annual.noncurrent_deferred_revenue',
 'annual.current_liabilities',
 'annual.total_liabilities',
 'annual.short_term_debt',
 'annual.long_term_debt',
 'annual.lease_obligations',
 'annual.equity',
 'annual.preferred_stock',
 'annual.noncontrolling_interests',
 'annual.depreciation_amortization',
 'annual.stock_based_compensation',
 'annual.operating_cash_flow',
 'annual.capital_expenditure',
 'annual.net_acquisitions',
 'annual.income_taxes_paid',
 'annual.interest_paid',
 'annual.net_debt_issuance',
 'annual.common_dividends_paid',
 'annual.preferred_dividends_paid',
 'annual.common_stock_repurchased',
 'annual.common_stock_issuance',
 'annual.ebit',
 'annual.basic_eps',
 'annual.diluted_eps',
 'annual.total_debt',
 'annual.free_cash_flow',
 'market.adjusted_price',
 'market.volume',
 'treasury.us_3m',
 'treasury.us_10y')
QUALIFIED_NAMESPACES = frozenset((version, 'financial-parameters/' + str(catalog), 'annual-lag90/1')
    for version in (1, 2, 3) for catalog in (1, 2, 3))
QUALIFIED_OPERATIONS = frozenset(('constant', 'parameter', 'annual', 'ref', 'at', 'lookback',
    'neg', 'add', 'sub', 'mul', 'div', 'positive_div'))
QUALIFIED_ANNUAL_STATISTICS = frozenset(('mean', 'min', 'max', 'growth', 'cagr'))


def _fail(code, path, message):
    raise definitions.FormulaError(code, path, message)


def require_program(program, *, checkpoint=lambda: None):
    checked = definitions.require_program(program)
    if checked['version'] != 1 or any(
            (item['definition']['version'], item['definition']['parameter_catalog'],
             item['definition']['temporal_policy']) not in QUALIFIED_NAMESPACES
            for item in checked['bundle']['definitions']):
        _fail('UNSUPPORTED_CAPABILITY', '/variables', 'Unsupported Original formula namespace.')
    for node in checked['nodes']:
        checkpoint()
        if node['op'] not in QUALIFIED_OPERATIONS or (node['op'] == 'annual' and
                node['stat'] not in QUALIFIED_ANNUAL_STATISTICS):
            _fail('UNSUPPORTED_CAPABILITY', node['path'], 'Unsupported Original formula operation.')
        if node['op'] in ('parameter', 'annual') and node['parameter'] not in QUALIFIED_PARAMETERS:
            _fail('UNSUPPORTED_CAPABILITY', node['path'], 'Unsupported Original observation parameter.')
    return columns.require_program(program, checkpoint=checkpoint)
