"""Write the fictional raw dataset in fixtures/fictional/raw/.

Run `python3 proof/fixture.py` from the repository root. It replaces the folder
with files in the exact layout that preparation reads from `raw/`. Generation
is deterministic: prices and amounts come from `random.Random` seeded with
fixed strings, so a second run changes no byte.

All companies, names and symbols are fictional. Prices run on weekdays from
2015-12-01 to 2023-06-30: a span that gives 5-year valuation
averages, 3-year returns and an 800-day stale report inside the test window
(2021-07-01 to 2023-06-28). Annual reports end on 31 December (US, Hong Kong)
or 31 March (Tokyo).

Cases, and the company or date that carries each:

- Distinct and tied ranking values: QAC and QAD (US) have equal annual rows,
  so their operating margin ties; QAD comes first in metrics.jsonl, so it has
  the better legacy candidate rank and wins the tie although its symbol sorts
  later. 7101.T and 7102.T (Tokyo) have equal annual rows, so their profit
  margin ties; foreign rows have no candidate rank, so the symbol decides.
  Their prices differ, so the tie changes returns.
- Missing ranking value: QAA has no revenue (its operating-margin formula is
  unavailable); 130A.T has fewer than three annual reports (no 3-year
  EV/EBITDA).
- Missing filter value: QAB has no net income (no P/E average); 0103.HK pays
  no dividends (no dividend yield).
- Excluded symbols: 4101.HK (a 4xxx line), 80101.HK (a five-digit counter),
  1306.T (an ETF name) and A130.T (not a Tokyo symbol form) are in the saved
  lists with full data; preparation leaves them out. 130A.T is the admitted
  letter form. The US rules (a dot, an ETF name, an OTC exchange) apply when
  the universe is downloaded; preparation never re-filters the saved US list,
  so no saved US file carries them.
- Delisted company: QDL is not listed and its prices stop on 2022-08-12; a
  holding over that day exits at its last available price.
- Price spike: QSP closes at ten times its neighbours on 2019-05-15, so its
  whole price series is left out.
- Stale report: QST reports only through fiscal 2019, so from 2022-03-11 its
  last report is more than 800 days old.
- Conflicting and repeated annual rows: QCF has two income rows for fiscal
  2019 with different net income (conflicting), an exact repeat for fiscal
  2020 (agreeing) and a fiscal-2018 repeat with a null net income (a null never
  overrides). 0104.HK has fiscal-2020 income rows in HKD and USD (conflicting
  currency, so that report has no anchor).
- First-seen US key-metrics value: metrics.jsonl holds QFS twice; the later
  line keeps the first-seen fiscal-2019 values and adds fiscal 2020 to 2022,
  while key-metrics/QFS.json holds the provider's revised fiscal-2019 values.
- Publication dates: 0101.HK has a filing date after the fiscal date; 0102.HK
  has one equal to the fiscal date (not admitted, so fiscal + 4 months);
  7103.T has an accepted date; the others have none (fiscal + 4 or 3 months).
- FX gap: USDJPY has no fixing from 2021-06-21 to 2021-07-02, so on the
  first Tokyo book day, 2021-07-01, the last fixing is more than 7 days old:
  no Tokyo report converts and that period holds cash. A gap on a later book
  day would also void the USD exit price of the period that ends there, and
  the run would fail.
- Holidays: Hong Kong has no index row on 25-26 December, 1 May, 1 October and
  10-12 February, and a row on 1 January that the session rule refuses; Tokyo
  has no row on 1 January and 3-5 May, and rows on 2-3 January and
  31 December that the rule refuses. Foreign price files have rows on every
  weekday, holidays included. The US has no SPY row on 1 January, 4 July,
  Thanksgiving and 25 December.
- Skipped non-positive close: QPX closes at 0 on 2020-03-16.
- Currency mismatch: QPX has a EUR price row on 2020-09-15 and a CAD
  balance-sheet row for fiscal 2018.
- Dividends and volume: every company except 0103.HK pays common dividends;
  every price row has a volume.
- Sectors: US Industrials, Technology, Consumer Cyclical, Basic Materials,
  Consumer Defensive and Communication Services (QDL, delisted, has none);
  Hong Kong Financial Services, Real Estate and Utilities; Tokyo Industrials
  and Consumer Cyclical.
"""
from datetime import date, timedelta
import json
from pathlib import Path
import random
import shutil

