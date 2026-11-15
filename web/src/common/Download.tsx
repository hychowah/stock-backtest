import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import { toCsv } from "../csv.ts";
import { asFailure } from "../read.ts";

/** A button that saves `rows` as the CSV file `file` (see toCsv: the headers
 *  are the reply's field names). `rows` is called when the button is pressed;
 *  it may return a promise, for rows that are read only then. A failure to
 *  read them shows beside the button, and the button waits while they are
 *  read. */
export function Download({ id, file, rows, children }: { id?: string; file: string; rows: () => readonly object[] | Promise<readonly object[]>; children: ComponentChildren }) {
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setFailure("");
    setBusy(true);
    let found: readonly object[];
    try {
      found = await rows();
    } catch (thrown) {
      setFailure(asFailure(thrown).message);
      return;
    } finally {
      setBusy(false);
    }
    const url = URL.createObjectURL(new Blob([toCsv(found)], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = file;
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <>
      <button type="button" id={id} disabled={busy} onClick={() => void save()}>
        {children}
      </button>
      {failure && (
        <span class="screen-message warning" role="alert">
          {" "}
          {failure}
        </span>
      )}
    </>
  );
}
