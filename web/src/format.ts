/** Number formatters shared by the pages. A missing value shows as a dash. */

const MISSING = "—";

/** A fraction as a percentage with two decimals: 0.1234 becomes "12.34%". */
export function formatPercent(value: number | null | undefined): string {
  return value == null ? MISSING : `${(value * 100).toFixed(2)}%`;
}

/** A dollar amount with two decimals: 1.5 becomes "$1.50". */
export function formatDollars(value: number | null | undefined): string {
  return value == null ? MISSING : `$${value.toFixed(2)}`;
}
