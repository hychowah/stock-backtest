"""Validate captured formulas without reading financial inputs or a library.

Raw submissions use at most 64 characters per decimal literal. Canonical
expansion may be longer. require_program() is the sole checked restore boundary
for that expanded representation; it reconstructs every derived field. The
program projection exposes resolved node edges, dimensions and observation
requirements so execution need not repeat language or dependency policy.
Definition version 2 adds annual growth and CAGR; the bundle and program
envelopes remain version 1. Counts are consecutive observations, so there are
count-1 annual intervals. Growth results use canonical scalar fractions.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
import hashlib
import json
import math
import re
from types import MappingProxyType

from backtest.variables import parameters

VERSION = 1  # Bundle and program envelope; definition versions evolve separately.
DEFINITION_VERSIONS = (1, 2, 3)
TEMPORAL_POLICY = 'annual-lag90/1'
MARKET_TEMPORAL_POLICY = 'market-annual/1'
CEILINGS = MappingProxyType(dict(nodes=256, depth=32, definitions=32,
    dependency_depth=8, bytes=256 * 1024, literal=64, expanded_literal=1024))
_ID = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')
_REVISION = re.compile(r'sha256:[0-9a-f]{64}\Z')
_DECIMAL = re.compile(r'([+-]?)(?:([0-9]+)(?:\.([0-9]*))?|\.([0-9]+))(?:[eE]([+-]?[0-9]+))?\Z')
_SHAPES = {'parameter': ('op', 'id'), 'constant': ('op', 'value', 'unit'),
    'neg': ('op', 'arg'), 'ref': ('op', 'variable_id', 'revision'),
    'at': ('op', 'date', 'arg'), 'lookback': ('op', 'months', 'arg'),
    'annual': ('op', 'stat', 'count', 'parameter')}
for _op in ('add', 'sub', 'mul', 'div', 'positive_div'):
    _SHAPES[_op] = ('op', 'left', 'right')
OPERATIONS = frozenset(_SHAPES)  # The language's operations; the editor lists them.


def canonical(value):
    """Canonical JSON for validated content; this function grants no capability."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False)


def _hash(document):
    return 'sha256:' + hashlib.sha256(document.encode('utf-8')).hexdigest()


class FormulaError(ValueError):
    """Safe validation issues in deterministic expression then definition order."""
    def __init__(self, code=None, path=None, message=None, *, errors=None):
        issues = errors if errors is not None else [dict(code=code, path=path, message=message)]
        self.errors = tuple(MappingProxyType(dict(issue)) for issue in issues)
        self.code, self.path = self.errors[0]['code'], self.errors[0]['path']
        super().__init__(self.errors[0]['message'])

    def to_dict(self):
        return dict(errors=[dict(issue) for issue in self.errors])


@dataclass(frozen=True)
class FormulaProgram:
    """Detached canonical program bytes; require_program() checks before execution.

    The projection contains the captured normalized bundle and its revision,
    limits, resolved definitions, ordered nodes and observation requirements.
    A node's dimensions are canonical exponent maps. left/right/arg and target
    point to node IDs. target resolves an immutable reference. Temporal nodes
    retain their tree position; equal effective dates do not merge contexts.
    """
    document: str

    def to_dict(self):
        return json.loads(self.document)

    def to_json(self):
        return self.document


def _fail(code, path, message):
    raise FormulaError(code, path, message)


def _shape(value, keys, path):
    if type(value) is not dict or set(value) != set(keys):
        _fail('INVALID_SHAPE', path, 'Fields do not match the declared formula shape.')


def _integer(value, minimum, maximum, path, *, code='INVALID_SHAPE'):
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(code, path, 'Integer is outside its declared bounds.')


def _identifier(value, path):
    if type(value) is not str or not _ID.fullmatch(value):
        _fail('INVALID_SHAPE', path, 'A bounded ASCII variable identity is required.')


def _identity(value, path):
    _shape(value, ('variable_id', 'revision'), path)
    _identifier(value['variable_id'], path + '/variable_id')
    if type(value['revision']) is not str or not _REVISION.fullmatch(value['revision']):
        _fail('INVALID_SHAPE', path + '/revision', 'An immutable content revision is required.')
    return value['variable_id'], value['revision']


