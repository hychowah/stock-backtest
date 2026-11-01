"""Private runtime/session lifecycle fixture. No installed data or factories in workers."""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).absolute().parents[1]


def __getattr__(name):
    if name != 'Session': raise AttributeError(name)
    # The real numerical runtime loads this factory only after source/cache
    # ownership. The fixed production trial worker never imports this fixture.
    from numerical_runtime_fixture import Session as Base
    import numerical_trial
    import numerical_calendar
    class Session(Base):
        def __init__(self, configuration):
            super().__init__(configuration)
            if configuration.get('pool_start'):
                self.pool().start()

        def calculate(self, mode, options, progress, configuration, **kwargs):
            if mode != '__pool__': return super().calculate(mode, options, progress, configuration, **kwargs)
            config = numerical_calendar.plan(self.workspace._calendar().sessions, dict(calendar=dict(
                version=1, start='2015-01-05', end='2016-12-30', interval=dict(unit='week', count=1)),
                trials=3, seed=42, rank_to=5, min_cap=0., min_ev=0.))
            binding = self._binding(config)
            specifications = [numerical_trial.specification(binding, n) for n in range(1, 4)]
            pool = self.pool()
            original = pool._send
            def send(worker, event):
                original(worker, event)
                if event.get('command') == 'trial': progress(dict(type='running', worker=worker.process.pid))
            pool._send = send
            results = []
            try:
                with pool.batch(specifications) as batch:
                    for completion in batch.completed():
                        results.append(dict(number=completion.number, summary=completion.artifact.summary))
                        completion.release()
            finally: pool._send = original
            return dict(trials=results)
    globals()['Session'] = Session
    return Session


def main():
    configuration, ready = map(Path, sys.argv[1:3])
    launch = json.loads(configuration.read_bytes())
    sys.path[:0] = [str(ROOT/'website')]
    import runtime_access
    with runtime_access.ownership(ROOT):
        sys.path[:0] = [str(ROOT/'scripts')]
        from numerical_runtime import NumericalRuntime
        import cache_access
        launch['coordinator'] = cache_access.WorkspaceAccess(Path(launch.pop('fixture_coordinator')))
        value = NumericalRuntime(**launch)
        value.start()
        state = dict(parent=os.getpid(), runtime=value.owner.process.pid,
            workers=value.last_stats['trial_pool']['worker_pids'], stage='idle')
        ready.write_text(json.dumps(state))
        if len(sys.argv) > 3 and sys.argv[3] == 'active':
            def progress(event):
                state.update(stage='active', event=event)
                pending = ready.with_suffix('.pending'); pending.write_text(json.dumps(state)); pending.replace(ready)
                # A real in-flight callback remains interruptible by runtime EOF
                # when this outer application owner dies.
                while True: time.sleep(.02)
            value.calculate('__pool__', {}, progress=progress)
        while True: time.sleep(.02)


if __name__ == '__main__': main()
