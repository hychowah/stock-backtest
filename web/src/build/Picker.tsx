import { useLayoutEffect, useRef, useState } from "preact/hooks";
import { type Choice, type Group, matches } from "../sources.ts";

type Open = { typed: boolean; query: string; active: number };

/** The searchable source list of one step row: a combobox whose list opens on
 *  focus. Typing keeps the choices whose label or detail holds every typed
 *  word, and the first of them becomes active, so Enter takes the best match.
 *  ArrowDown and ArrowUp move through the choices, wrapping; Enter takes the
 *  active one; Escape closes the list and shows the step's source again, as
 *  does leaving the field. A press inside the list keeps the field focused.
 *  `id` makes the ids filter-search-ID and filter-options-ID. With
 *  `onCreate`, the list ends with "Create a new variable…", which the
 *  keyboard reaches but typing never makes active. */
export function Picker({ id, kind, label, title, groups, note, onChoose, onCreate }: {
  id: string;
  kind: "filter" | "rank";
  /** The step's source; "" for a new step. */
  label: string;
  /** The step's name, which names the list: Step 2 · Filter. */
  title: string;
  groups: Group[];
  /** A line under the choices, such as why some are missing. */
  note: string;
  onChoose: (name: string) => void;
  /** Opens the formula editor for this step. */
  onCreate?: () => void;
}) {
  const [open, setOpen] = useState<Open | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);

  const shownOf = (state: Open) =>
    groups.map((group) => ({ label: group.label, choices: group.choices.filter((choice) => !state.typed || matches(choice, state.query)) })).filter((group) => group.choices.length);
  const shown = open ? shownOf(open) : [];
  const create: Choice | null = onCreate ? { name: "", label: "＋ Create a new variable…", detail: "Type a formula, then use it in this step." } : null;
  const matched = shown.reduce((sum, group) => sum + group.choices.length, 0);
  const items: Choice[] = [...shown.flatMap((group) => group.choices), ...(create ? [create] : [])];
  // After typing, the first match is active until the keyboard moves.
  const active = open ? (open.active < 0 && open.typed && matched ? 0 : Math.min(open.active, items.length - 1)) : -1;
  const optionId = (i: number) => `filter-option-${id}-${i}`;

  useLayoutEffect(() => {
    if (active >= 0) list.current?.querySelector(`#${CSS.escape(optionId(active))}`)?.scrollIntoView({ block: "nearest" });
  }, [active, open !== null]);

  const choose = (index: number) => {
    const choice = items[index];
    if (!choice) return;
    setOpen(null);
    if (choice === create) onCreate?.();
    else onChoose(choice.name);
  };
  /** Moves the active choice; a closed list opens first. */
  const move = (step: 1 | -1) => {
    const state = open ?? { typed: false, query: "", active: -1 };
    const count = shownOf(state).reduce((sum, group) => sum + group.choices.length, 0) + (create ? 1 : 0);
    if (!count) return setOpen(state);
    const from = open && active >= 0 ? active : step > 0 ? -1 : count;
    setOpen({ ...state, active: (from + step + count) % count });
  };

  let index = 0;
  const option = (choice: Choice) => {
    const i = index++;
    return (
      <div role="option" id={optionId(i)} key={choice.name} data-option={i} aria-selected={i === active ? "true" : "false"}>
        <span>{choice.label}</span>
        {choice.detail && <small>{choice.detail}</small>}
      </div>
    );
  };

  return (
    <div class="filter-source">
      <label for={`filter-search-${id}`}>{kind === "rank" ? "Rank by" : "Filter on"}</label>
      <div class="filter-combo">
        <input
          ref={input}
          id={`filter-search-${id}`}
          type="text"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open ? "true" : "false"}
          aria-controls={`filter-options-${id}`}
          aria-activedescendant={active >= 0 ? optionId(active) : ""}
          autocomplete="off"
          spellcheck={false}
          placeholder="Type to search: P/E, revenue, margin…"
          value={open?.typed ? open.query : label}
          onFocus={(event) => {
            if (!open) setOpen({ typed: false, query: "", active: -1 });
            event.currentTarget.select();
          }}
          onInput={(event) => setOpen({ typed: true, query: event.currentTarget.value, active: -1 })}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              move(event.key === "ArrowDown" ? 1 : -1);
            } else if (event.key === "Enter") {
              event.preventDefault();
              if (open && active >= 0) choose(active);
            } else if (event.key === "Escape" && open) {
              event.preventDefault();
              event.stopPropagation();
              setOpen(null);
            }
          }}
          onBlur={() => setTimeout(() => document.activeElement !== input.current && setOpen(null))}
        />
        <span class="filter-combo-arrow" aria-hidden="true">
          ▾
        </span>
        <div
          ref={list}
          id={`filter-options-${id}`}
          class="filter-options"
          role="listbox"
          aria-label={`${title} choices`}
          hidden={!open}
          onMouseDown={(event) => {
            // A press in the list, its scroll bar included, keeps the field focused.
            event.preventDefault();
            const target = (event.target as Element).closest("[data-option]");
            if (target) choose(Number((target as HTMLElement).dataset.option));
          }}
        >
          {open && (
            <>
              {shown.map((group) => (
                <div role="group" aria-label={group.label} key={group.label}>
                  <div class="filter-options-heading" aria-hidden="true">
                    {group.label}
                  </div>
                  {group.choices.map(option)}
                </div>
              ))}
              {open.typed && !shown.length && (
                <p class="filter-options-empty">
                  Nothing matches “{open.query}”. Try another word{create ? ", or create a variable" : ""}.
                </p>
              )}
              {note && <p class="filter-options-note">{note}</p>}
              {create && <div class="filter-options-actions">{option(create)}</div>}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