def _limits(limits):
    if limits is None:
        return dict(CEILINGS)
    if type(limits) is not dict or set(limits) - set(CEILINGS):
        _fail('INVALID_SHAPE', '/limits', 'Unknown formula limit.')
    result = dict(CEILINGS)
    for key, value in limits.items():
        _integer(value, 1, CEILINGS[key], '/limits/' + key)
        result[key] = value
    return result


def _decimal(value, limits, path, normalized, *, check_binary64=True):
    maximum = limits['expanded_literal'] if normalized else limits['literal']
    if type(value) is not str or not 1 <= len(value) <= maximum:
        _fail('INVALID_LITERAL', path, 'Decimal literal exceeds its length bound.')
    match = _DECIMAL.fullmatch(value)
    if not match:
        _fail('INVALID_LITERAL', path, 'A finite decimal string is required.')
    sign, integer, fraction, leading_fraction, exponent = match.groups()
    exponent = exponent or '0'
    exponent_digits = exponent.lstrip('+-').lstrip('0') or '0'
    if len(exponent_digits) > 4 or abs(int(exponent)) > 2048:
        _fail('INVALID_LITERAL', path, 'Decimal exponent exceeds its expansion bound.')
    integer, fraction = integer or '', (leading_fraction if leading_fraction is not None else fraction) or ''
    digits = (integer + fraction).lstrip('0')
    if not digits:
        result = '0'
    else:
        power = int(exponent) - len(fraction)
        trailing = len(digits) - len(digits.rstrip('0'))
        digits = digits.rstrip('0')
        power += trailing
        point = len(digits) + power
        unsigned_length = (point if power >= 0 else
                           len(digits) + 1 if point > 0 else 2 - point + len(digits))
        if unsigned_length + int(sign == '-') > limits['expanded_literal']:
            _fail('INVALID_LITERAL', path, 'Expanded decimal exceeds its byte bound.')
        if power >= 0:
            result = digits + '0' * power
        elif point > 0:
            result = digits[:point] + '.' + digits[point:]
        else:
            result = '0.' + '0' * -point + digits
        if sign == '-':
            result = '-' + result
    if check_binary64:
        _decimal_binary64(result, path)
    if normalized and result != value:
        _fail('INVALID_LITERAL', path, 'Expanded program literals must already be canonical.')
    return result


def _decimal_binary64(value, path):
    number = float(value)
    if not math.isfinite(number) or (value != '0' and number == 0):
        _fail('INVALID_LITERAL', path, 'Decimal must produce finite non-underflowing binary64.')
    return number


def normalize_quantity(quantity, unit):
    """Normalize a submitted threshold to canonical units with one binary64 cast.

    The original bounded decimal and display unit remain separate evidence.
    Conversion is exact decimal scaling, never floating-point multiplication.
    This helper grants no observation support and changes no legacy comparison.
    """
    _shape(quantity, ('value', 'unit'), '/threshold')
    submitted_unit = quantity['unit']
    scales = {'scalar': ('scalar', 0), 'number': ('scalar', 0),
        'multiple': ('scalar', 0), 'percent': ('scalar', -2),
        'percentage_points': ('scalar', -2), 'USD': ('USD', 0),
        'usd': ('USD', 0), 'usd_million': ('USD', 6),
        'USD/share': ('USD/share', 0), 'usd_per_share': ('USD/share', 0),
        'share': ('share', 0), 'shares': ('share', 0)}
    if type(submitted_unit) is not str or submitted_unit not in scales or scales[submitted_unit][0] != unit:
        _fail('UNIT_MISMATCH', '/threshold/unit', 'Threshold unit does not match the variable.')
    normalized = _decimal(quantity['value'], CEILINGS, '/threshold/value', False,
                          check_binary64=False)
    with localcontext() as context:
        context.prec = 2048
        scaled = format(Decimal(normalized).scaleb(scales[submitted_unit][1]), 'f')
    limits = dict(CEILINGS, literal=CEILINGS['expanded_literal'])
    value = _decimal(scaled, limits, '/threshold/value', False, check_binary64=False)
    return dict(threshold=dict(value=value, unit=unit),
                submitted_threshold=dict(quantity),
                comparison_value=_decimal_binary64(value, '/threshold/value'))


