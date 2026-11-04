"""Immutable numeric inputs for numerical engine tests.

`NumericInputs` loads source rows and contiguous sparse numeric histories once
from a caller-owned read-only daily database. `ArrayPrices` is its saved-price
lookup. Production owns complete-book evaluation; this module re-exports
`PythonExecutor`, `PolicyProgram` and `LOOKUP_FIELDS` for the tests.
"""
from pathlib import Path as _TestPath
import sys as _test_sys
_test_sys.path.insert(0, str(_TestPath(__file__).resolve().parents[1]))

from array import array
from bisect import bisect_left, bisect_right
from calendar import monthrange
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

from backtest.inputs import daily
from backtest.financial import rules, metrics
from backtest.engines.numerical.policy import PolicyProgram, FINANCIAL_FIELDS
from backtest.engines.numerical.generation import TEMPORAL_VERSION, DatedYields
from backtest.engines.numerical.books import PythonExecutor, RequestPlan, LOOKUP_FIELDS


MAX_ORDINAL = date.max.toordinal()


class ArrayPrices:
    """Stream saved rows into separate sparse raw and adjusted histories."""

    def __init__(self, readonly_sqlite_db):
        started = time.perf_counter()
        self._series = {}
        self._closed = False
        rows = raw_points = adjusted_points = 0
        # Optional price columns are treated as entirely missing. Required
        # symbol/day columns still cause SQLite to reject an invalid schema.
        cursor = readonly_sqlite_db.execute('PRAGMA table_info(prices)')
        try:
            columns = {row[1] for row in cursor}
        finally:
            cursor.close()
        raw = 'price' if 'price' in columns else 'NULL AS price'
        adjusted = 'adjusted' if 'adjusted' in columns else 'NULL AS adjusted'
        cursor = readonly_sqlite_db.execute(
            f'SELECT symbol,day,{raw},{adjusted} FROM prices ORDER BY symbol,day')
        current = None
        parts = None
        fromisoformat = date.fromisoformat
        isfinite = math.isfinite
        try:
            for symbol, day, price, adjusted in cursor:
                if symbol != current or parts is None:
                    if not isinstance(symbol, str) or not symbol:
                        raise ValueError('Saved price symbol must be a nonempty string.')
                    current = symbol
                    parts = (array('i'), array('d'), array('i'), array('d'))
                    self._series[symbol] = parts
                ordinal = fromisoformat(day).toordinal()
                if price is not None:
                    value = float(price)
                    if not isfinite(value):
                        raise ValueError('Saved raw price must be finite.')
                    parts[0].append(ordinal)
                    parts[1].append(value)
                    raw_points += 1
                if adjusted is not None:
                    value = float(adjusted)
                    if not isfinite(value):
                        raise ValueError('Saved adjusted price must be finite.')
                    parts[2].append(ordinal)
                    parts[3].append(value)
                    adjusted_points += 1
                rows += 1
        finally:
            cursor.close()
        payload_bytes = sum(len(a) * a.itemsize
                            for parts in self._series.values() for a in parts)
        # This includes array capacity and Python containers, not SQLite's
        # buffers, allocator fragmentation, or the process's peak resident set.
        allocated_bytes = sys.getsizeof(self._series) + sum(
            sys.getsizeof(symbol) + sys.getsizeof(parts)
            + sum(sys.getsizeof(a) for a in parts)
            for symbol, parts in self._series.items())
        self.stats = dict(
            load_seconds=time.perf_counter() - started,
            payload_bytes=payload_bytes,
            allocated_bytes=allocated_bytes,
            rows=rows,
            symbols=len(self._series),
            raw_points=raw_points,
            adjusted_points=adjusted_points,
            resolve_calls=0,
            queries=0,
        )

    def resolve(self, queries):
        """Return ordered nearest non-null prices; exact dates are included.

        Each query is ``(symbol, ordinal_day, 'price'|'adjusted', forward)``.
        Invalid queries raise ValueError. A missing symbol or empty column
        returns None. The shared benchmark adapter applies any date tolerance.
        """
        if self._closed:
            raise RuntimeError('Price resolver is closed.')
        answers = []
        histories = self._series
        for query in queries:
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
            parts = histories.get(symbol)
            if parts is None:
                answers.append(None)
                continue
            if column == 'price':
                days, values = parts[0], parts[1]
            else:
                days, values = parts[2], parts[3]
            index = (bisect_left(days, ordinal) if forward
                     else bisect_right(days, ordinal) - 1)
            answers.append((days[index], values[index])
                           if 0 <= index < len(days) else None)
        self.stats['resolve_calls'] += 1
        self.stats['queries'] += len(answers)
        return answers

    def close(self):
        """Release buffers; retain load statistics and the caller's connection."""
        self._series.clear()
        self._closed = True


