"""Column formula evaluation over typed prepared facts: arithmetic, observation rules and explanations.

Each case writes a private research file and an in-memory daily cache that
attaches it, borrows a fact_view.View of it, admits the roots (books.Screen.decide)
and runs columns.Formulas. Every explained result must equal the values-only
result.
"""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from datetime import date, timedelta
import json
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch

from backtest.application import strategy_requests
from backtest.financial import books, rules
from backtest.inputs import book_store, daily, fact_view, facts, research
from backtest.variables import columns, definitions as d, parameters
from prepared_inputs_fixture import PreparedInputs
import book_store_fixture as store
import test_strategy_requests as requests
import test_variable_definitions as language

c, b = language.constant, language.binary
DISPLAY = {'scalar': 'number', 'USD': 'usd', 'USD/share': 'usd_per_share', 'share': 'shares'}
SOURCE = dict(endpoint='income-statement', sha256='b'*64, disposition='valid')


def state(value, reason=None):
    return dict(value=value, valid=reason is None, reason=reason)


def annual(revenue=100., income=10.):
    return dict(revenue=state(revenue), operatingIncome=state(income))


def parameter(name='annual.revenue'):
    return dict(op='parameter', id=name)


def statistic(stat='mean', count=3, name='annual.operating_margin'):
    return dict(op='annual', stat=stat, count=count, parameter=name)


def program(expression=None, unit='scalar', *, version=1, catalog=parameters.V1):
    definition = language.definition(expression, unit, DISPLAY[unit])
    definition.update(version=version, parameter_catalog=catalog)
    return d.validate(language.bundle(language.entry(definition)))


def bits(value):
    return struct.pack('>d', value).hex()


class Company:
    """Company A in a private database that one view reads.

    Reports are statements of 150e6 market cap, 180e6 EV and 0.3 EBITDA yield,
    known 90 days after fiscal. Valuation prices are 10 on every calendar day
    around the reports and roots unless fill is False; prices overrides days
    (None removes one). Change attributes before view(); each view reads a new database.
    """

    def __init__(self):
        self.root_date, self.latest_date, self.through = '2015-01-02', '2015-01-05', None
        self.reports = ['2012-06-30', '2013-06-30', '2014-06-30']
        self.annual = {f'{year}-06-30': annual(100., income) for year, income in ((2012, -10.), (2013, 0.), (2014, 20.))}
        self.listed = True
        self.fill, self.prices, self.population, self.stale = True, {}, 0, False
        self.spy, self.stock, self.treasury = [], {}, {}
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = self.daily = None

    def build(self):
        """Write the research file and open the daily cache that attaches it; return the daily connection."""
        self.close()
        path = Path(self.folder.name) / 'research.sqlite'
        path.unlink(missing_ok=True)
        db = self.db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=OFF')  # A private fixture file needs no durability.
        db.executescript(research.SCHEMA + facts.SCHEMA)
        db.execute('INSERT INTO companies VALUES(?,?,?,?,?)', ('A', 'A', 'NYSE', 'Technology', int(self.listed)))
        for fiscal in self.reports:
            known = str(date.fromisoformat(fiscal) + rules.LAG)
            db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)', ('A', fiscal, known, 150e6, 180e6, 54e6, .3))
        prices = {}
        if self.fill:
            dates = [date.fromisoformat(day) for day in (*self.reports, self.root_date, self.latest_date)]
            day, last = min(dates) - timedelta(days=7), max(dates) + timedelta(days=7)
            while day <= last:
                prices[str(day)] = 10.
                day += timedelta(days=1)
        prices.update(self.prices)
        # One value rule: valuation and market inputs read the same stock days.
        stock = {day: dict(adjClose=state(price), volume=state(None, 'MISSING_INPUT'))
                 for day, price in prices.items() if price is not None}
        stock.update(self.stock)
        facts.store_annual(db, 'A', dict(sources={'income-statement': SOURCE}, annual={'income-statement': self.annual}))
        facts.store_stock(db, 'A', dict(source=dict(endpoint=facts.STOCK, sha256='c'*64, disposition='valid'), dated=stock))
        for index in range(self.population):
            # Higher yield than A; Z000-Z009 have no cached prices.
            symbol = f'Z{index:03d}'
            db.execute('INSERT INTO companies VALUES(?,?,?,?,?)', (symbol, symbol, 'NYSE', 'Energy', 1))
            db.execute('INSERT INTO statements VALUES(?,?,?,?,?,?,?)',
                       (symbol, '2014-06-30', '2014-09-28', 150e6, 180e6, 162e6, .9))
            if index >= 10:
                facts.store_stock(db, symbol, dict(source=dict(endpoint=facts.STOCK, sha256='f'*64, disposition='valid'),
                    dated={day: dict(adjClose=state(10.), volume=state(None, 'MISSING_INPUT')) for day in ('2014-06-30', '2015-01-02')}))
        # Admission needs saved SPY sessions at the root and latest dates.
        sessions = sorted({*self.spy, self.root_date, self.latest_date})
        facts.store_market(db, {
            facts.TREASURY: dict(source=dict(endpoint=facts.TREASURY, sha256='d'*64, disposition='valid'),
                                 dated=self.treasury),
            facts.CALENDAR: dict(source=dict(endpoint=facts.CALENDAR, sha256='e'*64, disposition='valid'),
                                 dated={day: dict(adjClose=state(100.)) for day in sessions})})
        daily_db = self.daily = sqlite3.connect(':memory:', uri=True)
        daily_db.row_factory = sqlite3.Row
        daily_db.executescript(daily.SCHEMA)
        store.record(db, daily_db, self.latest_date)
        db.commit()
        daily.attach(daily_db, path)
        # The latest book has no stored rows: owner lanes at a latest root are unavailable.
        for pool in ('legacy', 'cached'):
            book_store.store(daily_db, dict(entry=self.latest_date, exit=None, pool=pool, spy=None, candidates=0,
                                            rows=[], metrics=[], filters=[]))
        daily_db.commit()
        return daily_db

    def view(self):
        def freshness():
            if self.stale:
                raise ValueError('Fixture inputs are stale.')
        daily_db = self.build()
        return fact_view.View(daily_db, freshness, lambda: None)

    def close(self):
        for db in (self.daily, self.db):
            if db is not None:
                db.close()
        self.db = self.daily = None


