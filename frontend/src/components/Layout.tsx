import { AnimatePresence, motion } from "framer-motion";
import {
  Boxes, ChevronDown, Command, Database, FileSignature, LayoutDashboard, MessageSquareText, Moon, Scale, Search, ShieldCheck, Sun, Trophy, UserRound,
} from "lucide-react";
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { api, getUser, setUser, User } from "../lib/api";
import { cx, Kbd } from "./ui";

export type Health = {
  status: string; ai_available: boolean; ai_model: string; ai_provider?: string | null; data_ready: boolean; database: string;
  counts: Record<string, number>; active_policy: { version: string; effective_from: string } | null;
};
const HealthCtx = createContext<{ health: Health | null; refresh: () => void; online: boolean }>({ health: null, refresh: () => {}, online: true });
export const useHealth = () => useContext(HealthCtx);

export function useUser(): User {
  const [u, setU] = useState(getUser());
  useEffect(() => {
    const f = () => setU(getUser());
    window.addEventListener("cantill:user", f);
    return () => window.removeEventListener("cantill:user", f);
  }, []);
  return u;
}

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, hint: "Status and next steps" },
  { to: "/chat", label: "Raise a PR", icon: MessageSquareText, hint: "Chat with the intake assistant" },
  { to: "/workspace", label: "Buyer workspace", icon: Boxes, hint: "Decisions to approve" },
  { to: "/policy", label: "Policy studio", icon: Scale, hint: "Versions and amendments" },
  { to: "/contracts", label: "Contracts", icon: FileSignature, hint: "Rate contracts and ceilings" },
  { to: "/suppliers", label: "Preferred suppliers", icon: Trophy, hint: "Rankings and export" },
  { to: "/data", label: "Data & audit", icon: Database, hint: "Master data and audit trail" },
];

const PEOPLE: User[] = [
  { name: "Priya Buyer", role: "buyer" },
  { name: "Rahul Requester", role: "requester" },
  { name: "Meera Procurement Head", role: "procurement" },
  { name: "Admin", role: "admin" },
];

