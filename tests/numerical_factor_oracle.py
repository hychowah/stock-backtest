"""Test oracle: entry factors from one source-derived catalog over borrowed inputs.

Production evaluates complete books with NumbaExecutor. Tests use this Python
evaluation over the same TemporalEvaluator and CompiledMatrix to check policy
semantics such as missing inputs, rounding and calendar tolerances.

Callers retain source/cache ownership and validate freshness before each job.
There are no exit decisions, selection rules, SQL writes or durable caches here.
"""
from collections import OrderedDict
from dataclasses import dataclass, fields
from datetime import date
import hashlib
import json
import sys
from types import MappingProxyType

import numpy as np
from backtest.engines.numerical.temporal import TemporalEvaluator
import numba
from numba import njit, prange

from backtest.engines.numerical.policy import FACTOR_VERSION


from backtest.engines.numerical.matrix import compile_matrix, CompiledMatrix


def _immutable(value):
    value = np.asarray(value)
    # A bytes owner prevents callers from enabling writes on returned arrays.
    return np.frombuffer(value.tobytes(), dtype=value.dtype).reshape(value.shape)


def _size(value, seen=None):
    """Conservative retained Python/buffer bytes, including index metadata."""
    seen = set() if seen is None else seen
    if id(value) in seen: return 0
    seen.add(id(value))
    total = sys.getsizeof(value)
    if isinstance(value, np.ndarray):
        total += _size(value.base, seen) if value.base is not None else 0
    elif isinstance(value, EntryFactors):
        total += _size(vars(value), seen)
    elif isinstance(value, (dict, MappingProxyType)):
        if isinstance(value, MappingProxyType): total += sys.getsizeof(dict(value))
        total += sum(_size(k, seen) + _size(v, seen) for k, v in value.items())
    elif isinstance(value, (tuple, list)):
        total += sum(_size(v, seen) for v in value)
    return total


@dataclass(frozen=True)
class EntryFactors:
    """Detached values in original symbol order, with independent validity.

    Valuation columns are market cap, enterprise value and EBITDA in USD.
    Ranking columns are multiple and yield. Thresholds use catalog display units.
    An invalid value is NaN; validity is authoritative. No optional missing
    field excludes a row. Results survive evaluator and input closure.
    """
    entry: int
    pool: str
    identity: str
    schema: str
    symbols: np.ndarray
    reports: np.ndarray
    valuation: np.ndarray
    valuation_valid: np.ndarray
    pairs: object
    pair_valid: object
    thresholds: object
    threshold_valid: object

    @property
    def payload_bytes(self):
        arrays = (self.symbols, self.reports, self.valuation, self.valuation_valid,
                  *self.pairs.values(), *self.pair_valid.values(),
                  *self.thresholds.values(), *self.threshold_valid.values())
        return sum(a.nbytes for a in arrays)

    def detached(self):
        values = {}
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, np.ndarray): value = _immutable(value)
            elif isinstance(value, MappingProxyType):
                value = MappingProxyType({k: _immutable(v) for k, v in value.items()})
            values[field.name] = value
        return EntryFactors(**values)


