"""Completed eager artifact validation and original stored summary projection."""
def validate(snapshot):
    """Check completeness, without reinterpreting financial calculations."""
    if not isinstance(snapshot,dict) or snapshot.get('version') not in (1,2):
        raise ValueError('Unsupported saved backtest format.')
    kind=snapshot.get('kind')
    if kind not in ('january','custom','random'):
        raise ValueError('Run a historical backtest before saving it.')
    settings=snapshot.get('settings');result=snapshot.get('result')
    if not isinstance(settings,dict) or settings.get('mode')!=kind or not isinstance(result,dict):
        raise ValueError('The result and its submitted settings are required.')
    groups=result.get('years' if kind=='january' else 'periods')
    if kind=='random':
        details=result.get('trial_results');trials=result.get('trials')
        if not isinstance(details,list) or not isinstance(trials,list) or not trials or len(details)!=len(trials) or len(trials)!=result.get('completed'):
            raise ValueError('All random trials must include their traded stocks before saving.')
        groups=[]
        for trial,detail in zip(trials,details):
            if not isinstance(trial,dict):raise ValueError('Missing random-trial summary.')
            if not isinstance(detail,dict) or not isinstance(detail.get('periods'),list):
                raise ValueError('Missing random-trial holdings.')
            if len(detail['periods'])!=trial.get('periods'):
                raise ValueError('Incomplete random-trial holdings.')
            groups.extend(detail['periods'])
    if not isinstance(groups,list) or not groups:
        raise ValueError('The complete holding periods are required.')
    for group in groups:
        if not isinstance(group,dict) or not isinstance(group.get('holdings'),list) or len(group['holdings'])!=group.get('names'):
            raise ValueError('Each holding period must contain all traded stocks.')
        if 'portfolio' not in group or 'spy' not in group or any(not isinstance(h,dict) or 'symbol' not in h or 'return_value' not in h for h in group['holdings']):
            raise ValueError('Stock and period returns are required.')
    catalog=snapshot.get('catalog')
    if catalog is not None and (not isinstance(catalog,dict) or not isinstance(catalog.get('metrics'),dict) or not isinstance(catalog.get('filters'),dict)):
        raise ValueError('Saved display labels are invalid.')
    if snapshot['version']==2 and not isinstance(snapshot.get('presentation'),dict):
        raise ValueError('Saved presentation context is required.')
    return snapshot


def information(snapshot):
    result=snapshot['result'];kind=snapshot['kind']
    configuration=result.get('configuration',{}) if kind=='random' else result
    dates=configuration.get('calendar',configuration)
    return dict(kind=kind,start=dates.get('start',result.get('first')),
                end=dates.get('end',result.get('end')),
                cagr=result.get('cagr') if kind!='random' else result.get('distributions',{}).get('cagr',{}).get('mean'),
                trials=result.get('completed') if kind=='random' else None)
