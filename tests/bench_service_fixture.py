"""Disposable HTTP qualification support; no production launcher or admission.

Exercise existing HTTP handlers and financial functions. Fixture bindings replace
storage discovery only. These checks do not qualify the installed launcher,
production preparation, browser rendering, real-data capacity or full resources.
"""
from contextlib import closing, contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from bench_comparison import encoded

START_SECONDS = 20.
CLIENT_SECONDS = 30.
CLOSE_SECONDS = 15.
MAX_RESPONSE = 8 * 1024**2
_pending_services = {}


def expanded_fixture(case):
    """Build 16 companies/20,880 daily price rows, below the old 32 MiB cap."""
    from test_bench_execution_inputs import sha, receipt, semantic
    from test_bench_input_store import metadata
    from bench_generation import signature
    from bench_input_artifacts import SOURCE_ASSETS
    from types import SimpleNamespace
    f = case.fixture
    for path in (ROOT / 'website').iterdir():
        if path.is_file(): shutil.copy2(path, f.source / 'website' / path.name)
    f.sources = {p.relative_to(f.source).as_posix(): sha(p)
                 for folder in ('scripts', 'website', 'backtest') for p in (f.source / folder).rglob('*')
                 if p.is_file() and (p.suffix=='.py' or p.relative_to(f.source).as_posix() in SOURCE_ASSETS)}
    with closing(sqlite3.connect(f.capture / 'research.sqlite')) as research, \
            closing(sqlite3.connect(f.capture / 'schedules.sqlite')) as daily:
        for db in (research, daily):
            for index in range(1, 16):
                symbol = 'S%02d' % index
                db.execute('INSERT INTO companies VALUES(?,?,?,?)', (symbol, symbol, 'NYSE', 'Energy'))
                db.execute('INSERT INTO statements SELECT ?,fiscal,known,market_cap,enterprise_value,ebitda,ebitda_yield FROM statements WHERE symbol=?', (symbol, 'A'))
                db.execute('INSERT INTO financial_inputs SELECT ?,fiscal,values_json FROM financial_inputs WHERE symbol=?', (symbol, 'A'))
        for index in range(1, 16):
            daily.execute('INSERT INTO prices SELECT ?,day,price,adjusted FROM prices WHERE symbol=?', ('S%02d' % index, 'A'))
        symbols = [row[0] for row in research.execute('SELECT symbol FROM companies ORDER BY symbol')]
        raw = f.source / 'raw'
        (raw / 'universe.json').write_bytes(encoded([dict(symbol=s, exchangeShortName='NYSE', isEtf=False, isFund=False, listed=True) for s in symbols]))
        metrics = []
        for symbol in symbols:
            rows = [dict(symbol=symbol, date=day, adjClose=adjusted, close=price)
                    for day, price, adjusted in daily.execute('SELECT day,price,adjusted FROM prices WHERE symbol=? ORDER BY day', (symbol,))]
            (raw / 'px' / (symbol + '.json')).write_bytes(encoded(rows))
            annual = []
            for fiscal, cap, ev, ebitda in research.execute('SELECT fiscal,market_cap,enterprise_value,ebitda FROM statements WHERE symbol=?', (symbol,)):
                metrics.append(dict(symbol=symbol, date=fiscal, reportedCurrency='USD', marketCap=cap, enterpriseValue=ev, evToEbitda=ev / ebitda))
                annual.append(dict(symbol=symbol, date=fiscal, reportedCurrency='USD', netIncome=30e6, revenue=100e6, epsDiluted=2., ebitda=ebitda))
            (raw / 'financial-inputs' / 'income' / (symbol + '.json')).write_bytes(encoded(annual))
        (raw / 'metrics.jsonl').write_bytes(b''.join(encoded(row) + b'\n' for row in metrics))
        (raw / 'spy-div.json').write_bytes(encoded([dict(date=day, adjClose=price) for day, price in daily.execute('SELECT day,price FROM sessions ORDER BY day')]))
        (raw / 'treasury.json').write_bytes(encoded([dict(date='2014-12-31', month3=1.)]))
        names = ('baseline', 'metrics', 'books', 'cache_assets', 'market', 'legacy', 'revalue', 'financial_inputs', 'rules', 'screening')
        modules = {name: SimpleNamespace(__file__=str(f.source / {'metrics': 'backtest/financial/metrics.py', 'books': 'backtest/financial/books.py', 'rules': 'backtest/financial/rules.py', 'screening': 'backtest/screening.py', 'baseline': 'backtest/inputs/baseline.py', 'cache_assets': 'backtest/inputs/cache_assets.py', 'market': 'backtest/inputs/market.py', 'legacy': 'backtest/engines/reference/legacy.py', 'revalue': 'backtest/engines/reference/revalue.py', 'financial_inputs': 'backtest/inputs/financial_inputs.py'}[name])) for name in names}
        from datetime import date
        modules['baseline'].cutoff = lambda text: date(2026, 10, 21)
        f.freshness['inputs'] = signature(SimpleNamespace(ROOT=f.source, RAW=raw, RESULTS=f.source / 'results',
            __file__=str(f.source / 'backtest/inputs/research.py'), **modules))
        f.freshness['prices'] = {p.name: [p.stat().st_size, p.stat().st_mtime_ns] for p in (raw / 'px').glob('*.json')}
        f.freshness['daily_inputs']['inputs'] = f.freshness['inputs']
        metadata(research, dict(inputs=f.freshness['inputs'], prices=f.freshness['prices']))
        metadata(daily, dict(daily_inputs=f.freshness['daily_inputs'], cached_symbols=symbols))
        research.commit(); daily.commit()
        import bench_execution as execution
        f.meta = dict(zip(('research', 'daily'), (execution.inputs.artifacts.metadata(db,
            execution.inputs.ExecutionInputError, reason='incomplete') for db in (research, daily))))
        f.identity = semantic(research, daily, f.sources)
        counts = {table: daily.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                  for table in ('companies', 'statements', 'financial_inputs', 'prices', 'sessions')}
    for name in ('research.sqlite', 'schedules.sqlite'):
        assert (f.capture / name).stat().st_size < 32 * 1024**2
        shutil.copy2(f.capture / name, f.source / 'data' / name)
        f.manifest['artifacts'][name] = receipt(f.capture / name)
    f.manifest.update(financial_generation=f.identity, metadata=f.meta)
    f.manifest['originals'].update(sources=f.sources, freshness=f.freshness)
    f.write_manifest()
    output = f.source / 'website' / 'local'; output.mkdir()
    (output / 'index.html').write_text('<!doctype html><html><title>Synthetic CB-02</title><body>Disposable static delivery fixture</body></html>', encoding='utf-8')
    request = dict(source=str(f.source), capture=str(f.capture), sources=f.sources,
        database=str(f.source / 'data/schedules.sqlite'), observation_root=str(f.source),
        observation_mode='coordinated', captured_freshness=f.freshness, captured_metadata=f.meta,
        configuration=case.configuration, binding=dict(generation=f.identity))
    request['page_sources'] = {p.relative_to(f.source).as_posix(): sha(p)
        for p in (f.source / 'website').iterdir() if p.suffix in ('.html', '.js', '.css')}
    sizes = {name: (f.capture / name).stat().st_size for name in ('research.sqlite', 'schedules.sqlite')}
    assets = list(raw.rglob('*'))
    scale = dict(rows=counts, databases=sizes, raw_files=sum(p.is_file() for p in assets),
                 raw_bytes=sum(p.stat().st_size for p in assets if p.is_file()),
                 source_files=len(f.sources), sources=f.sources, page_sources=request['page_sources'])
    return request, scale


