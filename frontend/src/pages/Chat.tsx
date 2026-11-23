import { AnimatePresence, motion } from "framer-motion";
import { Bot, CalendarDays, CheckCircle2, Factory, Hash, Package, RotateCcw, SendHorizonal, Siren, Sparkles, Tag, User } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { aiLabel, useHealth, useUser } from "../components/Layout";
import { Badge, Button, Card, Mono, PageHeader, RouteBadge, cx } from "../components/ui";
import { api } from "../lib/api";
import { fmtDate, inr, num } from "../lib/format";

type Msg = { role: "user" | "assistant"; text: string; quick?: { label: string; value: string }[]; candidates?: any[]; created?: any; preview?: any; ai?: boolean };

function Rich({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return <span className="prose-chat">{parts.map((p, i) => (p.startsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : <React.Fragment key={i}>{p}</React.Fragment>))}</span>;
}

function Typing() {
  return (
    <div className="flex items-center gap-1 px-1 py-2">
      {[0, 1, 2].map((i) => (
        <motion.span key={i} className="h-1.5 w-1.5 rounded-full bg-muted" animate={{ y: [0, -4, 0], opacity: [0.4, 1, 0.4] }} transition={{ repeat: Infinity, duration: 0.9, delay: i * 0.15 }} />
      ))}
    </div>
  );
}

export default function ChatPage() {
  const user = useUser();
  const { health, refresh } = useHealth();
  const nav = useNavigate();
  const [session, setSession] = useState<string | null>(() => { try { return sessionStorage.getItem("chat.sid"); } catch { return null; } });
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [draft, setDraft] = useState<any>(null);
  const [preview, setPreview] = useState<any>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [mine, setMine] = useState<any[]>([]);
  const end = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const loadMine = () => api.get("/api/inbox").then((rows) => setMine(rows.filter((r: any) => r.requester === user.name).slice(0, 6))).catch(() => {});
  useEffect(() => { loadMine(); }, [user.name]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs, busy]);

  useEffect(() => {
    // restore or start
    const start = async () => {
      if (session) {
        try {
          const h = await api.get(`/api/chat/${session}`);
          setMsgs(h.messages.map((m: any) => ({ role: m.role, text: m.text, created: m.created })));
          return;
        } catch {}
      }
      send("", true);
    };
    if (health?.data_ready) start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [health?.data_ready]);

  async function send(text: string, silent = false) {
    if (busy) return;
    if (!silent && !text.trim()) return;
    if (!silent) setMsgs((m) => [...m, { role: "user", text }]);
    setInput("");
    setBusy(true);
    try {
      const r = await api.post("/api/chat", { session_id: silent ? null : session, message: text });
      setSession(r.session_id);
      try { sessionStorage.setItem("chat.sid", r.session_id); } catch {}
      setMsgs((m) => [...m, { role: "assistant", text: r.text, quick: r.quick_replies, candidates: r.candidates, created: r.created, preview: r.preview, ai: r.extracted_by === "ai" }]);
      if (r.draft) setDraft(r.draft);
      setPreview(r.preview || null);
      if (r.created) {
        toast.success(`${r.created.pr_no} raised`, { description: `${num(r.created.quantity)} ${r.created.uom} · ${r.created.description}` });
        loadMine(); refresh();
        if (!r.draft) { setDraft(null); setPreview(null); }
      }
    } catch (e: any) {
      setMsgs((m) => [...m, { role: "assistant", text: `Sorry, that failed: ${e.message}` }]);
    } finally {
      setBusy(false);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }

  const reset = () => {
    try { sessionStorage.removeItem("chat.sid"); } catch {}
    setSession(null); setMsgs([]); setDraft(null); setPreview(null);
    setTimeout(() => send("", true), 0);
  };

  const lastAssistant = [...msgs].reverse().find((m) => m.role === "assistant");

  return (
    <div>
      <PageHeader eyebrow="Requester" title="Raise a purchase request"
        desc="Describe what you need in your own words. The assistant matches it to the item master, asks for anything missing, and shows how the policy will treat it before you confirm."
        actions={<Button variant="ghost" onClick={reset} icon={<RotateCcw className="h-4 w-4" />}>New conversation</Button>} />

      {health && !health.data_ready ? (
        <Card className="p-8 text-center text-sm text-muted">Master data is not loaded yet. <button className="text-accent underline" onClick={() => nav("/data")}>Load it in Data setup</button>.</Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
          <Card className="flex h-[calc(100vh-220px)] min-h-[520px] flex-col overflow-hidden">
            <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
              <div className="flex items-center gap-2 text-sm"><span className="grid h-7 w-7 place-items-center rounded-lg bg-accent/15 text-accent"><Bot className="h-4 w-4" /></span><span className="font-medium">Intake assistant</span></div>
              <Badge tone={health?.ai_available ? "accent" : "muted"}>{health?.ai_available ? <><Sparkles className="h-3 w-3" /> {aiLabel(health?.ai_provider)} extraction</> : "rule-based extraction"}</Badge>
            </div>
            <div role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation with the intake assistant" aria-busy={busy} tabIndex={0} className="flex-1 space-y-4 overflow-y-auto px-4 py-5 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent/60">
              <AnimatePresence initial={false}>
                {msgs.map((m, i) => (
                  <motion.div key={i} initial={{ opacity: 0, y: 8, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ type: "spring", stiffness: 360, damping: 30 }}
                    className={cx("flex gap-2.5", m.role === "user" && "flex-row-reverse")}>
                    <div className={cx("grid h-7 w-7 shrink-0 place-items-center rounded-lg", m.role === "user" ? "bg-panel2 text-muted" : "bg-accent/15 text-accent")}>
                      {m.role === "user" ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
                    </div>
                    <div className={cx("max-w-[78%] space-y-2", m.role === "user" && "items-end text-right")}>
                      {m.text && (
                        <div className={cx("inline-block rounded-2xl px-3.5 py-2 text-left text-[14px] leading-relaxed",
                          m.role === "user" ? "rounded-tr-sm bg-accent text-[rgb(var(--bg))]" : "rounded-tl-sm border border-line bg-panel2")}>
                          <Rich text={m.text} />
                        </div>
                      )}
                      {m.candidates && m === lastAssistant && (
                        <div className="grid gap-2 sm:grid-cols-2">
                          {m.candidates.map((c: any, ci: number) => (
                            <motion.button key={c.item_code} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: ci * 0.05 }}
                              onClick={() => send(c.item_code)} className="rounded-xl border border-line bg-panel p-3 text-left transition hover:border-accent/50 hover:shadow-glow">
                              <div className="flex items-center justify-between"><Mono className="text-accent">{c.item_code}</Mono><span className="text-[11px] text-faint">{Math.round(c.score * 100)}% match</span></div>
                              <div className="mt-1 text-[13.5px] font-medium">{c.description}</div>
                              <div className="text-[11.5px] text-muted">{c.category} · {c.uom}</div>
                            </motion.button>
                          ))}
                        </div>
                      )}
                      {m.created && (
                        <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} className="inline-flex items-center gap-2 rounded-xl border border-ok/30 bg-ok/10 px-3 py-2 text-[13px] text-ok">
                          <CheckCircle2 className="h-4 w-4" /> {m.created.pr_no} raised · {num(m.created.quantity)} {m.created.uom} · {m.created.plant}
                        </motion.div>
                      )}
                      {m.quick && m === lastAssistant && !busy && (
                        <div className="flex flex-wrap gap-1.5">
                          {m.quick.map((q) => (
                            <motion.button whileHover={{ y: -1 }} whileTap={{ scale: 0.97 }} key={q.label} onClick={() => send(q.value)}
                              className={cx("rounded-full border px-3 py-1 text-[12.5px] transition-colors",
                                q.value === "confirm" ? "border-accent bg-accent text-[rgb(var(--bg))] font-medium" : "border-line bg-panel hover:border-accent/50 hover:text-accent")}>
                              {q.label}
                            </motion.button>
                          ))}
                        </div>
                      )}
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
              {busy && <div className="flex gap-2.5"><div className="grid h-7 w-7 place-items-center rounded-lg bg-accent/15 text-accent"><Bot className="h-3.5 w-3.5" /></div><div className="rounded-2xl rounded-tl-sm border border-line bg-panel2 px-3"><Typing /></div></div>}
              <div ref={end} />
            </div>
            <form onSubmit={(e) => { e.preventDefault(); send(input); }} className="border-t border-line p-3">
              <div className="flex items-end gap-2 rounded-xl border border-line bg-panel2 p-1.5 focus-within:border-accent/60 focus-within:ring-2 focus-within:ring-accent/15">
                <textarea ref={inputRef} rows={1} value={input} onChange={(e) => setInput(e.target.value)} placeholder="e.g. need 200 nitrile gloves for Chakan by next Friday"
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
                  className="max-h-32 min-h-[38px] flex-1 resize-none bg-transparent px-2 py-2 text-sm focus:outline-none" aria-label="Message" />
                <Button type="submit" variant="primary" disabled={!input.trim() || busy} icon={<SendHorizonal className="h-4 w-4" />}>Send</Button>
              </div>
              <div className="mt-1.5 px-1 text-[11px] text-faint">Enter to send · Shift+Enter for a new line · acting as {user.name}</div>
            </form>
          </Card>

          <div className="space-y-4">
            <Card className="p-4">
              <div className="mb-3 flex items-center justify-between"><h3 className="text-[14px] font-semibold">PR draft</h3>{draft?.is_new && <Badge tone="vio">new item</Badge>}</div>
              <DraftRow icon={<Package className="h-3.5 w-3.5" />} label="Item" value={draft?.item_code ? <span><Mono className="text-accent">{draft.item_code}</Mono> <span className="text-[13px]">{draft.item_description}</span></span> : draft?.item_description} />
              <DraftRow icon={<Hash className="h-3.5 w-3.5" />} label="Quantity" value={draft?.quantity ? `${num(draft.quantity)} ${draft.uom || ""}` : null} />
              <DraftRow icon={<Factory className="h-3.5 w-3.5" />} label="Plant" value={draft?.plant ? `${draft.plant} · ${draft.plant_name}` : null} />
              <DraftRow icon={<CalendarDays className="h-3.5 w-3.5" />} label="Need by" value={draft?.need_by_date ? fmtDate(draft.need_by_date) : null} />
              <DraftRow icon={<Siren className="h-3.5 w-3.5" />} label="Urgency" value={draft?.urgency ? <Badge tone={draft.urgency === "Emergency" ? "bad" : "muted"}>{draft.urgency}</Badge> : null} />
              {draft?.is_new && <DraftRow icon={<Tag className="h-3.5 w-3.5" />} label="Est. unit price" value={draft?.estimated_unit_price ? inr(draft.estimated_unit_price) : null} />}
            </Card>

            <AnimatePresence>
              {preview && (
                <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                  <Card className="border-accent/30 p-4">
                    <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold"><Sparkles className="h-4 w-4 text-accent" /> What the policy will do</div>
                    <div className="flex flex-wrap items-center gap-2"><RouteBadge route={preview.route} /><span className="text-[12px] text-muted">policy v{preview.policy_version}</span></div>
                    <div className="mt-2 grid grid-cols-2 gap-2 text-[13px]">
                      <div><div className="text-[11px] text-muted">Value</div><div className="font-medium tabular">{inr(preview.value)}</div></div>
                      <div><div className="text-[11px] text-muted">{preview.decision === "PO" ? "Supplier" : "Suggested"}</div>
                        <div className="font-medium">{preview.decision === "PO" ? `${preview.supplier_id} @ ${inr(preview.unit_price, 2)}` : (preview.suggested || "buyer to find").replace(/;/g, ", ")}</div></div>
                    </div>
                    {preview.clubbed_with?.length > 0 && <div className="mt-2 text-[12px] text-warn">Will be clubbed with {preview.clubbed_with.join(", ")} (§2.2).</div>}
                    <div className="mt-2 text-[11.5px] leading-relaxed text-muted">{preview.reason}</div>
                  </Card>
                </motion.div>
              )}
            </AnimatePresence>

            <Card className="p-4">
              <h3 className="mb-2 text-[14px] font-semibold">Your recent PRs</h3>
              {mine.length === 0 ? <div className="text-[13px] text-muted">Nothing raised yet.</div> : (
                <div className="space-y-2">
                  {mine.map((r) => (
                    <div key={r.id} className="flex items-center justify-between gap-2 text-[13px]">
                      <div className="min-w-0"><Mono className="text-accent">{r.pr_no}</Mono> <span className="truncate text-muted">{r.description}</span></div>
                      <Badge tone={r.status === "open" ? "warn" : "ok"}>{r.status === "open" ? "with Procurement" : "decided"}</Badge>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

function DraftRow({ icon, label, value }: { icon: React.ReactNode; label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2.5 border-t border-line py-2 first-of-type:border-t-0">
      <span className={cx("mt-0.5 grid h-6 w-6 place-items-center rounded-md", value ? "bg-accent/10 text-accent" : "bg-panel2 text-faint")}>{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="text-[11px] text-muted">{label}</div>
        <motion.div key={String(!!value)} initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-[13.5px]">{value || <span className="text-faint">—</span>}</motion.div>
      </div>
    </div>
  );
}
