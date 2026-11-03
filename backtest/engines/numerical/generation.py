"""Immutable numerical inputs, exported offline from validated prepared tables.

The store owns publication, recovery, mappings and reader leases. An attachment
can own a checked prepared-research reader, closed before its mappings. Callers retain cache
ownership during calculation. Delegated workers retain source ownership and
their generation pin; their coordinator retains financial ownership. Close
evaluators before closing the input attachment.
No application routing, downloads or reference-report writes occur here.
"""
from backtest.financial import rules, books as financial_books, metrics
from backtest.inputs import daily, research, observation_inputs, dated_observation_inputs

from collections.abc import Mapping, Sequence
from bisect import bisect_right
from contextlib import closing
from datetime import date
from functools import wraps
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import uuid

import numpy as np

from backtest.runtime import cache_access as cache_access
from backtest.inputs import cache_assets as cache_assets
from backtest.engines.numerical.policy import PolicyProgram, FACTOR_VERSION
from backtest.paths import ROOT

FORMAT = 1
TEMPORAL_VERSION = 1
STORE = ROOT / 'data' / 'numerical'
CHUNK = 4096
MAX_MANIFEST = 4 * 1024 * 1024
MAX_HISTORY = 16384
WORKER_REFERENCE_VERSION = 1
# Retain ownership after a caller loses a reference or a close fails. Explicit
# successful close removes this registration. GC is not a closure protocol.
_attachments = {}
ARRAYS = {
    'raw_offsets': '<i8', 'raw_days': '<i4', 'raw_values': '<f8',
    'adjusted_offsets': '<i8', 'adjusted_days': '<i4', 'adjusted_values': '<f8',
    'symbol_sort': '<i4', 'cached_mask': '|b1', 'report_symbol': '<i4',
    'report_fiscal': '<i4', 'report_known': '<i4', 'report_cap': '<f8',
    'report_enterprise': '<f8', 'report_yield': '<f8', 'average_3y': '<f8',
    'financial_parameters': '<f8',
    **{f'{pool}_{field}': dtype for pool in ('cached', 'legacy') for field, dtype in
       (('offsets', '<i8'), ('report_ids', '<i4'), ('known', '<i4'), ('fiscal', '<i4'))}}


class _Cancelled(BaseException):
    def __init__(self, error): self.error = error


def _cancellable(operation):
    """Keep caller cancellation distinct from malformed artifact ValueErrors."""
    @wraps(operation)
    def invoke(self, checkpoint=lambda: None):
        def check():
            try: checkpoint()
            except BaseException as error: raise _Cancelled(error) from None
        try: return operation(self, check)
        except _Cancelled as interrupted: raise interrupted.error from None
    return invoke


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _sha(path, checkpoint=lambda: None):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checkpoint()
            result.update(chunk)
    return result.hexdigest()


def _replace(source, target, checkpoint=lambda: None):
    for attempt in range(len(cache_assets.PUBLISH_RETRY_DELAYS) + 1):
        checkpoint()
        try: source.replace(target); return
        except PermissionError as error:
            if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == len(cache_assets.PUBLISH_RETRY_DELAYS): raise
            time.sleep(cache_assets.PUBLISH_RETRY_DELAYS[attempt])


def _read(path):
    if not _plain(path) or path.stat().st_size > MAX_MANIFEST:
        raise ValueError('Invalid numerical metadata file.')
    return json.loads(path.read_bytes())


def _plain(path):
    return not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)()


