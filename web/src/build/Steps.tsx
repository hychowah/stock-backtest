import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import type { CatalogReply } from "../api/CatalogReply.ts";
import type { Variable } from "../api/Variable.ts";
import {
  addStep,
  commitRanks,
  copySleeve,
  type Draft,
  editStep,
  isRank,
  isTextFilter,
  moveStep,
  removeSleeve,
  removeStep,
  renameSleeve,
  setSource,
  sleeveName,
  sourceOf,
  type Step,
} from "../draft.ts";
import { describeSource, displayName, type Known, sourceGroups, textChoices } from "../sources.ts";
import { Picker } from "./Picker.tsx";
import { changeDraft } from "./state.ts";

const COMPARISONS = [
  [">", "More than (>)"],
  ["<", "Less than (<)"],
  [">=", "At least (≥)"],
  ["<=", "At most (≤)"],
] as const;

type Kind = "filter" | "rank";

/** The Steps section: Add filter and Add rank, the sleeve tabs with Copy,
 *  the name field and Remove, and the active sleeve's steps. A new step
 *  first shows as a "New filter" or "New rank" row that asks for its source;
 *  it joins the draft once a source is chosen. When steps move, each row
 *  slides from its old place to its new one, and the moved row lifts and
 *  settles with a short tint; a new row fades in. A page that asks for
 *  reduced motion gets no animation. */
