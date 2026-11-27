// Visual policy editor: change limits and rules with forms (no JSON, no AI needed).
// It edits a copy of the latest approved policy; the server validates it and shows the plain-language diff.
import { AnimatePresence, motion } from "framer-motion";
import { ArrowDown, ArrowUp, ChevronDown, Plus, Power, Trash2, X } from "lucide-react";
import React, { useEffect, useMemo, useState } from "react";
import { Badge, Button, Field, cx, inputCls } from "../components/ui";
import { routeInfo } from "../lib/format";

const BOOL_FACTS = new Set(["contract_usable", "contract_applicable", "is_emergency", "is_new_item"]);
const NUM_FACTS = new Set(["value", "quantity", "unit_price", "days_since_active_purchase", "days_since_any_purchase", "active_purchase_count_365",
  "lead_time_days", "line_count", "preferred_supplier_count", "top_supplier_on_time_pct", "top_supplier_quality", "month"]);
const OP_LABEL: Record<string, string> = { eq: "is", ne: "is not", lt: "is below", lte: "is at most", gt: "is above", gte: "is at least",
  in: "is one of", not_in: "is not one of", between: "is between", contains: "contains", exists: "is known", not_exists: "is unknown" };
const ROUTES = ["CONTRACT_PO", "EMERGENCY_PO", "SPOT_PO", "RFQ", "RFP", "CAPEX_SOURCING", "NEW_ITEM_SOURCING", "NOT_PROCESSED"];

type Cond = { fact: string; op: string; value?: any };
const clone = (o: any) => JSON.parse(JSON.stringify(o));
const getPath = (o: any, p: string) => p.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
function setPath(o: any, p: string, v: any) { const ks = p.split("."); let c = o; ks.slice(0, -1).forEach((k) => (c = c[k] ??= {})); c[ks[ks.length - 1]] = v; }

/** A rule's condition as a flat AND-list, or null if it uses any/not (then it is edited as JSON). */
function flatConds(when: any): Cond[] | null {
  if (!when) return [];
  if (when.all && when.all.every((c: any) => c.fact)) return when.all;
  if (when.fact) return [when];
  return null;
}

function valueText(c: Cond): string {
  if (Array.isArray(c.value)) return c.value.join(", ");
  return c.value === undefined || c.value === null ? "" : String(c.value);
}
function parseValue(fact: string, op: string, raw: string): any {
  if (op === "exists" || op === "not_exists") return undefined;
  if (BOOL_FACTS.has(fact)) return raw === "true";
  const num = (s: string) => { const n = Number(String(s).replace(/[,₹\s]/g, "")); return isNaN(n) ? s.trim() : n; };
  if (op === "in" || op === "not_in" || op === "between") return raw.split(",").map((s) => (NUM_FACTS.has(fact) ? num(s) : s.trim())).filter((s) => s !== "");
  return NUM_FACTS.has(fact) ? num(raw) : raw.trim();
}