def _readonly(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA cache_size=-2048')
    db.execute('PRAGMA query_only=ON')
    return db


def _report(row, text=False):
    row = dict(row)
    row.pop('id', None)
    row.pop('sid', None)
    row.pop('symbol', None)
    row.update(enterprise=row['enterprise_value'], **{'yield': row['ebitda_yield']})
    if not text:
        row['fiscal'], row['known'] = map(date.fromisoformat, (row['fiscal'], row['known']))
    return row


class _Reports(Sequence):
    def __init__(self, owner): self.owner = owner
    def __len__(self): return len(self.owner.report_fiscal)
    def __getitem__(self, index):
        if isinstance(index, slice): return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0: index += len(self)
        row = self.owner._db.execute('SELECT * FROM reports WHERE id=?', (int(index),)).fetchone()
        if row is None: raise IndexError(index)
        return _report(row)


class _Records(Mapping):
    """Load one symbol at a time. Do not retain histories across evaluations."""
    def __init__(self, owner, kind): self.owner, self.kind = owner, kind
    def __iter__(self):
        table = 'reports' if self.kind == 'histories' else 'financial_inputs'
        return (row[0] for row in self.owner._db.execute(f'SELECT DISTINCT symbol FROM {table}'))
    def __len__(self): return sum(1 for _ in self)
    def __getitem__(self, symbol):
        if self.kind == 'histories':
            rows = [_report(row, text=True) for row in self.owner._db.execute(
                'SELECT * FROM reports WHERE symbol=? ORDER BY fiscal,id', (symbol,))]
            if not rows: raise KeyError(symbol)
            return rows
        rows = {row[0]: json.loads(row[1]) for row in self.owner._db.execute(
            'SELECT fiscal,values_json FROM financial_inputs WHERE symbol=?', (symbol,))}
        if not rows: raise KeyError(symbol)
        return rows


class DatedYields:
    """Saved yields with no future observation or invented missing-value default.

    Rows are ordered (ISO date, percent) pairs from the prepared Treasury table.
    Zero and negative observations remain usable. No earlier row returns None.
    """
    def __init__(self, rows):
        self.rows = tuple(tuple(row) for row in rows)
        self.days = tuple(row[0] for row in self.rows)

    def __call__(self, day):
        index = bisect_right(self.days, str(day)) - 1
        return self.rows[index][1] if index >= 0 else None


def _export(source, policy, folder, checkpoint):
    """Bound prices by CHUNK and annual work by one symbol's prepared history."""
    db = sqlite3.connect(folder / 'records.sqlite')
    db.execute('PRAGMA cache_size=-2048')
    db.executescript('''
      CREATE TABLE symbols(id INTEGER PRIMARY KEY,symbol TEXT UNIQUE,cached INTEGER);
      CREATE TABLE reports(id INTEGER PRIMARY KEY,sid INTEGER,symbol TEXT,fiscal TEXT,
        known TEXT,market_cap REAL,enterprise_value REAL,ebitda REAL,ebitda_yield REAL);
      CREATE INDEX report_history ON reports(symbol,fiscal,id);
      CREATE TABLE companies(symbol TEXT PRIMARY KEY,name TEXT,exchange TEXT,sector TEXT);
      CREATE TABLE financial_inputs(symbol TEXT,fiscal TEXT,values_json TEXT,PRIMARY KEY(symbol,fiscal));
      CREATE TABLE sessions(day TEXT PRIMARY KEY,price REAL);
      CREATE TABLE treasuries(day TEXT PRIMARY KEY,yield_value REAL);
      CREATE TABLE treasury10(day TEXT PRIMARY KEY,yield_percent REAL);
    ''')
    db.executescript(observation_inputs.SCHEMA)
    arrays = {}
    def allocate(name, shape):
        array = np.lib.format.open_memmap(folder / (name + '.npy'), mode='w+',
                                         dtype=ARRAYS[name], shape=shape)
        arrays[name] = array
        return array
    try:
        # First report occurrence supplies the stable buffer order. Price-only
        # symbols follow alphabetically, matching the tested sparse loader.
        symbols = [row[0] for row in source.execute(
            'SELECT symbol FROM statements GROUP BY symbol ORDER BY min(rowid)')]
        seen = set(symbols)
        symbols.extend(row[0] for row in source.execute('SELECT DISTINCT symbol FROM prices ORDER BY symbol')
                       if row[0] not in seen)
        cached = daily.cached_symbols(source)
        db.executemany('INSERT INTO symbols VALUES(?,?,?)',
                       ((i, symbol, int(symbol in cached)) for i, symbol in enumerate(symbols)))
        for table in ('companies', 'financial_inputs', 'sessions', 'treasuries', 'treasury10'):
            cursor = source.execute('SELECT * FROM ' + table)
            batch, batch_bytes = [], 0
            for row in cursor:
                checkpoint()
                size = sum(len(v.encode('utf-8')) if isinstance(v, str) else 8 for v in row)
                if size > MAX_MANIFEST: raise ValueError('Prepared record exceeds its byte bound.')
                if batch and (len(batch) >= CHUNK or batch_bytes + size > 1024 * 1024):
                    db.executemany('INSERT INTO ' + table + ' VALUES(' + ','.join('?' * len(batch[0])) + ')', batch)
                    batch, batch_bytes = [], 0
                batch.append(row); batch_bytes += size
            if batch:
                db.executemany('INSERT INTO ' + table + ' VALUES(' + ','.join('?' * len(batch[0])) + ')', batch)
            cursor.close()
        # Legacy synthetic calculation fixtures have no observation capability.
        # Real preparation admits this projection in _binding; a missing copy
        # always fails observations(), rather than fabricating source evidence.
        if source.execute('SELECT count(*) FROM observation_metadata').fetchone()[0]:
            observation_inputs.copy(source, db, checkpoint, max_record_bytes=MAX_MANIFEST)
        allocate('symbol_sort', (len(symbols),))[:] = np.argsort(np.asarray(symbols), kind='stable')
        allocate('cached_mask', (len(symbols),))[:] = [s in cached for s in symbols]
        for column, prefix in (('price', 'raw'), ('adjusted', 'adjusted')):
            count = source.execute(f'SELECT count({column}) FROM prices').fetchone()[0]
            offsets = allocate(prefix + '_offsets', (len(symbols) + 1,))
            days, values = allocate(prefix + '_days', (count,)), allocate(prefix + '_values', (count,))
            position = 0
            for sid, symbol in enumerate(symbols):
                checkpoint(); offsets[sid] = position
                cursor = source.execute(f'SELECT day,{column} FROM prices WHERE symbol=? AND {column} IS NOT NULL ORDER BY day', (symbol,))
                while batch := cursor.fetchmany(CHUNK):
                    checkpoint()
                    for day, value in batch:
                        if not math.isfinite(value) or value <= 0:
                            raise ValueError('Prepared prices must be finite and positive.')
                        days[position], values[position] = date.fromisoformat(day).toordinal(), value
                        position += 1
                cursor.close()
            offsets[-1] = position
        count = source.execute('SELECT count(*) FROM statements').fetchone()[0]
        for name in ('report_symbol', 'report_fiscal', 'report_known', 'report_cap',
                     'report_enterprise', 'report_yield', 'average_3y'):
            allocate(name, (count,))
        allocate('financial_parameters', (count, len(policy.parameter_names)))
        # Membership is delegated to the same source-owned pool policy.
        for pool in ('cached', 'legacy'):
            allocate(pool + '_offsets', (len(symbols) + 1,))
        pool_positions = dict(cached=0, legacy=0)
        # IDs are accumulated on disk. No whole-report Python graph is retained.
        db.execute('CREATE TABLE pool_rows(pool TEXT,position INTEGER,id INTEGER,known INTEGER,fiscal INTEGER,PRIMARY KEY(pool,position))')
        position = 0
        for sid, symbol in enumerate(symbols):
            checkpoint()
            history = []
            for row in source.execute('SELECT * FROM statements WHERE symbol=? ORDER BY fiscal,rowid', (symbol,)):
                item = _report(row); history.append(item)
                if len(history) > MAX_HISTORY:
                    raise ValueError('Prepared annual history exceeds the per-symbol bound.')
            textual = [dict(row, fiscal=str(row['fiscal']), known=str(row['known'])) for row in history]
            known = [row['known'] for row in history]
            if known != sorted(known): raise ValueError('Prepared report histories must be temporally ordered.')
            financials = {}
            for fiscal, values in db.execute('SELECT fiscal,values_json FROM financial_inputs WHERE symbol=?', (symbol,)):
                if len(financials) >= MAX_HISTORY or len(values) > MAX_MANIFEST:
                    raise ValueError('Prepared financial history exceeds the per-symbol bound.')
                financials[fiscal] = json.loads(values)
            broad, legacy = financial_books.pools({symbol: history})
            legacy_ids = {id(row) for row in legacy.get(symbol, [])}
            for pool in pool_positions: arrays[pool + '_offsets'][sid] = pool_positions[pool]
            for row in history:
                checkpoint()
                db.execute('INSERT INTO reports VALUES(?,?,?,?,?,?,?,?,?)',
                    (position, sid, symbol, str(row['fiscal']), str(row['known']), row['market_cap'],
                     row['enterprise_value'], row['ebitda'], row['ebitda_yield']))
                for name, value in (('symbol', sid), ('fiscal', row['fiscal'].toordinal()),
                        ('known', row['known'].toordinal()), ('cap', row['market_cap']),
                        ('enterprise', row['enterprise']), ('yield', row['yield'])):
                    arrays['report_' + name][position] = value
                average = metrics.annual_average(textual, str(row['fiscal']), 3)
                arrays['average_3y'][position] = np.nan if average is None else average
                arrays['financial_parameters'][position] = policy.specialize_financial(str(row['fiscal']), financials)
                for pool in pool_positions:
                    if pool == 'legacy' and id(row) not in legacy_ids: continue
                    db.execute('INSERT INTO pool_rows VALUES(?,?,?,?,?)', (pool, pool_positions[pool],
                        position, row['known'].toordinal(), row['fiscal'].toordinal()))
                    pool_positions[pool] += 1
                position += 1
        for pool, size in pool_positions.items():
            arrays[pool + '_offsets'][-1] = size
            for field, sql in (('report_ids', 'id'), ('known', 'known'), ('fiscal', 'fiscal')):
                array = allocate(pool + '_' + field, (size,))
                for i, row in enumerate(db.execute(f'SELECT {sql} FROM pool_rows WHERE pool=? ORDER BY position', (pool,))):
                    if i % CHUNK == 0: checkpoint()
                    array[i] = row[0]
        db.execute('DROP TABLE pool_rows')
        db.commit()
    finally:
        db.close()
        for array in arrays.values():
            array.flush(); array._mmap.close()
    return {name: dict(dtype=ARRAYS[name], shape=list(array.shape)) for name, array in arrays.items()}


def _valid_id(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _source_binding(policy, checkpoint=lambda: None):
    """One source definition for coordinator freshness and exact worker attach."""
    source = {p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else p.as_posix(): _sha(p, checkpoint) for p in policy.source_paths}
    for name in ('generation.py', 'policy.py', 'decisions.py', 'temporal.py', 'factors.py'):
        source['backtest/engines/numerical/'+name] = _sha(Path(__file__).with_name(name), checkpoint)
    source['backtest/runtime/cache_access.py'] = _sha(Path(cache_access.__file__), checkpoint)
    source['backtest/inputs/dated_observation_inputs.py'] = _sha(Path(dated_observation_inputs.__file__), checkpoint)
    source['backtest/inputs/observation_inputs.py'] = _sha(Path(observation_inputs.__file__), checkpoint)
    return source


class _ReaderGate:
    """Stable OS pin, separate from source and financial ownership."""
    def __init__(self, path, *, exclusive=False):
        self.handle, self.release = None, None
        if any(not _plain(part) for part in (path, *path.parents)):
            raise ValueError('Invalid numerical reader gate.')
        self.handle = path.open('r+b' if exclusive else 'rb', buffering=0)
        try:
            if self.handle.seek(0, 2) != 1: raise ValueError('Invalid numerical reader gate.')
            if os.name == 'nt':
                self.release = cache_access._windows_reader_lock(self.handle, exclusive)
            else:
                import fcntl
                fcntl.flock(self.handle, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                self.release = lambda: fcntl.flock(self.handle, fcntl.LOCK_UN)
        except BaseException:
            self.handle.close(); self.handle = None
            raise

    def close(self):
        try:
            if self.release is not None: self.release(); self.release = None
            if self.handle is not None: self.handle.close(); self.handle = None
        except BaseException as error:
            _attachments[id(self)] = self
            error.numerical_inputs = self
            raise
        _attachments.pop(id(self), None)

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class _VerificationResources:
    """Keep temporary verifier handles and a failed worker pin retryable."""
    def __init__(self, pin):
        self.arrays, self.db, self.pin, self.failed = {}, None, pin, False

    def close(self):
        try:
            if self.db is not None: self.db.close(); self.db = None
            for name, array in list(self.arrays.items()):
                array._mmap.close()
                del self.arrays[name]
            if self.failed and self.pin is not None: self.pin.close(); self.pin = None
        except BaseException as error:
            self.failed = True
            _attachments[id(self)] = self
            error.numerical_inputs = self
            raise
        _attachments.pop(id(self), None)


def _attachment_rows(db, query, checkpoint):
    for index, row in enumerate(db.execute(query)):
        if index % CHUNK == 0: checkpoint()
        yield row


class AttachedInputs:
    """Owned read-only mappings and lazy records. Views expire at close.

    Close all evaluators and borrowed NumPy views first. Failed close preserves
    the lease and remaining handles so the caller can retry explicitly.
    """
    def __init__(self, folder, manifest, policy, lease=None, *, pin=None, checkpoint=lambda: None):
        self._arrays, self._db, self._lease, self._pin = {}, None, lease, pin
        self.closed = False
        self.policy = policy
        self.signature = manifest['identity']
        self._binding = manifest['binding']
        self.temporal_version = self._binding['temporal_version']
        self.factor_version = self._binding['factor_version']
        self.field_schema = self._binding['field_schema']
        self.generation = json.dumps(manifest['binding']['daily'])
        self.database_path = str(folder / 'records.sqlite')
        self.bankrupt = frozenset(rules.BANKRUPT)
        _attachments[id(self)] = self
        try:
            for name in ARRAYS:
                checkpoint()
                self._arrays[name] = np.load(folder / (name + '.npy'), mmap_mode='r', allow_pickle=False)
                setattr(self, name, self._arrays[name])
            self._db = _readonly(folder / 'records.sqlite')
            def rows(query): return _attachment_rows(self._db, query, checkpoint)
            self.symbols = tuple(row[0] for row in rows('SELECT symbol FROM symbols ORDER BY id'))
            self.symbol_ids = {symbol: i for i, symbol in enumerate(self.symbols)}
            self.cached = frozenset(row[0] for row in rows('SELECT symbol FROM symbols WHERE cached=1'))
            self.sessions = dict(rows('SELECT day,price FROM sessions ORDER BY day'))
            treasury = list(rows('SELECT day,yield_value FROM treasuries ORDER BY day'))
            self.treasury_days, self.treasury_values = [r[0] for r in treasury], [r[1] for r in treasury]
            self.ten_year_yield = DatedYields(rows('SELECT day,yield_percent FROM treasury10 ORDER BY day'))
            for field in ('offsets', 'report_ids', 'known', 'fiscal'):
                setattr(self, 'pool_' + field, {pool: self._arrays[pool + '_' + field] for pool in ('cached', 'legacy')})
            self.report_rows, self.histories, self.financials = _Reports(self), _Records(self, 'histories'), _Records(self, 'financials')
            self.stats = dict(numeric_payload_bytes=sum(a.nbytes for a in self._arrays.values()),
                              symbols=len(self.symbols), reports=len(self.report_fiscal))
            checkpoint()
        except BaseException as error:
            try: self.close()
            except BaseException:
                error.numerical_inputs = self
            raise

    @property
    def companies(self):
        return tuple(tuple(r) for r in self._db.execute('SELECT * FROM companies'))

    def validate(self):
        """Check request-time freshness under the caller's job ownership.

        Keep that outer coordinator scope through calculation. This nested
        check never substitutes an old attachment receipt for current inventory.
        """
        if self.closed: raise ValueError('Numerical attachment is closed.')
        with self._store.coordinator.hold():
            binding, policy = self._store._binding()
            if binding != self._binding or policy.signature != self.policy.signature:
                raise ValueError('Numerical attachment is stale. Retry offline export.')

    def worker_reference(self):
        """Describe this exact generation for trusted workers.

        The caller already holds source and financial ownership. Validate
        current inputs before issuing a reference. This grants no preparation,
        recovery or publication operation. Workers own their mappings and pin.
        """
        with self._store.coordinator.hold():
            self.validate()
            self._store._ensure_gate(self.signature)
            return dict(version=WORKER_REFERENCE_VERSION, store=str(self._store.path.resolve()),
                        identity=self.signature)

    @property
    def observation_projection(self):
        """Detached accepted projection identity; reads no company observations."""
        if self.closed:raise ValueError('Numerical attachment is closed.')
        expected=self._binding.get('observations')
        if expected is None:raise ValueError('Generation has no admitted observation inputs.')
        return json.loads(_json(expected))

    def prepared_scopes(self):
        """Own a current research reader bound to this coordinator attachment.

        The caller holds source/financial ownership. Close this borrowed-scope
        source before its attachment. Delegated workers cannot discover it.
        """
        if not hasattr(self, '_store'):
            raise ValueError('Delegated inputs cannot borrow current prepared scopes.')
        if not hasattr(self, '_prepared_readers'):self._prepared_readers=[]
        reader=PreparedScopeReader.__new__(PreparedScopeReader)
        self._prepared_readers.append(reader)
        PreparedScopeReader.__init__(reader,self)
        return reader

    def observations(self):
        """Borrow trusted observation facts; retain this attachment until closed.

        Views own no connections or mappings. Prices use the existing immutable
        raw/adjusted series, with actual dates and the caller's declared tolerance.
        """
        if self.closed:
            raise ValueError('Numerical attachment is closed.')
        expected = self._binding.get('observations')
        if expected is None:
            raise ValueError('Generation has no admitted observation inputs. Retry offline preparation.')

        def reports(symbol, pool):
            if self.closed:
                raise ValueError('Numerical attachment is closed.')
            sid = self.symbol_ids.get(symbol)
            if sid is None:
                return []
            start, end = map(int, self.pool_offsets[pool][sid:sid+2])
            if end-start > MAX_HISTORY:
                raise ValueError('Prepared observation history exceeds its bound.')
            result = []
            for index in range(start, end):
                row = self.report_rows[int(self.pool_report_ids[pool][index])]
                row.update(fiscal=str(row['fiscal']), known=str(row['known']))
                result.append(row)
            return result

        def lookup(symbol, day, column, forward, slack):
            if self.closed:
                raise ValueError('Numerical attachment is closed.')
            sid = self.symbol_ids.get(symbol)
            if sid is None:
                return None
            prefix = 'raw' if column == 'price' else 'adjusted'
            offsets = getattr(self, prefix+'_offsets')
            start, end = map(int, offsets[sid:sid+2])
            days, values = getattr(self, prefix+'_days'), getattr(self, prefix+'_values')
            ordinal = day.toordinal()
            index = int(np.searchsorted(days[start:end], ordinal,
                        side='left' if forward else 'right')) + start - (not forward)
            if index < start or index >= end:
                return None
            actual = date.fromordinal(int(days[index]))
            if slack is not None and abs((actual-day).days) > slack:
                return None
            return actual, float(values[index])

        class Population(Mapping):
            # This order is the original first-report occurrence, including
            # uncached symbols. Filtering it to requested companies would alter
            # tied ranks and the legacy buffer before prices are considered.
            def __init__(population, pool, checkpoint):
                population.pool, population.checkpoint = pool, checkpoint
            def __iter__(population):
                for sid, symbol in enumerate(self.symbols):
                    population.checkpoint()
                    first, last = self.pool_offsets[population.pool][sid:sid+2]
                    if last > first:
                        yield symbol
            def __len__(population):
                return sum(1 for _ in population)
            def __getitem__(population, symbol):
                population.checkpoint()
                rows = reports(symbol, population.pool)
                if not rows:
                    raise KeyError(symbol)
                for row in rows:
                    population.checkpoint()
                    row['fiscal'], row['known'] = map(date.fromisoformat, (row['fiscal'], row['known']))
                return rows

        def maximum(table):
            # Annual admission counts the complete endpoint aggregate. The
            # borrowed view separately enforces each endpoint's history bound.
            return self._db.execute('SELECT coalesce(max(n),0) FROM '
                '(SELECT count(*) n FROM '+table+' GROUP BY symbol)').fetchone()[0]

        bounds = dict(historical_through=self._binding.get('daily', {}).get('inputs', {}).get('historical_through'),
                      latest_date=expected['latest_date'], population=len(self.symbols),
                      report_rows=len(self.report_fiscal), max_reports=maximum('reports'),
                      max_annual=maximum('observation_annual'))

        return observation_inputs.ReadView(self.signature, self._db, self.validate, reports, lookup,
            expected=expected, max_history=MAX_HISTORY, max_record_bytes=MAX_MANIFEST,
            bounds=bounds, populations=lambda checkpoint: (Population('cached', checkpoint), Population('legacy', checkpoint)),
            cached=lambda symbol: symbol in self.cached, session=lambda day: str(day) in self.sessions)

    def close(self):
        if self.closed: return
        for reader in tuple(getattr(self, '_prepared_readers', ())):reader.close()
        if self._db is not None: self._db.close(); self._db = None
        for name, array in list(self._arrays.items()):
            array._mmap.close()
            del self._arrays[name]
        if self._lease is not None:
            path, handle = self._lease
            cache_access._file_lock(handle, False)
            handle.close()
            self._lease = None
            path.unlink(missing_ok=True)
        if self._pin is not None: self._pin.close(); self._pin = None
        self.closed = True
        _attachments.pop(id(self), None)

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class PreparedScopeReader:
    """Admitted current January/latest scopes; connection remains caller-scoped.

    No snapshots are reconstructed from observations. A read can use the whole
    source population only while this object and its exact attachment are live.
    No read transaction survives a scope query or final validation.
    """
    def __init__(self, inputs):
        self.inputs,self.db=inputs,None
        try:
            inputs.validate()
            self.db=research.connect(full_prices=True)
            meta={row[0]:json.loads(row[1]) for row in self.db.execute('SELECT key,value FROM metadata')}
            binding=inputs._binding
            if (meta.get('inputs')!=binding['daily']['inputs'] or meta.get('prices')!=binding['prices']
                    or observation_inputs.require(self.db,expected=binding['observations'],verify_content=True)!=binding['observations']
                    or _sha(research.RESULTS/'summary-exits.txt')!=binding['report']):
                raise ValueError('Prepared scopes differ from the attached generation.')
            self.metadata=meta
            self.version=self.db.execute('PRAGMA data_version').fetchone()[0]
            self.path=Path(self.db.execute('PRAGMA database_list').fetchone()[2])
            self.file=self._file()
            self.validate()
        except BaseException:
            # The attachment already adopted us. Failed close keeps the reader
            # and its connection owned for attachment/session cleanup retry.
            self.close()
            raise

    def _file(self):
        value=self.path.stat()
        return value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns

    def validate(self):
        if self.db is None:raise ValueError('Prepared scope reader is closed.')
        self.inputs.validate()
        if (self._file()!=self.file or self.db.execute('PRAGMA data_version').fetchone()[0]!=self.version
                or {row[0]:json.loads(row[1]) for row in self.db.execute('SELECT key,value FROM metadata')}!=self.metadata):
            raise ValueError('Prepared scopes changed during scalar execution.')

    def close(self):
        if self.db is not None:
            self.db.close();self.db=None
        owners=getattr(self.inputs,'_prepared_readers',[])
        if self in owners:owners.remove(self)

    def __enter__(self):return self
    def __exit__(self,*unused):self.close()


class DelegatedInputs(AttachedInputs):
    """Exact immutable worker view; freshness remains the coordinator's duty.

    The caller owns source before imports. Its checkpoint supplies continuing
    ownership/cancellation checks. No financial ownership is acquired here.
    Close evaluators first, then records and mappings, then the reader pin.
    """
    def validate(self):
        if self.closed: raise ValueError('Numerical attachment is closed.')
        self._checkpoint()

    def worker_reference(self):
        raise ValueError('Only a coordinator attachment can delegate numerical inputs.')


def open_delegated(reference, *, checkpoint):
    """Attach one coordinator-authorized generation without financial access.

    Caller owns source before importing this module and supplies a checkpoint
    that raises when ownership ends or work must stop. This operation never
    chooses current inputs, recovers publication or prepares data. The result
    owns its read-only records connection, mappings and stable retirement pin.
    """
    if not callable(checkpoint): raise ValueError('A worker ownership checkpoint is required.')
    checkpoint()
    if (not isinstance(reference, dict) or set(reference) != {'version', 'store', 'identity'}
            or type(reference['version']) is not int or reference['version'] != WORKER_REFERENCE_VERSION
            or not isinstance(reference['store'], str) or not reference['store']
            or not _valid_id(reference['identity'])):
        raise ValueError('Invalid numerical worker reference.')
    path = Path(reference['store'])
    if not path.is_absolute() or str(path.resolve()) != reference['store']:
        raise ValueError('Numerical worker store must be canonical and absolute.')
    store = GenerationStore(path)
    identity = reference['identity']
    began = time.perf_counter()
    pin = store._gate(identity)
    try:
        checkpoint()
        manifest = store._verify(identity, checkpoint, pin=pin)
        policy = PolicyProgram(bankrupt=rules.BANKRUPT)
        binding = manifest['binding']
        if (binding.get('policy') != policy.signature or binding['field_schema'] != policy.field_schema
                or binding.get('sources') != _source_binding(policy, checkpoint)
                or manifest['arrays']['financial_parameters']['shape'][1] != len(policy.parameter_names)):
            raise ValueError('Numerical worker source policy differs from the delegated generation.')
        inputs = DelegatedInputs(path / identity, manifest, policy,
                                 pin=pin, checkpoint=checkpoint)
    except BaseException as error:
        if not getattr(error, 'numerical_inputs', None): pin.close()
        raise
    inputs._checkpoint = checkpoint
    inputs.stats['attachment_seconds'] = time.perf_counter() - began
    return inputs


class GenerationStore:
    """Publish immutable base inputs; never bind identity to mutable saved books.

    The coordinator is acquired before source connections, mappings and leases.
    Callers retain financial ownership through idle attachment reuse,
    calculation and final resource closure. The runtime uses one such session.
    """
    def __init__(self, path=STORE, coordinator=None):
        self.path = Path(path)
        if any(not _plain(part) for part in (self.path, *self.path.parents)):
            raise ValueError('Numerical store paths cannot use links or junctions.')
        self.coordinator = coordinator or cache_access.workspace

    def _binding(self):
        for name in ('deployment.pending.json', 'research.sqlite.publication.json'):
            if (research.ROOT / 'data' / name).exists():
                raise ValueError('Unfinished publication blocks numerical inputs. Retry preparation.')
        with closing(research.connect(full_prices=True)) as db:
            observations = observation_inputs.require(db, verify_content=True)
        with closing(daily.connect()) as db:
            daily_binding = json.loads(db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()[0])
            observation_inputs.require(db, expected=observations, verify_content=True)
        policy = PolicyProgram(bankrupt=rules.BANKRUPT)
        source = _source_binding(policy)
        return dict(temporal_version=TEMPORAL_VERSION, factor_version=FACTOR_VERSION, field_schema=policy.field_schema,
                    daily=daily_binding, prices=research.price_sources(), report=_sha(research.RESULTS / 'summary-exits.txt'),
                    policy=policy.signature, sources=source, observations=observations), policy

    def _ensure_gate(self, identity):
        """Create once under financial ownership; never replace its inode."""
        if not _valid_id(identity): raise ValueError('Invalid numerical generation identity.')
        path = self.path / 'gates' / (identity + '.lock')
        if any(not _plain(part) for part in (path, *path.parents)):
            raise ValueError('Invalid numerical reader gate.')
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open('xb') as handle: handle.write(b'0')
        except FileExistsError:
            pass
        return path

    def _gate(self, identity, *, exclusive=False):
        if not _valid_id(identity): raise ValueError('Invalid numerical generation identity.')
        return _ReaderGate(self.path / 'gates' / (identity + '.lock'), exclusive=exclusive)

    def _pointer(self):
        path = self.path / 'current.json'
        if not path.exists(): return None
        value = _read(path)
        if not isinstance(value, dict) or set(value) != {'current', 'previous'} or not _valid_id(value['current']) or (
                value['previous'] is not None and not _valid_id(value['previous'])):
            raise ValueError('Corrupt numerical generation pointer.')
        return value

    def _verify(self, identity, checkpoint=lambda: None, *, folder=None, pin=None):
        if not _valid_id(identity): raise ValueError('Invalid numerical generation identity.')
        folder = folder or self.path / identity
        if not _plain(folder): raise ValueError('Invalid generation directory.')
        manifest = _read(folder / 'manifest.json')
        if not isinstance(manifest, dict) or set(manifest) != {'format', 'binding', 'arrays', 'files', 'identity'}:
            raise ValueError('Malformed numerical manifest.')
        if not isinstance(manifest['binding'], dict) or not isinstance(manifest['arrays'], dict) or not isinstance(manifest['files'], dict):
            raise ValueError('Malformed numerical manifest fields.')
        if type(manifest['binding'].get('temporal_version')) is not int or manifest['binding']['temporal_version'] != TEMPORAL_VERSION:
            raise ValueError('Unsupported temporal interface version.')
        if (type(manifest['binding'].get('factor_version')) is not int or
                manifest['binding']['factor_version'] != FACTOR_VERSION or
                not _valid_id(manifest['binding'].get('field_schema'))):
            raise ValueError('Unsupported factor interface version or field schema.')
        core = {key: manifest[key] for key in ('format', 'binding', 'arrays', 'files')}
        if manifest.get('format') != FORMAT or manifest.get('identity') != identity or hashlib.sha256(_json(core)).hexdigest() != identity:
            raise ValueError('Incompatible or corrupt numerical manifest.')
        expected = {name + '.npy' for name in ARRAYS} | {'records.sqlite', 'owner.json'}
        if set(manifest['arrays']) != set(ARRAYS) or set(manifest['files']) != expected:
            raise ValueError('Incomplete numerical file inventory.')
        for name, spec in manifest['arrays'].items():
            if not isinstance(spec, dict) or set(spec) != {'dtype', 'shape'} or spec['dtype'] != ARRAYS[name] or not isinstance(spec['shape'], list) or len(spec['shape']) != (2 if name == 'financial_parameters' else 1) or any(type(n) is not int or n < 0 for n in spec['shape']):
                raise ValueError('Malformed numerical array schema.')
        for evidence in manifest['files'].values():
            if not isinstance(evidence, dict) or set(evidence) != {'bytes', 'sha256'} or type(evidence['bytes']) is not int or evidence['bytes'] < 0 or not _valid_id(evidence['sha256']):
                raise ValueError('Malformed numerical file evidence.')
        if {path.name for path in folder.iterdir()} != expected | {'manifest.json'}:
            raise ValueError('Unmanifested numerical generation contents.')
        if _read(folder / 'owner.json') != {'format': FORMAT, 'owner': 'numerical-generation'}:
            raise ValueError('Unknown numerical generation owner.')
        resources = _VerificationResources(pin)
        arrays = resources.arrays
        try:
            for name, evidence in manifest['files'].items():
                checkpoint(); path = folder / name
                if not _plain(path) or path.stat().st_size != evidence['bytes'] or _sha(path, checkpoint) != evidence['sha256']:
                    raise ValueError('Corrupt numerical buffer: ' + name)
            for name, dtype in ARRAYS.items():
                array = np.load(folder / (name + '.npy'), mmap_mode='r', allow_pickle=False)
                arrays[name] = array
                if array.dtype.str != dtype or list(array.shape) != manifest['arrays'][name]['shape'] or manifest['arrays'][name]['dtype'] != dtype:
                    raise ValueError('Invalid numerical shape or dtype.')
            resources.db = _readonly(folder / 'records.sqlite')
            with closing(resources.db) as db:
                if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok': raise ValueError('Corrupt numerical records.')
                n = db.execute('SELECT count(*) FROM symbols').fetchone()[0]
                r = db.execute('SELECT count(*) FROM reports').fetchone()[0]
                if arrays['cached_mask'].shape != (n,) or arrays['financial_parameters'].ndim != 2 or arrays['financial_parameters'].shape[0] != r:
                    raise ValueError('Invalid numerical record counts.')
                if arrays['symbol_sort'].shape != (n,) or sorted(arrays['symbol_sort'].tolist()) != list(range(n)):
                    raise ValueError('Invalid symbol sort order.')
                symbols = [row[0] for row in db.execute('SELECT symbol FROM symbols ORDER BY id')]
                if not np.array_equal(arrays['cached_mask'], np.fromiter(
                        (bool(row[0]) for row in db.execute('SELECT cached FROM symbols ORDER BY id')),dtype=np.bool_,count=n)):
                    raise ValueError('Cached membership and buffer differ.')
                if [symbols[int(i)] for i in arrays['symbol_sort']] != sorted(symbols):
                    raise ValueError('Invalid symbol sort permutation.')
                for name in ('report_symbol', 'report_fiscal', 'report_known', 'report_cap', 'report_enterprise', 'report_yield', 'average_3y'):
                    if arrays[name].shape != (r,): raise ValueError('Invalid report shape.')
                for i, record in enumerate(db.execute('SELECT * FROM reports ORDER BY id')):
                    if i % CHUNK == 0: checkpoint()
                    if record['id'] != i or not 0 <= record['sid'] < n or symbols[record['sid']] != record['symbol']:
                        raise ValueError('Invalid report record identity.')
                    for field, value in (('symbol', record['sid']),
                            ('fiscal', date.fromisoformat(record['fiscal']).toordinal()),
                            ('known', date.fromisoformat(record['known']).toordinal()),
                            ('cap', record['market_cap']), ('enterprise', record['enterprise_value']),
                            ('yield', record['ebitda_yield'])):
                        if arrays['report_' + field][i] != value: raise ValueError('Report record and buffer differ.')
                for prefix in ('raw', 'adjusted', 'cached', 'legacy'):
                    offsets = arrays[prefix + '_offsets']
                    size = len(arrays[prefix + ('_days' if prefix in ('raw', 'adjusted') else '_report_ids')])
                    if offsets.shape != (n + 1,) or offsets[0] != 0 or offsets[-1] != size or np.any(np.diff(offsets) < 0):
                        raise ValueError('Invalid sparse offsets.')
                    if prefix in ('raw', 'adjusted'):
                        days, values = arrays[prefix + '_days'], arrays[prefix + '_values']
                        if days.ndim != 1 or days.shape != values.shape: raise ValueError('Invalid sparse price shape.')
                        for i in range(0, size, CHUNK):
                            checkpoint()
                            if not np.all(np.isfinite(values[i:i+CHUNK])) or np.any(values[i:i+CHUNK] <= 0) or np.any(days[i:i+CHUNK] < 1) or np.any(days[i:i+CHUNK] > date.max.toordinal()):
                                raise ValueError('Invalid sparse price values.')
                        for start, end in zip(offsets[:-1], offsets[1:]):
                            for i in range(int(start), int(end), CHUNK):
                                checkpoint()
                                if np.any(np.diff(days[max(int(start), i-1):min(i+CHUNK, int(end))]) <= 0):
                                    raise ValueError('Invalid sparse price order.')
                    else:
                        ids = arrays[prefix + '_report_ids']
                        if ids.ndim != 1 or arrays[prefix + '_known'].shape != ids.shape or arrays[prefix + '_fiscal'].shape != ids.shape:
                            raise ValueError('Invalid report identifiers.')
                        for i in range(0,len(ids),CHUNK):
                            checkpoint(); part = ids[i:i+CHUNK]
                            if np.any(part < 0) or np.any(part >= r) or not np.array_equal(arrays[prefix + '_known'][i:i+CHUNK], arrays['report_known'][part]) or not np.array_equal(arrays[prefix + '_fiscal'][i:i+CHUNK], arrays['report_fiscal'][part]):
                                raise ValueError('Invalid report identifiers.')
                        for sid,(start,end) in enumerate(zip(offsets[:-1],offsets[1:])):
                            if np.any(arrays['report_symbol'][ids[start:end]] != sid) or np.any(np.diff(arrays[prefix + '_known'][start:end]) < 0) or np.any(np.diff(arrays[prefix + '_fiscal'][start:end]) < 0):
                                raise ValueError('Invalid report pool order.')
            resources.db = None
        finally:
            resources.close()
        return manifest

    def _busy(self, identity):
        leases = self.path / 'leases' / identity
        if not _plain(leases) or not _plain(leases.parent): return True
        for path in leases.iterdir() if leases.exists() else ():
            try:
                if not _plain(path): return True
                with path.open('r+b', buffering=0) as handle:
                    cache_access._file_lock(handle, True)
                    cache_access._file_lock(handle, False)
                path.unlink()
            except OSError: return True
        return False

    def _recover(self, checkpoint=lambda: None):
        # A process killed during export can leave only an owned staging tree.
        # Unknown directories and files are never candidates for this cleanup.
        for folder in self.path.glob('building-*'):
            suffix = folder.name.removeprefix('building-')
            if len(suffix) != 32 or any(c not in '0123456789abcdef' for c in suffix) or not _plain(folder): continue
            marker = folder / 'owner.json'
            if marker.is_file() and _read(marker) == {'format': FORMAT, 'owner': 'numerical-generation'}:
                shutil.rmtree(folder)
        journal = self.path / 'publication.json'
        if not journal.exists(): return
        value = _read(journal)
        if not isinstance(value, dict) or set(value) != {'candidate', 'prior'}:
            raise ValueError('Corrupt numerical publication journal.')
        candidate, prior = value['candidate'], value['prior']
        if not _valid_id(candidate): raise ValueError('Corrupt numerical publication journal.')
        if prior is not None and (not isinstance(prior, dict) or set(prior) != {'current','previous'} or not _valid_id(prior['current']) or prior['previous'] is not None and not _valid_id(prior['previous'])):
            raise ValueError('Corrupt prior numerical pointer.')
        current = self._pointer()
        target = dict(current=candidate, previous=(prior['previous'] if prior['current'] == candidate else prior['current']) if prior else None)
        if current not in (prior, target): raise ValueError('Conflicting numerical publication intent.')
        try:
            self._verify(candidate, checkpoint)
        except (ValueError, OSError, sqlite3.Error):
            if prior is None:
                if current is not None: raise ValueError('First numerical publication is corrupt.')
                journal.unlink(); return
            self._verify(prior['current'], checkpoint)
            cache_assets.write_json(self.path / 'current.json', prior)
            journal.unlink()
            return
        cache_assets.write_json(self.path / 'current.json', target)
        journal.unlink()

    @_cancellable
    def prepare(self, checkpoint=lambda: None):
        began = time.perf_counter()
        with self.coordinator.hold():
            self.path.mkdir(parents=True, exist_ok=True)
            self._recover(checkpoint)
            binding, policy = self._binding()
            prior = self._pointer()
            if prior:
                try: manifest = self._verify(prior['current'], checkpoint)
                except (ValueError, OSError, sqlite3.Error): manifest = None
                if manifest and manifest['binding'] == binding:
                    self._ensure_gate(manifest['identity'])
                    return dict(identity=manifest['identity'], reused=True, seconds=time.perf_counter()-began)
            staging = self.path / ('building-' + uuid.uuid4().hex)
            staging.mkdir()
            try:
                cache_assets.write_json(staging / 'owner.json', dict(format=FORMAT, owner='numerical-generation'))
                with closing(daily.connect()) as source:
                    source.execute('PRAGMA query_only=ON')
                    source.execute('PRAGMA cache_size=-2048')
                    source.execute('BEGIN')
                    arrays = _export(source, policy, staging, checkpoint)
                if self._binding()[0] != binding: raise ValueError('Prepared inputs changed during numerical export.')
                files = {p.name: dict(bytes=p.stat().st_size, sha256=_sha(p, checkpoint)) for p in staging.iterdir()}
                core = dict(format=FORMAT, binding=binding, arrays=arrays, files=files)
                identity = hashlib.sha256(_json(core)).hexdigest()
                manifest = dict(core, identity=identity)
                cache_assets.write_json(staging / 'manifest.json', manifest)
                self._verify(identity, checkpoint, folder=staging)
                self._ensure_gate(identity)
                target = self.path / identity
                if target.exists():
                    try: self._verify(identity, checkpoint)
                    except (ValueError, OSError, sqlite3.Error):
                        expected = {name + '.npy' for name in ARRAYS} | {'records.sqlite', 'owner.json', 'manifest.json'}
                        known = _plain(target) and all(_plain(path) and path.name in expected for path in target.iterdir())
                        marker = target / 'owner.json'
                        known = known and marker.exists() and _read(marker) == {'format': FORMAT, 'owner': 'numerical-generation'}
                        if not known:
                            raise ValueError('Damaged numerical generation is busy or unowned. Close readers before retry.')
                        try: gate = self._gate(identity, exclusive=True)
                        except (OSError, ValueError):
                            raise ValueError('Damaged numerical generation is busy or unowned. Close readers before retry.') from None
                        with gate:
                            if self._busy(identity):
                                raise ValueError('Damaged numerical generation is busy or unowned. Close readers before retry.')
                            _replace(target, self.path / ('damaged-' + identity + '-' + uuid.uuid4().hex), checkpoint)
                            _replace(staging, target, checkpoint)
                    else: shutil.rmtree(staging)
                else:
                    _replace(staging, target, checkpoint)
                self._verify(identity, checkpoint)
                checkpoint()
                cache_assets.write_json(self.path / 'publication.json', dict(candidate=identity, prior=prior))
                self._recover(checkpoint)
                return dict(identity=identity, reused=False, bytes=sum(f['bytes'] for f in files.values()),
                            seconds=time.perf_counter()-began)
            finally:
                if staging.exists(): shutil.rmtree(staging)

    def open_current(self):
        began = time.perf_counter()
        with self.coordinator.hold():
            self._recover()
            binding, policy = self._binding()
            pointer = self._pointer()
            if pointer is None: raise ValueError('Numerical inputs missing. Run: python3 scripts/numerical_generation.py prepare.')
            manifest = self._verify(pointer['current'])
            if manifest['binding'] != binding: raise ValueError('Numerical inputs stale. Run: python3 scripts/numerical_generation.py prepare.')
            if manifest['arrays']['financial_parameters']['shape'][1] != len(policy.parameter_names):
                raise ValueError('Numerical financial parameter width differs from source policy.')
            self._ensure_gate(pointer['current'])
            folder = self.path / 'leases' / pointer['current']
            if not _plain(folder) or not _plain(folder.parent): raise ValueError('Invalid reader lease directory.')
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / (uuid.uuid4().hex + '.lease')
            handle = path.open('x+b', buffering=0)
            try:
                handle.write(b'0'); cache_access._file_lock(handle, True)
                inputs = AttachedInputs(self.path / pointer['current'], manifest, policy, (path, handle))
            except BaseException as error:
                if not getattr(error, 'numerical_inputs', None):
                    handle.close(); path.unlink(missing_ok=True)
                raise
            inputs.stats['attachment_seconds'] = time.perf_counter() - began
            inputs._store = self
            return inputs

    def retire_unused(self):
        removed, retained = [], []
        with self.coordinator.hold():
            self._recover()
            pointer = self._pointer()
            keep = set(pointer.values()) if pointer else set()
            for folder in self.path.iterdir():
                if not _valid_id(folder.name) or not _plain(folder) or not folder.is_dir(): continue
                if folder.name in keep: continue
                self._ensure_gate(folder.name)
                try: gate = self._gate(folder.name, exclusive=True)
                except (OSError, ValueError): retained.append(folder.name); continue
                with gate:
                    self._verify(folder.name)
                    if self._busy(folder.name): retained.append(folder.name); continue
                    try: shutil.rmtree(folder)
                    except OSError: retained.append(folder.name)
                    else: removed.append(folder.name)
        return dict(removed=removed, retained=retained)

    def recover_previous(self):
        """Restore the verified prior pointer. Freshness is still required to attach.

        This explicit recovery never changes or deletes the damaged generation.
        A prior generation can be structurally valid and stale for current raw
        inputs. In that case attachment requires a new offline export.
        """
        with self.coordinator.hold():
            self._recover()
            pointer = self._pointer()
            if not pointer or not pointer['previous']:
                raise ValueError('No previous numerical generation is available.')
            self._verify(pointer['previous'])
            result = dict(current=pointer['previous'], previous=None)
            cache_assets.write_json(self.path / 'current.json', result)
            return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'attach', 'retire', 'recover'))
    args = parser.parse_args()
    store = GenerationStore()
    if args.command == 'prepare': result = store.prepare()
    elif args.command == 'retire': result = store.retire_unused()
    elif args.command == 'recover': result = store.recover_previous()
    else:
        with store.open_current() as inputs: result = dict(identity=inputs.signature, **inputs.stats)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__': main()
