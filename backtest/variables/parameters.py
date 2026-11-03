"""Versioned financial meaning, separate from observations and backend support.

Catalog recognition never grants execution or company/date availability. Annual
facts use one selected fiscal period, strict fiscal-plus-90 availability before
the context date and an 800-day anchor limit. Complete consecutive annual
histories permit mean/min/max over 1–10 periods. Missing selected-period fields
cannot be filled from newer reports, another endpoint or a different aggregate.

Market/rate contexts have dated lookup evidence, not annual reporting timing.
Session volume requires its own saved session value; a saved price supplies no
volume. Null, conflicting, nonfinite or unavailable values stay unavailable with
reasons, never zero. No calendar statistics, growth, quarterly or TTM operations
are introduced here. All public projections are detached JSON-compatible values.
"""
import copy
import hashlib
from pathlib import Path

V1 = 'financial-parameters/1'
V2 = 'financial-parameters/2'
_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_UNITS = {
    'scalar': dict(dimensions={}, displays=['number', 'multiple', 'percent', 'percentage_points']),
    'USD': dict(dimensions={'USD': 1}, displays=['usd', 'usd_million']),
    'USD/share': dict(dimensions={'USD': 1, 'share': -1}, displays=['usd_per_share']),
    'share': dict(dimensions={'share': 1}, displays=['shares']),
}
# Field identity is part of meaning. These are direct fields, not replacement
# calculations for the existing market-cap, total-debt or enterprise-value policy.
_INCOME = (
    ('revenue', 'revenue', 'Revenue'),
    ('cost_of_revenue', 'costOfRevenue', 'Cost of revenue'),
    ('selling_general_administrative_expense', 'sellingGeneralAndAdministrativeExpenses', 'Selling, general and administrative expense'),
    ('research_development_expense', 'researchAndDevelopmentExpenses', 'Research and development expense'),
    ('operating_income', 'operatingIncome', 'Operating income'),
    ('interest_income', 'interestIncome', 'Interest income'),
    ('interest_expense', 'interestExpense', 'Interest expense'),
    ('pretax_income', 'incomeBeforeTax', 'Pretax income'),
    ('income_tax_expense', 'incomeTaxExpense', 'Income tax expense'),
    ('net_income', 'netIncome', 'Net income under the existing FMP definition; no common-only attribution claim'),
    ('weighted_average_basic_shares', 'weightedAverageShsOut', 'Annual weighted-average basic shares; not exact dated shares'),
    ('weighted_average_diluted_shares', 'weightedAverageShsOutDil', 'Annual weighted-average diluted shares; not exact dated shares'),
)
_BALANCE = (
    ('cash_and_equivalents', 'cashAndCashEquivalents', 'Cash and cash equivalents'),
    ('short_term_investments', 'shortTermInvestments', 'Short-term investments'),
    ('long_term_investments', 'longTermInvestments', 'Long-term investments'),
    ('net_receivables', 'netReceivables', 'Net receivables; distinct from accounts receivable'),
    ('accounts_receivable', 'accountsReceivables', 'Accounts receivable; distinct from net receivables'),
    ('inventory', 'inventory', 'Inventory'),
    ('prepaid_expenses', 'prepaids', 'Prepaid expenses'),
    ('current_assets', 'totalCurrentAssets', 'Total current assets'),
    ('property_plant_equipment_net', 'propertyPlantEquipmentNet', 'Net property, plant and equipment'),
    ('goodwill', 'goodwill', 'Goodwill'),
    ('intangible_assets', 'intangibleAssets', 'Intangible assets excluding goodwill'),
    ('total_assets', 'totalAssets', 'Total assets'),
    ('accounts_payable', 'accountPayables', 'Accounts payable'),
    ('accrued_expenses', 'accruedExpenses', 'Accrued expenses'),
    ('current_deferred_revenue', 'deferredRevenue', 'Current deferred revenue'),
    ('noncurrent_deferred_revenue', 'deferredRevenueNonCurrent', 'Noncurrent deferred revenue'),
    ('current_liabilities', 'totalCurrentLiabilities', 'Total current liabilities'),
    ('total_liabilities', 'totalLiabilities', 'Total liabilities'),
    ('short_term_debt', 'shortTermDebt', 'FMP short-term debt; not a separate current portion of long-term debt'),
    ('long_term_debt', 'longTermDebt', 'FMP long-term debt; categories can overlap with leases'),
    ('lease_obligations', 'capitalLeaseObligations', 'FMP lease obligations; no operating/finance split; debt categories can overlap'),
    ('equity', 'totalStockholdersEquity', 'Book shareholders equity; neither common-only nor equity including noncontrolling interests'),
    ('preferred_stock', 'preferredStock', 'Book preferred stock; not market value'),
    ('noncontrolling_interests', 'minorityInterest', 'Noncontrolling interests'),
)
_CASH_FLOW = (
    ('depreciation_amortization', 'depreciationAndAmortization', 'Combined depreciation and amortization from cash flow only'),
    ('stock_based_compensation', 'stockBasedCompensation', 'Stock-based compensation'),
    ('operating_cash_flow', 'operatingCashFlow', 'Operating cash flow'),
    ('capital_expenditure', 'capitalExpenditure', 'Capital-expenditure cash flow; retain reported sign'),
    ('net_acquisitions', 'acquisitionsNet', 'Net acquisition cash flow; not gross acquisition spending'),
    ('income_taxes_paid', 'incomeTaxesPaid', 'Cash income taxes paid'),
    ('interest_paid', 'interestPaid', 'Cash interest paid'),
    ('net_debt_issuance', 'netDebtIssuance', 'Net debt issuance; no gross borrowing/repayment inference'),
    ('common_dividends_paid', 'commonDividendsPaid', 'Common dividends paid'),
    ('preferred_dividends_paid', 'preferredDividendsPaid', 'Preferred dividends paid'),
    ('common_stock_repurchased', 'commonStockRepurchased', 'Common-share repurchase cash flow'),
    ('common_stock_issuance', 'commonStockIssuance', 'Common-share issuance cash flow'),
)


