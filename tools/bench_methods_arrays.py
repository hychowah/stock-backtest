"""Benchmark-only sparse saved-price lookup using primitive arrays and bisect.

The caller owns the read-only SQLite connection. This module reads only its
``prices`` table and never changes financial policy or applies date tolerance.
It has no dependency on the checkout location or the current working folder.
"""
from array import array
from bisect import bisect_left, bisect_right
from datetime import date
import math
import sys
import time


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
