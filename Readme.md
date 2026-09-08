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

### Processing-time knowledge base

Every completed batch is recorded in `data/forecasts/run_history.csv` with its
machine time and analyst queue wait measured separately. The estimator calibrates
its throughput and queue-wait constants from that file once five batches of 200+
rows have completed, and the forecast agent is handed a snapshot of it with every
new batch. Two deployment consequences:

- **Persistent storage.** Point `FORECAST_DIR` (and the other `*_DIR` settings in
  `.env.example`) at a mounted volume. An ephemeral container filesystem starts
  the history cold on every restart.
- **One API process.** The batch registry, orchestrator and history are
  in-memory with a file behind them. Run `uvicorn` with a single worker; several
  workers or replicas would split batches across processes and interleave
  history writes.

---

## 🚀 Quick Start

### Backend (FastAPI)
```bash
cd backend
python -m uvicorn app.main:app --reload --port 8000
```
- API Documentation: `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/health`

Batches are **not** seeded. Drop a statement CSV into `incoming_sftp/` before
starting, or upload one from the console — the pipeline runs automatically from
ingestion through to publish. Picked-up files move to `incoming_sftp/processed/`
so a restart does not re-ingest them.

### Frontend (Angular 19)
```bash
cd frontend
npm start
```
- Web Application: `http://localhost:4200`

Use `npm start` / `npm run build` rather than `ng serve` / `ng build` directly:
the `pre*` hooks regenerate the API URL from `.env` first.