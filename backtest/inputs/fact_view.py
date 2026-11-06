"""The borrowed view of one operation's prepared inputs: a reader that binds no identity.

A View reads one daily connection (daily.connect): the book store in main and
the research facts through the attached 'research' schema. The caller's cache
ownership keeps both unchanged while the view is open; close the view before
the connection. Editing this module neither rebuilds research nor drops a book
(research.code_sources).
"""
from contextlib import contextmanager
from datetime import date
import hashlib
import json

from backtest.financial import books
from backtest.inputs import book_store, daily, facts


def _call(day, forward, slack, result):
    # 'price' is the stored explanation label of a valuation lookup.
    return dict(requested_date=str(day), column='price', forward=forward, slack=slack,
                observation=[str(result[0]), result[1]] if result else None)


class _Recorder:
    """The screens' facts port: BookFacts whose price lookups are recorded inside record()."""

    def __init__(self, facts):
        self.facts, self._calls = facts, None

    def __getattr__(self, name):
        return getattr(self.facts, name)

    def price(self, symbol, day, forward=False, slack=None):
        result = self.facts.price(symbol, day, forward, slack)
        if self._calls is not None:
            self._calls.append(_call(day, forward, slack, result))
        return result

    @contextmanager
    def record(self):
        """Yield a new list of the lookups made inside the block; none are recorded outside one."""
        self._calls = calls = []
        try:
            yield calls
        finally:
            self._calls = None


def _states(**pairs):
    """Field states from (value, reason) pairs; a field with neither has no state."""
    return {field: dict(value=value, valid=reason is None, reason=reason)
            for field, (value, reason) in pairs.items() if value is not None or reason is not None}


