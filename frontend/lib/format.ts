const timeFormat = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** "HH:mm" in the viewer's local time. */
export function formatTime(iso: string): string {
  return timeFormat.format(new Date(iso));
}

/** "30 Sep, 06:15" in the viewer's local time. */
export function formatDateTime(iso: string): string {
  return dateTimeFormat.format(new Date(iso));
}
