"""Borrow admitted daily SQLite facts through the existing observation contract.

The caller owns the connection, source/cache admission and freshness callback.
Close the returned view before the connection. No schema, cache or financial
policy is introduced here. Population order comes from daily.histories().
"""
from collections.abc import Mapping
from datetime import date
import hashlib
import json
from pathlib import Path

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

from backtest.inputs import daily, observation_inputs
from backtest.runtime import backtest_control
from backtest.financial import books

MAX_HISTORY = 16384
MAX_RECORD_BYTES = 4 * 1024 * 1024


def prepared_view(db, freshness, *, checkpoint=backtest_control.checkpoint):
    """Return a borrowed ReadView; freshness validates the owning admitted input.

    No connection or lock escapes. Full populations include uncached companies,
    so the provider retains its original legacy-buffer admission policy.
    """
    freshness()
    for table in ('observation_annual','observation_sources','observation_latest'):
        largest=db.execute('SELECT coalesce(max(length(CAST(evidence_json AS BLOB))),0) FROM '+table).fetchone()[0]
        if largest>MAX_RECORD_BYTES:raise ValueError('Prepared observation record exceeds its byte bound.')
    expected = observation_inputs.require(db, verify_content=True, checkpoint=checkpoint)
    row = db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()
    if row is None:
        raise ValueError('Admitted daily input identity is missing.')
    binding = json.loads(row[0])
    identity = 'sqlite:' + hashlib.sha256(observation_inputs.encoded(dict(inputs=binding,adapter=_LOADED)).encode()).hexdigest()
    cached = daily.cached_symbols(db)
    class Population(Mapping):
        # Financial pools decide eligibility. SQL supplies only one bounded raw
        # history at a time, in the original first-occurrence population order.
        def __init__(self,pool):self.pool=pool
        def __getitem__(self,symbol):
            rows=[daily.prepared_report(row)[1] for row in db.execute(
                'SELECT * FROM statements WHERE symbol=? ORDER BY fiscal LIMIT ?', (symbol,MAX_HISTORY+1))]
            checkpoint()
            if len(rows)>MAX_HISTORY:raise ValueError('Prepared observation history exceeds its bound.')
            if self.pool=='legacy':rows=books.pools({symbol:rows})[1].get(symbol,[])
            if not rows:raise KeyError(symbol)
            return rows
        def __iter__(self):
            for row in db.execute('SELECT symbol FROM statements GROUP BY symbol ORDER BY min(rowid)'):
                checkpoint()
                if self.pool=='cached' or self.get(row[0]):yield row[0]
        def __len__(self):
            return db.execute('SELECT count(DISTINCT symbol) FROM statements').fetchone()[0] if self.pool=='cached' else sum(1 for _ in self)
    populations=(Population('cached'),Population('legacy'))
    def reports(symbol, pool):
        return [dict(row,fiscal=str(row['fiscal']),known=str(row['known'])) for row in populations[0 if pool=='cached' else 1].get(symbol,[])]
    def maximum(table):
        # Annual rows count all endpoints per company. Provider preflight pays
        # for their aggregate, while ReadView bounds each endpoint's history.
        return db.execute('SELECT coalesce(max(n),0) FROM (SELECT count(*) n FROM ' + table + ' GROUP BY symbol)').fetchone()[0]
    bounds = dict(historical_through=binding.get('inputs', {}).get('historical_through'),
        latest_date=expected['latest_date'], population=len(populations[0]),
        report_rows=db.execute('SELECT count(*) FROM statements').fetchone()[0],
        max_reports=maximum('statements'), max_annual=maximum('observation_annual'))
    def validate():
        checkpoint(); freshness()
        if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=_LOADED:
            raise ValueError('Loaded SQLite observation adapter changed.')
        current = db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()
        if current is None or json.loads(current[0]) != binding:
            raise ValueError('Admitted daily input identity changed.')
    return observation_inputs.ReadView(identity, db, validate, reports,
        lambda symbol, day, column, forward, slack: daily.price(db, symbol, day, column, forward, slack),
        expected=expected, max_history=MAX_HISTORY, max_record_bytes=MAX_RECORD_BYTES,
        bounds=bounds, populations=lambda check: populations,
        cached=lambda symbol: symbol in cached,
        session=lambda day: db.execute('SELECT 1 FROM sessions WHERE day=?', (str(day),)).fetchone() is not None)
