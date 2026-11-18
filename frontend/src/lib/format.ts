// Indian digit grouping: 1234567 -> ₹12,34,567
export function inr(v: number | string | null | undefined, decimals = 0): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (!isFinite(n)) return String(v);
  return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
export function num(v: number | string | null | undefined, decimals = 2): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return n.toLocaleString("en-IN", { maximumFractionDigits: decimals });
}
export function compactInr(v: number): string {
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
  return inr(v);
}
export function fmtDate(s?: string | null): string {
  if (!s) return "—";
  const d = new Date(s.length <= 10 ? s + "T00:00:00" : s.replace(" ", "T"));
  if (isNaN(+d)) return s;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}
export function fmtDateTime(s?: string | null): string {
  if (!s) return "—";
  const d = new Date(s.endsWith("Z") ? s : s.replace(" ", "T"));
  if (isNaN(+d)) return s;
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
export function ago(s?: string | null): string {
  if (!s) return "";
  const d = new Date(s);
  const sec = (Date.now() - +d) / 1000;
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} h ago`;
  return `${Math.floor(sec / 86400)} d ago`;
}

export const ROUTES: Record<string, { label: string; tone: string; short: string }> = {
  CONTRACT_PO: { label: "Contract PO", short: "Contract", tone: "accent" },
  SPOT_PO: { label: "Spot PO", short: "Spot", tone: "info" },
  EMERGENCY_PO: { label: "Emergency PO", short: "Emergency", tone: "bad" },
  RFQ: { label: "RFQ", short: "RFQ", tone: "warn" },
  RFP: { label: "RFP", short: "RFP", tone: "warn" },
  CAPEX_SOURCING: { label: "Capex sourcing", short: "Capex", tone: "vio" },
  NEW_ITEM_SOURCING: { label: "New item sourcing", short: "New item", tone: "vio" },
  NOT_PROCESSED: { label: "Not processed", short: "Not processed", tone: "muted" },
};
export const routeInfo = (r: string) => ROUTES[r] || { label: r.replace(/_/g, " ").toLowerCase(), short: r, tone: "muted" };
