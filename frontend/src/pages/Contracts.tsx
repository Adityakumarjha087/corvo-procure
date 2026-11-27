import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ChevronDown, FilePlus2, FileText, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Badge, Button, Card, Dropzone, Empty, Field, Modal, Mono, PageHeader, Progress, Skeleton, Tabs, cx, inputCls, stagger } from "../components/ui";
import { api } from "../lib/api";
import { compactInr, fmtDate, inr, num } from "../lib/format";

const blank = { contract_id: "", supplier_id: "", supplier_name: "", start_date: "", end_date: "", value_cap: "", consumed_value: 0, lines: [{ item_code: "", rate: "" }], warnings: [] as string[], source: "manual" };

export default function ContractsPage() {
  const [rows, setRows] = useState<any[] | null>(null);
  const [filter, setFilter] = useState<"all" | "active" | "upcoming" | "expired">("all");
  const [openId, setOpenId] = useState<string | null>(null);
  const [add, setAdd] = useState(false);
  const [failed, setFailed] = useState(false);
  const load = () => api.get("/api/contracts").then((r) => { setRows(r); setFailed(false); }).catch(() => { setRows([]); setFailed(true); });
  useEffect(() => { load(); }, []);
  const shown = (rows || []).filter((c) => filter === "all" || c.state === filter);

  return (
    <div>
      <PageHeader eyebrow="Buyer" title="Rate contracts"
        desc="Contracts from the register (as at its last update) plus signed contracts added since. A contract is used only while it is valid, its supplier is Active and its ceiling has room."
        actions={<Button variant="primary" onClick={() => setAdd(true)} icon={<FilePlus2 className="h-4 w-4" />}>Add contract</Button>} />
      <div className="mb-3 flex items-center gap-3">
        <Tabs value={filter} onChange={setFilter} items={[
          { value: "all", label: "All", count: rows?.length }, { value: "active", label: "Active today", count: rows?.filter((r) => r.state === "active").length },
          { value: "upcoming", label: "Upcoming", count: rows?.filter((r) => r.state === "upcoming").length }, { value: "expired", label: "Expired", count: rows?.filter((r) => r.state === "expired").length }]} />
      </div>
      {rows === null ? <Skeleton className="h-64" /> : shown.length === 0 ? (
        <Card><Empty icon={<FileText className="h-5 w-5" />}
          title={failed ? "Could not load contracts" : filter === "all" ? "No rate contracts yet" : `No ${filter} contracts`}
          desc={failed ? "The server did not respond. Check that the backend is running, then try again." : filter === "all" ? "Add a signed contract to let the engine price against it." : "Switch to another tab to see the rest."}
          action={failed ? <Button size="sm" onClick={load}>Retry</Button> : filter === "all" ? <Button size="sm" variant="primary" onClick={() => setAdd(true)} icon={<FilePlus2 className="h-4 w-4" />}>Add contract</Button> : undefined} /></Card>
      ) : (
        <div className="space-y-2">
          {shown.map((c, i) => {
            const used = c.value_cap > 0 ? (c.consumed_value / c.value_cap) * 100 : 0;
            const open = openId === c.contract_id;
            return (
              <motion.div key={c.contract_id} {...stagger(i)}>
                <Card className={cx("overflow-hidden transition-colors", open && "border-accent/40")}>
                  <button aria-expanded={open} onClick={() => setOpenId(open ? null : c.contract_id)} className="grid w-full grid-cols-2 items-center gap-4 px-4 py-3 text-left md:grid-cols-[130px_minmax(0,1fr)_200px_220px_110px_20px]">
                    <div><Mono className="text-ink">{c.contract_id}</Mono><div className="mt-0.5"><SourceBadge s={c.source} /></div></div>
                    <div className="min-w-0">
                      <div className="truncate text-[14px] font-medium">{c.supplier_name}</div>
                      <div className="flex items-center gap-1.5 text-[12px] text-muted"><Mono>{c.supplier_id}</Mono>
                        {c.supplier_status !== "Active" && <Badge tone="bad"><AlertTriangle className="h-3 w-3" />{c.supplier_status} — not used</Badge>}
                        <span>· {c.lines.length} item{c.lines.length > 1 ? "s" : ""}</span></div>
                    </div>
                    <div className="text-[12.5px]"><StateBadge s={c.state} /><div className="mt-1 text-muted">{fmtDate(c.start_date)} → {fmtDate(c.end_date)}</div></div>
                    <div>
                      <div className="flex justify-between text-[12px]"><span className="text-muted">ceiling used</span><span className="tabular">{compactInr(c.consumed_value)} / {compactInr(c.value_cap)}</span></div>
                      <Progress value={used} tone={used > 90 ? "bad" : used > 70 ? "warn" : "accent"} className="mt-1.5" />
                    </div>
                    <div className="text-right"><div className="text-[11px] text-muted">left</div><div className={cx("font-mono text-[13px] tabular", used > 90 && "text-bad")}>{compactInr(c.ceiling_left)}</div></div>
                    <ChevronDown className={cx("hidden h-4 w-4 text-faint transition-transform md:block", open && "rotate-180")} />
                  </button>
                  <AnimatePresence>
                    {open && (
                      <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden border-t border-line">
                        <div className="p-4">
                          <table className="w-full text-[13px]">
                            <thead className="text-left text-[11px] text-faint"><tr><th className="pb-1.5 font-medium">Item</th><th className="pb-1.5 font-medium">Description</th><th className="pb-1.5 font-medium">UoM</th><th className="pb-1.5 text-right font-medium">Rate</th></tr></thead>
                            <tbody className="divide-y divide-line">{c.lines.map((l: any) => <tr key={l.item_code}><td className="py-1.5 font-mono">{l.item_code}</td><td className="py-1.5">{l.description}</td><td className="py-1.5 text-muted">{l.uom}</td><td className="py-1.5 text-right font-mono tabular">{inr(l.rate, 2)}</td></tr>)}</tbody>
                          </table>
                          <div className="mt-3 flex items-center justify-between text-[12px] text-muted">
                            <span>Consumed in register {inr(c.consumed_value)}{c.source !== "register" ? " (signed after the register update, starts at zero)" : ""} · added by {c.created_by}</span>
                            {c.source !== "register" && <Button size="sm" variant="danger" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={async () => { try { await api.del(`/api/contracts/${c.contract_id}`); toast.success("Contract removed"); load(); } catch (e: any) { toast.error(e.message); } }}>Remove</Button>}
                          </div>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </Card>
              </motion.div>
            );
          })}
        </div>
      )}
      <AddContract open={add} onClose={() => setAdd(false)} onSaved={() => { setAdd(false); load(); }} />
    </div>
  );
}

function SourceBadge({ s }: { s: string }) {
  return s === "pdf" ? <Badge tone="vio"><FileText className="h-3 w-3" />signed PDF</Badge> : s === "manual" ? <Badge tone="info">manual</Badge> : <Badge>register</Badge>;
}
function StateBadge({ s }: { s: string }) {
  return s === "active" ? <Badge tone="ok" dot>active</Badge> : s === "upcoming" ? <Badge tone="info" dot>upcoming</Badge> : <Badge tone="muted">expired</Badge>;
}

function AddContract({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const [step, setStep] = useState<"choose" | "form">("choose");
  const [c, setC] = useState<any>(blank);
  const [busy, setBusy] = useState(false);
  const [sups, setSups] = useState<any[]>([]);
  const [items, setItems] = useState<any[]>([]);
  useEffect(() => { if (open) { setStep("choose"); setC(blank); api.get("/api/suppliers").then(setSups); api.get("/api/items").then(setItems); } }, [open]);

  const extract = async (files: File[]) => {
    setBusy(true);
    try {
      const fd = new FormData(); fd.append("file", files[0]);
      const r = await api.upload("/api/contracts/extract", fd);
      setC({ ...blank, ...r, lines: r.lines.length ? r.lines : blank.lines, source: "pdf" });
      setStep("form");
      toast.success(`Read ${r.contract_id || "contract"}: ${r.lines.length} item line(s)`, { description: r.warnings.length ? "Check the highlighted points before saving." : "Review and save." });
    } catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  };
  const save = async () => {
    setBusy(true);
    try {
      await api.post("/api/contracts", { ...c, value_cap: Number(c.value_cap), consumed_value: Number(c.consumed_value || 0), lines: c.lines.filter((l: any) => l.item_code).map((l: any) => ({ ...l, rate: Number(l.rate) })) });
      toast.success(`${c.contract_id} saved — decisions now consider it`); onSaved();
    } catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  };
  const set = (k: string, v: any) => setC((p: any) => ({ ...p, [k]: v }));
  const setLine = (i: number, k: string, v: any) => setC((p: any) => ({ ...p, lines: p.lines.map((l: any, j: number) => (j === i ? { ...l, [k]: v } : l)) }));

  return (
    <Modal open={open} onClose={onClose} title="Add a rate contract" wide footer={step === "form" ? <><Button variant="ghost" onClick={() => setStep("choose")}>Back</Button><Button variant="primary" loading={busy} onClick={save}>Save contract</Button></> : undefined}>
      {step === "choose" ? (
        <div className="space-y-4">
          <Dropzone onFiles={extract} accept=".pdf" busy={busy} label="Drop the signed contract PDF" sub="Contract number, supplier, validity, ceiling and the Schedule A rates are read automatically." />
          <div className="text-center text-[12px] text-faint">or</div>
          <Button className="w-full" onClick={() => setStep("form")} icon={<Plus className="h-4 w-4" />}>Enter manually</Button>
        </div>
      ) : (
        <div className="space-y-3">
          {c.warnings?.length > 0 && <div className="rounded-lg border border-warn/30 bg-warn/5 p-3 text-[12.5px]">{c.warnings.map((w: string) => <div key={w}>• {w}</div>)}</div>}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Contract number"><input value={c.contract_id || ""} onChange={(e) => set("contract_id", e.target.value.toUpperCase())} className={inputCls} placeholder="RC-2026-031" /></Field>
            <Field label="Supplier">
              <select value={c.supplier_id || ""} onChange={(e) => set("supplier_id", e.target.value)} className={inputCls}>
                <option value="">Choose…</option>
                {sups.map((s) => <option key={s.supplier_id} value={s.supplier_id}>{s.supplier_id} · {s.name}{s.status !== "Active" ? ` (${s.status})` : ""}</option>)}
              </select>
            </Field>
            <Field label="Valid from"><input type="date" value={c.start_date || ""} onChange={(e) => set("start_date", e.target.value)} className={inputCls} /></Field>
            <Field label="Valid to (inclusive)"><input type="date" value={c.end_date || ""} onChange={(e) => set("end_date", e.target.value)} className={inputCls} /></Field>
            <Field label="Value ceiling (₹, excl. GST)" hint={c.value_cap ? inr(c.value_cap) : undefined}><input value={c.value_cap ?? ""} onChange={(e) => set("value_cap", e.target.value)} className={inputCls} inputMode="decimal" /></Field>
            <Field label="Already consumed (₹)" hint="Zero for contracts signed after the register update."><input value={c.consumed_value ?? 0} onChange={(e) => set("consumed_value", e.target.value)} className={inputCls} inputMode="decimal" /></Field>
          </div>
          <div>
            <div className="mb-1.5 flex items-center justify-between"><span className="text-[12px] font-medium text-muted">Schedule A — items and rates</span>
              <Button size="sm" variant="ghost" onClick={() => set("lines", [...c.lines, { item_code: "", rate: "" }])} icon={<Plus className="h-3.5 w-3.5" />}>Add line</Button></div>
            <div className="space-y-2">
              {c.lines.map((l: any, i: number) => (
                <div key={i} className="grid grid-cols-[minmax(0,1fr)_140px_32px] gap-2">
                  <select value={l.item_code} onChange={(e) => setLine(i, "item_code", e.target.value)} aria-label={`Line ${i + 1} item`} className={inputCls}>
                    <option value="">Item…</option>
                    {items.map((it) => <option key={it.item_code} value={it.item_code}>{it.item_code} · {it.description} ({it.uom})</option>)}
                  </select>
                  <input value={l.rate} onChange={(e) => setLine(i, "rate", e.target.value)} className={inputCls} placeholder="Rate ₹" aria-label={`Line ${i + 1} rate (₹)`} inputMode="decimal" />
                  <button onClick={() => set("lines", c.lines.filter((_: any, j: number) => j !== i))} className="grid place-items-center rounded-lg text-muted hover:bg-bad/10 hover:text-bad" aria-label={`Remove line ${i + 1}`}><Trash2 className="h-4 w-4" /></button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
