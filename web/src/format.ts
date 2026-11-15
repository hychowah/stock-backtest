/** A fraction as a percentage with two decimals: 0.1234 becomes "12.34%". A missing value shows as a dash. */
export function formatPercent(value: number | null | undefined): string {
  return value == null ? "—" : `${(value * 100).toFixed(2)}%`;
}
