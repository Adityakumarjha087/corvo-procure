import { motion } from "framer-motion";
import { Ban, CalendarDays, Download, Info, Search, Trophy } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Badge, Button, Card, Empty, Field, Mono, PageHeader, Skeleton, cx, inputCls, stagger } from "../components/ui";
import { api } from "../lib/api";
import { inr } from "../lib/format";
import { ScoreTable } from "./Workspace";

const today = () => new Date().toISOString().slice(0, 10);

export default function SuppliersPage() {
  const [params, setParams] = useSearchParams();
  const [items, setItems] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [asOf, setAsOf] = useState(params.get("as_of") || today());
  const [item, setItem] = useState(params.get("item") || "");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [all, setAll] = useState<any>(null);

  useEffect(() => { api.get("/api/items").then((r) => { setItems(r); if (!item && r.length) setItem(r[0].item_code);}); }, []);
  useEffect(() => {
    if (!item) return;
    setLoading(true);
    setParams({ item, as_of: asOf }, { replace: true });
    api.get(`/api/preferred?item_code=${item}&as_of=${asOf}`).then(setData).catch((e) => toast.error(e.message)).finally(() => setLoading(false));
  }, [item, asOf]);
  useEffect(() => { api.get(`/api/preferred/all?as_of=${asOf}`).then(setAll).catch(() => {}); }, [asOf]);

  const shownItems = useMemo(() => items.filter((i) => !q || `${i.item_code} ${i.description} ${i.category}`.toLowerCase().includes(q.toLowerCase())), [items, q]);
  const counts = useMemo(() => { const m: Record<string, number> = {}; (all?.rows || []).forEach((r: any) => (m[r.item_code] = (m[r.item_code] || 0) + 1)); return m; }, [all]);

  const exportCsv = async () => {
    try { const n = await api.download(`/api/preferred/export.csv?as_of=${asOf}&top=3`, `preferred_${asOf}.csv`); toast.success(`Downloaded ${n}`); } catch (e: any) { toast.error(e.message); }
  };

  return (
    <div>
      <PageHeader eyebrow="Buyer" title="Preferred suppliers"
        desc="Every item's ranked supplier list, rebuilt from PO history and contracts as of any date. Each score is broken down so you can see why a supplier ranks where it does."
        actions={<>
          <label className="flex items-center gap-2 text-[13px] text-muted"><CalendarDays className="h-4 w-4" /><input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className={cx(inputCls, "w-40")} aria-label="As of date" /></label>
          <Button variant="primary" onClick={exportCsv} icon={<Download className="h-4 w-4" />}>Export top 3 (CSV)</Button>
        </>} />

      <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
        <Card className="flex max-h-[calc(100vh-220px)] flex-col">
          <div className="border-b border-line p-2.5">
            <div className="relative"><Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-faint" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find an item" className={cx(inputCls, "pl-8")} /></div>
          </div>
          <div className="flex-1 overflow-y-auto p-1.5">
            {shownItems.map((it) => (
              <button key={it.item_code} onClick={() => setItem(it.item_code)} className={cx("relative flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left", item === it.item_code ? "bg-panel2" : "hover:bg-panel2/60")}>
                {item === it.item_code && <motion.span layoutId="item-sel" className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-accent" />}
                <span className="min-w-0"><Mono className="text-accent">{it.item_code}</Mono><span className="block truncate text-[12.5px]">{it.description}</span></span>
                <Badge tone={counts[it.item_code] ? "muted" : "warn"}>{counts[it.item_code] || 0}</Badge>
              </button>
            ))}
          </div>
        </Card>

        <div className="min-w-0 space-y-4">
          {loading && !data ? <Skeleton className="h-64" /> : data && (
            <>
              <Card className="p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2"><Mono className="text-accent">{data.item.item_code}</Mono><Badge>{data.item.category}</Badge><Badge tone="vio">{data.item.item_type}</Badge></div>
                    <h2 className="mt-1 text-xl font-semibold">{data.item.description}</h2>
                    <div className="text-[12.5px] text-muted">as of {asOf} · policy v{data.policy_version} · standard price {inr(data.item.standard_price, 2)}/{data.item.uom}</div>
                  </div>
                  <div className="rounded-xl border border-line bg-panel2/50 p-3 text-[12px]">
                    <div className="mb-1 font-medium">Weights (policy §6.2)</div>
                    {Object.entries(data.weights || {}).map(([k, v]) => <div key={k} className="flex justify-between gap-6"><span className="capitalize text-muted">{k}</span><span className="font-mono">{String(v)}</span></div>)}
                  </div>
                </div>
                <div className="mt-5">
                  {data.ranked.length === 0 ? <Empty icon={<Trophy className="h-5 w-5" />} title="No preferred suppliers" desc="No Active supplier has bought this item in the look-back window or held a contract for it. Sourcing tops up suggestions from the item category." /> : <ScoreTable ranked={data.ranked} />}
                </div>
              </Card>

              {data.excluded.length > 0 && (
                <Card className="p-4">
                  <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold"><Ban className="h-4 w-4 text-bad" />Not on the list</div>
                  {data.excluded.map((e: any) => <div key={e.supplier_id} className="text-[13px] text-muted"><Mono>{e.supplier_id}</Mono> {e.name} — {e.reason}</div>)}
                </Card>
              )}

              <Card className="p-4">
                <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold"><Info className="h-4 w-4 text-accent" />If this item went to sourcing (5 suggestions, §6.4)</div>
                <div className="flex flex-wrap gap-2">
                  {data.suggestions_5.map((s: any, i: number) => (
                    <motion.div key={s.supplier_id} {...stagger(i)} className="rounded-lg border border-line bg-panel2/50 px-2.5 py-1.5 text-[12.5px]">
                      <span className="mr-1 text-faint">{i + 1}.</span><Mono>{s.supplier_id}</Mono> {s.name} <span className="text-[11px] text-muted">{s.source === "preferred" ? "preferred" : "category"}</span>
                    </motion.div>
                  ))}
                </div>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
