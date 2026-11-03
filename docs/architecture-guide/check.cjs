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
assert(html.includes('server/app.py') && html.includes('runtime_access.py') && html.includes('--collect-report'), 'Explain native ownership and verified report collection');
assert(html.includes('checks main every two seconds') && html.includes('website-update-stop-') && html.includes('without automatic updates'), 'Explain automatic main updates, owned cleanup and fixed launches');
assert(html.includes('backtest/application/jobs.py') && html.includes('backtest-runs.js') && html.includes('/api/backtest-runs/*') && html.includes('24 hours, up to four recent runs') && html.includes('same browser storage'), 'Explain server-owned runs, reconnection and temporary result limits');
assert(html.includes('CB-13A') && html.includes('Calculations') && html.includes('Callers no longer prehold financial ownership.') && html.includes('Late request bodies cannot begin calculation.'), 'Explain shared application admission and ordinary routing');
assert(html.includes('backtest-queue.sqlite') && html.includes('backtest/application/queue.py') && html.includes('100 records') && html.includes('Held edits stay held') && html.includes('consumer lock'), 'Explain durable queue records, editing and single-consumer recovery');
assert(html.includes('Each saved row has an <strong>All parameters</strong> disclosure.') && html.includes('Retry parameters') && html.includes('Sorting, renaming and refreshing keep the expansion.'), 'Explain saved-row recorded parameters, lazy loading and retry');
assert(html.includes('First saved test') && html.includes('Second saved test') && html.includes('Clear comparison') && html.includes('website/browser/backtest-comparison.js') && html.includes('The main result and strategy form stay unchanged.') && html.includes('Mean trial CAGR is not one portfolio return.'), 'Explain stored comparison controls, independent view, parameter differences and random statistics');
assert(html.includes('Completed — waiting for saved slot') && html.includes('The saved copy commits before duplicate queue result bytes are removed.') && html.includes('The receipt survives saved-record deletion.') && html.includes('including while execution is paused'), 'Explain recoverable queue transfer, capacity, ownership and deletion receipts');
assert(html.includes('The library has 100 slots.') && html.includes('stable UUID database ID') && html.includes('Sort saved backtests') && html.includes('Renaming changes only the name.') && html.includes('lists scroll inside bounded regions'), 'Explain library capacity, identity, rename, performance sort and bounded lists');
assert(html.includes('tools/experiments/bench_baseline.py') && html.includes('CB-01') && html.includes('24 annual trials over 1997–2025') && html.includes('does not measure the browser or an HTTP server'), 'Explain the frozen production baseline and its measurement boundary');
assert(html.includes('backtest/engines/numerical/generation.py') && html.includes('data/numerical/') && html.includes('OS-locked lease') && html.includes('stale prior generation'), 'Explain offline numerical publication, read-only attachment and recovery');
assert(html.includes('Exact worker attachment checked 1 November 2026.') && html.includes('worker_reference()') && html.includes('open_delegated') && html.includes('stable generation gate') && html.includes('CB-19C now supplies parent monitoring'), 'Explain delegated identity, reader pin and remaining worker lifetime responsibility');
assert(html.includes('Recorded trial operation checked 1 November 2026.') && html.includes('backtest/engines/numerical/trial.py') && html.includes('Trial 37 remains trial 37.') && html.includes('not a committed checkpoint') && html.includes('CB-19C supplies process workers'), 'Explain recorded trials, bounded provisional artifacts and remaining pool responsibility');
assert(html.includes('Persistent trial pool checked 1 November 2026.') && html.includes('Declared worker capacity stays fixed') && html.includes('completed-but-unreleased') && html.includes('inherited pipe or process handle') && html.includes('They are not RSS limits.'), 'Explain persistent workers, stable capacity identity, reservation lifetime and actual parent monitoring');
assert(html.includes('tools/experiments/bench_execution.py') && html.includes('tools/experiments/bench_comparison.py') && html.includes('Real benchmark admission stays closed.') && html.includes('These fixture checks give no new speed result.'), 'Distinguish disposable financial execution from real admission and speed qualification');

