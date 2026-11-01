// Offline checks for this static guide. No browser or packages are required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, 'dist/index.html'), 'utf8');
const checkedDates = [...html.matchAll(/Checked(?: against the project on)? (\d{1,2} [A-Z][a-z]+ \d{4})/g)].map(x => x[1]);
assert.equal(checkedDates.length, 2, 'Both checked dates must be present');
assert.equal(new Set(checkedDates).size, 1, 'Guide sidebar and footer checked dates must agree');
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(x => x[1]);
assert.equal(new Set(ids).size, ids.length, 'IDs must be unique');
for (const match of html.matchAll(/\bhref="#([^"]+)"/g)) assert(ids.includes(match[1]), `Missing anchor ${match[1]}`);
for (const match of html.matchAll(/\baria-controls="([^"]+)"/g)) assert(ids.includes(match[1]), `Missing controlled panel ${match[1]}`);
assert(!/<(?:link|img|script)\b[^>]*(?:src|href)=["']https?:/i.test(html), 'Guide must work without remote assets');
assert(html.includes('Shared in-memory data remains a prototype.') && html.includes('The requested-pool change is now in the source.'), 'Source and prototype status must be clear');
assert(html.includes('Financial ratios use annual statement inputs.') && html.includes('All conditions must pass before ranking.'), 'Explain annual ratio inputs');
assert(html.includes('WSL source') && html.includes('Windows runtime') && html.includes('tools/deploy.py') && html.includes('deployment.pending.json'), 'Explain source deployment and interrupted publication');
assert(html.includes('serve_app.py') && html.includes('runtime_access.py') && html.includes('--collect-report'), 'Explain native ownership and verified report collection');
assert(html.includes('checks main every two seconds') && html.includes('website-update-stop-') && html.includes('without automatic updates'), 'Explain automatic main updates, owned cleanup and fixed launches');
assert(html.includes('backtest_jobs.py') && html.includes('backtest-runs.js') && html.includes('/api/backtest-runs/*') && html.includes('24 hours, up to four recent runs') && html.includes('same browser storage'), 'Explain server-owned runs, reconnection and temporary result limits');
assert(html.includes('CB-13A') && html.includes('Calculations') && html.includes('Callers no longer prehold financial ownership.') && html.includes('Late request bodies cannot begin calculation.'), 'Explain shared application admission and ordinary routing');
assert(html.includes('backtest-queue.sqlite') && html.includes('backtest_queue.py') && html.includes('100 records') && html.includes('Held edits stay held') && html.includes('consumer lock'), 'Explain durable queue records, editing and single-consumer recovery');
assert(html.includes('tools/bench_baseline.py') && html.includes('CB-01') && html.includes('24 annual trials over 1997–2025') && html.includes('does not measure the browser or an HTTP server'), 'Explain the frozen production baseline and its measurement boundary');
assert(html.includes('scripts/numerical_generation.py') && html.includes('data/numerical/') && html.includes('OS-locked lease') && html.includes('stale prior generation'), 'Explain offline numerical publication, read-only attachment and recovery');
assert(html.includes('Exact worker attachment checked 1 November 2026.') && html.includes('worker_reference()') && html.includes('open_delegated') && html.includes('stable generation gate') && html.includes('CB-19C must supply parent monitoring'), 'Explain delegated identity, reader pin and remaining worker lifetime responsibility');
assert(html.includes('tools/bench_execution.py') && html.includes('tools/bench_comparison.py') && html.includes('Real benchmark admission stays closed.') && html.includes('These fixture checks give no new speed result.'), 'Distinguish disposable financial execution from real admission and speed qualification');

assert(html.includes('raw/download-coverage.json') && html.includes('/api/data/*') && html.includes('Legacy gaps inside an existing span are not repaired automatically.'), 'Data panel source, coverage and download limits must be clear');

assert(html.includes('Multiple records can have the same fiscal date.') && html.includes('Conflicting values stay unavailable.'), 'Explain duplicate annual response preservation and input ambiguity');

assert(html.includes('content hash') && html.includes('worker completion and database closure') && html.includes('scripts/cache_assets.py'), 'Cache repair evidence and shared ownership must be explained');

assert(html.includes('up to 32 parallel requests') && html.includes('45 request starts per second') && html.includes('gzip compression') && html.includes('original saved span'), 'Current download policy and cache bounds must be clear');
assert(html.includes('6.56 seconds') && html.includes('policy selected on 22 October') && html.includes('fmp-throughput-2026-10-23.json') && html.includes('not new application tests'), 'Historical benchmark settings and limits must remain explicit');

assert(html.includes('Selectable-engine readiness checked 31 October 2026.') && html.includes('operating_yield_spread_3y') && html.includes('Confirmed child closure precedes every published outcome.') && html.includes('Cross-call compiler and result-memory reuse have ended.'), 'Explain supported experimental scope and operation ownership');
assert(html.includes('Both engines support <code>operating_yield_spread_3y</code>') && html.includes('<code>treasury10</code>') && html.includes('Missing annual inputs or a missing preceding yield omit only this threshold.'), 'Explain source-derived experimental spread and missing inputs');

assert(html.includes('website/evidence_views.py') && html.includes('website/result_exports.py') && html.includes('16 displays and 32 active requests') && html.includes('Changing the table page cannot change attribution.') && html.includes('Automatic calculation submission and queue execution remain eager.'), 'Explain acquired evidence readers, complete attribution, attachments and unchanged producers');

class Element {
  constructor(dataset = {}) { this.dataset = dataset; this.attributes = {}; this.events = {}; this.textContent = ''; this.children = []; this.hidden = false; this.open = false; }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  getAttribute(key) { return this.attributes[key]; }
  addEventListener(event, handler) { this.events[event] = handler; }
  click() { this.events.click(); }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children = []; this.textContent = ''; }
}
const stages = Array.from({length: 4}, (_, i) => new Element({stage: String(i)}));
const modes = ['january', 'latest', 'custom', 'random'].map(mode => new Element({mode}));
const panels = modes.map(button => Object.assign(new Element(), {id: 'mode-' + button.dataset.mode}));
const detail = new Element();
const title = new Element();
const paragraph = new Element();
detail.querySelector = name => name === 'h3' ? title : paragraph;
const elements = {
  'flow-detail': detail,
  'example-pool': Object.assign(new Element(), {value: 'legacy'}),
  'example-count': Object.assign(new Element(), {value: '50'}),
  'example-filter': Object.assign(new Element(), {value: 'none'}),
  'settings-explanation': new Element(),
  'print-guide': new Element()
};
const selects = ['example-pool', 'example-count', 'example-filter'].map(id => elements[id]);
const closed = [new Element(), new Element()];
let printed = false;
const windowEvents = {};
const window = {print() { printed = true; }, addEventListener(name, handler) { windowEvents[name] = handler; }};
const document = {
  getElementById(id) { assert(elements[id], `Unknown element ${id}`); return elements[id]; },
  createElement() { return new Element(); },
  querySelectorAll(selector) {
    const result = {'[data-stage]': stages, '[data-mode]': modes, '.mode-content': panels, '.settings select': selects, 'details:not([open])': closed}[selector];
    assert(result, `Unexpected selector ${selector}`); return result;
  }
};
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(x => x[1]);
assert.equal(scripts.length, 1);
vm.runInNewContext(scripts[0], {document, window});
for (const stage of stages) {
  stage.click();
  assert.equal(stage.attributes['aria-pressed'], 'true');
  assert.equal(stages.filter(x => x.attributes['aria-pressed'] === 'true').length, 1);
  assert(title.textContent && paragraph.textContent);
}
for (const mode of modes) {
  mode.click();
  assert.equal(panels.filter(x => !x.hidden).length, 1);
  assert.equal(panels.find(x => !x.hidden).id, 'mode-' + mode.dataset.mode);
}
const text = element => element.textContent + element.children.map(x => typeof x === 'string' ? x : text(x)).join('');
for (const pool of ['legacy', 'cached']) for (const count of ['50', '100']) for (const filter of ['none', 'cap', 'pb']) {
  elements['example-pool'].value = pool;
  elements['example-count'].value = count;
  elements['example-filter'].value = filter;
  selects[0].events.change();
  const result = text(elements['settings-explanation']);
  if (filter === 'pb') assert(result.includes('saved annual equity') && result.includes('Full annual financial data'));
  else assert(result.includes(count) && result.includes('Saved books'));
  if (pool === 'legacy' && count === '100' && filter !== 'pb') assert(result.includes('does not expand'));
}
elements['print-guide'].click();
assert(printed);
windowEvents.beforeprint();
assert(closed.every(x => x.open));
windowEvents.afterprint();
assert(closed.every(x => !x.open));
console.log('Guide checks passed: anchors, offline assets, stage/mode controls, 12 setting combinations and print state.');
