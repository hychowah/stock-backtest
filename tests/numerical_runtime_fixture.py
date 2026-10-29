"""Private synthetic runtime injection. Never selects installed/captured inputs."""
import json
import os
from pathlib import Path
import sqlite3
import time

import numerical_generation
import numerical_session
import schedules
from cache_assets import write_json


class FixtureStore(numerical_generation.GenerationStore):
    def __init__(self, s, path):
        super().__init__(s,path)
        self.binding_path = Path(path).parent/'binding.json'

    def _binding(self):
        binding = json.loads(self.binding_path.read_text())
        return binding,numerical_generation.PolicyProgram(self.s)


class Session(numerical_session.Session):
    def __init__(self, configuration):
        self.fault = configuration.get('fault')
        self.marker = Path(configuration['scratch'])/'fixture-state.json'
        self.close_attempts = 0
        if self.fault == 'startup-cancel':
            self._mark(starting=True,pid=os.getpid())
            import backtest_control
            while True:
                backtest_control.checkpoint(); time.sleep(.01)
        if self.fault == 'startup': raise RuntimeError('fictional startup failure')
        self.provider_builds = 0
        self.original_provider = numerical_session.NumbaExecutor
        def provider(*args,**kwargs):
            self.provider_builds += 1
            return self.original_provider(*args,**kwargs)
        self.provider_factory = provider
        numerical_session.NumbaExecutor = provider
        original = numerical_session.GenerationStore
        numerical_session.GenerationStore = FixtureStore
        try: super().__init__(configuration)
        finally: numerical_session.GenerationStore = original
        self._mark(pid=os.getpid(),ready=True)

    def _mark(self,**values):
        # Observers never see an empty/truncated JSON file during native replace.
        write_json(self.marker,values)

    def calculate(self,*args,**kwargs):
        self._before_calculation(args[2])
        return super().calculate(*args,**kwargs)

    def calculate_into(self,*args,**kwargs):
        self._before_calculation(args[3])
        return super().calculate_into(*args,**kwargs)

    def _before_calculation(self,progress):
        if self.fault == 'callback-stuck':
            import backtest_control
            try: progress(dict(type='progress',completed=0,total=1,trial=1))
            except backtest_control.Cancelled: pass
            self._mark(pid=os.getpid(),running=True)
            while True: time.sleep(.01)
        if self.fault in ('cancel','stuck'):
            self._mark(pid=os.getpid(),running=True)
            while True:
                if self.fault != 'stuck': self.portfolio.s.backtest_control.checkpoint()
                time.sleep(.01)
        if self.fault == 'descendant':
            import subprocess,sys
            self.descendant = subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(60)'])
            self._mark(pid=os.getpid(),descendant=self.descendant.pid)

    def measurements(self):
        values = super().measurements()
        values['pid'] = os.getpid()
        values['provider_builds'] = self.provider_builds
        if os.name == 'posix' and Path('/proc/self/status').exists():
            lines = dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
            values['sampled_working_set_bytes'] = int(lines['VmRSS'].split()[0])*1024
            values['sampled_threads'] = int(lines['Threads'])
        elif os.name == 'nt':
            import ctypes
            from ctypes import wintypes as w
            class Counters(ctypes.Structure):
                _fields_ = [('cb',w.DWORD),('faults',w.DWORD)]+[(name,ctypes.c_size_t) for name in
                    ('peak','working','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
            counters = Counters(); counters.cb = ctypes.sizeof(counters)
            process = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(process,ctypes.byref(counters),counters.cb):
                values['sampled_working_set_bytes'] = counters.working
        return values

    def close(self):
        self.close_attempts += 1
        if self.fault == 'close' and self.close_attempts <= 2:
            self._mark(close_attempts=self.close_attempts)
            raise OSError('fictional partial cleanup failure')
        portfolio,provider,inputs,checkpoints = self.portfolio,self.provider,self.inputs,self.checkpoints
        sql = portfolio.db if portfolio is not None else None
        checkpoint_db = checkpoints.db if checkpoints is not None else None
        super().close()
        def connection_closed(db):
            if db is None:return True
            try:db.execute('SELECT 1')
            except sqlite3.ProgrammingError:return True
            return False
        if numerical_session.NumbaExecutor is getattr(self,'provider_factory',None):
            numerical_session.NumbaExecutor = self.original_provider
        if hasattr(self,'marker'):
            self._mark(closed=True,close_attempts=self.close_attempts,provider_builds=self.provider_builds,
                portfolio_closed=portfolio is None or portfolio.closed,
                provider_closed=provider is None or provider.inputs is None,
                mappings_closed=inputs is None or inputs.closed and not inputs._arrays,
                record_db_closed=inputs is None or inputs._db is None,
                sql_closed=connection_closed(sql),checkpoint_db_closed=connection_closed(checkpoint_db))
