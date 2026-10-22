/** Number formatting helpers shared by all views. */

export function fmtInt(value) {
  return Number(value ?? 0).toLocaleString("en-US");
}

/** Fraction (0-1) -> "42.5%". */
export function fmtPct(value, digits = 1) {
  return `${(Number(value ?? 0) * 100).toFixed(digits)}%`;
}

/** Value already expressed in percent (0-100) -> "79.7%". */
export function fmtPctRaw(value, digits = 1) {
  return `${Number(value ?? 0).toFixed(digits)}%`;
}

export function fmtScore(value, digits = 4) {
  return Number(value ?? 0).toFixed(digits);
}

export function fmtWeight(value) {
  return Number(value ?? 0).toLocaleString("en-US");
}
