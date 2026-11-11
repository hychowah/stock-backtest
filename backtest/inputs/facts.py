"""Typed prepared facts: the tables that research preparation writes and the book facts port.

Research preparation resolves saved files into these tables in its build
transaction. Annual statements use financial_inputs.resolve_history; saved
stock, Treasury and SPY rows use resolve() below, which parses each file once.

- stock_days: one row per company and saved price day, keyed by date, with the
  observation fields.
- market_days: valid SPY sessions (spy) and saved Treasury days (both yields
  in percent).
- annual_facts: one row per company, statement endpoint and fiscal date, with
  one value and one reason column per annual catalog field.
- companies: each saved company with its name, exchange, sector and whether
  it is listed now.
- fact_sources: the source file digest and disposition per company and
  endpoint; the empty symbol names the shared Treasury and SPY files.
- valuation_sums: derived from the facts above as the last preparation stage
  (store_valuations): per company and priced day with a yield, the running
  sums of daily E/P, S/P and B/P and their day counts. Books read them for the
  valuation averages (BookFacts.valuation).

The research record (research.py) names the facts' version and content
identity. A field is valid when its value is present; otherwise its reason
column names the provider reason. A saved day or fiscal date always has a
value or a reason for each of its endpoint's fields. Value columns have no
declared type, so SQLite keeps the binary64 bits exactly, including -0.0,
which a REAL column stores as the integer 0.

One rule gives a day its value: equal admissible values agree, and a
conflicting, non-USD or invalid value gives no value and a reason. A stock
series with an isolated price spike keeps no close (stock()). Books
(books.book) and admission (books.Screen) read the valid values through
BookFacts. Every reader reads the facts through the 'research' schema that a
daily connection attaches (daily.attach). The book store of the daily cache
(backtest/inputs/book_store.py) holds the latest and dated books; the formula
view (backtest/inputs/fact_view.py) reads the facts for formulas.
"""
from datetime import date, timedelta
import hashlib
import json
import math

from backtest.financial import books, rules
from backtest.inputs import cache_assets, financial_inputs, market
from backtest.variables import parameters

MAX_HISTORY = 16384
STOCK = 'historical-price-eod/dividend-adjusted'
TREASURY = 'treasury-rates'
CALENDAR = 'spy-calendar'
# The isolated price spike of stock() and the reason it gives every close.
SPIKE = 8
INCONSISTENT_SERIES = 'INCONSISTENT_SERIES'


def _annual_columns():
    """(column, endpoint, field) for every direct annual catalog parameter."""
    result = []
    for item in parameters.catalog(parameters.V3):
        if item['kind'] == 'direct' and item['id'].startswith('annual.'):
            result.append((item['id'].split('.', 1)[1], item['source']['endpoint'], item['source']['field']))
    return tuple(result)


ANNUAL = _annual_columns()
# The annual_facts column of each (endpoint, field).
COLUMNS = {(endpoint, field): column for column, endpoint, field in ANNUAL}
# The legacy values-only annual fields by endpoint, in financial_inputs order:
# what BookFacts.legacy_annual reads. financial_inputs and the catalog are fact-row
# code, so the book identity names this list itself (research.code_identity).
LEGACY = tuple((endpoint, tuple((field, COLUMNS[endpoint, field]) for field in fields))
               for endpoint, fields in financial_inputs.ENDPOINTS.items() if fields)
_ENDPOINTS = {field: endpoint for endpoint, fields in LEGACY for field, _ in fields}
# The local-session filter of foreign closes. Probe the session key; IN
# rebuilds the full calendar for each price lookup.
_SESSION = ' AND EXISTS (SELECT 1 FROM research.local_sessions s WHERE s.market=? AND s.day=stock_days.day)'