export function PolicyBuilder({ base, schema, doc, setDoc }: { base: any; schema: any; doc: any; setDoc: (d: any) => void }) {
  const [openRule, setOpenRule] = useState<number | null>(null);
  useEffect(() => { if (base && !doc) setDoc(clone(base)); }, [base]);
  if (!doc || !schema) return <div className="py-6 text-center text-sm text-muted">Loading the current policy…</div>;

  const update = (fn: (d: any) => void) => { const d = clone(doc); fn(d); setDoc(d); };
  const numericParams = Object.entries(schema.params as Record<string, string>).filter(([p]) => {
    const v = getPath(base, p);
    return typeof v === "number" || typeof v === "boolean" || v === null;
  });

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="New version"><input value={doc.version} onChange={(e) => update((d) => (d.version = e.target.value))} className={inputCls} /></Field>
        <Field label="Effective from" hint="Requirements dated on or after this date use the new version."><input type="date" value={doc.effective_from} onChange={(e) => update((d) => (d.effective_from = e.target.value))} className={inputCls} /></Field>
      </div>

      <section>
        <div className="mb-2 text-[13px] font-semibold">Limits and windows</div>
        <div className="grid gap-2 sm:grid-cols-2">
          {numericParams.map(([p, label]) => {
            const v = getPath(doc, p);
            const changed = JSON.stringify(v) !== JSON.stringify(getPath(base, p));
            return (
              <label key={p} className={cx("flex items-center justify-between gap-3 rounded-lg border px-3 py-1.5", changed ? "border-accent/50 bg-accent/5" : "border-line")}>
                <span className="text-[12.5px] text-muted">{label}</span>
                {typeof getPath(base, p) === "boolean" ? (
                  <select value={String(v)} onChange={(e) => update((d) => setPath(d, p, e.target.value === "true"))} className="h-8 rounded-md border border-line bg-panel2 px-2 text-[13px]">
                    <option value="true">yes</option><option value="false">no</option>
                  </select>
                ) : (
                  <input value={v ?? ""} placeholder="not set" inputMode="decimal"
                    onChange={(e) => update((d) => setPath(d, p, e.target.value === "" ? null : isNaN(Number(e.target.value)) ? e.target.value : Number(e.target.value)))}
                    className="h-8 w-28 rounded-md border border-line bg-panel2 px-2 text-right font-mono text-[13px]" />
                )}
              </label>
            );
          })}
        </div>
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <div className="text-[13px] font-semibold">Decision rules <span className="font-normal text-muted">(checked top to bottom; the first that fits decides)</span></div>
          <Button size="sm" variant="subtle" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => {
            const ids = new Set(doc.rules.map((r: any) => String(r.id)));
            let n = 1; while (ids.has(`N${n}`)) n++;
            const idx = doc.rules.findIndex((r: any) => (r.then?.decision === "SOURCING_REQUEST" && JSON.stringify(r.when).includes('"value"') && !JSON.stringify(r.when).includes('"plant"')));
            const at = idx >= 0 ? idx : doc.rules.length;
            update((d) => d.rules.splice(at, 0, { id: `N${n}`, name: "New rule", when: { all: [{ fact: "plant", op: "eq", value: "CHK1" }] }, then: { decision: "SOURCING_REQUEST", route: "RFQ", supplier: { mode: "suggest", count: 3 } } }));
            setOpenRule(at);
          }}>Add rule</Button>
        </div>
        <div className="space-y-2">
          {doc.rules.map((r: any, i: number) => (
            <RuleCard key={i} rule={r} index={i} total={doc.rules.length} open={openRule === i} schema={schema}
              baseRule={base.rules.find((b: any) => String(b.id) === String(r.id))}
              onToggle={() => setOpenRule(openRule === i ? null : i)}
              onChange={(nr) => update((d) => (d.rules[i] = nr))}
              onMove={(dir) => { update((d) => { const [x] = d.rules.splice(i, 1); d.rules.splice(i + dir, 0, x); }); setOpenRule(openRule === i ? i + dir : openRule); }}
              onDelete={() => { update((d) => d.rules.splice(i, 1)); setOpenRule(null); }} />
          ))}
        </div>
      </section>
    </div>
  );
}

