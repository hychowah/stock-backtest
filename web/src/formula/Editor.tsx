import { Fragment } from "preact";
import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import type { CatalogReply } from "../api/CatalogReply.ts";
import type { CheckedFormula } from "../api/CheckedFormula.ts";
import type { Fault } from "../api/Fault.ts";
import type { FileVariable } from "../api/FileVariable.ts";
import type { FormulaReply } from "../api/FormulaReply.ts";
import type { Variable } from "../api/Variable.ts";
import { client } from "../client.ts";
import { type Edited, faultLine, faultRange, formulaWords, readyLine, shownDisplay, spelling, typingMatches, useSource, type Word } from "../formula.ts";
import { changeLibrary, useLibrary } from "../live.ts";
import { asFailure } from "../read.ts";
import { displayName } from "../sources.ts";
import { checkVariables, ownCheckVariables } from "../variables.ts";
import { Picture } from "./Picture.tsx";

/** Edits after which a formula is checked, in ms. */
const CHECK_DELAY = 400;

/** What opens the editor: its title and Use label, the market's catalog
 *  (null while it loads), whose names the typing list and "All inputs"
 *  offer, the draft's own variables, what the step reads now (null for a new
 *  formula), and what Use, a rename and a delete do to the drafts. */
type EditorRequest = {
  /** "New filter", or the step's name: "Step 2 · Rank". */
  title: string;
  /** "Add as filter", or "Update step 2". */
  use: string;
  catalog: CatalogReply | null;
  own: Readonly<Record<string, FileVariable>>;
  edited: Edited | null;
  /** Makes the step read `source`, a variable's name or formula text; with
   *  `own`, the draft's own variable `source` becomes `own`. */
  onUse: (source: string, own?: FileVariable) => void;
  /** Library entry `from` was saved as `to`. */
  onRenamed: (from: string, to: string) => void;
  /** Library entry `gone` was deleted from `library`. */
  onDeleted: (gone: Variable, library: readonly Variable[]) => void;
};

let request: EditorRequest | null = null;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((listener) => listener());

/** Opens the editor. It is modal, so it is never opened twice at once. */
export function openEditor(next: EditorRequest): void {
  request = next;
  notify();
}

/** The formula editor's window, drawn while it is open. The shell draws it
 *  at the end of `main`, outside every form, so that Enter in its fields
 *  submits nothing. */
export function FormulaEditor() {
  const [, setTick] = useState(0);
  useEffect(() => {
    const listener = () => setTick((tick) => tick + 1);
    listeners.add(listener);
    return () => void listeners.delete(listener);
  }, []);
  if (!request) return null;
  return (
    <Editor
      request={request}
      onEnd={() => {
        request = null;
        notify();
      }}
    />
  );
}

/** A check of the text with the variables of `key`: the server's reply, or
 *  why the request failed. */
type Check = { text: string; key: string } & ({ reply: FormulaReply } | { failure: string });

/** The window: a name, a formula checked by the server 400 ms after each
 *  edit (a later edit drops the reply to an earlier one), the check line
 *  with the display choice and the fault's suggestions, the picture of the
 *  formula, Save to My variables (Save changes and Save as new for a saved
 *  entry), Favourite, Delete, Use, and "All inputs" to insert a name at the
 *  caret. While typing, a list offers the names that the word at the caret
 *  begins. Close and Escape discard unsaved edits. While a library entry is
 *  edited, the check carries only the entries that do not use it; while a
 *  variable of the draft is edited, the check carries only the draft's
 *  variables before it, the lists offer no library entry, and Use changes it
 *  in the draft. */