class SyntheticService:
    """Own a disposable service loaded from verified private source.

    Publish its loopback address after binding. Keep source ownership until the
    listener, request threads, databases and child process close. Restart creates
    a new interpreter against the same synthetic saved data. Unknown closure
    retains this owner and its controls for explicit retry.
    """
    start_seconds = START_SECONDS
    client_seconds = CLIENT_SECONDS
    close_seconds = CLOSE_SECONDS
    max_response = MAX_RESPONSE

    def __init__(self, fixture, request, **scenario):
        self.fixture, self.request_spec = fixture, request
        self.control = fixture.root / ('http-' + uuid.uuid4().hex)
        self.scenario = scenario
        self.owned = None
        self.events = []
        self.clients = set()
        self.stop_sent = self.closed = self.ready = False

    def start(self):
        from backtest.runtime.process_owner import OwnedProcess
        self.control.mkdir()
        request = dict(self.request_spec, control=str(self.control), scenario=self.scenario)
        path = self.control / 'request.json'; path.write_bytes(encoded(request))
        _pending_services[id(self)] = self
        command = self.command(path)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', NUMBA_NUM_THREADS='2',
                   OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
        try:
            self.owned = OwnedProcess(command, env=env, limits=self.limits())
            self.owned.start()
            ready = self.wait('ready', self.start_seconds)
            self.port = ready['port']
            if ready['host'] != '127.0.0.1' or self.port in (0, 3000):
                raise AssertionError('Invalid disposable service address.')
            self.ready = True
            return self
        except BaseException as error:
            self.owned = self.owned or getattr(error, 'owned_process', None)
            try: self.close()
            except BaseException: error.synthetic_service = self
            raise

    def command(self, path):
        return [sys.executable, '-X', 'utf8', '-I', '-B', '-c',
            'import sys;sys.path[:0]=sys.argv[1:3];from bench_service_fixture import child;child(sys.argv[3])',
            str(ROOT / 'tests'), str(ROOT / 'tools'), str(path)]

    def limits(self):
        from backtest.runtime.process_owner import ProcessLimits
        return ProcessLimits(512 * 1024**2, 8, 25, close_seconds=5.)

    def wait(self, event, seconds=None):
        seconds = self.client_seconds if seconds is None else seconds
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            value = self.owned.event(.02)
            if value:
                self.events.append(value)
                if value.get('event') == 'failed':
                    raise AssertionError('Synthetic service transport failed: ' + value['reason'])
                if value.get('event') == event: return value
            elif self.owned.process.poll() is not None: break
        raise AssertionError('Missing synthetic service event: ' + event)

    @contextmanager
    def connection(self):
        client = http.client.HTTPConnection('127.0.0.1', self.port, timeout=self.client_seconds)
        self.clients.add(client)
        try: yield client
        finally: client.close(); self.clients.discard(client)

    def request(self, method, path, payload=None, *, status=200):
        with self.connection() as client:
            body = None if payload is None else encoded(payload)
            client.request(method, path, body, {'Content-Type': 'application/json'})
            response = client.getresponse()
            raw = response.read(self.max_response + 1)
            assert response.status == status, (response.status, raw[:200])
            assert len(raw) <= self.max_response
            length = response.getheader('Content-Length')
            if length is not None: assert int(length) == len(raw)
            if path == '/api/robustness':
                rows = [json.loads(line) for line in raw.splitlines()]
                assert rows[0]['type'] == 'configuration' and rows[-1]['type'] == 'complete'
                return rows
            if path.startswith('/api/'): return json.loads(raw)
            return raw

    def close(self):
        if self.closed: return
        if self.owned is not None:
            if not self.stop_sent and self.owned.process.poll() is None:
                (self.control / 'stop').touch()
                self.stop_sent = True
            self.owned.process.wait(timeout=self.close_seconds)
            self.owned.close()
            if not self.owned.closed: raise TimeoutError('Synthetic service closure is unconfirmed.')
            while not self.owned.events.empty():
                self.events.append(self.owned.events.get_nowait())
            if self.ready:
                assert self.owned.failure is None, 'Synthetic service transport failed.'
                assert self.owned.process.returncode == 0, 'Synthetic service failed during shutdown.'
                names = [row.get('event') for row in self.events]
                assert names.index('shutdown_started') < names.index('service_closed') < names.index('source_released')
        for client in list(self.clients): client.close()
        self.clients.clear()
        self.closed = True
        _pending_services.pop(id(self), None)

    def restart(self):
        """Start ordinary service code afresh; fault barriers belong to one child."""
        self.close()
        return SyntheticService(self.fixture, self.request_spec).start()

    def __enter__(self): return self.start()

    def __exit__(self, kind, error, tb):
        try: self.close()
        except BaseException:
            if error is None: raise
            error.synthetic_service = self


