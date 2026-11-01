"""Contain a real isolated candidate entry with explicit fictional failures."""
from contextlib import ExitStack
from pathlib import Path
import sys
from threading import Thread
from unittest.mock import patch


def main():
    source,tests=map(Path,sys.argv[1:3]);scenario=sys.argv[3]
    sys.path[:0]=[str(tests),str(tests.parent/'tools')]
    from bench_source_service_fixture import dependency_guard, assert_package_source
    import mimetypes
    mimetypes.init()
    dependency_guard(source)
    sys.path[:0]=[str(source),str(source/'scripts'),str(source/'website')]
    import runtime_access
    with runtime_access.ownership(source),ExitStack() as context:
        from backtest.financial import rules
        from backtest.inputs import market, fmp_download, cache_assets
        from backtest.engines.reference import legacy
        fmp_download.KEY_PATH=source.parent/'nonexistent-offline-key'
        from backtest.application import preparation as numerical_preparation
        if scenario=='dependencies':
            context.enter_context(patch.object(numerical_preparation,'dependencies',
                side_effect=numerical_preparation.PreparationError('dependencies unavailable')))
        elif scenario=='build':
            context.enter_context(patch('subprocess.run',
                side_effect=OSError('fictional build failure')))
        if scenario.startswith('ordinary'):
            class WithoutNative:
                def find_spec(self,fullname,path=None,target=None):
                    if fullname.split('.')[0] in ('numpy','numba','llvmlite'):
                        raise ImportError('Ordinary fixture has no numerical stack')
            sys.meta_path.insert(0,WithoutNative())
        if scenario=='selectable-workflow':
            # Observe native bootstrap diagnostics without changing a byte of
            # the strict runtime protocol or retaining exception messages.
            import json,re
            from contextlib import suppress
            from backtest.engines.numerical import runtime as numerical_runtime
            original_process=numerical_runtime.RuntimeProcess
            class ObservedProcess(original_process):
                def _read(self):
                    observed=[];stream=self.process.stdout
                    class Tap:
                        def __getattr__(tap,name):return getattr(stream,name)
                        def readline(tap,*args,**kwargs):
                            line=stream.readline(*args,**kwargs)
                            try:json.loads(line)
                            except ValueError:
                                if line and len(observed)<32:
                                    row=dict(bytes=len(line.encode('utf8')),kind='unstructured')
                                    if line.startswith(('Fatal error in launcher','Unable to create process using')):row['kind']='venv-launcher'
                                    match=re.match(r'\s*File "([^"]+)", line (\d+), in (.*)',line)
                                    if match:row.update(kind='frame',file=Path(match[1]).name,line=int(match[2]),function=match[3])
                                    match=re.match(r'([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)):',line)
                                    if match:row.update(kind='exception-type',error_type=match[1])
                                    match=re.search(r'\[WinError (\d+)\]',line)
                                    if match:row['winerror']=int(match[1])
                                    observed.append(row)
                            return line
                    self.process.stdout=Tap()
                    try:return super()._read()
                    finally:
                        with suppress(Exception):
                            from backtest.inputs.cache_assets import write_json
                            write_json(source/'data'/('_fixture-transport-'+str(self.process.pid)+'.json'),
                                dict(pid=self.process.pid,failure=self.failure,returncode=self.process.poll(),
                                     eof=self.eof,output_bytes=self.output_bytes,observations=observed))
                def close(self):
                    try:return super().close()
                    finally:
                        with suppress(Exception):
                            from backtest.inputs.cache_assets import write_json
                            path=source/'data'/('_fixture-transport-'+str(self.process.pid)+'.json')
                            record=json.loads(path.read_bytes())
                            record.update(final_returncode=self.process.returncode,closed=self.closed)
                            write_json(path,record)
            context.enter_context(patch.object(numerical_runtime,'RuntimeProcess',ObservedProcess))
        import serve_app
        assert_package_source(source)
        if scenario=='selectable-workflow':
            emit=serve_app.DATA_JOBS.emit
            def report(**values):
                emit(**values)
                if 'message' in values:print('SELECTABLE PREPARATION: '+values['message'],flush=True)
            serve_app.DATA_JOBS.emit=report
        original=serve_app.Server
        def server(*args,**kwargs):
            value=original(*args,**kwargs)
            if scenario=='evidence':
                serve=value.serve_forever
                def serve_evidence():
                    from evidence_browser_fixture import seed
                    try:seed(value,source)
                    except BaseException:
                        import traceback
                        (source/'data/evidence-fixture-failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
                        raise
                    serve()
                value.serve_forever=serve_evidence
            def stop():
                # A blocked Windows CRT reader can stall a later NumPy import.
                # Optional normal-app preparation imports after serving starts.
                from backtest.engines.numerical.runtime_child import _stdin_lines
                if next(_stdin_lines(),None)=='close\n':value.shutdown()
            Thread(target=stop,name='fixture-stop',daemon=True).start()
            return value
        context.enter_context(patch.object(serve_app,'Server',side_effect=server))
        if scenario=='ordinary-evidence':
            from evidence_browser_fixture import forbid_read_dependencies
            forbid_read_dependencies(context,serve_app)
        if scenario=='evidence':
            context.enter_context(patch.object(serve_app.backtest_queue.Queue,'start',return_value=None))
        if scenario not in ('workflow','ordinary-workflow','selectable-workflow'):
            context.enter_context(patch.object(serve_app.backtest_jobs,'calculate',side_effect=AssertionError('Stored result requested calculation')))
        if scenario.startswith('ordinary') or scenario=='selectable-workflow':
            serve_app.main(arguments=['--host','127.0.0.1','--port','0','--no-browser'])
        else:
            import serve_candidate
            sys.argv=['serve_candidate.py','--private-root',str(source),'--no-browser']
            serve_candidate.main()


if __name__=='__main__':main()