SCHEMA = '''
CREATE TABLE stock_days(symbol TEXT, day TEXT, adjusted, adjusted_reason TEXT, volume, volume_reason TEXT,
 PRIMARY KEY(symbol,day)) WITHOUT ROWID;
CREATE TABLE market_days(day TEXT PRIMARY KEY, spy, month3, month3_reason TEXT, year10, year10_reason TEXT) WITHOUT ROWID;
CREATE TABLE annual_facts(symbol TEXT, endpoint TEXT, fiscal TEXT, ''' + ', '.join(
    column + ', ' + column + '_reason TEXT' for column, _, _ in ANNUAL) + ''',
 income_ebitda, income_ebitda_reason TEXT,
 PRIMARY KEY(symbol,endpoint,fiscal)) WITHOUT ROWID;
CREATE TABLE companies(symbol TEXT PRIMARY KEY, name TEXT, exchange TEXT, sector TEXT, listed INTEGER NOT NULL);
CREATE TABLE fact_sources(symbol TEXT, endpoint TEXT, sha256 TEXT, disposition TEXT NOT NULL,
 PRIMARY KEY(symbol,endpoint)) WITHOUT ROWID;
CREATE TABLE company_markets(symbol TEXT PRIMARY KEY, market TEXT NOT NULL, currency TEXT NOT NULL);
CREATE TABLE annual_metadata(symbol TEXT, endpoint TEXT, fiscal TEXT, currency TEXT, known TEXT, basis TEXT, PRIMARY KEY(symbol,endpoint,fiscal)) WITHOUT ROWID;
CREATE TABLE foreign_reports(symbol TEXT, fiscal TEXT, known TEXT, currency TEXT, shares, ebitda, debt, cash, basis TEXT, fiscal_cap, PRIMARY KEY(symbol,fiscal)) WITHOUT ROWID;
CREATE TABLE stock_native(symbol TEXT, day TEXT, close, PRIMARY KEY(symbol,day)) WITHOUT ROWID;
CREATE TABLE local_sessions(market TEXT, day TEXT, PRIMARY KEY(market,day)) WITHOUT ROWID;
CREATE TABLE fx_days(currency TEXT, day TEXT, usd, reason TEXT, PRIMARY KEY(currency,day)) WITHOUT ROWID;
CREATE TABLE valuation_sums(symbol TEXT, day TEXT, earnings REAL, sales REAL, equity REAL,
 earnings_days INTEGER, sales_days INTEGER, equity_days INTEGER, PRIMARY KEY(symbol,day)) WITHOUT ROWID;
'''
# The valuation sums before a company's first row. A sum starts at +0.0 and
# never becomes -0.0, so the REAL columns keep every sum exactly.
_NO_SUMS = (0., 0., 0., 0, 0, 0)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


# Resolving saved dated files.

def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, float, int)):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, OverflowError):
        return None


def row_day(row):
    """Return the saved day under which one dated row is resolved, or None."""
    value = row.get('date') if isinstance(row, dict) else None
    try:
        return str(date.fromisoformat(value[:10])) if isinstance(value, str) else None
    except ValueError:
        return None


def observe(rows, fields, checkpoint=lambda: None, *, currency='USD'):
    """{day: {field: state}} of saved dated rows: the one value rule of a day.

    Equal admissible values agree; different ones are CONFLICTING_INPUT. A
    currency mismatch disqualifies only a price, never volume. A
    price must be positive, a volume non-negative; all signed rates are valid.
    """
    grouped = {}
    for row in rows:
        day = row_day(row)
        if day is not None:
            grouped.setdefault(day, []).append(row)
    dated = {}
    for day, variants in grouped.items():
        checkpoint()
        states = {}
        for field in fields:
            candidates, invalid, foreign = set(), False, False
            for row in variants:
                value = _number(row.get(field))
                incompatible = field in ('adjClose','close') and currency is not None and any(
                    code not in (None, '', currency) for code in (row.get('currency'), row.get('reportedCurrency')))
                acceptable = (value is not None and (value > 0 if field in ('adjClose','close')
                              else value >= 0 if field == 'volume' else True))
                if acceptable and not incompatible:
                    candidates.add(value)
                foreign |= incompatible and value is not None
                invalid |= row.get(field) not in (None, '') and not acceptable
            reason = (None if len(candidates) == 1 else 'CONFLICTING_INPUT' if len(candidates) > 1
                      else 'NON_USD_INPUT' if foreign else 'INVALID_INPUT' if invalid else 'MISSING_INPUT')
            states[field] = dict(value=next(iter(candidates)) if reason is None else None,
                                 valid=reason is None, reason=reason)
        dated[day] = states
    return dated


