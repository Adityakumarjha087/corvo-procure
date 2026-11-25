import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle, BadgeCheck, Ban, Check, ChevronRight, Download, FileSpreadsheet, Filter, History, Layers, PenLine, RefreshCcw, Scale, Search, Upload, Workflow,
} from "lucide-react";
import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useHealth } from "../components/Layout";
import {
  AnimatedNumber, Badge, Button, Card, Drawer, Dropzone, Empty, Field, Modal, Mono, PageHeader, Progress, RouteBadge, Skeleton, Tabs, cx, inputCls, stagger,
} from "../components/ui";
import { api } from "../lib/api";
import { compactInr, fmtDate, fmtDateTime, inr, num, routeInfo } from "../lib/format";

type Work = { id: string; kind: "PO" | "REQ"; route: string; supplier?: string; supplierName?: string; plant: string; value: number; items: string[]; reqs: any[]; date: string; status: string; emergency: boolean; decision: string };

export default function Workspace() {
  const { runId } = useParams();
  const nav = useNavigate();
  const { health, refresh } = useHealth();
  const [runs, setRuns] = useState<any[] | null>(null);
  const [run, setRun] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<"review" | "po" | "sourcing" | "np" | "lines">("review");
  const [q, setQ] = useState("");
  const [routeF, setRouteF] = useState<string>("");
  const [open, setOpen] = useState<Work | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadRuns = () => api.get("/api/runs").then((r) => { setRuns(r); return r; });
  const loadRun = (id: number | string) => { setLoading(true); return api.get(`/api/runs/${id}`).then(setRun).finally(() => setLoading(false)); };

  const reload = () => {
    setLoadError(null);
    loadRuns().then((r) => {
      const id = runId || r[0]?.id;
      if (id) return loadRun(id); else setRun(null);
    }).catch((e: any) => setLoadError(e?.message || "Request failed"));
  };
  useEffect(() => { reload(); }, [runId]);

  const work: Work[] = useMemo(() => {
    if (!run) return [];
    const st = run.state || {};
    const items: Work[] = [];
    for (const po of run.purchase_orders) {
      const reqs = run.requirements.filter((r: any) => po.group_ids.includes(r.group_id));
      items.push({ id: po.po_id, kind: "PO", route: po.route, supplier: po.supplier_id, supplierName: po.supplier_name, plant: po.plant, value: reqs.reduce((a: number, r: any) => a + (r.value || 0), 0),
        items: reqs.map((r: any) => r.item_code), reqs, date: reqs[0]?.requirement_date, status: st[po.po_id]?.status || "pending", emergency: reqs.some((r: any) => r.is_emergency), decision: "PO" });
    }
    for (const r of run.requirements.filter((r: any) => r.decision !== "PO")) {
      items.push({ id: r.group_id, kind: "REQ", route: st[r.group_id]?.override?.route || r.route, plant: r.plant, value: r.value || 0, items: [r.item_code || "NEW"], reqs: [r], date: r.requirement_date,
        status: st[r.group_id]?.status || "pending", emergency: r.is_emergency, decision: r.decision });
    }
    return items.sort((a, b) => (a.date < b.date ? -1 : 1));
  }, [run]);

  const npRows = useMemo(() => (run?.rows || []).filter((r: any) => r.route === "NOT_PROCESSED"), [run]);
  const filtered = work.filter((w) => {
    if (view === "review" && w.status === "approved") return false;
    if (view === "po" && w.kind !== "PO") return false;
    if (view === "sourcing" && w.kind !== "REQ") return false;
    if (routeF && w.route !== routeF) return false;
    if (q) {
      const s = q.toLowerCase();
      const hay = [w.id, w.supplier, w.supplierName, w.plant, ...w.items, ...w.reqs.flatMap((r: any) => [r.group_id, ...r.lines.map((l: any) => `${l.pr_no} ${l.description}`)])].join(" ").toLowerCase();
      if (!hay.includes(s)) return false;
    }
    return true;
  });
  const routesPresent = Array.from(new Set(work.map((w) => w.route)));

  const processInbox = async () => {
    setBusy(true);
    try { const r = await api.post("/api/inbox/process"); toast.success(`Processed ${r.summary.lines} chat PR line(s)`); refresh(); nav(`/workspace/${r.run_id}`); }
    catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  };
  const reprocess = async () => {
    if (!run) return;
    setBusy(true);
    try { const r = await api.post(`/api/runs/${run.id}/reprocess`); toast.success("Reprocessed with the current approved policy versions"); nav(`/workspace/${r.run_id}`); }
    catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  };
  const exportCsv = async (withOverrides = false) => {
    try { const n = await api.download(`/api/runs/${run.id}/export.csv${withOverrides ? "?with_overrides=true" : ""}`, `decisions_run${run.id}.csv`); toast.success(`Downloaded ${n}`); }
    catch (e: any) { toast.error(e.message); }
  };

  const pct = run ? (run.progress.approved / Math.max(1, run.progress.work_items)) * 100 : 0;

  return (
    <div>
      <PageHeader eyebrow="Buyer" title="Buyer workspace"
        desc="Each card is one purchase order or sourcing request, decided by the policy. Open it to see why, then approve or override."
        actions={<>
          {(health?.counts.open_prs ?? 0) > 0 && <Button variant="subtle" loading={busy} onClick={processInbox} icon={<Workflow className="h-4 w-4" />}>Process {health?.counts.open_prs} chat PR(s)</Button>}
          {run && <Button onClick={() => exportCsv(false)} icon={<Download className="h-4 w-4" />}>Export CSV</Button>}
          <Button variant={run ? "secondary" : "primary"} onClick={() => setUploadOpen(true)} icon={<Upload className="h-4 w-4" />}>Upload PR batch</Button>
        </>} />

      {loadError ? (
        <Card className="p-5"><div role="alert" className="text-[13px] text-bad">Couldn't load the buyer workspace ({loadError}). <button className="text-accent underline" onClick={reload}>Try again</button></div></Card>
      ) : runs === null ? <Skeleton className="h-40" /> : runs.length === 0 ? (
        <Card><UploadPanel onDone={(id) => { refresh(); nav(`/workspace/${id}`); }} /></Card>
      ) : (
        <>
          <Card className="mb-4 p-4">
            <div className="flex flex-wrap items-center gap-3">
              <select value={run?.id || ""} onChange={(e) => nav(`/workspace/${e.target.value}`)} className={cx(inputCls, "max-w-[340px]")} aria-label="Choose a run">
                {runs.map((r) => <option key={r.id} value={r.id}>#{r.id} · {r.name} · {fmtDateTime(r.created_at)}</option>)}
              </select>
              {run && <>
                <Badge tone="accent"><Scale className="h-3 w-3" /> policy {run.policy_versions.map((v: string) => `v${v}`).join(" + ") || "—"}</Badge>
                <Badge>{run.mode === "latest" ? "latest version for all lines" : "version by requirement date"}</Badge>
                <span className="text-[12px] text-muted">by {run.created_by}</span>
                <div className="flex flex-wrap items-center gap-2 md:ml-auto">
                  <Button size="sm" variant="ghost" loading={busy} onClick={reprocess} icon={<RefreshCcw className="h-3.5 w-3.5" />}>Reprocess with current policy</Button>
                  <Button size="sm" variant="ghost" onClick={() => exportCsv(true)} icon={<Download className="h-3.5 w-3.5" />}>CSV incl. overrides</Button>
                </div>
              </>}
            </div>
            {run && (
              <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-6">
                <Mini label="PR lines" v={run.summary.lines} />
                <Mini label="Requirements" v={run.summary.requirements} />
                <Mini label="Purchase orders" v={run.summary.purchase_orders} />
                <Mini label="Sourcing requests" v={work.filter((w) => w.kind === "REQ").length} />
                <Mini label="Not processed" v={run.summary.not_processed} tone={run.summary.not_processed ? "warn" : undefined} />
                <div>
                  <div className="text-[11px] text-muted">Approved</div>
                  <div className="font-display text-xl font-semibold tabular">{run.progress.approved}<span className="text-sm text-faint">/{run.progress.work_items}</span></div>
                  <Progress value={pct} className="mt-1.5" tone="ok" />
                </div>
              </div>
            )}
          </Card>

          {loading && !run ? <Skeleton className="h-64" /> : run && (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <Tabs value={view} onChange={setView} items={[
                  { value: "review", label: "To review", count: work.filter((w) => w.status !== "approved").length },
                  { value: "po", label: "Purchase orders", count: work.filter((w) => w.kind === "PO").length },
                  { value: "sourcing", label: "Sourcing", count: work.filter((w) => w.kind === "REQ").length },
                  { value: "np", label: "Not processed", count: npRows.length },
                  { value: "lines", label: "All lines", count: run.rows.length },
                ]} />
                <div className="relative ml-auto">
                  <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-faint" />
                  <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="PR no, item, supplier…" className={cx(inputCls, "w-64 pl-8")} />
                </div>
              </div>
              {view !== "np" && view !== "lines" && (
                <div className="mb-3 flex flex-wrap items-center gap-1.5">
                  <Filter className="h-3.5 w-3.5 text-faint" />
                  <button onClick={() => setRouteF("")} className={cx("rounded-full border px-2.5 py-0.5 text-[12px]", !routeF ? "border-accent text-accent" : "border-line text-muted")}>All routes</button>
                  {routesPresent.map((r) => (
                    <button key={r} onClick={() => setRouteF(r === routeF ? "" : r)} className={cx("rounded-full border px-2.5 py-0.5 text-[12px]", routeF === r ? "border-accent text-accent" : "border-line text-muted hover:text-ink")}>{routeInfo(r).label}</button>
                  ))}
                </div>
              )}

              {view === "np" ? <NotProcessed rows={npRows} /> : view === "lines" ? <LinesTable rows={run.rows} q={q} /> : (
                <Card className="overflow-hidden">
                  <div className="hidden grid-cols-[110px_150px_minmax(0,1fr)_80px_130px_110px_28px] gap-3 border-b border-line bg-panel2/60 px-4 py-2 text-[11px] font-medium uppercase tracking-wider text-faint md:grid">
                    <span>Work item</span><span>Route</span><span>Items · supplier</span><span>Plant</span><span className="text-right">Value</span><span>Status</span><span />
                  </div>
                  {filtered.length === 0 && <Empty icon={<BadgeCheck className="h-5 w-5" />} title={view === "review" ? "All caught up" : "Nothing here"} desc={view === "review" ? "Every decision in this run is approved." : "Try another filter."} />}
                  <div className="divide-y divide-line">
                    {filtered.map((w, i) => (
                      <motion.button key={w.id} {...stagger(i)} onClick={() => setOpen(w)}
                        className="grid w-full grid-cols-2 items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-panel2/70 md:grid-cols-[110px_150px_minmax(0,1fr)_80px_130px_110px_28px]">
                        <span className="flex items-center gap-1.5"><Mono className="text-ink">{w.id}</Mono>{w.emergency && <AlertTriangle className="h-3.5 w-3.5 text-bad" />}</span>
                        <span><RouteBadge route={w.route} /></span>
                        <span className="col-span-2 min-w-0 md:col-span-1">
                          <span className="block truncate text-[13.5px]">{w.reqs.map((r: any) => r.item_code ? `${r.item_code}` : "NEW").join(", ")} <span className="text-muted">· {w.reqs[0]?.lines[0]?.description}</span></span>
                          <span className="block truncate text-[12px] text-muted">
                            {w.kind === "PO" ? `${w.supplier} ${w.supplierName || ""} · ${w.reqs.length} requirement${w.reqs.length > 1 ? "s" : ""}` : (w.reqs[0].suggestions || []).map((s: any) => s.supplier_id).join(", ") || "buyer to find suppliers"}
                          </span>
                        </span>
                        <span className="text-[13px] text-muted">{w.plant}</span>
                        <span className="text-right font-mono text-[13px] tabular">{inr(w.value)}</span>
                        <span><StatusBadge s={w.status} /></span>
                        <ChevronRight className="hidden h-4 w-4 text-faint md:block" />
                      </motion.button>
                    ))}
                  </div>
                </Card>
              )}
            </>
          )}
        </>
      )}

      <Drawer open={!!open} onClose={() => setOpen(null)} width={760}>
        {open && run && <WorkDetail w={open} run={run} onChanged={async () => { await loadRun(run.id); loadRuns(); setOpen(null); }} />}
      </Drawer>
      <Modal open={uploadOpen} onClose={() => setUploadOpen(false)} title="Process a PR batch" wide>
        <UploadPanel onDone={(id) => { setUploadOpen(false); refresh(); nav(`/workspace/${id}`); }} />
      </Modal>
    </div>
  );
}

function Mini({ label, v, tone }: { label: string; v: number; tone?: string }) {
  return <div><div className="text-[11px] text-muted">{label}</div><div className={cx("font-display text-xl font-semibold", tone === "warn" && "text-warn")}><AnimatedNumber value={v} /></div></div>;
}
function StatusBadge({ s }: { s: string }) {
  if (s === "approved") return <Badge tone="ok"><Check className="h-3 w-3" />Approved</Badge>;
  if (s === "overridden") return <Badge tone="warn"><PenLine className="h-3 w-3" />Overridden</Badge>;
  if (s === "rejected") return <Badge tone="bad">Rejected</Badge>;
  return <Badge tone="muted">To review</Badge>;
}

function UploadPanel({ onDone }: { onDone: (runId: number) => void }) {
  const [mode, setMode] = useState<"by_date" | "latest">("by_date");
  const [busy, setBusy] = useState(false);
  const go = async (files: File[]) => {
    const f = files[0];
    if (!f.name.toLowerCase().endsWith(".csv")) { toast.error("Upload the PR batch as a .csv file."); return; }
    setBusy(true);
    try {
      const fd = new FormData(); fd.append("file", f);
      const r = await api.upload(`/api/process-batch?mode=${mode}&name=${encodeURIComponent(f.name)}`, fd);
      toast.success(`Decided ${r.summary.lines} lines → ${r.summary.requirements} requirements, ${r.summary.purchase_orders} POs`);
      onDone(r.run_id);
    } catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  };
  return (
    <div className="space-y-4 p-1">
      <Dropzone onFiles={go} accept=".csv" busy={busy} label={busy ? "Deciding every line…" : "Drop the PR batch CSV here, or click to choose"} sub="Columns: pr_no, pr_line, created_at, requester, department, plant, item_code, description, quantity, uom, estimated_unit_price, need_by_date, urgency" />
      <div className="grid gap-2 sm:grid-cols-2">
        {([["by_date", "Version by requirement date", "Each requirement uses the policy version in force on its date (recommended)."],
          ["latest", "Latest approved version for all", "Ignore effective dates and apply the newest approved version to every line."]] as const).map(([v, t, d]) => (
          <button key={v} onClick={() => setMode(v)} className={cx("rounded-xl border p-3 text-left transition", mode === v ? "border-accent bg-accent/5" : "border-line hover:border-accent/40")}>
            <div className="flex items-center gap-2 text-[13.5px] font-medium"><span className={cx("h-3.5 w-3.5 rounded-full border-2", mode === v ? "border-accent bg-accent" : "border-line")} />{t}</div>
            <div className="mt-1 text-[12px] text-muted">{d}</div>
          </button>
        ))}
      </div>
      <div className="rounded-lg border border-line bg-panel2/60 p-3 text-[12px] text-muted">
        Automations can call the same engine: <Mono>POST /api/process-batch</Mono> with the CSV as the <Mono>file</Mono> field or the raw body.
      </div>
    </div>
  );
}

function NotProcessed({ rows }: { rows: any[] }) {
  if (!rows.length) return <Card><Empty icon={<BadgeCheck className="h-5 w-5" />} title="Every line was processed" /></Card>;
  return (
    <Card className="divide-y divide-line">
      {rows.map((r, i) => (
        <motion.div key={r.pr_no + r.pr_line} {...stagger(i)} className="flex items-start gap-3 px-4 py-3">
          <Ban className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
          <div><Mono>{r.pr_no}/{r.pr_line}</Mono><div className="text-[13px] text-muted">{r.reason}</div></div>
        </motion.div>
      ))}
    </Card>
  );
}

function LinesTable({ rows, q }: { rows: any[]; q: string }) {
  const f = rows.filter((r) => !q || JSON.stringify(r).toLowerCase().includes(q.toLowerCase()));
  return (
    <Card className="overflow-x-auto">
      <table className="w-full min-w-[1100px] text-[12.5px]">
        <thead className="bg-panel2/60 text-left text-[11px] uppercase tracking-wider text-faint">
          <tr>{["PR / line", "Item", "Group", "PO", "Route", "Supplier", "Unit price", "Group value", "Suggested", "Ver."].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-line">
          {f.map((r) => (
            <tr key={r.pr_no + r.pr_line} className="hover:bg-panel2/50" title={r.reason}>
              <td className="px-3 py-1.5 font-mono">{r.pr_no}/{r.pr_line}</td>
              <td className="px-3 py-1.5 font-mono">{r.resolved_item_code}</td>
              <td className="px-3 py-1.5 font-mono text-muted">{r.group_id}</td>
              <td className="px-3 py-1.5 font-mono text-muted">{r.po_id}</td>
              <td className="px-3 py-1.5"><RouteBadge route={r.route} /></td>
              <td className="px-3 py-1.5 font-mono">{r.supplier_id}</td>
              <td className="px-3 py-1.5 text-right font-mono tabular">{r.unit_price === "" ? "" : num(r.unit_price)}</td>
              <td className="px-3 py-1.5 text-right font-mono tabular">{r.group_value_inr === "" ? "" : inr(r.group_value_inr)}</td>
              <td className="px-3 py-1.5 font-mono text-muted">{r.suggested_supplier_ids}</td>
              <td className="px-3 py-1.5">{r.policy_version}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function WorkDetail({ w, run, onChanged }: { w: Work; run: any; onChanged: () => void }) {
  const st = run.state?.[w.id];
  const [ovOpen, setOvOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const approved = st?.status === "approved";
  const isPO = w.kind === "PO";
  const approve = async () => {
    setBusy(true);
    try { const r = await api.post(`/api/runs/${run.id}/approve`, { target: w.id }); toast.success(`${r.doc_no} created`, { description: isPO ? "Purchase order issued" : `${routeInfo(w.route).label} raised` }); onChanged(); }
    catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  };
  const actionLabel = isPO ? "Approve & create PO" : w.route === "NEW_ITEM_SOURCING" ? "Approve & start new-item sourcing" : w.route === "CAPEX_SOURCING" ? "Approve & send for capex sourcing" : `Approve & raise ${routeInfo(w.route).label}`;

  return (
    <div>
      <div className="sticky top-0 z-10 border-b border-line bg-panel/95 px-6 py-4 backdrop-blur">
        <div className="flex flex-wrap items-center gap-2">
          <Mono className="text-base text-ink">{w.id}</Mono>
          <RouteBadge route={w.route} />
          <StatusBadge s={st?.status || "pending"} />
          {w.emergency && <Badge tone="bad"><AlertTriangle className="h-3 w-3" />Emergency</Badge>}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {approved ? <Badge tone="ok" className="py-1 text-[12.5px]"><BadgeCheck className="h-3.5 w-3.5" /> {st.doc_no} created</Badge> : (
            <>
              <Button variant="primary" loading={busy} onClick={approve} icon={<Check className="h-4 w-4" />}>{actionLabel}</Button>
              {!isPO || w.reqs.length === 1 ? <Button onClick={() => setOvOpen(true)} icon={<PenLine className="h-4 w-4" />}>Override</Button> : null}
            </>
          )}
        </div>
      </div>

      <div className="space-y-5 px-6 py-5">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Fact label={isPO ? "PO value" : "Requirement value"} value={inr(w.value)} />
          <Fact label="Plant" value={w.plant} />
          {isPO ? <Fact label="Supplier" value={<span><Mono>{w.supplier}</Mono> <span className="text-[12px] text-muted">{w.supplierName}</span></span>} />
                : <Fact label="Suggested" value={(w.reqs[0].suggestions || []).length ? `${w.reqs[0].suggestions.length} suppliers` : "none (buyer finds)"} />}
          <Fact label="Requirement date" value={fmtDateTime(w.date)} />
        </div>

        {st?.override && (
          <div className="rounded-xl border border-warn/30 bg-warn/5 p-3 text-[13px]">
            <div className="font-medium text-warn">Overridden by {st.override.actor}</div>
            <div className="text-muted">{st.override.route} {st.override.supplier_id ? `· ${st.override.supplier_id} @ ${inr(st.override.unit_price, 2)}` : ""} {st.override.suggested_supplier_ids ? `· ${st.override.suggested_supplier_ids}` : ""}</div>
            <div className="mt-1">“{st.override.comment}”</div>
          </div>
        )}

        {w.reqs.map((r: any, idx: number) => <RequirementBlock key={r.group_id} r={r} idx={idx} total={w.reqs.length} />)}

        {st?.history?.length > 0 && (
          <Section icon={<History className="h-4 w-4" />} title="Activity">
            <div className="space-y-2">
              {st.history.map((h: any, i: number) => (
                <div key={i} className="flex items-start gap-3 text-[13px]">
                  <span className="w-28 shrink-0 text-faint">{fmtDateTime(h.at)}</span>
                  <span><b className="font-medium">{h.actor}</b> {h.kind === "approve" ? `approved → ${h.payload.doc_no}` : h.kind}{h.comment ? ` — “${h.comment}”` : ""}</span>
                </div>
              ))}
            </div>
          </Section>
        )}
      </div>
      <OverrideModal open={ovOpen} onClose={() => setOvOpen(false)} run={run} req={w.reqs[0]} onDone={onChanged} />
    </div>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="rounded-xl border border-line bg-panel2/50 p-3"><div className="text-[11px] text-muted">{label}</div><div className="mt-0.5 text-[14px] font-medium">{value}</div></div>;
}
function Section({ icon, title, children, right }: { icon: React.ReactNode; title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between"><div className="flex items-center gap-2 text-[13px] font-semibold"><span className="text-accent">{icon}</span>{title}</div>{right}</div>
      {children}
    </div>
  );
}

function RequirementBlock({ r, idx, total }: { r: any; idx: number; total: number }) {
  const [showPref, setShowPref] = useState(false);
  return (
    <div className="rounded-2xl border border-line">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-panel2/40 px-4 py-2.5">
        <div className="flex items-center gap-2 text-[13px]">
          <Layers className="h-4 w-4 text-muted" />
          <Mono>{r.group_id}</Mono>
          {total > 1 && <span className="text-faint">({idx + 1} of {total} on this PO)</span>}
          <span className="font-medium">{r.item_code || "NEW"}</span>
          <span className="text-muted">{num(r.quantity)} {r.lines[0]?.uom}</span>
        </div>
        <div className="flex items-center gap-2 text-[12px]">
          {r.decision === "PO" && <span className="font-mono">{r.supplier_id} @ {inr(r.unit_price, 2)}</span>}
          <Badge tone="accent">v{r.policy_version} · §{r.rule_id}</Badge>
        </div>
      </div>
      <div className="space-y-4 p-4">
        <div className="rounded-xl border border-accent/20 bg-accent/[0.04] p-3 text-[13px] leading-relaxed">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-accent">Why</div>
          {r.reason}
        </div>

        <ol className="relative ml-2 space-y-3 border-l border-line pl-5">
          {r.trace.map((t: any, i: number) => (
            <motion.li key={i} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }} className="relative">
              <span className="absolute -left-[27px] top-0.5 grid h-3.5 w-3.5 place-items-center rounded-full border-2 border-accent bg-panel" />
              <div className="flex items-center gap-2 text-[13px] font-medium"><Badge tone="accent">§{t.clause}</Badge>{t.title}</div>
              <div className="mt-0.5 text-[12.5px] text-muted">{t.detail}</div>
            </motion.li>
          ))}
        </ol>

        {r.suggestions?.length > 0 && (
          <Section icon={<BadgeCheck className="h-4 w-4" />} title="Suggested suppliers">
            <div className="flex flex-wrap gap-2">
              {r.suggestions.map((s: any, i: number) => (
                <div key={s.supplier_id} className="rounded-lg border border-line bg-panel2/50 px-2.5 py-1.5 text-[12.5px]">
                  <span className="mr-1 text-faint">{i + 1}.</span><Mono>{s.supplier_id}</Mono> {s.name}
                  <span className="ml-1.5 text-[11px] text-muted">{s.source === "preferred" ? `preferred #${s.rank}` : "category top-up"}</span>
                </div>
              ))}
            </div>
          </Section>
        )}

        <Section icon={<FileSpreadsheet className="h-4 w-4" />} title={`PR lines (${r.lines.length})`}>
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full text-[12.5px]">
              <thead className="bg-panel2/60 text-left text-[11px] text-faint"><tr>{["PR", "Created", "Requester", "As typed", "Qty", "Need by", "Urgency"].map((h) => <th key={h} className="px-2.5 py-1.5 font-medium">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-line">
                {r.lines.map((l: any) => (
                  <tr key={l.pr_no + l.pr_line}>
                    <td className="px-2.5 py-1.5 font-mono">{l.pr_no}/{l.pr_line}</td><td className="px-2.5 py-1.5">{fmtDateTime(l.created_at)}</td>
                    <td className="px-2.5 py-1.5">{l.requester}<span className="text-faint"> · {l.department}</span></td>
                    <td className="px-2.5 py-1.5 text-muted">{l.description}</td><td className="px-2.5 py-1.5 tabular">{num(l.quantity)} {l.uom}</td>
                    <td className="px-2.5 py-1.5">{fmtDate(l.need_by_date)}</td><td className="px-2.5 py-1.5">{l.urgency === "Emergency" ? <Badge tone="bad">Emergency</Badge> : "Normal"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        {r.preferred?.length > 0 && (
          <Section icon={<Scale className="h-4 w-4" />} title="Preferred supplier ranking (§6)" right={<button onClick={() => setShowPref(!showPref)} className="text-[12px] text-accent">{showPref ? "Hide" : "Show"} scores</button>}>
            <AnimatePresence>{showPref && (
              <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                <ScoreTable ranked={r.preferred} />
              </motion.div>
            )}</AnimatePresence>
          </Section>
        )}
      </div>
    </div>
  );
}

export function ScoreTable({ ranked }: { ranked: any[] }) {
  const max = Math.max(...ranked.map((r) => r.score), 0.0001);
  const seg = [["frequency", "bg-accent"], ["recency", "bg-info"], ["contract", "bg-vio"], ["performance", "bg-warn"]] as const;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-3 text-[11px] text-muted">{seg.map(([k, c]) => <span key={k} className="flex items-center gap-1"><span className={cx("h-2 w-2 rounded-sm", c)} />{k}</span>)}</div>
      {ranked.map((r) => (
        <div key={r.supplier_id} className="grid grid-cols-[28px_minmax(0,180px)_minmax(0,1fr)_60px] items-center gap-3 text-[12.5px]">
          <span className="font-display text-base font-semibold text-muted">#{r.rank}</span>
          <span className="min-w-0"><Mono>{r.supplier_id}</Mono> <span className="block truncate text-[11.5px] text-muted">{r.name}</span></span>
          <div>
            <div className="flex h-2.5 overflow-hidden rounded-full bg-panel2">
              {seg.map(([k, c]) => <motion.div key={k} className={c} initial={{ width: 0 }} animate={{ width: `${(r.components[k] / max) * 100}%` }} transition={{ type: "spring", stiffness: 70 }} />)}
            </div>
            <div className="mt-1 text-[11px] text-faint">{r.po_count} POs · last {r.last_po_date ? fmtDate(r.last_po_date) : "never"} · {r.has_contract ? "contract" : "no contract"} · {r.on_time_pct}% on time · Q {r.quality_rating} · ref {inr(r.reference_price, 2)}</div>
          </div>
          <span className="text-right font-mono tabular">{r.score.toFixed(3)}</span>
        </div>
      ))}
    </div>
  );
}

function OverrideModal({ open, onClose, run, req, onDone }: { open: boolean; onClose: () => void; run: any; req: any; onDone: () => void }) {
  const [route, setRoute] = useState(req?.route || "RFQ");
  const [supplier, setSupplier] = useState("");
  const [price, setPrice] = useState("");
  const [sugg, setSugg] = useState("");
  const [comment, setComment] = useState("");
  const [sups, setSups] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { api.get("/api/suppliers").then(setSups); setRoute(req?.route); setSupplier(req?.supplier_id || ""); setPrice(req?.unit_price ? String(req.unit_price) : ""); setSugg((req?.suggestions || []).map((s: any) => s.supplier_id).join(";")); setComment(""); } }, [open]);
  const isPO = route.endsWith("_PO");
  const active = sups.filter((s) => s.status === "Active");
  const submit = async () => {
    setBusy(true);
    try {
      await api.post(`/api/runs/${run.id}/override`, { group_id: req.group_id, route, supplier_id: supplier, unit_price: price, suggested_supplier_ids: sugg, comment });
      toast.success("Override recorded with your reason"); onClose(); onDone();
    } catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title={`Override ${req?.group_id}`} footer={<>
      <Button variant="ghost" onClick={onClose}>Cancel</Button>
      <Button variant="primary" loading={busy} disabled={comment.trim().length < 5} onClick={submit}>Record override</Button></>}>
      <div className="space-y-3">
        <div className="rounded-lg border border-line bg-panel2/50 p-3 text-[12.5px] text-muted">Engine decision: <b className="text-ink">{routeInfo(req?.route || "").label}</b>{req?.supplier_id ? ` · ${req.supplier_id} @ ${inr(req.unit_price, 2)}` : ""}. The original stays on record next to your override (policy 8.1).</div>
        <Field label="New route">
          <select value={route} onChange={(e) => setRoute(e.target.value)} className={inputCls}>
            {["CONTRACT_PO", "SPOT_PO", "EMERGENCY_PO", "RFQ", "RFP", "CAPEX_SOURCING", "NEW_ITEM_SOURCING"].map((r) => <option key={r} value={r}>{routeInfo(r).label}</option>)}
          </select>
        </Field>
        {isPO ? (
          <div className="grid grid-cols-2 gap-3">
            <Field label="Supplier" hint="Only Active suppliers can receive a PO (5.7).">
              <select value={supplier} onChange={(e) => setSupplier(e.target.value)} className={inputCls}>
                <option value="">Choose…</option>
                {active.map((s) => <option key={s.supplier_id} value={s.supplier_id}>{s.supplier_id} · {s.name}</option>)}
              </select>
            </Field>
            <Field label="Unit price (₹)"><input value={price} onChange={(e) => setPrice(e.target.value)} className={inputCls} inputMode="decimal" /></Field>
          </div>
        ) : (
          <Field label="Suggested suppliers" hint="Supplier ids separated by ; — Active suppliers only.">
            <input value={sugg} onChange={(e) => setSugg(e.target.value)} className={inputCls} placeholder="S014;S013;S016" />
          </Field>
        )}
        <Field label="Reason (required)" hint="Kept with the original decision in the audit trail.">
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={3} className={cx(inputCls, "h-auto py-2")} placeholder="e.g. Supplier confirmed it cannot meet the need-by date" />
        </Field>
      </div>
    </Modal>
  );
}
