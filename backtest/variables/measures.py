"""Immutable reusable definitions, detached from capture and execution.

Bundles contain only exact referenced definitions and their reachable closure.
Restoring a capture does not read this registry. Version 3 positive division
requires a positive denominator; annual history belongs only to named adapters.
The existing program limits apply to each requested closure.
"""
import copy

from backtest.variables import definitions


def _parameter(name):
    return dict(op='parameter', id=name)


def _binary(op, left, right):
    return dict(op=op, left=left, right=right)


def _ref(name):
    entry = _ENTRIES[name]
    return dict(op='ref', variable_id=entry['variable_id'], revision=entry['revision'])


_ENTRIES = {}
_DESCRIPTORS = {}


def _add(key, name, expression, unit, display, missing, history=None):
    definition = dict(format='variable-definition', version=3,
        parameter_catalog='financial-parameters/3', temporal_policy=definitions.TEMPORAL_POLICY,
        expression=expression, output=dict(unit=unit, display=display))
    identity = dict(variable_id='measure:' + key, revision=definitions.revision(definition))
    _ENTRIES[key] = dict(**identity, definition=definition)
    _DESCRIPTORS[key] = dict(id=key, name=name, description=name, root=identity,
        unit=unit, display=display, missing=missing, history=history)


_USD = ('USD', 'usd')
_RATIO = ('scalar', 'multiple')
_FRACTION = ('scalar', 'percent')
_EPS = ('USD/share', 'usd_per_share')

def _direct(key, name, parameter, output, missing, history=False):
    _add(key, name, _parameter(parameter), *output, missing,
         parameter if history else None)


_OWNER_MISSING = {
    'market_cap': 'Existing report and entry valuation required.',
    'profit_margin': 'Net income and positive revenue required.',
    'pe': 'Market cap and positive net income required.',
    'pb': 'Market cap and positive equity required.',
    'fcf_yield': 'Stored FCF and positive market cap required.',
    'price_fcf': 'Market cap and positive stored FCF required.',
    'peg': 'P/E and four positive EPS values with positive percentage growth required.',
    'roe': 'Net income and two positive annual equity endpoints required.',
    'current_ratio': 'Current assets and positive current liabilities required.',
    'interest_coverage': 'Reported EBIT and positive interest expense required.',
    'debt_equity': 'Reported total debt and positive equity required.',
    'return_1y': 'Existing one-year trailing price endpoints required.',
    'return_3y': 'Existing three-year trailing price endpoints required.',
    'ev_ebitda': 'Existing owner metric pair required.',
    'ev_ebitda_3y': 'Complete positive three-year owner average required.',
    'ebitda_yield': 'Existing owner metric pair required.',
    'operating_yield_spread_3y': 'Three annual operating margins, current sales, EV and Treasury required.',
}


def _owner(key, name, lane, output=_RATIO):
    _direct(key, name, 'owner.' + lane, output, _OWNER_MISSING[lane])