RAW = Path(__file__).resolve().parents[1] / 'fixtures' / 'fictional' / 'raw'
FIRST, LAST = date(2015, 12, 1), date(2023, 6, 30)
LATE_FIRST = date(2020, 12, 1)  # first price day of the excluded lines


def weekdays(first=FIRST, last=LAST):
    day = first
    while day <= last:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def us_closed(day):
    thanksgiving = day.month == 11 and day.weekday() == 3 and 22 <= day.day <= 28
    return (day.month, day.day) in {(1, 1), (7, 4), (12, 25)} or thanksgiving


def hk_closed(day):
    return (day.month, day.day) in {(12, 25), (12, 26), (5, 1), (10, 1), (2, 10), (2, 11), (2, 12)}


def jp_closed(day):
    return (day.month, day.day) in {(1, 1), (5, 3), (5, 4), (5, 5)}


US_SESSIONS = [day for day in weekdays() if not us_closed(day)]
CURRENCY = {'us': 'USD', 'hk': 'HKD', 'jp': 'JPY'}

# symbol: market, name, exchange, sector, listed, first price, shares,
# first revenue, growth, operating margin, debt and cash as revenue shares,
# dividend payout, and the case flags that the writers below read.
COMPANIES = {
    'QAA': ('us', 'Quartz Alder Holdings', 'NYSE', 'Industrials', 40, 80e6, 2.0e9, .05, .12, .4, .1, .3, {'no_revenue'}),
    'QAB': ('us', 'Quartz Birch Systems', 'NASDAQ', 'Technology', 25, 120e6, 1.5e9, .08, .18, .2, .3, .2, {'no_net_income'}),
    'QAC': ('us', 'Quartz Cedar Tools', 'NYSE', 'Industrials', 30, 90e6, 1.8e9, .04, .20, .3, .1, .3, {'twin'}),
    'QAD': ('us', 'Quartz Dogwood Tools', 'NYSE', 'Industrials', 32, 90e6, 1.8e9, .04, .20, .3, .1, .3, {'twin'}),
    'QDL': ('us', 'Quartz Delta Energy', 'NYSE', '', 18, 150e6, 2.5e9, .03, .30, .6, .05, .4, {'delisted'}),
    'QSP': ('us', 'Quartz Spire Retail', 'NASDAQ', 'Consumer Cyclical', 22, 100e6, 3.0e9, .03, .08, .3, .1, .3, {'spike'}),
    'QST': ('us', 'Quartz Stale Mining', 'AMEX', 'Basic Materials', 3, 20e6, 0.2e9, .02, .28, .5, .05, .2, {'stale'}),
    'QFS': ('us', 'Quartz Fern Software', 'NASDAQ', 'Technology', 50, 60e6, 1.2e9, .10, .16, .1, .4, .1, {'first_seen'}),
    'QCF': ('us', 'Quartz Copper Foods', 'NYSE', 'Consumer Defensive', 28, 110e6, 2.2e9, .03, .14, .3, .1, .5, {'conflict'}),
    'QPX': ('us', 'Quartz Pixel Media', 'NASDAQ', 'Communication Services', 15, 200e6, 1.6e9, .06, .15, .2, .2, .2, {'bad_rows'}),
    '0101.HK': ('hk', 'Harbour Lantern Bank', 'HKSE', 'Financial Services', 60, 900e6, 20e9, .04, .30, .8, .3, .4, {'published'}),
    '0102.HK': ('hk', 'Harbour Pine Estates', 'HKSE', 'Real Estate', 12, 2000e6, 9e9, .03, .35, .9, .1, .5, {'same_day_filing'}),
    '0103.HK': ('hk', 'Harbour Tide Power', 'HKSE', 'Utilities', 35, 800e6, 12e9, .02, .25, .7, .1, 0, set()),
    '0104.HK': ('hk', 'Harbour Kite Land', 'HKSE', 'Real Estate', 8, 3000e6, 10e9, .03, .32, .9, .2, .3, {'currency_conflict'}),
    '0105.HK': ('hk', 'Harbour Reed Water', 'HKSE', 'Utilities', 20, 1000e6, 8e9, .03, .28, .6, .1, .45, set()),
    '4101.HK': ('hk', 'Harbour Line of Quartz Alder', 'HKSE', 'Industrials', 5, 3000e6, 30e9, .05, .40, .1, .3, .3, {'excluded'}),
    '80101.HK': ('hk', 'Harbour Lantern Bank RMB counter', 'HKSE', 'Financial Services', 6, 900e6, 20e9, .04, .45, .1, .3, .4, {'excluded'}),
    '7101.T': ('jp', 'Kumo Gear Works', 'JPX', 'Industrials', 2400, 50e6, 300e9, .03, .12, .3, .2, .3, {'twin'}),
    '7102.T': ('jp', 'Kumo Gear Systems', 'JPX', 'Industrials', 2600, 48e6, 300e9, .03, .12, .3, .2, .3, {'twin'}),
    '7103.T': ('jp', 'Sora Kitchen', 'JPX', 'Consumer Cyclical', 1800, 80e6, 250e9, .05, .16, .2, .3, .25, {'published'}),
    '7104.T': ('jp', 'Mori Rail Parts', 'JPX', 'Industrials', 900, 120e6, 200e9, .02, .08, .4, .1, .35, set()),
    '130A.T': ('jp', 'Hoshi Apparel', 'JPX', 'Consumer Cyclical', 1500, 30e6, 60e9, .10, .14, .1, .3, .1, {'new'}),
    '1306.T': ('jp', 'Sakura Index ETF Units', 'JPX', 'Financial Services', 2000, 400e6, 100e9, .02, .50, .1, .1, .3, {'excluded'}),
    'A130.T': ('jp', 'Hoshi Apparel Class B', 'JPX', 'Consumer Cyclical', 1400, 30e6, 60e9, .10, .50, .1, .3, .1, {'excluded'}),
}
TWIN_SEED = {'QAC': 'QAC', 'QAD': 'QAC', '7101.T': '7101.T', '7102.T': '7101.T'}