def resolve(path, endpoint, *, stock=False, checkpoint=lambda: None, currency='USD', fields=None, content=None):
    """Return the source and the field states of each saved day of one file.

    The file is read and parsed once. A stock file is a mapping whose 'div'
    rows are dated; any other content is unreadable. Currency-free stock routes
    use the admitted USD-company/share basis. The source is always complete.
    """
    source = dict(endpoint=endpoint, sha256=None, disposition='missing')
    if content is None:
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            return dict(source=source, dated={})
    checkpoint()
    source.update(sha256=hashlib.sha256(content).hexdigest(), disposition='unreadable')
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return dict(source=source, dated={})
    rows = (payload.get('div') if isinstance(payload, dict) else None) if stock else payload
    if endpoint == CALENDAR and isinstance(rows, dict):
        # Match the retained SPY reader. Wrapper metadata is not a receipt.
        rows = rows.get('historical') or rows.get('data') or []
    if not isinstance(rows, list):
        return dict(source=source, dated={})
    if len(rows) > MAX_HISTORY:
        raise ValueError('Prepared observation history exceeds its bound.')
    try:
        valid = cache_assets.valid_series(payload, 'month3' if endpoint == TREASURY else (fields[0] if fields else 'adjClose'), stock=stock)
    except (ValueError, TypeError, OverflowError):
        valid = False
    source['disposition'] = 'valid' if valid else 'salvaged'
    fields = fields or (('month3', 'year10') if endpoint == TREASURY else ('adjClose', 'volume') if stock else ('adjClose',))
    return dict(source=source, dated=observe(rows, fields, checkpoint, currency=currency))


def _spiked(closes):
    """Whether one close is at least SPIKE times, or at most 1/SPIKE of, both neighbouring closes."""
    for before, middle, after in zip(closes, closes[1:], closes[2:]):
        up, down = middle / before, middle / after
        if min(up, down) >= SPIKE or max(up, down) <= 1 / SPIKE:
            return True
    return False


def stock(raw, symbol, checkpoint=lambda: None, *, currency='USD', content=None):
    """Resolve one saved price file; a series with an isolated spike keeps no close.

    Such a spike mixes two price scales in one provider series, so no close of
    it is usable: every valid close becomes INCONSISTENT_SERIES and the company
    has no price. Neighbours are the adjacent valid closes in day order.
    """
    resolution = resolve(raw / 'px' / market.cache_path_for(symbol).name, STOCK, stock=True, checkpoint=checkpoint, currency=currency, content=content)
    closes = [states['adjClose'] for _, states in sorted(resolution['dated'].items()) if states['adjClose']['valid']]
    if _spiked([state['value'] for state in closes]):
        for state in closes:
            state.update(value=None, valid=False, reason=INCONSISTENT_SERIES)
    return resolution


# Writing, inside research preparation's build transaction.

def _pair(state):
    """Return (value, reason) of one resolved field state."""
    return (state['value'], None) if state['valid'] else (None, state['reason'])


def same_row(left, right):
    """Typed equality, including the sign of zero in unaffinitized value columns."""
    return len(left)==len(right) and all(type(a) is type(b) and
        (a.hex()==b.hex() if isinstance(a,float) else a==b) for a,b in zip(left,right))


def reconcile(db, table, keys, rows, **scope):
    """Replace one table scope with resolved rows, writing only exact differences.

    Tables, key columns and scope columns are application-owned schema names.
    The caller owns the transaction. Returned old/new pairs include deletions.
    """
    where=' AND '.join(column+'=?' for column in scope)
    old={tuple(row[:len(keys)]):tuple(row) for row in db.execute(
        f'SELECT * FROM {table}'+(' WHERE '+where if where else ''),tuple(scope.values()))}
    changes=[]
    for row in rows:
        row=tuple(row);before=old.pop(row[:len(keys)],None)
        if before is None or not same_row(before,row):changes.append((before,row))
    changes.extend((row,None) for row in old.values())
    added=[after for _,after in changes if after is not None]
    if added:db.executemany(f'INSERT OR REPLACE INTO {table} VALUES('+','.join('?'*len(added[0]))+')',added)
    if old:db.executemany(f'DELETE FROM {table} WHERE '+' AND '.join(key+'=?' for key in keys),old)
    return changes


def _source(db, symbol, source):
    reconcile(db,'fact_sources',('symbol','endpoint'),
              [(symbol,source['endpoint'],source['sha256'],source['disposition'])],
              symbol=symbol,endpoint=source['endpoint'])


def store_annual(db, symbol, resolution):
    """Reconcile the supplied annual endpoints, including unavailable fields."""
    for endpoint, source in resolution['sources'].items():
        _source(db, symbol, source)
    changes={'rows':[],'metadata':[]}
    for endpoint, dates in resolution['annual'].items():
        rows=[]
        for fiscal, states in dates.items():
            values = {COLUMNS[endpoint, field]: _pair(state) for field, state in states.items() if (endpoint,field) in COLUMNS}
            row = [symbol, endpoint, fiscal]
            for column, _, _ in ANNUAL:
                row.extend(values.get(column, (None, None)))
            row.extend(_pair(states['ebitda']) if 'ebitda' in states else (None,None))
            rows.append(row)
        changes['rows']+=reconcile(db,'annual_facts',('symbol','endpoint','fiscal'),rows,symbol=symbol,endpoint=endpoint)
        if endpoint in resolution.get('metadata',{}):
            rows=[(symbol,endpoint,fiscal,info['currency'],info['known'],info['basis'])
                  for fiscal,info in resolution['metadata'][endpoint].items()]
            changes['metadata']+=reconcile(db,'annual_metadata',('symbol','endpoint','fiscal'),rows,symbol=symbol,endpoint=endpoint)
    return changes