def _normal_definition(definition, limits, path, normalized=False):
    _shape(definition, ('format', 'version', 'parameter_catalog', 'temporal_policy', 'expression', 'output'), path)
    if (definition['format'] != 'variable-definition' or type(definition['version']) is not int
            or definition['version'] not in DEFINITION_VERSIONS
            or definition['temporal_policy'] != (MARKET_TEMPORAL_POLICY
                if definition['parameter_catalog'] == parameters.V4 else TEMPORAL_POLICY)):
        _fail('UNKNOWN_VERSION', path, 'Unsupported definition format, catalog or temporal policy.')
    try:
        catalog = {item['id']: item for item in parameters.catalog(definition['parameter_catalog'])}
        units = parameters.units(definition['parameter_catalog'])
    except ValueError:
        _fail('UNKNOWN_VERSION', path, 'Unsupported definition format, catalog or temporal policy.')
    issues, refs, count = [], [], [0]
    def visit(node, node_path, depth):
        count[0] += 1
        if count[0] > limits['nodes'] or depth > limits['depth']:
            _fail('DEFINITION_LIMIT', node_path, 'Formula exceeds its structural bound.')
        try:
            op = node.get('op') if type(node) is dict else None
            if type(op) is not str or op not in _SHAPES:
                _fail('UNSUPPORTED_OPERATION', node_path, 'Unsupported formula operation.')
            _shape(node, _SHAPES[op], node_path)
            if op == 'positive_div' and definition['version'] < 3:
                _fail('UNSUPPORTED_OPERATION', node_path, 'Positive division requires definition version 3.')
            result = dict(node)
            if op in ('add', 'sub', 'mul', 'div', 'positive_div'):
                result['left'] = visit(node['left'], node_path + '/left', depth + 1)
                result['right'] = visit(node['right'], node_path + '/right', depth + 1)
            elif op in ('neg', 'at', 'lookback'):
                # Visit the argument first for depth-first expression diagnostics.
                result['arg'] = visit(node['arg'], node_path + '/arg', depth + 1)
                if op == 'at':
                    try:
                        day = date.fromisoformat(node['date'])
                    except (TypeError, ValueError):
                        _fail('INVALID_DATE', node_path + '/date', 'A canonical ISO calendar date is required.')
                    if str(day) != node['date']:
                        _fail('INVALID_DATE', node_path + '/date', 'A canonical ISO calendar date is required.')
                elif op == 'lookback':
                    _integer(node['months'], 1, 120, node_path + '/months')
            elif op in ('parameter', 'annual'):
                field = 'id' if op == 'parameter' else 'parameter'
                parameter = node[field]
                if type(parameter) is not str or parameter not in catalog:
                    _fail('UNKNOWN_PARAMETER', node_path + '/' + field, 'Unsupported financial parameter.')
                if op == 'annual':
                    if not parameter.startswith('annual.'):
                        _fail('UNSUPPORTED_OPERATION', node_path, 'Annual statistics require an annual parameter.')
                    statistics = ('mean', 'min', 'max')
                    if definition['version'] >= 2:
                        statistics += ('growth', 'cagr')
                    if node['stat'] not in statistics:
                        _fail('UNSUPPORTED_OPERATION', node_path + '/stat', 'Unsupported annual statistic.')
                    minimum = 2 if node['stat'] in ('growth', 'cagr') else 1
                    _integer(node['count'], minimum, catalog[parameter]['counts']['maximum'], node_path + '/count')
            elif op == 'constant':
                if type(node['unit']) is not str or node['unit'] not in units:
                    _fail('UNIT_MISMATCH', node_path + '/unit', 'A canonical constant unit is required.')
                result['value'] = _decimal(node['value'], limits, node_path + '/value', normalized)
            else:
                identity = _identity({key: node[key] for key in ('variable_id', 'revision')}, node_path)
                refs.append((identity, node_path))
            return result
        except FormulaError as error:
            if error.code == 'DEFINITION_LIMIT':
                raise
            issues.extend(dict(issue) for issue in error.errors)
            return None
    expression = visit(definition['expression'], path + '/expression', 1)
    try:
        _shape(definition['output'], ('unit', 'display'), path + '/output')
        output = dict(definition['output'])
        if type(output['unit']) is not str or output['unit'] not in units:
            _fail('UNSUPPORTED_OUTPUT_UNIT', path + '/output/unit', 'Unsupported output unit.')
        if type(output['display']) is not str or output['display'] not in units[output['unit']]['displays']:
            _fail('UNIT_MISMATCH', path + '/output/display', 'Display does not match the canonical output unit.')
    except FormulaError as error:
        issues.extend(dict(issue) for issue in error.errors)
    if issues:
        raise FormulaError(errors=issues)
    return dict(definition, expression=expression, output=output), refs, count[0]


