import type { ComponentChildren } from "preact";
import { toCsv } from "../csv.ts";

/** A button that saves `rows` as the CSV file `file` (see toCsv: the headers
 *  are the reply's field names). `rows` is called when the button is pressed. */
export function Download({ id, file, rows, children }: { id?: string; file: string; rows: () => readonly object[]; children: ComponentChildren }) {
  const save = () => {
    const url = URL.createObjectURL(new Blob([toCsv(rows())], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = file;
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <button type="button" id={id} onClick={save}>
      {children}
    </button>
  );
}
