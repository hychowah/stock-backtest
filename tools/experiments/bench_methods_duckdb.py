"""Benchmark-only, batched saved-price lookup through DuckDB ASOF joins.

Resolve the nearest non-null saved price in the requested direction. Preserve
exact-day matches. Return no result when that direction has no saved price.
Date tolerance belongs to the shared policy adapter. Never download, change
inputs, rank holdings or persist results. The caller owns its SQLite connection.

One SQLite cursor streams bounded chunks into registered NumPy buffers. DuckDB
uses a private, disposable database and spill directory. It needs neither Arrow
nor a downloaded SQLite extension. No application financial formula lives here.
"""
from datetime import date
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time


MAX_ORDINAL = date.max.toordinal()
CHUNK_ROWS = 65_536
THREADS = 4
MEMORY_LIMIT = '1GB'


def _working_root(db):
    """Keep native working files beside the runtime, never in source/raw/data."""
    requested = os.environ.get('BACKTEST_METHODS_DUCKDB_WORKDIR')
    if requested:
        root = Path(requested).resolve()
    elif os.name == 'nt':
        # The benchmark interpreter is installed beneath the native runtime's
        # tmp/. Find that registered runtime without depending on source paths.
        root = None
        candidates = list(Path(sys.executable).resolve().parents)
        for row in db.execute('PRAGMA database_list'):
            if row[1] == 'main' and row[2]:
                candidates.extend(Path(row[2]).resolve().parents)
        for candidate in candidates:
            if (candidate / 'data/workspace.json').is_file():
                root = candidate / 'tmp/cb02-methods/duckdb-spill'
                break
        if root is None:
            root = Path(tempfile.gettempdir()) / 'cb02-methods-duckdb-spill'
    else:
        root = Path(tempfile.gettempdir()) / 'cb02-methods-duckdb-spill'
    source = Path(__file__).resolve().parents[2]
    source_checkout = (source / '.git').exists() or (source / '.git-local').is_dir()
    if source_checkout and (root == source or root.is_relative_to(source)):
        raise ValueError('DuckDB benchmark working files must stay outside source.')
    root.mkdir(parents=True, exist_ok=True)
    return root