class FactorEvaluator:
    """Borrow an attachment; own temporal evaluation, compilation and LRU reuse.

    Results are detached from mappings and retained cache storage. The cache
    budget includes retained buffers and indexing metadata; it is not a process
    memory cap. Caller-held results consume additional memory. Calculation
    requests have a separate conservative workspace bound. Close before inputs.
    """
    def __init__(self, inputs, *, cache_bytes=16*1024**2, max_batch_bytes=64*1024**2):
        if (type(cache_bytes) is not int or cache_bytes < 0 or
                type(max_batch_bytes) is not int or max_batch_bytes <= 0):
            raise ValueError('Invalid factor memory budget.')
        if (getattr(inputs, 'closed', False) or
                type(getattr(inputs, 'factor_version', None)) is not int or
                inputs.factor_version != FACTOR_VERSION or
                getattr(inputs, 'field_schema', None) != inputs.policy.field_schema):
            raise ValueError('Closed or incompatible factor inputs.')
        self.inputs, self.policy = inputs, inputs.policy
        self.closed = False
        self.temporal = TemporalEvaluator(inputs)
        self.outputs = self.policy.projection(('cap', 'ev', 'ebitda',
            *(name for pair in self.policy.ranking_outputs.values() for name in pair),
            *('filter_' + name for name in self.policy.fields['thresholds'])))
        self.index = {name: i for i, name in enumerate(self.outputs)}
        self.catalog = json.dumps(self.policy.fields, sort_keys=True, separators=(',', ':'))
        self.execution = dict(numba=numba.__version__, numpy=np.__version__,
            threads=numba.get_num_threads(), fastmath=False, compiler_cache=False)
        self.identity = hashlib.sha256(json.dumps(dict(generation=inputs.signature,
            policy=self.policy.signature, schema=inputs.field_schema, factor=FACTOR_VERSION,
            temporal=inputs.temporal_version, execution=self.execution), sort_keys=True).encode()).hexdigest()
        self.cache_limit, self.max_batch_bytes = cache_bytes, max_batch_bytes
        self._cache = OrderedDict()
        self.stats = dict(hits=0, misses=0, retained_bytes=0, retained_entries=0,
                          peak_workspace_bound=0, returned_payload_bytes=0)
        try: self._calculate = CompiledMatrix(self.policy, self.identity, self.outputs,
                cache_bytes=0, workspace_bytes=max_batch_bytes)
        except BaseException:
            self.close()
            raise

    def _open(self):
        if self.closed or getattr(self.inputs, 'closed', False):
            raise ValueError('Factor evaluator or attachment is closed.')

    def _requirements(self, threshold_fields):
        known = self.policy.fields['thresholds']
        if threshold_fields is None: return tuple(known)
        if not isinstance(threshold_fields, (list, tuple, set, frozenset)):
            raise ValueError('Invalid threshold field collection.')
        if any(not isinstance(f, str) or f not in known for f in threshold_fields):
            raise ValueError('Unknown threshold field.')
        return tuple(f for f in known if f in threshold_fields)

    def evaluate(self, entry_days, pool='cached', threshold_fields=None):
        """Return one batch per entry, retaining order and duplicate requests.

        None requests all thresholds; an empty collection requests ranking pairs
        only. Both pairs are always present. Invalid requests fail before native
        indexing. No factor request observes an exit or future return.
        """
        self._open()
        if pool not in ('cached', 'legacy'): raise ValueError('Unknown factor pool.')
        required = self._requirements(threshold_fields)
        entries = self.temporal._integers(entry_days, 'entry days', 1, date.max.toordinal(), np.int32)
        if {'return_1y', 'return_3y'} & set(required):
            for entry in entries:
                self.policy.trailing(date.fromordinal(int(entry)), lambda *args: None)
        # Bounds cover result copies, numeric matrices, lookup vectors, masks,
        # report selection and per-row Python planning. They are conservative
        # workload accounting, not an allocator or total-residency guarantee.
        per_row = 4096 + 32*(len(self.policy.input_names) + len(self.outputs) + len(required))
        estimate = len(entries)*(4096 + max(1, len(self.inputs.symbols))*per_row)
        if estimate > self.max_batch_bytes: raise ValueError('Factor batch exceeds its workspace bound.')
        self.stats['peak_workspace_bound'] = max(self.stats['peak_workspace_bound'], estimate)
        result = []
        for entry in entries:
            key = (self.identity, int(entry), pool, required)
            if key in self._cache:
                batch = self._cache.pop(key); self._cache[key] = batch
                self.stats['hits'] += 1
            else:
                batch = self._entry(int(entry), pool, required)
                self.stats['misses'] += 1
                if _size(OrderedDict([(key, batch)])) <= self.cache_limit:
                    self._cache[key] = batch
                    while self._retained() > self.cache_limit: self._cache.popitem(last=False)
            result.append(batch.detached())
        self.stats.update(retained_bytes=self._retained(), retained_entries=len(self._cache),
                          returned_payload_bytes=sum(b.payload_bytes for b in result))
        return result

    def _retained(self):
        return _size(self._cache) if self._cache else 0

    def _entry(self, entry, pool, required):
        inputs, policy = self.inputs, self.policy
        selected = self.temporal.select_reports(np.array([entry], dtype=np.int32))[int(pool == 'legacy')][0]
        symbols = np.flatnonzero(selected >= 0).astype(np.int32)
        reports = selected[symbols].copy()
        day = date.fromordinal(entry)
        matrix = np.full((len(symbols), len(policy.input_names)), np.nan, dtype=np.float64)
        ii = policy.input_index
        for name, values in (('report_cap', inputs.report_cap), ('report_enterprise', inputs.report_enterprise),
                             ('report_yield', inputs.report_yield), ('average_3y', inputs.average_3y)):
            matrix[:, ii[name]] = values[reports]
        matrix[:, len(ii)-len(policy.parameter_names):] = inputs.financial_parameters[reports]
        treasury10 = inputs.ten_year_yield(day)
        matrix[:, ii['treasury10']] = np.nan if treasury10 is None else treasury10
        dependencies = policy.dependencies(tuple('filter_' + f for f in required))
        trailing_needed = dependencies & {'screen_adjusted', 'trailing_1y', 'trailing_3y'}
        queries, locations, row_specs = [], [], []
        for row, (symbol, report) in enumerate(zip(symbols, reports, strict=True)):
            specs = []
            def record(target, column, forward, slack):
                specs.append((target, column, forward, slack))
                return None
            statement = inputs.report_rows[int(report)]
            policy._entry(statement, day, record, {})
            if len(specs) != 2: raise ValueError('Unsupported entry lookup plan.')
            names = ['fiscal_raw', 'raw_entry']
            if trailing_needed:
                policy.trailing(day, record)
                names += ['screen_adjusted', 'trailing_1y', 'trailing_3y']
                if len(specs) != 5: raise ValueError('Unsupported trailing lookup plan.')
            row_specs.append(specs)
            for slot, (name, spec) in enumerate(zip(names, specs, strict=True)):
                if slot >= 2 and name not in trailing_needed: continue
                target, column, forward, slack = spec
                if target.year < 1: raise ValueError('Invalid trailing date.')
                queries.append((int(symbol), target.toordinal(), int(column == 'adjusted'), forward))
                locations.append((row, slot, name))
        resolved = [{} for _ in symbols]
        if queries:
            ss, dd, cc, ff = zip(*queries, strict=True)
            actual, values = self.temporal.resolve(ss, dd, cc, ff)
            for (row, slot, name), actual_day, value in zip(locations, actual, values, strict=True):
                target, column, forward, slack = row_specs[row][slot]
                available = actual_day != 0 and abs(int(actual_day)-target.toordinal()) <= slack
                resolved[row][(target, column, forward)] = (date.fromordinal(int(actual_day)), float(value)) if available else None
                if available: matrix[row, ii[name]] = value
        numeric = self._calculate(matrix)
        valid = np.zeros(len(symbols), dtype=np.bool_)
        trailing_valid = []
        for row, report in enumerate(reports):
            def lookup(target, column, forward=False, slack=None):
                value = resolved[row].get((target, column, forward))
                return value if value is not None and (slack is None or abs((value[0]-target).days) <= slack) else None
            values = {name: float(numeric[row, i]) for name, i in self.index.items()}
            valid[row] = bool(policy._entry(inputs.report_rows[int(report)], day, lookup, values))
            trailing_valid.append(policy.trailing(day, lookup) if trailing_needed else {})
        valuation = numeric[:, [self.index[name] for name in ('cap', 'ev', 'ebitda')]].copy()
        valuation[~valid] = np.nan
        pairs, pair_valid, thresholds, threshold_valid = {}, {}, {}, {}
        for metric, spec in policy.fields['metrics'].items():
            names = spec['outputs']
            values = numeric[:, [self.index[name] for name in names]].copy()
            available = valid.copy()
            if spec['validity'] == 'average_3y':
                available &= ~np.isnan(inputs.average_3y[reports]) & (inputs.average_3y[reports] > 0)
            values[~available] = np.nan
            pairs[metric], pair_valid[metric] = _immutable(values), _immutable(available)
        for name in required:
            values = numeric[:, self.index['filter_' + name]].copy()
            available = valid.copy()
            rule = policy.fields['thresholds'][name]['validity']
            if rule == 'finite': available &= np.isfinite(values)
            elif rule == 'pair': available &= pair_valid[name]
            elif rule == 'trailing':
                available &= np.array([name in fields for fields in trailing_valid], dtype=np.bool_)
            values[~available] = np.nan
            thresholds[name], threshold_valid[name] = _immutable(values), _immutable(available)
        identity = hashlib.sha256(json.dumps([self.identity, entry, pool, required]).encode()).hexdigest()
        return EntryFactors(entry, pool, identity, inputs.field_schema, _immutable(symbols), _immutable(reports),
            _immutable(valuation), _immutable(valid), MappingProxyType(pairs), MappingProxyType(pair_valid),
            MappingProxyType(thresholds), MappingProxyType(threshold_valid))

    def close(self):
        if getattr(self, 'closed', True): return
        self._cache.clear()
        self.stats.update(retained_bytes=0, retained_entries=0)
        self.temporal.close()
        if getattr(self, '_calculate', None) is not None: self._calculate.close()
        self.inputs = self.policy = self._calculate = None
        self.closed = True

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, *args): self.close()