class ColumnTests(unittest.TestCase):
    def setUp(self):
        self.company = Company()
        self.addCleanup(self.company.folder.cleanup);self.addCleanup(self.company.close)

    def root(self, **changes):
        return dict(dict(symbol='A', pool='legacy', mode='historical', date=self.company.root_date), **changes)

    def latest(self, **changes):
        return self.root(mode='latest', date=self.company.latest_date, **changes)

    def explain(self, checked, roots=None, *, view=None):
        """Return the explanation block; its results must equal the values-only evaluation."""
        roots = columns.require_roots(roots or [self.root()])
        formulas = columns.Formulas(d.require_program(checked))
        formulas.require_contexts(roots)
        if view is None:
            with self.company.view() as view:
                return self.explain(checked, roots, view=view)
        decisions = view.admit(roots)
        values = formulas.evaluate(roots, view, lambda: None, decisions=decisions)
        block = formulas.explain(roots, view, lambda: None, decisions=decisions)
        for item in block['results']:
            value, valid, reason = values[item['request']][item['variable_id'], item['revision']]
            self.assertEqual((repr(value), valid, reason), (repr(item['value']), item['valid'], item['reason']))
        return block

    def result(self, expression, unit='scalar', roots=None, **settings):
        return self.explain(program(expression, unit, **settings), roots)['results'][0]

    def observation(self, expression, unit='scalar', roots=None, index=0, **settings):
        return self.explain(program(expression, unit, **settings), roots)['observations']['results'][index]

    def error(self, code, function, *args):
        with self.assertRaises(d.FormulaError) as caught:
            function(*args)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    # Arithmetic.

    def test_tree_order_binary64_division_and_nonfinite_results(self):
        neg = lambda value: dict(op='neg', arg=value)
        cases = [(b('add', b('add', c('1e16'), c('-1e16')), c('1')), 1., None, None),
                 (b('add', c('1e16'), b('add', c('-1e16'), c('1'))), 0., None, None),
                 (b('div', c('-12'), c('-3')), 4., None, 'signed nonzero'),
                 (b('div', c('12'), c('-3')), -4., None, 'signed nonzero'),
                 (b('div', c('0'), c('-3')), -0., None, 'signed nonzero'),
                 (b('div', c('12'), c('0')), None, 'ZERO_DENOMINATOR', 'signed nonzero'),
                 (b('div', c('12'), neg(c('0'))), None, 'ZERO_DENOMINATOR', 'signed nonzero'),
                 (b('positive_div', c('-12'), c('3')), -4., None, 'positive'),
                 (b('positive_div', c('12'), c('-3')), None, 'NONPOSITIVE_DENOMINATOR', 'positive'),
                 (b('positive_div', c('12'), neg(c('0'))), None, 'NONPOSITIVE_DENOMINATOR', 'positive'),
                 (b('mul', c('1e308'), c('2')), None, 'NONFINITE_RESULT', None),
                 (b('add', c('1e308'), c('1e308')), None, 'NONFINITE_RESULT', None),
                 (b('div', c('1e308'), c('5e-324')), None, 'NONFINITE_RESULT', 'signed nonzero'),
                 (b('mul', c('5e-324'), c('0.1')), 0., None, None),
                 (neg(c('0')), -0., None, None)]
        for expression, value, reason, rule in cases:
            with self.subTest(expression=expression):
                block = self.explain(program(expression, version=3, catalog=parameters.V3))
                result = block['results'][0]
                self.assertEqual((result['valid'], result['reason']), (reason is None, reason))
                if value is None:
                    self.assertIsNone(result['value'])
                else:
                    self.assertEqual(bits(result['value']), bits(value))
                self.assertEqual(block['operations'][-1].get('denominator_rule'), rule)
        self.assertEqual(len(self.explain(program(cases[0][0]))['operations']), 5)

    def test_first_unavailable_operand_wins_even_against_zero(self):
        self.company.annual['2014-06-30']['revenue'] = state(None, 'CONFLICTING_INPUT')
        for left, right in ((c('0'), parameter()), (parameter(), c('0'))):
            block = self.explain(program(b('mul', left, right), 'USD'))
            self.assertEqual(block['results'][0]['reason'], 'CONFLICTING_INPUT')
            operation = block['operations'][-1]
            self.assertEqual(len(operation['operands']), 2)
            self.assertIn(0., operation['inputs']); self.assertIn(None, operation['inputs'])
        self.company.annual['2014-06-30']['operatingIncome'] = state(None, 'NON_USD_INPUT')
        block = self.explain(program(b('add', parameter(), parameter('annual.operating_income')), 'USD'))
        self.assertEqual(block['results'][0]['reason'], 'CONFLICTING_INPUT')
        self.assertEqual([item['reason'] for item in block['observations']['results']], ['CONFLICTING_INPUT', 'NON_USD_INPUT'])
        self.assertEqual([item['reason'] for item in block['operations'][:2]], ['CONFLICTING_INPUT', 'NON_USD_INPUT'])

    def test_references_share_tasks_and_keep_repeated_output_slots(self):
        base = language.entry(language.definition(parameter(), 'USD', 'usd'), 'saved:base')
        twice = language.entry(language.definition(b('add', language.reference(base), language.reference(base)),
                                                    'USD', 'usd'), 'draft:twice')
        checked = d.validate(language.bundle(base, twice, roots=[language.root(twice), language.root(base),
                                                                 language.root(twice)]))
        block = self.explain(checked, [self.root()] * 2)
        self.assertEqual([item['value'] for item in block['results']], [200., 100., 200.] * 2)
        self.assertEqual([item['request'] for item in block['results']], [0, 0, 0, 1, 1, 1])
        self.assertEqual([len(block['observations'][key]) for key in ('roots', 'contexts', 'results')], [1, 1, 1])
        self.assertEqual(len(block['operations']), 4)

    # Root admission.

    def test_constants_still_need_root_admission(self):
        block = self.explain(program(c('12')))
        self.assertEqual(block['results'][0]['value'], 12.)
        self.assertEqual(block['observations']['results'], [])
        self.assertTrue(block['observations']['roots'][0]['admitted'])
        self.company.listed = False
        with self.company.view() as view, patch.object(view, 'company', side_effect=AssertionError('Annual read')):
            for expression, unit in ((c('12'), 'scalar'), (parameter(), 'USD')):
                block = self.explain(program(expression, unit), [self.latest()], view=view)
                self.assertEqual((block['results'][0]['value'], block['results'][0]['reason']), (None, 'ROOT_NOT_ADMITTED'))
                self.assertEqual(block['observations']['roots'][0]['reason'], 'NOT_LISTED')
        block = self.explain(program(parameter(), 'USD'), [self.latest()])
        self.assertEqual(block['observations']['results'][0]['reason'], 'ROOT_NOT_ADMITTED')
        self.assertEqual(self.result(c('1'), roots=[self.latest(symbol='B')])['reason'], 'ROOT_NOT_ADMITTED')

    def test_root_shapes_and_owner_scopes_are_checked_and_kept_distinct(self):
        root = self.latest()
        roots = [dict(root, owner_scope=dict(kind='prepared', book=0)), dict(root, owner_scope=dict(kind='dated')), root]
        block = self.explain(program(c('12')), roots)
        self.assertEqual(block['requests'], roots)
        admitted = block['observations']['roots']
        self.assertEqual([item.get('owner_scope') for item in admitted], [roots[0]['owner_scope'], roots[1]['owner_scope'], None])
        self.assertNotIn('owner_scope', admitted[2])
        self.assertEqual(block['observations']['contexts'][0]['owner_scope'], roots[0]['owner_scope'])
        for roots in ([], {}, [dict(root, extra=1)], [dict(root, symbol=[])], [dict(root, mode='quarterly')],
                      [dict(root, pool='all')], [dict(root, owner_scope=dict(kind='prepared', book=True))]):
            self.error('INVALID_SHAPE', columns.require_roots, roots)
        self.error('INVALID_DATE', columns.require_roots, [dict(root, date='20150102')])

    def test_admission_refuses_roots_outside_saved_sessions_and_changed_facts(self):
        for changed in (dict(date='2015-01-03'), dict(date='1995-01-02'), dict(mode='latest')):
            with self.subTest(changed=changed), self.company.view() as view, self.assertRaises(ValueError):
                view.admit([self.root(**changed)])
        with self.company.view() as view:
            with self.assertRaisesRegex(ValueError, 'not a saved SPY session'):
                view.admit([self.root(date='2015-01-03')])
            self.assertTrue(view.admit([self.latest()])[0]['admitted'])
            # An unknown company is a denial, at a latest and at a historical root.
            self.assertEqual([item['reason'] for item in view.admit([self.latest(symbol='B'), self.root(symbol='B')])],
                             ['UNKNOWN_COMPANY', 'UNKNOWN_COMPANY'])
            self.company.db.execute("DELETE FROM metadata WHERE key='identity'"); self.company.db.commit()
            with self.assertRaisesRegex(ValueError, 'missing|stale'):
                view.admit([self.latest()])

    def test_cancellation_staleness_and_closed_views_fail_the_operation(self):
        formulas, roots = columns.Formulas(d.require_program(program(parameter(), 'USD'))), [self.root()]
        def cancel():
            raise RuntimeError('cancelled')
        with self.company.view() as view:
            decisions = view.admit(roots)
            for run in (formulas.evaluate, formulas.explain):
                with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                    run(roots, view, cancel, decisions=decisions)
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                view.admit(roots, cancel)
            self.company.stale = True
            with self.assertRaisesRegex(ValueError, 'stale'):
                view.admit(roots)
        with self.assertRaisesRegex(ValueError, 'closed'):
            view.admit(roots)

    def test_complete_population_legacy_buffer_and_uncached_names(self):
        self.company.population = 260
        roots = [self.root(symbol=symbol, pool=pool) for symbol, pool in
                 (('Z249', 'legacy'), ('Z250', 'legacy'), ('Z005', 'legacy'), ('Z250', 'cached'))]
        with self.company.view() as view:
            block = self.explain(program(c('13')), roots, view=view)
            alone = self.explain(program(parameter('market.enterprise_value'), 'USD'), [roots[1]], view=view)
            ev = self.explain(program(parameter('market.enterprise_value'), 'USD'), [roots[-1]], view=view)
            book_facts = facts.BookFacts(view.db)
            selected, ranks = books.candidates(book_facts.reports(), date(2015, 1, 2))
            expected = books.admit(selected['legacy']['Z249'], date(2015, 1, 2),
                lambda day, forward, slack: book_facts.price('Z249', day, forward, slack), books.ENTRY_SLACK)[1]
        admitted = block['observations']['roots']
        self.assertEqual([item['valid'] for item in block['results']], [True, False, False, True])
        self.assertEqual([item['reason'] for item in admitted], [None, 'OUTSIDE_LEGACY_BUFFER', 'MISSING_CACHED_PRICES', None])
        self.assertEqual(admitted[0]['candidate_rank'], 250)
        self.assertEqual(admitted[0]['candidate_rank'], ranks['Z249'])
        self.assertEqual(admitted[0]['valuation']['enterprise_value'], expected[3])
        self.assertEqual(block['observations']['results'], [])
        # A request for only the low-ranked name cannot promote it.
        self.assertEqual((alone['observations']['roots'][0]['reason'], alone['results'][0]['reason']),
                         ('OUTSIDE_LEGACY_BUFFER', 'ROOT_NOT_ADMITTED'))
        self.assertEqual(ev['results'][0]['value'], 180e6)

    # Annual statistics.

    def test_mean_is_oldest_first_and_not_a_ratio_of_pooled_amounts(self):
        for year, revenue, income in ((2012, 100., 10.), (2013, 200., 40.), (2014, 300., 90.)):
            self.company.annual[f'{year}-06-30'] = annual(revenue, income)
        block = self.explain(program(b('div', b('mul', parameter(), statistic()), parameter('market.enterprise_value'))))
        mean = ((.1 + .2) + .3) / 3
        self.assertEqual(block['results'][0]['value'], (300. * mean) / 180e6)
        self.assertNotEqual(mean, (10. + 40. + 90.) / (100. + 200. + 300.))
        self.assertEqual(next(item for item in block['operations'] if item['operation'] == 'annual')['inputs'], [.1, .2, .3])

    def test_mean_fold_order_and_extrema_keep_the_oldest_signed_zero(self):
        for year, income in ((2012, 1e16), (2013, -1e16), (2014, 1.)):
            self.company.annual[f'{year}-06-30'] = annual(1., income)
        self.assertEqual(self.result(statistic())['value'], 1. / 3)
        for year, income in ((2012, 2 ** 53), (2013, 1), (2014, -(2 ** 53))):
            self.company.annual[f'{year}-06-30'] = annual(1., income)
        self.assertEqual(self.result(statistic(name='annual.operating_income'), 'USD')['value'], 0.)
        for year in (2012, 2013, 2014):
            self.company.annual[f'{year}-06-30'] = annual(1., -0. if year == 2012 else 0.)
        for stat in ('min', 'max'):
            self.assertEqual(bits(self.result(statistic(stat))['value']), bits(-0.))
        self.assertEqual(bits(self.result(statistic('mean', 1))['value']), bits(0.))
        self.company.annual['2014-06-30'] = annual(1., -0.)
        self.assertEqual(bits(self.result(statistic('mean', 1))['value']), bits(-0.))

    def test_every_annual_member_is_required_and_nonfinite_mean_is_unavailable(self):
        for stat, expected in (('min', -.1), ('max', .2)):
            self.assertEqual(self.result(statistic(stat))['value'], expected)
        self.company.annual.pop('2013-06-30')
        for stat in ('mean', 'min', 'max'):
            block = self.explain(program(statistic(stat)))
            self.assertEqual(block['results'][0]['reason'], 'MISSING_FISCAL_YEAR')
            self.assertEqual(len(block['observations']['results'][0]['members']), 3)
        for year in (2012, 2013, 2014):
            self.company.annual[f'{year}-06-30'] = annual(1., 1e308)
        self.assertEqual(self.result(statistic())['reason'], 'NONFINITE_RESULT')

    def growth(self, stat, values, count=3, wrap=None):
        for year, value in zip(range(2015 - len(values), 2015), values):
            self.company.annual[f'{year}-06-30'] = annual(value, 1.)
        expression = statistic(stat, count, 'annual.revenue')
        return self.explain(program(wrap(expression) if wrap else expression, version=2))

    def test_growth_and_cagr_endpoints_and_missing_precedence(self):
        for stat, values, expected in (('growth', [100., 150., 400.], 3.), ('cagr', [100., 150., 400.], 1.),
                                       ('growth', [100., 50., -50.], -1.5), ('cagr', [400., -10., 100.], -.5)):
            block = self.growth(stat, values)
            self.assertEqual((block['results'][0]['value'], block['results'][0]['unit']), (expected, 'scalar'))
            self.assertEqual(block['operations'][0]['inputs'], values)
            self.assertEqual(len(block['observations']['results'][0]['members']), 3)
        for stat, values, reason in (('growth', [0., 1., 2.], 'NONPOSITIVE_DENOMINATOR'),
                                     ('cagr', [-1., 1., -2.], 'NONPOSITIVE_DENOMINATOR'),
                                     ('cagr', [1., 1., 0.], 'NONPOSITIVE_ENDPOINT'),
                                     ('growth', [1e-308, 1., 1e308], 'NONFINITE_RESULT')):
            self.assertEqual(self.growth(stat, values)['results'][0]['reason'], reason)
        self.company.annual.pop('2013-06-30')
        self.company.annual['2012-06-30'] = annual(0., 1.)
        block = self.explain(program(statistic('growth', 3, 'annual.revenue'), version=2))
        self.assertEqual(block['results'][0]['reason'], 'MISSING_FISCAL_YEAR')
        self.assertEqual(len(block['observations']['results'][0]['members']), 3)

    def test_growth_history_lengths_and_earlier_contexts(self):
        values = [float(2 ** (year - 2005)) for year in range(2005, 2015)]
        for count in (2, 10):
            for stat, expected in (('growth', 2 ** (count - 1) - 1), ('cagr', 1.)):
                block = self.growth(stat, values, count)
                self.assertEqual(block['results'][0]['value'], expected)
                self.assertEqual(len(block['operations'][0]['inputs']), count)
        for context in (dict(op='at', date='2014-01-02'), dict(op='lookback', months=12)):
            block = self.growth('growth', values, 2, lambda expression: dict(context, arg=expression))
            self.assertEqual(block['results'][0]['value'], 1.)
            self.assertEqual(block['observations']['results'][0]['anchor'], '2013-06-30')
            self.assertEqual(block['operations'][0]['inputs'], [128., 256.])

    def test_growth_definitions_need_version_two_counts_and_scalar_output(self):
        def make(stat='growth', count=3, version=2, catalog=parameters.V1):
            definition = language.definition(statistic(stat, count, 'annual.revenue'))
            definition.update(version=version, parameter_catalog=catalog)
            return definition
        for definition in (make(version=1), make(count=1), make(count=11), make(version=4)):
            with self.assertRaises(d.FormulaError):
                d.validate(language.bundle(language.entry(definition)))
        for catalog in (parameters.V1, parameters.V2):
            for count in (2, 10):
                checked = d.validate(language.bundle(language.entry(make(count=count, catalog=catalog))))
                self.assertEqual(d.require_program(checked), checked.to_dict())
        wrong = make(); wrong['output'] = dict(unit='USD', display='usd')
        with self.assertRaises(d.FormulaError):
            d.validate(language.bundle(language.entry(wrong)))

    def test_mixed_definition_versions_evaluate(self):
        old = language.entry(language.definition(c('2')), 'old')
        newer = language.definition(language.reference(old)); newer['version'] = 2
        new = language.entry(newer, 'new')
        for roots in ([language.root(old)], [language.root(new)]):
            checked = d.validate(language.bundle(old, new, roots=roots))
            self.assertEqual(d.require_program(checked), checked.to_dict())
            self.assertEqual(self.explain(checked)['results'][0]['value'], 2.)
        definition = language.definition(c('2')); definition['version'] = 2
        entry = language.entry(definition, 'version2')
        capture = strategy_requests.capture_strategy(requests.intent(requests.formula(entry)), submitted=[entry]).to_dict()
        self.assertEqual(strategy_requests.check_options(dict(strategy=capture, engine='original')), capture)

    # Annual observation rules.

    def test_strict_ninety_day_availability_reselects_at_an_earlier_context(self):
        self.company.root_date, self.company.reports = '2024-04-02', ['2023-12-31']
        self.company.annual = {'2023-12-31': annual()}
        expression = b('add', dict(op='at', date='2024-03-30', arg=parameter()),
                       dict(op='at', date='2024-03-31', arg=parameter()))
        equal, after = self.explain(program(expression, 'USD'))['observations']['results']
        self.assertEqual((equal['reason'], equal['members']), ('NO_ELIGIBLE_REPORT', []))
        self.assertEqual((after['valid'], after['anchor']), (True, '2023-12-31'))

    def test_anchor_ages_800_and_801_and_stale_reports(self):
        fiscal = date(2019, 6, 30)
        self.company.reports = [str(fiscal)]
        self.company.annual = {f'{year}-06-30': annual() for year in range(2010, 2020)}
        for age in (800, 801):
            with self.subTest(age=age):
                self.company.root_date = str(fiscal + timedelta(days=age))
                observed = self.observation(statistic('mean', 10, 'annual.revenue'), 'USD')
                if age == 800:
                    self.assertTrue(observed['valid'])
                    self.assertEqual(len(observed['members']), 10)
                else:
                    self.assertEqual(observed['reason'], 'ROOT_NOT_ADMITTED')
        self.company.root_date = '2022-01-03'
        self.company.reports.append('2021-06-30')
        observed = self.observation(dict(op='at', date=str(fiscal + timedelta(days=801)), arg=parameter()), 'USD')
        self.assertEqual(observed['reason'], 'STALE_REPORT')

    def test_fiscal_spine_buckets_and_exact_dates(self):
        margins = statistic('mean', 3)
        self.company.annual['2014-01-01'] = annual(999., 999.)
        self.company.annual['2014-06-30']['revenue'] = state(None, 'CONFLICTING_INPUT')
        observed = self.observation(parameter(), 'USD')
        # The exact anchor's missing field is not replaced by another report.
        self.assertEqual((observed['anchor'], observed['reason'], observed['members'][0]['value']),
                         ('2014-06-30', 'CONFLICTING_INPUT', None))
        self.company.annual = {f'{year}-06-30': annual(100., income) for year, income in ((2012, -10.), (2013, 0.), (2014, 20.))}
        self.company.annual['2013-12-31'] = dict(revenue=state(None, 'MISSING_INPUT'), operatingIncome=state(99.))
        member = self.observation(margins)['members'][1]
        # The newest eligible income date of a year is selected even when incomplete.
        self.assertEqual((member['fiscal_date'], member['reason']), ('2013-12-31', 'MISSING_INPUT'))
        del self.company.annual['2013-12-31'], self.company.annual['2013-06-30']
        observed = self.observation(margins)
        self.assertFalse(observed['valid'])
        self.assertEqual([item['fiscal_year'] for item in observed['members']], [2012, 2013, 2014])
        self.assertEqual((observed['members'][1]['reason'], observed['members'][1]['fiscal_date']), ('MISSING_FISCAL_YEAR', None))
        self.company.annual['2013-03-31'] = annual(100., 7.)
        # Calendar-year buckets, not fiscal spacing.
        self.assertEqual([item['value'] for item in self.observation(margins)['members']], [-.1, .07, .2])

    def test_signed_and_zero_denominators_and_nonfinite_margins(self):
        for revenue, income in ((-100., -5.), (0., 0.), (100., 0.)):
            self.company.annual['2014-06-30'] = annual(revenue, income)
            self.assertEqual(self.observation(parameter(), 'USD')['members'][0]['value'], revenue)
            margin = self.observation(parameter('annual.operating_margin'))
            self.assertEqual(margin['reason'], 'NONPOSITIVE_DENOMINATOR' if revenue <= 0 else None)
            if revenue > 0:
                self.assertEqual(margin['members'][0]['value'], 0.)
        self.company.annual['2014-06-30'] = annual(-100., -20.)
        # The provider's positive margin denominator is not generic division.
        self.assertEqual(self.result(b('div', parameter('annual.operating_income'), parameter()))['value'], .2)
        self.company.annual['2014-06-30'] = annual(1e-300, 1e300)
        margin = self.observation(parameter('annual.operating_margin'))
        self.assertEqual((margin['reason'], margin['members'][0]['value']), ('NONFINITE_RESULT', None))

    # Dated contexts.

    def test_month_end_and_leap_lookbacks_keep_the_root_admission(self):
        saved = self.company.reports, self.company.annual
        self.company.root_date, self.company.reports = '2024-05-31', ['2021-06-30', '2022-06-30', '2023-06-30']
        self.company.annual = {day: annual() for day in self.company.reports}
        block = self.explain(program(dict(op='lookback', months=3, arg=dict(op='lookback', months=12, arg=parameter())), 'USD'))
        self.assertEqual([item['date'] for item in block['observations']['contexts']], ['2024-05-31', '2024-02-29', '2023-02-28'])
        self.assertEqual(len(block['observations']['roots']), 1)
        observed = block['observations']['results'][0]
        self.assertEqual((observed['anchor'], observed['members'][0]['value']), ('2022-06-30', 100.))
        self.assertEqual(observed['candidate_rank'], block['observations']['roots'][0]['candidate_rank'])
        self.assertEqual(observed['candidate_rank'], 1)
        block = self.explain(program(dict(op='lookback', months=3, arg=c())))
        self.assertEqual([item['date'] for item in block['observations']['contexts']], ['2024-05-31', '2024-02-29'])
        self.company.reports, self.company.annual = saved
        self.company.root_date = '2015-03-31'
        base = language.entry(language.definition(parameter(), 'USD', 'usd'), 'saved:revenue')
        nested = dict(op='lookback', months=1, arg=dict(op='lookback', months=1, arg=language.reference(base)))
        outer = language.entry(language.definition(nested, 'USD', 'usd'), 'draft:history')
        block = self.explain(d.validate(language.bundle(base, outer)))
        self.assertEqual([item['date'] for item in block['observations']['contexts']], ['2015-03-31', '2015-02-28', '2015-01-28'])
        self.assertEqual(block['results'][0]['value'], 100.)
        self.assertEqual({item['candidate_rank'] for item in block['observations']['results']}, {1})
        observed = self.observation(dict(op='at', date='2013-12-31', arg=parameter('annual.operating_income')), 'USD')
        self.assertEqual((observed['members'][0]['value'], observed['anchor']), (0., '2013-06-30'))

    def test_future_dates_calendar_floor_and_depth_fail_before_inputs(self):
        roots = [self.root(date='2024-05-31')]
        nested = dict(op='lookback', months=3, arg=dict(op='at', date='2024-03-01', arg=c()))
        error = self.error('FUTURE_DATE', columns.Formulas(d.require_program(program(nested))).require_contexts, roots)
        self.assertEqual(error.path, '/definitions/0/definition/expression/arg/date')
        # A later root cannot make an earlier root's future date valid.
        later = columns.Formulas(d.require_program(program(dict(op='at', date='2024-05-31', arg=c()))))
        self.error('FUTURE_DATE', later.require_contexts, [self.root(date='2024-05-30')] + roots)
        self.error('INVALID_DATE', columns.Formulas(d.require_program(program(dict(op='lookback', months=1, arg=c())))).require_contexts,
                   [self.root(date='0001-01-31')])
        future = columns.Formulas(d.require_program(program(dict(op='at', date='2015-01-03', arg=c()))))
        with self.company.view() as view:
            decisions = view.admit([self.root()])
            self.error('FUTURE_DATE', lambda: future.evaluate([self.root()], view, lambda: None, decisions=decisions))
        def depth(count):
            expression = c()
            for _ in range(count):
                expression = dict(op='lookback', months=1, arg=expression)
            return expression
        # The language bounds expression depth at 32, so 31 nested contexts is the deepest program.
        self.assertEqual(len(self.explain(program(depth(31)))['observations']['contexts']), 32)
        with self.assertRaises(d.FormulaError):
            program(depth(32))

    # Enterprise value.

    def test_latest_root_values_at_its_session_and_earlier_contexts_reconstruct(self):
        # The latest root is valued at its exact session (books.Screen.decide); a
        # derived context reconstructs with the same entry valuation rule.
        self.company.prices = {self.company.latest_date: 12.}
        ev = parameter('market.enterprise_value')
        for day, difference, earlier_value in ((self.company.root_date, 30e6, 180e6), (self.company.latest_date, 0., 210e6)):
            with self.subTest(day=day):
                block = self.explain(program(b('sub', ev, dict(op='at', date=day, arg=ev)), 'USD'), [self.latest()])
                self.assertEqual(block['results'][0]['value'], difference)
                current, earlier = block['observations']['results']
                self.assertEqual((current['members'][0]['value'], earlier['members'][0]['value']), (210e6, earlier_value))
                self.assertEqual(earlier['candidate_rank'], 1)
                self.assertEqual(earlier['members'][0]['evidence']['lookup_policy'], 'existing-entry-valuation')
                self.assertEqual(len(block['observations']['contexts']), 2)

    def test_ev_uses_entry_valuation_lookups_and_missing_prices_deny(self):
        self.company.fill, self.company.prices = False, {'2000-01-03': 10.}
        block = self.explain(program(parameter('market.enterprise_value'), 'USD'))
        self.assertEqual(block['observations']['roots'][0]['reason'], 'MISSING_PRICE')
        self.assertEqual(block['results'][0]['reason'], 'ROOT_NOT_ADMITTED')
        self.company.prices = {'2014-06-28': 3., '2015-01-05': 7.}
        statement = dict(fiscal=date(2014, 6, 30), market_cap=150e6, enterprise=180e6, **{'yield': .3})
        expected = books.admit(statement, date(2015, 1, 2), lambda day, forward, slack:
                               (date(2015, 1, 5), 7.) if forward else (date(2014, 6, 28), 3.), books.ENTRY_SLACK)[1]
        member = self.observation(parameter('market.enterprise_value'), 'USD')['members'][0]
        self.assertEqual(member['value'], expected[3])
        lookups = member['evidence']['lookups']
        self.assertEqual([item['observation'] for item in lookups], [['2014-06-28', 3.], ['2015-01-05', 7.]])
        self.assertEqual([item['slack'] for item in lookups], [7, 4])
        self.company.fill = True
        self.company.prices = {f'2014-10-0{day}': None for day in range(2, 7)}
        observed = self.observation(dict(op='at', date='2014-10-02', arg=parameter('market.enterprise_value')), 'USD')
        self.assertEqual((observed['reason'], observed['candidate_rank']), ('MISSING_PRICE', 1))

    # Dated market inputs.

    def test_price_volume_and_treasury_lookups(self):
        self.company.spy = ['2014-12-10', '2014-12-31', '2015-01-02']
        # The 2014-12-10 session has no saved price for A.
        self.company.prices = {'2014-12-10': None}
        self.company.stock = {'2014-12-31': dict(adjClose=state(9.5), volume=state(1000.)),
                              '2015-01-02': dict(adjClose=state(10.5), volume=state(None, 'INVALID_INPUT'))}
        self.company.treasury = {'2014-12-01': dict(month3=state(2.5), year10=state(-.25)),
                                 '2015-01-02': dict(month3=state(None, 'MISSING_INPUT'), year10=state(3.))}
        cases = [('market.adjusted_price', None, 10.5, None, '2015-01-02'),
                 ('market.volume', None, None, 'INVALID_INPUT', '2015-01-02'),
                 ('market.adjusted_price', '2015-01-01', 9.5, None, '2014-12-31'),
                 ('market.volume', '2015-01-01', 1000., None, '2014-12-31'),
                 ('market.adjusted_price', '2014-12-17', None, 'MISSING_INPUT', '2014-12-10'),
                 ('market.adjusted_price', '2014-12-18', None, 'MISSING_SESSION', None),
                 ('treasury.us_3m', None, None, 'MISSING_INPUT', '2015-01-02'),
                 ('treasury.us_10y', None, 3. / 100, None, '2015-01-02'),
                 ('treasury.us_3m', '2015-01-01', 2.5 / 100, None, '2014-12-01'),
                 ('treasury.us_10y', '2015-01-01', -.25 / 100, None, '2014-12-01'),
                 ('treasury.us_3m', '2014-11-30', None, 'MISSING_INPUT', None)]
        for name, day, value, reason, observed in cases:
            with self.subTest(name=name, day=day):
                expression = parameter(name) if day is None else dict(op='at', date=day, arg=parameter(name))
                unit = parameters.parameter(parameters.V3, name)['unit']
                block = self.explain(program(expression, unit, version=3, catalog=parameters.V3))
                self.assertEqual(block['results'][0]['value'], value)
                self.assertEqual(block['results'][0]['reason'], reason)
                member = block['observations']['results'][0]['members'][0]
                self.assertEqual((member['observation_date'], member['fiscal_date']), (observed, None))
                treasury = name.startswith('treasury.')
                self.assertEqual(member['evidence']['source'], dict(
                    endpoint=facts.TREASURY if treasury else facts.STOCK, sha256=('d' if treasury else 'c') * 64,
                    disposition='valid'))
                self.assertEqual(member['evidence']['conversion'],
                                 'provider-percent-divided-by-100' if treasury else 'identity')

    # Explanations.

    def test_explanation_block_references_dates_sources_and_detaches(self):
        checked = program(b('div', parameter(), parameter('market.enterprise_value')))
        with self.company.view() as view:
            block = self.explain(checked, view=view)
            identity, content = view.identity, view.projection['content']
            margins = self.explain(program(statistic('mean', 3)), view=view)
        self.company.close()
        self.assertEqual((block['format'], block['observations']['format']), ('formula-evaluation', 'parameter-observations'))
        self.assertEqual((block['identity']['evaluator'], block['identity']['generation'], block['identity']['projection']),
                         ('columns', identity, content))
        self.assertEqual(block['identity']['policy'], columns.policy_fingerprint())
        nodes = {item['id'] for item in block['program']['nodes']}
        tasks = {item['id'] for item in block['operations']}
        contexts = {item['id'] for item in block['observations']['contexts']}
        observed = {item['id'] for item in block['observations']['results']}
        for operation in block['operations']:
            self.assertIn(operation['node'], nodes); self.assertIn(operation['context'], contexts)
            self.assertTrue(set(operation['operands']) <= tasks)
            if 'observation' in operation:
                self.assertIn(operation['observation'], observed)
        for output in block['results']:
            self.assertIn(output['evidence']['operation'], tasks)
            self.assertIn(output['evidence']['admission'], contexts)
        revenue, ev = block['observations']['results']
        self.assertEqual(revenue['anchor_report'], dict(fiscal='2014-06-30', known='2014-09-28'))
        member = revenue['members'][0]
        self.assertEqual((member['fiscal_date'], member['fiscal_year'], member['evidence']['known_date']),
                         ('2014-06-30', 2014, '2014-09-28'))
        self.assertEqual(member['evidence']['source'], SOURCE)
        self.assertEqual(member['evidence']['fields'], dict(revenue=state(100.)))
        self.assertEqual((ev['members'][0]['fiscal_date'], ev['members'][0]['fiscal_year']), ('2014-06-30', 2014))
        members = margins['observations']['results'][0]['members']
        self.assertEqual([(item['fiscal_date'], item['fiscal_year'], item['evidence']['known_date'], item['reason'])
                          for item in members],
                         [(f'{year}-06-30', year, str(date(year, 6, 30) + rules.LAG), None) for year in (2012, 2013, 2014)])
        # The block holds no reference to the closed view or database.
        self.assertEqual(json.loads(json.dumps(block, allow_nan=False)), block)

    def test_real_preparation_chain_explains_without_future_returns(self):
        ratio = language.entry(language.definition(b('div', parameter(), parameter('market.enterprise_value'))), 'draft:ratio')
        margin = language.entry(language.definition(statistic()), 'draft:margin')
        constant = language.entry(language.definition(c('12')), 'draft:constant')
        checked = d.validate(language.bundle(ratio, margin, constant,
                                             roots=[language.root(item) for item in (ratio, margin, constant)]))
        roots = [dict(symbol='TEST', pool='legacy', mode=mode, date=day)
                 for mode, day in (('historical', '2015-01-02'), ('latest', '2015-10-20'))]
        with PreparedInputs() as prepared, prepared.view() as view:
            block = self.explain(checked, roots, view=view)
            self.assertEqual(block['identity']['generation'], view.identity)
        results = block['results']
        self.assertEqual([item['valid'] for item in results], [True, False, True] * 2)
        self.assertEqual((results[1]['reason'], results[4]['reason']), ('MISSING_INPUT', 'MISSING_INPUT'))
        self.assertEqual(results[3]['value'], 100e6 / 270e6)
        self.assertEqual([item['value'] for item in results[2::3]], [12., 12.])
        self.assertTrue(all(item['admitted'] for item in block['observations']['roots']))
        for observed in block['observations']['results']:
            self.assertEqual(observed['candidate_rank'], 1)
            self.assertIsNotNone(observed['anchor_report'])
        text = json.dumps(block, allow_nan=False)
        self.assertEqual(json.loads(text), block)
        self.assertIn('income-statement', text)
        self.assertNotIn('return', text)

    def test_catalog_covers_direct_inputs_and_adapters(self):
        items = {item['id']: item for item in columns.catalog()}
        direct = {item['id'] for item in parameters.catalog(parameters.V3) if item['kind'] == 'direct'}
        self.assertTrue(direct | {'annual.operating_margin', 'market.enterprise_value', 'annual.report_ebitda'} <= set(items))
        for key, item in items.items():
            self.assertEqual(item['counts']['maximum'], 10 if key.startswith('annual.') else 1)
            self.assertEqual(item['contexts'], ['root', 'at', 'lookback'])


if __name__ == '__main__':
    unittest.main()