def store_foreign_reports(db, checkpoint):
    """Derive accepted foreign anchors from reconciled annual/native/session facts."""
    def rows():
        core=db.execute('''SELECT i.symbol,i.fiscal,MAX(im.known,bm.known),im.currency,
            i.weighted_average_basic_shares,i.income_ebitda,b.total_debt,b.cash_and_equivalents,im.basis
            FROM annual_facts i JOIN annual_facts b ON b.symbol=i.symbol AND b.fiscal=i.fiscal
            JOIN annual_metadata im ON im.symbol=i.symbol AND im.endpoint=i.endpoint AND im.fiscal=i.fiscal
            JOIN annual_metadata bm ON bm.symbol=b.symbol AND bm.endpoint=b.endpoint AND bm.fiscal=b.fiscal
            JOIN company_markets c ON c.symbol=i.symbol
            WHERE c.market!='us' AND i.endpoint='income-statement' AND b.endpoint='balance-sheet-statement'
            AND im.currency IS NOT NULL AND im.currency=bm.currency
            AND i.weighted_average_basic_shares>0 AND i.income_ebitda>0
            AND b.total_debt IS NOT NULL AND b.cash_and_equivalents IS NOT NULL
            ORDER BY i.symbol,i.fiscal''')
        for row in core:
            checkpoint()
            symbol,fiscal,_,_,shares,*_=row
            close=db.execute('SELECT n.close FROM stock_native n JOIN company_markets c ON c.symbol=n.symbol JOIN local_sessions s ON s.market=c.market AND s.day=n.day WHERE n.symbol=? AND n.day<=? AND n.day>=? ORDER BY n.day DESC LIMIT 1',
                             (symbol,fiscal,str(date.fromisoformat(fiscal)-timedelta(days=7)))).fetchone()
            yield (*row,None if close is None else shares*close[0])
    return reconcile(db,'foreign_reports',('symbol','fiscal'),rows())


def store_valuations(db, changes, checkpoint):
    """Fold the valuation sums of this build's facts: the last preparation stage.

    db attaches the build's facts as 'research'. changes None (a cold build)
    folds every company. Otherwise each company refolds once from its earliest
    cutoff over every market (books.affected_entries), with the port of its
    current market, so a market move keeps its new rows.
    """
    ports=[BookFacts(db,code) for code in market.MARKETS]
    owners={symbol:port for port in ports for symbol in port.companies()}
    if changes is None:
        cutoffs=dict.fromkeys(owners)
    else:
        cutoffs={}
        for port in ports:
            for symbol,day in books.affected_entries(changes,port).items():
                if symbol not in cutoffs or day<cutoffs[symbol]:cutoffs[symbol]=day
    for number,(symbol,cutoff) in enumerate(sorted(cutoffs.items()),1):
        checkpoint()
        refold(db,symbol,owners.get(symbol),cutoff)
        if number%500==0 or number==len(cutoffs):
            print(f'Valuation sums for {number}/{len(cutoffs)} companies',flush=True)


def refold(db, symbol, port, cutoff):
    """Replace one company's valuation sums from cutoff (ISO day) on: the one writer of valuation_sums.

    port is the facts port of the company's current market; None (no current
    market) deletes all its rows. A cutoff of None, or on or before
    rules.FIRST_DAY, refolds the whole company. The sums continue from the last
    row before the cutoff, or from zeros, and add books.valuation_days in day
    order, so a refold equals a cold fold bit for bit.
    """
    start=None if port is None or cutoff is None or date.fromisoformat(cutoff)<=rules.FIRST_DAY else date.fromisoformat(cutoff)
    total=list(_NO_SUMS if start is None else port.valuation(symbol,start-timedelta(days=1)))
    db.execute('DELETE FROM research.valuation_sums WHERE symbol=? AND day>=?',(symbol,'' if start is None else str(start)))
    if port is None or symbol not in port.reported():return
    rows=[]
    for day,yields in books.valuation_days(symbol,port,start):
        for k,value in enumerate(yields):
            if value is not None:
                total[k]+=value;total[3+k]+=1
        rows.append((symbol,str(day),*total))
    db.executemany('INSERT INTO research.valuation_sums VALUES(?,?,?,?,?,?,?,?)',rows)


