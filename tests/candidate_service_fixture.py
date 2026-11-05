"""Contain the real ordinary app in a private source export with fictional failures."""
from contextlib import ExitStack
from pathlib import Path
import sys
from threading import Thread
from unittest.mock import patch


def forbid_calculations(context):
    """Refuse calculation, so a stored result can open without one."""
    from backtest.application.original_calculations import Original
    context.enter_context(patch.object(Original,'calculate',side_effect=AssertionError('Stored result requested calculation')))


def main():
    source,tests=map(Path,sys.argv[1:3]);scenario=sys.argv[3]
    sys.path[:0]=[str(tests),str(tests.parent)]
    from source_service_fixture import dependency_guard, assert_package_source
    import mimetypes
    mimetypes.init()
    dependency_guard(source)
    sys.path[:0]=[str(source)]
    from website import runtime_access
    with runtime_access.ownership(source),ExitStack() as context:
        from backtest.financial import rules
        from backtest.inputs import market, fmp_download, cache_assets
        from backtest.engines.reference import legacy
        fmp_download.KEY_PATH=source.parent/'nonexistent-offline-key'
        if scenario.startswith('ordinary'):
            class WithoutNative:
                def find_spec(self,fullname,path=None,target=None):
                    if fullname.split('.')[0] in ('numpy','numba','llvmlite'):
                        raise ImportError('Ordinary fixture has no numerical stack')
            sys.meta_path.insert(0,WithoutNative())
        from website.server import app as serve_app
        assert_package_source(source)
        original=serve_app.Server
        def server(*args,**kwargs):
            value=original(*args,**kwargs)
            def stop():
                if sys.stdin.readline()=='close\n':value.shutdown()
            Thread(target=stop,name='fixture-stop',daemon=True).start()
            return value
        context.enter_context(patch.object(serve_app,'Server',side_effect=server))
        forbid_calculations(context)
        serve_app.main(arguments=['--host','127.0.0.1','--port','0','--no-browser'])


if __name__=='__main__':main()
