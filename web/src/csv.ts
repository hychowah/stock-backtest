/** CSV text of reply rows: one line of headers, which are the rows' field
 *  names in the order they first appear, then one line per row. A missing or
 *  null value is an empty cell; a number keeps all its digits; text with a
 *  comma, quote or line break is quoted. */
export function toCsv(rows: readonly object[]): string {
  const headers = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const cell = (value: unknown) => {
    const text = value == null ? "" : typeof value === "object" ? JSON.stringify(value) : String(value);
    return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  const line = (values: unknown[]) => values.map(cell).join(",");
  return [line(headers), ...rows.map((row) => line(headers.map((header) => (row as Record<string, unknown>)[header])))].join("\n") + "\n";
}