def revision(definition):
    """Hash normalized definition content without authorizing its references.

    Use this helper to build submitted immutable bundles. Only validate() resolves
    dependencies, infers units and establishes checked semantic validity.
    Backend admission separately determines execution support. No durable
    variable library is consulted or changed.
    """
    normalized, _, _ = _normal_definition(definition, dict(CEILINGS), '')
    return _hash(canonical(normalized))


def _compile(bundle, limits, normalized=False):
    _shape(bundle, ('format', 'version', 'definitions', 'roots'), '')
    if bundle['format'] != 'variable-bundle' or type(bundle['version']) is not int or bundle['version'] != VERSION:
        _fail('UNKNOWN_VERSION', '', 'Unsupported variable bundle version.')
    if type(bundle['definitions']) is not list or type(bundle['roots']) is not list:
        _fail('INVALID_SHAPE', '', 'Definitions and roots must be ordered lists.')
    _integer(len(bundle['definitions']), 1, limits['definitions'], '/definitions', code='DEFINITION_LIMIT')
    if not bundle['roots']:
        _fail('INVALID_SHAPE', '/roots', 'At least one formula root is required.')
    minimum_root_bytes = len(canonical(dict(variable_id='a', revision='sha256:' + '0' * 64)))
    if len(bundle['roots']) * minimum_root_bytes > limits['bytes']:
        _fail('DEFINITION_LIMIT', '/roots', 'Formula roots exceed the submission byte bound.')
    entries, keys, dependencies, source_indexes, total_nodes, errors = [], {}, [], [], 0, []
    for index, entry in enumerate(bundle['definitions']):
        path = '/definitions/' + str(index)
        try:
            _shape(entry, ('variable_id', 'revision', 'definition'), path)
            identity = _identity({key: entry[key] for key in ('variable_id', 'revision')}, path)
            definition, refs, nodes = _normal_definition(entry['definition'], limits, path + '/definition', normalized)
            value = dict(entry, definition=definition)
            if identity in keys:
                if entries[keys[identity]] != value:
                    _fail('REVISION_MISMATCH', path, 'Duplicate immutable identity has different content.')
                continue
            total_nodes += nodes
            if total_nodes > limits['nodes']:
                _fail('DEFINITION_LIMIT', path, 'Resolved bundle exceeds its node bound.')
            keys[identity] = len(entries)
            entries.append(value)
            dependencies.append(refs)
            source_indexes.append(index)
        except FormulaError as error:
            if error.code == 'DEFINITION_LIMIT':
                raise
            errors.extend(dict(issue) for issue in error.errors)
    if errors:
        raise FormulaError(errors=errors)
    roots = []
    for index, root in enumerate(bundle['roots']):
        roots.append(_identity(root, '/roots/' + str(index)))
    for refs in dependencies:
        for identity, path in refs:
            if identity not in keys:
                _fail('MISSING_REFERENCE', path, 'Immutable referenced definition is absent.')
    for index, identity in enumerate(roots):
        if identity not in keys:
            _fail('MISSING_REFERENCE', '/roots/' + str(index), 'Formula root is absent.')
    # Resolve graph shape before comparing content hashes. Cycles cannot acquire
    # a valid hash fixed point, but must receive a deliberate graph diagnostic.
    visiting, complete, dependency_depths = set(), set(), {}
    def graph(index):
        if index in visiting:
            _fail('DEPENDENCY_CYCLE', '/definitions/' + str(source_indexes[index]), 'Formula dependency cycle.')
        if index in complete:
            return dependency_depths[index]
        visiting.add(index)
        depth = 1
        for identity, path in dependencies[index]:
            depth = max(depth, 1 + graph(keys[identity]))
        if depth > limits['dependency_depth']:
            _fail('DEFINITION_LIMIT', '/definitions/' + str(source_indexes[index]), 'Formula dependency depth exceeds its bound.')
        visiting.remove(index)
        complete.add(index)
        dependency_depths[index] = depth
        return depth
    for index in range(len(entries)):
        graph(index)
    for index, entry in enumerate(entries):
        if _hash(canonical(entry['definition'])) != entry['revision']:
            _fail('REVISION_MISMATCH', '/definitions/' + str(source_indexes[index]) + '/revision', 'Definition content does not match its revision.')
    normalized_bundle = dict(format='variable-bundle', version=VERSION, definitions=entries,
        roots=[dict(variable_id=identity[0], revision=identity[1]) for identity in roots])
    # Both submitted and expanded bytes are bounded. Expansion is checked before
    # constructing any long decimal, and structural parsing precedes encoding.
    for value in (bundle, normalized_bundle):
        if len(canonical(value).encode('utf-8')) > limits['bytes']:
            _fail('DEFINITION_LIMIT', '', 'Formula bundle exceeds its byte bound.')
    catalogs = [{item['id']: item for item in parameters.catalog(entry['definition']['parameter_catalog'])}
                for entry in entries]
    unit_vocabularies = [parameters.units(entry['definition']['parameter_catalog']) for entry in entries]
    nodes, definition_roots, requirements = [], {}, []
    def lower(node, path, definition_index):
        identity = 'n' + str(len(nodes))
        item = dict(id=identity, op=node['op'], path=path, definition=definition_index)
        nodes.append(item)
        op = node['op']
        if op in ('add', 'sub', 'mul', 'div', 'positive_div'):
            for field in ('left', 'right'):
                item[field] = lower(node[field], path + '/' + field, definition_index)
        elif op in ('neg', 'at', 'lookback'):
            item['arg'] = lower(node['arg'], path + '/arg', definition_index)
            if op != 'neg':
                field = 'date' if op == 'at' else 'months'
                item[field] = node[field]
        elif op == 'ref':
            item['target_definition'] = keys[(node['variable_id'], node['revision'])]
        elif op == 'constant':
            item.update(value=node['value'], unit=node['unit'])
        else:
            item['parameter'] = node['id'] if op == 'parameter' else node['parameter']
            item['count'] = 1 if op == 'parameter' else node['count']
            if op == 'annual':
                item['stat'] = node['stat']
            requirements.append(dict(node=identity, parameter=item['parameter'], count=item['count']))
        return identity
    for index, entry in enumerate(entries):
        definition_roots[index] = lower(entry['definition']['expression'],
            '/definitions/' + str(index) + '/definition/expression', index)
    node_by_id = {node['id']: node for node in nodes}
    for node in nodes:
        if node['op'] == 'ref':
            node['target'] = definition_roots[node.pop('target_definition')]
    def submitted_path(item):
        # Projection paths address the normalized bundle. Diagnostics must still
        # address the submitted entry after identical definitions collapse.
        prefix = '/definitions/' + str(item['definition'])
        return '/definitions/' + str(source_indexes[item['definition']]) + item['path'][len(prefix):]
    inferred, expanded_depths = {}, {}
    def infer(identity):
        if identity in inferred:
            return inferred[identity]
        item = node_by_id[identity]
        op, depth = item['op'], 1
        if op in ('parameter', 'annual'):
            # Growth is a fraction over count-1 annual intervals, regardless of
            # the underlying annual parameter's dimension or catalog version.
            unit = ('scalar' if op == 'annual' and item['stat'] in ('growth', 'cagr')
                    else catalogs[item['definition']][item['parameter']]['unit'])
            dimensions = dict(unit_vocabularies[item['definition']][unit]['dimensions'])
        elif op == 'constant':
            dimensions = dict(unit_vocabularies[item['definition']][item['unit']]['dimensions'])
        elif op in ('neg', 'at', 'lookback', 'ref'):
            target = item['target'] if op == 'ref' else item['arg']
            dimensions = dict(infer(target))
            depth += expanded_depths[target]
        else:
            left, right = infer(item['left']), infer(item['right'])
            depth += max(expanded_depths[item['left']], expanded_depths[item['right']])
            if op in ('add', 'sub'):
                if left != right:
                    _fail('UNIT_MISMATCH', submitted_path(item), 'Addition and subtraction require identical dimensions.')
                dimensions = dict(left)
            else:
                dimensions = dict(left)
                for unit, power in right.items():
                    dimensions[unit] = dimensions.get(unit, 0) + power * (1 if op == 'mul' else -1)
                dimensions = {key: value for key, value in dimensions.items() if value}
        if depth > limits['depth']:
            _fail('DEFINITION_LIMIT', submitted_path(item), 'Resolved expression depth exceeds its bound.')
        item['dimensions'] = dimensions
        inferred[identity], expanded_depths[identity] = dimensions, depth
        return dimensions
    resolved = []
    for index, entry in enumerate(entries):
        root = definition_roots[index]
        dimensions = infer(root)
        unit = next((name for name, value in unit_vocabularies[index].items()
                     if value['dimensions'] == dimensions), None)
        if unit is None:
            _fail('UNSUPPORTED_OUTPUT_UNIT', '/definitions/' + str(source_indexes[index]) + '/definition/output', 'Formula output has unsupported dimensions.')
        if unit != entry['definition']['output']['unit']:
            _fail('UNIT_MISMATCH', '/definitions/' + str(source_indexes[index]) + '/definition/output/unit', 'Declared output differs from the inferred unit.')
        resolved.append(dict(variable_id=entry['variable_id'], revision=entry['revision'],
            root=root, unit=unit, display=entry['definition']['output']['display'],
            dependencies=list(dict.fromkeys(keys[identity] for identity, _ in dependencies[index]))))
    return dict(format='formula-program', version=VERSION, bundle=normalized_bundle,
        bundle_revision=_hash(canonical(normalized_bundle)), limits=limits,
        definitions=resolved, roots=[keys[identity] for identity in roots],
        nodes=nodes, requirements=requirements)


