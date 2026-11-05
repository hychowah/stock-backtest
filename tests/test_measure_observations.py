"""Synthetic scope metadata and stored owner lane evidence."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import sqlite3
import unittest
from backtest import measure_observations as bridge
from backtest.inputs import observation_inputs as source


class PreparedMeasureTests(unittest.TestCase):
    def test_scope_digest_and_empty_scope(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript(source.SCHEMA)
        scopes = [dict(mode='latest', pool='cached', context_date='2020-01-02', book=0)]
        metadata = source.finish(db, '2020-01-02', inputs='fixture', scopes=scopes)
        self.assertEqual(source.require(db), metadata)
        root = dict(mode='latest', pool='cached')
        self.assertTrue(bridge.prepared_scope(metadata, root, dict(id='a', root='a', date='2020-01-02')))
        self.assertFalse(bridge.prepared_scope(metadata, root, dict(id='b', root='a', date='2020-01-02')))
        dated = dict(root, owner_scope=dict(kind='dated'))
        prepared = dict(root, owner_scope=dict(kind='prepared', book=0))
        self.assertFalse(bridge.prepared_scope(metadata, dated, dict(id='a', root='a', date='2020-01-02')))
        self.assertTrue(bridge.prepared_scope(metadata, prepared, dict(id='a', root='a', date='2020-01-02')))
        self.assertFalse(bridge.prepared_scope(metadata, prepared, dict(id='b', root='a', date='2020-01-02')))
        db.execute("UPDATE observation_metadata SET value='[]' WHERE key='scopes'")
        with self.assertRaises(ValueError):
            source.require(db)

    def test_projection_rejects_missing_latest_scope(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript(source.SCHEMA)
        metadata = source.finish(db, '2020-01-02', inputs='fixture', scopes=[])
        self.assertEqual({item['pool'] for item in metadata['scopes']}, {'cached','legacy'})
        scopes = [item for item in metadata['scopes'] if item['pool'] == 'cached']
        db.execute("UPDATE observation_metadata SET value=? WHERE key='scopes'", (source.encoded(scopes),))
        with self.assertRaises(ValueError): source.require(db)
        other = sqlite3.connect(':memory:')
        self.addCleanup(other.close)
        other.executescript(source.SCHEMA)
        with self.assertRaises(ValueError):
            source.finish(other, '2020-01-02', inputs='fixture', scopes=[dict(mode='latest',pool='cached',context_date='2019-01-02',book=0)])

    def test_stored_components_and_missing_lanes(self):
        context = dict(reason=None, evidence=dict(snapshot=dict(market_cap=500.),
            metrics=dict(ev_ebitda=[3.0, .33333333333333337]),
            filters=dict(profit_margin=12.5)))
        self.assertEqual(bridge.lane(context, 'ev_ebitda')['value'], 3.)
        self.assertEqual(bridge.lane(context, 'ebitda_yield')['value'], .33333333333333337)
        margin = bridge.lane(context, 'profit_margin')
        self.assertEqual(margin['value'], .125)
        self.assertEqual(margin['evidence']['stored'], 12.5)
        self.assertEqual(bridge.lane(context, 'roe')['reason'], 'LEGACY_MEASURE_UNAVAILABLE')
        self.assertEqual(bridge.lane(dict(reason='PREPARED_MEASURE_CONTEXT_UNAVAILABLE', evidence=None), 'pe')['reason'],
                         'PREPARED_MEASURE_CONTEXT_UNAVAILABLE')


class OwnerExtractionTests(unittest.TestCase):
    def test_snapshot_preserves_predecessor_and_lookup_order(self):
        from datetime import date
        from backtest.financial import books
        def predecessor(statement, entry_day, exit_day, lookup, bankruptcy):
            valuation = books.entry_valuation(statement, entry_day, lookup)
            if valuation is None: return None
            fiscal_px, entry_px, cap, ev, ebitda = valuation
            start = lookup(entry_px[0], 'adjusted', True, 4)
            if start is None or start[0] >= exit_day: return None
            end = lookup(exit_day, 'adjusted', False, 10)
            status = 'Scheduled exit' if exit_day.year > entry_day.year else 'Marked to date'
            if end is None:
                end = lookup(exit_day, 'adjusted', False, 100000)
                if end is None or end[0] < start[0]: return None
                status = 'Last available price'
            if end[0] < start[0]: return None
            ret = -1. if bankruptcy else end[1] / start[1] - 1
            if bankruptcy: status = 'Bankruptcy'
            return [str(statement['fiscal']), str(start[0]), str(end[0]), cap, ev,
                    ebitda, ebitda / ev, ev / ebitda, ret, status]
        fiscal, entry = date(2018, 12, 31), date(2020, 1, 2)
        statement = dict(fiscal=fiscal, market_cap=101., enterprise=153., yield_=.1)
        statement['yield'] = statement.pop('yield_')
        for label, exit_day, missing, bankrupt, zero in (
                ('scheduled', date(2021, 1, 2), None, False, False),
                ('marked', date(2020, 12, 2), None, False, False),
                ('stopped', date(2021, 1, 2), 10, False, False),
                ('bankrupt', date(2021, 1, 2), None, True, False),
                ('no exit', date(2021, 1, 2), 'all_exit', False, True),
                ('zero', date(2021, 1, 2), None, False, True),
                ('no valuation', date(2021, 1, 2), 'valuation', False, False),
                ('no start', date(2021, 1, 2), 'start', False, False)):
            with self.subTest(label=label):
                report = dict(statement, **{'yield': 0. if zero else .1})
                results, histories = [], []
                for fn in (predecessor, books.snapshot):
                    calls = []
                    def lookup(day, column, forward, slack):
                        calls.append((day, column, forward, slack))
                        if missing == 'valuation' and column == 'price': return None
                        if missing == 'start' and column == 'adjusted' and forward: return None
                        if missing == 'all_exit' and column == 'adjusted' and not forward: return None
                        if missing == 10 and column == 'adjusted' and not forward and slack == 10: return None
                        return day, 10. if column == 'price' else 12.
                    try: results.append(('value', fn(report, entry, exit_day, lookup, bankrupt)))
                    except ArithmeticError as exc: results.append(('error', type(exc)))
                    histories.append(calls)
                self.assertEqual(results[0], results[1])
                self.assertEqual(histories[0], histories[1])
        pair = books.ebitda_yield_and_multiple(1., 49.)
        self.assertEqual(pair, (1. / 49., 49. / 1.))
        self.assertNotEqual(pair[1], 1. / pair[0])

    def test_dated_owner_parity_with_no_future_lookups(self):
        from datetime import date
        from unittest.mock import Mock, patch
        from backtest.financial import books, metrics
        day = date(2020, 1, 2)
        anchor = dict(fiscal=date(2018, 12, 31), known=date(2019, 3, 31), market_cap=100., enterprise=150., ebitda=30., **{'yield': .2})
        reports = [dict(fiscal=f'{year}-12-31', ebitda=value) for year, value in ((2016, 10.), (2017, 20.), (2018, 30.))]
        financials = {f'{year}-12-31': dict(revenue=100., operatingIncome=20., netIncome=10., totalStockholdersEquity=50., freeCashFlow=5., totalCurrentAssets=30., totalCurrentLiabilities=10., ebit=12., interestExpense=3., totalDebt=25., epsDiluted=eps)
                      for year, eps in ((2015, 1.), (2016, 2.), (2017, 3.), (2018, 4.))}
        inputs = Mock()
        inputs.entry.return_value = (dict(market_cap=200., enterprise_value=250., ebitda=30.), dict(reason=None))
        inputs.broad_reports.return_value = reports
        inputs.legacy_financial_history.return_value = financials
        inputs.legacy_treasury.return_value = dict(day='2020-01-01', value=2.)
        inputs.lookup.side_effect = lambda symbol, date_, column, forward, slack: (date_, 10. if date_ < day else 15.)
        root = dict(symbol='A')
        context = dict(date=str(day))
        with patch.object(books, 'ebitda_yield_and_multiple', wraps=books.ebitda_yield_and_multiple) as helper:
            owner = bridge.dated(inputs, root, context, anchor, lambda: None, budget=1000000)
        helper.assert_called_once_with(30., 250.)
        obs = dict(fiscal='2018-12-31', market_cap=200., enterprise_value=250., ebitda_yield=30./250., ev_ebitda=250./30.)
        pairs = metrics.evaluate(obs, reports)
        expected = metrics.filter_values(obs, pairs, day, lambda when, column, forward, slack: (when, 10. if when < day else 15.), financials, 2.)
        self.assertEqual(owner['evidence']['metrics'], {key:list(value) for key,value in pairs.items()})
        self.assertEqual(owner['evidence']['filters'], expected)
        self.assertEqual(bridge.lane(owner, 'pe')['value'], 20.)
        self.assertEqual(bridge.lane(owner, 'profit_margin')['value'], .1)
        self.assertEqual(bridge.lane(owner, 'return_1y')['value'], .5)
        self.assertTrue(all(call.args[1] <= day for call in inputs.lookup.call_args_list))
        inputs.entry.return_value[0]['ebitda'] = 0.
        missing = bridge.dated(inputs, root, context, anchor, lambda: None, budget=1000000)
        self.assertEqual(missing['reason'], 'LEGACY_MEASURE_UNAVAILABLE')

    def test_entry_valuation_needs_no_holding_or_exit_prices(self):
        from datetime import date
        from backtest.financial import books
        statement=dict(fiscal=date(2014,6,30),market_cap=100e6,enterprise=150e6,**{'yield':.2})
        calls=[]
        def lookup(day,column,forward,slack):
            calls.append((day,column,forward,slack))
            self.assertEqual(column,'price')
            return day,10. if day==statement['fiscal'] else 20.
        fiscal,entry,cap,ev,ebitda=books.entry_valuation(statement,date(2015,1,2),lookup)
        self.assertEqual((cap,ev,ebitda),(200e6,250e6,30e6))
        self.assertEqual(calls,[(statement['fiscal'],'price',False,7),(date(2015,1,2),'price',True,4)])
        self.assertEqual((fiscal,entry),((statement['fiscal'],10.),(date(2015,1,2),20.)))


class PreparedTransportTests(unittest.TestCase):
    def test_preparation_context_matches_final_stored_lanes(self):
        import json
        import test_observation_inputs as fixtures
        from backtest.inputs import research, sqlite_observations
        from backtest import observations
        fixture = fixtures.ProjectionTests('test_complete_chain_preserves_evidence_dates_and_latest_valuation')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        db = sqlite3.connect(fixture.path)
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        metadata = source.require(db)
        original = sqlite3.connect(fixture.source)
        original.row_factory = sqlite3.Row
        self.addCleanup(original.close)
        for mode, date_ in (('historical','2015-01-02'), ('latest','2015-10-20')):
            for pool in ('legacy','cached'):
                self.assertTrue(any(scope['mode']==mode and scope['pool']==pool and scope['context_date']==date_ for scope in metadata['scopes']))
                record = db.execute('SELECT evidence_json FROM observation_measure_contexts WHERE mode=? AND pool=? AND context_date=? AND symbol=?', (mode,pool,date_,'TEST')).fetchone()
                self.assertIsNotNone(record)
                evidence = json.loads(record[0])
                scope = next(scope for scope in metadata['scopes'] if scope['mode']==mode and scope['pool']==pool and scope['context_date']==date_)
                pairs = {row['metric']:[row['multiple'],row['yield_value']] for row in original.execute('SELECT metric,multiple,yield_value FROM screening_metrics WHERE mode=? AND pool=? AND year=? AND symbol=?', (mode,pool,scope['book'],'TEST'))}
                self.assertEqual(evidence['metrics'], pairs)
                self.assertIn('lookups', evidence['valuation'])
                self.assertIn('treasury_selected', evidence)
                self.assertEqual(bridge.lane(dict(reason=None,evidence=evidence),'ev_ebitda')['value'], pairs['ev_ebitda'][0])

    def test_real_prepared_view_missing_context_and_lane_never_fall_back(self):
        from unittest.mock import patch
        import test_observation_inputs as fixtures
        from backtest.inputs import sqlite_observations, research
        from backtest import observations
        fixture = fixtures.ProjectionTests('test_complete_chain_preserves_evidence_dates_and_latest_valuation')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        research.signature.return_value['historical_through'] = '2015-10-20'
        fixture.prepare()
        db = sqlite3.connect(fixture.path)
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        root = dict(id='r', kind='root', symbol='TEST', pool='cached', mode='historical', date='2015-01-02')
        plan = observations.plan([dict(id='pe', parameter='owner.pe', context='r', count=1)], [root])
        def refresh():
            old = source.require(db)
            db.execute('DELETE FROM observation_metadata')
            return source.finish(db, old['latest_date'], inputs='fixture', scopes=old['scopes'])
        # A real admitted company has a context but no PE lane in the saved fixture.
        with sqlite_observations.prepared_view(db, lambda:None) as view, patch.object(bridge, 'dated', side_effect=AssertionError('fallback')):
            result = observations.observe(plan, view).to_dict()['results'][0]
            self.assertEqual(result['reason'], 'LEGACY_MEASURE_UNAVAILABLE')
        db.execute("DELETE FROM observation_measure_contexts WHERE mode='historical' AND pool='cached' AND context_date='2015-01-02' AND symbol='TEST'")
        refresh()
        # A freshly verified fixture represents a known scope lacking this company.
        with sqlite_observations.prepared_view(db, lambda:None) as view, patch.object(bridge, 'dated', side_effect=AssertionError('fallback')):
            result = observations.observe(plan, view).to_dict()['results'][0]
            self.assertEqual(result['reason'], 'PREPARED_MEASURE_CONTEXT_UNAVAILABLE')

    def test_memoized_dated_context_and_fixed_boundary_validations(self):
        from unittest.mock import patch
        import test_reusable_measures as fixtures
        from backtest import observations
        fixture = fixtures.fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        view = fixture.view()
        fixture.db.executescript('CREATE TABLE financial_inputs(symbol TEXT, fiscal TEXT, values_json TEXT); CREATE TABLE treasury10(day TEXT, yield_percent REAL);')
        roots = fixture.contexts()
        requests = [fixture.request(parameter=name,identity=name.replace('.','_')) for name in ('owner.pe','owner.pb','owner.return_1y')]
        with patch.object(bridge, 'dated', wraps=bridge.dated) as owner, patch.object(view, 'validate', wraps=view.validate) as validate:
            observations.observe(observations.plan(requests, roots), view)
        owner.assert_called_once()
        # Provider entry, admission entry/final, and provider final only.
        self.assertEqual(validate.call_count, 4)

    def test_context_leaf_lifetime_record_bounds_and_cancellation(self):
        import test_observations as fixtures
        fixture = fixtures.ProviderTests('test_catalog_and_example_return_ingredients_without_formula_arithmetic')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        view = fixture.view()
        fixture.db.executescript('CREATE TABLE financial_inputs(symbol TEXT, fiscal TEXT, values_json TEXT); CREATE TABLE treasury10(day TEXT, yield_percent REAL);')
        fixture.db.execute("INSERT INTO financial_inputs VALUES('A','2014-06-30','{\"revenue\":100}')")
        fixture.db.execute("INSERT INTO treasury10 VALUES('2014-12-31',2.0)")
        self.assertEqual(view.legacy_financial_history('A')['2014-06-30']['revenue'],100)
        with self.assertRaises(ValueError): view.legacy_financial_history('A', budget=1)
        calls=[]
        def cancelled():
            calls.append(1)
            raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError,'cancelled'): view.broad_reports('A',cancelled)
        view.max_record_bytes = 4
        with self.assertRaises(ValueError): view.legacy_financial_history('A')
        with self.assertRaises(ValueError): view.legacy_treasury(__import__('datetime').date(2015,1,2))
        view.close()
        for action in (lambda:view.measure_context('historical','cached','2015-01-02','A'), lambda:view.broad_reports('A'), lambda:view.legacy_financial_history('A'), lambda:view.legacy_treasury(__import__('datetime').date(2015,1,2))):
            with self.assertRaisesRegex(ValueError,'closed'): action()

    def test_missing_context_relation_is_operation_error(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript(source.SCHEMA)
        source.finish(db, '2020-01-02', inputs='fixture')
        db.execute('DROP TABLE observation_measure_contexts')
        with self.assertRaises(ValueError): source.require(db)

    def test_delayed_stock_entry_and_selected_treasury_dates(self):
        import json
        import test_observation_inputs as fixtures
        from backtest.inputs import research
        fixture = fixtures.ProjectionTests('test_complete_chain_preserves_evidence_dates_and_latest_valuation')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        price = research.RAW/'px'/'TEST.json'
        payload = json.loads(price.read_text())
        payload['div'][1]['date'] = '2015-01-05'
        price.write_text(json.dumps(payload))
        (research.RAW/'treasury.json').write_text(json.dumps([
            dict(date='2014-12-31', month3=2, year10=3),
            dict(date='2015-01-03', month3=2, year10=9),
            dict(date='2015-10-20', month3=2, year10=4)]))
        fixture.prepare()
        db = sqlite3.connect(fixture.source)
        self.addCleanup(db.close)
        payload = json.loads(db.execute("SELECT evidence_json FROM observation_measure_contexts WHERE mode='historical' AND pool='cached' AND symbol='TEST'").fetchone()[0])
        self.assertEqual(payload['screen_date'], '2015-01-05')
        self.assertEqual(payload['treasury_requested_date'], '2015-01-02')
        self.assertEqual(payload['treasury_selected'], ['2014-12-31',3.])
        self.assertEqual(payload['lookups'][0]['requested_date'], '2015-01-05')
        self.assertEqual(payload['valuation']['lookups'][1]['requested_date'], '2015-01-02')

    def test_leap_day_trailing_and_legacy_treasury_asof(self):
        from datetime import date
        from unittest.mock import Mock
        view = Mock()
        day = date(2020,2,29)
        anchor = dict(fiscal=date(2018,12,31))
        view.entry.return_value = (dict(market_cap=100.,enterprise_value=150.,ebitda=30.),dict(reason=None))
        view.broad_reports.return_value = [dict(fiscal='2018-12-31',ebitda=30.)]
        view.legacy_financial_history.return_value = {}
        view.legacy_treasury.return_value = dict(day='2020-02-27',value=2.)
        view.lookup.side_effect = lambda symbol,when,column,forward,slack:(when,10.)
        owner=bridge.dated(view,dict(symbol='A'),dict(date=str(day)),anchor,lambda:None,budget=100000)
        dates=[x['requested_date'] for x in owner['evidence']['lookups']]
        self.assertEqual(dates,['2020-02-29','2019-02-28','2017-02-28'])
        self.assertEqual(owner['evidence']['treasury'],dict(day='2020-02-27',value=2.))

    def test_owner_history_views_preserve_order_and_checkpoint_inside_scans(self):
        reports = [{'fiscal':'2018-01-01'}, {'fiscal':'2018-12-31'}]
        financials = {'2018-01-01': {'revenue':1}, '2018-12-31': {'revenue':2}}
        ticks=[]
        checked_reports = bridge._CheckedReports(reports, lambda:ticks.append('r'))
        checked_financials = bridge._CheckedFinancials(financials, lambda:ticks.append('f'))
        self.assertEqual(list(checked_reports),reports)
        self.assertEqual(list(checked_financials.items()),list(financials.items()))
        self.assertEqual(checked_financials.get('2018-01-01'), financials['2018-01-01'])
        self.assertEqual(len(checked_financials),len(financials))
        self.assertEqual(ticks,['r','r','f','f'])
        calls=[]
        def cancel():
            calls.append(1)
            if len(calls)==2: raise RuntimeError('cancelled during owner scan')
        with self.assertRaisesRegex(RuntimeError,'owner scan'):
            list(bridge._CheckedReports(reports,cancel))
        calls.clear()
        with self.assertRaisesRegex(RuntimeError,'owner scan'):
            list(bridge._CheckedFinancials(financials,cancel).items())
        calls.clear()
        with self.assertRaisesRegex(RuntimeError,'owner scan'):
            bridge.detached({'a':[1,2]},cancel)

if __name__ == '__main__':
    unittest.main()