def save(relative, value):
    path = RAW / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(',', ':')) + '\n', encoding='utf-8')


def walk(seed, days, start, low=-200, high=215):
    """{day: price} of a deterministic random walk, rounded as a provider would."""
    rng = random.Random(seed)
    value, result = float(start), {}
    for day in days:
        value *= 1 + rng.randint(low, high) / 10000
        result[day] = round(value, 4)
    return result


def price_days(symbol, market):
    flags = COMPANIES[symbol][-1]
    first = date(2021, 4, 1) if 'new' in flags else LATE_FIRST if 'excluded' in flags else FIRST
    last = date(2022, 8, 12) if 'delisted' in flags else LAST
    days = US_SESSIONS if market == 'us' else list(weekdays())
    return [day for day in days if first <= day <= last]


def last_close(prices, day):
    return prices[max(d for d in prices if d <= day)]


def fiscal_dates(symbol, market):
    flags = COMPANIES[symbol][-1]
    if market == 'jp':
        years = range(2022, 2024) if 'new' in flags else range(2021, 2024) if 'excluded' in flags else range(2016, 2024)
        return [date(year, 3, 31) for year in years]
    last = 2019 if 'stale' in flags else 2021 if 'delisted' in flags else 2022
    first = 2020 if 'excluded' in flags else 2015
    return [date(year, 12, 31) for year in range(first, last + 1)]


