"""Shared nonfinancial adapters for the analytical candidate experiments.

The expression walkers translate the source-bound PolicyProgram tree. They
contain no valuation or filter formulas. Temporal tables expose complete input
histories; the executors receive no preselected reports or calculated factors.
"""
from pathlib import Path
from datetime import date
import os
import tempfile

import numpy as np


def quote(name):
    return '"' + str(name).replace('"', '""') + '"'


def sql_expression(node, columns):
    """Lower one expanded arithmetic tree, preserving its operation nesting."""
    op = node[0]
    if op == 'input':
        try:
            return columns[node[1]]
        except KeyError:
            raise ValueError('Policy uses an unknown analytical input.') from None
    if op == 'const':
        value = float(node[1])
        # String-to-double casting preserves float64 constants, including NaN,
        # infinities and signed zero, without decimal-literal inference.
        return "CAST('" + repr(value) + "' AS DOUBLE)"
    if op == 'neg':
        return '(-(' + sql_expression(node[1], columns) + '))'
    if op in ('add', 'sub', 'mul', 'div'):
        operator = dict(add='+', sub='-', mul='*', div='/')[op]
        return '(' + sql_expression(node[1], columns) + operator + sql_expression(node[2], columns) + ')'
    if op == 'if':
        condition, yes, no = (sql_expression(part, columns) for part in node[1:])
        return '(CASE WHEN (' + condition + ')<>0 THEN ' + yes + ' ELSE ' + no + ' END)'
    raise ValueError('Unsupported analytical policy operation: ' + str(op))


def polars_expression(node, columns, pl, literals=None):
    """Lower the same arithmetic tree to Polars expressions without formulas."""
    op = node[0]
    if op == 'input':
        try:
            return columns[node[1]]
        except KeyError:
            raise ValueError('Policy uses an unknown analytical input.') from None
    if op == 'const':
        value = float(node[1])
        if literals is None:
            return pl.lit(value, dtype=pl.Float64)
        key = value.hex()
        if key not in literals:
            literals[key] = ('__policy_literal_' + str(len(literals)), value)
        return pl.col(literals[key][0])
    if op == 'neg':
        return -polars_expression(node[1], columns, pl, literals)
    if op in ('add', 'sub', 'mul', 'div'):
        left = polars_expression(node[1], columns, pl, literals)
        right = polars_expression(node[2], columns, pl, literals)
        if op == 'add':
            return left + right
        if op == 'sub':
            return left - right
        if op == 'mul':
            return left * right
        return left / right
    if op == 'if':
        condition, yes, no = (polars_expression(part, columns, pl, literals) for part in node[1:])
        return pl.when(condition != 0).then(yes).otherwise(no)
    raise ValueError('Unsupported analytical policy operation: ' + str(op))


def report_columns(inputs, pool):
    """Expose each complete pool with explicit stable row order for ties."""
    ids = np.asarray(inputs.pool_report_ids[pool], dtype=np.int64)
    return dict(
        sid=np.asarray(inputs.report_symbol[ids], dtype=np.int32),
        known=np.asarray(inputs.report_known[ids], dtype=np.int32),
        fiscal=np.asarray(inputs.report_fiscal[ids], dtype=np.int32),
        report_id=ids.astype(np.int32),
        position=np.arange(len(ids), dtype=np.int64),
    )


def price_columns(inputs, column):
    """Borrow sparse value/day buffers and add one compact symbol-ID column."""
    prefix = 'raw' if column == 0 else 'adjusted'
    offsets = np.asarray(getattr(inputs, prefix + '_offsets'))
    days = np.asarray(getattr(inputs, prefix + '_days'))
    values = np.asarray(getattr(inputs, prefix + '_values'))
    counts = np.diff(offsets)
    if len(offsets) != len(inputs.symbols) + 1 or offsets[0] != 0 or offsets[-1] != len(days):
        raise ValueError('Analytical price offsets do not match the attached input.')
    if np.any(counts < 0) or len(values) != len(days):
        raise ValueError('Analytical sparse histories have inconsistent shapes.')
    symbols = np.repeat(np.arange(len(inputs.symbols), dtype=np.int32), counts)
    return dict(sid=symbols, day=days, value=values)