assert(html.includes('raw/download-coverage.json') && html.includes('/api/data/*') && html.includes('Legacy gaps inside an existing span are not repaired automatically.'), 'Data panel source, coverage and download limits must be clear');

assert(html.includes('Multiple records can have the same fiscal date.') && html.includes('Conflicting values stay unavailable.'), 'Explain duplicate annual response preservation and input ambiguity');

assert(html.includes('content hash') && html.includes('worker completion and database closure') && html.includes('backtest/inputs/cache_assets.py'), 'Cache repair evidence and shared ownership must be explained');

assert(html.includes('up to 32 parallel requests') && html.includes('45 request starts per second') && html.includes('gzip compression') && html.includes('original saved span'), 'Current download policy and cache bounds must be clear');
assert(html.includes('6.56 seconds') && html.includes('policy selected on 22 October') && html.includes('fmp-throughput-2026-10-23.json') && html.includes('not new application tests'), 'Historical benchmark settings and limits must remain explicit');

assert(html.includes('Selectable-engine readiness checked 31 October 2026.') && html.includes('operating_yield_spread_3y') && html.includes('Confirmed child closure precedes every published outcome.') && html.includes('Cross-call compiler and result-memory reuse have ended.'), 'Explain supported experimental scope and operation ownership');
assert(html.includes('Both engines support <code>operating_yield_spread_3y</code>') && html.includes('<code>treasury10</code>') && html.includes('Missing annual inputs or a missing preceding yield omit only this threshold.'), 'Explain source-derived experimental spread and missing inputs');

assert(html.includes('backtest/application/evidence_views.py') && html.includes('backtest/application/result_exports.py') && html.includes('16 displays and 32 active requests') && html.includes('Changing the table page cannot change attribution.') && html.includes('Legacy built-in submissions remain eager. Captured scalar submissions use bounded evidence.'), 'Explain acquired evidence readers, complete attribution, attachments and explicit scalar producers');
assert(html.includes('id="variable-library"') && html.includes('data/variable-library.sqlite') && html.includes('expected entry version') && html.includes('All immutable revisions and its last metadata remain retained.') && html.includes('There is no dynamic latest reference.'), 'Explain durable variable identity, concurrency, deletion retention and exact resolution');
assert(html.includes('aria-label="Atomic variable capture"') && html.includes('require_capture()') && html.includes('one database snapshot') && html.includes('3 MiB of encoded content') && html.includes('removal of the library file'), 'Explain atomic complete detached captures, bounds and deletion independence');

assert(html.includes('backtest/variables/parameters.py') && html.includes('all 52 direct inputs') && html.includes('financial-parameters/1') && html.includes('financial-parameters/2') && html.includes('All catalog /2 execution stays closed') && html.includes('ordinary picker still offer only'), 'Explain semantic recognition, versioned units and the four usable observations');

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
assert(html.includes('backtest/engines/numerical/formula_capabilities.py') && html.includes('Original reference preview') && html.includes('Eager numerical scalar calculation and numerical sample preview are unsupported.') && html.includes('approximately 50 ms parent-wait cadence') && html.includes('One shared engine selector applies to all four scalar modes.') && html.includes('Every scalar result panel shows its recorded producer.') && html.includes('Missing producer evidence stays explicitly unknown.'), 'Explain explicit capability, Original preview, pinned choice and memory-only worker cancellation');
console.log('Guide checks passed: anchors, offline assets, stage/mode controls, 12 setting combinations and print state.');

assert(html.includes('Ordered random coordination checked 1 November 2026.') && html.includes('Full recovery constructs no provider and starts no workers.') && html.includes('Unretained artifacts keep bounded reservations') && html.includes('Completion progress follows a successful save.'), 'Explain recovery before compilation, parent commitment and bounded ordered presentation');

assert(html.includes('Complete period candidates checked 1 November 2026.') && html.includes('the same source-derived arithmetic and financial decision trees') && html.includes('Full recovery builds no provider.') && html.includes('not three permanent production engine choices') && html.includes('backtest/engines/numerical/rust_kernel.rs'), 'Explain the shared compiled candidate boundary, lazy recovery and comparison-only native status');

