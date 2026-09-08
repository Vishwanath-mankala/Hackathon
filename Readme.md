Full pipeline include FE, BE, SMTP & Agentic Integrations repo.
# Bank Reconciliation Batch File Validator & Processing Time Estimator

An enterprise-grade, end-of-day bank reconciliation platform featuring automated structural gating, agentic anomaly detection, multi-tier waterfall matching, predictive SLA estimation, and downstream publishing.

---

## 📚 Key Documentation

- **[8-Stage Pipeline Architecture](file:///c:/Projects/Hackathon/ARCHITECTURE.md)**: Complete technical specification and flow diagram of all 8 pipeline stages from raw ingestion to downstream publication.
- **[Product Specification](file:///c:/Projects/Hackathon/PRODUCT.md)**: Core business requirements, persona briefs, and user journey.
- **[Frontend Design System](file:///c:/Projects/Hackathon/FRONTEND_DESIGN_SYSTEM.md)**: UI/UX standards, typography (IBM Plex), zero-radius borders, and docked inspector guidelines.
- **[Visual Design Specification](file:///c:/Projects/Hackathon/DESIGN.md)**: High-density financial analyst workstation design philosophy.

- **[Multi-Agent Pipeline Reference](AGENTS.md)**: Every agent's trigger, input schema, output contract, platform prompt, and the analyst sign-off audit trail.

---

## ⚙️ Configuration

One file, at the repo root:

```bash
cp .env.example .env
```

`.env` is the **only** configuration file in the repository. The backend reads it
directly; the Angular app reads it at build time and writes
`frontend/src/environments/environment.generated.ts` (a git-ignored build
artefact — change `.env`, not that file).

A copy anywhere else — `backend/.env`, or one relative to wherever you launched
from — is ignored, and the API logs a warning if it finds one.

Agent IDs are blank by default and have no fallbacks: an ID is issued by the
agent platform and cannot be guessed. A stage with a blank ID reports
`SKIPPED — no agent ID configured`, and the deterministic pipeline still runs
end to end. See [AGENTS.md](AGENTS.md) for the prompt to create each agent with.
The agents are `CREWAI_AGENT_FORECAST_ID` (Stage 1 processing-time forecast),
`CREWAI_AGENT_ANOMALY_ID` (Stage 4), `CREWAI_AGENT_RECON_ID` (Stage 6),
`CREWAI_AGENT_SLA_ID` (Stage 7) and `CREWAI_AGENT_EXTRACTION_ID` (manual only).

### Deploying

The backend is a long-running process (background agent threads, a SQLite
file, a 15 s startup that parses the GL cache), so it needs a real web service,
not serverless functions. The frontend is a static Angular build.

**Backend on Render.** `render.yaml` at the repo root is a Blueprint: connect
the repo, choose *Blueprint*, and Render creates the `recon-api` web service
with a 1 GB disk at `/var/data` and every `*_DIR` / `DB_PATH` pointed at it.
It prompts for `CREWAI_API_KEY` and the `CREWAI_AGENT_*_ID` values; leave an
ID blank to have that stage report `SKIPPED`. Health check is `/health`. The
GL cache and the 65-file demo feed are tracked in git under
`File-Gen Scripts/OutPut/`, so a fresh deploy has them. A persistent disk needs
a paid instance; on the free tier the app still runs but starts cold on every
deploy or restart.

**Frontend on Vercel.** Import the repo with *Root Directory* set to
`frontend`; `frontend/vercel.json` supplies the build command, the output
directory (`dist/frontend/browser`) and the SPA rewrite. Set one environment
variable, `API_BASE_URL`, to the Render service URL (for example
`https://recon-api.onrender.com`) — the build reads it from the environment
when there is no `.env`. CORS on the API is open, so no backend change is
needed for the Vercel origin.

### Processing-time knowledge base

Every completed batch is recorded in `data/forecasts/run_history.csv` with its
machine time and analyst queue wait measured separately. The estimator calibrates
its throughput and queue-wait constants from that file once five batches of 200+
rows have completed, and the forecast agent is handed a snapshot of it with every
new batch. Two deployment consequences:

- **Persistent storage.** Point `DB_PATH`, `FORECAST_DIR` and the other `*_DIR`
  settings in `.env.example` at a mounted volume. An ephemeral container
  filesystem starts the history cold on every restart.
- **One API process.** The batch registry, orchestrator and history are an
  in-memory cache over `data/recon.db`. Run `uvicorn` with a single worker;
  several workers or replicas would each hold their own cache and disagree.

---

## 🚀 Quick Start

### Backend (FastAPI)
```bash
cd backend
python -m uvicorn app.main:app --reload --port 8000
```
- API Documentation: `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/health`

Batches are **not** seeded. Three ways a statement enters the pipeline, and it
runs automatically from ingestion through to publish for each:

- **Pull next feed batch** (console button, `POST /api/pipeline/simulate-sftp`)
  takes the next file from the sample-feed queue. The queue is
  `File-Gen Scripts/OutPut/ingestion_batches/manifest.csv` loaded into the
  database at startup, so its position survives restarts and `--reload`: 65
  pulls walk `ingest_batch_0001.csv` → `0065`, each with the manifest's declared
  record count and control total going through the structural gate. Regenerate
  the feed with `python "File-Gen Scripts/split_recon_feed.py" --input "File-Gen Scripts/BenchRec_cash_v1.0_eval.csv"`;
  the queue picks up the new manifest on the next start (or `POST /api/pipeline/feed/reset`).
- **Upload** from the console (`POST /api/pipeline/ingest`).
- **Real SFTP drop**: a CSV in `incoming_sftp/` is ingested by the startup poll
  and moved to `incoming_sftp/processed/`.

**Durable state** lives in `data/recon.db` (SQLite, stdlib, no server): the
batch registry, anomalies, match results, the feed queue and the run history.
A restart restores every batch, rebuilds the GL cache minus the rows earlier
batches already settled, and lets an analyst resolve a batch that was parked at
the escalation queue before the restart — with the wait counted. Delete the
file to start completely clean; `POST /api/pipeline/feed/reset` (the console's
**Reset feed** button) forgets the batches and requeues the feed while keeping
the run history and sign-off trails.

### Frontend (Angular 19)
```bash
cd frontend
npm start
```
- Web Application: `http://localhost:4200`

Use `npm start` / `npm run build` rather than `ng serve` / `ng build` directly:
the `pre*` hooks regenerate the API URL from `.env` first.