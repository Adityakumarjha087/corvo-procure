import { motion } from "framer-motion";
import { Database, FileArchive, History, RefreshCcw, ServerCog } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useHealth } from "../components/Layout";
import { AnimatedNumber, Badge, Button, Card, Dropzone, Mono, PageHeader, Stat, Tabs, stagger } from "../components/ui";
import { api } from "../lib/api";
import { fmtDateTime } from "../lib/format";

export default function DataPage() {
  const { health, refresh } = useHealth();
  const [audit, setAudit] = useState<any[]>([]);
  const [docs, setDocs] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [tab, setTab] = useState<"audit" | "docs">("audit");
  const load = () => { api.get("/api/audit?limit=300").then(setAudit); api.get("/api/documents").then(setDocs); };
  useEffect(() => { load(); }, []);

  const upload = async (files: File[]) => {
    setBusy(true);
    try {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      const r = await api.upload("/api/setup/upload", fd);
      setResult(r);
      toast.success("Data loaded", { description: Object.entries(r.loaded).map(([k, v]) => `${k}: ${v}`).join(" · ") });
      refresh(); load();
    } catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  };
  const c = health?.counts || {};

  return (
    <div>
      <PageHeader eyebrow="Admin" title="Data & audit"
        desc="Master data the engine decides with, and a record of every action: who did what, and when." />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[["Items", c.items], ["Suppliers", c.suppliers], ["PO history", c.po_history], ["Contracts", c.contracts]].map(([l, v], i) => (
          <motion.div key={String(l)} {...stagger(i)}><Stat label={String(l)} value={<AnimatedNumber value={Number(v || 0)} />} icon={<Database className="h-3.5 w-3.5" />} /></motion.div>
        ))}
      </div>

      <Card className="mt-4 p-5">
        <div className="mb-3 flex items-center gap-2"><FileArchive className="h-4 w-4 text-accent" /><h3 className="text-[15px] font-semibold">Load or refresh master data</h3></div>
        <Dropzone multiple onFiles={upload} busy={busy} accept=".csv,.pdf,.zip"
          label="Drop the kit files: item_master.csv, supplier_master.csv, po_history.csv, plants.csv, contract_register.csv, contract_lines.csv and contract PDFs — or one .zip"
          sub="Each file replaces its table. PDFs of contracts that are not in the register are added automatically." />
        {result && (
          <div className="mt-3 rounded-xl border border-line bg-panel2/50 p-3 text-[12.5px]">
            <div className="flex flex-wrap gap-2">{Object.entries(result.loaded).map(([k, v]) => <Badge key={k} tone="ok">{k}: {String(v)}</Badge>)}</div>
            {result.pdf_contracts_added?.length > 0 && <div className="mt-2">Added from PDF: {result.pdf_contracts_added.map((x: string) => <Mono key={x} className="mr-2 text-accent">{x}</Mono>)}</div>}
            {result.pdf_skipped?.length > 0 && <div className="mt-1 text-muted">Skipped: {result.pdf_skipped.join("; ")}</div>}
          </div>
        )}
        <div className="mt-3 flex items-center gap-2 text-[12px] text-muted"><ServerCog className="h-3.5 w-3.5" />Servers started with <Mono>KIT_DIR</Mono> load the kit on first boot.
          <Button size="sm" variant="ghost" onClick={async () => { try { const r = await api.post("/api/setup/load-local"); setResult(r); refresh(); load(); toast.success("Reloaded from KIT_DIR"); } catch (e: any) { toast.error(e.message); } }} icon={<RefreshCcw className="h-3.5 w-3.5" />}>Reload from server folder</Button>
        </div>
      </Card>

      <Card className="mt-4 p-5">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2"><History className="h-4 w-4 text-accent" /><h3 className="text-[15px] font-semibold">Records</h3></div>
          <Tabs value={tab} onChange={setTab} items={[{ value: "audit", label: "Audit log", count: audit.length }, { value: "docs", label: "POs & sourcing events", count: docs.length }]} />
        </div>
        {tab === "audit" ? (
          <div className="max-h-[60vh] overflow-auto rounded-lg border border-line">
            <table className="w-full text-[12.5px]">
              <thead className="sticky top-0 bg-panel2 text-left text-[11px] text-faint"><tr>{["When", "Who", "Action", "Entity", "Detail"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-line">
                {audit.map((a) => (
                  <tr key={a.id} className="align-top hover:bg-panel2/40">
                    <td className="whitespace-nowrap px-3 py-1.5 text-muted">{fmtDateTime(a.at)}</td><td className="px-3 py-1.5 font-medium">{a.actor}</td>
                    <td className="px-3 py-1.5"><Badge>{a.action}</Badge></td><td className="px-3 py-1.5 font-mono">{a.entity} {a.entity_id}</td>
                    <td className="max-w-[420px] truncate px-3 py-1.5 font-mono text-[11.5px] text-muted" title={JSON.stringify(a.detail)}>{JSON.stringify(a.detail)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="max-h-[60vh] overflow-auto rounded-lg border border-line">
            <table className="w-full text-[12.5px]">
              <thead className="sticky top-0 bg-panel2 text-left text-[11px] text-faint"><tr>{["Document", "Type", "From", "Supplier", "Plant", "Value", "Created"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-line">
                {docs.map((d) => (
                  <tr key={d.doc_no}><td className="px-3 py-1.5 font-mono text-accent">{d.doc_no}</td><td className="px-3 py-1.5">{d.route}</td><td className="px-3 py-1.5 font-mono">run {d.run_id} · {d.target}</td>
                    <td className="px-3 py-1.5 font-mono">{d.supplier_id || "—"}</td><td className="px-3 py-1.5">{d.plant}</td><td className="px-3 py-1.5 tabular">₹{Math.round(d.value).toLocaleString("en-IN")}</td>
                    <td className="px-3 py-1.5 text-muted">{d.created_by} · {fmtDateTime(d.created_at)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