def validate(bundle, limits=None):
    """Resolve a raw immutable bundle; errors prevent financial work.

    Limits can only lower fixed capabilities. All captured definitions, including
    unreferenced entries, must be valid. Array order contributes to bundle
    identity; repeated identical definitions normalize to their first occurrence.
    """
    return FormulaProgram(canonical(_compile(bundle, _limits(limits))))


def resolve(roots, lookup, *, submitted=None, limits=None, checkpoint=lambda: None):
    """Capture exact revisions through a bounded, caller-owned lookup snapshot.

    lookup(variable_id, revision) returns an authored raw definition or None.
    It must keep one consistent snapshot for the call. Submitted entries use the
    ordinary bundle entry shape and take precedence over lookup. All submitted
    entries are retained and checked, including unused entries. Missing roots or
    dependencies fail; there is no current/latest resolution. Entries are ordered
    by submission, then first-use depth-first lookup. Roots retain their order.

    This operation owns reference discovery and calls the existing validator.
    It accepts only raw authored literals, never canonical expanded submissions.
    The returned FormulaProgram owns all content and retains no callback.
    """
    bound = _limits(limits)
    if not callable(lookup) or not callable(checkpoint):
        _fail('INVALID_SHAPE', '', 'Resolution requires lookup and checkpoint callbacks.')
    if type(roots) is not list or not roots:
        _fail('INVALID_SHAPE', '/roots', 'At least one ordered exact root is required.')
    minimum = len(canonical(dict(variable_id='a', revision='sha256:' + '0' * 64)))
    if len(roots) * minimum > bound['bytes']:
        _fail('DEFINITION_LIMIT', '/roots', 'Formula roots exceed the submission byte bound.')
    checked_roots = []
    for index, root in enumerate(roots):
        checkpoint()
        variable_id, content_revision = _identity(root, '/roots/' + str(index))
        checked_roots.append(dict(variable_id=variable_id, revision=content_revision))
    if len(canonical(checked_roots)) > bound['bytes']:
        _fail('DEFINITION_LIMIT', '/roots', 'Formula roots exceed the submission byte bound.')
    submitted = [] if submitted is None else submitted
    if type(submitted) is not list:
        _fail('INVALID_SHAPE', '/definitions', 'Submitted definitions must be an ordered list.')
    if len(submitted) > bound['definitions']:
        _fail('DEFINITION_LIMIT', '/definitions', 'Too many submitted definitions.')
    entries, known, references = [], {}, {}
    raw_bytes, normalized_bytes, nodes = len(canonical(checked_roots)), len(canonical(checked_roots)), 0

    def retain(entry):
        nonlocal raw_bytes, normalized_bytes, nodes
        checkpoint()
        path = '/definitions/' + str(len(entries))
        _shape(entry, ('variable_id', 'revision', 'definition'), path)
        identity = _identity({key: entry[key] for key in ('variable_id', 'revision')}, path)
        normalized, refs, count = _normal_definition(entry['definition'], bound, path + '/definition')
        normalized_entry = dict(entry, definition=normalized)
        if identity in known:
            if known[identity] != normalized_entry:
                _fail('REVISION_MISMATCH', path, 'Duplicate immutable identity has different content.')
            return identity
        if len(entries) >= bound['definitions'] or nodes + count > bound['nodes']:
            _fail('DEFINITION_LIMIT', path, 'Resolved bundle exceeds its structural bound.')
        raw_document, normal_document = canonical(entry), canonical(normalized_entry)
        raw_bytes += len(raw_document)
        normalized_bytes += len(normal_document)
        if max(raw_bytes, normalized_bytes) > bound['bytes']:
            _fail('DEFINITION_LIMIT', path, 'Resolved bundle exceeds its byte bound.')
        nodes += count
        entries.append(json.loads(raw_document))
        known[identity], references[identity] = normalized_entry, refs
        return identity

    for entry in submitted:
        retain(entry)
    visited = set()

    def discover(identity, path):
        checkpoint()
        if identity in visited:
            return
        if identity not in known:
            # Check capacity before asking storage for another definition.
            if len(entries) >= bound['definitions']:
                _fail('DEFINITION_LIMIT', path, 'Resolved bundle exceeds its definition bound.')
            definition = lookup(*identity)
            checkpoint()
            if definition is None:
                _fail('MISSING_REFERENCE', path, 'Immutable referenced definition is absent.')
            retain(dict(variable_id=identity[0], revision=identity[1], definition=definition))
        visited.add(identity)
        for dependency, dependency_path in references[identity]:
            discover(dependency, dependency_path)

    for index, root in enumerate(checked_roots):
        discover((root['variable_id'], root['revision']), '/roots/' + str(index))
    # Unused submitted entries receive the same complete validation as a bundle.
    for identity in list(known):
        discover(identity, '/definitions')
    checkpoint()
    program = validate(dict(format='variable-bundle', version=VERSION,
                            definitions=entries, roots=checked_roots), bound)
    checkpoint()
    return program