function UserMenu() {
  const user = useUser();
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const f = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", f);
    return () => document.removeEventListener("mousedown", f);
  }, []);
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} className="flex items-center gap-2 rounded-lg border border-line bg-panel2 py-1 pl-1 pr-2 text-sm hover:border-accent/40">
        <span className="grid h-7 w-7 place-items-center rounded-md bg-accent/15 font-display text-[12px] font-semibold text-accent">
          {user.name.split(" ").map((p) => p[0]).slice(0, 2).join("")}
        </span>
        <span className="hidden text-left leading-tight sm:block">
          <span className="block text-[13px] font-medium">{user.name}</span>
          <span className="block text-[11px] capitalize text-muted">{user.role}</span>
        </span>
        <ChevronDown className="h-3.5 w-3.5 text-muted" />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
            className="absolute right-0 z-50 mt-2 w-64 rounded-xl border border-line bg-panel p-1.5 shadow-2xl">
            <div className="px-2 py-1.5 text-[11px] uppercase tracking-wider text-faint">Acting as (recorded in the audit log)</div>
            {PEOPLE.map((p) => (
              <button key={p.name} onClick={() => { setUser(p); setOpen(false); }}
                className={cx("flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-sm hover:bg-panel2", p.name === user.name && "text-accent")}>
                <span>{p.name}</span><span className="text-[11px] capitalize text-muted">{p.role}</span>
              </button>
            ))}
            <form className="mt-1 flex gap-1 border-t border-line p-1.5" onSubmit={(e) => { e.preventDefault(); if (custom.trim()) { setUser({ name: custom.trim(), role: user.role }); setCustom(""); setOpen(false); } }}>
              <input value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="Your name" className="h-8 flex-1 rounded-md border border-line bg-panel2 px-2 text-[13px] focus:outline-none" />
              <button className="rounded-md bg-accent/15 px-2 text-[12px] font-medium text-accent">Use</button>
            </form>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function ThemeToggle() {
  const [dark, setDark] = useState(document.documentElement.classList.contains("dark"));
  return (
    <button aria-label="Dark mode" aria-pressed={dark} onClick={() => {
      const d = !dark; setDark(d);
      document.documentElement.classList.toggle("dark", d);
      try { localStorage.setItem("theme", d ? "dark" : "light"); } catch {}
    }} className="grid h-9 w-9 place-items-center rounded-lg border border-line bg-panel2 text-muted hover:text-ink">
      <AnimatePresence mode="wait" initial={false}>
        <motion.span key={dark ? "d" : "l"} initial={{ rotate: -90, opacity: 0 }} animate={{ rotate: 0, opacity: 1 }} exit={{ rotate: 90, opacity: 0 }}>
          {dark ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
        </motion.span>
      </AnimatePresence>
    </button>
  );
}

function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<any[]>([]);
  const [sel, setSel] = useState(0);
  useEffect(() => { if (open) { setQ(""); setSel(0); } }, [open]);
  useEffect(() => {
    if (!open || q.length < 2) { setItems([]); return; }
    const t = setTimeout(() => api.get(`/api/items?q=${encodeURIComponent(q)}`).then(setItems).catch(() => setItems([])), 150);
    return () => clearTimeout(t);
  }, [q, open]);
  const pages = NAV.filter((n) => !q || n.label.toLowerCase().includes(q.toLowerCase()));
  const results = [
    ...pages.map((p) => ({ kind: "page", label: p.label, sub: p.hint, go: () => nav(p.to), Icon: p.icon })),
    ...items.slice(0, 6).map((it) => ({ kind: "item", label: `${it.item_code} · ${it.description}`, sub: `${it.category} · ranking`, go: () => nav(`/suppliers?item=${it.item_code}`), Icon: Trophy })),
  ];
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-[60] flex items-start justify-center p-4 pt-[12vh]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
          <motion.div role="dialog" aria-modal="true" aria-label="Command palette" initial={{ scale: 0.97, y: -8 }} animate={{ scale: 1, y: 0 }} className="relative w-full max-w-xl overflow-hidden rounded-2xl border border-line bg-panel shadow-2xl">
            <div className="flex items-center gap-2 border-b border-line px-4">
              <Search className="h-4 w-4 text-muted" />
              <input autoFocus aria-label="Jump to a page or search items" value={q} onChange={(e) => { setQ(e.target.value); setSel(0); }} placeholder="Jump to a page or search items…"
                onKeyDown={(e) => {
                  if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, results.length - 1)); }
                  if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
                  if (e.key === "Enter" && results[sel]) { results[sel].go(); onClose(); }
                  if (e.key === "Escape") onClose();
                }}
                className="h-12 flex-1 bg-transparent text-sm focus:outline-none" />
              <Kbd>esc</Kbd>
            </div>
            <div className="max-h-80 overflow-y-auto p-1.5">
              {results.map((r, i) => (
                <button key={r.label} onMouseEnter={() => setSel(i)} onClick={() => { r.go(); onClose(); }}
                  className={cx("flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left", i === sel ? "bg-panel2" : "")}>
                  <r.Icon className="h-4 w-4 text-muted" />
                  <span className="flex-1 truncate text-sm">{r.label}</span>
                  <span className="text-[11.5px] text-faint">{r.sub}</span>
                </button>
              ))}
              {!results.length && <div className="px-3 py-6 text-center text-sm text-muted">No matches</div>}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function Layout({ children }: { children: React.ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [online, setOnline] = useState(true);
  const [palette, setPalette] = useState(false);
  const loc = useLocation();
  const refresh = useCallback(() => {
    api.get<Health>("/api/health").then((h) => { setHealth(h); setOnline(true); }).catch(() => setOnline(false));
  }, []);
  useEffect(() => { refresh(); const t = setInterval(refresh, 20000); return () => clearInterval(t); }, [refresh]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); } };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  const ctx = useMemo(() => ({ health, refresh, online }), [health, refresh, online]);
  const current = NAV.find((n) => (n.to === "/" ? loc.pathname === "/" : loc.pathname.startsWith(n.to)));

  return (
    <HealthCtx.Provider value={ctx}>
      <div className="flex h-full">
        <aside className="hidden w-[236px] shrink-0 flex-col border-r border-line bg-panel/60 lg:flex">
          <div className="flex items-center gap-2.5 px-5 py-5">
            <img src="/favicon.svg" alt="" className="h-8 w-8" />
            <div className="leading-tight">
              <div className="font-display text-[15px] font-semibold">Corvo Procure</div>
              <div className="text-[11px] text-muted">PR → PO, by policy</div>
            </div>
          </div>
          <nav className="flex-1 space-y-0.5 px-3">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.to === "/"} className="relative block">
                {({ isActive }) => (
                  <div className={cx("relative flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors", isActive ? "text-ink" : "text-muted hover:text-ink")}>
                    {isActive && <motion.span layoutId="nav-active" className="absolute inset-0 rounded-lg border border-line bg-panel2" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
                    {isActive && <motion.span layoutId="nav-bar" className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-accent" />}
                    <n.icon className={cx("relative h-4 w-4", isActive && "text-accent")} />
                    <span className="relative">{n.label}</span>
                    {n.to === "/workspace" && (health?.counts?.open_prs ?? 0) > 0 && (
                      <span className="relative ml-auto rounded-full bg-warn/15 px-1.5 text-[10.5px] font-semibold text-warn">{health?.counts.open_prs}</span>
                    )}
                  </div>
                )}
              </NavLink>
            ))}
          </nav>
          <div className="m-3 rounded-xl border border-line bg-panel2/60 p-3 text-[12px]">
            <div className="mb-2 flex items-center gap-1.5 font-medium"><ShieldCheck className="h-3.5 w-3.5 text-accent" /> System</div>
            <StatusRow label="API" ok={online} text={online ? "online" : "offline"} />
            <StatusRow label="Database" ok={!!health} text={health?.database ?? "…"} />
            <StatusRow label="Master data" ok={!!health?.data_ready} text={health?.data_ready ? "loaded" : "not loaded"} />
            <StatusRow label="AI reader" ok={!!health?.ai_available} warn text={health?.ai_available ? aiLabel(health?.ai_provider) : "rule-based"} />
            <StatusRow label="Policy today" ok={!!health?.active_policy} text={health?.active_policy ? `v${health.active_policy.version}` : "…"} />
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-bg/80 px-4 backdrop-blur-md md:px-6">
            <MobileNav />
            <div className="min-w-0 flex-1 truncate text-sm text-muted">
              <span className="text-faint">Corvo Engineering</span><span className="mx-2 text-faint">/</span><span className="text-ink">{current?.label ?? ""}</span>
            </div>
            <button onClick={() => setPalette(true)} className="hidden h-9 items-center gap-2 rounded-lg border border-line bg-panel2 px-3 text-[13px] text-muted hover:text-ink md:flex">
              <Search className="h-3.5 w-3.5" /> Search <span className="ml-3 flex items-center gap-0.5"><Kbd><Command className="inline h-2.5 w-2.5" /></Kbd><Kbd>K</Kbd></span>
            </button>
            <ThemeToggle />
            <UserMenu />
          </header>
          {!online && <div className="border-b border-bad/30 bg-bad/10 px-6 py-2 text-[13px] text-bad">The API is not reachable. Start the backend, then this page reconnects by itself.</div>}
          <main className="relative min-w-0 flex-1 overflow-x-hidden">
            <div className="pointer-events-none absolute inset-x-0 top-0 h-64 grid-bg opacity-60" />
            <AnimatePresence mode="wait">
              <motion.div key={loc.pathname} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.2 }}
                className="relative mx-auto w-full max-w-[1400px] px-4 py-6 md:px-8">
                {children}
              </motion.div>
            </AnimatePresence>
          </main>
        </div>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} />
    </HealthCtx.Provider>
  );
}

