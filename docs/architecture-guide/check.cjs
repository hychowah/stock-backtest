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
assert(html.includes('Shared in-memory data was only a benchmark prototype. That prototype was later removed.') && html.includes('The requested-pool change is now in the source.'), 'Source and removed-prototype status must be clear');
assert(html.includes('Financial ratios use annual statement inputs.') && html.includes('All conditions must pass before ranking.'), 'Explain annual ratio inputs');
assert(html.includes('WSL source') && html.includes('Windows runtime') && html.includes('tools/deploy.py') && html.includes('deployment.pending.json'), 'Explain source deployment and interrupted publication');
assert(html.includes('server/app.py') && html.includes('runtime_access.py') && html.includes('The tracked report is a frozen record.'), 'Explain native ownership and the frozen report');
assert(html.includes('scripts/check.py') && html.includes('Every preparation is a full build.') && html.includes('Nothing regenerates or changes it.'), 'Explain the development check, full research builds and the frozen January record');
assert(html.includes('there is no January mode') && html.includes('A saved January result opens in the dated view.') && html.includes('at <code>/mode</code>'), 'Explain the removed January mode, saved January results and the refusal');
assert(html.includes('checks main once a day at 01:00') && html.includes('website-update-stop-') && html.includes('without automatic updates'), 'Explain automatic main updates, owned cleanup and fixed launches');
assert(html.includes('backtest/application/jobs.py') && html.includes('backtest-runs.js') && html.includes('/api/backtest-runs/*') && html.includes('24 hours, up to four recent runs') && html.includes('same browser storage'), 'Explain server-owned runs, reconnection and temporary result limits');
assert(html.includes('CB-13A') && html.includes('Callers no longer prehold financial ownership.') && html.includes('Late request bodies cannot begin calculation.'), 'Explain shared application admission and ordinary routing');
assert(html.includes('backtest-queue.sqlite') && html.includes('backtest/application/queue.py') && html.includes('100 records') && html.includes('Held edits stay held') && html.includes('consumer lock'), 'Explain durable queue records, editing and single-consumer recovery');
assert(html.includes('Each saved row has an <strong>All parameters</strong> disclosure.') && html.includes('Retry parameters') && html.includes('Sorting, renaming and refreshing keep the expansion.'), 'Explain saved-row recorded parameters, lazy loading and retry');
assert(html.includes('First saved test') && html.includes('Second saved test') && html.includes('Clear comparison') && html.includes('website/browser/backtest-comparison.js') && html.includes('The main result and strategy form stay unchanged.') && html.includes('Mean trial CAGR is not one portfolio return.'), 'Explain stored comparison controls, independent view, parameter differences and random statistics');
assert(html.includes('Completed — waiting for saved slot') && html.includes('The saved copy commits before duplicate queue result bytes are removed.') && html.includes('The receipt survives saved-record deletion.') && html.includes('including while execution is paused'), 'Explain recoverable queue transfer, capacity, ownership and deletion receipts');
assert(html.includes('The library has 100 slots.') && html.includes('stable UUID database ID') && html.includes('Sort saved backtests') && html.includes('Renaming changes only the name.') && html.includes('lists scroll inside bounded regions'), 'Explain library capacity, identity, rename, performance sort and bounded lists');

assert(html.includes('raw/download-coverage.json') && html.includes('/api/data/*') && html.includes('Legacy gaps inside an existing span are not repaired automatically.'), 'Data panel source, coverage and download limits must be clear');

assert(html.includes('Multiple records can have the same fiscal date.') && html.includes('Conflicting values stay unavailable.'), 'Explain duplicate annual response preservation and input ambiguity');

assert(html.includes('content hash') && html.includes('worker completion and database closure') && html.includes('backtest/inputs/cache_assets.py'), 'Cache repair evidence and shared ownership must be explained');

assert(html.includes('up to 32 parallel requests') && html.includes('45 request starts per second') && html.includes('gzip compression') && html.includes('original saved span'), 'Current download policy and cache bounds must be clear');
assert(html.includes('6.56 seconds') && html.includes('policy selected on 22 October') && html.includes('fmp-throughput-2026-10-23.json') && html.includes('not new application tests'), 'Historical benchmark settings and limits must remain explicit');

assert(html.includes('The source has no experimental (Numba) engine. The website runs only Original.') && html.includes('Edit it to choose Original, or delete it.') && html.includes('Application calculation owner'), 'Explain the absent experimental engine, the waiting queue rule and the single live calculation owner');

assert(html.includes('backtest/application/evidence_views.py') && html.includes('backtest/application/result_exports.py') && html.includes('16 displays and 32 active requests') && html.includes('Changing the table page cannot change attribution.') && html.includes('Legacy built-in submissions remain eager. Captured scalar submissions use bounded evidence.'), 'Explain acquired evidence readers, complete attribution, attachments and explicit scalar producers');
assert(html.includes('id="variable-library"') && html.includes('data/variable-library.sqlite') && html.includes('expected entry version') && html.includes('All immutable revisions and its last metadata remain retained.') && html.includes('There is no dynamic latest reference.'), 'Explain durable variable identity, concurrency, deletion retention and exact resolution');
assert(html.includes('aria-label="Atomic variable capture"') && html.includes('require_capture()') && html.includes('one database snapshot') && html.includes('3 MiB of encoded content') && html.includes('removal of the library file'), 'Explain atomic complete detached captures, bounds and deletion independence');