def require_program(program):
    """Reconstruct and check a program before execution; return detached content.

    This is the one formula gate. The column evaluator implements every
    program it returns.

    This restore path admits canonical expanded literals only inside a complete
    FormulaProgram. Every identity, edge, unit, requirement and limit is rebuilt
    and compared. It does not let raw submissions bypass their literal bound.
    """
    if type(program) is not FormulaProgram or type(program.document) is not str:
        _fail('INVALID_SHAPE', '', 'A validated immutable formula program is required.')
    # The projection repeats bounded bundle content and adds resolved metadata.
    # Bound decoding independently of attacker-controlled recorded limits.
    if len(program.document) > 8 * CEILINGS['bytes']:
        _fail('DEFINITION_LIMIT', '', 'Serialized formula program exceeds its byte bound.')
    try:
        submitted = program.to_dict()
    except (TypeError, ValueError, RecursionError):
        _fail('INVALID_SHAPE', '', 'Formula program is malformed.')
    _shape(submitted, ('format', 'version', 'bundle', 'bundle_revision', 'limits',
                       'definitions', 'roots', 'nodes', 'requirements'), '')
    rebuilt = _compile(submitted['bundle'], _limits(submitted['limits']), normalized=True)
    if canonical(rebuilt) != program.document:
        _fail('INVALID_SHAPE', '', 'Formula program is not its canonical validated projection.')
    return rebuilt