def _annual(identity, field, description, endpoint):
    shares = field in ('weightedAverageShsOut', 'weightedAverageShsOutDil')
    return dict(id='annual.' + identity, kind='direct', unit='share' if shares else 'USD',
        description=description, source=dict(endpoint=endpoint, field=field),
        conversion='identity', sign='reported; no absolute value or sign inversion',
        sampling='annual-period-weighted-average' if shares else 'selected-annual-fiscal-period',
        counts=dict(minimum=1, maximum=10), contexts=['root', 'at', 'lookback'],
        history=dict(statistics=['mean', 'min', 'max'], consecutive=True, complete=True),
        timing=dict(availability='fiscal-plus-90-strict-before-context', anchor_max_days=800),
        omission='unavailable-with-reason; no zero, newer-report, endpoint or aggregate substitution')


def _build():
    entries = [_annual(*row, endpoint) for endpoint, rows in (
        ('income-statement', _INCOME), ('balance-sheet-statement', _BALANCE),
        ('cash-flow-statement', _CASH_FLOW)) for row in rows]
    for identity, field, description, unit, sampling, endpoint, conversion in (
        ('market.adjusted_price', 'adjClose', 'Dividend-adjusted close; not unadjusted transaction price or replacement market-cap policy',
         'USD/share', 'actual-price-session', 'historical-price-eod/dividend-adjusted', 'identity'),
        ('market.volume', 'volume', 'Trading volume; saved value for the relevant session, not an annual share count',
         'share', 'session-volume', 'historical-price-eod/dividend-adjusted', 'identity'),
        ('treasury.us_3m', 'month3', 'US 3-month Treasury yield',
         'scalar', 'dated-rate-observation', 'treasury-rates', 'provider-percent-divided-by-100'),
        ('treasury.us_10y', 'year10', 'US 10-year Treasury yield',
         'scalar', 'dated-rate-observation', 'treasury-rates', 'provider-percent-divided-by-100')):
        entries.append(dict(id=identity, kind='direct', unit=unit, description=description,
            source=dict(endpoint=endpoint, field=field), conversion=conversion,
            sign='reported; no absolute value or sign inversion', sampling=sampling,
            counts=dict(minimum=1, maximum=1), contexts=['root', 'at', 'lookback'],
            history=dict(statistics=[], consecutive=False, complete=False),
            timing=dict(availability='dated-context-lookup; no annual reporting lag', anchor_max_days=None),
            omission='unavailable-with-reason; no zero or missing-session substitution'))
    for identity, unit, description, policy in (
        ('annual.operating_margin', 'scalar', 'Operating income / positive revenue', 'existing-positive-revenue-operating-margin'),
        ('market.enterprise_value', 'USD', 'Existing dated enterprise value', 'existing-dated-enterprise-value')):
        value = _annual(identity.split('.', 1)[1], None, description, None)
        value.update(id=identity, kind='adapter', unit=unit, source=None, adapter=policy)
        if identity.startswith('market.'):
            value.update(sampling='existing-dated-valuation', counts=dict(minimum=1, maximum=1),
                history=dict(statistics=[], consecutive=False, complete=False),
                timing=dict(availability='existing-dated-valuation-policy', anchor_max_days=800))
        entries.append(value)
    return {value['id']: value for value in entries}


_ALL = _build()
_V1_IDS = ('annual.revenue', 'annual.operating_income', 'annual.operating_margin', 'market.enterprise_value')


def _version(identity):
    if type(identity) is not str or identity not in (V1, V2):
        raise ValueError('Unknown semantic parameter catalog.')
    return identity


def catalog(identity):
    """Return recognized meanings, never current provider/backend capabilities."""
    _version(identity)
    return copy.deepcopy([_ALL[key] for key in (_V1_IDS if identity == V1 else _ALL)])


def parameter(identity, parameter_id):
    """Look up one meaning under its recorded namespace; unknown IDs fail."""
    _version(identity)
    if type(parameter_id) is not str or parameter_id not in _ALL or (identity == V1 and parameter_id not in _V1_IDS):
        raise ValueError('Unknown semantic parameter.')
    return copy.deepcopy(_ALL[parameter_id])


def units(identity):
    """Return only the canonical unit vocabulary admitted by this catalog."""
    _version(identity)
    return copy.deepcopy({key: value for key, value in _UNITS.items() if identity == V2 or key != 'share'})


def unit(identity, name):
    values = units(identity)
    if type(name) is not str or name not in values:
        raise ValueError('Unknown semantic unit.')
    return values[name]


def policy_fingerprint():
    """Bind loaded meaning and detect source changes without financial work."""
    current = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if current != _LOADED:
        raise ValueError('Loaded semantic parameter source changed.')
    return current