assert(html.includes('backtest/variables/parameters.py') && html.includes('all 57 direct inputs') && html.includes('financial-parameters/1') && html.includes('financial-parameters/2') && html.includes('77 parameter IDs') && html.includes('33 named measures') && html.includes('The shared editor offers all 57 direct inputs') && html.includes('The language check, <code>definitions.require_program</code>, is the one formula gate.') && html.includes('The one evaluator implements the whole language') && html.includes('It does not establish installed readiness or coverage'), 'Explain the captured vocabulary, the one formula gate, ordinary picker and coverage limits');

assert(html.includes('Inspect recorded coverage') && html.includes('every snapshot row before formula availability') && html.includes('Results are never truncated.') && html.includes('without importing it into My variables') && html.includes('Use expanded inputs') && html.includes('backtest/application/variable_coverage.py'), 'Explain exact measure authoring, explicit namespace upgrades and bounded complete coverage');

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
const modes = ['latest', 'custom', 'random'].map(mode => new Element({mode}));
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
assert(html.includes('Original sample preview') && html.includes('Variable strategies run with Original in all three scalar modes.') && html.includes('Every scalar result panel shows its recorded producer.') && html.includes('Missing producer evidence stays explicitly unknown.'), 'Explain Original preview, pinned choice and recorded producers');
console.log('Guide checks passed: anchors, offline assets, stage/mode controls, 12 setting combinations and print state.');











assert(html.includes('backtest/application/result_access.py') && html.includes('One browser scope') && html.includes('lost response releases the requested reader identity') && html.includes('drains result readers'), 'Explain application result ownership and acquisition/shutdown lifetimes');

assert(html.includes("website/rendering/data.py") && html.includes("website/server/results.py") && html.includes("tools/ops/") && html.includes("tools/experiments/"), "Explain grouped website and operational source owners");

assert(html.includes("backtest/variables/columns.py") && html.includes("legacy top-250 buffer is formed before checking cached prices") && html.includes("Older annual history members do not inherit that age limit.") && html.includes("It calculates no average or formula.") && html.includes("Returned evidence remains readable after closure."), "Explain bounded admitted observations, temporal history, canonical values and detached evidence");
assert(html.includes('point-in-time formula evaluation.'), 'Keep provider source status consistent throughout the guide');

assert(html.includes('id="formula-program"') && html.includes('backtest/variables/definitions.py') && html.includes('References name exact content revisions.') && html.includes('A submitted decimal has at most 64 characters.') && html.includes('These capabilities are integrated into main.'), 'Explain immutable formula validation, identities, canonical units and fixed limits');

assert(html.includes('backtest/variables/columns.py') && html.includes('aria-label="Formula execution"') && html.includes('Even a constant requires admission.') && html.includes('Missing multiplied by zero stays missing.') && html.includes('Freshness is checked at each operation boundary.'), 'Explain admitted reference scalar execution, missing propagation and final freshness');
assert(html.includes('Contexts nest at most 32 deep.') && html.includes('One explanation block fits one 8 MiB evidence record or is split in half') && html.includes('These are content bounds, not a measure of process memory.'), 'Explain the evaluator bounds as encoded-content bounds without RSS claims');

assert(html.includes('id="scalar-selection"') && html.includes('aria-label="Scalar selection"') && html.includes('backtest/selection.py') && html.includes('No hidden minimum yield applies to custom ranking.') && html.includes('Null candidate ranks come first.'), 'Explain scalar direction, admission and deterministic ties');
assert(html.includes('Exact decimal conversion precedes binary64 comparison.') && html.includes('at most 50 conditions and 8,192 candidates in a scope') && html.includes('The view checks freshness after each scope.'), 'Explain canonical thresholds, bounded detached selection and lifetime checks');

assert(html.includes('Legacy SQL and browser adapters keep stored ranking pairs') && html.includes('Unsupported experimental formula requests fail before readiness or financial execution') && html.includes('Legacy prepared populations do not inherit the callable candidate limit.'), 'Explain explicit legacy adapters, freshness and formula rejection');

assert(html.includes('id="variable-workspace"') && html.includes('id="variable-authoring-map"') && html.includes('id="variable-presentation-map"') && html.includes('backtest/application/variable_authoring.py') && html.includes('website/browser/variable-workspace.js') && html.includes('website/browser/filter-picker.js') && html.includes('website/browser/evidence-results.js') && html.includes('website/browser/variable-evidence.js') && html.includes('Shared dependencies do not multiply the request size.'), 'Explain the shared workspace, authoring owners, bounded transport and detached presentation');

assert(html.includes('id="strategy-capture"') && html.includes('backtest/application/strategy_requests.py') && html.includes('192 KiB') && html.includes('256 KiB') && html.includes('There is no hidden minimum-yield condition.') && html.includes('Submission equality includes the complete payload and presentation.') && html.includes('capture_submitted()'), 'Explain captured strategy intent, detached restoration, comparison meanings, application bounds and unsaved capture');

assert(html.includes('id="scalar-execution"') && html.includes('Scalar execution and immutable evidence') && html.includes('no task, inspected-row or scope ceiling') && html.includes('zero trials and zero periods') && html.includes('Download complete evidence') && html.includes('backtest/scalar_result_evidence.py'), 'Explain scalar Original execution, independent formats, complete scope/bounds, Latest and detached exports');



