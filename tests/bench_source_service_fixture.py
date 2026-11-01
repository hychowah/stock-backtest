"""Complete fictional source-root qualification. No real data or admission.

Fixture allowances bound this verification exercise. They neither modify
captured-execution limits nor qualify production capacity, installed
compatibility, browser resources or real benchmark admission.
"""

from contextlib import closing
from datetime import date, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
from bench_service_fixture import SyntheticService, _pending_services

MIB = 1024**2
ALLOWANCES = dict(raw=64*MIB, database=128*MIB, website=64*MIB,
                  history=32*MIB, control=16*MIB, downloads=16*MIB, total=512*MIB)
SPEC = dict(companies=64, first='1992-01-01', through='2026-10-21',
            fiscal_first=1992, fiscal_last=2025, calendar='fictional weekdays')
_retained_workspaces = {}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(',', ':'), allow_nan=False), encoding='utf-8')


def copy_native(destination):
    """Borrow immutable compiler bytes through fixture-owned hard-link names."""
    native=ROOT/'data/numerical-native'
    if not (native/'installation.json').is_file():return 0
    target=Path(destination)/'data/numerical-native';target.mkdir(parents=True)
    shutil.copy2(native/'installation.json',target/'installation.json')
    directory=json.loads((native/'installation.json').read_bytes())['directory']
    def link(source,destination):
        try:os.link(source,destination)
        except OSError:shutil.copy2(source,destination)
    shutil.copytree(native/'toolchains'/directory,target/'toolchains'/directory,copy_function=link)
    return sum(p.stat().st_size for p in target.rglob('*') if p.is_file())


class FictionalWorkspace:
    """Create a complete fictional workspace from an explicit source inventory
    and saved-input specification. Prepared databases, baseline reports and
    website output are produced only by the copied application's ordinary
    preparation and build functions.
    """
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='cb02-source-service-')
        self.root = Path(self.temporary.name)
        self.source = self.root / 'application'
        self._owners = []
        self.closed = False
        self.sources = {}
        for folder in ('scripts', 'website', 'backtest'):
            for path in sorted((ROOT / folder).rglob('*')):
                if any(part in ('local','dist','__pycache__','node_modules','.openai') for part in path.relative_to(ROOT/folder).parts):
                    continue
                if not path.is_file() or not (path.suffix in ('.py','.js','.css','.html') or path.relative_to(ROOT).as_posix()=='backtest/engines/numerical/rust_kernel.rs'):
                    continue
                assert not path.is_symlink()
                relative = path.relative_to(ROOT)
                target = self.source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                self.sources[relative.as_posix()] = sha(target)
        dependency_file = ROOT / 'requirements-numerical.txt'
        shutil.copy2(dependency_file, self.source / dependency_file.name)
        self.sources[dependency_file.name] = sha(self.source / dependency_file.name)
        # The selected application path must prepare and run without Rust.
        # Direct comparison-only Rust fixtures may explicitly copy_native().
        self.native_components_bytes=0
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

    def capture_prepared(self):
        """Capture this fictional workspace only after its service has confirmed
        closure. Reuse the offline capture owner to preserve actual prepared
        metadata, source identity and report binding. Never prepare or repair
        inputs during capture.
        """
        if any(isinstance(owner,SourceService) and not owner.closed for owner in self._owners):
            raise AssertionError('Close the fictional service before offline capture.')
        if any(service.fixture is self and not service.closed for service in _pending_services.values()):
            raise AssertionError('Unconfirmed service closure blocks offline capture.')
        import tools.experiments.bench_capture_offline as bench_capture_offline
        before=self.input_inventory()
        report=sha(self.source/'results/summary-exits.txt')
        capture=bench_capture_offline.capture_offline(self.source,self.source/'tmp'/'combined-capture')
        assert before==self.input_inventory()
        assert report==sha(self.source/'results/summary-exits.txt')
        self.inventory()
        return capture

    def inventory(self):
        """Check logical bytes and immutable source; this is not a disk quota."""
        files = []
        for p in self.root.rglob('*'):
            assert not p.is_symlink(), 'Unexpected fixture symlink.'
            if p.is_file(): files.append((p, p.stat().st_size))
        assert all(sha(self.source/n)==s for n,s in self.sources.items())
        size = lambda root: sum(n for p,n in files if p.is_relative_to(root))
        native=size(self.source/'data/numerical-native')
        assert native<=self.native_components_bytes+64*MIB, ('native fixture components plus build allowance',native)
        result = dict(total=sum(n for _,n in files)-native, native=native, raw=size(self.source/'raw'),
            website=size(self.source/'website/local'), history=size(self.source/'results/baseline-history'),
            control=sum(n for p,n in files if not p.is_relative_to(self.source) and p.suffix!='.sqlite'),
            downloads=size(self.root/'downloads'), databases={p.name:n for p,n in files
                if p.parent==self.source/'data' and p.suffix=='.sqlite'})
        for name in ('total','raw','website','history','control','downloads'):
            assert result[name] <= ALLOWANCES[name], (name,result[name],ALLOWANCES[name])
        assert all(n<=ALLOWANCES['database'] for p,n in files if p.suffix=='.sqlite')
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
        if any(s.fixture is self and not s.closed for s in _pending_services.values()):
            self.temporary._finalizer.detach()
            _retained_workspaces[id(self)]=self
            raise AssertionError('Unconfirmed service closure retains the fictional workspace.')
        self.inventory()
        self.temporary.cleanup()
        self.closed=True
        _retained_workspaces.pop(id(self),None)

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class SourceService(SyntheticService):
    """Own one disposable source service from pre-import source ownership through
    closure of data jobs, request threads, listener, descendants and transport.
    Readiness means ordinary preparation and building succeeded before the
    loopback listener was published.
    """
    start_seconds = 180.
    client_seconds = 60.
    close_seconds = 15.
    max_response = 16*MIB

    def __init__(self, workspace, **scenario):
        super().__init__(workspace, dict(source=str(workspace.source), sources=workspace.sources), **scenario)
        workspace.own(self)

    def command(self, path):
        return [sys.executable, '-X', 'utf8', '-I', '-B', '-c',
            'import sys;sys.path[:0]=sys.argv[1:3];from bench_source_service_fixture import child;child(sys.argv[3])',
            str(ROOT/'tests'), str(ROOT), str(path)]

    def limits(self):
        from backtest.runtime.process_owner import ProcessLimits
        return ProcessLimits(2*1024**3, 16, 25, user_cpu_seconds=180., close_seconds=5.)

    def restart(self):
        self.close()
        return SourceService(self.fixture).start()

    def job(self, action, payload=None):
        self.request('POST', '/api/data/'+action, payload or {}, status=202)
        until = time.monotonic()+self.client_seconds
        while time.monotonic()<until:
            state=self.request('GET','/api/data/status')
            if not state['job']['running']:
                assert state['job']['error'] is None, state['job']
                return state
            time.sleep(.01)
        raise TimeoutError('Fictional data job deadline expired.')


