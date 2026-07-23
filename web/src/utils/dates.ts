// Local-timezone date helpers. NB: `new Date().toISOString()` is UTC — in any US timezone
// it rolls to tomorrow around 5–8 PM local, so using it for "today" let the as-of controls
// prefill/admit a session that doesn't exist yet.

/** Today's date in the LOCAL timezone as YYYY-MM-DD ("sv" locale formats ISO-style). */
export function localToday(): string {
  return new Date().toLocaleDateString('sv')
}
