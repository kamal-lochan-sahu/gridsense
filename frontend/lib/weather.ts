/**
 * Index of the current hour inside Open-Meteo's hourly_time array
 * (local wall-clock strings such as "2026-09-30T14:00" in `timeZone`).
 * Returns -1 when the current hour is not in the data.
 */
export function currentHourIndex(times: string[], timeZone: string, now: Date): number {
  if (times.length === 0) return -1;
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return times.indexOf(`${get("year")}-${get("month")}-${get("day")}T${get("hour")}:00`);
}