class View:
    """Borrowed daily connection of one operation: research facts and the book store.

    The facts supply the reports, prices, saved sessions and typed facts
    through BookFacts; the book store supplies the stored latest book. The
    view's input identity is the daily binding (daily.binding) and its
    projection the research identity. Admission is books.Screen.decide for
    every root: an open-book screen at the latest date for a latest root, a
    dated screen for a historical root. Each company, day and source is read
    once per view: neither database can change while it is open. validate()
    is the operation's boundary check: the freshness callback, the daily
    binding and the research identity.
    """

    def __init__(self, db, freshness, checkpoint):
        freshness()
        self.db, self._freshness, self._checkpoint = db, freshness, checkpoint
        self._binding = daily.binding(db)
        if self._binding is None:
            raise ValueError('Admitted daily input identity is missing.')
        self._record = self._identity()
        if self._record is None:
            raise ValueError('Prepared facts are missing, incompatible or stale. Retry offline preparation.')
        self.identity = 'sqlite:' + hashlib.sha256(facts.encoded(dict(inputs=json.loads(self._binding))).encode()).hexdigest()
        self._projection = json.loads(self._record)
        self._facts = facts.BookFacts(db)
        self._recorder = _Recorder(self._facts)
        broad, legacy = self._facts.reports()
        if any(len(rows) > facts.MAX_HISTORY for rows in broad.values()):
            raise ValueError('Prepared observation history exceeds its bound.')
        self._pools = dict(cached=broad, legacy=legacy)
        self._bounds = dict(latest_date=self._projection['latest_date'], population=len(broad))
        self._screens, self._reports, self._companies, self._lanes, self._open_book = {}, {}, {}, {}, None
        self._sessions, self._stock, self._treasury, self._sources = {}, {}, {}, {}
        self.closed = False

    def _identity(self):
        row = self.db.execute("SELECT value FROM research.metadata WHERE key='identity'").fetchone()
        return None if row is None else row[0]

    @property
    def projection(self):
        """The research identity (version, latest date, code and content identity); callers do not change it."""
        return self._projection

    @property
    def bounds(self):
        return dict(self._bounds)

    @property
    def open_book(self):
        """The id of the stored open (latest) book."""
        self._open()
        if self._open_book is None:
            self._open_book = book_store.open_book(self.db)
        return self._open_book

    def validate(self):
        if self.closed:
            raise ValueError('Observation input view is closed.')
        self._checkpoint()
        self._freshness()
        if daily.binding(self.db) != self._binding:
            raise ValueError('Admitted daily input identity changed.')
        if self._identity() != self._record:
            raise ValueError('Prepared facts are missing, incompatible or stale. Retry offline preparation.')

    def _open(self):
        if self.closed:
            raise ValueError('Observation input view is closed.')

    def close(self):
        self.closed = True
        self.db = self._freshness = self._facts = self._recorder = None

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()

    # Admission and valuation, by the existing financial policy.

    def _screen(self, day, open_book, checkpoint=lambda: None):
        """The books.Screen of one entry day; a day that is not a saved SPY session from FIRST_DAY fails."""
        key = day, open_book
        if key not in self._screens:
            checkpoint()
            self._screens[key] = books.Screen(date.fromisoformat(day), self._recorder, open_book=open_book)
        return self._screens[key]

    def candidates(self, day, checkpoint=lambda: None):
        """Return (statements by pool, legacy ranks) at one saved screen date."""
        self._open()
        screen = self._screen(day, False, checkpoint)
        return screen.statements, screen.ranks

    def is_cached(self, symbol):
        self._open()
        return symbol in self._facts.cached()

    def reports(self, symbol, pool):
        self._open()
        key = symbol, pool
        if key not in self._reports:
            self._reports[key] = [dict(row, fiscal=str(row['fiscal']), known=str(row['known']))
                                  for row in self._pools[pool].get(symbol, [])]
        return self._reports[key]

    def admit(self, roots, checkpoint=lambda: None):
        """Admission decisions in root order: books.Screen.decide, with its reason.

        A latest root must be on the latest date and uses the open book's
        screen (listed companies, the exact session). A historical root, on a
        saved SPY session from rules.FIRST_DAY, uses the complete-population
        candidates of its date: the legacy buffer precedes cached-price
        membership, so asking for fewer companies cannot promote one. A
        historical decision that reached the entry valuation keeps its
        recorded lookups as admission evidence. Earlier contexts reuse these
        decisions.
        """
        self._open()
        self.validate()
        decisions = []
        for index, root in enumerate(roots):
            checkpoint()
            symbol, pool, latest = root['symbol'], root['pool'], root['mode'] == 'latest'
            if latest and root['date'] != self._bounds['latest_date']:
                raise ValueError('Latest observation root does not match prepared admission.')
            screen = self._screen(root['date'], latest, checkpoint)
            with self._recorder.record() as lookups:
                held, reason = screen.decide(symbol, pool)
            statement = screen.statements[pool].get(symbol)
            decision = dict(root='r' + str(index), symbol=symbol, pool=pool, mode=root['mode'],
                            date=root['date'], admitted=held is not None, reason=reason,
                            candidate_rank=screen.ranks.get(symbol), statement=None, valuation=None)
            if statement is not None:
                decision['statement'] = (dict(fiscal=str(statement['fiscal']), known=str(statement['known']))
                                         if latest else _detached(statement))
            if not latest and lookups:
                decision['admission_evidence'] = dict(
                    lookup_policy='existing-entry-valuation', lookups=lookups,
                    statement=_detached(statement), reason=None if reason == 'INELIGIBLE_VALUATION' else reason)
            if held is not None:
                valuation = dict(market_cap=held['market_cap'], enterprise_value=held['enterprise_value'],
                                 ebitda=held['ebitda'])
                if not latest:
                    valuation.update(fiscal_price=[str(held['fiscal_price'][0]), held['fiscal_price'][1]],
                                     valuation_price=[str(held['entry'][0]), held['entry'][1]])
                decision['valuation'] = valuation
            decisions.append(decision)
        self.validate()
        return decisions

    def entry(self, symbol, statement, day):
        """Observe the authoritative entry valuation (books.admit) and its recorded lookups."""
        self._open()
        lookups = []

        def lookup(when, forward, slack):
            result = self._facts.price(symbol, when, forward, slack)
            lookups.append(_call(when, forward, slack, result))
            return result
        reason, value = books.admit(statement, day, lookup, books.ENTRY_SLACK)
        evidence = dict(lookup_policy='existing-entry-valuation', lookups=lookups, statement=_detached(statement),
                        reason=reason)
        if value is None:
            return None, evidence
        fiscal, entry, cap, ev, ebitda = value
        return dict(market_cap=cap, enterprise_value=ev, ebitda=ebitda,
                    fiscal_price=[str(fiscal[0]), fiscal[1]], valuation_price=[str(entry[0]), entry[1]]), evidence

    def lookup(self, symbol, day, forward=False, slack=None):
        """(day, valid adjusted close) of one company (BookFacts.price); facts.observe keeps only positive values."""
        self._open()
        if not isinstance(day, date):
            raise ValueError('Invalid observation price lookup.')
        return self._facts.price(symbol, day, forward, slack)

    def broad_reports(self, symbol, checkpoint=lambda: None, *, budget=None):
        self._open()
        checkpoint()
        reports = self.reports(symbol, 'cached')
        if budget is not None and len(facts.encoded(reports).encode('utf-8')) > budget:
            raise ValueError('Observation report history exceeds its byte bound.')
        return reports

    def legacy_financial_history(self, symbol, checkpoint=lambda: None, *, budget=None):
        """facts.legacy_annual() of one company; the byte bound counts each date's JSON text."""
        self._open()
        result = facts.legacy_annual(self.db, symbol, checkpoint)
        if len(result) > facts.MAX_HISTORY:
            raise ValueError('Prepared observation history exceeds its bound.')
        size = 0
        for fiscal, values in result.items():
            checkpoint()
            size += len(symbol) + len(fiscal) + len(json.dumps(values))
            if budget is not None and size > budget:
                raise ValueError('Observation financial history exceeds its byte bound.')
        return result

    def legacy_treasury(self, day, checkpoint=lambda: None):
        self._open()
        checkpoint()
        row = facts.ten_year(self.db, day)
        return dict(day=row[0], value=row[1]) if row else None

    # Typed facts.

    def company(self, symbol, pool, requirements):
        """Return company facts: reports, the requested annual states and their sources.

        Income-statement dates always form the fiscal spine when any annual field
        is required.
        """
        self._open()
        key = symbol, pool
        cached = self._companies.get(key)
        if cached is None:
            cached = self._companies[key] = dict(reports=self.reports(symbol, pool), annual={}, sources={}, loaded={})
        annual, loaded, sources = cached['annual'], cached['loaded'], cached['sources']
        wanted = dict(requirements)
        if wanted:
            wanted.setdefault('income-statement', set())
        for endpoint, fields in wanted.items():
            missing = sorted(set(fields) - loaded.get(endpoint, set()))
            if endpoint in loaded and not missing:
                continue
            states = annual.setdefault(endpoint, {})
            columns = [facts.COLUMNS[endpoint, field] for field in missing]
            projection = ''.join(f',{column},{column}_reason' for column in columns)
            count = 0
            for row in self.db.execute(f'SELECT fiscal{projection} FROM research.annual_facts WHERE symbol=? AND endpoint=? '
                                       'ORDER BY fiscal LIMIT ?', (symbol, endpoint, facts.MAX_HISTORY + 1)):
                count += 1
                if count > facts.MAX_HISTORY:
                    raise ValueError('Prepared observation history exceeds its bound.')
                states.setdefault(row[0], {}).update(
                    _states(**{field: row[1 + 2 * i:3 + 2 * i] for i, field in enumerate(missing)}))
            loaded.setdefault(endpoint, set()).update(missing)
            if endpoint not in sources:
                sources[endpoint] = self.source(symbol, endpoint)
        return cached

    def session(self, day):
        """The latest valid SPY session on or before day within seven days, or None."""
        self._open()
        if day not in self._sessions:
            row = self.db.execute('SELECT day FROM research.market_days WHERE day<=? AND spy IS NOT NULL '
                                  'ORDER BY day DESC LIMIT 1', (str(day),)).fetchone()
            self._sessions[day] = row[0] if row is not None and (day - date.fromisoformat(row[0])).days <= 7 else None
        return self._sessions[day]

    def stock(self, symbol, day):
        """{'adjClose': state, 'volume': state} at one exact saved day, or None."""
        self._open()
        key = symbol, day
        if key not in self._stock:
            row = self.db.execute('SELECT adjusted,adjusted_reason,volume,volume_reason FROM research.stock_days '
                                  'WHERE symbol=? AND day=?', (symbol, str(day))).fetchone()
            self._stock[key] = None if row is None else _states(adjClose=row[0:2], volume=row[2:4])
        return self._stock[key]

    def treasury(self, day):
        """(day, {'month3': state, 'year10': state}) of the latest saved Treasury day on or before day."""
        self._open()
        if day not in self._treasury:
            row = self.db.execute('SELECT day,month3,month3_reason,year10,year10_reason FROM research.market_days '
                                  'WHERE day<=? AND (month3 IS NOT NULL OR month3_reason IS NOT NULL) '
                                  'ORDER BY day DESC LIMIT 1', (str(day),)).fetchone()
            self._treasury[day] = None if row is None else (row[0], _states(month3=row[1:3], year10=row[3:5]))
        return self._treasury[day]

    def source(self, symbol, endpoint):
        """{endpoint, sha256, disposition} of one source file, as explanations keep them."""
        self._open()
        key = symbol, endpoint
        if key not in self._sources:
            row = self.db.execute('SELECT sha256,disposition FROM research.fact_sources WHERE symbol=? AND endpoint=?',
                                  (symbol, endpoint)).fetchone()
            self._sources[key] = None if row is None else dict(endpoint=endpoint, sha256=row[0], disposition=row[1])
        return self._sources[key]

    def prepared(self, decision):
        """Owner values of a latest root's row in its stored book (book_store.lanes).

        The book is the root's prepared owner scope, else the open book; each
        book pool is read once per view. A missing row is unavailable; it never
        falls back to a recalculation.
        """
        self._open()
        if decision['mode'] != 'latest':
            raise ValueError('Only a latest root has a stored owner book.')
        scope = decision.get('owner_scope')
        book = scope['book'] if scope is not None and scope['kind'] == 'prepared' else self.open_book
        key = book, decision['pool']
        if key not in self._lanes:
            self._lanes[key] = ({row['symbol']: row['market_cap'] for row in book_store.rows(self.db, *key)},
                                *book_store.lanes(self.db, *key))
        rows, pairs, values = self._lanes[key]
        symbol = decision['symbol']
        if symbol not in rows:
            return dict(reason='PREPARED_MEASURE_CONTEXT_UNAVAILABLE', evidence=None)
        return dict(reason=None, evidence=dict(snapshot=dict(market_cap=rows[symbol]),
                    metrics={metric: list(pair) for metric, pair in pairs.get(symbol, {}).items()},
                    filters=dict(values.get(symbol, {}))))


def _detached(statement):
    return {key: str(value) if isinstance(value, date) else value for key, value in statement.items()}
