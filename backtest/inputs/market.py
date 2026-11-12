"""The three supported stock markets and their saved inputs. No network access."""
from calendar import monthrange
from datetime import timedelta
from pathlib import Path
import re
import urllib.parse

from backtest.paths import RAW
from backtest.financial import rules

MARKETS = {
    'us': dict(label='United States', currency='USD', exchanges=('NYSE','NASDAQ','AMEX'), index='SPY', report_months=None),
    'hk': dict(label='Hong Kong', currency='HKD', exchanges=('HKSE',), index='^HSI', report_months=4),
    'jp': dict(label='Japan — Tokyo', currency='JPY', exchanges=('JPX',), index='^N225', report_months=3),
}


def require(value='us'):
    """Return one supported market id; omitted recorded settings mean US."""
    if not isinstance(value,str) or value not in MARKETS:
        raise ValueError('Choose United States, Hong Kong or Japan.')
    return value


def identify(company):
    """The market recorded in an inventory, or its recognized listing exchange."""
    if company.get('market') is not None:return require(company['market'])
    exchange=str(company.get('exchangeShortName') or company.get('exchange') or '').upper()
    if exchange=='HKSE' or 'HONG KONG' in exchange:return 'hk'
    if exchange=='JPX' or 'TOKYO' in exchange:return 'jp'
    return 'us'


def common_stock(symbol,name='',market='us',**metadata):
    market=require(market)
    if metadata.get('isEtf') or metadata.get('isFund'):return False
    if market=='us':return rules.common_stock(symbol,name)
    # HK's five-digit RMB counters duplicate an HKD share; funds/warrants are not common stocks.
    # HK's 4xxx codes are bonds and US companies' dormant HK lines (stale prices, global share counts).
    pattern=r'[0-35-9][0-9]{3}\.HK' if market=='hk' else r'(?:[0-9]{4}|[0-9]{3}[A-Z])\.T'
    return bool(re.fullmatch(pattern,symbol or '')) and not any(
        token in (' '+(name or '').upper()+' ') for token in (' ETF ',' FUND ',' ETN '))


def cache_path_for(symbol: str) -> Path:
    safe = urllib.parse.quote(symbol, safe='')
    return RAW / 'px' / f'{safe}.json'


def raw_directory(raw,market='us'):
    return Path(raw) if require(market)=='us' else Path(raw)/'markets'/market


def universe_path(raw,market='us'):
    return raw_directory(raw,market)/'universe.json'


def calendar_path(raw,market='us'):
    return Path(raw)/'spy-div.json' if require(market)=='us' else raw_directory(raw,market)/'calendar.json'


def fx_path(raw,currency):
    return Path(raw)/'fx'/('USD'+currency+'.json')


def available(fiscal,market='us',publication=None):
    """The report's known date: US's unchanged lag, or a foreign publication/default."""
    if require(market)=='us':return fiscal+rules.LAG,'fiscal-plus-90'
    published=rules.parse_day(publication)
    if published and published>fiscal:return published,'publication-date'
    absolute=fiscal.year*12+fiscal.month-1+MARKETS[market]['report_months']
    year,month=divmod(absolute,12);month+=1
    return fiscal.replace(year=year,month=month,day=min(fiscal.day,monthrange(year,month)[1])), 'fiscal-plus-months'


def native_path(raw,symbol):
    return Path(raw)/'px-full'/cache_path_for(symbol).name


def completed_session(day,market_id):
    """Whether a dated index row can name a completed local stock session."""
    from datetime import datetime, timezone
    if day.weekday()>4:return False
    if market_id=='jp' and ((day.month==1 and day.day<=3) or (day.month==12 and day.day==31)):return False
    if market_id=='hk' and day.month==1 and day.day==1:return False
    offset=8 if market_id=='hk' else 9
    local=datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=offset)))
    closing=(16,0) if market_id=='hk' else (15,30)
    return day<local.date() or day==local.date() and (local.hour,local.minute)>=closing
