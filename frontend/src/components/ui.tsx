import clsx from "clsx";
import { AnimatePresence, motion, useMotionValue, useSpring, useTransform } from "framer-motion";
import { Loader2, UploadCloud, X } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { routeInfo } from "../lib/format";

export const cx = clsx;

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "subtle";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  icon?: React.ReactNode;
};
export function Button({ variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest }: BtnProps) {
  return (
    <motion.button
      whileTap={{ scale: disabled || loading ? 1 : 0.97 }}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed select-none whitespace-nowrap",
        size === "sm" && "h-8 px-3 text-[13px]",
        size === "md" && "h-9 px-3.5 text-sm",
        size === "lg" && "h-11 px-5 text-[15px]",
        variant === "primary" && "bg-accent text-[rgb(var(--bg))] hover:bg-accent2 shadow-glow",
        variant === "secondary" && "bg-panel2 border border-line text-ink hover:border-accent/50",
        variant === "ghost" && "text-muted hover:text-ink hover:bg-panel2",
        variant === "subtle" && "bg-accent/10 text-accent hover:bg-accent/15",
        variant === "danger" && "bg-bad/10 text-bad border border-bad/30 hover:bg-bad/15",
        className,
      )}
      disabled={disabled || loading}
      {...(rest as any)}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </motion.button>
  );
}

export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cx("rounded-xl border border-line bg-panel", className)} {...rest}>{children}</div>;
}

const TONES: Record<string, string> = {
  accent: "bg-accent/10 text-accent border-accent/25",
  info: "bg-info/10 text-info border-info/25",
  ok: "bg-ok/10 text-ok border-ok/25",
  warn: "bg-warn/10 text-warn border-warn/25",
  bad: "bg-bad/10 text-bad border-bad/25",
  vio: "bg-vio/10 text-vio border-vio/25",
  muted: "bg-panel2 text-muted border-line",
};
export function Badge({ tone = "muted", className, children, dot }: { tone?: string; className?: string; children: React.ReactNode; dot?: boolean }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-[11.5px] font-medium leading-4 whitespace-nowrap", TONES[tone] || TONES.muted, className)}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}
export function RouteBadge({ route, className }: { route: string; className?: string }) {
  const r = routeInfo(route);
  return <Badge tone={r.tone} dot className={className}>{r.label}</Badge>;
}
export function Mono({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cx("font-mono text-[12.5px]", className)}>{children}</span>;
}
export function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="rounded border border-line bg-panel2 px-1.5 py-0.5 font-mono text-[10.5px] text-muted">{children}</kbd>;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("h-4 w-4 animate-spin text-muted", className)} />;
}
export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton h-4", className)} />;
}

export function AnimatedNumber({ value, format = (n: number) => Math.round(n).toLocaleString("en-IN") }: { value: number; format?: (n: number) => string }) {
  const mv = useMotionValue(0);
  const spring = useSpring(mv, { stiffness: 90, damping: 20 });
  const text = useTransform(spring, (v) => format(v));
  const [display, setDisplay] = useState(format(value));
  useEffect(() => { mv.set(value); }, [value]);
  useEffect(() => text.on("change", (v) => setDisplay(v)), [text]);
  return <span className="tabular">{display}</span>;
}

export function PageHeader({ eyebrow, title, desc, actions }: { eyebrow?: string; title: string; desc?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 pb-5">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 font-mono text-[11px] uppercase tracking-[0.14em] text-accent">{eyebrow}</div>}
        <h1 className="text-[26px] font-semibold leading-tight">{title}</h1>
        {desc && <p className="mt-1 max-w-2xl text-sm text-muted">{desc}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Empty({ icon, title, desc, action }: { icon?: React.ReactNode; title: string; desc?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      {icon && <div className="grid h-12 w-12 place-items-center rounded-xl border border-line bg-panel2 text-muted">{icon}</div>}
      <div className="font-display text-base font-semibold">{title}</div>
      {desc && <div className="max-w-md text-sm text-muted">{desc}</div>}
      {action}
    </div>
  );
}

export function Modal({ open, onClose, title, children, footer, wide }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; footer?: React.ReactNode; wide?: boolean }) {
  const dialogRef = useRef<HTMLDivElement>(null);
  // Move focus into the dialog when it opens and hand it back to the trigger on close.
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const t = setTimeout(() => {
      const el = dialogRef.current;
      if (el && !el.contains(document.activeElement)) el.focus();
    }, 0);
    return () => { clearTimeout(t); prev?.focus?.(); };
  }, [open]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 grid place-items-center p-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
          <motion.div
            ref={dialogRef} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}
            initial={{ y: 16, scale: 0.98, opacity: 0 }} animate={{ y: 0, scale: 1, opacity: 1 }} exit={{ y: 10, opacity: 0 }}
            transition={{ type: "spring", stiffness: 380, damping: 30 }}
            className={cx("relative w-full rounded-2xl border border-line bg-panel shadow-2xl focus:outline-none", wide ? "max-w-4xl" : "max-w-lg")}
          >
            <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
              <h3 className="text-base font-semibold">{title}</h3>
              <button onClick={onClose} className="rounded-md p-1 text-muted hover:bg-panel2 hover:text-ink" aria-label="Close"><X className="h-4 w-4" /></button>
            </div>
            <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
            {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function Drawer({ open, onClose, children, width = 720 }: { open: boolean; onClose: () => void; children: React.ReactNode; width?: number }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <motion.aside
            className="fixed right-0 top-0 z-50 h-full overflow-y-auto border-l border-line bg-panel shadow-2xl"
            style={{ width: `min(${width}px, 100vw)` }}
            initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ type: "spring", stiffness: 320, damping: 34 }}
          >
            {children}
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { value: T; label: React.ReactNode; count?: number }[] }) {
  return (
    <div role="tablist" className="inline-flex max-w-full overflow-x-auto rounded-lg border border-line bg-panel2 p-0.5">
      {items.map((it) => (
        <button key={it.value} role="tab" type="button" aria-selected={value === it.value} onClick={() => onChange(it.value)} className={cx("relative shrink-0 whitespace-nowrap rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors", value === it.value ? "text-ink" : "text-muted hover:text-ink")}>
          {value === it.value && <motion.span layoutId={`tab-${items.map((i) => i.value).join()}`} className="absolute inset-0 rounded-md border border-line bg-panel shadow-sm" transition={{ type: "spring", stiffness: 400, damping: 32 }} />}
          <span className="relative flex items-center gap-1.5">{it.label}{it.count !== undefined && <span className="tabular text-[11px] text-faint">{it.count}</span>}</span>
        </button>
      ))}
    </div>
  );
}