def store_stock(db, symbol, resolution):
    """Reconcile one price history and return its changed old/new fact rows."""
    _source(db, symbol, resolution['source'])
    dated = resolution['dated']
    rows = [(day, *_pair(dated[day]['adjClose']), *_pair(dated[day]['volume'])) for day in sorted(dated)]
    return reconcile(db,'stock_days',('symbol','day'),((symbol,*row) for row in rows),symbol=symbol)


def store_market(db, resolutions):
    """Write the shared Treasury and SPY calendar days and their sources."""
    for resolution in resolutions.values():
        _source(db, '', resolution['source'])
    days={row[0]:list(row[1:]) for row in db.execute('SELECT * FROM market_days')}
    if CALENDAR in resolutions:
        for row in days.values():row[0]=None
        for day,states in resolutions[CALENDAR]['dated'].items():
            if states['adjClose']['valid']:days.setdefault(day,[None]*5)[0]=states['adjClose']['value']
    if TREASURY in resolutions:
        for row in days.values():row[1:]=[None]*4
        for day,states in resolutions[TREASURY]['dated'].items():
            days.setdefault(day,[None]*5)[1:]=[*_pair(states['month3']),*_pair(states['year10'])]
    return reconcile(db,'market_days',('day',),((day,*days[day]) for day in sorted(days)
                                              if any(value is not None for value in days[day])))


def store_companies(db, universe):
    """Write each saved company: its name, exchange and sector, and whether it is listed (universe 'listed' is True)."""
    markets=reconcile(db,'company_markets',('symbol',),((symbol,market.identify(company),company.get('currency') or market.MARKETS[market.identify(company)]['currency']) for symbol,company in universe.items()))
    companies=reconcile(db,'companies',('symbol',),(
        (symbol, company.get('name') or 'Unavailable', company.get('exchange') or 'Unavailable',
         company.get('sector') or 'Unavailable', int(company.get('listed') is True)) for symbol, company in universe.items()))
    return companies,markets



def store_native(db,raw,symbol,checkpoint=lambda:None,*,content=None):
    currency=db.execute('SELECT currency FROM company_markets WHERE symbol=?',(symbol,)).fetchone()[0]
    resolution=resolve(market.native_path(raw,symbol),'native-price',fields=('close',),checkpoint=checkpoint,currency=currency,content=content)
    _source(db,symbol,resolution['source'])
    return reconcile(db,'stock_native',('symbol','day'),((symbol,day,states['close']['value']) for day,states in resolution['dated'].items() if states['close']['valid'] and states['close']['value']>0),symbol=symbol)


def store_foreign_market(db,raw,market_ids,checkpoint=lambda:None,*,contents):
    changes={'sessions':{},'fx':{}}
    for market_id in market_ids:
        endpoint='calendar:'+market_id
        if endpoint not in contents:continue
        resolution=resolve(market.calendar_path(raw,market_id),endpoint,fields=('close',),checkpoint=checkpoint,currency=None,content=contents[endpoint])
        _source(db,'',resolution['source'])
        changes['sessions'][market_id]=reconcile(db,'local_sessions',('market','day'),((market_id,day) for day,states in resolution['dated'].items() if states['close']['valid'] and states['close']['value']>0 and market.completed_session(date.fromisoformat(day),market_id)),market=market_id)
    for path in sorted((raw/'fx').glob('USD???.json')):
        currency=path.stem[3:]
        endpoint='fx:'+currency
        if endpoint not in contents:continue
        resolution=resolve(path,endpoint,fields=('close',),checkpoint=checkpoint,currency=None,content=contents[endpoint])
        _source(db,'',resolution['source'])
        rows=[]
        for day,states in resolution['dated'].items():
            state=states['close']
            usd=1/state['value'] if state['valid'] else None
            if usd is not None and not math.isfinite(usd):usd=None
            rows.append((currency,day,usd,None if usd is not None else state['reason'] or 'INVALID_INPUT'))
        changes['fx'][currency]=reconcile(db,'fx_days',('currency','day'),rows,currency=currency)
    return changes


# Book facts: what books.book, books.Screen and the derived-context readers read,
# through the 'research' schema of a daily connection.

