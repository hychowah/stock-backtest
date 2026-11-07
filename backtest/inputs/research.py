"""Offline research database: companies, reports, typed facts and the one research record.

It holds no book: the book store of the daily cache (backtest/inputs/book_store.py)
holds the latest and dated books, computed from these facts.

Every preparation is a full build. It writes a temporary file and replaces the
published database atomically (cache_assets.replace); the previous database
stays on any failure.

The metadata table is the one research record: the schema version, the
accepted raw-file signature (inputs) with each price file's stamps (prices),
the identity: version, latest date, the content identity of the fact-row code
(code) and the content identity of the facts (content), and the fact diff of
the build (changes()). Readers compare the stamps and the code (identity()).
Both identities are content digests, so a rewrite with equal bytes keeps them.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
from datetime import date
import json
import os
import stat
from pathlib import Path
import sqlite3
import time

from backtest.financial import rules
from backtest.inputs import market, cache_assets
from backtest.financial import metrics as metrics
from backtest.financial import books as books
from backtest.inputs import financial_inputs as financial_inputs
from backtest.inputs import book_store, facts
from backtest.runtime import backtest_control
from backtest.runtime import diagnostics
from backtest.runtime import cache_access as cache_access
from backtest.paths import ROOT, RAW

DATABASE = ROOT / 'data' / 'research.sqlite'
SCHEMA_VERSION = 19
# The annual statements; the typed facts are facts.SCHEMA.
SCHEMA = '''
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE statements (symbol TEXT, fiscal TEXT, known TEXT, market_cap REAL, enterprise_value REAL, ebitda REAL, ebitda_yield REAL, PRIMARY KEY(symbol,fiscal));
'''


def _metadata_entries(directory, pattern):
    """Return fresh metadata for the same paths selected by the inventory glob.

    Preserve platform matching, link traversal and discovery errors. Results
    are ordered and own no open directory handles. No metadata survives this
    invocation. Only the existing one- and two-level patterns are used.
    """
    paths = sorted(directory.glob(pattern))
    parents = {}
    for path in paths:
        parents.setdefault(str(path.parent), set()).add(path.name)
    discovered = {}
    for parent, names in parents.items():
        try:
            with os.scandir(parent) as entries:
                selected = {str(Path(parent) / entry.name): entry for entry in entries if entry.name in names}
        except OSError:
            # Enumeration is an optimization, not an additional permission
            # requirement. Path.stat retains the original metadata failures.
            selected = {}
        discovered.update(selected)
    # Exact spelling also preserves distinct names in case-sensitive Windows
    # directories. Evaluate metadata in the original sorted-path order.
    return [(path, discovered[str(path)].stat() if str(path) in discovered else path.stat())
            for path in paths]


_accepted = {}


def accepted_signature():
    """Return the raw-input signature that ordinary readers compare against.

    signature() inspects about 36,000 files on the real cache. Readers reuse
    the value taken at startup, by preparation and after each data-panel
    action, so a hand edit to raw/ needs a data-panel check before readers see it.
    """
    key = str(RAW), str(ROOT)
    if key not in _accepted:
        _accepted.clear(); _accepted[key] = signature()
    return _accepted[key]


def forget_signature():
    """Make the next reader inspect raw inputs again."""
    _accepted.clear()


def signature():
    """Return the current ordered input signature.

    Every call discovers and inspects inputs afresh. Keys preserve lexical
    paths relative to ROOT; discovery and metadata failures retain their
    existing precedence. No inventory or derived prefix survives the call.
    raw/download-coverage.json is not an input: no preparation reads it. Code
    is not in the signature: identity() compares the fact-row code by content.
    """
    paths = [RAW/n for n in ['universe.json','metrics.jsonl','spy-div.json','treasury.json']] + [RAW/'px']
    entries = [(path, path.stat()) for path in paths]
    financial = _metadata_entries(RAW/'financial-inputs', '*/*.json')
    result = {p.relative_to(ROOT).as_posix(): ['directory' if stat.S_ISDIR(info.st_mode) else info.st_size,info.st_mtime_ns] for p,info in entries}
    prefixes = {}
    for path, info in financial:
        parent = path.parent
        # Exact spelling keeps case-distinct native directories distinct.
        spelling = str(parent)
        if spelling not in prefixes:
            try:
                relative = parent.relative_to(ROOT).as_posix()
            except ValueError:
                # Preserve the original full-path result or exception.
                key = path.relative_to(ROOT).as_posix()
            else:
                prefixes[spelling] = '' if relative == '.' else relative + '/'
                key = prefixes[spelling] + path.name
        else:
            key = prefixes[spelling] + path.name
        result[key] = ['directory' if stat.S_ISDIR(info.st_mode) else info.st_size,info.st_mtime_ns]
    return result


def price_sources():
    return {p.name: [info.st_size,info.st_mtime_ns] for p,info in _metadata_entries(RAW/'px', '*.json')}


def code_sources(role):
    """The source files whose content forms one identity: the one rule of code roles.

    Each identity binds only the files that hold its role's code, by content
    (sha256), so a rewrite with equal bytes keeps it.
    - 'facts', the research identity: the fact-row code that parses saved
      files into research rows. research.prepare; facts.resolve, observe and
      the store_* writers; books.statements; financial_inputs with its
      parameter catalog; the parsing parts of cache_assets; market and rules.
    - 'books', the book identity that the daily binding names: the code that
      computes and stores books. books.py, metrics.py, rules.py,
      facts.BookFacts and book_store (its schema, writer and readers).
      code_identity also names the legacy annual field list that
      BookFacts.legacy_annual reads (facts.LEGACY): fact-row code defines it.
    A file that holds code of both roles is in both lists. Readers bind no
    identity: fact_view (View and its recorder), schedules, book_batch,
    calendar, portfolio_results, screening, scalar_execution, the CLI and
    connection code (daily.py among them). An edit to a reader neither
    rebuilds research nor drops a book. The reference engine and the
    development check (backtest/engines/reference) are never bound.
    """
    if role == 'facts':
        return [Path(__file__)] + [Path(module.__file__) for module in (
            facts, books, rules, financial_inputs, financial_inputs.parameters, cache_assets, market)]
    if role == 'books':
        return [Path(module.__file__) for module in (books, metrics, rules, facts, book_store)]
    raise ValueError('Unknown code role.')


def code_identity(role):
    """The content identity of one code role: the digest of its files' names and sha256s (code_sources).

    The book identity also digests facts.LEGACY, so an edit to the legacy field
    list in financial_inputs or the catalog drops every book.
    """
    digests = [[path.name, hashlib.sha256(path.read_bytes()).hexdigest()] for path in code_sources(role)]
    if role == 'books':
        digests.append(['facts.LEGACY', facts.LEGACY])
    return hashlib.sha256(json.dumps(digests, separators=(',', ':')).encode()).hexdigest()


def identity(db, schema='main', *, prices=False):
    """The identity of one research record, after the readers' freshness check.

    schema is 'main' on a research connection and 'research' on a daily
    connection that attaches it. The record must have this schema version,
    the accepted raw-file signature, the current fact-row code and, when
    prices is set, each saved price file's current stamps. A stale record
    raises ValueError.
    """
    keys = ('version', 'inputs', 'identity') + (('prices',) if prices else ())
    meta = {key: json.loads(value) for key, value in db.execute(
        f'SELECT key,value FROM {schema}.metadata WHERE key IN ({",".join("?" * len(keys))})', keys)}
    if meta.get('version') != SCHEMA_VERSION:
        raise ValueError('Database version changed; run research.py prepare')
    if (meta.get('inputs') != accepted_signature() or (prices and meta.get('prices') != price_sources())
            or not isinstance(meta.get('identity'), dict) or meta['identity'].get('code') != code_identity('facts')):
        raise ValueError('Cached inputs changed. Run: python3 scripts/research.py prepare')
    return meta['identity']


def connect(path=DATABASE, full_prices=False):
    """Open a read-only research connection whose record passes identity()."""
    path=Path(path)
    if not path.exists():
        raise ValueError('Prepared database missing. Run: python3 scripts/research.py prepare')
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    try:
        identity(db,prices=full_prices)
    except Exception:
        db.close()
        raise
    return db


def changes(db, schema='main'):
    """The fact diff of the build that wrote this research record: dict(base, rows).

    base is the content identity of the research file that the build replaced,
    or None when there was none with these tables; rows maps each kind of
    books.VISIBLE to {company: its earliest changed row key} ('' names the
    shared SPY and Treasury rows). Research produces the diff; the book code
    decides which books stay (books.change_day, books.kept).
    """
    row = db.execute(f"SELECT value FROM {schema}.metadata WHERE key='changes'").fetchone()
    if row is None:
        raise ValueError('Cached inputs changed. Run: python3 scripts/research.py prepare')
    return json.loads(row[0])


def _first_change(old, new):
    """The key (first column) of the first row where two key-ordered row lists differ, or None.

    At the first differing position the smaller key is a changed, added or
    removed row; every row before it is equal.
    """
    for a, b in zip(old, new):
        if a != b:
            return min(a[0], b[0])
    if len(old) != len(new):
        return (old if len(old) > len(new) else new)[min(len(old), len(new))][0]
    return None


def _base(path, tables):
    """The identity of the research file at path when its tables equal this build's, else None.

    It is the base of the fact diff: equal table definitions let the build
    compare the rows column by column.
    """
    if not path.exists():
        return None
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            found = db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
            if sorted(row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE type='table'")) != tables:
                return None
        identity = json.loads(found[0]) if found else None
    except (sqlite3.Error, ValueError):
        return None
    return identity if isinstance(identity, dict) and identity.get('version') == SCHEMA_VERSION else None


class _Diff:
    """The fact diff of one build against the replaced research file, attached as 'old'.

    A price or annual file whose sha256 (fact_sources) and the fact-row code
    are both unchanged is skipped. The rows of every other file, the statements
    and the SPY and Treasury rows are compared. Statements keep only the saved
    companies, so they cover an added or removed company. Equal values compare
    equal, so 0.0 equals -0.0: book tables store REAL values, which keep no
    signed zero.
    """

    def __init__(self, db, same_code):
        self.db, self.same = db, same_code
        self.read = db.cursor()
        self.read.row_factory = None
        self.sources = {(symbol, endpoint): sha for symbol, endpoint, sha in
                        self.read.execute('SELECT symbol,endpoint,sha256 FROM old.fact_sources')}
        self.rows = {kind: {} for kind in books.VISIBLE}

    def _note(self, kind, symbol, key):
        if key is not None:
            self.rows[kind][symbol] = key

    def _unchanged(self, symbol, endpoint, sha):
        return self.same and (symbol, endpoint) in self.sources and self.sources[symbol, endpoint] == sha

    def company(self, symbol, stock, rows, annual):
        """Compare one company's price rows and legacy annual values, unless their files are unchanged."""
        if self._unchanged(symbol, facts.STOCK, stock['sha256']):
            diagnostics.count('price_files_skipped')
        else:
            diagnostics.count('price_files_compared')
            self._note('prices', symbol, _first_change(self.read.execute(
                'SELECT day,adjusted,adjusted_reason,volume,volume_reason FROM old.stock_days WHERE symbol=? ORDER BY day',
                (symbol,)).fetchall(), rows))
        if not all(self._unchanged(symbol, endpoint, source['sha256']) for endpoint, source in annual.items()):
            old, new = (facts.legacy_annual(self.db, symbol, schema=schema) for schema in ('old', 'main'))
            self._note('annual', symbol, next((fiscal for fiscal in sorted(old.keys() | new.keys())
                                               if old.get(fiscal) != new.get(fiscal)), None))

    def finish(self):
        """Compare the statements, SPY and Treasury; return the rows."""
        statements = {}
        for index, schema in enumerate(('old', 'main')):
            for symbol, *row in self.read.execute(f'SELECT * FROM {schema}.statements ORDER BY symbol,fiscal'):
                statements.setdefault(symbol, ([], []))[index].append(tuple(row))
        for symbol, (old, new) in statements.items():
            self._note('statements', symbol, _first_change(old, new))
        self._note('market', '', _first_change(*(self.read.execute(f'SELECT * FROM {schema}.market_days ORDER BY day').fetchall()
                                                  for schema in ('old', 'main'))))
        return self.rows


