# Corvo Procure: policy-driven PR → PO

A web app where Corvo Engineering's employees raise purchase requests by **chatting**, and a decision engine applies the **procurement policy, stored as versioned data**, to decide for every line: a PO (contract, emergency or spot) or a sourcing request (RFQ, RFP, capex, new item). When Procurement approves a policy amendment, decisions change from its effective date with **no code change**.

- **Engine & API:** Python 3.12 · FastAPI · SQLAlchemy (Postgres or SQLite)
- **UI:** React 18 · TypeScript · Tailwind · Framer Motion
- **AI:** Claude (`claude-opus-5-5`) for chat extraction and amendment reading. A deterministic fallback runs everywhere without a key.

| Doc | What's in it |
|---|---|
| [DECISIONS.md](DECISIONS.md) | Every gap in the policy or data, and what the app does about it, including the supplier-ranking method |
| [APPROACH.md](APPROACH.md) | How it was built, AI tools used, how it was verified |

---

## Run it (one command)

```bash
# optional: put the task kit at ./data/kit (it is gitignored, never committed)
# optional: export ANTHROPIC_API_KEY=...   (enables Claude for chat + amendment reading)
docker compose up --build
```

Open **http://localhost:8000**. If `./data/kit` is absent, go to **Data & audit** and drop the kit files (or a zip of the kit) into the uploader. The data persists in Postgres.

Services: `db` (Postgres 16) and `app` (API + built UI on one port). Both have health checks; `GET /api/health` reports the API, database, data, AI and active policy status.

### Local development

```bash
# API (http://localhost:8000)
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
KIT_DIR=../data/kit .venv/bin/uvicorn app.main:app --reload      # SQLite by default

# UI with hot reload (http://localhost:5173, proxies /api to :8000)
cd frontend && npm install && npm run dev

# Tests (46): the 14 worked examples, preferred lists, rules, amendments, matcher, chat, API
cd backend && KIT_DIR=../data/kit .venv/bin/python -m pytest -q
```

| Env var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./cantill.db` | Any SQLAlchemy URL; `postgres://` is accepted |
| `KIT_DIR` | unset | Folder laid out like the task kit; loaded on first start if the DB is empty |
| `ANTHROPIC_API_KEY` | unset | Enables Claude; without it, chat uses the rule-based extractor and policy changes use the Rule builder or "Edit as JSON" |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Model for chat extraction and amendment reading |
| `STATIC_DIR` | `../frontend/dist` | Built UI served by the API |

### Hosting (Render)

- **Backend (Render):** `render.yaml` is a blueprint: a Docker web service plus a free Postgres. Create the blueprint from the repo, set `ANTHROPIC_API_KEY`, then upload the kit once in **Data & audit**. The Render URL also serves the full app on its own.
- **Frontend (Vercel):** import the repo with **Root Directory = `frontend`**. `frontend/vercel.json` builds the Vite app and proxies `/api/*` to the Render backend, so the UI needs no API URL setting and no CORS. If the Render URL differs, change it in `vercel.json`.

---

## What's in the app

| Screen | For | Primary action |
|---|---|---|
| **Overview** | everyone | The one next step (load data / process PRs / review a run), status, route mix |
| **Raise a PR** | requesters | Chat; the assistant matches the item, asks for anything missing, previews the policy outcome, then raises the PR |
| **Buyer workspace** | buyers | Upload a batch or process chat PRs; each PO or sourcing request has its decision, value, supplier/price or suggestions and **why** (clause, version, contract or PO relied on); **Approve** creates the PO/RFQ, **Override** needs a reason |
| **Policy studio** | Procurement | Version timeline, rule ladder, parameters; **Propose a change** (rule builder / upload amendment / describe it / edit JSON) → plain-language diff → impact preview → approve with effective date |
| **Contracts** | buyers | Register + PDF-only contracts, validity, ceiling usage; **Add contract** extracts it from the signed PDF |
| **Preferred suppliers** | buyers | Ranked list per item as of any date with the score breakdown; **Export top 3 CSV** |
| **Data & audit** | admin | Load/refresh master data; audit log (who, what, when); created POs and sourcing events |

Press **⌘K / Ctrl+K** anywhere to jump to a page or an item's ranking. Choose who you are acting as (top right); every action is recorded with that name.

## API

| Method & path | Purpose |
|---|---|
| `POST /api/process-batch` | PR batch CSV (multipart `file`, or raw CSV body) → `{run_id, summary, decisions[]}`; `?mode=by_date\|latest&name=` |
| `GET /api/runs/{id}/export.csv` | Decisions in the brief's format (`?with_overrides=true` for the buyer's final position) |
| `GET /api/preferred/export.csv?as_of=YYYY-MM-DD` | Top-3 preferred suppliers per item: `item_code,rank,supplier_id,reference_price` |
| `GET /api/preferred?item_code=&as_of=` | Full ranking with score components |
| `POST /api/runs/{id}/approve` · `/override` | Buyer actions (`X-User` header names the actor) |
| `POST /api/chat` | Chat intake turn `{session_id, message}` |
| `GET/POST /api/policies…` | Versions, `draft/ai` (amendment file or text), `draft/manual` (JSON or operations), `{id}/impact`, `{id}/approve`, `{id}/reject` |
| `GET/POST /api/contracts` · `POST /api/contracts/extract` | Contracts; extract one from a signed PDF |
| `POST /api/setup/upload` | Load kit files (CSV, PDF or zip) |
| `GET /api/health` · `GET /api/audit` | Status, audit trail |

Interactive docs: `/docs`.

```bash
curl -F file=@sample_pr_batch.csv -H "X-User: ops" http://localhost:8000/api/process-batch
curl -o run1.csv http://localhost:8000/api/runs/1/export.csv
```

---

## Blind-test runbook (Thu 19 Nov, 10:00–12:00 IST)

1. **Run 1:** Buyer workspace → **Upload PR batch** (mode: *version by requirement date*) → **Export CSV** → save as `submission/<name>__run1.csv`.
2. **Amendment:** Policy studio → **Propose a change** → upload the amendment (or enter it in the **Rule builder**) → read the diff, warnings and **impact preview** → check the effective date → **Approve**.
3. **Run 2:** Buyer workspace → select the run → **Reprocess with current policy** (or upload the batch again) → **Export CSV** → `submission/<name>__run2.csv`.
4. **Preferred lists:** Preferred suppliers → set the given date → **Export top 3** → `submission/<name>__preferred.csv`.
5. Commit and push **only** the `submission/` folder before 12:00.

## Project layout

```
backend/app/engine/     pure decision engine: matcher, clubbing, valuation, contracts, rules, suppliers, consolidation
backend/app/policy/     policy v5.0 as JSON, validation, edit operations, plain-language diff
backend/app/ai/         Claude client, chat intake, amendment reader (each with a fallback)
backend/app/ingest/     contract PDF extraction
backend/app/api/        REST endpoints
backend/tests/          pytest suite
frontend/src/           React app (pages/, components/, lib/)
```

The engine has no database or HTTP code: it takes a dataset, PR lines and the approved policy versions, and returns decisions. The same function serves the API, the chat preview, the impact preview and the tests.