assert(html.includes('explicitly joins every numerical thread and its thread-local cleanup'), 'Explain complete native thread cleanup before library closure');

assert(html.includes('Scoped comparison history checked 1 November 2026.') && html.includes('51.98 seconds for Rust and 59.52 seconds') && html.includes('startup and completed-build reuse benefit') && html.includes('failed shared statistics publication') && html.includes('tools/experiments/parallel_comparison.py'), 'Keep historical F comparison scope and failed publication explicit');

assert(html.includes('Selected experimental path checked 1 November 2026.') && html.includes('one compiled-Numba complete-book provider') && html.includes('117.432 seconds') && html.includes('123.548 seconds') && html.includes('additional readiness checks outside that clock') && html.includes('not a contiguous balanced sequence'), 'Explain G selection and distinguish measured Candidate and selectable boundaries');

assert(html.includes('256 MiB readiness estimate') && html.includes('first actual worker reaches readiness') && html.includes('Each worker has its own readiness identity and deadline.') && html.includes('Resolved capacity cannot change after checkpoint binding.'), 'Explain measured admission provenance, concurrent startup and fixed recovery identity');

assert(html.includes('Normal startup, status and experimental preparation require no Rust') && html.includes('requests no factor-kernel compilation') && html.includes('Ordinary preparation can reuse'), 'Explain selected dependencies and complete recovery without provider construction');

assert(html.includes('tools/setup_numerical_native.py') && html.includes('outside benchmark tmp paths') && html.includes('durable pointer checks') && html.includes('within that inspection') && html.includes('Payload and required statistics must publish before a result frame.'), 'Explain retained offline native comparison setup and atomic protocol publication');

assert(html.includes('Final-source normal application qualification checked 1 November 2026.') && html.includes('120.686 seconds') && html.includes('51.414 seconds') && html.includes('remaining 21') && html.includes('single qualification observations') && html.includes('Recovery still validates inputs'), 'Explain final normal adapter qualification without equating recovery with instant delivery or a fresh Original comparison');

assert(html.includes('backtest/application/result_access.py') && html.includes('One browser scope') && html.includes('lost response releases the requested reader identity') && html.includes('drains result readers'), 'Explain application result ownership and acquisition/shutdown lifetimes');

assert(html.includes("website/rendering/data.py") && html.includes("website/server/results.py") && html.includes("tools/ops/") && html.includes("tools/experiments/"), "Explain grouped website and operational source owners");

assert(html.includes("backtest/observations.py") && html.includes("legacy top-250 buffer is formed before checking cached prices") && html.includes("Older annual history members do not inherit that age limit.") && html.includes("It calculates no average or formula.") && html.includes("Returned evidence remains readable after closure."), "Explain bounded admitted observations, temporal history, canonical values and detached evidence");
assert(html.includes('Its second slice adds the four-parameter point-in-time provider in source.') && !html.includes('The point-in-time provider is still pending.'), 'Keep provider source status consistent throughout the guide');

assert(html.includes('id="formula-program"') && html.includes('backtest/variables/definitions.py') && html.includes('References name exact content revisions.') && html.includes('A submitted decimal has at most 64 characters.') && html.includes('Phase 7 qualification is authorized.'), 'Explain immutable formula validation, identities, canonical units and fixed limits');

assert(html.includes('backtest/variables/reference.py') && html.includes('aria-label="Reference formula execution"') && html.includes('Even a constant requires admission.') && html.includes('Missing multiplied by zero stays missing.') && html.includes('Freshness is checked after final encoding as well.'), 'Explain admitted reference scalar execution, missing propagation and final freshness');
assert(html.includes('65,536 tasks') && html.includes('8,192 output slots') && html.includes('Retained encoded content uses at most 64 MiB.') && html.includes('These are content bounds, not a measure of process memory.'), 'Explain fixed evaluator count and encoded-content bounds without RSS claims');
assert(!html.includes('Provider-backed scalar evaluation is its next slice.') && !html.includes('The next slice will bind it to the existing provider'), 'Keep evaluator status current throughout the guide');

