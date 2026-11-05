"""A complete fictional workspace copied from private source. No real data.

Fixture allowances catch runaway fixture growth. They are not capacity limits.
"""

from datetime import date, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

MIB = 1024**2

# Allowances catch runaway fixture growth; they are not capacity limits. Keep
# them well above the largest measured workspace.
ALLOWANCES = dict(raw=64*MIB, database=512*MIB, website=64*MIB,
                  history=32*MIB, control=16*MIB, downloads=16*MIB, total=2048*MIB)
SPEC = dict(companies=64, first='1992-01-01', through='2026-10-21',
            fiscal_first=1992, fiscal_last=2025, calendar='fictional weekdays')
_retained_workspaces = {}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(',', ':'), allow_nan=False), encoding='utf-8')


class FictionalWorkspace:
    """Create a complete fictional workspace from an explicit source inventory
    and saved-input specification. Prepared databases, baseline reports and
    website output are produced only by the copied application's ordinary
    preparation and build functions.
    """
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='fictional-workspace-')
        self.root = Path(self.temporary.name)
        self.source = self.root / 'application'
        self._owners = []
        self.closed = False
        self.sources = {}
        for folder in ('scripts', 'website', 'backtest'):
            for path in sorted((ROOT / folder).rglob('*')):
                if any(part in ('local','dist','__pycache__','node_modules','.openai') for part in path.relative_to(ROOT/folder).parts):
                    continue
                if not path.is_file() or not (path.suffix in ('.py','.js','.css','.html')):
                    continue
                assert not path.is_symlink()
                relative = path.relative_to(ROOT)
                target = self.source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                self.sources[relative.as_posix()] = sha(target)
        self._generate()
        self.inputs = self.input_inventory()
        write(self.root / 'specification.json', dict(specification=SPEC, allowances=ALLOWANCES,
                                                    sources=self.sources, inputs=self.inputs))
        self.inventory()

    def _generate(self):
        raw = self.source / 'raw'
        sessions = []
        day = date.fromisoformat(SPEC['first'])
        through = date.fromisoformat(SPEC['through'])
        while day <= through:
            if day.weekday() < 5: sessions.append(day.isoformat())
            day += timedelta(days=1)
        universe, metrics, ledger = [], [], {}
        exchanges = ('NYSE', 'NASDAQ', 'AMEX')
        sectors = ('Technology', 'Energy', 'Industrials', 'Health Care')
        for index in range(SPEC['companies']):
            symbol = 'ZZ%03d' % index
            universe.append(dict(symbol=symbol, name='Fictional Company %03d' % index,
                exchange=exchanges[index % 3], sector=sectors[index % 4], listed=True))
            annual = [dict(symbol=symbol, date='%d-06-30' % year, reportedCurrency='USD',
                marketCap=300e6+index*10e6, enterpriseValue=350e6+index*10e6,
                evToEBITDA=3.+index*.1+(year-1992)*.002)
                for year in range(SPEC['fiscal_first'], SPEC['fiscal_last']+1)]
            metrics.append(dict(symbol=symbol, rows=annual))
            # Observations are fictional inputs, not an oracle for calculations.
            # Alternating cycles give positive and negative holding periods.
            prices = [dict(date=day, adjClose=round(20+index*.3+n*.001+
                2*math.sin(n/190.+index), 6)) for n,day in enumerate(sessions)]
            write(raw/'px'/(symbol+'.json'), dict(div=prices))
            for endpoint in ('income-statement', 'balance-sheet-statement',
                             'cash-flow-statement', 'key-metrics', 'ratios'):
                rows = []
                for report in annual:
                    year = int(report['date'][:4])
                    row = dict(symbol=symbol, date=report['date'], period='FY',
                               reportedCurrency='USD', filingDate='%d-08-15' % year)
                    if endpoint == 'income-statement':
                        row.update(revenue=200e6, netIncome=20e6+index*1e5,
                            epsDiluted=None if index==63 else 1.+(year-1992)*.1,
                            ebit=30e6, interestExpense=2e6)
                    elif endpoint == 'balance-sheet-statement':
                        row.update(totalStockholdersEquity=200e6, totalCurrentAssets=90e6,
                                   totalCurrentLiabilities=30e6, totalDebt=60e6)
                    elif endpoint == 'cash-flow-statement': row['freeCashFlow']=(index-8)*1e6
                    else: row.update(report)
                    rows.append(row)
                path = raw/'financial-inputs'/endpoint/(symbol+'.json')
                write(path, dict(version=2, full_response=True, symbol=symbol, endpoint=endpoint, rows=rows))
                ledger[path.relative_to(raw).as_posix()] = dict(sha256=sha(path))
        write(raw/'universe.json', universe)
        (raw/'metrics.jsonl').write_text(''.join(json.dumps(row, separators=(',', ':'))+'\n'
                                               for row in metrics), encoding='utf-8')
        write(raw/'spy-div.json', [dict(date=day, adjClose=round(100+n*.01,6))
                                  for n,day in enumerate(sessions)])
        write(raw/'treasury.json', [dict(date=day, month3=2.) for day in sessions])
        write(raw/'download-coverage.json', ledger)
        (self.source/'results').mkdir()
        (self.source/'results/summary-exits.txt').write_text('Fictional bootstrap only.\nThrough 2026-10-21\n', encoding='utf-8')
        (self.source/'data').mkdir(exist_ok=True)
        (self.root/'downloads').mkdir()

    def input_inventory(self):
        return {p.relative_to(self.source).as_posix(): sha(p)
                for p in sorted((self.source/'raw').rglob('*')) if p.is_file()}

    def own(self, owner):
        """Retain every registered owner until it confirms closure.

        Uncertain closure preserves this workspace and its cleanup dependencies
        for explicit retry. Register before the owner can create effects.
        """
        if self.closed or owner is self:raise ValueError('Fictional ownership is closed or recursive.')
        if not callable(getattr(owner,'close',None)) or not hasattr(owner,'closed'):
            raise TypeError('Fixture dependencies must confirm closure.')
        if not any(value is owner for value in self._owners):self._owners.append(owner)
        return owner

    def inventory(self):
        """Check logical bytes and immutable source; this is not a disk quota."""
        files = []
        for p in self.root.rglob('*'):
            assert not p.is_symlink(), 'Unexpected fixture symlink.'
            if p.is_file(): files.append((p, p.stat().st_size))
        assert all(sha(self.source/n)==s for n,s in self.sources.items())
        size = lambda root: sum(n for p,n in files if p.is_relative_to(root))
        result = dict(total=sum(n for _,n in files), raw=size(self.source/'raw'),
            website=size(self.source/'website/local'), history=size(self.source/'results/baseline-history'),
            control=sum(n for p,n in files if not p.is_relative_to(self.source) and p.suffix!='.sqlite'),
            downloads=size(self.root/'downloads'), databases={p.name:n for p,n in files
                if p.parent==self.source/'data' and p.suffix=='.sqlite'})
        for name in ('total','raw','website','history','control','downloads'):
            assert result[name] <= ALLOWANCES[name], (name,result[name],ALLOWANCES[name])
        for p,n in files:
            if p.suffix=='.sqlite':
                assert n <= ALLOWANCES['database'], ('database',p.name,n,ALLOWANCES['database'])
        return result

    def close(self):
        if self.closed:return
        try:
            for owner in reversed(self._owners):
                owner.close()
                if not owner.closed:raise AssertionError('Fixture dependency closure is unconfirmed.')
        except BaseException:
            self.temporary._finalizer.detach()
            _retained_workspaces[id(self)]=self
            raise
        self.inventory()
        self.temporary.cleanup()
        self.closed=True
        _retained_workspaces.pop(id(self),None)

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


