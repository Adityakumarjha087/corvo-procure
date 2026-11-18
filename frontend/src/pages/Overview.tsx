import { motion } from "framer-motion";
import { Activity, ArrowRight, Boxes, Database, FileSpreadsheet, Gauge, MessageSquareText, Scale, Sparkles, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useHealth, useUser } from "../components/Layout";
import { AnimatedNumber, Badge, Button, Card, PageHeader, Skeleton, Stat, cx, stagger } from "../components/ui";
import { api } from "../lib/api";
import { ago, compactInr, routeInfo } from "../lib/format";

const STAGES = [
  ["1", "Match item", "Code or fuzzy text match; unknown → new item"],
  ["2", "Club lines", "Same item & plant, 14-day window, ±7-day need-by"],
  ["3", "Value", "Contract rate → last PO (365 d) → standard price"],
  ["4", "Contracts", "Valid date, Active supplier, ceiling left"],
  ["5", "Rule ladder", "First matching rule decides the route"],
  ["6", "Suppliers", "Ranked preferred list, reference price"],
  ["7", "Consolidate", "Same supplier, plant, route within 24 h"],
  ["8", "Record", "Clause, version, contract or PO relied on"],
];

const TONE_BG: Record<string, string> = { accent: "bg-accent", info: "bg-info", bad: "bg-bad", warn: "bg-warn", vio: "bg-vio", muted: "bg-faint" };

