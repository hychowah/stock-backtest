// Offline checks for this static guide. No browser or packages are required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, 'dist/index.html'), 'utf8');
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(x => x[1]);
assert.equal(new Set(ids).size, ids.length, 'IDs must be unique');
for (const match of html.matchAll(/\bhref="#([^"]+)"/g)) assert(ids.includes(match[1]), `Missing anchor ${match[1]}`);
for (const match of html.matchAll(/\baria-controls="([^"]+)"/g)) assert(ids.includes(match[1]), `Missing controlled panel ${match[1]}`);
assert(!/<(?:link|img|script)\b[^>]*(?:src|href)=["']https?:/i.test(html), 'Guide must work without remote assets');
assert(html.includes('Shared in-memory data remains a prototype.') && html.includes('The requested-pool change is now in the source.'), 'Source and prototype status must be clear');
assert(html.includes('P/B and P/E need more saved financial data.') && html.includes('All conditions must pass before ranking.'), 'Do not imply P/B is implemented');

assert(html.includes('raw/download-coverage.json') && html.includes('/api/data/*') && html.includes('Gaps inside an existing span are not repaired automatically.'), 'Data panel source, coverage and download limits must be clear');

assert(html.includes('content hash') && html.includes('worker completion and database closure') && html.includes('scripts/cache_assets.py'), 'Cache repair evidence and shared ownership must be explained');

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
  if (filter === 'pb') assert(result.includes('not available now') && result.includes('historical book values'));
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