function RuleCard({ rule, baseRule, index, total, open, schema, onToggle, onChange, onMove, onDelete }: {
  rule: any; baseRule?: any; index: number; total: number; open: boolean; schema: any; onToggle: () => void; onChange: (r: any) => void; onMove: (d: number) => void; onDelete: () => void;
}) {
  const conds = flatConds(rule.when);
  const [rawWhen, setRawWhen] = useState(JSON.stringify(rule.when, null, 1));
  const changed = !baseRule ? "new" : JSON.stringify(baseRule) !== JSON.stringify(rule) ? "changed" : "";
  const enabled = rule.enabled !== false;
  const set = (fn: (r: any) => void) => { const r = clone(rule); fn(r); onChange(r); };
  const facts: string[] = Object.keys(schema.facts);
  const summary = (conds || []).map((c) => `${c.fact.replace(/_/g, " ")} ${OP_LABEL[c.op] || c.op} ${valueText(c)}`).join(" and ") || "complex condition";

  return (
    <div className={cx("rounded-xl border", changed === "new" ? "border-ok/50" : changed ? "border-warn/50" : "border-line", !enabled && "opacity-60")}>
      <div className="flex items-center gap-2 px-3 py-2">
        <span className="w-12 font-mono text-[12.5px] font-semibold text-accent">{rule.id}</span>
        <button onClick={onToggle} aria-expanded={open} aria-label={`${open ? "Collapse" : "Edit"} rule ${rule.id}: ${rule.name}`} className="min-w-0 flex-1 text-left">
          <div className="truncate text-[13.5px] font-medium">{rule.name}</div>
          <div className="truncate text-[11.5px] text-muted">when {summary}</div>
        </button>
        <Badge tone={routeInfo(rule.then?.route || "").tone}>{routeInfo(rule.then?.route || "").label}</Badge>
        {changed && <Badge tone={changed === "new" ? "ok" : "warn"}>{changed}</Badge>}
        <IconBtn label="Move up" disabled={index === 0} onClick={() => onMove(-1)}><ArrowUp className="h-3.5 w-3.5" /></IconBtn>
        <IconBtn label="Move down" disabled={index === total - 1} onClick={() => onMove(1)}><ArrowDown className="h-3.5 w-3.5" /></IconBtn>
        <IconBtn label={enabled ? "Disable rule" : "Enable rule"} onClick={() => set((r) => (r.enabled = !enabled))}><Power className={cx("h-3.5 w-3.5", enabled ? "text-ok" : "text-faint")} /></IconBtn>
        <IconBtn label="Delete rule" onClick={onDelete}><Trash2 className="h-3.5 w-3.5 hover:text-bad" /></IconBtn>
        <IconBtn label={`${open ? "Collapse" : "Edit"} rule ${rule.id}`} expanded={open} onClick={onToggle}><ChevronDown className={cx("h-4 w-4 transition-transform", open && "rotate-180")} /></IconBtn>
      </div>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden border-t border-line">
            <div className="space-y-3 p-3">
              <div className="grid gap-2 sm:grid-cols-[110px_1fr]">
                <Field label="Rule id"><input value={rule.id} onChange={(e) => set((r) => (r.id = e.target.value))} className={inputCls} /></Field>
                <Field label="Name"><input value={rule.name} onChange={(e) => set((r) => (r.name = e.target.value))} className={inputCls} /></Field>
              </div>

              <div>
                <div className="mb-1 text-[12px] font-medium text-muted">When ALL of these are true</div>
                {conds === null ? (
                  <textarea value={rawWhen} rows={5} onChange={(e) => { setRawWhen(e.target.value); try { const w = JSON.parse(e.target.value); set((r) => (r.when = w)); } catch {} }}
                    className={cx(inputCls, "h-auto py-2 font-mono text-[12px]")} />
                ) : (
                  <div className="space-y-1.5">
                    {conds.map((c, ci) => (
                      <div key={ci} className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1.2fr)_28px] gap-1.5">
                        <select value={c.fact} onChange={(e) => set((r) => { r.when = { all: clone(conds) }; r.when.all[ci].fact = e.target.value; })} className={inputCls} title={schema.facts[c.fact]}>
                          {facts.map((f) => <option key={f} value={f}>{f.replace(/_/g, " ")}</option>)}
                        </select>
                        <select value={c.op} onChange={(e) => set((r) => { r.when = { all: clone(conds) }; r.when.all[ci].op = e.target.value; })} className={inputCls}>
                          {Object.entries(OP_LABEL).map(([o, l]) => <option key={o} value={o}>{l}</option>)}
                        </select>
                        {c.op === "exists" || c.op === "not_exists" ? <span /> : BOOL_FACTS.has(c.fact) ? (
                          <select value={String(c.value)} onChange={(e) => set((r) => { r.when = { all: clone(conds) }; r.when.all[ci].value = e.target.value === "true"; })} className={inputCls}>
                            <option value="true">yes</option><option value="false">no</option>
                          </select>
                        ) : (
                          <ValueInput c={c} onCommit={(v) => set((r) => { r.when = { all: clone(conds) }; r.when.all[ci].value = parseValue(c.fact, c.op, v); })} />
                        )}
                        <IconBtn label="Remove condition" onClick={() => set((r) => { r.when = { all: conds.filter((_, j) => j !== ci) }; })}><X className="h-3.5 w-3.5" /></IconBtn>
                      </div>
                    ))}
                    <button onClick={() => set((r) => { r.when = { all: [...conds, { fact: "value", op: "lt", value: 100000 }] }; })} className="text-[12px] text-accent">+ Add condition</button>
                    <div className="text-[11px] text-faint">Money in ₹ (e.g. 300000 for 3 lakh). Lists: comma separated (e.g. CHK1, PUN1). Between: two values, e.g. 0, 500000.</div>
                  </div>
                )}
              </div>

              <div className="grid gap-2 sm:grid-cols-3">
                <Field label="Decision">
                  <select value={rule.then?.decision} onChange={(e) => set((r) => {
                    r.then.decision = e.target.value;
                    if (e.target.value === "PO" && !["contract", "preferred", "fixed"].includes(r.then.supplier?.mode)) r.then.supplier = { mode: "preferred", rank: 1 };
                    if (e.target.value !== "PO" && !["suggest", "none"].includes(r.then.supplier?.mode)) r.then.supplier = { mode: "suggest", count: 3 };
                  })} className={inputCls}>
                    <option value="PO">PO</option><option value="SOURCING_REQUEST">Sourcing request</option><option value="NOT_PROCESSED">Not processed</option>
                  </select>
                </Field>
                <Field label="Route">
                  <input list="routes" value={rule.then?.route} onChange={(e) => set((r) => (r.then.route = e.target.value.toUpperCase().replace(/\s+/g, "_")))} className={inputCls} />
                  <datalist id="routes">{ROUTES.map((x) => <option key={x} value={x} />)}</datalist>
                </Field>
                <Field label="Supplier">
                  <select value={supplierChoice(rule.then?.supplier)} onChange={(e) => set((r) => (r.then.supplier = supplierFromChoice(e.target.value, r.then.supplier)))} className={inputCls}>
                    {rule.then?.decision === "PO" ? <>
                      <option value="contract">Contract supplier at contract rate</option>
                      <option value="preferred">Preferred supplier by rank</option>
                      <option value="cheapest">Cheapest of top preferred</option>
                    </> : <>
                      <option value="suggest">Suggest suppliers</option>
                      <option value="none">No suggestions</option>
                    </>}
                  </select>
                </Field>
              </div>
              {["preferred", "cheapest", "suggest"].includes(supplierChoice(rule.then?.supplier)) && (
                <div className="grid gap-2 sm:grid-cols-3">
                  <Field label={supplierChoice(rule.then.supplier) === "preferred" ? "Rank" : supplierChoice(rule.then.supplier) === "cheapest" ? "Among top" : "How many"}>
                    <input inputMode="numeric" value={rule.then.supplier.rank ?? rule.then.supplier.among ?? rule.then.supplier.count ?? ""}
                      onChange={(e) => set((r) => { const n = Number(e.target.value) || 0; const s = r.then.supplier; if (s.mode === "suggest") s.count = n; else if (s.pick) s.among = n; else s.rank = n; })} className={inputCls} />
                  </Field>
                  <Field label="Note on the decision (optional)" className="sm:col-span-2"><input value={rule.then.note || ""} onChange={(e) => set((r) => (r.then.note = e.target.value || undefined))} className={inputCls} /></Field>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function ValueInput({ c, onCommit }: { c: Cond; onCommit: (v: string) => void }) {
  const [v, setV] = useState(valueText(c));
  useEffect(() => setV(valueText(c)), [c.fact, c.op, JSON.stringify(c.value)]);
  return <input value={v} onChange={(e) => setV(e.target.value)} onBlur={() => onCommit(v)} onKeyDown={(e) => e.key === "Enter" && onCommit(v)} className={cx(inputCls, "font-mono")} />;
}

function supplierChoice(s: any): string {
  if (!s) return "none";
  if (s.mode === "preferred" && s.pick === "lowest_price") return "cheapest";
  return s.mode;
}
function supplierFromChoice(c: string, prev: any) {
  if (c === "contract") return { mode: "contract" };
  if (c === "preferred") return { mode: "preferred", rank: prev?.rank || 1 };
  if (c === "cheapest") return { mode: "preferred", pick: "lowest_price", among: prev?.among || 3 };
  if (c === "suggest") return { mode: "suggest", count: prev?.count || 3 };
  return { mode: "none" };
}

function IconBtn({ children, label, onClick, disabled, expanded }: { children: React.ReactNode; label: string; onClick: () => void; disabled?: boolean; expanded?: boolean }) {
  return <button aria-label={label} aria-expanded={expanded} title={label} disabled={disabled} onClick={onClick} className="grid h-7 w-7 place-items-center rounded-md text-muted hover:bg-panel2 hover:text-ink disabled:opacity-30">{children}</button>;
}

export function useBuilderState() {
  const [doc, setDoc] = useState<any>(null);
  return useMemo(() => ({ doc, setDoc, reset: () => setDoc(null) }), [doc]);
}
