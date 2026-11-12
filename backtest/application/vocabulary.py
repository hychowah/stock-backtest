"""One plain name per quantity. A formula uses the entry's term; a step uses
its linked built-in lane when the term reads that lane. Entries without a term
are steps only.

Every catalog /4 parameter has exactly one entry. A single-parameter named
measure gives its parameter the plain name; a compound measure is its own
entry with its /4 reference as the term. Names are unique ignoring case.
Catalog descriptions, measure names and built-in labels stay as stored.
"""
import copy

from backtest.application import strategy_requests
from backtest.variables import measures, parameters

DISPLAYS = {'scalar': 'percent', 'USD': 'usd_million', 'USD/share': 'usd_per_share', 'share': 'shares'}

# (category, rows); a row is (ID, name, linked built-ins...). An ID is a /4
# parameter, 'measure:' plus a compound measure, or a step-only built-in.
_ROWS = (
    ('Income statement', (
        ('annual.revenue', 'Revenue'),
        ('annual.cost_of_revenue', 'Cost of revenue'),
        ('measure:gross_profit', 'Gross profit'),
        ('annual.selling_general_administrative_expense', 'SG&A expense'),
        ('annual.research_development_expense', 'R&D expense'),
        ('annual.operating_income', 'Operating income'),
        ('annual.ebit', 'EBIT'),
        ('annual.report_ebitda', 'EBITDA'),
        ('annual.interest_income', 'Interest income'),
        ('annual.interest_expense', 'Interest expense'),
        ('annual.pretax_income', 'Pretax income'),
        ('annual.income_tax_expense', 'Income tax expense'),
        ('annual.net_income', 'Net income'),
        ('annual.weighted_average_basic_shares', 'Basic shares'),
        ('annual.weighted_average_diluted_shares', 'Diluted shares'),
        ('annual.basic_eps', 'Basic EPS'),
        ('annual.diluted_eps', 'Diluted EPS'))),
    ('Balance sheet', (
        ('annual.cash_and_equivalents', 'Cash and equivalents'),
        ('annual.short_term_investments', 'Short term investments'),
        ('annual.long_term_investments', 'Long term investments'),
        ('annual.net_receivables', 'Net receivables'),
        ('annual.accounts_receivable', 'Accounts receivable'),
        ('annual.inventory', 'Inventory'),
        ('annual.prepaid_expenses', 'Prepaid expenses'),
        ('annual.current_assets', 'Current assets'),
        ('annual.property_plant_equipment_net', 'Net PP&E'),
        ('annual.goodwill', 'Goodwill'),
        ('annual.intangible_assets', 'Intangible assets'),
        ('annual.total_assets', 'Total assets'),
        ('annual.accounts_payable', 'Accounts payable'),
        ('annual.accrued_expenses', 'Accrued expenses'),
        ('annual.current_deferred_revenue', 'Current deferred revenue'),
        ('annual.noncurrent_deferred_revenue', 'Noncurrent deferred revenue'),
        ('annual.current_liabilities', 'Current liabilities'),
        ('measure:working_capital', 'Working capital'),
        ('annual.total_liabilities', 'Total liabilities'),
        ('annual.short_term_debt', 'Short term debt'),
        ('annual.long_term_debt', 'Long term debt'),
        ('annual.lease_obligations', 'Lease obligations'),
        ('annual.total_debt', 'Total debt'),
        ('measure:net_debt', 'Net debt'),
        ('annual.equity', 'Shareholders equity'),
        ('measure:tangible_book_equity', 'Tangible book equity'),
        ('annual.preferred_stock', 'Preferred stock'),
        ('annual.noncontrolling_interests', 'Minority interest'))),
    ('Cash flow', (
        ('annual.operating_cash_flow', 'Operating cash flow'),
        ('annual.capital_expenditure', 'CapEx'),
        ('measure:operating_cash_flow_plus_capex', 'Operating cash flow plus CapEx'),
        ('annual.free_cash_flow', 'Reported free cash flow'),
        ('annual.depreciation_amortization', 'Depreciation and amortization'),
        ('annual.stock_based_compensation', 'Stock based compensation'),
        ('annual.net_acquisitions', 'Net acquisitions'),
        ('annual.income_taxes_paid', 'Income taxes paid'),
        ('annual.interest_paid', 'Interest paid'),
        ('annual.net_debt_issuance', 'Net debt issuance'),
        ('annual.common_dividends_paid', 'Common dividends paid'),
        ('annual.preferred_dividends_paid', 'Preferred dividends paid'),
        ('annual.common_stock_repurchased', 'Share buybacks'),
        ('annual.common_stock_issuance', 'Share issuance'))),
    ('Market', (
        ('market.adjusted_price', 'Share price'),
        ('market.volume', 'Trading volume'),
        ('owner.market_cap', 'Market cap', 'filter:market_cap'),
        ('market.enterprise_value', 'Enterprise value', 'filter:enterprise_value'),
        ('treasury.us_3m', 'Treasury 3 month yield'),
        ('treasury.us_10y', 'Treasury 10 year yield'))),
    ('Valuation', (
        ('owner.pe', 'P/E', 'filter:pe'),
        ('owner.pb', 'P/B', 'filter:pb'),
        ('measure:price_sales', 'Price/sales'),
        ('owner.price_fcf', 'Price/FCF', 'filter:price_fcf'),
        ('owner.fcf_yield', 'FCF yield', 'filter:fcf_yield'),
        ('owner.peg', 'PEG', 'filter:peg'),
        ('owner.ev_ebitda', 'EV/EBITDA', 'metric:ev_ebitda:multiple', 'filter:ev_ebitda'),
        ('owner.ev_ebitda_3y', 'EV/3-year average EBITDA', 'metric:ev_ebitda_3y:multiple', 'filter:ev_ebitda_3y'),
        ('owner.ebitda_yield', 'EBITDA yield', 'metric:ev_ebitda:yield', 'filter:ebitda_yield'),
        ('owner.operating_yield_spread_3y', 'Operating yield spread', 'filter:operating_yield_spread_3y'),
        ('filter:ps', 'P/S'),
        ('metric:ev_ebitda_3y:yield', '3-year average EBITDA yield'),
        ('filter:pe_avg_3y', 'P/E 3-year average'),
        ('filter:pe_avg_5y', 'P/E 5-year average'),
        ('filter:ps_avg_3y', 'P/S 3-year average'),
        ('filter:ps_avg_5y', 'P/S 5-year average'),
        ('filter:pb_avg_3y', 'P/B 3-year average'),
        ('filter:pb_avg_5y', 'P/B 5-year average'),
        ('filter:pe_vs_avg_3y', 'P/E vs 3-year average'),
        ('filter:pe_vs_avg_5y', 'P/E vs 5-year average'),
        ('filter:ps_vs_avg_3y', 'P/S vs 3-year average'),
        ('filter:ps_vs_avg_5y', 'P/S vs 5-year average'),
        ('filter:pb_vs_avg_3y', 'P/B vs 3-year average'),
        ('filter:pb_vs_avg_5y', 'P/B vs 5-year average'))),
    ('Margins and returns', (
        ('annual.operating_margin', 'Operating margin'),
        ('measure:gross_margin', 'Gross margin'),
        ('owner.profit_margin', 'Net margin', 'filter:profit_margin'),
        ('owner.roe', 'ROE', 'filter:roe'),
        ('owner.return_1y', 'One year return', 'filter:return_1y'),
        ('owner.return_3y', 'Three year return', 'filter:return_3y'))),
    ('Debt and liquidity', (
        ('owner.current_ratio', 'Current ratio', 'filter:current_ratio'),
        ('owner.interest_coverage', 'Interest coverage', 'filter:interest_coverage'),
        ('owner.debt_equity', 'Debt/equity', 'filter:debt_equity'),
        ('measure:debt_assets', 'Debt/assets'))),
)


