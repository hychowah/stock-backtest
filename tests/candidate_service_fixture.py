"""Contain a real isolated candidate entry with explicit fictional failures."""
from contextlib import ExitStack
from pathlib import Path
import sys
from threading import Thread
from unittest.mock import patch


def main():
    source,tests=map(Path,sys.argv[1:3]);scenario=sys.argv[3]
    sys.path[:0]=[str(tests),str(tests.parent/'tools')]
    from bench_source_service_fixture import dependency_guard
    import mimetypes
    mimetypes.init()
    dependency_guard(source)
    sys.path[:0]=[str(source/'scripts'),str(source/'website')]
    import runtime_access
    with runtime_access.ownership(source),ExitStack() as context:
        import run
        run.KEY_PATH=source.parent/'nonexistent-offline-key'
        import numerical_preparation
        if scenario=='dependencies':
            context.enter_context(patch.object(numerical_preparation,'dependencies',
                side_effect=numerical_preparation.PreparationError('dependencies unavailable')))
        elif scenario=='build':
            context.enter_context(patch.object(numerical_preparation.subprocess,'run',
                side_effect=OSError('fictional build failure')))
        if scenario.startswith('ordinary'):
            class WithoutNative:
                def find_spec(self,fullname,path=None,target=None):
                    if fullname.split('.')[0] in ('numpy','numba','llvmlite'):
                        raise ImportError('Ordinary fixture has no numerical stack')
            sys.meta_path.insert(0,WithoutNative())
        import serve_app
        original=serve_app.Server
        def server(*args,**kwargs):
            value=original(*args,**kwargs)
            def stop():
                if sys.stdin.readline()=='close\n':value.shutdown()
            Thread(target=stop,name='fixture-stop',daemon=True).start()
            return value
        context.enter_context(patch.object(serve_app,'Server',side_effect=server))
        if scenario not in ('workflow','ordinary-workflow'):
            context.enter_context(patch.object(serve_app.backtest_jobs,'calculate',side_effect=AssertionError('Stored result requested calculation')))
        if scenario.startswith('ordinary'):
            serve_app.main(arguments=['--host','127.0.0.1','--port','0','--no-browser'])
        else:
            import serve_candidate
            sys.argv=['serve_candidate.py','--private-root',str(source),'--no-browser']
            serve_candidate.main()


if __name__=='__main__':main()