export function Field({ label, hint, children, className }: { label: string; hint?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <label className={cx("block", className)}>
      <span className="mb-1 block text-[12px] font-medium text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11.5px] text-faint">{hint}</span>}
    </label>
  );
}
export const inputCls = "h-9 w-full rounded-lg border border-line bg-panel2 px-3 text-sm text-ink placeholder:text-faint focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/20";

export function Progress({ value, tone = "accent", className }: { value: number; tone?: string; className?: string }) {
  const color = { accent: "bg-accent", warn: "bg-warn", bad: "bg-bad", ok: "bg-ok", info: "bg-info" }[tone] || "bg-accent";
  return (
    <div className={cx("h-1.5 w-full overflow-hidden rounded-full bg-panel2", className)}>
      <motion.div className={cx("h-full rounded-full", color)} initial={{ width: 0 }} animate={{ width: `${Math.max(0, Math.min(100, value))}%` }} transition={{ type: "spring", stiffness: 80, damping: 20 }} />
    </div>
  );
}

export function Dropzone({ onFiles, accept, multiple, label, sub, busy }: { onFiles: (f: File[]) => void; accept?: string; multiple?: boolean; label: string; sub?: string; busy?: boolean }) {
  const [over, setOver] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const fs = Array.from(e.dataTransfer.files); if (fs.length) onFiles(fs); }}
      onClick={() => ref.current?.click()}
      role="button" tabIndex={0} aria-label={label} aria-busy={busy || undefined}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ref.current?.click(); } }}
      className={cx("group relative flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-6 py-8 text-center transition-all",
        over ? "border-accent bg-accent/5 scale-[1.01]" : "border-line bg-panel2/50 hover:border-accent/50")}
    >
      <input ref={ref} type="file" className="hidden" accept={accept} multiple={multiple} onChange={(e) => { const fs = Array.from(e.target.files || []); if (fs.length) onFiles(fs); e.target.value = ""; }} />
      <motion.div animate={over ? { y: -4 } : { y: 0 }} className="grid h-11 w-11 place-items-center rounded-xl border border-line bg-panel text-accent">
        {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <UploadCloud className="h-5 w-5" />}
      </motion.div>
      <div className="text-sm font-medium">{label}</div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function Stat({ label, value, sub, icon, tone = "accent" }: { label: string; value: React.ReactNode; sub?: React.ReactNode; icon?: React.ReactNode; tone?: string }) {
  return (
    <Card className="relative overflow-hidden p-4">
      <div className="flex items-start justify-between">
        <div className="text-[12px] font-medium text-muted">{label}</div>
        {icon && <div className={cx("grid h-7 w-7 place-items-center rounded-lg border", TONES[tone])}>{icon}</div>}
      </div>
      <div className="mt-2 font-display text-[26px] font-semibold leading-none">{value}</div>
      {sub && <div className="mt-1.5 text-[12px] text-muted">{sub}</div>}
    </Card>
  );
}

export const fadeUp = { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.28, ease: [0.2, 0.8, 0.2, 1] } };
export const stagger = (i: number) => ({ initial: { opacity: 0, y: 6 }, animate: { opacity: 1, y: 0 }, transition: { delay: Math.min(i, 20) * 0.025, duration: 0.25 } });
