// Numbers the way Indian readers expect them: 1,78,650 and ₹1.94 lakh crore.

const grouping = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const whole = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export function rupees(value: number | null | undefined, digits = 2): string {
  if (value == null) return "—";
  return "₹" + new Intl.NumberFormat("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits })
    .format(value);
}

export function plain(value: number | null | undefined): string {
  return value == null ? "—" : grouping.format(value);
}

export function count(value: number | null | undefined): string {
  return value == null ? "—" : whole.format(value);
}

const CRORE = 1e7;
const LAKH_CRORE = 1e12;

/** Large rupee amounts in crore, or lakh crore once they get that big. */
export function crore(value: number | null | undefined): string {
  if (value == null) return "—";
  const sign = value < 0 ? "−" : "";
  const abs = Math.abs(value);
  if (abs >= LAKH_CRORE) return `${sign}₹${(abs / LAKH_CRORE).toFixed(2)} lakh crore`;
  return `${sign}₹${whole.format(Math.round(abs / CRORE))} crore`;
}

export function percent(value: number | null | undefined, digits = 1): string {
  return value == null ? "—" : `${value.toFixed(digits)}%`;
}

export function signed(value: number | null | undefined, digits = 2): string {
  if (value == null) return "—";
  const s = Math.abs(value).toFixed(digits);
  return value > 0 ? `+${s}` : value < 0 ? `−${s}` : s;
}

export function metricValue(unit: string, value: number | null): string {
  if (value == null) return "—";
  switch (unit) {
    case "INR":
      return crore(value);
    case "INR_PER_SHARE":
      return rupees(value);
    case "PERCENT":
      return percent(value);
    case "RATIO":
      return `${value.toFixed(1)}×`;
    default:
      return plain(value);
  }
}

const dateFmt = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });
const shortDate = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });
const dateTime = new Intl.DateTimeFormat("en-IN", {
  day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata",
});

export const fmtDate = (iso: string) => dateFmt.format(new Date(iso));
export const fmtShortDate = (iso: string) => shortDate.format(new Date(iso));
export const fmtDateTime = (iso: string) => dateTime.format(new Date(iso));

/** "3 hours ago", falling back to a date after a week. */
export function ago(iso: string, now = Date.now()): string {
  const minutes = Math.round((now - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
  return fmtDate(iso);
}