function Editor({ request, onEnd }: { request: EditorRequest; onEnd: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const alive = useRef(true);
  const sequence = useRef(0);
  const started = request.edited;
  const [entry, setEntry] = useState(started?.entry ?? null);
  const [opened, setOpened] = useState(started?.opened ?? null);
  // Formula text has no name, and a name that only repeats the formula was
  // given on save: then the field stays empty.
  const [name, setName] = useState(started && started.opened.source !== started.opened.text ? started.opened.source : "");
  const [text, setText] = useState(started?.opened.text ?? "");
  const [chosen, setChosen] = useState(started?.opened.display ?? null);
  const [check, setCheck] = useState<Check | null>(null);
  const [message, setMessage] = useState<{ text: string; failed: boolean } | null>(null);
  /** While Use or a Save checks and sends, the three buttons wait. */
  const [busy, setBusy] = useState(false);
  /** The typing list: where its fragment starts, its words and the active one. */
  const [typing, setTyping] = useState<{ start: number; words: Word[]; active: number } | null>(null);

  const ownName = started?.own ? started.opened.source : null;
  const library = useLibrary().value ?? [];
  // While a variable of the draft is edited, the library is out of its reach.
  const offered = ownName === null ? library : [];
  const variables = ownName === null ? checkVariables(request.own, library, entry) : ownCheckVariables(request.own, ownName);
  const key = JSON.stringify(variables);
  const catalog = request.catalog;

  useLayoutEffect(() => {
    dialog.current?.showModal();
    field.current?.focus();
    return () => {
      alive.current = false;
    };
  }, []);

  const say = (text: string, failed = false) => alive.current && setMessage({ text, failed });

  /** Checks `text`; the reply is shown when no later check started. */
  const run = (text: string): Promise<Check | null> => {
    clearTimeout(timer.current);
    const number = ++sequence.current;
    const done = (result: Check) => {
      if (!alive.current || number !== sequence.current) return null;
      setCheck(result);
      return result;
    };
    return client.formula({ formula: text, variables }).then(
      (reply) => done({ text, key, reply }),
      (thrown: unknown) => done({ text, key, failure: asFailure(thrown).message }),
    );
  };

  const current = check !== null && check.text === text && check.key === key ? check : null;
  const blank = !text.trim();
  useEffect(() => {
    if (blank || current) return;
    // The text the window opened with is checked at once.
    timer.current = setTimeout(() => void run(text), check === null && text === started?.opened.text ? 0 : CHECK_DELAY);
    return () => clearTimeout(timer.current);
  }, [text, key]);

  /** The checked formula of the current text, checking it now when its
   *  check still waits or failed; null when it does not read. */
  const checked = async (): Promise<CheckedFormula | null> => {
    if (blank) return null;
    const result = current && "reply" in current ? current : await run(text);
    return result && "reply" in result && "checked" in result.reply ? result.reply.checked : null;
  };

  // The dialog's own close gives the focus back to what opened it.
  const close = () => dialog.current?.close();

  /** Puts `value` in place of the characters `[start, end)` of the formula
   *  through the browser's own editing, so that undo takes it back. */
  const insert = (value: string, start: number, end: number) => {
    const area = field.current;
    if (!area) return;
    area.focus();
    area.setSelectionRange(start, end);
    document.execCommand("insertText", false, value);
  };

  /** Runs Use or a Save with the three buttons waiting. */
  const waiting = async (work: () => Promise<void>) => {
    setBusy(true);
    try {
      await work();
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  const use = async () => {
    const formula = await checked();
    if (!formula || !alive.current) return;
    const display = shownDisplay(chosen, formula);
    if (ownName !== null) {
      close();
      return request.onUse(ownName, { formula: formula.canonical, display });
    }
    const source = useSource(opened, text, display, formula);
    if (source === null)
      return void say(`A formula in a step shows as ${displayName(formula.display)}. Save it to My variables to show it as ${displayName(display)}.`, true);
    close();
    request.onUse(source);
  };

  const save = async (asNew: boolean) => {
    const formula = await checked();
    if (!formula || !alive.current) return;
    const display = shownDisplay(chosen, formula);
    const replaced = asNew ? null : entry;
    const body = { name: name.trim() || formula.canonical, formula: text, display, favourite: replaced?.favourite ?? false };
    try {
      const saved = await changeLibrary(() => (replaced ? client.editVariable(replaced.id, body) : client.addVariable(body)));
      if (replaced && replaced.name !== saved.name) request.onRenamed(replaced.name, saved.name);
      if (!alive.current) return;
      setEntry(saved);
      setOpened({ source: saved.name, text, display: saved.display });
      say(`Saved “${saved.name}” to My variables.`);
    } catch (thrown) {
      say(asFailure(thrown).message, true);
    }
  };

  /** Shows the typing list for the text before the caret, while nothing is
   *  selected. */
  const suggest = (area: HTMLTextAreaElement) => {
    const found = area.selectionStart === area.selectionEnd ? typingMatches(area.value.slice(0, area.selectionStart), formulaWords(offered, catalog)) : null;
    setTyping(found && { ...found, active: 0 });
  };
  /** Puts word `index` of the typing list in place of its fragment. */
  const take = (index: number) => {
    const area = field.current;
    const word = typing?.words[index];
    if (!area || !typing || !word) return;
    setTyping(null);
    insert(word.text, typing.start, area.selectionStart);
  };

  const favourite = async () => {
    if (!entry) return;
    const { id, name, formula, display } = entry;
    try {
      const saved = await changeLibrary(() => client.editVariable(id, { name, formula, display, favourite: !entry.favourite }));
      if (!alive.current) return;
      setEntry(saved);
      say(saved.favourite ? "Added to favourites." : "Removed from favourites.");
    } catch (thrown) {
      say(asFailure(thrown).message, true);
    }
  };

  const remove = async () => {
    if (!entry) return;
    try {
      await changeLibrary(() => client.deleteVariable(entry.id));
      request.onDeleted(entry, library);
      if (!alive.current) return;
      setEntry(null);
      if (opened?.source === entry.name) setOpened(null);
      say("Deleted from My variables. Tests already added keep their own copy.");
    } catch (thrown) {
      say(asFailure(thrown).message, true);
    }
  };

  // The check line: empty, waiting, ready or at fault. While a check waits,
  // the last picture stays.
  let state: "empty" | "pending" | "ready" | "error" = "pending";
  let line = "Checking…";
  let ready: CheckedFormula | null = null;
  let fault: Fault | null = null;
  if (blank) [state, line] = ["empty", "Type a formula"];
  else if (current && "failure" in current) [state, line] = ["error", "✗ " + current.failure];
  else if (current && "fault" in current.reply) {
    fault = current.reply.fault;
    [state, line] = ["error", faultLine(text, fault)];
  } else if (current && "checked" in current.reply) {
    ready = current.reply.checked;
    [state, line] = ["ready", readyLine(ready)];
  }
  const last = check && "reply" in check && "checked" in check.reply ? check.reply.checked : null;
  const picture = state === "ready" ? ready : state === "pending" ? last : null;

  const saved = entry !== null;
  const favourites = offered.filter((other) => other.favourite);
  const inputs = new Map<string, string[]>();
  for (const listed of catalog?.names ?? []) if (!listed.step_only) inputs.set(listed.category, [...(inputs.get(listed.category) ?? []), listed.name]);
  const at = () => [field.current?.selectionStart ?? text.length, field.current?.selectionEnd ?? text.length] as const;
  const group = (title: string, names: string[]) =>
    names.length > 0 && (
      <>
        <h3>{title}</h3>
        <div>
          {names.map((inserted) => (
            <button type="button" key={inserted} onClick={() => insert(spelling(inserted), ...at())}>
              {inserted}
            </button>
          ))}
        </div>
      </>
    );

  return (
    <dialog id="variable-dialog" aria-labelledby="variable-dialog-title" ref={dialog} onClose={onEnd}>
      <div class="variable-dialog-head">
        <h2 id="variable-dialog-title">{request.title}</h2>
        <div class="variable-head-actions">
          <button type="button" id="variable-favourite" hidden={!saved} aria-pressed={entry?.favourite ? "true" : "false"} onClick={() => void favourite()}>
            {entry?.favourite ? "★ Favourite" : "☆ Favourite"}
          </button>
          <button type="button" id="variable-delete" hidden={!saved} onClick={() => void remove()}>
            Delete
          </button>
          <button type="button" id="variable-close" onClick={close}>
            Close
          </button>
        </div>
      </div>
      <div class="variable-form">
        <label for="variable-name">Name</label>
        <input
          id="variable-name"
          maxlength={120}
          autocomplete="off"
          placeholder="Optional. If empty, the formula is the name."
          value={name}
          onInput={(event) => setName(event.currentTarget.value)}
        />
        <label for="variable-formula">Formula</label>
        <div class="filter-combo">
          <textarea
            id="variable-formula"
            ref={field}
            rows={2}
            spellcheck={false}
            autocomplete="off"
            // The types allow a textarea only the textbox role; this one is a combobox.
            {...({ role: "combobox" } as object)}
            aria-autocomplete="list"
            aria-expanded={typing ? "true" : "false"}
            aria-controls="variable-suggestions"
            aria-activedescendant={typing ? `variable-suggestion-${typing.active}` : ""}
            placeholder="For example: Total debt / Enterprise value"
            value={text}
            onInput={(event) => {
              setText(event.currentTarget.value);
              suggest(event.currentTarget);
            }}
            onKeyDown={(event) => {
              const key = event.key;
              if (typing && (key === "ArrowDown" || key === "ArrowUp")) {
                event.preventDefault();
                const count = typing.words.length;
                setTyping({ ...typing, active: (typing.active + (key === "ArrowDown" ? 1 : count - 1)) % count });
              } else if (typing && (key === "Enter" || key === "Tab")) {
                event.preventDefault();
                take(typing.active);
              } else if (key === "Enter") {
                // Enter never adds a line.
                event.preventDefault();
              } else if (typing && key === "Escape") {
                // Escape hides the list and leaves the window open.
                event.preventDefault();
                setTyping(null);
              } else if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(key)) setTyping(null);
            }}
            // A moved caret ends the list; typing starts it again.
            onBlur={() => setTyping(null)}
            onClick={() => setTyping(null)}
          />
          <div
            id="variable-suggestions"
            class="filter-options"
            role="listbox"
            aria-label="Suggestions"
            hidden={!typing}
            onMouseDown={(event) => {
              // Choosing with the pointer keeps the caret in the formula.
              event.preventDefault();
              const option = (event.target as Element).closest<HTMLElement>("[data-suggestion]");
              if (option) take(Number(option.dataset.suggestion));
            }}
          >
            {typing?.words.map((word, i) => (
              <div role="option" id={`variable-suggestion-${i}`} key={word.detail + word.name} data-suggestion={i} aria-selected={i === typing.active ? "true" : "false"}>
                <span>{word.name}</span>
                <small>{word.detail}</small>
              </div>
            ))}
          </div>
        </div>
        <div id="variable-check" class="variable-check" data-state={state}>
          <span id="variable-check-text" role="status" aria-live="polite">
            {line}
          </span>{" "}
          <label id="variable-display-label" hidden={!ready || ready.displays.length < 2}>
            · Show as{" "}
            <select id="variable-display" value={ready ? shownDisplay(chosen, ready) : ""} onChange={(event) => setChosen(event.currentTarget.value)}>
              {ready?.displays.map((display) => (
                <option value={display} key={display}>
                  {displayName(display)}
                </option>
              ))}
            </select>
          </label>
          <span id="variable-fixes">
            {fault?.suggestions.map((suggestion) => (
              <button type="button" key={suggestion.text} onClick={() => insert(suggestion.text, ...faultRange(text, fault!))}>
                {suggestion.label}
              </button>
            ))}
          </span>
        </div>
        <div id="variable-picture" class="variable-picture" aria-label="How the formula was read">
          {picture && <Picture part={picture.picture} />}
        </div>
      </div>
      <div class="variable-actions">
        <button type="button" id="variable-save" disabled={busy} onClick={() => void waiting(() => save(false))}>
          {saved ? "Save changes" : "Save to My variables"}
        </button>
        <button type="button" id="variable-save-new" hidden={!saved} disabled={busy} onClick={() => void waiting(() => save(true))}>
          Save as new
        </button>
        <button type="button" id="variable-apply" class="primary" disabled={busy} onClick={() => void waiting(use)}>
          {request.use}
        </button>
      </div>
      <p id="variable-message" class={message?.failed ? "backtest-failed" : "hint"} role="status" aria-live="polite">
        {message?.text}
      </p>
      <details id="variable-inputs">
        <summary>All inputs</summary>
        <div id="variable-input-list">
          {group(
            "Favourites",
            favourites.map((other) => other.name),
          )}
          {group(
            "My variables",
            offered.map((other) => other.name),
          )}
          {[...inputs].map(([title, names]) => (
            <Fragment key={title}>{group(title, names)}</Fragment>
          ))}
        </div>
      </details>
    </dialog>
  );
}
