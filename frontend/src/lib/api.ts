// Thin fetch wrapper: sends who is acting (audited server-side) and surfaces API errors as readable messages.
export type User = { name: string; role: "requester" | "buyer" | "procurement" | "admin" };

const USER_KEY = "cantill.user";
export function getUser(): User {
  try {
    const u = JSON.parse(localStorage.getItem(USER_KEY) || "null");
    if (u && u.name) return u;
  } catch {}
  return { name: "Priya Buyer", role: "buyer" };
}
export function setUser(u: User) {
  try { localStorage.setItem(USER_KEY, JSON.stringify(u)); } catch {}
  window.dispatchEvent(new Event("cantill:user"));
}

function headers(extra?: Record<string, string>) {
  const u = getUser();
  return { "X-User": u.name, "X-Role": u.role, ...(extra || {}) };
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : Array.isArray(j.detail) ? j.detail.map((d: any) => d.msg).join("; ") : JSON.stringify(j.detail ?? j);
    } catch {}
    throw new ApiError(res.status, msg || `Request failed (${res.status})`);
  }
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T = any>(url: string) => fetch(url, { headers: headers() }).then((r) => handle<T>(r)),
  post: <T = any>(url: string, body?: unknown) =>
    fetch(url, { method: "POST", headers: headers({ "Content-Type": "application/json" }), body: JSON.stringify(body ?? {}) }).then((r) => handle<T>(r)),
  put: <T = any>(url: string, body?: unknown) =>
    fetch(url, { method: "PUT", headers: headers({ "Content-Type": "application/json" }), body: JSON.stringify(body ?? {}) }).then((r) => handle<T>(r)),
  del: <T = any>(url: string) => fetch(url, { method: "DELETE", headers: headers() }).then((r) => handle<T>(r)),
  upload: <T = any>(url: string, form: FormData) => fetch(url, { method: "POST", headers: headers(), body: form }).then((r) => handle<T>(r)),
  async download(url: string, fallbackName: string) {
    const res = await fetch(url, { headers: headers() });
    if (!res.ok) await handle(res);
    const blob = await res.blob();
    const cd = res.headers.get("content-disposition") || "";
    const name = /filename="?([^"]+)"?/.exec(cd)?.[1] || fallbackName;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    return name;
  },
};