def legacy_annual(db, symbol):
    """{fiscal: {field: value}} of the valid legacy annual values of one company.

    The fields are LEGACY (financial_inputs.ENDPOINTS), in its endpoint and
    field order; a fiscal date without a valid value is left out. This equals the
    values-only projection of financial_inputs.resolve_history bit for bit.
    The daily connection attaches the research facts read-only. The read is
    bounded: more than MAX_HISTORY rows for each legacy endpoint, counted
    together, fail.
    """
    columns = [column for _, fields in LEGACY for _, column in fields]
    bound = MAX_HISTORY * len(LEGACY)
    found, count = {}, 0
    for endpoint, fiscal, *values in db.execute(
            f'SELECT endpoint,fiscal,{",".join(columns)} FROM research.annual_facts WHERE symbol=? AND endpoint IN '
            f'({",".join("?" * len(LEGACY))}) ORDER BY fiscal LIMIT ?', (symbol, *(endpoint for endpoint, _ in LEGACY), bound + 1)):
        count += 1
        if count > bound:
            raise ValueError('Prepared observation history exceeds its bound.')
        found.setdefault(fiscal, {})[endpoint] = dict(zip(columns, values))
    result = {}
    for fiscal, rows in found.items():
        values = {field: row[column] for endpoint, fields in LEGACY if (row := rows.get(endpoint))
                  for field, column in fields if row[column] is not None}
        if values:
            result[fiscal] = values
    return result


def ten_year(db, day):
    """(day, percent) of the latest valid 10-year Treasury value on or before day, or None."""
    row = db.execute('SELECT day,year10 FROM research.market_days WHERE day<=? AND year10 IS NOT NULL '
                     'ORDER BY day DESC LIMIT 1', (str(day),)).fetchone()
    return None if row is None else (row[0], row[1])


def sessions(db,market='us'):
    """The selected market's saved sessions in order; omitted market keeps SPY."""
    if market!='us':
        return [date.fromisoformat(row[0]) for row in db.execute('SELECT day FROM research.local_sessions WHERE market=? ORDER BY day',(market,))]
    return [date.fromisoformat(row[0]) for row in db.execute(
        'SELECT day FROM research.market_days WHERE spy IS NOT NULL ORDER BY day')]