export function Steps({ draft, sleeve, setSleeve, catalog, library, note }: {
  draft: Draft;
  sleeve: number;
  setSleeve: (sleeve: number) => void;
  catalog: CatalogReply | null;
  library: readonly Variable[] | null;
  /** Why the picker lists no or few sources, while it does. */
  note: string;
}) {
  const [pending, setPending] = useState<Kind | null>(null);
  const list = useRef<HTMLOListElement>(null);
  const slide = useRef<{ before: Map<string, number>; moved: string | null } | null>(null);
  const focus = useRef<string | null>(null);
  const steps = draft.sleeves[sleeve]?.steps ?? [];
  const known: Known = { own: draft.variables, library: library ?? [], catalog };

  // Another sleeve drops the pending row.
  useEffect(() => setPending(null), [sleeve]);

  useLayoutEffect(() => {
    const motion = slide.current;
    slide.current = null;
    if (motion && list.current) animate(list.current, motion.before, motion.moved);
    if (focus.current) document.getElementById(focus.current)?.focus();
    focus.current = null;
  });

  /** Notes where each row is before a change, so the rows can slide. */
  const before = (moved: string | null) => {
    const rows = [...(list.current?.querySelectorAll<HTMLElement>("[data-row]") ?? [])];
    slide.current = { before: new Map(rows.map((row) => [row.dataset.row!, row.getBoundingClientRect().top])), moved };
  };
  const isText = (name: string) => textChoices(name, catalog) !== null;

  const choose = (kind: Kind, name: string) => {
    before(null);
    let id = 0;
    changeDraft((current) => {
      const [next, added] = addStep(current, sleeve, kind, name, isText(name));
      id = added;
      return next;
    });
    setPending(null);
    // The new step's first control: a Rank's order, a Filter's value.
    focus.current = kind === "rank" ? `step-direction-${id}` : `step-value-${id}`;
  };
  const move = (step: Step, offset: -1 | 1) => {
    before(String(step.id));
    const at = steps.indexOf(step) + offset;
    const edge = at === 0 ? "up" : at === steps.length - 1 ? "down" : null;
    const direction = offset < 0 ? "up" : "down";
    focus.current = `step-${edge === direction ? (direction === "up" ? "down" : "up") : direction}-${step.id}`;
    changeDraft((current) => moveStep(current, sleeve, step.id, offset));
  };
  const remove = (step: Step) => {
    before(null);
    const at = steps.indexOf(step);
    const next = steps.filter((other) => other !== step)[Math.min(at, steps.length - 2)];
    focus.current = next ? `step-remove-${next.id}` : "add-filter";
    changeDraft((current) => removeStep(current, sleeve, step.id));
  };
  const open = (kind: Kind) => {
    before(null);
    setPending(kind);
    focus.current = "filter-search-new";
  };

  const total = draft.sleeves.length;
  return (
    <section class="extra-filters" id="strategy-steps-section" aria-labelledby="strategy-steps-title">
      <div class="toolbar">
        <div class="section-heading">
          <h3 id="strategy-steps-title">Steps</h3>
          <p class="hint">Steps run in order. A Filter keeps the stocks that pass. A Rank orders them and keeps its rank range.</p>
        </div>
        <div class="strategy-step-actions">
          <button type="button" id="add-filter" onClick={() => open("filter")}>
            + Add filter
          </button>{" "}
          <button type="button" id="add-rank" onClick={() => open("rank")}>
            + Add rank
          </button>
        </div>
      </div>
      <div class="sleeve-row">
        <div id="sleeve-tabs" role="group" aria-label="Sleeves">
          {draft.sleeves.map((other, i) => (
            <button type="button" key={i} data-sleeve={i} aria-pressed={i === sleeve ? "true" : "false"} onClick={() => setSleeve(i)}>
              {sleeveName(other, i)}
            </button>
          ))}
        </div>
        <button
          type="button"
          id="sleeve-copy"
          onClick={() => {
            changeDraft((current) => copySleeve(current, sleeve));
            setSleeve(total);
          }}
        >
          + Copy this sleeve
        </button>
        <span id="sleeve-edit" hidden={total < 2}>
          <label for="sleeve-name">Sleeve name</label>
          <input
            id="sleeve-name"
            type="text"
            maxlength={256}
            autocomplete="off"
            spellcheck={false}
            value={draft.sleeves[sleeve]?.name ?? ""}
            placeholder={sleeveName({ name: "", steps }, sleeve)}
            onInput={(event) => {
              const name = event.currentTarget.value;
              changeDraft((current) => renameSleeve(current, sleeve, name));
            }}
          />
          <button
            type="button"
            id="sleeve-remove"
            onClick={() => {
              changeDraft((current) => removeSleeve(current, sleeve));
              setSleeve(Math.min(sleeve, total - 2));
              requestAnimationFrame(() => document.querySelector<HTMLElement>('#sleeve-tabs [aria-pressed="true"]')?.focus());
            }}
          >
            Remove sleeve
          </button>
        </span>
      </div>
      <ol id="strategy-steps" aria-label="Strategy steps" ref={list}>
        {steps.map((step, i) => (
          <StepRow
            key={step.id}
            step={step}
            number={i + 1}
            last={i === steps.length - 1}
            known={known}
            groups={sourceGroups(isRank(step) ? "rank" : "filter", catalog, library)}
            note={note}
            onSource={(name) => {
              changeDraft((current) => setSource(current, sleeve, step.id, name, isText(name)));
              focus.current = isRank(step) ? `step-direction-${step.id}` : `step-value-${step.id}`;
            }}
            onEdit={(edit) => changeDraft((current) => editStep(current, sleeve, step.id, edit))}
            onRanks={(key) => changeDraft((current) => commitRanks(current, sleeve, step.id, key))}
            onMove={(offset) => move(step, offset)}
            onRemove={() => remove(step)}
          />
        ))}
        {pending && (
          <li class="condition-row condition-pending" data-row="new">
            <span class="step-name">New {pending}</span>
            <Picker id="new" kind={pending} label="" title={`New ${pending}`} groups={sourceGroups(pending, catalog, library)} note={note} onChoose={(name) => choose(pending, name)} />
            <div class="condition-actions">
              <button
                type="button"
                onClick={() => {
                  setPending(null);
                  focus.current = "add-filter";
                }}
              >
                Cancel
              </button>
            </div>
          </li>
        )}
      </ol>
      <details class="how-it-works">
        <summary>How this works</summary>
        <p class="hint" id="strategy-ranking-help">
          The last Rank sets the final order and ranks; filters after it add no replacements. Each selected stock receives equal weight. Latest mode ranks at the latest cached close. Backtests
          rebalance on the selected fixed or random schedule.
        </p>
        <p class="hint">Auto-run works in Latest stock picks: turn it off to change several settings, then select Screen latest. A dated test runs from Add to queue.</p>
        <p class="hint">
          Sales-based operating yield spread: latest eligible annual sales × the simple average of operating margins from 3 consecutive annual reports ÷ screen-date EV, minus the US 10-year Treasury
          yield. Each annual operating margin is operating income ÷ sales. Use the latest saved Treasury yield on or before the screen date. Enter 5 for a spread of 5 percentage points. Missing
          years, operating inputs or Treasury yields fail this condition.
        </p>
        <p class="hint">
          Three-year metric divides current EV by mean EBITDA from three consecutive annual reports available at the screening date; stocks missing a year are excluded. Yield is EBITDA ÷ EV, the
          reciprocal of the multiple (EV ÷ EBITDA). A higher yield and a lower multiple both mean a cheaper stock.
        </p>
      </details>
    </section>
  );
}

type Edit = Parameters<typeof editStep>[3];

/** One step: its name, source picker, comparison or order, and value or
 *  ranks, then Move up, Move down and Remove. */
