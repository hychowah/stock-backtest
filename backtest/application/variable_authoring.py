"""Financial-free authoring over the existing language, library and capture owners.

Raw edits and checked detached restoration are distinct. Exact submitted content
wins over archive lookup. No operation starts a calculation or owns financial
resources.
"""
from copy import deepcopy

from backtest.runtime import backtest_control
from backtest.variables import columns, definitions, library, parameters, measures
from backtest.application import formula_text, strategy_requests, vocabulary


def catalog():
    """Editor descriptors from the language, parameter and measure owners."""
    available = {item['id']: item for item in columns.catalog()}
    admitted = [available[item['id']] for item in parameters.catalog(parameters.V1)]
    terms = []
    for descriptor in measures.catalog(parameters.V4):
        bundle = measures.bundle([descriptor['id']], parameters.V4)
        labels = []
        for entry in bundle['definitions']:
            found = measures.exact(entry['variable_id'], entry['revision'])
            labels.append(dict(variable_id=entry['variable_id'], revision=entry['revision'], name=found['name']))
        terms.append(dict(descriptor, submitted=bundle['definitions'], labels=labels))
    return dict(parameters=admitted, builtins=strategy_requests.builtin_catalog(),
                expanded_parameters=parameters.catalog(parameters.V4), version2_parameters=parameters.catalog(parameters.V2),
                version3_parameters=parameters.catalog(parameters.V3), measures=terms, units=parameters.units(parameters.V4),
                operations=sorted(definitions.OPERATIONS),
                namespaces=[parameters.V1,parameters.V2,parameters.V3,parameters.V4],
                current_parameter_catalog=parameters.V4, current_temporal_policy=definitions.MARKET_TEMPORAL_POLICY,
                displays={unit:details['displays'] for unit,details in parameters.units(parameters.V4).items()},
                preview_limit=16, preview_engine='original', strategy_bytes=strategy_requests.STRATEGY_BYTES,
                request_bytes=strategy_requests.REQUEST_BYTES,
                vocabulary=[dict(item, text=formula_text.spelling(item['name'])) for item in vocabulary.entries()],
                functions=[dict(item) for item in formula_text.FUNCTIONS])


def entries(store):
    """Active library entries, each with the typed spelling of its name."""
    return [dict(item, text=formula_text.spelling(item['name'])) for item in store.list()]


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
    """Check a typed formula or a raw editor definition and complete dependencies without saving.

    The request has exactly one of formula {text, display} and definition.
    base {root, capture} is what opened the formula, as detached takes it.
    Text equal to detached(base)'s text, repeated spaces ignored, keeps base's
    definition and its references and applies only the display. Other text is
    read in the current form; its names come from the vocabulary and the
    library. The display stays when it suits the inferred unit, else the
    unit's default applies; an empty name becomes the text. Formula errors
    raise formula_text.TextError; errors from the definition owner carry no
    position. The definition owner supplies the revision, units and
    requirements. Captures include exact references. Missing storage is valid
    for a complete local draft.
    """
    if type(request) is not dict or ('definition' in request) == ('formula' in request):
        raise ValueError('Send a formula or a variable definition.')
    if 'definition' in request:
        return _checked(request, request['definition'], request.get('name'), store, checkpoint)
    formula = request['formula']
    if type(formula) is not dict or type(formula.get('text')) is not str:
        raise ValueError('A formula needs its text.')
    text = ' '.join(formula['text'].split())
    name = request.get('name').strip() if type(request.get('name')) is str else ''
    name = name or text[:120].strip()
    content = dict(variable_id=request.get('variable_id', 'local:editor'))
    try:
        if request.get('base') is not None:
            opened = detached(request['base'])
            if text == ' '.join(opened['text'].split()):
                selected = opened['selected']['variable_id'], opened['selected']['revision']
                definition = next(item['definition'] for item in opened['authored']
                                  if (item['variable_id'], item['revision']) == selected)
                unit = definition['output']['unit']
                definition = dict(definition, output=dict(unit=unit, display=_display(formula.get('display'), unit)))
                checked = _checked(dict(content, detached=[request['base']['capture']]), definition, name, store, checkpoint)
                return dict(checked, picture=formula_text.picture(definition, opened['capture']['presentation']), name=name)
        expression, picture = formula_text.from_text(formula['text'], store.list())
        definition = dict(format='variable-definition', version=3, parameter_catalog=parameters.V4,
                          temporal_policy=definitions.MARKET_TEMPORAL_POLICY, expression=expression)
        # The output is provisional: the definition owner checks the tree here,
        # before the referenced units are known.
        references = definitions.references(dict(definition, output=dict(unit='scalar', display='number')))
        keys = [item['variable_id'].split(':', 1)[1] for item in references if item['variable_id'].startswith('measure:')]
        if keys:
            bundled = measures.bundle(keys, parameters.V4)['definitions']
            content.update(submitted=bundled, labels=[dict(variable_id=item['variable_id'], revision=item['revision'],
                                                           name=measures.exact(item['variable_id'], item['revision'])['name'])
                                                      for item in bundled])
        units = {}
        if references:
            closure, names = _content(content, references)
            program = _capture(references, store, closure, names, checkpoint).to_dict()['program']
            units = {(item['variable_id'], item['revision']): item['unit'] for item in program['definitions']}
        unit = definitions.output_unit(definition, units)
        definition['output'] = dict(unit=unit, display=_display(formula.get('display'), unit))
        return dict(_checked(content, definition, name, store, checkpoint), picture=picture, name=name)
    except definitions.FormulaError as error:
        raise formula_text.TextError([dict(code=error.code, message=str(error), suggestions=[])]) from None