def child(request_path):
    """Test-only bootstrap; no call to the normal launcher or preparation.

    Live requests use the ordinary coordinator. Barriers arrange arrival but
    never replace ownership operations or financial results.
    """
    assert input() == 'GO'
    request = json.loads(Path(request_path).read_bytes())
    source = Path(request['source']).resolve()
    control = Path(request['control']).resolve()
    from bench_execution_worker import _verify, _bind
    _verify(source, request['sources'])
    _verify(source, request['page_sources'])
    # Standard HTTP MIME initialization reads OS MIME configuration. Complete
    # it before the guard that rejects ambient application assets.
    import mimetypes
    mimetypes.init()
    # Reject accidental ambient filesystem/network dependencies in this child.
    # This is a Python dependency check, not an OS/native-code sandbox.
    import sysconfig
    roots = (source.parent, ROOT / 'tests', ROOT / 'tools',
             *(Path(sysconfig.get_path(k)).resolve() for k in ('stdlib', 'platstdlib', 'purelib', 'platlib')))
    def audit(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            mode, flags = args[1:3]
            writing = isinstance(mode, str) and any(c in mode for c in 'wax+') or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            allowed = (source.parent,) if writing else roots
            if not any(path.is_relative_to(root) for root in allowed):
                if writing or os.name == 'nt' or not any(path.is_relative_to(p) for p in (Path('/proc'), Path('/sys'))):
                    raise AssertionError('Ambient fixture file dependency.')
        elif event in ('socket.connect', 'socket.bind'):
            address = args[1]
            if isinstance(address, tuple) and (address[0] != '127.0.0.1' or event == 'socket.bind' and address[1] != 0):
                raise AssertionError('Nonfixture network dependency.')
    sys.addaudithook(audit)
    sys.path[:0] = [str(source / 'scripts'), str(source / 'website')]
    import runtime_access
    def emit(event, **data): print(json.dumps(dict(event=event, **data)), flush=True)
    def barrier(name):
        emit(name)
        deadline = time.monotonic() + CLIENT_SECONDS
        while not (control / (name + '.release')).exists():
            if time.monotonic() > deadline: raise TimeoutError('Synthetic barrier expired.')
            time.sleep(.005)
    with runtime_access.ownership(source, timeout=0):
        if request['scenario'].get('fail_start'): raise RuntimeError('Synthetic startup failure.')
        s, robust, _ = _bind(request)
        from backtest.inputs import daily, research
        from backtest.financial import metrics
        # A service owns mutable prepared storage; the private financial binding
        # keeps its copied freshness baseline. Observation tests independently
        # exercise current enumeration. This is not production preparation.
        research.signature = lambda: request['captured_freshness']['inputs']
        (Path(request['database']).parent / 'binding.json').write_bytes(encoded(request))
        if request['scenario'].get('oracle'):
            oracle = control / 'oracle.sqlite'
            shutil.copy2(Path(request['capture']) / 'schedules.sqlite', oracle)
            reference = dict(request, database=str(oracle))
            (control / 'binding.json').write_bytes(encoded(reference))
            s, robust, _ = _bind(reference)
            research.signature = lambda: request['captured_freshness']['inputs']
            config = request['configuration']
            with closing(daily.connect()) as db:
                planned = robust.plan(db, start=config['start'], end=config['end'], months=config['months'],
                    trials=config['requested'], seed=config['seed'], **config['options'])
                batch = robust.run(db, planned)
                inspections = [s.backtest_dates(db, dates=dates, start=config['start'], end=config['end'],
                    months=config['months'], **config['options']) for dates in planned['samples']]
            # The normal engine adapter adds its producer after calculation.
            for result in (batch, *inspections):
                result['producer'] = dict(engine='original', label='Original')
            (control / 'expected.json').write_bytes(encoded(dict(random=batch, inspections=inspections)))
            s, robust, _ = _bind(request)
            research.signature = lambda: request['captured_freshness']['inputs']
        import serve_app
        from backtest.runtime import cache_access as cache_access
        for module in (serve_app, s, robust, cache_access, research, metrics, runtime_access):
            assert Path(module.__file__).resolve().is_relative_to(source)
        assert cache_access.workspace.path.resolve() == source / 'data/website-data-0.lock'
        access_context = cache_access.access
        @contextmanager
        def observed_access(*args, **kwargs):
            with access_context(*args, **kwargs) as owner:
                emit('acquired', at=time.monotonic())
                try:
                    if request['scenario'].get('hold_request'): barrier('request_held')
                    yield owner
                finally: emit('leaving', at=time.monotonic())
            emit('released', at=time.monotonic())
        cache_access.access = observed_access
        if request['scenario'].get('disconnect'):
            run = robust.run
            def interrupted_run(db, config, progress=None, **kwargs):
                def progress_barrier(value):
                    progress(value)
                    if value['type'] == 'progress' and value['completed'] == 1:
                        barrier('trial_committed')
                return run(db, config, progress=progress_barrier, **kwargs)
            robust.run = interrupted_run
        # HTTP logs must not pollute the bounded JSON control protocol.
        serve_app.Handler.log_message = lambda *args: None
        server = serve_app.Server(('127.0.0.1', 0), serve_app.Handler)
        server.daemon_threads = False
        from threading import Thread
        listener = Thread(target=server.serve_forever, kwargs=dict(poll_interval=.02))
        listener.start()
        try:
            emit('ready', host='127.0.0.1', port=server.server_address[1], pid=os.getpid(),
                 sources=request['sources'])
            deadline = time.monotonic() + 120.
            while not (control / 'stop').exists():
                if time.monotonic() > deadline: raise TimeoutError('Synthetic service lifetime expired.')
                time.sleep(.005)
            emit('shutdown_started')
        finally:
            server.shutdown()
            serve_app.DATA_JOBS.close()
            server.server_close()
            listener.join(timeout=5)
            assert not listener.is_alive()
            emit('service_closed')
    emit('source_released')