def dependency_guard(source):
    """Reject ambient application opens and provider sockets in this interpreter.

    It is a Python dependency check, not a hostile native-code sandbox.
    """
    import sysconfig
    from urllib.parse import urlsplit, parse_qsl
    from urllib.request import url2pathname
    roots = (source.parent, ROOT/'tests', ROOT/'tools',
        *(Path(sysconfig.get_path(k)).resolve() for k in ('stdlib','platstdlib','purelib','platlib')))
    def audit(event,args):
        if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
            # Ordinary rebuild redirects child output to the fixed null device.
            if os.fsdecode(args[0])==os.devnull:return
            path=Path(os.fsdecode(args[0])).resolve()
            mode,flags=args[1:3]
            writing=isinstance(mode,str) and any(c in mode for c in 'wax+') or flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)
            allowed=(source.parent,) if writing else roots
            if not any(path.is_relative_to(root) for root in allowed):
                if writing or os.name=='nt' or not any(path.is_relative_to(p) for p in (Path('/proc'),Path('/sys'))):
                    raise AssertionError('Ambient fictional-workspace dependency.')
        elif event=='sqlite3.connect':
            value=os.fsdecode(os.fspath(args[0]))
            if value==':memory:':return
            if not value:raise AssertionError('Unsupported fictional SQLite dependency.')
            if value.startswith('file:'):
                uri=urlsplit(value)
                query=parse_qsl(uri.query,keep_blank_values=True,strict_parsing=True)
                allowed={'mode':{'ro','rw','rwc'},'cache':{'private','shared'},'immutable':{'0','1'}}
                if (uri.netloc or uri.fragment or not uri.path.startswith('/')
                        or any(k not in allowed or v not in allowed[k] for k,v in query)
                        or len({k for k,_ in query})!=len(query)):
                    raise AssertionError('Unsupported fictional SQLite URI.')
                value=url2pathname(uri.path)
            if not Path(value).resolve().is_relative_to(source.parent):
                raise AssertionError('Ambient fictional SQLite dependency.')
        elif event in ('socket.connect','socket.bind'):
            address=args[1]
            if isinstance(address,tuple) and (address[0]!='127.0.0.1' or event=='socket.bind' and address[1]!=0):
                raise AssertionError('Provider or nonfixture socket dependency.')
    sys.addaudithook(audit)


def assert_package_source(source):
    """Every loaded package module belongs to the acquired private source."""
    loaded=[module for name,module in sys.modules.items()
            if name in ('backtest','website') or name.startswith(('backtest.','website.'))]
    assert loaded
    assert all(Path(module.__file__).resolve().is_relative_to(source) for module in loaded)
