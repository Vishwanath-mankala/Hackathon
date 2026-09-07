# Multi-Agent Pipeline Reference

## Configured Agents

| Agent ID | Name | Pipeline Stage | Role |
|:---------|:-----|:---------------|:-----|
| **56800** | Enterprise Risk And Anomaly Detection Engine A5 | Stage 4: Agentic Anomaly Scorer | Senior Enterprise Risk Analytics Specialist |
| **55551** | Agent2 SLA Analysis and Urgency Detection JSON Classifier Agent | Stage 7: Time & SLA Estimator | Senior SLA Compliance Analyst |
| **56797** | Senior Healthcare Provider Verification Reconciliation Agent | Stage 6: GL Reconciliation Engine | Senior Exception Management Specialist |
| **56231** | Financial Statement Data Extraction And Evidence Traceability Agent | Stage 2: Ingestion & Extraction | Senior Financial Data Extraction Engineer |
| **7723** | Frontend Architecture Collab Agent | Cross-cutting (not pipeline-critical) | General Collab |

---

## Agent Details

### Agent 56800 — Enterprise Risk & Anomaly Detection Engine A5

| Property | Value |
|:---------|:------|
| **Environment Variable** | `CREWAI_AGENT_ANOMALY_ID=56800` |
| **Pipeline Stage** | Stage 4: Agentic Anomaly Scorer & Classifier |
| **Trigger** | Automatic — after Stage 3 row-level rule engine completes and `{batch_id}_candidates.csv` is generated |
| **Input** | ZIP archive containing `{batch_id}_candidates.csv` (or full batch CSV if no anomalies found) |
| **Input Format** | `.zip` file submitted as `multipart/form-data` with fields: `agentId=56800`, `userInputs="{}"`, `files=(binary)` |
| **Input File Schema** | CSV with columns: `row_index`, `external_txn_id`, `account`, `raw_amount`, `booking_date`, `error_type`, `category`, `severity`, `status`, `confidence_score`, `description`, `suggested_fix` |
| **Output** | Enterprise Risk Analytics Assessment Report |
| **Output Format** | JSON string in `output` field containing: anomaly alerts table, KRI dashboard, scenario analysis, audit log, compliance certification |
| **Backend Generates Input?** | ✅ Yes — `agentic_anomaly_service.evaluate_batch()` writes `{batch_id}_candidates.csv` and `.json` to `data/anomalies/` |
| **Human Intervention** | ❌ No — fully automatic classification and scoring |

---

### Agent 55551 — SLA Analysis & Urgency Detection Classifier

| Property | Value |
|:---------|:------|
| **Environment Variable** | `CREWAI_AGENT_SLA_ID=55551` |
| **Pipeline Stage** | Stage 7: Time & SLA Estimator |
| **Trigger** | Automatic — after Stage 6 reconciliation completes with time estimate data |
| **Input** | ZIP archive containing batch time estimate and anomaly triage metrics |
| **Input Format** | `.zip` file submitted as `multipart/form-data` with fields: `agentId=55551`, `userInputs="{}"`, `files=(binary)` |
| **Input File Schema** | CSV/JSON with: `batch_id`, `total_records`, `anomaly_count`, `escalated_count`, `throughput_records_per_sec`, `total_estimated_seconds`, `sla_status`, `eta_timestamp` |
| **Output** | SLA compliance classification, urgency level, recommended actions |
| **Output Format** | JSON string with urgency tier (`P1`/`P2`/`P3`/`P4`), breach risk percentage, escalation recommendations |
| **Backend Generates Input?** | ⚠️ Partial — `time_estimator_service` calculates the model but does NOT currently export a file for this agent. **Needs: export `{batch_id}_sla_metrics.csv` from `time_estimator_service`** |
| **Human Intervention** | ❌ No — automatic SLA classification |

---

### Agent 56797 — Verification Reconciliation & Exception Specialist

