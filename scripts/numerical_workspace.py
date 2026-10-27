"""Private SQL staging shared by offline complete-book diagnostics."""

DERIVED = ('period_pools', 'filter_values', 'screening_metrics', 'snapshots',
           'latest_snapshots', 'baseline_prices', 'baseline_periods', 'periods')


def stage_book(db, book, pool, *, ranking_metric=None, staged_rows=None):
    """Replace one complete book. Optionally stage only the requested pair.

    This retains the historical runner's staging behavior. The caller owns the
    private database and its transaction. No application cache is discovered.
    """
    for table in DERIVED:
        db.execute('DELETE FROM ' + table)
    db.execute('INSERT INTO periods VALUES(?,?,?,?,?,?,?)', (1, *book['period']))
    snapshots = db.executemany('INSERT INTO snapshots VALUES(' + ','.join('?' * 15) + ')',
                               ((pool, 1, *row) for row in book['snapshots']))
    metrics = db.executemany('INSERT INTO screening_metrics VALUES(?,?,?,?,?,?,?)',
        (('historical', pool, 1, symbol, metric, multiple, score)
         for symbol, metric, multiple, score in book['metrics']
         if ranking_metric is None or metric == ranking_metric))
    filters = db.executemany('INSERT INTO filter_values VALUES(?,?,?,?,?,?)',
                             (('historical', pool, 1, *row) for row in book['filters']))
    if staged_rows is not None:
        for name, cursor in (('snapshots', snapshots), ('screening_metrics', metrics),
                             ('filter_values', filters)):
            staged_rows[name] += cursor.rowcount
    return 1