assert(html.includes('id="scalar-selection"') && html.includes('aria-label="Scalar selection"') && html.includes('backtest/selection.py') && html.includes('backtest/variables/selection.py') && html.includes('No hidden minimum yield applies to custom ranking.') && html.includes('Null candidate ranks come first.'), 'Explain scalar direction, admission and deterministic ties');
assert(html.includes('Exact decimal conversion precedes binary64 comparison.') && html.includes('24 MiB output') && html.includes('96 MiB retained encoded content') && html.includes('Final encoding is followed by a freshness check.'), 'Explain canonical thresholds, bounded detached selection and lifetime checks');

assert(html.includes('Legacy SQL and browser adapters keep stored ranking pairs') && html.includes('Unsupported experimental formula requests fail before readiness or financial execution') && html.includes('Legacy prepared populations do not inherit the callable candidate limit.'), 'Explain explicit legacy adapters, freshness and formula rejection');

assert(!html.includes('The editor and numerical formula execution remain held.') && !html.includes('The Phase 6 editor remains outstanding.') && html.includes('Phase 6 is complete in source after independent audit and private verification.') && html.includes('Qualified numerical variable execution is opt-in.'), 'Keep completed Phase 6 source and opt-in bounded numerical admission current');
assert(html.includes('id="variable-workspace"') && html.includes('id="variable-authoring-map"') && html.includes('id="variable-presentation-map"') && html.includes('backtest/application/variable_authoring.py') && html.includes('website/browser/variable-workspace.js') && html.includes('website/browser/evidence-results.js') && html.includes('website/browser/variable-evidence.js') && html.includes('Shared dependencies do not multiply the request size.'), 'Explain the shared workspace, authoring owners, bounded transport and detached presentation');

assert(html.includes('id="strategy-capture"') && html.includes('backtest/application/strategy_requests.py') && html.includes('192 KiB') && html.includes('256 KiB') && html.includes('There is no hidden minimum-yield condition.') && html.includes('Submission equality includes the complete payload and presentation.') && html.includes('capture_submitted()'), 'Explain captured strategy intent, detached restoration, comparison meanings, application bounds and unsaved capture');

assert(html.includes('id="scalar-execution"') && html.includes('Scalar execution and immutable evidence') && html.includes('16,777,216 planned tasks') && html.includes('zero trials and zero periods') && html.includes('Download complete evidence') && html.includes('backtest/scalar_result_evidence.py'), 'Explain scalar Original execution, independent formats, complete scope/bounds, Latest and detached exports');

assert(!html.includes('Automatic producers remain eager.') && !html.includes('Automatic calculation submission and queue execution remain eager.'), 'Keep legacy and scalar producer descriptions distinct');

assert(html.includes('id="numerical-formulas"') && html.includes('id="numerical-formula-map"') && html.includes('aria-label="Compiled formula evaluation"') && html.includes('backtest/variables/evaluation.py') && html.includes('backtest/engines/numerical/formulas.py') && html.includes('The reference interpreter remains the correctness authority.') && html.includes('Cache bytes and working buffers count within the existing 64 MiB retained allowance.') && html.includes('Separate member steps permit cancellation between annual observations.'), 'Explain shared checked work, independent compiled arithmetic, existing bounds and declared application capability');

assert(html.includes('id="numerical-scalar-execution"') && html.includes('id="numerical-scalar-map"') && html.includes('aria-label="Numerical scalar execution and recovery"') && html.includes('backtest/engines/numerical/scalar.py') && html.includes('Required built-in lanes are declared directly.') && html.includes('A complete checkpoint hit constructs no formula evaluator, book provider or worker.') && html.includes('Trial-qualified scope IDs') && html.includes('Both book and formula kernels warm before the cold worker memory sample.'), 'Explain qualified candidate scalar scopes, complete recovery and existing resource ownership');
assert(html.includes('Admit supported bounded scalar work. Original remains default.') && !html.includes('Keep public numerical scalar admission closed until qualification.'), 'Keep numerical scalar file-map admission current');