def _display(display, unit):
    return display if display in parameters.units(parameters.V4)[unit]['displays'] else vocabulary.DISPLAYS[unit]


def _checked(request, definition, name, store, checkpoint):
    root = dict(variable_id=request.get('variable_id','local:editor'), revision=definitions.revision(definition))
    entries, labels = _content(request, [root] + definitions.references(definition))
    entries = [item for item in entries if (item['variable_id'],item['revision']) != (root['variable_id'],root['revision'])]
    entries.append(dict(root, definition=definition))
    labels = [item for item in labels if (item['variable_id'],item['revision']) != (root['variable_id'],root['revision'])]
    labels.append(dict(root, name=name or root['variable_id']))
    captured = _capture([root],store,entries,labels,checkpoint)
    checked = captured.to_dict()['program']
    output = next(item for item in checked['definitions'] if (item['variable_id'],item['revision']) == (root['variable_id'],root['revision']))
    return dict(root=root, output=output, requirements=checked['requirements'], capture=captured.to_dict(),
                authored=definitions.authored_bundle(captured.program)['definitions'])


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
    definition = next(item['definition'] for item in authored['definitions']
                      if (item['variable_id'],item['revision']) == (selected['variable_id'],selected['revision']))
    return dict(selected=selected,name=label['name'],authored=authored['definitions'],capture=checked,
                text=formula_text.to_text(definition, checked['presentation']))


def authoring_snapshot(request, store):
    """Read an exact saved revision for editing, with its text as detached prints it."""
    snapshot = store.authoring_snapshot(request)
    return dict(snapshot, text=detached(dict(root=snapshot['selected'], capture=snapshot['capture']))['text'])


def prepare(request, store, *, checkpoint=backtest_control.checkpoint):
    """Capture one draft snapshot for one market before retry identity; HK/JP
    captures use the market-aware form; the draft is unchanged.

    Drafts submit complete detached dependencies and labels; absent exact
    archives fail rather than substituting newer revisions. This never imports
    those records. A US capture keeps every formula as submitted.
    """
    if type(request) is not dict or type(request.get('intent')) is not dict:
        raise ValueError('A complete strategy intent is required.')
    if request.get('market') not in ('us', 'hk', 'jp'):
        raise ValueError('Choose US, Hong Kong or Japan.')
    # Only the reachable closure is retained. Old editor revisions can coexist
    # locally without changing the submitted calculation or exceeding limits.
    roots = []
    for source in strategy_requests.sources(request['intent']):
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
    value = captured.to_dict()
    if request['market'] == 'us' or value['variables'] is None:
        return dict(strategy=value)
    # Capture the market-aware closure again from submitted content only, so
    # the stored request is what runs. Names carry over by variable ID.
    program = _variable(value['variables']).program
    authored, revisions = definitions.upgrade(definitions.authored_bundle(program)['definitions'])
    intent = deepcopy(request['intent'])
    for source in strategy_requests.sources(intent):
        if source.get('kind') == 'formula':
            source['revision'] = revisions[source['variable_id'], source['revision']]
    names = {item['variable_id']: item['name'] for item in value['variables']['presentation']}
    labels = [dict(variable_id=item['variable_id'], revision=item['revision'], name=names[item['variable_id']]) for item in authored]
    captured = strategy_requests.capture_strategy(intent,submitted=authored,labels=labels,checkpoint=checkpoint)
    return dict(strategy=captured.to_dict())