def authored_bundle(program, roots=None):
    """Return an exact raw editable closure from a checked detached program.

    Restoration itself never needs this conversion. Expanded decimals are
    compacted with string arithmetic, then normal language validation proves
    every recorded revision. No binary64 round trip or raw-limit exception is
    permitted. Explicit roots retain order and repeated exact identities.
    """
    checked = require_program(program)
    entries = checked['bundle']['definitions']
    roots = checked['bundle']['roots'] if roots is None else roots
    if type(roots) is not list or not roots:
        _fail('INVALID_SHAPE', '/roots', 'Editable content needs exact roots.')
    by_identity = {(item['variable_id'], item['revision']): index for index, item in enumerate(entries)}
    selected = set()
    def retain(index):
        if index in selected:
            return
        selected.add(index)
        for dependency in checked['definitions'][index]['dependencies']:
            retain(dependency)
    for index, root in enumerate(roots):
        identity = _identity(root, '/roots/' + str(index))
        if identity not in by_identity:
            _fail('MISSING_REFERENCE', '/roots/' + str(index), 'Editable root is absent from the captured program.')
        retain(by_identity[identity])
    def editable(node):
        result = dict(node)
        if node['op'] == 'constant':
            value = node['value']
            if len(value) > CEILINGS['literal']:
                sign = '-' if value.startswith('-') else ''
                unsigned = value.lstrip('-')
                whole, _, fraction = unsigned.partition('.')
                digits = (whole + fraction).lstrip('0')
                power = -len(fraction)
                trailing = len(digits) - len(digits.rstrip('0'))
                digits = digits.rstrip('0'); power += trailing
                exponent = power + len(digits) - 1
                compact = sign + digits[0] + ('.' + digits[1:] if len(digits) > 1 else '') + 'e' + str(exponent)
                if len(compact) > CEILINGS['literal']:
                    _fail('INVALID_LITERAL', '/expression', 'This exact captured literal has no bounded editable spelling.')
                result['value'] = compact
        for key in ('left', 'right', 'arg'):
            if key in result:
                result[key] = editable(result[key])
        return result
    authored = []
    for index, entry in enumerate(entries):
        if index not in selected:
            continue
        definition = dict(entry['definition'], expression=editable(entry['definition']['expression']))
        if revision(definition) != entry['revision']:
            _fail('REVISION_MISMATCH', '/definitions', 'Editable conversion changed immutable formula meaning.')
        authored.append(dict(variable_id=entry['variable_id'], revision=entry['revision'], definition=definition))
    bundle = dict(format='variable-bundle', version=VERSION, definitions=authored,
                  roots=json.loads(canonical(roots)))
    validate(bundle)
    return bundle