def report_queries(days, symbol_count, max_rows):
    days = np.asarray(days)
    if days.ndim != 1 or not np.issubdtype(days.dtype, np.integer) or np.any(days < 1) or np.any(days > date.max.toordinal()):
        raise ValueError('Report queries require valid integer ordinal days.')
    days = days.astype(np.int32, copy=False)
    count = len(days) * symbol_count
    if count > max_rows:
        raise ValueError('Report query batch exceeds the declared analytical row limit.')
    return dict(
        query_id=np.arange(count, dtype=np.int64),
        sid=np.tile(np.arange(symbol_count, dtype=np.int32), len(days)),
        day=np.repeat(days, symbol_count),
    ), len(days)


def price_queries(symbols, days, columns, forwards, max_rows):
    values = [np.asarray(item) for item in (symbols, days, columns, forwards)]
    if any(value.ndim != 1 for value in values) or len({len(value) for value in values}) != 1:
        raise ValueError('Price query arrays must be one-dimensional and equally sized.')
    symbols, days, columns, forwards = values
    if len(days) > max_rows:
        raise ValueError('Price query batch exceeds the declared analytical row limit.')
    if not np.issubdtype(symbols.dtype, np.integer) or not np.issubdtype(days.dtype, np.integer):
        raise ValueError('Price symbols and days must be integer arrays.')
    if np.any(days < 1) or np.any(days > date.max.toordinal()) or np.any((columns != 0) & (columns != 1)):
        raise ValueError('Price query days or columns are invalid.')
    if not np.issubdtype(forwards.dtype, np.bool_):
        raise ValueError('Price directions must be a boolean array.')
    return dict(query_id=np.arange(len(days), dtype=np.int64),
                sid=np.asarray(symbols, dtype=np.int32),
                day=np.asarray(days, dtype=np.int32),
                column=np.asarray(columns, dtype=np.int8),
                forward=np.asarray(forwards, dtype=np.bool_))


def matrix_columns(matrix, names):
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != len(names):
        raise ValueError('Numerical matrix does not match the policy input columns.')
    return {name: matrix[:, number] for number, name in enumerate(names)}, len(matrix)


def work_root(inputs, limits, method):
    requested = limits.get('workdir')
    if requested is None:
        if os.name == 'nt':
            requested = Path(inputs.s.r.ROOT) / 'tmp/cb02-all-methods' / method
        else:
            requested = Path(tempfile.gettempdir()) / ('cb02-candidates-' + method)
    path = Path(requested).resolve()
    if os.name == 'nt' and not path.is_relative_to((Path(inputs.s.r.ROOT) / 'tmp').resolve()):
        raise ValueError('Native analytical temporary files must stay below runtime tmp/.')
    path.mkdir(parents=True, exist_ok=True)
    return path


def stage_stats(method, **extra):
    return dict(method=method, backend=method, report_batches=0, report_probe_rows=0,
                max_report_batch_days=0, price_batches=0, price_queries=0,
                max_price_queries=0, numeric_batches=0, numeric_rows=0,
                stage_coverage=dict(report_selection=method + ' multi-date ASOF',
                    price_resolution=method + ' multi-date ASOF',
                    numeric_policy=method + ' source-derived expressions',
                    buffer_ranking='shared stable scalar policy',
                    snapshot_guards='shared authoritative source control',
                    final_selection='shared production SQLite selector'), **extra)


def begin_stats(stats):
    """Clear request counters without discarding separately measured setup."""
    for key in ('report_batches', 'report_probe_rows', 'max_report_batch_days',
                'price_batches', 'price_queries', 'max_price_queries',
                'numeric_batches', 'numeric_rows'):
        stats[key] = 0
