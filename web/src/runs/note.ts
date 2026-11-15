import { useState } from "preact/hooks";
import { act } from "../live.ts";
import { asFailure } from "../read.ts";

/** The line a panel says what its last action did: the success text, or the
 *  server's refusal (`error`). */
export type Note = { text: string; error: boolean } | null;

/** The note of a panel and its way to send a change. `perform(change,
 *  success)` sends the change through act(), then sets the note to `success`
 *  or to the refusal's message, and keeps `busy` while the change is sent, so
 *  that a button is not pressed twice. */
export function useActions() {
  const [note, setNote] = useState<Note>(null);
  const [busy, setBusy] = useState(false);
  async function perform(change: () => Promise<unknown>, success: string): Promise<boolean> {
    setBusy(true);
    try {
      await act(change);
      setNote({ text: success, error: false });
      return true;
    } catch (thrown) {
      setNote({ text: asFailure(thrown).message, error: true });
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { note, setNote, busy, perform };
}

/** The `perform` of useActions, for the rows that send changes. */
export type Perform = ReturnType<typeof useActions>["perform"];

/** The `setNote` of useActions, for a row that says why it sent nothing. */
export type SetNote = ReturnType<typeof useActions>["setNote"];
