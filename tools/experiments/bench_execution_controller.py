"""Private comparison controller entry. Default admission rejects before reads."""
import json
from pathlib import Path
import sys
import time

import tools.experiments.bench_admission as admission
from tools.experiments.bench_execution_storage import failure_reason
from tools.experiments.bench_comparison import ComparisonError, ComparisonProtocol, encoded


def main():
    admission.require_execution()
    if input() != 'GO': raise ComparisonError('protocol')
    # Only the test harness can patch admission. No flag or environment switch
    # is accepted by the controller or its existing financial workers.
    with Path(sys.argv[2]).open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024: raise ComparisonError('limit')
    request = json.loads(raw)
    # This fresh controller needs the actual coordination implementation.
    # MeasurementExecution verifies its bytes against captured participating
    # source before any observation. Financial workers still use private source.
    root = Path(__file__).resolve().parents[2]
    from tools.experiments.bench_execution import ExecutionEnvelope, MeasurementExecution
    protocol = ComparisonProtocol(encoded(request['protocol']))
    if protocol.identity != request['protocol_sha256']: raise ComparisonError('mismatch')
    mode = request['observation_mode']
    if mode not in ('fixture', 'coordinated'): raise ComparisonError('unsupported')
    owner = MeasurementExecution(request['capture'], request['source'], request['output'],
        protocol, ExecutionEnvelope(**request['envelope']), **{
            ('fixture_observation_root' if mode == 'fixture' else 'coordinated_observation_root'):
                request['observation_root']})
    owner._supervision_started = request['supervision_started']
    owner._read_only_observation = request.get('read_only_observation', False)
    try:
        with owner: owner.compare()
        print(encoded(dict(event='complete', result=owner.result,
            finalization_started=owner._finalization_started,
            controller_finished=time.monotonic(), workspace=str(owner._workspace._folder))).decode(), flush=True)
    except BaseException as error:
        print(encoded(dict(event='failed', reason=failure_reason(error),
                           error_type=type(error).__name__)).decode(), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