def references(definition):
    """Return exact authored dependency identities using the language parser."""
    _, refs, _ = _normal_definition(definition, _limits(None), '')
    return [dict(variable_id=identity[0], revision=identity[1]) for identity, _ in refs]


def upgrade(entries):
    """Market-aware form of a closed authored set; the whole closure becomes /4;
    variable_ids never change; returns the old→new identity map.

    The input is trusted checked content, such as authored_bundle output.
    Entries keep their order; old revisions with one new form appear once.
    revisions maps each old (variable_id, revision) to its new revision.
    """
    authored = {(entry['variable_id'], entry['revision']): entry['definition'] for entry in entries}
    revisions, upgraded = {}, {}
    def form(identity):
        if identity not in revisions:
            definition = json.loads(canonical(authored[identity]))
            if definition['parameter_catalog'] != parameters.V4:
                definition.update(version=3, parameter_catalog=parameters.V4,
                                  temporal_policy=MARKET_TEMPORAL_POLICY)
            def remap(node):
                if node['op'] == 'ref':
                    node['revision'] = form((node['variable_id'], node['revision']))
                for field in ('left', 'right', 'arg'):
                    if field in node:
                        remap(node[field])
            remap(definition['expression'])
            upgraded[identity], revisions[identity] = definition, revision(definition)
        return revisions[identity]
    result = {}
    for entry in entries:
        old = entry['variable_id'], entry['revision']
        new = old[0], form(old)
        result.setdefault(new, dict(variable_id=new[0], revision=new[1], definition=upgraded[old]))
    return list(result.values()), revisions