export default function Overview() {
  const { health, refresh } = useHealth();
  const user = useUser();
  const nav = useNavigate();
  const [runs, setRuns] = useState<any[] | null>(null);
  const [audit, setAudit] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.get("/api/runs").then(setRuns).catch(() => setRuns([]));
    api.get("/api/audit?limit=8").then(setAudit).catch(() => {});
  }, []);
  const latest = runs?.[0];
  const routes: Record<string, number> = latest?.summary?.routes || {};
  const totalReq = Object.values(routes).reduce((a: number, b: any) => a + b, 0) || 1;
  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  const processInbox = async () => {
    setBusy(true);
    try {
      const r = await api.post("/api/inbox/process");
      toast.success(`Processed ${r.summary.lines} open PR line(s)`);
      refresh();
      nav(`/workspace/${r.run_id}`);
    } catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  };

  let next: { title: string; desc: string; cta: React.ReactNode; icon: any };
  if (health && !health.data_ready) {
    next = { title: "Load the master data", desc: "Items, suppliers, PO history and contracts are needed before any decision can be made.", icon: Database,
      cta: <Button variant="primary" onClick={() => nav("/data")} icon={<ArrowRight className="h-4 w-4" />}>Go to data setup</Button> };
  } else if ((health?.counts.open_prs ?? 0) > 0) {
    next = { title: `${health?.counts.open_prs} PR line(s) raised in chat are waiting`, desc: "Run them through the policy engine to get decisions you can approve.", icon: Sparkles,
      cta: <Button variant="primary" loading={busy} onClick={processInbox} icon={<Workflow className="h-4 w-4" />}>Process open PRs</Button> };
  } else if (!latest) {
    next = { title: "Process your first PR batch", desc: "Upload a batch CSV in the buyer workspace, or raise a PR through chat.", icon: FileSpreadsheet,
      cta: <Button variant="primary" onClick={() => nav("/workspace")} icon={<ArrowRight className="h-4 w-4" />}>Open buyer workspace</Button> };
  } else {
    next = { title: `Review “${latest.name}”`, desc: `${latest.summary.requirements} requirements decided under policy v${(latest.policy_versions || []).join(", v")}.`, icon: Boxes,
      cta: <Button variant="primary" onClick={() => nav(`/workspace/${latest.id}`)} icon={<ArrowRight className="h-4 w-4" />}>Review decisions</Button> };
  }

  return (
    <div>
      <PageHeader eyebrow="Overview" title={`${greet}, ${user.name.split(" ")[0]}`}
        desc="Every purchase request is decided by the procurement policy in force on its date. Here's where things stand." />

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
        className="relative mb-6 overflow-hidden rounded-2xl border border-accent/30 bg-gradient-to-br from-accent/[0.09] via-panel to-panel p-5 md:p-6">
        <div className="absolute -right-10 -top-10 h-44 w-44 rounded-full bg-accent/10 blur-3xl" />
        <div className="relative flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-start gap-4">
            <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-accent/30 bg-accent/10 text-accent"><next.icon className="h-5 w-5" /></div>
            <div>
              <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-accent">Next step</div>
              <div className="mt-0.5 font-display text-lg font-semibold">{next.title}</div>
              <div className="text-sm text-muted">{next.desc}</div>
            </div>
          </div>
          {next.cta}
        </div>
      </motion.div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          <Stat key="a" label="Open chat PRs" value={<AnimatedNumber value={health?.counts.open_prs ?? 0} />} sub="waiting for processing" icon={<MessageSquareText className="h-3.5 w-3.5" />} tone="warn" />,
          <Stat key="b" label="Latest batch lines" value={<AnimatedNumber value={latest?.summary?.lines ?? 0} />} sub={latest ? `${latest.summary.requirements} requirements` : "no batch yet"} icon={<FileSpreadsheet className="h-3.5 w-3.5" />} tone="info" />,
          <Stat key="c" label="Purchase orders" value={<AnimatedNumber value={latest?.summary?.purchase_orders ?? 0} />} sub="after consolidation (§7)" icon={<Boxes className="h-3.5 w-3.5" />} />,
          <Stat key="d" label="Value decided" value={<AnimatedNumber value={latest?.summary?.total_value ?? 0} format={(n) => compactInr(n)} />} sub="latest batch, excl. GST" icon={<Gauge className="h-3.5 w-3.5" />} tone="vio" />,
        ].map((s, i) => <motion.div key={i} {...stagger(i)}>{s}</motion.div>)}
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-5">
        <Card className="p-5 lg:col-span-3">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-[15px] font-semibold">Route mix</h3>
              <div className="text-xs text-muted">{latest ? `${latest.name} · ${ago(latest.created_at)}` : "No batch processed yet"}</div>
            </div>
            {latest && <Link to={`/workspace/${latest.id}`} className="text-[13px] text-accent hover:underline">Open run →</Link>}
          </div>
          {runs === null ? <Skeleton className="h-24" /> : latest ? (
            <>
              <div className="flex h-3 w-full overflow-hidden rounded-full bg-panel2">
                {Object.entries(routes).map(([k, v], i) => (
                  <motion.div key={k} title={`${routeInfo(k).label}: ${v}`} className={cx("h-full", TONE_BG[routeInfo(k).tone])}
                    style={{ opacity: 0.55 + 0.45 * ((i % 3) / 2) }} initial={{ width: 0 }} animate={{ width: `${(Number(v) / totalReq) * 100}%` }} transition={{ delay: 0.1 + i * 0.05, type: "spring", stiffness: 60 }} />
                ))}
              </div>
              <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
                {Object.entries(routes).sort((a: any, b: any) => b[1] - a[1]).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between text-[13px]">
                    <span className="flex items-center gap-2"><span className={cx("h-2 w-2 rounded-sm", TONE_BG[routeInfo(k).tone])} />{routeInfo(k).label}</span>
                    <span className="tabular font-mono text-muted">{String(v)}</span>
                  </div>
                ))}
              </div>
            </>
          ) : <div className="py-8 text-center text-sm text-muted">Process a batch to see how requirements are routed.</div>}
        </Card>

        <Card className="p-5 lg:col-span-2">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-[15px] font-semibold">Policy in force today</h3>
            <Scale className="h-4 w-4 text-muted" />
          </div>
          {health?.active_policy ? (
            <div>
              <div className="flex items-baseline gap-2">
                <span className="font-display text-3xl font-semibold">v{health.active_policy.version}</span>
                <Badge tone="ok" dot>approved</Badge>
              </div>
              <div className="mt-1 text-sm text-muted">effective from {health.active_policy.effective_from}</div>
              <div className="mt-4 text-[13px] text-muted">Procurement changes the rules by uploading an amendment or describing the change. Nothing in the code changes.</div>
              <Button className="mt-4" variant="subtle" onClick={() => nav("/policy")} icon={<Scale className="h-4 w-4" />}>Open policy studio</Button>
            </div>
          ) : <Skeleton className="h-20" />}
        </Card>
      </div>

      <Card className="mt-4 p-5">
        <div className="mb-4 flex items-center gap-2"><Workflow className="h-4 w-4 text-accent" /><h3 className="text-[15px] font-semibold">How every PR line is decided</h3></div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
          {STAGES.map(([n, t, d], i) => (
            <motion.div key={n} {...stagger(i)} className="group relative rounded-xl border border-line bg-panel2/60 p-3 transition-colors hover:border-accent/40">
              <div className="flex items-center justify-between">
                <span className="font-mono text-[11px] text-accent">§{n}</span>
                {i < STAGES.length - 1 && <ArrowRight className="hidden h-3.5 w-3.5 text-faint xl:block" />}
              </div>
              <div className="mt-1 text-[13.5px] font-semibold">{t}</div>
              <div className="mt-0.5 text-[11.5px] leading-snug text-muted">{d}</div>
            </motion.div>
          ))}
        </div>
      </Card>

      <Card className="mt-4 p-5">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2"><Activity className="h-4 w-4 text-accent" /><h3 className="text-[15px] font-semibold">Recent activity</h3></div>
          <Link to="/data" className="text-[13px] text-accent hover:underline">Full audit log →</Link>
        </div>
        <div className="divide-y divide-line">
          {audit.length === 0 && <div className="py-4 text-sm text-muted">No activity yet.</div>}
          {audit.map((a, i) => (
            <motion.div key={a.id} {...stagger(i)} className="flex items-center gap-3 py-2 text-[13px]">
              <span className="w-24 shrink-0 text-faint">{ago(a.at)}</span>
              <span className="font-medium">{a.actor}</span>
              <Badge>{a.action}</Badge>
              <span className="truncate text-muted">{a.entity} {a.entity_id}</span>
            </motion.div>
          ))}
        </div>
      </Card>
    </div>
  );
}