_add('gross_profit', 'Gross profit', _binary('sub', _parameter('annual.revenue'), _parameter('annual.cost_of_revenue')), *_USD, 'Both reported fields required.')
_add('gross_margin', 'Gross margin', _binary('positive_div', _ref('gross_profit'), _parameter('annual.revenue')), *_FRACTION, 'Gross profit and positive revenue required.')
_direct('operating_margin', 'Operating margin', 'annual.operating_margin', _FRACTION, 'Positive revenue and operating income required.', True)
_owner('net_margin', 'Net margin', 'profit_margin', _FRACTION)
_direct('ebit', 'EBIT', 'annual.ebit', _USD, 'Reported EBIT required.', True)
_direct('ebitda', 'Existing-policy EBITDA', 'annual.report_ebitda', _USD, 'Accepted report EBITDA required.', True)
_direct('free_cash_flow', 'Stored free cash flow', 'annual.free_cash_flow', _USD, 'Reported free cash flow required.', True)
_add('operating_cash_flow_plus_capex', 'Operating cash flow plus signed CapEx', _binary('add', _parameter('annual.operating_cash_flow'), _parameter('annual.capital_expenditure')), *_USD, 'Both reported fields required.')
_direct('total_debt', 'Total debt', 'annual.total_debt', _USD, 'Reported total debt required.', True)
_add('net_debt', 'Cash-only net debt', _binary('sub', _ref('total_debt'), _parameter('annual.cash_and_equivalents')), *_USD, 'Total debt and cash required.')
_add('working_capital', 'Working capital', _binary('sub', _parameter('annual.current_assets'), _parameter('annual.current_liabilities')), *_USD, 'Both reported fields required.')
_add('tangible_book_equity', 'Tangible book equity', _binary('sub', _binary('sub', _parameter('annual.equity'), _parameter('annual.goodwill')), _parameter('annual.intangible_assets')), *_USD, 'Equity, goodwill and intangible assets required.')
_owner('market_cap', 'Existing-policy market cap', 'market_cap', _USD)
_direct('enterprise_value', 'Existing-policy enterprise value', 'market.enterprise_value', _USD, 'Existing valuation requirements apply.')
_direct('basic_eps', 'Reported basic EPS', 'annual.basic_eps', _EPS, 'Reported basic EPS required.', True)
_direct('diluted_eps', 'Reported diluted EPS', 'annual.diluted_eps', _EPS, 'Reported diluted EPS required.', True)
_add('price_sales', 'Price/sales', _binary('positive_div', _ref('market_cap'), _parameter('annual.revenue')), *_RATIO, 'Market cap and positive revenue required.')
_add('debt_assets', 'Total debt/total assets', _binary('positive_div', _ref('total_debt'), _parameter('annual.total_assets')), *_RATIO, 'Total debt and positive total assets required.')
for _key, _name, _lane, _output in (
    ('pe', 'P/E', 'pe', _RATIO), ('pb', 'P/B', 'pb', _RATIO),
    ('fcf_yield', 'FCF yield', 'fcf_yield', _FRACTION), ('price_fcf', 'Price/FCF', 'price_fcf', _RATIO),
    ('peg', 'PEG', 'peg', _RATIO), ('roe', 'ROE', 'roe', _FRACTION),
    ('current_ratio', 'Current ratio', 'current_ratio', _RATIO),
    ('interest_coverage', 'Interest coverage', 'interest_coverage', _RATIO),
    ('debt_equity', 'Debt/equity', 'debt_equity', _RATIO),
    ('return_1y', 'One-year trailing return', 'return_1y', _FRACTION),
    ('return_3y', 'Three-year trailing return', 'return_3y', _FRACTION),
    ('ev_ebitda', 'EV/EBITDA', 'ev_ebitda', _RATIO),
    ('ev_ebitda_3y', 'EV/three-year average EBITDA', 'ev_ebitda_3y', _RATIO),
    ('ebitda_yield', 'EBITDA yield', 'ebitda_yield', _FRACTION),
    ('operating_yield_spread_3y', 'Three-year operating-yield spread', 'operating_yield_spread_3y', _FRACTION)):
    _owner(_key, _name, _lane, _output)


def catalog():
    """Return detached identities and meanings; this grants no admission."""
    return copy.deepcopy(list(_DESCRIPTORS.values()))


def bundle(ids):
    """Return an ordinary checked bundle with only the requested closure."""
    if type(ids) is not list or not ids or any(type(key) is not str or key not in _ENTRIES for key in ids):
        raise ValueError('An ordered nonempty list of known measures is required.')
    entries, seen = [], set()
    identities = {entry['variable_id']: key for key, entry in _ENTRIES.items()}
    def visit(key):
        if key in seen:
            return
        seen.add(key)
        def walk(node):
            if node['op'] == 'ref':
                visit(identities[node['variable_id']])
            for field in ('left', 'right', 'arg'):
                if field in node:
                    walk(node[field])
        walk(_ENTRIES[key]['definition']['expression'])
        entries.append(copy.deepcopy(_ENTRIES[key]))
    for key in ids:
        visit(key)
    result = dict(format='variable-bundle', version=1, definitions=entries,
                  roots=[copy.deepcopy(_DESCRIPTORS[key]['root']) for key in ids])
    definitions.validate(result)
    return result
