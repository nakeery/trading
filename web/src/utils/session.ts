// Market-session helpers (S70). Mirrors the server's pc_oi/netcache convention:
// a report generated today is fresh until the next weekday 16:00 ET (half-days ignored).

/** Milliseconds from now until the next weekday 16:00 ET. */
export function msUntilNextClose(now: Date = new Date()): number {
  // Read the current wall-clock in New York via Intl (no tz library).
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false, weekday: 'short',
  }).formatToParts(now)
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
  const weekday = get('weekday') // 'Mon'..'Sun'
  const h = Number(get('hour')) % 24 // Intl can emit '24' at midnight
  const m = Number(get('minute'))
  const s = Number(get('second'))

  const secsOfDay = h * 3600 + m * 60 + s
  const closeSecs = 16 * 3600
  const dayIdx = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(weekday)

  // Days until the next weekday whose 16:00 ET is still ahead of us.
  let addDays = 0
  let idx = dayIdx
  if (idx === 0 || idx === 6 || secsOfDay >= closeSecs) {
    // weekend, or past today's close — advance to the next weekday
    do {
      addDays += 1
      idx = (idx + 1) % 7
    } while (idx === 0 || idx === 6)
  }
  const msToday = (closeSecs - secsOfDay) * 1000
  return addDays > 0
    ? msToday + addDays * 24 * 3600 * 1000 // DST shifts make this ±1h — fine for a staleness bound
    : msToday
}