def _readable(resolution, name):
    """Return one resolved price or yield file; an unreadable saved file stops preparation."""
    if resolution['source']['disposition']=='unreadable':
        raise ValueError(f'Saved file raw/{name} is unreadable. Use the data panel to download it again.')
    return resolution


@cache_access.exclusive
@diagnostics.operation('prepare.research')
def prepare(path=DATABASE, force=False):
    """Build the research database from saved files; never download.

    Every build is a full build. A current database is kept unless force is set.
    """
    started=time.perf_counter()
    diagnostics.note(force=force)
    path=Path(path)
    # Preparation is a data action: its readers inspect raw inputs afresh.
    forget_signature()
    if path.exists() and not force:
        try:
            db=connect(path,full_prices=True)
        except ValueError:
            pass
        else:
            db.close()
            print(f'Database already current ({time.perf_counter()-started:.2f}s); only file metadata was checked.')
            diagnostics.note(outcome='current');return
    inputs, sources=signature(),price_sources()
    code=code_identity('facts')
    content=(RAW/'universe.json').read_bytes()
    # The facts' content identity: the code and the bytes of every saved file read.
    raw=dict(universe=hashlib.sha256(content).hexdigest(),
             metrics=hashlib.sha256((RAW/'metrics.jsonl').read_bytes()).hexdigest())
    universe={r['symbol']:r for r in json.loads(content)}
    # Each saved file is parsed once, into its typed facts.
    market_facts=facts.shared(RAW,backtest_control.checkpoint)
    for name,endpoint in (('spy-div.json',facts.CALENDAR),('treasury.json',facts.TREASURY)):
        _readable(market_facts[endpoint],name)
    records,invalid=cache_assets.financial_records(RAW/'metrics.jsonl')
    if invalid:raise ValueError('Annual financial cache contains invalid records. Use the data panel to repair annual financials.')
    broad=books.statements(records,universe)
    financials=[(symbol,str(row['fiscal']),str(row['known']),row['market_cap'],row['enterprise'],row['ebitda'],row['yield'])
                for symbol,rows in broad.items() for row in rows]
    latest_day=date.fromisoformat(max(day for day,states in market_facts[facts.CALENDAR]['dated'].items() if states['adjClose']['valid']))
    diagnostics.lap('inputs')
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.building')
    if temporary.exists():
        temporary.unlink()
    db=sqlite3.connect(temporary.resolve().as_uri(),uri=True)
    db.row_factory=sqlite3.Row
    try:
        db.executescript(SCHEMA+facts.SCHEMA)
        # The replaced database is the base of the fact diff when its tables equal these.
        base=_base(path,sorted(row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE type='table'")))
        diff=None
        if base is not None:
            db.execute('ATTACH DATABASE ? AS old',(path.resolve().as_uri()+'?mode=ro',))
            diff=_Diff(db,base.get('code')==code)
        facts.store_companies(db,universe)
        db.executemany('INSERT OR REPLACE INTO statements VALUES(?,?,?,?,?,?,?)',financials)
        cached={s for s in broad if market.cache_path_for(s).name in sources}
        spiked=[]
        for number,symbol in enumerate(sorted(broad),1):
            backtest_control.checkpoint()
            # One parse of the price file gives its typed facts.
            stock=_readable(facts.stock(RAW,symbol,backtest_control.checkpoint),'px/'+market.cache_path_for(symbol).name)
            rows=facts.store_stock(db,symbol,stock)
            if any(row[2]==facts.INCONSISTENT_SERIES for row in rows):spiked.append(symbol)
            resolved=financial_inputs.resolve_history(RAW,symbol)
            facts.store_annual(db,symbol,resolved)
            if diff is not None:
                diff.company(symbol,stock['source'],rows,resolved['sources'])
            if number%200==0 or number==len(broad):
                print(f'Prepared {number}/{len(broad)} companies',flush=True)
        diagnostics.lap('companies')
        if spiked:
            print(f'Left out {len(spiked)} price series with an isolated price spike: {", ".join(spiked)}',flush=True)
        diagnostics.note(companies=len(cached),spiked_series=len(spiked))
        facts.store_market(db,market_facts)
        diagnostics.lap('dated_facts')
        changed=dict(base=None,rows={})
        if diff is not None:
            changed=dict(base=base.get('content'),rows=diff.finish())
        diagnostics.note(changes={kind:len(rows) for kind,rows in changed['rows'].items()})
        diagnostics.lap('fact_diff')
        # fact_sources holds the digest of every price, annual, SPY and Treasury file read.
        digest=hashlib.sha256()
        for row in db.execute('SELECT symbol,endpoint,sha256,disposition FROM fact_sources ORDER BY symbol,endpoint'):
            digest.update(json.dumps(list(row),separators=(',',':')).encode()+b'\n')
        raw['sources']=digest.hexdigest()
        record=dict(version=SCHEMA_VERSION,latest_date=str(latest_day),code=code)
        record['content']=hashlib.sha256(facts.encoded(dict(record,raw=raw)).encode()).hexdigest()
        diagnostics.lap('identity')
        for key,value in dict(version=SCHEMA_VERSION,inputs=inputs,prices=sources,identity=record,changes=changed).items():
            db.execute('INSERT INTO metadata VALUES(?,?)',(key,json.dumps(value)))
        # Reject changing inputs and keep an existing database intact on failure.
        if inputs!=signature() or sources!=price_sources() or code!=code_identity('facts'):
            raise ValueError('Inputs changed during preparation; retry.')
        db.commit()
        diagnostics.lap('commit')
        db.close()
        cache_assets.replace(temporary,path)
        diagnostics.lap('publication')
    except BaseException:
        db.close()
        temporary.unlink(missing_ok=True)
        raise
    diagnostics.note(outcome='prepared',database_bytes=path.stat().st_size)
    print(f'Prepared {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: {path.stat().st_size/1e6:.1f} MB in {time.perf_counter()-started:.2f}s')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=DATABASE)
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('prepare',help='Prepare the research database from saved JSON; never downloads')
    p.add_argument('--force',action='store_true')
    commands.add_parser('status',help='Show database size and latest price coverage')
    args=parser.parse_args()
    if args.command=='prepare':
        prepare(args.database,args.force);return
    # The latest book lives in the book store of the daily cache, which binds this database.
    from backtest.inputs import daily
    connect(args.database).close()
    with closing(daily.connect(daily.DATABASE,args.database)) as db:
        book=book_store.open_book(db);latest=book_store.record(db,book)
        counts={pool:sum(1 for _ in book_store.rows(db,book,pool)) for pool in ('legacy','cached')}
    print(f'Database: {args.database.stat().st_size/1e6:.1f} MB')
    print(f"Latest session {latest['entry']}: {latest['candidates']} active names with eligible financials; "
          f"{counts.get('cached',0)} valued with cached prices, {counts.get('legacy',0)} in the original candidate set.")


if __name__=='__main__':
    try:
        main()
    except (ValueError,sqlite3.Error) as error:
        raise SystemExit(str(error))
