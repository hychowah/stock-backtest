"""Financial-free authoring over the existing language, library and capture owners.

Raw edits and checked detached restoration are distinct. Exact submitted content
wins over archive lookup. Unchanged captures are returned without a library or
catalog read. No operation starts a calculation or owns financial resources.
"""
from backtest.runtime import backtest_control
from backtest.variables import columns, definitions, library, parameters, measures
from backtest.application import strategy_requests


def catalog():
    """Editor descriptors; each support flag comes from the one formula gate's inventory."""
    available = {item['id']: item for item in columns.catalog()}
    admitted = [available[item['id']] for item in parameters.catalog(parameters.V1)]
    expanded = parameters.catalog(parameters.V3)
    for item in expanded:
        item['support']=dict(original=item['id'] in available)
    terms = []
    for descriptor in measures.catalog():
        bundle = measures.bundle([descriptor['id']])
        labels = []
        for entry in bundle['definitions']:
            found = measures.exact(entry['variable_id'], entry['revision'])
            labels.append(dict(variable_id=entry['variable_id'], revision=entry['revision'], name=found['name']))
        program=definitions.validate(bundle)
        try:
            strategy_requests.require_formula_support(program,'original')
            original=True
        except definitions.FormulaError:
            original=False
        terms.append(dict(descriptor, submitted=bundle['definitions'], labels=labels,
            support=dict(original=original)))
    return dict(parameters=admitted, builtins=strategy_requests.builtin_catalog(),
                expanded_parameters=expanded, version2_parameters=parameters.catalog(parameters.V2), measures=terms, units=parameters.units(parameters.V3),
                operations=sorted(columns.OPERATIONS),
                namespaces=[parameters.V1,parameters.V2,parameters.V3],
                displays={unit:details['displays'] for unit,details in parameters.units(parameters.V3).items()},
                preview_limit=16, preview_engine='original', strategy_bytes=strategy_requests.STRATEGY_BYTES,
                request_bytes=strategy_requests.REQUEST_BYTES)


def _variable(value):
    return library.VariableCapture(definitions.canonical(value))


def _content(request, roots=None):
    entries, names = {}, {}
    for value in request.get('detached', []):
        captured = library.require_capture(_variable(value))
        program = _variable(value).program
        available = {(item['variable_id'],item['revision']) for item in captured['program']['bundle']['definitions']}
        chosen = [root for root in roots if (root['variable_id'],root['revision']) in available] if roots is not None else None
        if chosen == []:
            continue
        bundle = definitions.authored_bundle(program, chosen)
        for item in bundle['definitions']:
            entries[item['variable_id'], item['revision']] = item
        retained = {(item['variable_id'],item['revision']) for item in bundle['definitions']}
        for item in captured['presentation']:
            if (item['variable_id'],item['revision']) not in retained:
                continue
            names[item['variable_id'], item['revision']] = {key:item[key] for key in ('variable_id','revision','name')}
    for item in request.get('submitted', []):
        identity = item.get('variable_id'), item.get('revision')
        if identity in entries and definitions.revision(item.get('definition')) != identity[1]:
            raise definitions.FormulaError('REVISION_MISMATCH', '/submitted', 'Edited content disagrees with its exact revision.')
        entries[identity] = item
    for item in request.get('labels', []):
        names[item.get('variable_id'), item.get('revision')] = item
    return list(entries.values()), list(names.values())


def _capture(roots, store, entries, labels, checkpoint):
    try:
        return library.capture_submitted(roots, submitted=entries, labels=labels, checkpoint=checkpoint)
    except definitions.FormulaError as missing:
        if missing.code != 'MISSING_REFERENCE':
            raise
        try:
            return store.capture(roots, submitted=entries, labels=labels, checkpoint=checkpoint)
        except library.Missing:
            raise missing


def validate(request, store, *, checkpoint=backtest_control.checkpoint):
    """Validate a raw editor definition and complete dependencies without saving.

    The definition owner supplies the revision, units and requirements. Captures
    include exact references. Missing storage is valid for a complete local draft.
    """
    if type(request) is not dict or 'definition' not in request:
        raise ValueError('A variable definition is required.')
    definition = request['definition']
    root = dict(variable_id=request.get('variable_id','local:editor'), revision=definitions.revision(definition))
    entries, labels = _content(request, [root] + definitions.references(definition))
    entries = [item for item in entries if (item['variable_id'],item['revision']) != (root['variable_id'],root['revision'])]
    entries.append(dict(root, definition=definition))
    labels = [item for item in labels if (item['variable_id'],item['revision']) != (root['variable_id'],root['revision'])]
    labels.append(dict(root, name=request.get('name') or root['variable_id']))
    captured = _capture([root],store,entries,labels,checkpoint)
    checked = captured.to_dict()['program']
    output = next(item for item in checked['definitions'] if (item['variable_id'],item['revision']) == (root['variable_id'],root['revision']))
    return dict(root=root, output=output, requirements=checked['requirements'], capture=captured.to_dict(),
                authored=definitions.authored_bundle(captured.program)['definitions'])


def intent(capture):
    checked = strategy_requests.require_strategy(strategy_requests.from_wire(capture))
    return dict(format='strategy-intent',version=1,selection=checked['selection'],pool=checked['pool'],bounds=checked['bounds'])


def detached(request):
    """Open an exact captured selection for editing without an archive lookup."""
    if type(request) is not dict or set(request) != {'capture','root'}:
        raise ValueError('An exact root and complete detached variable capture are required.')
    captured = _variable(request['capture'])
    checked = library.require_capture(captured)
    authored = definitions.authored_bundle(captured.program, [request['root']])
    selected = authored['roots'][0]
    label = next(item for item in checked['presentation']
                 if (item['variable_id'],item['revision']) == (selected['variable_id'],selected['revision']))
    return dict(selected=selected,name=label['name'],authored=authored['definitions'],capture=checked)


def prepare(request, store, *, checkpoint=backtest_control.checkpoint):
    """Capture one draft snapshot before transport owners allocate retry identity.

    An unchanged restored capture stays byte-for-byte unchanged. Changed drafts
    submit complete detached dependencies and labels; absent exact archives fail
    rather than substituting newer revisions. This never imports those records.
    """
    if type(request) is not dict or type(request.get('intent')) is not dict:
        raise ValueError('A complete strategy intent is required.')
    if request.get('original') is not None and request['intent'] == intent(request['original']):
        checked = strategy_requests.require_strategy(strategy_requests.from_wire(request['original']))
        return dict(strategy=checked)
    # Only the reachable closure is retained. Old editor revisions can coexist
    # locally without changing the submitted calculation or exceeding limits.
    roots = []
    selection = request['intent']['selection']
    for source in [selection['ranking']['source']] + [item['source'] for item in selection.get('conditions',[])]:
        if source.get('kind') == 'formula':
            roots.append({key:source[key] for key in ('variable_id','revision')})
    entries, labels = _content(request, roots) if roots else ([], [])
    try:
        captured = strategy_requests.capture_strategy(request['intent'],submitted=entries,labels=labels,checkpoint=checkpoint)
    except definitions.FormulaError as missing:
        if missing.code != 'MISSING_REFERENCE':
            raise
        try:
            captured = strategy_requests.capture_strategy(request['intent'],store,submitted=entries,labels=labels,checkpoint=checkpoint)
        except library.Missing:
            raise missing
    return dict(strategy=captured.to_dict())