def write_company(symbol, metrics):
    market, name, exchange, sector, price, shares, revenue, growth, margin, debt, cash, payout, flags = COMPANIES[symbol]
    currency = CURRENCY[market]
    days = price_days(symbol, market)
    prices = walk('price:' + symbol, days, price)
    if 'spike' in flags:
        prices[date(2019, 5, 15)] = round(prices[date(2019, 5, 15)] * 10, 4)
    volumes = random.Random('volume:' + symbol)
    rows = []
    for day in reversed(days):
        row = dict(date=str(day), adjClose=prices[day], volume=volumes.randint(20, 400) * 1000)
        if 'bad_rows' in flags and day == date(2020, 3, 16):
            row['adjClose'] = 0.0
        if 'bad_rows' in flags and day == date(2020, 9, 15):
            row['currency'] = 'EUR'
        rows.append(row)
    save(f'px/{symbol}.json', dict(div=rows))
    if market != 'us':
        # Native closes carry the dividend adjustment that the adjusted series removes.
        save(f'px-full/{symbol}.json', [dict(date=str(day), close=round(prices[day] * (1 + (LAST - day).days / 36500), 3))
                                       for day in reversed(days)])
    annual = random.Random('annual:' + TWIN_SEED.get(symbol, symbol))
    income, balance, cash_flow, key_metrics = [], [], [], []
    level = revenue
    for fiscal in fiscal_dates(symbol, market):
        level *= 1 + growth + annual.randint(-20, 20) / 1000
        sales = round(level)
        operating = round(sales * (margin + annual.randint(-15, 15) / 1000))
        ebitda = round(operating * 1.25)
        net = round(operating * .75)
        base = dict(date=str(fiscal), symbol=symbol, reportedCurrency=currency, period='FY')
        if 'published' in flags:
            base['filingDate' if market == 'hk' else 'acceptedDate'] = str(fiscal + timedelta(days=80))
        if 'same_day_filing' in flags:
            base['filingDate'] = str(fiscal)
        row = dict(base, revenue=sales, operatingIncome=operating, ebit=operating, ebitda=ebitda,
                   netIncome=net, eps=round(net / shares, 2), epsDiluted=round(net / shares * .98, 2),
                   interestExpense=round(sales * debt * .04), weightedAverageShsOut=round(shares))
        if 'no_revenue' in flags:
            del row['revenue']
        if 'no_net_income' in flags:
            del row['netIncome']
        income.append(row)
        if 'conflict' in flags and fiscal.year == 2019:
            income.append(dict(row, netIncome=net + 7_000_000))
        if 'conflict' in flags and fiscal.year == 2020:
            income.append(dict(row))
        if 'conflict' in flags and fiscal.year == 2018:
            income.append(dict(row, netIncome=None))
        if 'currency_conflict' in flags and fiscal.year == 2020:
            income.append(dict(row, reportedCurrency='USD', revenue=round(sales / 7.8)))
        borrowing, holding = round(sales * debt), round(sales * cash)
        equity = round(sales * .6)
        balance.append(dict(base, totalStockholdersEquity=equity, totalCurrentAssets=round(sales * .5),
                            totalCurrentLiabilities=round(sales * .3), totalDebt=borrowing,
                            cashAndCashEquivalents=holding,
                            **({'reportedCurrency': 'CAD'} if 'bad_rows' in flags and fiscal.year == 2018 else {})))
        flow = dict(base, freeCashFlow=round(net * .9))
        if payout:
            flow['commonDividendsPaid'] = -round(net * payout)
        cash_flow.append(flow)
        if market == 'us':
            if 'twin' in flags:
                cap = round(shares * 31.0 * (1 + (fiscal.year - 2015) / 20))
            else:
                cap = round(shares * last_close(prices, fiscal))
            enterprise = cap + borrowing - holding
            key_metrics.append(dict(date=str(fiscal), symbol=symbol, reportedCurrency='USD', period='FY',
                                    marketCap=cap, enterpriseValue=enterprise, evToEBITDA=enterprise / ebitda))
    for endpoint, values in (('income-statement', income), ('balance-sheet-statement', balance),
                             ('cash-flow-statement', cash_flow)):
        save(f'financial-inputs/{endpoint}/{symbol}.json',
             dict(version=2, full_response=True, symbol=symbol, endpoint=endpoint, rows=list(reversed(values))))
    if market == 'us':
        provider = [dict(row) for row in key_metrics]
        if 'first_seen' in flags:
            # The provider later revised fiscal 2019; the saved line keeps the first-seen values.
            revised = next(row for row in provider if row['date'] == '2019-12-31')
            revised.update(marketCap=round(revised['marketCap'] * 1.1), evToEBITDA=revised['evToEBITDA'] * 1.1,
                           enterpriseValue=revised['enterpriseValue'] + round(revised['marketCap'] * .1))
        save(f'financial-inputs/key-metrics/{symbol}.json',
             dict(version=2, full_response=True, symbol=symbol, endpoint='key-metrics', rows=list(reversed(provider))))
        metrics[symbol] = list(reversed(key_metrics))
    return dict(symbol=symbol, name=name, exchange=exchange, sector=sector, listed='delisted' not in flags,
                **({} if market == 'us' else dict(market=market, currency=currency)))


