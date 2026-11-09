"""Explicit browser assets and source-only recovery-page assembly."""
import json
from pathlib import Path

BROWSER=Path(__file__).resolve().parents[1]/'browser'
SCRIPT_NAMES=('engine-controls.js','calendar-settings.js','result-artifacts.js',
    'backtest-comparison.js','saved-backtests.js','screener.js','contributions.js',
    'robustness.js','backtest-runs.js','variable-evidence.js','result-explorer.js','evidence-results.js','variable-workspace.js','filter-picker.js','schedule.js','queue.js','sector-view.js','workspaces.js','range.js','responsive.js')
STYLE_NAMES=('contributions.css','responsive.css','queue.css','variable-workspace.css','filter-picker.css','workspaces.css','sector-view.css')


def read(name):
    return (BROWSER/name).read_text(encoding='utf-8')


def template():
    return read('template.html').replace('__WORKSPACE_NAV__',read('workspace.html')).replace('__SECTOR_VIEW__',read('sector-view.html'))


def queue_fragment():
    return read('queue.html')


def variable_controls():
    return read('variable-workspace.html').split('<dialog',1)[0]


def variable_fragment():
    return '<dialog'+read('variable-workspace.html').split('<dialog',1)[1]


def styles():
    return '\n'.join(read(name) for name in STYLE_NAMES)


def scripts(screening_data):
    packed=json.dumps(screening_data,separators=(',', ':')).replace('<',chr(92)+'u003c')
    result='<script id="screening-data" type="application/json">'+packed+'</script>'
    for name in SCRIPT_NAMES:
        result+='<script>'+read(name)+'</script>'
    return result


def data_page():
    return read('data.html').replace('__DATA_STYLE__',read('data-panel.css')).replace('__DATA_SCRIPT__',read('data-panel.js'))