function StepRow({ step, number, last, known, groups, note, onSource, onEdit, onRanks, onMove, onRemove }: {
  step: Step;
  number: number;
  last: boolean;
  known: Known;
  groups: ReturnType<typeof sourceGroups>;
  note: string;
  onSource: (name: string) => void;
  onEdit: (edit: Edit) => void;
  onRanks: (key: "from" | "to") => void;
  onMove: (offset: -1 | 1) => void;
  onRemove: () => void;
}) {
  const key = step.id;
  const name = `Step ${number} · ${isRank(step) ? "Rank" : "Filter"}`;
  const source = sourceOf(step);
  let middle;
  let value;
  if (isRank(step)) {
    middle = (
      <select id={`step-direction-${key}`} aria-label={`${name} order`} value={step.order} onChange={(event) => onEdit({ order: event.currentTarget.value as "highest" | "lowest" })}>
        <option value="highest">Highest first</option>
        <option value="lowest">Lowest first</option>
      </select>
    );
    const ranks = (end: "from" | "to", label: string) => (
      <input
        id={`step-rank_${end}-${key}`}
        aria-label={`${name} ${label}`}
        type="number"
        min={1}
        max={5000}
        step={1}
        required
        value={step[end]}
        onInput={(event) => {
          const typed = event.currentTarget.valueAsNumber;
          if (Number.isSafeInteger(typed)) onEdit({ [end]: typed });
        }}
        onChange={() => onRanks(end)}
      />
    );
    value = (
      <span class="condition-value">
        <span class="condition-unit">Ranks</span>
        {ranks("from", "first rank")}
        <span class="condition-unit">to</span>
        {ranks("to", "last rank")}
      </span>
    );
  } else if (isTextFilter(step)) {
    const choices = [...new Set([...(textChoices(source, known.catalog) ?? []), ...(step.value ? [step.value] : [])])];
    middle = (
      <select id={`step-op-${key}`} aria-label={`${name} comparison`} value={step.op} onChange={(event) => onEdit({ op: event.currentTarget.value as "is" | "is not" })}>
        <option value="is">Is</option>
        <option value="is not">Is not</option>
      </select>
    );
    value = (
      <select id={`step-value-${key}`} aria-label={`${name} value`} value={step.value} onChange={(event) => onEdit({ value: event.currentTarget.value })}>
        <option value="">Choose…</option>
        {choices.map((choice) => (
          <option value={choice} key={choice}>
            {choice}
          </option>
        ))}
      </select>
    );
  } else {
    const display = describeSource(source, known)?.display;
    middle = (
      <select id={`step-op-${key}`} aria-label={`${name} comparison`} value={step.op} onChange={(event) => onEdit({ op: event.currentTarget.value as (typeof COMPARISONS)[number][0] })}>
        {COMPARISONS.map(([op, label]) => (
          <option value={op} key={op}>
            {label}
          </option>
        ))}
      </select>
    );
    value = (
      <span class="condition-value">
        <input
          id={`step-value-${key}`}
          aria-label={`${name} value`}
          inputMode="decimal"
          autocomplete="off"
          placeholder="Enter value"
          value={step.value}
          onInput={(event) => onEdit({ value: event.currentTarget.value })}
        />
        {display && display !== "text" && <span class="condition-unit">{displayName(display)}</span>}
      </span>
    );
  }
  // A compact button keeps its full name as its accessible name and tooltip.
  const button = (action: string, label: string, text: string, onClick: () => void, disabled = false) => (
    <button type="button" id={`step-${action}-${key}`} aria-label={`${label} ${name.toLowerCase()}`} title={label} disabled={disabled} onClick={onClick}>
      {text}
    </button>
  );
  return (
    <li class={`condition-row step-${isRank(step) ? "rank" : "filter"}`} data-row={key}>
      <span class="step-name">{name}</span>
      <Picker id={String(key)} kind={isRank(step) ? "rank" : "filter"} label={source} title={name} groups={groups} note={note} onChoose={onSource} />
      {middle}
      {value}
      <div class="condition-actions">
        {button("up", "Move up", "↑", () => onMove(-1), number === 1)}
        {button("down", "Move down", "↓", () => onMove(1), last)}
        {button("remove", "Remove", "✕", onRemove)}
      </div>
    </li>
  );
}

/** Slides each row from where it was (`before`, by row) to where it is. The
 *  moved row lifts, slides and settles with a tint; a chosen source slides
 *  from the New row to its step; a row that was not there fades in. */
function animate(list: HTMLElement, before: Map<string, number>, moved: string | null): void {
  const rows = [...list.querySelectorAll<HTMLElement>("[data-row]")];
  if (!before.size || !rows.length || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  for (const row of rows) {
    const id = row.dataset.row!;
    const start = before.get(id) ?? before.get("new");
    if (start === undefined) {
      row.animate([{ opacity: 0, transform: "translateY(-6px)" }, { opacity: 1, transform: "none" }], { duration: 200, easing: "ease-out" });
      continue;
    }
    const shift = start - row.getBoundingClientRect().top;
    if (id === moved || !before.has(id))
      row.animate(
        [
          { transform: `translateY(${shift}px) scale(1.01)`, boxShadow: "0 0 0 6px #fff,0 14px 30px #102e252e", backgroundColor: "#fff", zIndex: 1, easing: "cubic-bezier(.2,.8,.2,1)" },
          { offset: 0.5, transform: "none", boxShadow: "0 0 0 6px #e3f0e7,0 2px 6px #102e2514", backgroundColor: "#e3f0e7", zIndex: 1 },
          { transform: "none", boxShadow: "0 0 0 6px #e3f0e700,0 0 0 #102e2500", backgroundColor: "#e3f0e700", zIndex: 1 },
        ],
        { duration: 700 },
      );
    else if (Math.abs(shift) >= 1) row.animate([{ transform: `translateY(${shift}px)` }, { transform: "none" }], { duration: 330, easing: "cubic-bezier(.2,.8,.2,1)" });
  }
}