class BookFacts:
    """One market's prepared facts for an operation.

    price() is native for valuation rescaling; usd_price() uses the actual
    price date's FX for holding returns. Annual amounts use the context date
    supplied to reports()/legacy_annual(). US arithmetic remains unchanged.
    """
    def __init__(self, db, market='us'):
        self.db,self.market=db,market
        self._annual,self._reports,self._cached,self._companies={},None,None,None
        self._native_reports=None;self._report_day=None;self._fx={};self._metadata={}
        self._currencies=None
        self._currency_users=None

    def reports(self, day=None, *, symbol=None):
        if self.market=='us':
            if self._reports is None:
                broad={}
                for company,fiscal,known,cap,ev,ebitda,earnings in self.db.execute(
                        'SELECT symbol,fiscal,known,market_cap,enterprise_value,ebitda,ebitda_yield FROM research.statements ORDER BY rowid'):
                    broad.setdefault(company,[]).append(dict(fiscal=date.fromisoformat(fiscal),known=date.fromisoformat(known),market_cap=cap,enterprise=ev,ebitda=ebitda,**{'yield':earnings}))
                for rows in broad.values():rows.sort(key=lambda row:row['fiscal'])
                self._reports=books.pools(broad)
            return self._reports if symbol is None else tuple({symbol:pool[symbol]} if symbol in pool else {} for pool in self._reports)
        if day is None:raise ValueError('Foreign reports require a context date.')
        day=date.fromisoformat(day) if isinstance(day,str) else day
        if self._reports is not None and self._report_day==day:
            return self._reports if symbol is None else tuple({symbol:pool[symbol]} if symbol in pool else {} for pool in self._reports)
        native=self._native();broad={}
        for company in ((symbol,) if symbol is not None else native):
            for fiscal,known,row in native.get(company,()):
                report=self._report(fiscal,known,row,day)
                if report is not None:broad.setdefault(company,[]).append(report)
        result=(broad,{})
        if symbol is None:self._report_day=day;self._reports=result
        return result

    def _native(self):
        """{symbol: [(fiscal, known, row)]} of this market's saved native reports, in fiscal order."""
        if self._native_reports is None:
            self._native_reports={}
            for row in self.db.execute('SELECT r.symbol,r.fiscal,r.known,r.currency,r.ebitda,r.debt,r.cash,r.fiscal_cap,c.currency,r.basis FROM research.foreign_reports r JOIN research.company_markets c USING(symbol) WHERE c.market=? ORDER BY r.symbol,r.fiscal',(self.market,)):
                self._native_reports.setdefault(row[0],[]).append((date.fromisoformat(row[1]),date.fromisoformat(row[2]),row))
        return self._native_reports

    def _report(self,fiscal,known,row,day):
        """One native report converted at the FX of day, as reports(day) admits it, or None."""
        _,_,_,currency,ebitda,debt,cash,cap,quote,basis=row
        if cap is None:return None
        quote_fx,report_fx=self.fx(quote,day),self.fx(currency,day)
        if quote_fx is None or report_fx is None:return None
        market_cap=cap*quote_fx[1];earnings=ebitda*report_fx[1]
        enterprise=market_cap+(debt-cash)*report_fx[1]
        if not all(math.isfinite(v) and v>0 for v in (market_cap,earnings,enterprise)):return None
        return dict(fiscal=fiscal,known=known,market_cap=market_cap,enterprise=enterprise,ebitda=earnings,**{'yield':earnings/enterprise},currency=currency,quote_currency=quote,fx_date=str(report_fx[0]),quote_fx_date=str(quote_fx[0]),availability_basis=basis)

    def reported(self):
        """The companies with a saved report in this market: the ones refold folds."""
        return self.reports()[0].keys() if self.market=='us' else self._native().keys()

    def report_at(self,symbol,day):
        """(statement, legacy annual values of its fiscal date) of the cached-pool report a book on day selects, or None.

        This equals rules.latest_statement over reports(day) and
        legacy_annual(symbol, day) of the selected fiscal date. A foreign company
        converts only the latest report that rules.selectable admits on day and
        converts, and only that fiscal date's values, with the same conversions.
        """
        if self.market=='us':
            statement=rules.latest_statement(self.reports()[0].get(symbol,()),day)
            return None if statement is None else (statement,self.legacy_annual(symbol).get(str(statement['fiscal']),{}))
        for fiscal,known,row in reversed(self._native().get(symbol,())):
            if rules.selectable(fiscal,known,day) and (statement:=self._report(fiscal,known,row,day)) is not None:
                return statement,self._converted(symbol,str(fiscal),self._saved_annual(symbol).get(str(fiscal),{}),day)
        return None

    def cached(self):
        if self._cached is None:
            self._cached={row[0] for row in self.db.execute("SELECT f.symbol FROM research.fact_sources f LEFT JOIN research.company_markets c USING(symbol) WHERE f.endpoint=? AND f.disposition!='missing' AND COALESCE(c.market,'us')=?",(STOCK,self.market))}
        return self._cached

    def companies(self):
        if self._companies is None:
            self._companies={symbol:bool(listed) for symbol,listed in self.db.execute("SELECT c.symbol,c.listed FROM research.companies c LEFT JOIN research.company_markets m USING(symbol) WHERE COALESCE(m.market,'us')=?",(self.market,))}
        return self._companies

    def price(self,symbol,day,forward=False,slack=None):
        """Native adjusted price and actual date, bounded by local sessions for foreign stocks."""
        operator,order=('>=','ASC') if forward else ('<=','DESC')
        session='' if self.market=='us' else _SESSION
        args=(symbol,str(day),*((self.market,) if self.market!='us' else ()))
        row=self.db.execute(f'SELECT day,adjusted FROM research.stock_days WHERE symbol=? AND day{operator}? AND adjusted IS NOT NULL{session} ORDER BY day {order} LIMIT 1',args).fetchone()
        if row is None:return None
        result=(date.fromisoformat(row[0]),row[1])
        return result if slack is None or abs((result[0]-day).days)<=slack else None

    def closes(self,symbol,start):
        """[(day, native adjusted close)] on or after start (every day when None), in day order: the closes price() reads."""
        session='' if self.market=='us' else _SESSION
        args=(symbol,'' if start is None else str(start),*((self.market,) if self.market!='us' else ()))
        return [(date.fromisoformat(day),close) for day,close in self.db.execute(
            f'SELECT day,adjusted FROM research.stock_days WHERE symbol=? AND day>=? AND adjusted IS NOT NULL{session} ORDER BY day',args)]

    def valuation(self,symbol,day):
        """(earnings, sales, equity, earnings_days, sales_days, equity_days): one company's valuation sums at its last row on or before day, or zeros."""
        row=self.db.execute('SELECT earnings,sales,equity,earnings_days,sales_days,equity_days FROM research.valuation_sums '
                            'WHERE symbol=? AND day<=? ORDER BY day DESC LIMIT 1',(symbol,str(day))).fetchone()
        return _NO_SUMS if row is None else tuple(row)

    def usd_price(self,symbol,day,forward=False,slack=None):
        price=self.price(symbol,day,forward,slack)
        if price is None or self.market=='us':return price
        value=self.convert(price[1],self.quote_currency(symbol),price[0])
        return None if value is None else (price[0],value)

    def quote_currency(self,symbol):
        if self._currencies is None:self._currencies=dict(self.db.execute('SELECT symbol,currency FROM research.company_markets WHERE market=?',(self.market,)))
        return self._currencies.get(symbol,'USD' if self.market=='us' else None)

    def currency_users(self):
        """Companies using each quote or annual-report currency across their history."""
        if self._currency_users is None:
            self._currency_users={}
            rows=self.db.execute('''SELECT symbol,currency FROM research.company_markets WHERE market=?
                UNION SELECT a.symbol,a.currency FROM research.annual_metadata a
                JOIN research.company_markets c USING(symbol) WHERE c.market=?''',(self.market,self.market))
            for symbol,currency in rows:self._currency_users.setdefault(currency,set()).add(symbol)
        return self._currency_users

    def fx(self,currency,day):
        """Prior completed daily USD-per-unit fixing, within seven days; no identity FX substitute."""
        day=date.fromisoformat(day) if isinstance(day,str) else day
        if currency=='USD':return day,1.
        key=currency,day
        if key not in self._fx:
            row=self.db.execute('SELECT day,usd FROM research.fx_days WHERE currency=? AND day<? AND usd IS NOT NULL ORDER BY day DESC LIMIT 1',(currency,str(day))).fetchone()
            self._fx[key]=None if row is None or (day-date.fromisoformat(row[0])).days>7 else (date.fromisoformat(row[0]),row[1])
        return self._fx[key]

    def convert(self,value,currency,day):
        fixing=self.fx(currency,day)
        if fixing is None or value is None:return None
        result=value*fixing[1]
        return result if math.isfinite(result) else None

    def annual_metadata(self,symbol,endpoint,fiscal):
        key=symbol,endpoint,str(fiscal)
        if key not in self._metadata:
            row=self.db.execute('SELECT currency,known,basis FROM research.annual_metadata WHERE symbol=? AND endpoint=? AND fiscal=?',key).fetchone()
            self._metadata[key]=None if row is None else dict(zip(('currency','known','basis'),row))
        return self._metadata[key]

    def session(self,day):
        if self.market=='us':return self.spy(day) is not None
        return self.db.execute('SELECT 1 FROM research.local_sessions WHERE market=? AND day=?',(self.market,str(day))).fetchone() is not None

    def spy_observation(self,day):
        """Completed SPY close; Asian lookbacks allow up to seven calendar days."""
        if self.market=='us':
            row=self.db.execute('SELECT day,spy FROM research.market_days WHERE day=? AND spy IS NOT NULL',(str(day),)).fetchone()
        else:
            row=self.db.execute('SELECT day,spy FROM research.market_days WHERE day<? AND day>=? AND spy IS NOT NULL ORDER BY day DESC LIMIT 1',(str(day),str(day-timedelta(days=7)))).fetchone()
        return None if row is None else (date.fromisoformat(row[0]),row[1])

    def spy(self,day):
        row=self.spy_observation(day)
        return None if row is None else row[1]

    def treasury(self,day):
        operator='<=' if self.market=='us' else '<'
        row=self.db.execute(f'SELECT month3 FROM research.market_days WHERE day{operator}? AND month3 IS NOT NULL ORDER BY day DESC LIMIT 1',(str(day),)).fetchone()
        return None if row is None else row[0]/100

    def ten_year(self,day):
        if self.market=='us':
            row=ten_year(self.db,day)
            return None if row is None else row[1]
        row=self.db.execute('SELECT year10 FROM research.market_days WHERE day<? AND year10 IS NOT NULL ORDER BY day DESC LIMIT 1',(str(day),)).fetchone()
        return None if row is None else row[0]

    def _saved_annual(self,symbol):
        if symbol not in self._annual:self._annual[symbol]=legacy_annual(self.db,symbol)
        return self._annual[symbol]

    def _converted(self,symbol,fiscal,values,day):
        """The legacy values of one fiscal date converted at day: only the fields known before day."""
        converted={}
        for field,value in values.items():
            info=self.annual_metadata(symbol,_ENDPOINTS[field],fiscal)
            if info is None or info['known']>=str(day):continue
            number=self.convert(value,info['currency'],day)
            if number is not None:converted[field]=number
        return converted

    def legacy_annual(self,symbol,day=None):
        annual=self._saved_annual(symbol)
        if self.market=='us':return annual
        if day is None:raise ValueError('Foreign annual values require a context date.')
        result={}
        for fiscal,values in annual.items():
            converted=self._converted(symbol,fiscal,values,day)
            if converted:result[fiscal]=converted
        return result
