import { editHeld, heldEditOpen, OPEN_EDIT, tune } from "../build/Build.tsx";
import { ApiFailure, client } from "../client.ts";
import type { Perform, SetNote } from "./note.ts";

/** The two row actions that load a run into Build strategy, which then shows.
 *  While a held run's edit is open there, neither sends anything, and the
 *  panel says why. */

/** Tune: reads the run and puts its settings into the live draft. */
export function tuneRun(id: number, perform: Perform, setNote: SetNote): void {
  if (heldEditOpen()) return setNote({ text: OPEN_EDIT, error: true });
  void perform(async () => tune(await client.run(id)), "Settings copied to the strategy controls. Change them and add a new test.");
}

/** Edit settings: reads the run, holds it when it waits, and opens the
 *  settings of the run as it is after the hold. A run that is neither waiting
 *  nor held when it is read is not edited. */
export function editRun(id: number, perform: Perform, setNote: SetNote): void {
  if (heldEditOpen()) return setNote({ text: OPEN_EDIT, error: true });
  void perform(async () => {
    let run = await client.run(id);
    if (run.state === "waiting") {
      await client.hold(id);
      run = await client.run(id);
    }
    if (run.state !== "held") throw new ApiFailure(409, "Only a waiting or held test can be edited.", "");
    editHeld(run);
  }, "Test held. Edit its settings in Build strategy, then save or cancel the edit.");
}