def dependency_guard(source):
    """Reject ambient application opens and provider sockets in each interpreter.

    Build subprocesses use this same guard through a private sitecustomize.
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


def guarded_environment(source):
    """Give ordinary Python children the same tested dependency boundary."""
    guard=source.parent/'guard';guard.mkdir(exist_ok=True)
    (guard/'sitecustomize.py').write_text('import sys\nsys.path[:0]='+repr([str(ROOT/'tests'),str(ROOT)])+ '\nfrom bench_source_service_fixture import dependency_guard\nfrom pathlib import Path\ndependency_guard(Path('+repr(str(source))+'))\n',encoding='utf-8')
    return dict(os.environ,PYTHONPATH=str(guard),PYTHONDONTWRITEBYTECODE='1')


def assert_package_source(source):
    """Every loaded package module belongs to the acquired private source."""
    loaded=[module for name,module in sys.modules.items()
            if name in ('backtest','website') or name.startswith(('backtest.','website.'))]
    assert loaded
    assert all(Path(module.__file__).resolve().is_relative_to(source) for module in loaded)


def child(request_path):
    assert input()=='GO'
    request=json.loads(Path(request_path).read_bytes())
    source=Path(request['source']).resolve();control=Path(request['control']).resolve()
    from tools.experiments.bench_execution_worker import _verify
    _verify(source,request['sources'])
    import mimetypes
    mimetypes.init()
    # Only the secret-provider dependency is redirected. No financial or
    # preparation/signature function is replaced. Children inherit the guard.
    os.environ.update(guarded_environment(source))
    dependency_guard(source)
    sys.path.insert(0,str(source))
    from website import runtime_access
    def emit(event,**values): print(json.dumps(dict(event=event,**values)),flush=True)
    def barrier(name):
        emit(name,at=time.monotonic())
        until=time.monotonic()+60.
        while not (control/(name+'.release')).exists():
            if time.monotonic()>until:raise TimeoutError('Source-service barrier expired.')
            time.sleep(.005)
    with runtime_access.ownership(source,timeout=0):
        emit('source_acquired')
        from backtest.financial import rules
        from backtest.inputs import market, fmp_download, cache_assets, daily, research
        from backtest.engines.reference import legacy
        fmp_download.KEY_PATH=source.parent/'missing-fixture-key'
        from website.server import app
        from backtest.engines.original import robustness as robustness
        from backtest.engines.original import schedules
        from backtest import screening
        assert_package_source(source)
        if request['scenario'].get('fail_start'):raise RuntimeError('Fictional startup failure.')
        # Barriers observe actual operations. Results and ownership are unchanged.
        from backtest.runtime import cache_access as cache_access
        if request['scenario'].get('hold_prepare'):
            original=research.prepare
            def preparing(*args,**kwargs):
                barrier('preparation_held')
                return original(*args,**kwargs)
            research.prepare=preparing
        app.ensure_ready()
        for module in (app,schedules,robustness,app.data_manager,cache_access,market,runtime_access,research):
            assert Path(module.__file__).resolve().is_relative_to(source)
        assert_package_source(source)
        assert app.current_build()
        with cache_access.access(),closing(research.connect(full_prices=True)) as db:
            baseline=research.verify_reference(db)
            latest=screening.latest(db)
            historical=screening.historical(db,first=2015,last=2016,rank_to=4)
            browser_latest=screening.latest(db,pool='cached',metric='ev_ebitda_3y',rank_to=7,
                filters=[dict(field='pe',op='lt',value=20.)])
            browser_historical=screening.historical(db,first=2015,last=2016,pool='cached',rank_from=2,rank_to=4)
            metadata={row[0]:json.loads(row[1]) for row in db.execute('SELECT * FROM metadata')}
        with cache_access.access(),closing(daily.connect()) as db:
            daily_metadata={row[0]:json.loads(row[1]) for row in db.execute('SELECT * FROM metadata')}
        write(control/'expected.json',dict(baseline=baseline,latest=latest,historical=historical,
            browser_latest=browser_latest,browser_historical=browser_historical,
            metadata=metadata,daily_metadata=daily_metadata,signature=research.signature()))
        if request['scenario'].get('oracle'):
            oracle=control/'oracle.sqlite'
            shutil.copy2(daily.DATABASE,oracle)
            with cache_access.access(),closing(daily.connect(oracle)) as db:
                options=dict(start='2015-01-01',end='2016-12-30',months=12,pool='cached',rank_to=4)
                config=robustness.plan(db,**options,trials=5,seed=42)
                fixed=schedules.backtest(db,**options)
                random=robustness.run(db,config)
                inspected=schedules.backtest_dates(db,dates=config['samples'][2],**options)
            # The HTTP adapter adds current producer metadata after closing resources.
            # Keep full equality, including that explicit application contract.
            for result in (fixed,random,inspected):
                result['producer']=dict(engine='original',label='Original')
            write(control/'oracle.json',dict(fixed=fixed,random=random,inspected=inspected))
            # The oracle is disposable. Its selected books never warm the service.
            oracle.unlink()
        if request['scenario'].get('hold_rebuild'):
            original_prepare=research.prepare
            def rebuild_prepare(*args,**kwargs):
                barrier('rebuild_held')
                return original_prepare(*args,**kwargs)
            research.prepare=rebuild_prepare
        from backtest.application.original_calculations import Original
        financial=Original._financial
        from contextlib import contextmanager
        @contextmanager
        def observed_financial(self,admission,progress):
            entered=False
            try:
                with financial(self,admission,progress):
                    entered=True
                    emit('acquired',at=time.monotonic())
                    try:
                        if request['scenario'].get('hold_request'):barrier('request_held')
                        yield
                    finally:emit('leaving',at=time.monotonic())
            finally:
                if entered:emit('released',at=time.monotonic())
        Original._financial=observed_financial
        if request['scenario'].get('disconnect'):
            original_run=robustness.run
            def interrupted(db,config,progress=None,**kwargs):
                def progress_barrier(value):
                    progress(value)
                    if value['type']=='progress' and value['completed']==1:barrier('trial_committed')
                return original_run(db,config,progress=progress_barrier,**kwargs)
            robustness.run=interrupted
        app.Handler.log_message=lambda *args:None
        server=app.Server(('127.0.0.1',0),app.Handler)
        close_admission=server.close_calculation_admission
        def observed_close_admission():
            close_admission()
            emit('admission_closed',at=time.monotonic())
        server.close_calculation_admission=observed_close_admission
        server.daemon_threads=False
        from threading import Thread
        listener=Thread(target=server.serve_forever,kwargs=dict(poll_interval=.02));listener.start()
        try:
            emit('ready',host='127.0.0.1',port=server.server_address[1],pid=os.getpid(),
                 sources=request['sources'],current_build=app.current_build())
            until=time.monotonic()+600.
            while not (control/'stop').exists():
                if time.monotonic()>until:raise TimeoutError('Source service lifetime expired.')
                time.sleep(.005)
            emit('shutdown_started')
        finally:
            server.shutdown();app.DATA_JOBS.close();server.server_close()
            listener.join(timeout=5.);assert not listener.is_alive()
            emit('service_closed')
    emit('source_released')