| Property | Value |
|:---------|:------|
| **Environment Variable** | `CREWAI_AGENT_RECON_ID=56797` |
| **Pipeline Stage** | Stage 6: GL Reconciliation Engine |
| **Trigger** | Automatic — after GL matching completes, specifically for unmatched/ambiguous items |
| **Input** | ZIP archive containing unmatched reconciling items and ambiguous matches |
| **Input Format** | `.zip` file submitted as `multipart/form-data` with fields: `agentId=56797`, `userInputs="{}"`, `files=(binary)` |
| **Input File Schema** | CSV with columns from matched/unmatched/ambiguous result sets: `account`, `external_txn_id`, `internal_txn_id`, `amount`, `value_date`, `booking_date`, `matchRule`, `candidate_internal_txn_ids`, `chosen_by_reference_score` |
| **Output** | Exception verification report, recommended tie-breaks for ambiguous matches |
| **Output Format** | JSON string with exception classification, recommended match assignments, confidence scores |
| **Backend Generates Input?** | ⚠️ Partial — `pipeline_orchestrator._execute_gl_matching()` stores results in memory (`batch_match_results`) but does NOT export unmatched/ambiguous items as CSV files. **Needs: export `{batch_id}_unmatched.csv` and `{batch_id}_ambiguous.csv` from GL matching** |
| **Human Intervention** | ⚠️ Maybe — for ambiguous tie-breaking where agent confidence is low; analyst confirms or overrides suggested match |

---

### Agent 56231 — Financial Statement Data Extraction & Evidence Traceability

| Property | Value |
|:---------|:------|
| **Environment Variable** | `CREWAI_AGENT_EXTRACTION_ID=56231` |
| **Pipeline Stage** | Stage 1-2: Ingestion & Structural Gate |
| **Trigger** | Optional — for complex multi-format files (MT940, BAI2) requiring intelligent parsing |
| **Input** | ZIP archive containing raw bank statement file |
| **Input Format** | `.zip` file submitted as `multipart/form-data` with fields: `agentId=56231`, `userInputs="{}"`, `files=(binary)` |
| **Input File Schema** | Raw bank statement file (CSV, MT940, BAI2) as-is from ingestion |
| **Output** | Structured extracted data with field evidence traceability |
| **Output Format** | JSON with extracted fields mapped to canonical schema, confidence scores per field, source line references |
| **Backend Generates Input?** | ✅ Yes — raw file is stored in `data/ingestion_storage/{batch_id}_{filename}` during Stage 1 |
| **Human Intervention** | ❌ No — automatic extraction |

---

### Agent 7723 — Frontend Architecture Collab Agent

| Property | Value |
|:---------|:------|
| **Environment Variable** | `CREWAI_AGENT_COLLAB_ID=7723` |
| **Pipeline Stage** | Cross-cutting (not part of pipeline flow) |
| **Trigger** | Manual — developer tool, not production pipeline |
| **Input** | UI/UX specification files |
| **Input Format** | `.zip` containing `uiux.json` and tech stack preferences |
| **Output** | Frontend architecture plan |
| **Output Format** | JSON |
| **Backend Generates Input?** | ❌ No — requires manual UI/UX input files |
| **Human Intervention** | ✅ Yes — this is a human-driven collaboration tool |

---

## API Endpoints for Agent Operations

| Endpoint | Method | Description |
|:---------|:-------|:------------|
| `/api/pipeline/batches/{batch_id}/agent/classify` | `POST` | Submit batch/anomaly file to specified agent |
| `/api/pipeline/batches/{batch_id}/agent/status` | `GET` | Check agent execution metadata |
| `/api/pipeline/batches/{batch_id}/agent/output` | `GET` | Fetch agent execution output |
| `/api/pipeline/agent/available-agents` | `GET` | List configured multi-agent roster |
| `/api/pipeline/agent/status` | `GET` | Test agent platform connectivity |
| `/api/pipeline/agent/execution/{execution_id}` | `GET` | Direct execution lookup by ID |

## Aava AI Platform Details

| Property | Value |
|:---------|:------|
| **Submission URL** | `POST https://int-ai.aava.ai/agents/execute/agent-executions` |
| **Output Retrieval URL** | `GET https://int-ai.aava.ai/agents/execute/history/execution?execution_id={id}` |
| **Authentication** | `Authorization: Bearer <JWT_TOKEN>` |
| **File Format** | Files MUST be packaged as `.zip` archives (raw CSV rejected) |
| **Submission Fields** | `agentId` (int), `userInputs` (string `"{}"`), `files` (binary zip) |

## Missing Backend File Exports (Required for Full Automation)

| Agent | Missing File | What Needs to Be Generated |
|:------|:-------------|:---------------------------|
| **55551** (SLA) | `{batch_id}_sla_metrics.csv` | Export from `time_estimator_service` after SLA calculation |
| **56797** (Recon) | `{batch_id}_unmatched.csv` | Export unmatched reconciling items from `_execute_gl_matching()` |
| **56797** (Recon) | `{batch_id}_ambiguous.csv` | Export ambiguous match candidates from `_execute_gl_matching()` |