function StatusRow({ label, ok, text, warn }: { label: string; ok: boolean; text: string; warn?: boolean }) {
  return (
    <div className="flex items-center justify-between py-0.5">
      <span className="text-muted">{label}</span>
      <span className="flex items-center gap-1.5">
        <span className={cx("h-1.5 w-1.5 rounded-full", ok ? "bg-ok" : warn ? "bg-warn" : "bg-bad", ok && "animate-pulseDot")} />
        <span className="font-mono text-[11px]">{text}</span>
      </span>
    </div>
  );
}

function MobileNav() {
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);
  return (
    <div className="lg:hidden">
      <button onClick={() => setOpen(!open)} className="grid h-9 w-9 place-items-center rounded-lg border border-line bg-panel2" aria-label="Menu">
        <UserRound className="hidden" /><span className="font-display text-sm">≡</span>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="absolute left-3 top-14 z-50 w-60 rounded-xl border border-line bg-panel p-1.5 shadow-2xl">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.to === "/"} className={({ isActive }) => cx("flex items-center gap-2 rounded-lg px-3 py-2 text-sm", isActive ? "bg-panel2 text-ink" : "text-muted")}>
                <n.icon className="h-4 w-4" />{n.label}
              </NavLink>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function aiLabel(p?: string | null) {
  return p === "gemini" ? "Gemini" : p === "groq" ? "Groq" : "Claude";
}
