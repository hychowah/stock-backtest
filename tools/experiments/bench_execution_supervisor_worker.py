"""Private supervisor process. Shipped admission rejects before control reads.

The existing application/storage owners stay alive for mechanical close retry.
A killed helper loses those Python objects and any uncollected tmpfs bytes.
"""
import json
from pathlib import Path
import sys
import time

import tools.experiments.bench_admission as admission
from tools.experiments.bench_comparison import ComparisonError, encoded
from tools.experiments.bench_execution_storage import CONTROL_BYTES, failure_reason
from tools.experiments.bench_execution_supervisor import _ApplicationSupervisor


def send(**value):
    raw = encoded(value)
    if len(raw) > 64*1024: raise ComparisonError('limit')
    print(raw.decode(), flush=True)


def main():
    admission.require_execution()
    if input() != 'GO': raise ComparisonError('protocol')
    request = Path(sys.argv[2])
    with request.open('rb') as stream: raw = stream.read(CONTROL_BYTES+1)
    if len(raw)>CONTROL_BYTES: raise ComparisonError('limit')
    spec = json.loads(raw)
    action = request.parent/'action.json'
    def cancelled(): return action.exists()
    owner = _ApplicationSupervisor(spec, cancel=cancelled, hierarchy=spec['hierarchy'], report=send)
    try:
        owner.run()
        send(event='complete', result=owner.result, evidence=owner.evidence,
             finalization_started=owner._finalization_started)
        return 0
    except BaseException as error:
        send(event='failed', reason=failure_reason(error), error_type=type(error).__name__,
             pending=not owner.closed, application_not_requested=not owner.application_requested)
        sequence = -1
        while not owner.closed:
            if action.exists():
                with action.open('rb') as stream: raw=stream.read(4097)
                if len(raw)>4096: raise ComparisonError('limit')
                value=json.loads(raw)
                if value['sequence']>sequence:
                    sequence=value['sequence']
                    try: owner.close()
                    except BaseException: send(event='pending')
                    else: send(event='closed')
            time.sleep(.02)
        return 1


if __name__ == '__main__': raise SystemExit(main())
