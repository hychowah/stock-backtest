"""Immutable numerical inputs, exported offline from validated prepared tables.

The store owns publication, recovery, mappings and reader leases. An attachment
borrows no source database handles. Callers retain ordinary cache ownership
during calculation and close evaluators before closing their input attachment.
No application routing, downloads or reference-report writes occur here.
"""
from collections.abc import Mapping, Sequence
from contextlib import closing
from datetime import date
from functools import wraps
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import uuid

# The standalone command owns source before financial or native imports. A
# library caller (server or worker) owns source for its complete lifetime.
if __name__ == '__main__':
    import atexit
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'website'))
    from runtime_access import ownership
    _source_owner = ownership(Path(__file__).resolve().parents[1])
    _source_owner.__enter__()
    atexit.register(_source_owner.__exit__, None, None, None)

import numpy as np

import cache_access
import cache_assets
from numerical_policy import PolicyProgram
from paths import ROOT

FORMAT = 1
STORE = ROOT / 'data' / 'numerical'
CHUNK = 4096
MAX_MANIFEST = 4 * 1024 * 1024
MAX_HISTORY = 16384
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


def _export(source, schedules, policy, folder, checkpoint):
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
    ''')
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
        cached = schedules.cached_symbols(source)
        db.executemany('INSERT INTO symbols VALUES(?,?,?)',
                       ((i, symbol, int(symbol in cached)) for i, symbol in enumerate(symbols)))
        for table in ('companies', 'financial_inputs', 'sessions', 'treasuries'):
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
            broad, legacy = schedules.financial_books.pools({symbol: history})
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
                average = schedules.metrics.annual_average(textual, str(row['fiscal']), 3)
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


class AttachedInputs:
    """Owned read-only mappings and lazy records. Views expire at close.

    Close all evaluators and borrowed NumPy views first. Failed close preserves
    the lease and remaining handles so the caller can retry explicitly.
    """
    def __init__(self, folder, manifest, schedules, policy, lease=None):
        self._arrays, self._db, self._lease = {}, None, lease
        self.closed = False
        self.s, self.policy = schedules, policy
        self.signature = manifest['identity']
        self._binding = manifest['binding']
        self.generation = json.dumps(manifest['binding']['daily'])
        self.database_path = str(folder / 'records.sqlite')
        self.bankrupt = frozenset(schedules.r.revalue.BANKRUPT)
        _attachments[id(self)] = self
        try:
            for name in ARRAYS:
                self._arrays[name] = np.load(folder / (name + '.npy'), mmap_mode='r', allow_pickle=False)
                setattr(self, name, self._arrays[name])
            self._db = _readonly(folder / 'records.sqlite')
            self.symbols = tuple(row[0] for row in self._db.execute('SELECT symbol FROM symbols ORDER BY id'))
            self.symbol_ids = {symbol: i for i, symbol in enumerate(self.symbols)}
            self.cached = frozenset(row[0] for row in self._db.execute('SELECT symbol FROM symbols WHERE cached=1'))
            self.sessions = dict(self._db.execute('SELECT day,price FROM sessions ORDER BY day'))
            treasury = list(self._db.execute('SELECT day,yield_value FROM treasuries ORDER BY day'))
            self.treasury_days, self.treasury_values = [r[0] for r in treasury], [r[1] for r in treasury]
            for field in ('offsets', 'report_ids', 'known', 'fiscal'):
                setattr(self, 'pool_' + field, {pool: self._arrays[pool + '_' + field] for pool in ('cached', 'legacy')})
            self.report_rows, self.histories, self.financials = _Reports(self), _Records(self, 'histories'), _Records(self, 'financials')
            self.stats = dict(numeric_payload_bytes=sum(a.nbytes for a in self._arrays.values()),
                              symbols=len(self.symbols), reports=len(self.report_fiscal))
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

    def close(self):
        if self.closed: return
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
        self.closed = True
        _attachments.pop(id(self), None)

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class GenerationStore:
    """Publish immutable base inputs; never bind identity to mutable saved books.

    The coordinator is acquired before source connections, mappings and leases.
    Long-lived idle attachments retain only their generation lease. Jobs still
    use ordinary project ownership through calculation and resource closure.
    """
    def __init__(self, schedules, path=STORE, coordinator=None):
        self.s, self.path = schedules, Path(path)
        if any(not _plain(part) for part in (self.path, *self.path.parents)):
            raise ValueError('Numerical store paths cannot use links or junctions.')
        self.coordinator = coordinator or cache_access.workspace

    def _binding(self):
        s = self.s
        for name in ('deployment.pending.json', 'research.sqlite.publication.json'):
            if (s.r.ROOT / 'data' / name).exists():
                raise ValueError('Unfinished publication blocks numerical inputs. Retry preparation.')
        with closing(s.r.connect(full_prices=True)):
            pass
        with closing(s.connect()) as db:
            daily = json.loads(db.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()[0])
        policy = PolicyProgram(s, bankrupt=s.r.revalue.BANKRUPT)
        source = {p.name: _sha(p) for p in policy.source_paths}
        for name in ('numerical_generation.py', 'numerical_policy.py', 'numerical_decisions.py'):
            source[name] = _sha(Path(__file__).with_name(name))
        return dict(daily=daily, prices=s.r.price_sources(), report=_sha(s.r.RESULTS / 'summary-exits.txt'),
                    policy=policy.signature, sources=source), policy

    def _pointer(self):
        path = self.path / 'current.json'
        if not path.exists(): return None
        value = _read(path)
        if not isinstance(value, dict) or set(value) != {'current', 'previous'} or not _valid_id(value['current']) or (
                value['previous'] is not None and not _valid_id(value['previous'])):
            raise ValueError('Corrupt numerical generation pointer.')
        return value

    def _verify(self, identity, checkpoint=lambda: None, *, folder=None):
        if not _valid_id(identity): raise ValueError('Invalid numerical generation identity.')
        folder = folder or self.path / identity
        if not _plain(folder): raise ValueError('Invalid generation directory.')
        manifest = _read(folder / 'manifest.json')
        if not isinstance(manifest, dict) or set(manifest) != {'format', 'binding', 'arrays', 'files', 'identity'}:
            raise ValueError('Malformed numerical manifest.')
        if not isinstance(manifest['binding'], dict) or not isinstance(manifest['arrays'], dict) or not isinstance(manifest['files'], dict):
            raise ValueError('Malformed numerical manifest fields.')
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
        arrays = {}
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
            with closing(_readonly(folder / 'records.sqlite')) as db:
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
        finally:
            for array in arrays.values(): array._mmap.close()
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
                    return dict(identity=manifest['identity'], reused=True, seconds=time.perf_counter()-began)
            staging = self.path / ('building-' + uuid.uuid4().hex)
            staging.mkdir()
            try:
                cache_assets.write_json(staging / 'owner.json', dict(format=FORMAT, owner='numerical-generation'))
                with closing(self.s.connect()) as source:
                    source.execute('PRAGMA query_only=ON')
                    source.execute('PRAGMA cache_size=-2048')
                    source.execute('BEGIN')
                    arrays = _export(source, self.s, policy, staging, checkpoint)
                if self._binding()[0] != binding: raise ValueError('Prepared inputs changed during numerical export.')
                files = {p.name: dict(bytes=p.stat().st_size, sha256=_sha(p, checkpoint)) for p in staging.iterdir()}
                core = dict(format=FORMAT, binding=binding, arrays=arrays, files=files)
                identity = hashlib.sha256(_json(core)).hexdigest()
                manifest = dict(core, identity=identity)
                cache_assets.write_json(staging / 'manifest.json', manifest)
                self._verify(identity, checkpoint, folder=staging)
                target = self.path / identity
                if target.exists():
                    try: self._verify(identity, checkpoint)
                    except (ValueError, OSError, sqlite3.Error):
                        expected = {name + '.npy' for name in ARRAYS} | {'records.sqlite', 'owner.json', 'manifest.json'}
                        known = _plain(target) and all(_plain(path) and path.name in expected for path in target.iterdir())
                        marker = target / 'owner.json'
                        known = known and marker.exists() and _read(marker) == {'format': FORMAT, 'owner': 'numerical-generation'}
                        if not known or self._busy(identity):
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
            if pointer is None: raise ValueError('Numerical inputs missing. Run numerical_generation.py prepare.')
            manifest = self._verify(pointer['current'])
            if manifest['binding'] != binding: raise ValueError('Numerical inputs stale. Run numerical_generation.py prepare.')
            if manifest['arrays']['financial_parameters']['shape'][1] != len(policy.parameter_names):
                raise ValueError('Numerical financial parameter width differs from source policy.')
            folder = self.path / 'leases' / pointer['current']
            if not _plain(folder) or not _plain(folder.parent): raise ValueError('Invalid reader lease directory.')
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / (uuid.uuid4().hex + '.lease')
            handle = path.open('x+b', buffering=0)
            try:
                handle.write(b'0'); cache_access._file_lock(handle, True)
                inputs = AttachedInputs(self.path / pointer['current'], manifest, self.s, policy, (path, handle))
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
    import schedules
    store = GenerationStore(schedules)
    if args.command == 'prepare': result = store.prepare()
    elif args.command == 'retire': result = store.retire_unused()
    elif args.command == 'recover': result = store.recover_previous()
    else:
        with store.open_current() as inputs: result = dict(identity=inputs.signature, **inputs.stats)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__': main()