def main():
    if RAW.exists():
        shutil.rmtree(RAW)
    RAW.mkdir(parents=True)
    metrics, universes = {}, {'us': [], 'hk': [], 'jp': []}
    for symbol, spec in COMPANIES.items():
        universes[spec[0]].append(write_company(symbol, metrics))
    save('universe.json', universes['us'])
    for market in ('hk', 'jp'):
        save(f'markets/{market}/universe.json', universes[market])
    # metrics.jsonl: QFS's first-seen line comes first, QAD before QAC, and QFS's
    # later line (first-seen fiscal 2019 kept, later years added) last.
    order = ['QAA', 'QAB', 'QAD', 'QAC', 'QDL', 'QSP', 'QST', 'QCF', 'QPX']
    lines = [dict(symbol='QFS', rows=[row for row in metrics['QFS'] if row['date'] <= '2019-12-31'], full_response=True)]
    lines += [dict(symbol=symbol, rows=metrics[symbol], full_response=True) for symbol in order]
    lines.append(dict(symbol='QFS', rows=lines[0]['rows'] + [row for row in metrics['QFS'] if row['date'] > '2019-12-31'],
                      full_response=True))
    (RAW / 'metrics.jsonl').write_text(''.join(json.dumps(line, separators=(',', ':')) + '\n' for line in lines),
                                       encoding='utf-8')
    spy = walk('spy', US_SESSIONS, 200, -150, 170)
    save('spy-div.json', [dict(date=str(day), adjClose=spy[day]) for day in reversed(US_SESSIONS)])
    rates = random.Random('treasury')
    month3 = year10 = 1.5
    treasury = []
    for day in US_SESSIONS:
        month3 = min(5.5, max(.02, round(month3 + rates.randint(-3, 3) / 100, 2)))
        year10 = min(5.0, max(.5, round(year10 + rates.randint(-3, 3) / 100, 2)))
        treasury.append(dict(date=str(day), month3=month3, year10=year10))
    save('treasury.json', list(reversed(treasury)))
    for market, closed, start in (('hk', hk_closed, 22000), ('jp', jp_closed, 19000)):
        days = [day for day in weekdays() if not closed(day)]
        index = walk('index:' + market, days, start, -150, 160)
        save(f'markets/{market}/calendar.json', [dict(date=str(day), close=index[day]) for day in reversed(days)])
    gap = (date(2021, 6, 21), date(2021, 7, 2))
    for currency, start, low, high in (('HKD', 7.8, -5, 5), ('JPY', 120, -60, 62)):
        days = [day for day in weekdays() if not (currency == 'JPY' and gap[0] <= day <= gap[1])]
        fixings = walk('fx:' + currency, days, start, low, high)
        save(f'fx/USD{currency}.json', [dict(date=str(day), close=fixings[day]) for day in reversed(days)])
    files = [path for path in RAW.rglob('*') if path.is_file()]
    print(f'Wrote {len(files)} files, {sum(path.stat().st_size for path in files) / 1e6:.2f} MB, in {RAW}')


if __name__ == '__main__':
    main()
