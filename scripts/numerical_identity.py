"""Conservative loaded calculation/compiler identity for numerical reuse."""
import hashlib
from importlib.metadata import version
import json
import platform
import sys


def compiler_identity(inputs, threads):
    # Local import avoids importing the planner when only matrix kernels are used.
    from numerical_random import source_identity
    import numba
    import llvmlite.binding as llvm
    fields = dict(sources=source_identity(),policy=inputs.policy.signature,
        schema=inputs.policy.field_schema,catalog=json.loads(json.dumps(inputs.policy.fields)),
        bankruptcy=[list(value) for value in sorted(inputs.bankrupt)],
        python=platform.python_version(),python_build=sys.version,implementation=sys.implementation.name,
        versions={name:version(name) for name in ('numpy','numba','llvmlite')},
        platform=dict(system=platform.system(),release=platform.release(),machine=platform.machine(),byteorder=sys.byteorder),
        target=dict(triple=llvm.get_default_triple(),cpu=str(llvm.get_host_cpu_name()),
                    features=llvm.get_host_cpu_features().flatten(),configured_cpu=numba.config.CPU_NAME,
                    configured_features=numba.config.CPU_FEATURES),
        threads=threads,threading_layer=numba.config.THREADING_LAYER,
        fastmath=False,compiler_cache=False,error_model='numpy',dtype='float64')
    signature=hashlib.sha256(json.dumps(fields,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return dict(signature=signature,fields=fields)