class DuckDBPrices:
    """Own bounded DuckDB inputs and resolve each query batch in two joins."""

    def __init__(self, readonly_sqlite_db):
        began = time.perf_counter()
        # Optional dependencies stay inside construction: importing the methods
        # catalog can still report this method unavailable when wheels are absent.
        import duckdb
        import numpy as np
        self._np = np
        self._db = None
        self._directory = None
        self._symbols = {}
        self._closed = False
        self.stats = {}
        try:
            self._directory = Path(tempfile.mkdtemp(prefix='prices-', dir=_working_root(readonly_sqlite_db)))
            spill = self._directory / 'spill'
            spill.mkdir()
            self._db = duckdb.connect(str(self._directory / 'prices.duckdb'),
                                      config=dict(threads=THREADS, memory_limit=MEMORY_LIMIT,
                                                  temp_directory=str(spill),
                                                  preserve_insertion_order=False))
            self._db.execute('CREATE TABLE price_values(lookup_key INTEGER, day INTEGER, value DOUBLE)')
            rows = raw_points = adjusted_points = 0
            chunk_peak_bytes = 0
            columns_cursor = readonly_sqlite_db.execute('PRAGMA table_info(prices)')
            try:
                columns = {row[1] for row in columns_cursor}
            finally:
                columns_cursor.close()
            price_column = 'price' if 'price' in columns else 'NULL AS price'
            adjusted_column = 'adjusted' if 'adjusted' in columns else 'NULL AS adjusted'
            cursor = readonly_sqlite_db.execute(
                f'SELECT symbol,day,{price_column},{adjusted_column} FROM prices ORDER BY symbol,day')
            previous = None
            self._db.execute('BEGIN TRANSACTION')
            try:
                while True:
                    chunk = cursor.fetchmany(CHUNK_ROWS)
                    if not chunk:
                        break
                    # At most two finite values exist per saved row. Missing
                    # values produce no lookup point, so ASOF skips them exactly.
                    capacity = len(chunk) * 2
                    keys = np.empty(capacity, dtype=np.int32)
                    days = np.empty(capacity, dtype=np.int32)
                    values = np.empty(capacity, dtype=np.float64)
                    chunk_peak_bytes = max(chunk_peak_bytes, keys.nbytes + days.nbytes + values.nbytes)
                    used = 0
                    for symbol, day, price, adjusted in chunk:
                        if not isinstance(symbol, str) or not symbol:
                            raise ValueError('Saved price symbol must be a nonempty string.')
                        ordinal = date.fromisoformat(day).toordinal()
                        identity = symbol, ordinal
                        if previous == identity:
                            raise ValueError('Saved prices must have unique symbol/date pairs.')
                        previous = identity
                        symbol_id = self._symbols.get(symbol)
                        if symbol_id is None:
                            symbol_id = len(self._symbols)
                            self._symbols[symbol] = symbol_id
                        for field, value in enumerate((price, adjusted)):
                            if value is None:
                                continue
                            value = float(value)
                            if not math.isfinite(value):
                                raise ValueError('Saved prices must be finite when non-null.')
                            keys[used] = symbol_id * 2 + field
                            days[used] = ordinal
                            values[used] = value
                            used += 1
                            if field == 0:
                                raw_points += 1
                            else:
                                adjusted_points += 1
                        rows += 1
                    if used:
                        self._db.register('price_chunk', dict(lookup_key=keys[:used], day=days[:used], value=values[:used]))
                        try:
                            self._db.execute('INSERT INTO price_values SELECT lookup_key,day,value FROM price_chunk')
                        finally:
                            self._db.unregister('price_chunk')
                self._db.execute('COMMIT')
            except BaseException:
                self._db.execute('ROLLBACK')
                raise
            finally:
                cursor.close()
            self._db.execute('CHECKPOINT')
            self.stats = dict(
                versions=dict(duckdb=duckdb.__version__, numpy=np.__version__),
                load_seconds=time.perf_counter()-began,
                rows=rows, symbols=len(self._symbols), raw_points=raw_points,
                adjusted_points=adjusted_points,
                payload_bytes=(raw_points+adjusted_points)*16,
                chunk_rows=CHUNK_ROWS, peak_numpy_chunk_bytes=chunk_peak_bytes,
                disk_bytes=self._disk_bytes(), memory_limit=MEMORY_LIMIT, threads=THREADS,
                resolve_calls=0, queries=0, resolve_seconds=0.,
                memory_accounting='Payload is int32 lookup key + int32 ordinal + float64 per non-null point. '
                                  'DuckDB compression, allocator and query memory are separate; 1GB is its configured buffer limit, '
                                  'not a total-process RSS guarantee. SQLite fetchmany holds at most chunk_rows Python rows.',
            )
        except BaseException:
            self.close()
            raise

    def _disk_bytes(self):
        if self._directory is None:
            return 0
        return sum(path.stat().st_size for path in self._directory.rglob('*') if path.is_file())

    def resolve(self, queries):
        """Return ordered None|(actual ordinal, price) via batched ASOF LEFT JOINs.

        Every query is (symbol, integer ordinal, 'price'|'adjusted', bool forward).
        There is no date slack. Unknown symbols and empty series return None.
        Invalid queries fail before executing a join. No per-symbol SQL occurs.
        """
        if self._closed:
            raise RuntimeError('Price resolver is closed.')
        began = time.perf_counter()
        queries = list(queries)
        count = len(queries)
        if not count:
            self.stats['resolve_calls'] += 1
            return []
        np = self._np
        keys = np.empty(count, dtype=np.int32)
        days = np.empty(count, dtype=np.int32)
        forwards = np.empty(count, dtype=np.bool_)
        for index, query in enumerate(queries):
            if not isinstance(query, (tuple, list)) or len(query) != 4:
                raise ValueError('A price query must contain four fields.')
            symbol, ordinal, column, forward = query
            if not isinstance(symbol, str) or not symbol:
                raise ValueError('Query symbol must be a nonempty string.')
            if type(ordinal) is not int or not 1 <= ordinal <= MAX_ORDINAL:
                raise ValueError('Query day must be a valid integer date ordinal.')
            if column not in ('price', 'adjusted'):
                raise ValueError('Query column must be price or adjusted.')
            if type(forward) is not bool:
                raise ValueError('Query direction must be a boolean.')
            symbol_id = self._symbols.get(symbol)
            keys[index] = -1 if symbol_id is None else symbol_id * 2 + (column == 'adjusted')
            days[index] = ordinal
            forwards[index] = forward
        self._db.register('lookup_queries', dict(query_id=np.arange(count, dtype=np.int64),
                                                lookup_key=keys, day=days, forward=forwards))
        try:
            # Filtering the right side to the batch's keys avoids joining every
            # saved company for a small requested pool. Direction is an explicit
            # pair of ASOF inequalities; exact dates pass both inequalities.
            sql = '''
                WITH backward_queries AS (
                    SELECT query_id,lookup_key,day FROM lookup_queries WHERE NOT forward
                ), forward_queries AS (
                    SELECT query_id,lookup_key,day FROM lookup_queries WHERE forward
                ), backward_values AS (
                    SELECT lookup_key,day,value FROM price_values
                    WHERE lookup_key IN (SELECT DISTINCT lookup_key FROM backward_queries)
                ), forward_values AS (
                    SELECT lookup_key,day,value FROM price_values
                    WHERE lookup_key IN (SELECT DISTINCT lookup_key FROM forward_queries)
                ), answers AS (
                    SELECT q.query_id,p.day,p.value
                    FROM backward_queries q ASOF LEFT JOIN backward_values p
                    ON q.lookup_key=p.lookup_key AND q.day>=p.day
                    UNION ALL
                    SELECT q.query_id,p.day,p.value
                    FROM forward_queries q ASOF LEFT JOIN forward_values p
                    ON q.lookup_key=p.lookup_key AND q.day<=p.day
                )
                SELECT query_id,day,value FROM answers ORDER BY query_id
            '''
            rows = self._db.execute(sql).fetchall()
        finally:
            self._db.unregister('lookup_queries')
        if len(rows) != count or any(row[0] != index for index, row in enumerate(rows)):
            raise ValueError('ASOF lookup did not preserve one answer per ordered query.')
        answers = []
        for unused, actual, value in rows:
            if actual is None:
                if value is not None:
                    raise ValueError('ASOF returned a value without a date.')
                answers.append(None)
            elif value is None or not math.isfinite(value):
                raise ValueError('ASOF returned a malformed saved price.')
            else:
                answers.append((int(actual), float(value)))
        self.stats['resolve_calls'] += 1
        self.stats['queries'] += count
        self.stats['resolve_seconds'] += time.perf_counter()-began
        self.stats['disk_bytes'] = self._disk_bytes()
        return answers

    def close(self):
        """Release DuckDB handles and owned temporary files; leave SQLite open."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._db is not None:
                self._db.close()
                self._db = None
        finally:
            if self._directory is not None:
                shutil.rmtree(self._directory)
                self._directory = None
            self._symbols.clear()


def open_prices(readonly_sqlite_db):
    """Stream saved SQLite prices once and return a disposable DuckDB resolver."""
    return DuckDBPrices(readonly_sqlite_db)
