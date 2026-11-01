"""Trusted internal comparison configurations; no application/user selector.

Source-guard Numba remains the default pending CB-19F/G. This fixed factory
predicts identity without JIT/native builds so complete D recovery stays lazy.
"""
from numerical_identity import compiler_identity
from numerical_numba import NumbaExecutor
import numerical_rust


def expected_identity(inputs,limits):
    backend=limits.get('backend','numba')
    if backend=='rust':return numerical_rust.identity(inputs,limits['threads'])
    if backend!='numba':raise ValueError('Unknown trusted numerical backend.')
    return compiler_identity(inputs,limits['threads'],
        decisions=inputs.policy.decisions if limits.get('candidate_assembly')=='compiled' else None)


def attach(inputs,limits):
    backend=limits.get('backend','numba')
    if backend=='numba':return NumbaExecutor(inputs,limits=limits)
    if backend=='rust':return numerical_rust.RustExecutor(inputs,limits=limits)
    raise ValueError('Unknown trusted numerical backend.')
