import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle, ArrowDownUp, Braces, SlidersHorizontal, CheckCircle2, CircleDot, FileUp, GitCompareArrows, Minus, PenLine, Plus, Scale, Sparkles, Wand2, XCircle,
} from "lucide-react";
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { useHealth } from "../components/Layout";
import { Badge, Button, Card, Dropzone, Empty, Field, Modal, Mono, PageHeader, RouteBadge, Skeleton, Tabs, cx, inputCls, stagger } from "../components/ui";
import { api } from "../lib/api";
import { PolicyBuilder } from "./PolicyBuilder";
import { fmtDate, fmtDateTime } from "../lib/format";

const CHANGE_ICON: Record<string, any> = { rule_added: Plus, rule_removed: Minus, rule_changed: PenLine, rule_order: ArrowDownUp, param: CircleDot, meta: Scale };
const CHANGE_TONE: Record<string, string> = { rule_added: "text-ok", rule_removed: "text-bad", rule_changed: "text-warn", rule_order: "text-info", param: "text-accent", meta: "text-muted" };

const EXAMPLES = [
  "From 1 Dec 2026, raise the spot PO limit to ₹3,00,000.",
  "Effective 20 Nov 2026: at Chakan (CHK1), Safety & PPE requirements below ₹50,000 may be bought as a spot PO from the 1st preferred supplier even without purchase history.",
  "Emergency POs now need the item to have been bought in the last 180 days, and the emergency limit is ₹7.5 lakh.",
  "Do not suggest suppliers with on-time delivery below 70% for any sourcing event.",
];

function getPath(o: any, p: string) { return p.split(".").reduce((a, k) => (a == null ? a : a[k]), o); }

