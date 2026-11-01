"""Admission for executable financial benchmarks, separate from source imports.

Execution has no admitted state yet. Both engines need one consistent bound-input
owner, independent experimental resources and qualified availability limits.
Runtime paths, copied databases and source hashes cannot establish those facts.
Source attachment and pure numerical/evidence helpers do not grant admission.
"""


class BenchmarkAdmissionError(RuntimeError):
    """Required benchmark ownership and availability have not been qualified."""


def require_execution():
    """Reject execution until bound inputs and resource ownership are qualified.

    No CLI flag, environment variable, directory marker or caller permission can
    admit a benchmark. Synthetic calculation tests patch this function only
    within their disposable fixture scopes; source-only imports need no patch.
    """
    raise BenchmarkAdmissionError(
        'Benchmark execution is closed: consistent bound input ownership and '
        'resource/availability admission are not qualified. Keep the stable '
        'website running; do not use the live cache for benchmarks.')
