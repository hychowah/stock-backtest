"""Research preparation reuses unchanged company units and equals a full rebuild."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextlib import ExitStack, closing, redirect_stdout
import io
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backtest import screening
from backtest.engines.reference import legacy
from backtest.financial import rules
from backtest.inputs import market
from backtest.inputs import research as r
from backtest.runtime import cache_access, diagnostics

PRICES = {  # newest first, as SeriesAsset saves them
    'AAA': [('2015-10-20', 16), ('2015-06-30', 15), ('2015-01-02', 14), ('2014-06-30', 13), ('2014-01-02', 12), ('2013-06-28', 10)],
    'BBB': [('2015-10-20', 26), ('2015-06-30', 24), ('2015-01-02', 25), ('2014-06-30', 21), ('2014-01-02', 22), ('2013-06-28', 20)],
    # Unlisted and stopped before the final sale: kept at its last price.
    'CCC': [('2015-06-30', 36), ('2015-01-02', 35), ('2014-06-30', 34), ('2014-01-02', 33), ('2013-06-28', 30)],
}


class PreparedReuseTests(unittest.TestCase):
    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        root = Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.raw = raw = root / 'raw'
        (raw / 'px').mkdir(parents=True)
        results = root / 'results'; results.mkdir()
        (results / 'summary-exits.txt').write_text('Through 2015-10-20\n')
        self.path = root / 'data' / 'research.sqlite'
        self.write('universe.json', [dict(symbol=s, name=s + ' Corp', exchange='NYSE', sector='Industrials', listed=s != 'CCC')
                                     for s in PRICES])
        (raw / 'metrics.jsonl').write_text(''.join(json.dumps(dict(symbol=s, rows=[
            dict(date=f'{year}-06-30', marketCap=200e6, enterpriseValue=260e6, evToEBITDA=multiple, reportedCurrency='USD')
            for year in (2014, 2013)])) + '\n' for s, multiple in zip(PRICES, (5, 6, 7))))
        self.write('spy-div.json', [dict(date=d, adjClose=v) for d, v in [('2015-10-20', 115), ('2015-01-02', 110), ('2014-01-02', 100)]])
        self.write('treasury.json', [dict(date='2015-01-02', month3=2, year10=3.5), dict(date='2014-01-02', month3=1, year10=3)])
        for symbol, rows in PRICES.items():
            self.write(f'px/{symbol}.json', dict(div=[dict(date=d, adjClose=v) for d, v in rows]))
        for owner, key, value in [(r, 'ROOT', root), (r, 'RAW', raw), (r, 'RESULTS', results), (market, 'RAW', raw),
                                  (legacy, 'RAW', raw), (r.revalue, 'RAW', raw), (legacy, 'FIRST_YEAR', 2014),
                                  (rules, 'FIRST_YEAR', 2014), (legacy, 'LAST_YEAR', 2015), (rules, 'LAST_YEAR', 2015)]:
            self.context.enter_context(patch.object(owner, key, value))
        self.context.enter_context(patch.object(cache_access, 'workspace',
            cache_access.WorkspaceAccess(root / 'data' / 'website-data-0.lock')))
        # Real stat freshness over the private raw folder, like the product.
        self.context.enter_context(patch.object(r, 'signature', side_effect=lambda: {
            p.relative_to(raw).as_posix(): [p.stat().st_size, p.stat().st_mtime_ns] for p in sorted(raw.rglob('*.json'))}))
        self.context.enter_context(patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected download')))
        self.context.enter_context(redirect_stdout(io.StringIO()))

    def write(self, name, value):
        path = self.raw / name
        stamp = path.stat().st_mtime_ns if path.exists() else None
        path.write_text(json.dumps(value))
        if stamp is not None:  # A same-size rewrite must still be a new file version.
            os.utime(path, ns=(stamp + 10**9, stamp + 10**9))

    def edit(self, name, change):
        value = json.loads((self.raw / name).read_text()); change(value); self.write(name, value)

    def prepare(self, force=False, *, detail=False):
        """Return (independent engine runs, price files parsed by preparation).

        detail adds the companies whose dated evidence was resolved in full,
        those resolved only for new days and those resolved for source evidence.
        """
        state = dict(runs=0, inside=False, parsed=set(), full=set(), shifted=set(), source=set())
        calculate, read_text, stock = r.revalue.calculate, Path.read_text, r.dated_observation_inputs.stock
        def reference(through):
            state.update(runs=state['runs'] + 1, inside=True)
            try:
                return calculate(through)
            finally:
                state['inside'] = False
        def read(path, *args, **kwargs):
            content = read_text(path, *args, **kwargs)
            if path.parent == self.raw / 'px' and not state['inside']:
                state['parsed'].add(path.stem)
            return content
        def resolve(raw, symbol, ledger, checkpoint, *, days=None):
            if (raw / 'px' / f'{symbol}.json').exists():
                state['full' if days is None else 'source' if days == () else 'shifted'].add(symbol)
            return stock(raw, symbol, ledger, checkpoint, days=days)
        with patch.object(r.revalue, 'calculate', side_effect=reference), patch.object(Path, 'read_text', read), \
                patch.object(r.dated_observation_inputs, 'stock', side_effect=resolve):
            r.prepare(self.path, force=force)
        result = state['runs'], sorted(state['parsed'])
        return result + tuple(sorted(state[key]) for key in ('full', 'shifted', 'source')) if detail else result

    def dump(self):
        with closing(sqlite3.connect(self.path)) as db:
            tables = db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            return {name: db.execute(f'SELECT * FROM {name}' if 'WITHOUT ROWID' in sql
                                     else f'SELECT rowid,* FROM {name} ORDER BY rowid').fetchall()
                    for name, sql in tables}

    def assert_full_rebuild_equal(self):
        incremental = self.dump()
        self.assertEqual(self.prepare(force=True)[0], 1)
        self.assertEqual(self.dump(), incremental)

    def append_session(self, day, symbols=('AAA', 'BBB')):
        self.edit('spy-div.json', lambda rows: rows.insert(0, dict(date=day, adjClose=120)))
        self.edit('treasury.json', lambda rows: rows.insert(0, dict(date=day, month3=3, year10=4)))
        for symbol in symbols:
            self.edit(f'px/{symbol}.json', lambda value: value['div'].insert(0, dict(date=day, adjClose=30)))

    def test_daily_append_reuses_history_skips_reference_and_equals_full_rebuild(self):
        self.assertEqual(self.prepare(), (1, ['AAA', 'BBB', 'CCC']))
        with closing(r.connect(self.path)) as db:
            before = [dict(row) for row in screening.historical(db, first=2014, last=2015, pool='cached')]
        self.assertEqual(len(before), 6)
        self.append_session('2015-12-01')
        # The unlisted company's unchanged file is not parsed or resolved; listed
        # files are parsed for latest roots. The verified baseline is reused.
        self.assertEqual(self.prepare(detail=True), (0, ['AAA', 'BBB'], [], ['AAA', 'BBB'], []))
        with closing(r.connect(self.path, full_prices=True)) as db:
            self.assertEqual([dict(row) for row in screening.historical(db, first=2014, last=2015, pool='cached')], before)
            self.assertEqual({row['price_date'] for row in screening.latest(db, pool='cached')}, {'2015-12-01'})
        self.assert_full_rebuild_equal()

    def test_preparation_logs_phases_reuse_and_verification(self):
        folder = self.path.parent.parent / 'logs'
        self.addCleanup(diagnostics.close); diagnostics.configure(folder)
        self.prepare()
        self.append_session('2015-12-01'); self.prepare()
        self.prepare()
        full, incremental, current = [record for record in diagnostics.records(folder) if record['event'] == 'prepare.research']
        self.assertEqual({key: full[key] for key in ('outcome', 'verification', 'companies', 'companies_rebuilt', 'companies_reused')},
                         dict(outcome='prepared', verification='independent', companies=3, companies_rebuilt=3, companies_reused=0))
        self.assertLessEqual({'inputs', 'companies', 'observations', 'metrics', 'measure_contexts', 'observation_finish',
                              'commit', 'verification', 'publication'}, full['stages'].keys())
        self.assertGreater(full['verified_holdings'], 0)
        self.assertEqual((incremental['verification'], incremental['companies_rebuilt'], incremental['companies_reused']), ('reused', 0, 3))
        self.assertEqual(current['outcome'], 'current')

    def test_prepended_rows_resolve_only_their_days(self):
        self.prepare()
        # Two days in a row: shifted evidence is shifted again.
        for day in ('2015-12-01', '2015-12-02'):
            self.append_session(day)
            self.assertEqual(self.prepare(detail=True), (0, ['AAA', 'BBB'], [], ['AAA', 'BBB'], []))
            self.assert_full_rebuild_equal()
        # A second variant of a saved day recalculates that whole day. A row
        # without a usable date touches no day, but counts as history, so the
        # reference engine runs.
        self.edit('px/AAA.json', lambda value: value['div'].insert(0, dict(date='2015-12-02', adjClose=31)))
        self.edit('px/BBB.json', lambda value: value['div'].insert(0, dict(date='not a day', adjClose=1)))
        self.assertEqual(self.prepare(detail=True), (1, ['AAA', 'BBB'], [], ['AAA', 'BBB'], []))
        self.assert_full_rebuild_equal()
        # A row inserted between saved rows is not a prepend: resolve in full.
        self.edit('px/AAA.json', lambda value: value['div'].insert(3, dict(date='2015-11-30', adjClose=29)))
        self.assertEqual(self.prepare(detail=True)[2], ['AAA'])
        self.assert_full_rebuild_equal()

    def test_moved_evidence_equals_fresh_encoding_or_is_refused(self):
        dated = r.dated_observation_inputs
        path = self.raw / 'px' / 'AAA.json'
        before = dated.resolve(path, dated.STOCK, {}, stock=True)['dated']
        def prepend_two(value):
            for day in ('2016-01-01', '2016-01-02'):
                value['div'].insert(0, dict(date=day, adjClose=9))
        self.edit('px/AAA.json', prepend_two)
        after = dated.resolve(path, dated.STOCK, {}, stock=True)['dated']
        encoded = r.observation_inputs.encoded
        for day, states in before.items():
            self.assertEqual(dated.shifted(encoded(states), 2), encoded(after[day]))
        # A retained-row layout without the expected next key is never moved.
        self.assertIsNone(dated.shifted('{"rows":[{"index":0,"provider":"x","reported_currency":null}]}', 1))
        self.assertEqual(dated.shifted('{"value":1}', 1), '{"value":1}')

    def test_unmovable_evidence_resolves_the_file_in_full(self):
        self.prepare()
        self.append_session('2015-12-01')
        with patch.object(r.dated_observation_inputs, 'shifted', return_value=None):
            self.assertEqual(self.prepare(detail=True), (0, ['AAA', 'BBB'], ['AAA', 'BBB'], [], []))
        self.assert_full_rebuild_equal()

    def test_same_bytes_with_new_receipt_resolve_only_source_evidence(self):
        # A checked download window with no new rows rewrites equal bytes and
        # extends the coverage receipt, as SeriesAsset.publish does.
        path = self.raw / 'px' / 'CCC.json'
        digest = r.hashlib.sha256(path.read_bytes()).hexdigest()
        self.write('download-coverage.json', {'px/CCC.json': dict(sha256=digest, windows=[['2013-01-01', '2015-10-20']])})
        self.prepare()
        self.write('px/CCC.json', json.loads(path.read_text()))
        self.assertEqual(r.hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.write('download-coverage.json', {'px/CCC.json': dict(sha256=digest, windows=[['2013-01-01', '2015-12-01']])})
        self.assertEqual(self.prepare(detail=True), (0, ['AAA', 'BBB'], [], [], ['CCC']))
        with closing(sqlite3.connect(self.path)) as db:
            source = json.loads(db.execute("SELECT evidence_json FROM observation_sources WHERE symbol='CCC' AND endpoint=?",
                                           (r.dated_observation_inputs.STOCK,)).fetchone()[0])
        self.assertEqual(source['receipt']['windows'], [['2013-01-01', '2015-12-01']])
        self.assert_full_rebuild_equal()

    def test_changed_history_recalculates_that_company_and_runs_reference(self):
        self.prepare()
        self.edit('px/AAA.json', lambda value: value['div'][1].update(adjClose=15.5))
        self.assertEqual(self.prepare(), (1, ['AAA', 'BBB']))
        self.assert_full_rebuild_equal()

    def test_rows_through_the_cutoff_count_as_history(self):
        self.prepare()
        # The last entry is long before Through, so the horizon is Through itself.
        self.append_session('2015-10-21')
        self.assertEqual(self.prepare(), (0, ['AAA', 'BBB']))
        self.assert_full_rebuild_equal()
        self.edit('px/AAA.json', lambda value: value['div'].insert(2, dict(date='2015-10-19', adjClose=17)))
        self.assertEqual(self.prepare(), (1, ['AAA', 'BBB']))
        self.assert_full_rebuild_equal()
        # A shared row on or before Through changes the reuse scope for everyone.
        self.edit('spy-div.json', lambda rows: rows.insert(2, dict(date='2015-10-19', adjClose=116)))
        self.assertEqual(self.prepare(), (1, ['AAA', 'BBB', 'CCC']))
        self.assert_full_rebuild_equal()

    def test_universe_or_report_change_recalculates_everything(self):
        self.prepare()
        self.edit('universe.json', lambda rows: rows[2].update(sector='Energy'))
        self.assertEqual(self.prepare(), (1, ['AAA', 'BBB', 'CCC']))
        self.assert_full_rebuild_equal()

    def test_changed_bytes_with_a_kept_stamp_are_recalculated(self):
        # A restore that keeps size and timestamps must not hide changed rows.
        self.prepare()
        path = self.raw / 'px' / 'AAA.json'
        before, stamp = path.read_text(), path.stat()
        path.write_text(before.replace('"adjClose": 13', '"adjClose": 31'))
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.assertEqual([path.stat().st_size, path.stat().st_mtime_ns], [stamp.st_size, stamp.st_mtime_ns])
        self.edit('treasury.json', lambda rows: rows.insert(0, dict(date='2015-12-01', month3=3, year10=4)))
        self.assertEqual(self.prepare()[0], 1)
        self.assert_full_rebuild_equal()

    def test_removed_price_file_runs_reference(self):
        self.prepare()
        (self.raw / 'px' / 'CCC.json').unlink()
        self.assertEqual(self.prepare(), (1, ['AAA', 'BBB']))
        self.assert_full_rebuild_equal()

    def test_database_without_reuse_evidence_recalculates(self):
        self.prepare()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM metadata WHERE key='reuse'")
        self.append_session('2015-12-01')
        self.assertEqual(self.prepare(), (1, ['AAA', 'BBB', 'CCC']))
        self.assert_full_rebuild_equal()


if __name__ == '__main__':
    unittest.main()