export default function PolicyPage() {
  const { health, refresh } = useHealth();
  const [versions, setVersions] = useState<any[] | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [doc, setDoc] = useState<any>(null);
  const [schema, setSchema] = useState<any>(null);
  const [tab, setTab] = useState<"rules" | "params" | "changes" | "json">("rules");
  const [propose, setPropose] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [docError, setDocError] = useState<string | null>(null);

  const load = async (select?: number) => {
    let vs: any[];
    try { vs = await api.get("/api/policies"); } catch (e: any) { setListError(e.message || "Request failed"); return; }
    setListError(null);
    setVersions(vs);
    const target = select ?? sel ?? (vs.find((v: any) => v.status === "draft")?.id || vs.find((v: any) => v.in_force_today)?.id || vs[0]?.id);
    if (target) setSel(target);
  };
  useEffect(() => { load(); api.get("/api/policies/schema").then(setSchema); }, []);
  const loadDoc = (id: number) => {
    setDoc(null); setDocError(null);
    api.get(`/api/policies/${id}`).then((d) => { setDoc(d); if (d.status === "draft") setTab("changes"); }).catch((e: any) => setDocError(e.message || "Request failed"));
  };
  useEffect(() => { if (sel) loadDoc(sel); }, [sel]);

  return (
    <div>
      <PageHeader eyebrow="Procurement" title="Policy studio"
        desc="The decision rules live here as versioned data. Upload an amendment or describe a change; review what will change in plain language; approve it to take effect from its date."
        actions={<Button variant="primary" onClick={() => setPropose(true)} icon={<Wand2 className="h-4 w-4" />}>Propose a change</Button>} />

      <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <Card className="h-fit p-2">
          <div className="px-2 pb-2 pt-1 text-[11px] font-medium uppercase tracking-wider text-faint">Versions</div>
          {listError ? (
            <div role="alert" className="m-2 text-[13px] text-bad">Couldn't load policy versions ({listError}). <button className="text-accent underline" onClick={() => load()}>Try again</button></div>
          ) : versions === null ? <Skeleton className="m-2 h-24" /> : (
            <div className="relative space-y-1">
              {versions.map((v, i) => (
                <motion.button key={v.id} {...stagger(i)} onClick={() => setSel(v.id)} aria-current={sel === v.id ? "true" : undefined}
                  className={cx("relative w-full rounded-lg px-3 py-2.5 text-left transition-colors", sel === v.id ? "bg-panel2" : "hover:bg-panel2/60")}>
                  {sel === v.id && <motion.span layoutId="ver-sel" className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-accent" />}
                  <div className="flex items-center justify-between">
                    <span className="font-display text-[15px] font-semibold">v{v.version}</span>
                    <VerBadge v={v} />
                  </div>
                  <div className="mt-0.5 text-[12px] text-muted">effective {fmtDate(v.effective_from)}</div>
                  <div className="mt-0.5 truncate text-[11.5px] text-faint">{v.source_name || "—"} · {v.created_by}</div>
                </motion.button>
              ))}
            </div>
          )}
        </Card>

        <div className="min-w-0">
          {docError ? (
            <Card className="p-6"><div role="alert" className="text-[13px] text-bad">Couldn't load this version ({docError}). <button className="text-accent underline" onClick={() => sel && loadDoc(sel)}>Try again</button></div></Card>
          ) : !doc ? <Card className="p-6"><Skeleton className="h-6 w-40" /><Skeleton className="mt-4 h-40" /></Card> : (
            <AnimatePresence mode="wait">
              <motion.div key={doc.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                {doc.status === "draft" && <DraftPanel doc={doc} schema={schema} versions={versions || []} onDecided={async (id) => { await load(id); refresh(); setSel(id); api.get(`/api/policies/${id}`).then(setDoc); }} onEdited={setDoc} />}
                <Card className="p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2"><h2 className="text-xl font-semibold">Version {doc.version}</h2><VerBadge v={versions?.find((v) => v.id === doc.id) || doc} /></div>
                      <div className="mt-1 text-[13px] text-muted">{doc.title} · effective {fmtDate(doc.effective_from)}{doc.base_version ? ` · based on v${doc.base_version}` : ""}</div>
                      {doc.decided_by && <div className="mt-0.5 text-[12px] text-faint">{doc.status} by {doc.decided_by} · {fmtDateTime(doc.decided_at)}{doc.decision_comment ? ` — “${doc.decision_comment}”` : ""}</div>}
                    </div>
                    <Tabs value={tab} onChange={setTab} items={[
                      { value: "rules", label: "Rule ladder", count: doc.rules_text.length }, { value: "params", label: "Parameters" },
                      { value: "changes", label: "Changes", count: doc.changes.length }, { value: "json", label: "JSON" }]} />
                  </div>
                  <div className="mt-5">
                    {tab === "rules" && <RuleLadder rules={doc.rules_text} fallback={doc.document.fallback} />}
                    {tab === "params" && schema && <Params doc={doc.document} labels={schema.params} />}
                    {tab === "changes" && <ChangeList changes={doc.changes} />}
                    {tab === "json" && <pre className="max-h-[60vh] overflow-auto rounded-xl border border-line bg-panel2/60 p-4 font-mono text-[12px] leading-relaxed">{JSON.stringify(doc.document, null, 2)}</pre>}
                  </div>
                </Card>
              </motion.div>
            </AnimatePresence>
          )}
        </div>
      </div>

      <ProposeModal open={propose} onClose={() => setPropose(false)} aiOn={!!health?.ai_available} latest={versions?.find((v) => v.latest_approved)} schema={schema}
        onCreated={async (id) => { setPropose(false); await load(id); setSel(id); setTab("changes"); }} />
    </div>
  );
}

function VerBadge({ v }: { v: any }) {
  if (v.status === "draft") return <Badge tone="warn" dot>draft</Badge>;
  if (v.status === "rejected") return <Badge tone="bad">rejected</Badge>;
  if (v.in_force_today) return <Badge tone="ok" dot>in force</Badge>;
  if (v.latest_approved) return <Badge tone="info">scheduled</Badge>;
  return <Badge>approved</Badge>;
}

function RuleLadder({ rules, fallback }: { rules: any[]; fallback?: any }) {
  return (
    <div className="space-y-2">
      <div className="text-[12.5px] text-muted">Rules are checked top to bottom; the first that fits decides the outcome.</div>
      {rules.map((r, i) => (
        <motion.div key={r.id} {...stagger(i)} className={cx("grid grid-cols-[52px_minmax(0,1fr)] gap-3 rounded-xl border border-line bg-panel2/40 p-3 md:grid-cols-[52px_minmax(0,1fr)_260px]", !r.enabled && "opacity-50")}>
          <div className="flex flex-col items-center"><span className="font-mono text-[13px] font-semibold text-accent">{r.id}</span>{i < rules.length - 1 && <span className="mt-1 h-full w-px bg-line" />}</div>
          <div className="min-w-0">
            <div className="text-[14px] font-medium">{r.name}</div>
            <div className="mt-0.5 text-[12.5px] text-muted"><span className="text-faint">when</span> {r.when}</div>
          </div>
          <div className="col-span-2 flex items-center gap-2 md:col-span-1 md:justify-end"><RouteBadge route={r.then.split(" ")[0]} /><span className="text-[12px] text-muted">{r.then.replace(/^\S+\s/, "")}</span></div>
        </motion.div>
      ))}
      {fallback && <div className="rounded-xl border border-dashed border-line p-3 text-[12.5px] text-muted">If no rule fits: <b className="text-ink">{fallback.then?.route}</b> ({fallback.name})</div>}
    </div>
  );
}

function Params({ doc, labels }: { doc: any; labels: Record<string, string> }) {
  const groups: Record<string, [string, string][]> = {};
  Object.entries(labels).forEach(([k, l]) => { const g = k.split(".")[0]; (groups[g] ||= []).push([k, l]); });
  const fmt = (v: any) => v === null || v === undefined ? <span className="text-faint">not set</span> : typeof v === "boolean" ? (v ? "yes" : "no") : Array.isArray(v) ? v.join(", ") : String(v);
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {Object.entries(groups).map(([g, items]) => (
        <div key={g} className="rounded-xl border border-line p-3">
          <div className="mb-2 font-mono text-[11px] uppercase tracking-wider text-accent">{g.replace(/_/g, " ")}</div>
          {items.map(([k, l]) => (
            <div key={k} className="flex justify-between gap-3 border-t border-line py-1.5 text-[12.5px] first:border-t-0">
              <span className="text-muted">{l}</span><span className="text-right font-mono">{fmt(getPath(doc, k))}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function ChangeList({ changes }: { changes: any[] }) {
  if (!changes.length) return <Empty icon={<GitCompareArrows className="h-5 w-5" />} title="No changes" desc="This version is identical to its base." />;
  return (
    <div className="space-y-2">
      {changes.map((c, i) => {
        const Icon = CHANGE_ICON[c.kind] || CircleDot;
        return (
          <motion.div key={i} {...stagger(i)} className="flex items-start gap-3 rounded-xl border border-line bg-panel2/40 p-3">
            <span className={cx("mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-md bg-panel", CHANGE_TONE[c.kind])}><Icon className="h-3.5 w-3.5" /></span>
            <div className="text-[13.5px] leading-relaxed">{c.text}</div>
          </motion.div>
        );
      })}
    </div>
  );
}

function DraftPanel({ doc, schema, versions, onDecided, onEdited }: { doc: any; schema: any; versions: any[]; onDecided: (id: number) => void; onEdited: (d: any) => void }) {
  const [editOpen, setEditOpen] = useState(false);
  const [editBase, setEditBase] = useState<any>(null);
  const [editDoc, setEditDoc] = useState<any>(null);
  const openEditor = async () => {
    const baseRef = versions.find((v: any) => v.version === doc.base_version && v.status === "approved") || versions.find((v: any) => v.latest_approved);
    try {
      const b = baseRef ? (await api.get(`/api/policies/${baseRef.id}`)).document : doc.document;
      setEditBase(b); setEditDoc(JSON.parse(JSON.stringify(doc.document))); setEditOpen(true);
    } catch (e: any) { toast.error(e.message); }
  };
  const saveRules = async () => {
    setBusy("rules");
    try { const d = await api.put(`/api/policies/${doc.id}`, { document: editDoc }); onEdited(d); setImpact(null); setEditOpen(false); toast.success("Draft updated: review the changes again"); }
    catch (e: any) { toast.error(e.message); } finally { setBusy(null); }
  };
  const [impact, setImpact] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [eff, setEff] = useState(doc.effective_from);
  const [ver, setVer] = useState(doc.version);
  const errors = (doc.warnings || []).filter((w: string) => w.startsWith("Error:"));
  const notes = (doc.warnings || []).filter((w: string) => !w.startsWith("Error:"));
  useEffect(() => { setEff(doc.effective_from); setVer(doc.version); setImpact(null); }, [doc.id]);

  const saveMeta = async () => {
    setBusy("meta");
    try { const d = await api.put(`/api/policies/${doc.id}`, { document: { ...doc.document, effective_from: eff, version: ver } }); onEdited(d); toast.success("Draft updated"); }
    catch (e: any) { toast.error(e.message); } finally { setBusy(null); }
  };
  const runImpact = async () => {
    setBusy("impact");
    try { setImpact(await api.post(`/api/policies/${doc.id}/impact`, {})); } catch (e: any) { toast.error(e.message); } finally { setBusy(null); }
  };
  const decide = async (kind: "approve" | "reject") => {
    setBusy(kind);
    try { await api.post(`/api/policies/${doc.id}/${kind}`, { comment }); toast.success(kind === "approve" ? `v${doc.version} approved — effective ${fmtDate(doc.effective_from)}` : "Draft rejected"); onDecided(doc.id); }
    catch (e: any) { toast.error(e.message); } finally { setBusy(null); }
  };

  return (
    <Card className="mb-4 overflow-hidden border-warn/40">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-warn/30 bg-warn/[0.06] px-5 py-3">
        <div className="flex items-center gap-2 text-[14px] font-semibold"><AlertTriangle className="h-4 w-4 text-warn" /> Draft v{doc.version} is waiting for approval</div>
        <div className="text-[12px] text-muted">from {doc.source_name} · {doc.created_by}</div>
      </div>
      <div className="space-y-4 p-5">
        {doc.ai_notes && <div className="rounded-xl border border-accent/25 bg-accent/[0.05] p-3 text-[13px]"><div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-accent"><Sparkles className="h-3 w-3" /> AI reading of the amendment</div>{doc.ai_notes}</div>}
        <div>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="text-[13px] font-semibold">What will change</div>
            <Button size="sm" variant="subtle" onClick={openEditor} disabled={!schema} icon={<SlidersHorizontal className="h-3.5 w-3.5" />}>Edit rules</Button>
          </div>
          <ChangeList changes={doc.changes} />
        </div>
        {errors.length > 0 && <div className="rounded-xl border border-bad/30 bg-bad/5 p-3 text-[13px] text-bad">{errors.map((e: string) => <div key={e}>• {e.replace("Error: ", "")}</div>)}</div>}
        {notes.length > 0 && <div className="rounded-xl border border-warn/30 bg-warn/5 p-3 text-[13px]">{notes.map((e: string) => <div key={e} className="text-muted">• {e}</div>)}</div>}

        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <Field label="Version"><input value={ver} onChange={(e) => setVer(e.target.value)} className={inputCls} /></Field>
          <Field label="Effective from" hint="Requirements dated on or after this use the new version."><input type="date" value={eff} onChange={(e) => setEff(e.target.value)} className={inputCls} /></Field>
          <div className="flex items-end pb-[18px]"><Button size="md" onClick={saveMeta} loading={busy === "meta"} disabled={eff === doc.effective_from && ver === doc.version}>Save</Button></div>
        </div>

        <div className="rounded-xl border border-line p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div><div className="text-[13px] font-semibold">Impact preview</div><div className="text-[12px] text-muted">Replays the latest PR batch with this draft and lists every decision that would change.</div></div>
            <Button size="sm" variant="subtle" loading={busy === "impact"} onClick={runImpact} icon={<GitCompareArrows className="h-3.5 w-3.5" />}>Run preview</Button>
          </div>
          <AnimatePresence>{impact && <ImpactView impact={impact} />}</AnimatePresence>
        </div>
        <Modal open={editOpen} onClose={() => setEditOpen(false)} title={`Edit draft v${doc.version} in the rule builder`} wide
          footer={<><Button variant="ghost" onClick={() => setEditOpen(false)}>Cancel</Button>
            <Button variant="primary" loading={busy === "rules"} onClick={saveRules} disabled={!editDoc} icon={<CheckCircle2 className="h-4 w-4" />}>Save draft</Button></>}>
          <div className="mb-3 text-[12.5px] text-muted">Fix anything the reading got wrong (a limit, a condition, or where a rule sits in the ladder: the first matching rule wins). Changes are compared with v{doc.base_version}.</div>
          {editOpen && <PolicyBuilder base={editBase} schema={schema} doc={editDoc} setDoc={setEditDoc} />}
        </Modal>

        <div className="flex flex-wrap items-end gap-2 border-t border-line pt-4">
          <Field label="Approval note (optional)" className="min-w-[240px] flex-1"><input value={comment} onChange={(e) => setComment(e.target.value)} className={inputCls} placeholder="e.g. Approved per Head of Procurement email" /></Field>
          <Button variant="danger" loading={busy === "reject"} onClick={() => decide("reject")} icon={<XCircle className="h-4 w-4" />}>Reject</Button>
          <Button variant="primary" loading={busy === "approve"} disabled={errors.length > 0} onClick={() => decide("approve")} icon={<CheckCircle2 className="h-4 w-4" />}>Approve v{doc.version}</Button>
        </div>
      </div>
    </Card>
  );
}

function ImpactView({ impact }: { impact: any }) {
  return (
    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="mt-3 overflow-hidden">
      <div className="mb-2 text-[12.5px]"><b>{impact.changed.length}</b> of {impact.lines} lines in “{impact.run_name}” would change. Versions used: {impact.versions_used_after.map((v: string) => `v${v}`).join(", ")}.</div>
      {impact.note && <div className="mb-2 rounded-lg border border-info/30 bg-info/5 p-2 text-[12.5px] text-info">{impact.note}</div>}
      {impact.changed.length > 0 && (
        <div className="max-h-72 overflow-auto rounded-lg border border-line">
          <table className="w-full text-[12px]">
            <thead className="sticky top-0 bg-panel2 text-left text-[11px] text-faint"><tr><th scope="col" className="px-2.5 py-1.5">PR line</th><th scope="col" className="px-2.5 py-1.5">Item</th><th scope="col" className="px-2.5 py-1.5">Change</th></tr></thead>
            <tbody className="divide-y divide-line">
              {impact.changed.map((c: any) => (
                <tr key={c.pr_no + c.pr_line} title={c.reason_after}>
                  <td className="px-2.5 py-1.5 font-mono">{c.pr_no}/{c.pr_line}</td><td className="px-2.5 py-1.5 font-mono">{c.item}</td>
                  <td className="px-2.5 py-1.5">{Object.entries(c.changes).map(([k, [a, b]]: any) => <div key={k}><span className="text-faint">{k}:</span> <span className="text-bad line-through">{String(a) || "—"}</span> → <span className="text-ok">{String(b) || "—"}</span></div>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </motion.div>
  );
}

function ProposeModal({ open, onClose, aiOn, latest, schema, onCreated }: { open: boolean; onClose: () => void; aiOn: boolean; latest?: any; schema: any; onCreated: (id: number) => void }) {
  const [mode, setMode] = useState<"builder" | "upload" | "describe" | "json">(aiOn ? "upload" : "builder");
  const [base, setBase] = useState<any>(null);
  const [built, setBuilt] = useState<any>(null);
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [json, setJson] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open && latest) api.get(`/api/policies/${latest.id}`).then((d) => {
      setJson(JSON.stringify(d.document, null, 2));
      const b = JSON.parse(JSON.stringify(d.document));
      b.version = String(b.version).replace(/(\d+)$/, (n: string) => String(Number(n) + 1));
      b.effective_from = new Date().toISOString().slice(0, 10);
      setBase(d.document); setBuilt(b);
    });
    if (open) { setFile(null); setText(""); setMode(aiOn ? "upload" : "builder"); }
  }, [open, latest?.id]);
  const parsedErr = useMemo(() => { if (mode !== "json") return null; try { JSON.parse(json); return null; } catch (e: any) { return e.message; } }, [json, mode]);

  const submit = async () => {
    setBusy(true);
    try {
      let d;
      if (mode === "builder") d = await api.post("/api/policies/draft/manual", { document: built, source_name: "rule builder" });
      else if (mode === "json") d = await api.post("/api/policies/draft/manual", { document: JSON.parse(json), source_name: "JSON edit" });
      else {
        const fd = new FormData();
        if (mode === "upload" && file) fd.append("file", file);
        if (text.trim()) fd.append("text", text.trim());
        d = await api.upload("/api/policies/draft/ai", fd);
      }
      toast.success(`Draft v${d.version} created with ${d.changes.length} change(s)`);
      onCreated(d.id);
    } catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  };

  return (
    <Modal open={open} onClose={onClose} title="Propose a policy change" wide footer={<>
      <Button variant="ghost" onClick={onClose}>Cancel</Button>
      <Button variant="primary" loading={busy} onClick={submit}
        disabled={(mode === "upload" && (!file || !aiOn)) || (mode === "describe" && (!text.trim() || !aiOn)) || (mode === "json" && !!parsedErr) || (mode === "builder" && !built)}
        icon={mode === "json" || mode === "builder" ? <Braces className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}>{busy ? (mode === "upload" || mode === "describe" ? "Reading the amendment…" : "Checking…") : "Create draft for review"}</Button></>}>
      <div className="space-y-4">
        <Tabs value={mode} onChange={setMode} items={[{ value: "builder", label: <><SlidersHorizontal className="h-3.5 w-3.5" />Rule builder</> }, { value: "upload", label: <><FileUp className="h-3.5 w-3.5" />Upload amendment</> }, { value: "describe", label: <><Wand2 className="h-3.5 w-3.5" />Describe in words</> }, { value: "json", label: <><Braces className="h-3.5 w-3.5" />Edit as JSON</> }]} />
        {mode === "builder" && <PolicyBuilder base={base} schema={schema} doc={built} setDoc={setBuilt} />}
        {!aiOn && (mode === "upload" || mode === "describe") && <div className="rounded-lg border border-warn/30 bg-warn/5 p-3 text-[12.5px]">The AI reader is not configured on this server (set <Mono>GEMINI_API_KEY</Mono>, <Mono>GROQ_API_KEY</Mono> or <Mono>ANTHROPIC_API_KEY</Mono>). Use the <b>Rule builder</b> (or <b>Edit as JSON</b>) to make the change by hand; it is validated and shown as a plain-language diff before approval.</div>}
        {mode === "upload" && (
          <>
            <Dropzone onFiles={(f) => setFile(f[0])} accept=".pdf,.txt,.md" label={file ? file.name : "Drop the amendment (PDF, TXT or MD)"} sub="The AI proposes edits to the latest approved version; you review every change before it applies." />
            <Field label="Extra instruction (optional)"><input value={text} onChange={(e) => setText(e.target.value)} className={inputCls} placeholder="e.g. effective date is 19 Nov 2026" /></Field>
          </>
        )}
        {mode === "describe" && (
          <>
            <textarea value={text} onChange={(e) => setText(e.target.value)} aria-label="Describe the policy change" rows={5} className={cx(inputCls, "h-auto py-2")} placeholder="Describe the change, including when it takes effect." />
            <div className="flex flex-wrap gap-1.5">{EXAMPLES.map((e) => <button key={e} type="button" onClick={() => setText(e)} className="rounded-full border border-line px-2.5 py-1 text-left text-[12px] text-muted hover:border-accent/50 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">{e}</button>)}</div>
          </>
        )}
        {mode === "json" && (
          <>
            <textarea value={json} onChange={(e) => setJson(e.target.value)} spellCheck={false} aria-label="Policy document as JSON" aria-invalid={!!parsedErr} rows={18} className={cx(inputCls, "h-auto py-2 font-mono text-[12px] leading-relaxed")} />
            {parsedErr ? <div role="alert" className="text-[12px] text-bad">Invalid JSON: {parsedErr}</div> : <div className="text-[12px] text-muted">Valid JSON. The server validates facts, operators and outcomes, then shows the diff.</div>}
          </>
        )}
      </div>
    </Modal>
  );
}