def _build():
    catalog = {item['id']: item for item in parameters.catalog(parameters.V4)}
    named = {item['id']: item for item in measures.catalog(parameters.V4)}
    measured = {}  # parameter ID -> the named measure of that one parameter
    for item in named.values():
        expression = measures.exact(**item['root'])['definition']['expression']
        if expression['op'] == 'parameter':
            measured[expression['id']] = item
    builtins = {item['id']: item for item in strategy_requests.builtin_catalog()}
    result = []
    for category, rows in _ROWS:
        for identity, name, *links in rows:
            if identity.startswith('measure:'):
                measure = named[identity.split(':', 1)[1]]
                term, unit = dict(op='ref', **measure['root']), measure['unit']
            elif identity in builtins:
                term, unit, links = None, builtins[identity]['unit'], [identity]
            else:
                measure, unit = measured.get(identity), catalog[identity]['unit']
                term = dict(op='parameter', id=identity)
            # A ratio keeps its measure's display; amounts default to $ million.
            display = (builtins[identity]['display'] if term is None else
                       measure['display'] if measure and unit == 'scalar' else DISPLAYS[unit])
            result.append(dict(id=identity, name=name, category=category, unit=unit,
                               display=display, term=term, builtins=list(links)))
    names = {item['term'].get('id') or item['term']['variable_id']: item['name'] for item in result if item['term']}
    names.update({measure['root']['variable_id']: names[identity] for identity, measure in measured.items()})
    return result, names


_ENTRIES, _NAMES = _build()


def entries():
    """Every entry: {id, name, category, unit, display, term or None, builtins}."""
    return copy.deepcopy(_ENTRIES)


def names():
    """The plain name of each term, by parameter ID or measure variable ID.

    A named measure of one parameter has that parameter's name.
    """
    return dict(_NAMES)