def open_prices(readonly_sqlite_db):
    """Load a resolver from a caller-owned, read-only SQLite connection."""
    return ArrayPrices(readonly_sqlite_db)


class NumericInputs:
    """Load immutable source rows and contiguous sparse numeric histories once."""
    def __init__(self,source,schedules):
        began = time.perf_counter()
        self.closed = False
        self.temporal_version = TEMPORAL_VERSION
        self.s = schedules
        self.books = daily.histories(source)
        self.cached = daily.cached_symbols(source)
        self.histories = {symbol:[dict(row,fiscal=str(row['fiscal']),known=str(row['known']))
                                 for row in rows] for symbol,rows in self.books[0].items()}
        self.financials = {}
        for symbol,fiscal,values in source.execute('SELECT symbol,fiscal,values_json FROM financial_inputs'):
            self.financials.setdefault(symbol,{})[fiscal] = json.loads(values)
        self.companies = tuple(tuple(row) for row in source.execute('SELECT * FROM companies'))
        self.sessions = dict(source.execute('SELECT day,price FROM sessions ORDER BY day'))
        treasuries = list(source.execute('SELECT day,yield_value FROM treasuries ORDER BY day'))
        self.treasury_days = [row[0] for row in treasuries]
        self.treasury_values = [row[1] for row in treasuries]
        self.ten_year_yield = DatedYields(source.execute(
            'SELECT day,yield_percent FROM treasury10 ORDER BY day'))
        self.bankrupt = frozenset(rules.BANKRUPT)
        self.policy = PolicyProgram(bankrupt=self.bankrupt)
        prices = ArrayPrices(source)
        symbols = list(self.books[0])
        symbols.extend(symbol for symbol in prices._series if symbol not in self.books[0])
        self.symbols = tuple(symbols)
        self.symbol_ids = {symbol:i for i,symbol in enumerate(symbols)}
        self.cached_mask = np.array([symbol in self.cached for symbol in symbols],dtype=np.bool_)
        buffers = [array('q'),array('i'),array('d'),array('q'),array('i'),array('d')]
        for symbol in symbols:
            buffers[0].append(len(buffers[1]));buffers[3].append(len(buffers[4]))
            parts = prices._series.pop(symbol,None)
            if parts is not None:
                for target,part in zip((1,2,4,5),parts,strict=True):buffers[target].extend(part)
        buffers[0].append(len(buffers[1]));buffers[3].append(len(buffers[4]))
        price_stats = dict(prices.stats)
        prices.close()
        for name,buffer,dtype in zip(('raw_offsets','raw_days','raw_values',
                'adjusted_offsets','adjusted_days','adjusted_values'),buffers,
                (np.int64,np.int32,np.float64,np.int64,np.int32,np.float64),strict=True):
            setattr(self,name,np.frombuffer(buffer,dtype=dtype))
        if np.any(self.raw_values<=0) or np.any(self.adjusted_values<=0):
            raise ValueError('Prepared price inputs must be strictly positive.')
        rows = []
        report_symbol = []
        row_ids = {}
        for symbol,history in self.books[0].items():
            for row in history:
                row_ids[id(row)] = len(rows)
                rows.append(row);report_symbol.append(self.symbol_ids[symbol])
        self.report_rows = tuple(rows)
        self.report_symbol = np.asarray(report_symbol,dtype=np.int32)
        self.report_fiscal = np.asarray([row['fiscal'].toordinal() for row in rows],dtype=np.int32)
        self.report_known = np.asarray([row['known'].toordinal() for row in rows],dtype=np.int32)
        self.report_cap = np.asarray([row['market_cap'] for row in rows],dtype=np.float64)
        self.report_enterprise = np.asarray([row['enterprise'] for row in rows],dtype=np.float64)
        self.report_yield = np.asarray([row['yield'] for row in rows],dtype=np.float64)
        self.pool_offsets,self.pool_report_ids,self.pool_known,self.pool_fiscal = {},{},{},{}
        for pool,book in zip(('cached','legacy'),self.books,strict=True):
            offsets,identities = [0],[]
            for symbol in symbols:
                history = book.get(symbol,[])
                known = [row['known'].toordinal() for row in history]
                fiscal = [row['fiscal'].toordinal() for row in history]
                if known!=sorted(known) or fiscal!=sorted(fiscal):
                    raise ValueError('Prepared report histories must be temporally ordered.')
                identities.extend(row_ids[id(row)] for row in history)
                offsets.append(len(identities))
            self.pool_offsets[pool] = np.asarray(offsets,dtype=np.int64)
            self.pool_report_ids[pool] = np.asarray(identities,dtype=np.int32)
            self.pool_known[pool] = self.report_known[self.pool_report_ids[pool]]
            self.pool_fiscal[pool] = self.report_fiscal[self.pool_report_ids[pool]]
        report_setup = time.perf_counter()
        self.average_3y = np.full(len(rows),np.nan,dtype=np.float64)
        self.financial_parameters = np.full((len(rows),len(self.policy.parameter_names)),np.nan,dtype=np.float64)
        for index,row in enumerate(rows):
            symbol = symbols[int(self.report_symbol[index])]
            average = metrics.annual_average(self.histories[symbol],str(row['fiscal']),3)
            if average is not None:self.average_3y[index] = average
            self.financial_parameters[index] = self.policy.specialize_financial(
                str(row['fiscal']),self.financials.get(symbol,{}))
        generation = source.execute("SELECT value FROM metadata WHERE key='daily_inputs'").fetchone()
        self.generation = generation[0] if generation else None
        database = next((row[2] for row in source.execute('PRAGMA database_list') if row[1]=='main'),'')
        self.database_path = database
        signature = hashlib.sha256(json.dumps(dict(generation=self.generation,
            policy=self.policy.signature, symbols=symbols, companies=self.companies,
            sessions=self.sessions,treasury=list(zip(self.treasury_days,self.treasury_values)),
            treasury10=self.ten_year_yield.rows,
            bankruptcy=sorted(self.bankrupt)),
            sort_keys=True,separators=(',',':'),allow_nan=False).encode())
        numeric_bytes = 0
        for key,value in sorted(vars(self).items()):
            arrays = [(key,value)] if isinstance(value,np.ndarray) else (
                [(key+'.'+name,item) for name,item in sorted(value.items()) if isinstance(item,np.ndarray)]
                if isinstance(value,dict) else [])
            for name,item in arrays:
                signature.update(name.encode());signature.update(str(item.dtype).encode())
                signature.update(str(item.shape).encode())
                if item.size:signature.update(memoryview(item).cast('B'))
                numeric_bytes += item.nbytes
        self.signature = signature.hexdigest()
        self.stats = dict(load_seconds=time.perf_counter()-began,
            report_specialization_seconds=time.perf_counter()-report_setup,
            price_loading=price_stats, symbols=len(symbols),reports=len(rows),
            policy_sha256=self.policy.signature, input_identity=self.signature,
            numeric_payload_bytes=numeric_bytes)
        self._freeze()

    def _freeze(self):
        for value in vars(self).values():
            if isinstance(value,np.ndarray):value.flags.writeable=False
            if isinstance(value,dict):
                for item in value.values():
                    if isinstance(item,np.ndarray):item.flags.writeable=False

    def close(self):
        """Release owned numeric arrays; leave the caller's connection open."""
        for key,value in list(vars(self).items()):
            if isinstance(value,np.ndarray):setattr(self,key,np.empty(0))
        self.pool_offsets.clear();self.pool_report_ids.clear()
        self.pool_known.clear();self.pool_fiscal.clear()
        self.closed = True
