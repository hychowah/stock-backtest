"""Financial-free support for checked captured scalar programs.

Support is independent of optional packages, generation readiness and coverage.
The existing language owner alone parses and restores programs. This owner
checks that its public checked projection is inside the compiled subset. It
does not construct an evaluator, provider, runtime or financial connection.
"""
import hashlib
from pathlib import Path

from backtest.variables import definitions, evaluation, selection
from backtest import observations

VERSION = 1
MAX_CHUNK_STEPS = 256
MAX_CACHE_BYTES = 16 * 1024 * 1024
OPERATIONS = ('constant', 'parameter', 'annual', 'ref', 'at', 'lookback',
              'neg', 'add', 'sub', 'mul', 'div')
PARAMETERS = ('annual.revenue', 'annual.operating_income',
              'annual.operating_margin', 'market.enterprise_value')
# Compiler vocabulary is distinct from the currently qualified public policy.
# These declarations alone do not admit an application request.
IMPLEMENTED_OPERATIONS = OPERATIONS + ('positive_div',)
IMPLEMENTED_PARAMETERS = tuple(item['id'] for item in observations.catalog())
IMPLEMENTED_ANNUAL_STATISTICS = ('mean', 'min', 'max', 'growth', 'cagr')
# Qualification is pinned separately from compiler/provider implementation.
QUALIFIED_PARAMETERS = selection.QUALIFIED_PARAMETERS
QUALIFIED_NAMESPACES = selection.QUALIFIED_NAMESPACES
QUALIFIED_OPERATIONS = selection.QUALIFIED_OPERATIONS
QUALIFIED_ANNUAL_STATISTICS = selection.QUALIFIED_ANNUAL_STATISTICS
MODES = ('latest', 'january', 'custom', 'random')
_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def fingerprint():
    """Reject changed loaded support policy, including on recovered work."""
    current = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if current != _LOADED:
        raise definitions.FormulaError('STALE_INPUT_GENERATION', '', 'Loaded numerical capability source changed.')
    selection.policy_fingerprint()
    return current


def capabilities():
    """Return detached supported semantics; readiness and coverage are separate."""
    return dict(format='variable-capabilities', version=1,
        backend_id='numba-formulas', backend_version=VERSION,
        definition_versions=[1, 2, 3], catalog_versions=['financial-parameters/1', 'financial-parameters/2', 'financial-parameters/3'],
        temporal_policies=['annual-lag90/1'], parameter_ids=list(QUALIFIED_PARAMETERS),
        operations=sorted(QUALIFIED_OPERATIONS), annual_statistics=sorted(QUALIFIED_ANNUAL_STATISTICS),
        root_modes=['historical', 'latest'], limits=dict(evaluation.CEILINGS),
        max_chunk_steps=MAX_CHUNK_STEPS, max_cache_bytes=MAX_CACHE_BYTES,
        application_admission=True, application_modes=list(MODES),
        execution='bounded-complete-evidence', eager=False, sample_preview=False)


def require_program(program, *, checkpoint=lambda: None):
    """Admit the existing checked program; no raw-formula restoration bypass."""
    checkpoint()
    checked = definitions.require_program(program)
    if checked['version'] != 1 or any(
            (item['definition']['version'], item['definition']['parameter_catalog'],
             item['definition']['temporal_policy']) not in QUALIFIED_NAMESPACES
            for item in checked['bundle']['definitions']):
        raise definitions.FormulaError('UNSUPPORTED_CAPABILITY', '/variables', 'Unsupported numerical formula namespace.')
    for node in checked['nodes']:
        checkpoint()
        if node['op'] not in QUALIFIED_OPERATIONS:
            raise definitions.FormulaError('UNSUPPORTED_CAPABILITY', node['path'], 'Unsupported numerical formula operation.')
        if node['op'] == 'annual' and node['stat'] not in QUALIFIED_ANNUAL_STATISTICS:
            raise definitions.FormulaError('UNSUPPORTED_CAPABILITY', node['path'], 'Unsupported numerical annual statistic.')
        if node['op'] in ('parameter', 'annual') and node['parameter'] not in QUALIFIED_PARAMETERS:
            raise definitions.FormulaError('UNSUPPORTED_CAPABILITY', node['path'], 'Unsupported numerical observation parameter.')
    fingerprint()
    return checked


def require_operation(mode, *, eager=False):
    """Bounded scalar execution only, rejected before readiness or input work."""
    if eager or mode not in MODES:
        raise definitions.FormulaError('UNSUPPORTED_CAPABILITY', '/execution',
            'Captured scalar strategies require bounded complete evidence in a supported mode.')
