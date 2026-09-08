# Multi-Agent Pipeline Reference

Authoritative contract for every external agent wired into the 8-stage pipeline:
what fires it, what file it is handed, the exact schema of that file, what comes
back, and whether a human is in the loop.

Agents are dispatched **automatically by the orchestrator** as their input
artefacts are produced — no operator action starts an agent. The console only
observes their progress and can retry a failed submission.

Platform: Aava AI (`int-ai.aava.ai`). Toggle globally with `AUTO_AGENT_DISPATCH`
in `.env` (default `true`).

---

## 1. Roster at a glance

| Agent | Env var | Stage hook | Trigger | Input artefact | Backend generates it? | Human intervention |
|:------|:--------|:-----------|:--------|:---------------|:----------------------|:-------------------|
| Processing Time Forecast & Calibration Analyst | `CREWAI_AGENT_FORECAST_ID` | `STAGE_1_FORECAST` | Automatic, at ingest | `{batch_id}_forecast_input.csv` + `{batch_id}_run_history.csv` (one zip) | ✅ Yes | ❌ No |
| Enterprise Risk & Anomaly Detection Engine | `CREWAI_AGENT_ANOMALY_ID` | `STAGE_4_ANOMALY` | Automatic | `{batch_id}_candidates.csv` | ✅ Yes | ❌ No |
| Verification Reconciliation & Exception Specialist | `CREWAI_AGENT_RECON_ID` | `STAGE_6_RECON` | Automatic | `{batch_id}_recon_exceptions.csv` | ✅ Yes | ⚠️ Yes — analyst signs off ambiguous tie-breaks |
| SLA Analysis & Urgency Classifier | `CREWAI_AGENT_SLA_ID` | `STAGE_7_SLA` | Automatic | `{batch_id}_sla_metrics.csv` | ✅ Yes | ❌ No |
| Financial Statement Extraction & Traceability | `CREWAI_AGENT_EXTRACTION_ID` | `STAGE_1_EXTRACTION` | Manual only | `{batch_id}_{filename}` (raw statement) | ✅ Yes | ❌ No |
| Frontend Architecture Collab Agent | `CREWAI_AGENT_COLLAB_ID` | `NON_PIPELINE` | Never (dev tool) | `uiux.json` | ❌ No | ✅ Yes — human-authored input |

### Agent IDs

**This document contains no agent IDs, and the code ships no defaults.** An agent
ID is issued by the platform when you create the agent there — it cannot be
guessed, and a wrong one submits your batch data to somebody else's agent.

Create each agent on the platform using the prompt in section 2, copy the ID from
its page, and set the matching `CREWAI_AGENT_*_ID` in `.env`. A stage whose ID is
blank is reported as `SKIPPED — no agent ID configured` and the deterministic local
pipeline result stands, so an unconfigured deployment still runs end to end.

Check what is wired up at any time:

```
GET /api/pipeline/agent/available-agents   # each entry carries `configured: true|false`
```

### Why is there no Stage 5 agent?

Stage 5 is the only pipeline stage with **no agent, by design**. Both of its paths
are places where an LLM's judgement is the wrong instrument:

- **Stage 5a — automated remediation** applies only fixes the architecture calls
  "safe, verifiable patterns": date format normalisation, DR/CR polarity
  realignment, whitespace and quote stripping, currency case normalisation. These
  are deterministic string transforms whose correctness is provable. Routing them
  through a probabilistic model would make a lossless correction non-reproducible
  and unauditable, for no gain.
- **Stage 5b — analyst escalation** is human review by definition. Handing the
  sign-off to an agent would delete the control the stage exists to provide.

The advisory work an agent *could* usefully do here — ranking the escalation
queue, judging whether a suggested fix is safe to apply — is already produced one
stage earlier by the **anomaly agent**, whose per-row output carries
`fix_is_lossless` and `recommended_action` (`AUTO_REMEDIATE` /
`ESCALATE_TO_ANALYST` / `QUARANTINE_ROW`). Stage 5 consumes that judgement rather
than re-requesting it.

> Historical note: `CREWAI_AGENT_SLA_ID` was previously labelled "Stage 5"
> in `.env` and the service comments. That was a mislabel — SLA estimation is
> **Stage 7** in ARCHITECTURE.md, and that is the hook it is wired to
> (`STAGE_7_SLA`). The labels have been corrected; the agent never ran at Stage 5.

### Which agents need a human?

Only **two** points in the whole system block on a person, and neither is an
agent gate:

1. **Stage 5b — Analyst escalation queue** (not an agent). Anomalies the rule
   engine marks `ESCALATED` — duplicate transaction IDs, zero-amount lines,
   malformed amounts, unknown GL accounts, invalid ISO currencies — hold the
   batch at `ESCALATED_FOR_REVIEW`. **Stage 6 does not run until every one is
   resolved**, so an approved correction is matched against the GL rather than
   skipped. Resolve via `POST /batches/{id}/anomalies/{anomaly_id}/resolve` with:
   - `APPROVE` — accepts the derived `suggested_fix`. Rejected with `400` when the
     anomaly has none, which is the case for every escalated row.
   - `OVERRIDE` — writes the analyst's own values. Blank values, and columns not in
     the batch, are rejected.
   - `QUARANTINE` — isolates the row from matching.

   Clearing the last item automatically runs Stages 6 → 8 with no further input.

2. **Stage 6 — ambiguous tie sign-off.** The recon agent *runs* without a human,
   but its tie-breaks are advisory. An ambiguous tie is a case where several GL
   rows match the same bank line equally well; the engine deliberately refuses to
   auto-settle it. An analyst confirms, re-points or leaves the tie unsettled in
   the reconciliation workbench — see section 4.

The forecast, anomaly, SLA and extraction agents are fully autonomous — they
predict, classify and score, they never gate the pipeline, and a failed dispatch
degrades the batch to the deterministic local result rather than stalling it.

---

## 2. Agent contracts

Each agent below carries a **Platform prompt** — the Role / Goal / Backstory /
Task / Expected-output text to paste into the CrewAI (Aava) agent builder.

> **These prompts must be self-contained.** The backend submits every job with
> `userInputs = "{}"` and the artefact as a zipped file attachment — it sends no
> per-run instructions. Everything the agent needs to know about its input schema
> and output contract has to live in its platform configuration. If you change a
> prompt's output shape, update the **Output** row here to match.

### Forecast agent — Processing Time Forecast & Calibration Analyst

| Property | Value |
|:---------|:------|
| **Env var** | `CREWAI_AGENT_FORECAST_ID` (no default — set it from the platform) |
| **Stage hook** | `STAGE_1_FORECAST` — Ingestion, before Stage 2 runs |
| **Trigger** | Automatic, the moment a statement is ingested and **before** it is processed |
| **Dispatched from** | `PipelineOrchestrator.ingest_batch()` → `_dispatch_forecast()` |
| **Input files** | `data/forecasts/{batch_id}_forecast_input.csv` **and** `data/forecasts/{batch_id}_run_history.csv`, both members of one zip |
| **Backend generates them?** | ✅ `run_history_service.write_forecast_input()` and `snapshot_history_for()` |
| **Knowledge base** | `data/forecasts/run_history.csv` — one row per completed run, upserted by the pipeline; the snapshot is its newest 60 terminal rows |
| **Result captured by** | The backend itself: `_await_forecast()` polls the platform every 10 s for up to 15 min, parses the reply into `batch.agent_forecast`, records it in the history row and scores it against the measured wall-clock. No browser needed |
| **Skipped when** | `CREWAI_AGENT_FORECAST_ID` is unset |
| **Human intervention** | ❌ None |

**What this agent is for.** The problem statement asks for processing time to be
predicted from file size and data quality. The local estimator is a formula whose
throughput and queue-wait constants are now calibrated from the run history, but
it cannot reason about *this* file's provenance, its date range, or what happened
to the last twenty batches that looked like it. The agent can. It is handed the
batch's ingest-time features and the history, and asked for a prediction with a
range, a breach probability, and the batches it compared against.

**Honest framing.** The pipeline is synchronous. On a laptop a 500-row batch
finishes in about a second, so the forecast usually arrives after the run and is
scored as a *forecast-accuracy record* rather than acted on. Two cases are
different: a batch that escalates sits at the analyst queue for real wall-clock
time, so the queue-wait prediction is genuinely ahead of reality; and on deployed
infrastructure with realistic volumes the machine time grows to the point where
the forecast is an ETA an operator can act on. Nothing in the contract changes
between those cases.

**Input schema 1** (`{batch_id}_forecast_input.csv`, single row — **ingest-time
features only**):

| Column | Type | Notes |
|:-------|:-----|:------|
| `batch_id`, `received_at`, `source`, `filename` | string | `source` is SFTP / UPLOAD / SAMPLE_FEED |
| `record_count`, `file_size_mb`, `file_size_bytes` | int / float / int | Batch volume |
| `currency`, `booking_date_range` | string | From the statement |
| `declared_record_count`, `actual_record_count`, `declared_control_total`, `declared_vs_actual_count_delta` | int / int / float / int | A non-zero delta predicts a structural-gate quarantine |
| `local_estimate_sec`, `local_est_parse_sec`, `local_est_gate_sec`, `local_est_rule_sec`, `local_est_gl_match_sec` | float | The formula's own estimate and its per-stage split |
| `calibration_source`, `calibration_sample_size`, `baseline_throughput_used` | string / int / float | `DEFAULT` until 5 eligible runs exist, then `HISTORY` |
| `sla_target_seconds` | float | The cut-off budget |

> **Nothing from Stage 3 onwards is in this file.** Anomaly count, escalation
> count and match counts are unknown when the forecast is issued. Including them
> — even as zeros — would leak a false signal and make the forecast un-scoreable.
> The history is how the agent infers what quality to expect.

**Input schema 2** (`{batch_id}_run_history.csv`, newest first, up to 60 rows,
header-only when the deployment is new):

`batch_id`, `completed_at`, `source`, `outcome`
(`RECONCILED | PUBLISHED | ESCALATED_RESOLVED | GATE_QUARANTINED`),
`record_count`, `file_size_mb`, `declared_vs_actual_count_delta`,
`anomaly_count`, `escalated_count`, `matched_count`,
`estimate_at_ingest_sec`, `estimate_final_sec`,
`machine_seconds`, `queue_wait_seconds`, `wall_seconds`,
`throughput_actual_rec_per_sec`, `local_error_pct`, `local_ratio`,
`forecast_error_pct`.

`machine_seconds` is compute across the stages; `queue_wait_seconds` is time
parked at the analyst queue; `wall_seconds` is both and is what the SLA is judged
against. Errors are **signed**: positive means over-estimated.

**Output**: a prediction with a p10–p90 range, breach probability, expected
escalation rate, comparable batches and reasoning. JSON string; the backend
parses it tolerantly (a ```json fence or surrounding prose is fine, but a reply
with no `forecast_seconds` is recorded as `UNPARSEABLE` and nothing is imputed).

#### Platform prompt

**Role**

```
Senior Batch Capacity & Forecasting Analyst — Bank Statement Processing
```

**Goal**

```
Before a bank statement batch is processed, predict how long it will take from
ingest to reconciliation — machine time plus any time it will spend waiting on an
analyst — using only what is known at ingest and the recorded history of batches
that came before it. Give a point estimate, an honest range, and a breach
probability against the SLA budget, and say which past batches you compared it to
so an operator can check your reasoning. Your prediction is scored against the
measured actual once the batch completes, and that score is fed back to you in
the next batch's history, so calibrated uncertainty matters more than a confident
number.
```

**Backstory**

```
You have run capacity planning for a bank's end-of-day batch window for years. You
know that the machine time for a statement is almost linear in its row count on a
given box, that the box changes when the pipeline is redeployed, and that neither
of those is what breaches an SLA — what breaches an SLA is a batch that escalates
and sits in an analyst queue while nobody is looking. So when you forecast, you
first ask how likely this file is to escalate at all, judged by what files of this
size, source and shape did historically, and only then how long the compute will
take. You distrust a formula's constant when the history contradicts it, and you
distrust the history when it is thin: with a handful of runs you widen your range
rather than pretend precision. You never invent a comparable batch that is not in
the history you were given.
```

**Task description**

```
The attached ZIP contains two CSV files.

{batch_id}_forecast_input.csv — one row describing the batch you must forecast,
with only what is known at ingest:

  batch_id, received_at, source, filename
  record_count, file_size_mb, file_size_bytes        batch volume
  currency, booking_date_range                        from the statement itself
  declared_record_count, actual_record_count,
  declared_control_total,
  declared_vs_actual_count_delta                      a non-zero delta usually means
                                                      the structural gate will
                                                      quarantine the file, which is
                                                      a very short run
  local_estimate_sec                                  the pipeline's own formula
                                                      estimate for this batch
  local_est_parse_sec, local_est_gate_sec,
  local_est_rule_sec, local_est_gl_match_sec          its per-stage split
  calibration_source                                  DEFAULT = the formula is using
                                                      its declared constants;
                                                      HISTORY = its throughput was
                                                      derived from past runs
  calibration_sample_size, baseline_throughput_used
  sla_target_seconds                                  the cut-off budget

Anomaly counts, escalation counts and match counts are deliberately absent: they
are not known yet. Infer the likely data quality of this file from the history.

{batch_id}_run_history.csv — every completed batch before this one, newest first,
at most 60 rows. It may contain only a header when the deployment is new. Columns:

  batch_id, completed_at, source
  outcome                    RECONCILED | PUBLISHED | ESCALATED_RESOLVED |
                             GATE_QUARANTINED
  record_count, file_size_mb, declared_vs_actual_count_delta
  anomaly_count, escalated_count, matched_count
  estimate_at_ingest_sec     what the formula said at ingest (quality unknown)
  estimate_final_sec         what it said once quality was known
  machine_seconds            compute across the stages
  queue_wait_seconds         time parked at the analyst queue
  wall_seconds               machine + queue; the SLA is judged on this
  throughput_actual_rec_per_sec
  local_error_pct            signed error of estimate_final_sec vs wall_seconds;
                             positive = over-estimated
  local_ratio                wall_seconds / estimate_final_sec
  forecast_error_pct         signed error of the previous agent forecast for that
                             batch, blank if none was made

Method:

1. Find the comparable batches: similar record_count and file_size_mb first, then
   the same source, then a similar booking_date_range. State which ones you used.
2. From the comparables, estimate the probability this batch escalates
   (escalated_count > 0) and, if it does, the queue wait per escalated row. Queue
   wait is the dominant SLA risk; weight it accordingly.
3. Estimate machine time from the comparables' throughput_actual_rec_per_sec,
   scaled to this batch's record_count. Use local_estimate_sec as a prior, and say
   whether the history tells you the formula is running fast or slow on this
   machine (local_ratio is precomputed for that).
4. Combine into forecast_seconds = expected machine time + expected queue wait,
   with p10_seconds and p90_seconds bounding the plausible range. Widen the range
   when the history is thin or the comparables disagree.
5. Give breach_probability_pct against sla_target_seconds.

Constraints:
- If the history file has no rows, return local_estimate_sec as forecast_seconds,
  confidence LOW, and say so in the reasoning. Do not invent comparables.
- Only list batch_ids that appear in the history file in comparable_batches.
- Do not assume staffing, business hours or cut-off times that are not in the
  data.
- Reason in seconds; do not convert units.
```

**Expected output**

```
A single JSON object, no prose outside it, no markdown fences:

{
  "batch_id": "",
  "forecast_seconds": 0.0,
  "p10_seconds": 0.0,
  "p90_seconds": 0.0,
  "confidence": "HIGH | MEDIUM | LOW",
  "breach_probability_pct": 0,
  "expected_escalation_rate_pct": 0.0,
  "expected_machine_seconds": 0.0,
  "expected_queue_wait_seconds": 0.0,
  "dominant_uncertainty": "ESCALATION_LIKELIHOOD | QUEUE_WAIT | THROUGHPUT | THIN_HISTORY | GATE_QUARANTINE_RISK",
  "comparable_batches": [""],
  "formula_bias_observed": "one sentence: is local_estimate_sec running fast or slow on this machine, per local_ratio",
  "reasoning": "two or three sentences citing the specific history rows and figures relied on",
  "dashboard_line": "one line under 120 characters for an operations banner"
}
```

> The backend reads `forecast_seconds`, `p10_seconds`, `p90_seconds`,
> `confidence`, `breach_probability_pct`, `expected_escalation_rate_pct`,
> `dominant_uncertainty`, `comparable_batches`, `reasoning` and
> `dashboard_line`. Extra keys are kept in the raw output and shown in the
> console's agent report; a missing `forecast_seconds` marks the forecast
> `UNPARSEABLE`.

---

### Anomaly agent — Enterprise Risk & Anomaly Detection Engine

| Property | Value |
|:---------|:------|
| **Env var** | `CREWAI_AGENT_ANOMALY_ID` (no default — set it from the platform) |
| **Stage hook** | `STAGE_4_ANOMALY` — Agentic Anomaly Scorer & Classifier |
| **Trigger** | Automatic, immediately after the Stage 3 rule engine writes the candidates file |
| **Dispatched from** | `PipelineOrchestrator.run_pipeline()` → `_dispatch_agent_async(batch, "STAGE_4_ANOMALY", …)` |
| **Input file** | `File-Gen Scripts/OutPut/anomalies/{batch_id}_candidates.csv` |
| **Backend generates it?** | ✅ `agentic_anomaly_service.evaluate_batch()` writes both `.csv` and `.json` |
| **Skipped when** | The batch has zero anomalies, or `CREWAI_AGENT_ANOMALY_ID` is unset |
| **Human intervention** | ❌ None |

**Input schema** (`{batch_id}_candidates.csv`):

| Column | Type | Notes |
|:-------|:-----|:------|
| `row_index` | int | 0-based row in the ingested frame |
| `external_txn_id` | string | Bank transaction ID |
| `account` | string | e.g. `ACC#00017` |
| `raw_amount` | string | As it appeared in the file, unparsed |
| `booking_date` | string | As it appeared in the file |
| `error_type` | string | `DUPLICATE_TRANSACTION_ID`, `MALFORMED_AMOUNT`, `ZERO_AMOUNT_LINE`, `NON_CANONICAL_DR_CR`, `UNKNOWN_DR_CR`, `UNNORMALIZED_CURRENCY`, `INVALID_ISO_CURRENCY`, `ACCOUNT_FORMAT_DRIFT`, `UNKNOWN_GL_ACCOUNT`, `DATE_FORMAT_SLACK` |
| `category` | enum | `STRUCTURAL` \| `SEMANTIC` \| `TIMING` \| `REFERENTIAL` |
| `severity` | enum | `CRITICAL` \| `HIGH` \| `MEDIUM` \| `LOW` |
| `status` | enum | `AUTO_REMEDIATED` \| `ESCALATED` |
| `confidence_score` | float | 0.00–1.00 |
| `description` | string | Human-readable diagnosis |
| `suggested_fix` | JSON string | The derived correction, e.g. `{"debit_credit": "DR"}`. **Empty for every `ESCALATED` row** — see the note below |
| `override_fields` | list | Columns an analyst must supply to resolve an `ESCALATED` row |

> **`suggested_fix` is only ever a derived correction.** It is populated solely for
> `AUTO_REMEDIATED` rows, where the value comes from the row itself and applying it
> is lossless — mapping `C` to `CR`, upper-casing a currency, normalising a slash
> date, matching an account after whitespace normalisation. An `ESCALATED` row
> carries `null`, because nothing in the row determines the right answer. The
> engine does not guess an account, a currency, a direction or an amount, so there
> is never a fabricated value for an analyst to approve. Those rows are resolved by
> `OVERRIDE` with a real value read off the source statement, or `QUARANTINE`.

**Output**: Enterprise risk analytics assessment — anomaly alert table, KRI
dashboard, scenario analysis, audit log, compliance certification. Returned as a
JSON string in the `output` field of the execution-history response.

> The agent's report is **displayed, not applied**. Nothing it returns is written
> back onto the anomaly records: its severity overrides and recommendations inform
> the analyst, they do not change what the queue offers or auto-resolve anything.

#### Platform prompt

**Role**

```
Senior Enterprise Risk Analytics Specialist — Corporate & Institutional Banking
```

**Goal**

```
Independently review every flagged row in the attached end-of-day bank statement
anomaly candidate file, confirm or overturn the deterministic pre-classification,
assign a defensible risk severity, and surface systemic patterns that a row-by-row
rule engine cannot see. Your assessment is read by operations analysts who must
decide, before the general ledger is touched, which exceptions are safe to
auto-remediate and which must be held for human sign-off.
```

**Backstory**

```
You have spent two decades in corporate banking operations, reconciling BAI2,
MT940 and ISO 20022 CAMT.053 statements against internal GL cashbooks. You have
seen what happens when silent data corruption reaches a ledger: inverted debit and
credit polarity that balances on paper but reverses a customer's position,
transposed day/month dates that shift a settlement across a reporting boundary,
and duplicate transmissions that double-post a wire. You are deliberately
conservative. An upstream rule engine has already pre-classified each row, but you
treat its verdict as a hypothesis, not a fact — you have watched a pattern-matched
"safe" auto-fix corrupt a ledger more than once. You never invent a transaction,
never guess an account, and never mark a row auto-remediable unless the correction
is provably lossless.
```

**Task description**

```
The attached ZIP contains a single CSV, {batch_id}_candidates.csv, listing the
anomalous rows found in one bank statement batch. Every row has these columns:

  row_index          0-based row position in the ingested statement
  external_txn_id    bank transaction identifier
  account            GL account, e.g. ACC#00017
  raw_amount         amount exactly as it appeared in the file, unparsed
  booking_date       date exactly as it appeared in the file
  error_type         one of DUPLICATE_TRANSACTION_ID, MALFORMED_AMOUNT,
                     ZERO_AMOUNT_LINE, NON_CANONICAL_DR_CR, UNKNOWN_DR_CR,
                     UNNORMALIZED_CURRENCY, INVALID_ISO_CURRENCY,
                     ACCOUNT_FORMAT_DRIFT, UNKNOWN_GL_ACCOUNT, DATE_FORMAT_SLACK
  category           STRUCTURAL | SEMANTIC | TIMING | REFERENTIAL
  severity           CRITICAL | HIGH | MEDIUM | LOW
  status             AUTO_REMEDIATED (already corrected) | ESCALATED (held for a human)
  confidence_score   0.00-1.00, the rule engine's confidence
  description        the rule engine's plain-language diagnosis
  suggested_fix      JSON object, e.g. {"debit_credit": "DR"}

For every row:

1. Confirm or correct the category. STRUCTURAL means the field is malformed or the
   record is duplicated. SEMANTIC means the field parses but means the wrong thing
   (inverted DR/CR, wrong currency). TIMING means the date is valid but suspect
   (transposed day/month, forward post-dating). REFERENTIAL means the row points at
   something that does not exist in the chart of accounts.
2. Confirm or correct the severity, judged by ledger impact, not by how odd the row
   looks. A row that would post a wrong signed amount to a real account outranks a
   row that merely fails to parse and is therefore stopped anyway.
3. State whether the suggested_fix is provably lossless. If applying it could
   change the economic meaning of the transaction, it is not.
4. Give your own confidence score and one sentence of reasoning that cites the
   specific field values you relied on.

Then analyse the batch as a whole: cluster the anomalies by account, by error_type
and by category, and report any concentration that suggests a systemic upstream
problem rather than isolated bad rows — for example a single account producing most
of the referential misses, or a date-format fault affecting a contiguous block of
rows, which usually means a feed configuration change rather than data entry error.

Constraints:
- Judge only from the values present in the file. Never infer a correct account
  number, amount or date that is not derivable from the row itself.
- If a row is too ambiguous to classify with confidence, say so and recommend
  human review rather than guessing.
- Never recommend downgrading a DUPLICATE_TRANSACTION_ID below HIGH without an
  explicit, stated reason.
```

**Expected output**

```
A single JSON object, no prose outside it, no markdown fences:

{
  "batch_summary": {
    "total_anomalies": 0,
    "by_category":  {"STRUCTURAL": 0, "SEMANTIC": 0, "TIMING": 0, "REFERENTIAL": 0},
    "by_severity":  {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0},
    "safe_to_auto_remediate": 0,
    "requires_human_review": 0,
    "overall_risk_rating": "CRITICAL | HIGH | MEDIUM | LOW",
    "ledger_release_recommendation": "RELEASE | RELEASE_WITH_EXCEPTIONS | HOLD"
  },
  "assessments": [
    {
      "row_index": 0,
      "external_txn_id": "",
      "agent_category": "STRUCTURAL | SEMANTIC | TIMING | REFERENTIAL",
      "agent_severity": "CRITICAL | HIGH | MEDIUM | LOW",
      "agrees_with_rule_engine": true,
      "disagreement_reason": "null when agrees_with_rule_engine is true",
      "fix_is_lossless": true,
      "recommended_action": "AUTO_REMEDIATE | ESCALATE_TO_ANALYST | QUARANTINE_ROW",
      "agent_confidence": 0.0,
      "reasoning": "one sentence citing the field values relied on"
    }
  ],
  "systemic_findings": [
    {
      "pattern": "short description of the cluster",
      "affected_rows": [0],
      "evidence": "what makes this systemic rather than isolated",
      "likely_root_cause": "e.g. upstream feed format change",
      "recommendation": "operational action to take"
    }
  ],
  "key_risk_indicators": {
    "anomaly_rate_pct": 0.0,
    "critical_exception_count": 0,
    "referential_integrity_breaches": 0,
    "duplicate_transmission_suspected": false
  },
  "audit_note": "two or three sentences an auditor could read as the rationale for the release recommendation"
}
```

---

### Recon agent — Verification Reconciliation & Exception Specialist

| Property | Value |
|:---------|:------|
| **Env var** | `CREWAI_AGENT_RECON_ID` (no default — set it from the platform) |
| **Stage hook** | `STAGE_6_RECON` — GL Reconciliation Exception Review |
| **Trigger** | Automatic, after the 4-tier waterfall finishes and exports its artefacts |
| **Dispatched from** | `PipelineOrchestrator._reconcile_and_finalize()` |
| **Input file** | `data/batch_results/{batch_id}_recon_exceptions.csv` |
| **Backend generates it?** | ✅ `_export_recon_artifacts()` |
| **Skipped when** | The waterfall settled everything, or `CREWAI_AGENT_RECON_ID` is unset |
| **Human intervention** | ⚠️ Advisory: an analyst confirms or overrides the agent's tie-breaks |

**Input schema** (`{batch_id}_recon_exceptions.csv`) — a union of two exception
families, discriminated by `exception_type`:

*Rows with `exception_type = AMBIGUOUS_TIE`:*

| Column | Type | Notes |
|:-------|:-----|:------|
| `tier` | string | Tier that produced the tie |
| `ingest_external_txn_id` | string | Contested bank line |
| `candidate_internal_txn_ids` | list | All equally-scoring GL rows |
| `chosen_internal_txn_id` | string | Engine's provisional pick |
| `chosen_by_reference_score` | float | Reference/narrative token overlap |
| `disambiguated_by_reference` | bool | False means the tie-break was arbitrary |
| `batch_file` | string | Source statement file |

*Rows with `exception_type = RECONCILING_ITEM_BANK_ONLY`:* the full canonical
bank row — `external_txn_id`, `account`, `currency`, `amount`, `debit_credit`,
`booking_date`, `value_date`, `reference`, `narrative`, `_source_batch`.

**Output**: Exception verification report — classification per exception,
recommended match assignments for ambiguous ties, confidence scores. JSON string.

**Sibling artefacts** written by the same step (audit exports, not agent inputs):
`{batch_id}_matched.csv`, `{batch_id}_unmatched_bank.csv`,
`{batch_id}_outstanding_gl.csv`, `{batch_id}_ambiguous.csv`.

#### Platform prompt

**Role**

```
Senior Exception Management Specialist — Bank Reconciliation & Settlement
```

**Goal**

```
Adjudicate every line the 4-tier waterfall could not settle outright. For each
ambiguous tie, recommend which candidate general ledger row the bank line should
settle against and show the evidence. For each bank-only reconciling item, classify
what kind of exception it actually is so an analyst knows whether to wait for it to
clear or raise a journal entry. Your recommendations are advisory: an analyst signs
off before anything posts.
```

**Backstory**

```
You have run the exceptions desk for an institutional bank's daily cash
reconciliation. You know the difference between a deposit in transit and a genuine
missing entry, between an unpresented cheque and a posting error, and you know that
recurring standing orders of identical amounts on identical dates are the single
biggest source of false ambiguity in naive matching. You are acutely aware of the
cost of overmatching: settling a bank line against the wrong ledger row hides two
errors instead of surfacing one, and it is far harder to unwind later than an
unmatched item is to clear. When the evidence does not separate two candidates, you
say so plainly and let the tie stand rather than manufacture a preference.
```

**Task description**

```
The attached ZIP contains {batch_id}_recon_exceptions.csv. It holds two kinds of
row, told apart by the exception_type column.

Rows where exception_type = AMBIGUOUS_TIE — several GL rows matched one bank line
equally well at the same tier:

  tier                          the tier that produced the tie: TIER_1_EXACT,
                                TIER_2_DATE_TOLERANCE, TIER_3_REFERENCE_MATCH or
                                TIER_4_AMOUNT_TOLERANCE
  ingest_external_txn_id        the contested bank transaction
  candidate_internal_txn_ids    every equally-scoring GL candidate
  chosen_internal_txn_id        the engine's provisional pick
  chosen_by_reference_score     reference/narrative token overlap for that pick
  disambiguated_by_reference    false means the pick was arbitrary, not evidenced
  batch_file                    source statement file

Rows where exception_type = RECONCILING_ITEM_BANK_ONLY — a structurally valid bank
line with no GL counterpart at any tier: external_txn_id, account, currency, amount,
debit_credit, booking_date, value_date, reference, narrative, _source_batch.

What the tiers mean, so you can weigh the evidence:
  TIER_1_EXACT             account + amount + value date + direction all identical
  TIER_2_DATE_TOLERANCE    account + amount identical, date within 3 business days
  TIER_3_REFERENCE_MATCH   account + amount plus reference/narrative token overlap
  TIER_4_AMOUNT_TOLERANCE   account matches, amount within $1.00 slack, date within tolerance

For each AMBIGUOUS_TIE:
1. Decide whether the provisional pick should stand. Pay close attention to
   disambiguated_by_reference — when it is false the engine broke the tie on date
   and amount proximity alone, with no textual evidence at all, and that pick
   deserves the most scrutiny.
2. Recommend CONFIRM_PROVISIONAL, SELECT_ALTERNATIVE (naming the GL id) or
   LEAVE_UNSETTLED, and give the evidence: which reference tokens, dates or amounts
   separate the candidates.
3. Flag the tie as a probable recurring standing instruction where the pattern fits
   — identical amounts recurring on a regular cycle against the same account. These
   are the expected, benign source of ambiguity and should be reported as a
   configuration observation, not as a data quality defect.

For each RECONCILING_ITEM_BANK_ONLY, classify it as one of:
  DEPOSIT_IN_TRANSIT | BANK_FEE_OR_CHARGE | INTEREST_POSTING |
  UNRECORDED_RECEIPT | TIMING_DIFFERENCE | SUSPECTED_MISSING_GL_ENTRY | UNKNOWN
using the amount sign, direction, reference and narrative as evidence, and say
whether it should clear on its own or needs a manual GL journal entry.

Constraints:
- Never recommend settling against a GL id that is not in that row's
  candidate_internal_txn_ids list.
- Prefer LEAVE_UNSETTLED over a low-confidence pick. An unmatched item is cheap; a
  wrong match is expensive.
- Do not invent GL entries, amounts or dates.
```

**Expected output**

```
A single JSON object, no prose outside it, no markdown fences:

{
  "exception_summary": {
    "total_exceptions": 0,
    "ambiguous_ties": 0,
    "bank_only_items": 0,
    "ties_confirmed": 0,
    "ties_overturned": 0,
    "ties_left_unsettled": 0,
    "analyst_review_required": 0
  },
  "tie_breaks": [
    {
      "ingest_external_txn_id": "",
      "tier": "",
      "provisional_choice": "",
      "recommendation": "CONFIRM_PROVISIONAL | SELECT_ALTERNATIVE | LEAVE_UNSETTLED",
      "recommended_internal_txn_id": "must be one of the listed candidates, or null",
      "confidence": 0.0,
      "evidence": "the specific tokens, dates or amounts that separate the candidates",
      "recurring_standing_instruction_suspected": false
    }
  ],
  "bank_only_classifications": [
    {
      "external_txn_id": "",
      "classification": "DEPOSIT_IN_TRANSIT | BANK_FEE_OR_CHARGE | INTEREST_POSTING | UNRECORDED_RECEIPT | TIMING_DIFFERENCE | SUSPECTED_MISSING_GL_ENTRY | UNKNOWN",
      "expected_to_self_clear": true,
      "recommended_action": "MONITOR | RAISE_GL_JOURNAL | INVESTIGATE",
      "confidence": 0.0,
      "evidence": "the amount, direction, reference or narrative relied on"
    }
  ],
  "configuration_observations": [
    {
      "observation": "e.g. account ACC#00017 generates repeated identical-amount ties",
      "affected_accounts": [""],
      "recommendation": "e.g. widen Tier 3 reference matching for this account"
    }
  ],
  "analyst_note": "two or three sentences telling the analyst what needs their sign-off and why"
}
```

---

### SLA agent — SLA Analysis & Urgency Classifier

| Property | Value |
|:---------|:------|
| **Env var** | `CREWAI_AGENT_SLA_ID` (no default — set it from the platform) |
| **Stage hook** | `STAGE_7_SLA` — Processing Time & SLA Estimator |
| **Trigger** | Automatic, after the actual run duration is recorded |
| **Dispatched from** | `PipelineOrchestrator._finalize_sla()` |
| **Input file** | `data/sla_metrics/{batch_id}_sla_metrics.csv` |
| **Backend generates it?** | ✅ `time_estimator_service.export_sla_metrics()` |
| **Human intervention** | ❌ None |

**Input schema** (`{batch_id}_sla_metrics.csv`, single row):

`batch_id`, `total_records`, `file_size_mb`, `anomaly_count`, `escalated_count`,
`matched_count`, `unmatched_count`, `ambiguous_count`,
`throughput_records_per_sec`, `estimated_parse_time_sec`,
`estimated_gate_time_sec`, `estimated_rule_time_sec`,
`estimated_anomaly_triage_sec`, `estimated_gl_match_sec`,
`estimated_queue_wait_sec`, `total_estimated_seconds`, `sla_target_seconds`,
`sla_consumed_pct`, `sla_status`, `eta_timestamp`, `actual_duration_seconds`
(wall-clock, including analyst queue wait), `machine_seconds`,
`queue_wait_seconds`, `calibration_source`.

> This artefact is exported for **both** outcomes: a batch parked at
> `ESCALATED_FOR_REVIEW` still gets an SLA vector (with `matched_count = 0`), so
> the urgency classifier can flag a batch that is burning its SLA budget sitting
> in the analyst queue. When the batch is released it is exported again with the
> measured `queue_wait_seconds`.

> **Next step, not done yet:** bundle `{batch_id}_run_history.csv` into this
> agent's zip too, so it can compare the batch against its peers the way the
> forecast agent does. That is a prompt change on the platform as well as a code
> change — the task description above enumerates a single-row schema, and a
> second file would be ignored or misread until the prompt names it.

**Output**: urgency tier (`P1`–`P4`), SLA breach probability, escalation
recommendations. JSON string.

#### Platform prompt

**Role**

```
Senior SLA Compliance Analyst — End-of-Day Batch Operations
```

**Goal**

```
Turn one batch's processing telemetry into an operational urgency call: how likely
this batch is to breach its SLA cut-off, what is actually consuming the budget, and
what the operations desk should do about it right now. Your output drives the alert
banner an operations manager sees, so it must be decisive and specific.
```

**Backstory**

```
You run SLA compliance for a bank's end-of-day batch window, where a missed cut-off
cascades into downstream breaches with corporate customers and clearing houses. You
have learned that machine time is almost never the problem — a batch that misses its
window is usually one that has been sitting in an analyst queue while nobody was
watching. So you weigh queue-wait time far more heavily than raw execution time, and
you are quick to escalate a batch that is burning its budget while parked rather
than while processing. You do not cry wolf: a fast, clean batch gets a calm P4 and
no recommendations.
```

**Task description**

```
The attached ZIP contains {batch_id}_sla_metrics.csv, a single-row feature vector
for one batch:

  batch_id                        batch identifier
  total_records, file_size_mb     batch volume
  anomaly_count                   rows the rule engine flagged
  escalated_count                 rows now waiting on a human analyst
  matched_count, unmatched_count, ambiguous_count
                                  reconciliation outcome, all 0 if the batch is
                                  still held at the analyst queue
  throughput_records_per_sec      effective throughput achieved
  estimated_parse_time_sec, estimated_gate_time_sec, estimated_rule_time_sec,
  estimated_anomaly_triage_sec, estimated_gl_match_sec
                                  per-stage duration breakdown
  total_estimated_seconds         modelled total
  sla_target_seconds              the cut-off budget
  sla_consumed_pct                total_estimated_seconds as a % of the budget
  sla_status                      ON_TRACK (<80%) | AT_RISK (80-100%) | BREACHED (>100%)
  eta_timestamp                   projected completion, UTC
  actual_duration_seconds         measured machine time; blank if not yet complete

Produce:

1. An urgency tier:
     P1  breach certain or already occurred, or a large escalation queue with the
         budget nearly gone — needs intervention now
     P2  credible breach risk on the current trajectory — needs attention this cycle
     P3  within budget but with a factor worth watching
     P4  comfortably clear, no action

2. A breach probability from 0 to 100, with the reasoning stated explicitly.

3. The dominant cost driver. Compare the per-stage estimates against each other and
   name which one owns the budget. Treat estimated_anomaly_triage_sec as human queue
   wait, not compute: when escalated_count is above zero this figure is the analyst
   backlog, it grows in wall-clock time whether or not anyone is working the queue,
   and it is the single most common cause of a real breach.

4. Concrete recommended actions, addressed to the operations desk. "Assign two
   analysts to clear the 14-item escalation queue within 20 minutes" is useful;
   "monitor the situation" is not. Return an empty list when the batch is P4.

5. A one-line status suitable for an operations dashboard banner.

Constraints:
- Reason only from the supplied metrics. Do not assume staffing levels, business
  hours or cut-off times that are not in the file.
- If actual_duration_seconds is present and far below total_estimated_seconds, say
  so — the model is over-estimating and the tier should reflect measured reality.
- Never return P1 or P2 without naming the specific metric that drove it.
```

**Expected output**

```
A single JSON object, no prose outside it, no markdown fences:

{
  "batch_id": "",
  "urgency_tier": "P1 | P2 | P3 | P4",
  "breach_probability_pct": 0,
  "sla_status_confirmed": "ON_TRACK | AT_RISK | BREACHED",
  "agrees_with_computed_status": true,
  "disagreement_reason": "null when agrees_with_computed_status is true",
  "dominant_cost_driver": {
    "stage": "PARSE | GATE | RULE_ENGINE | ANOMALY_TRIAGE | GL_MATCH",
    "seconds": 0.0,
    "share_of_total_pct": 0.0,
    "is_human_queue_wait": false
  },
  "queue_pressure": {
    "escalated_count": 0,
    "estimated_queue_minutes": 0.0,
    "is_primary_breach_risk": false
  },
  "recommended_actions": [
    {
      "action": "specific, addressed to the operations desk",
      "owner": "OPERATIONS_ANALYST | BATCH_ENGINEER | DUTY_MANAGER",
      "urgency": "IMMEDIATE | THIS_CYCLE | ROUTINE"
    }
  ],
  "dashboard_line": "one line under 120 characters for an operations banner",
  "reasoning": "two or three sentences citing the specific metrics that set the tier"
}
```

---

### Extraction agent — Financial Statement Extraction & Traceability

| Property | Value |
|:---------|:------|
| **Env var** | `CREWAI_AGENT_EXTRACTION_ID` (no default — set it from the platform) |
| **Stage hook** | `STAGE_1_EXTRACTION` — Ingestion & Field Extraction |
| **Trigger** | **Manual only** (`auto_dispatch: false`) |
| **Input file** | `data/ingestion_storage/{batch_id}_{filename}` |
| **Backend generates it?** | ✅ Written by `ingestion_service.ingest_file()` during Stage 1 |
| **Human intervention** | ❌ None |

Not auto-dispatched because the deterministic CSV parser already handles the
canonical schema and the common bank column aliases. Reach for this agent when a
statement arrives in a format the parser cannot map — native MT940 or BAI2, or a
proprietary layout. Fire it with:

```
POST /api/pipeline/batches/{batch_id}/agent/classify?stage_key=STAGE_1_EXTRACTION
```

Returns `400` naming the variable to set if `CREWAI_AGENT_EXTRACTION_ID` is blank.

**Output**: extracted fields mapped to the canonical schema, per-field confidence
scores, source line references for audit evidence.

#### Platform prompt

**Role**

```
Senior Financial Data Extraction Engineer — Bank Statement Formats
```

**Goal**

```
Read a raw bank statement in whatever format it arrived — MT940, BAI2, ISO 20022
CAMT.053 or a proprietary delimited layout — and emit each transaction mapped to the
pipeline's canonical schema, with a confidence score and a source line reference for
every single field so the extraction can be audited line by line.
```

**Backstory**

```
You have written statement parsers for a decade and you have met every dialect:
MT940 :61: lines with bank-specific supplementary details, BAI2 continuation records
that wrap a single transaction across several physical lines, mainframe exports
padded with trailing spaces and doubled quotes, and headers that name the same field
five different ways. You never fabricate a value to complete a record. A field you
cannot source from the document is null with a stated reason, because a downstream
general ledger will treat anything you emit as fact, and a plausible guess is far
more dangerous than an honest gap.
```

**Task description**

```
The attached ZIP contains one raw bank statement file, exactly as it was received.
Identify its format, then extract every transaction into this canonical schema:

  external_txn_id   string   unique bank transaction identifier
  account           string   account identifier, e.g. ACC#00017
  currency          string   3-letter ISO 4217 code, uppercase
  amount            decimal  signed, using '.' as the decimal separator, no thousands
                             separators and no currency symbol
  debit_credit      enum     DR or CR
  booking_date      date     ISO 8601, YYYY-MM-DD
  value_date        date     ISO 8601, YYYY-MM-DD
  reference         string   transaction reference, e.g. INV-XXXX or a wire IMAD/OMAD
  narrative         string   free-text description

Also extract the file-level control record when the format carries one: the declared
record count and the declared control total from the trailer. The structural gate
downstream checks these against the actual rows, so report them exactly as declared
— never as the values you computed. If the file has no trailer, return null for both
and say so.

Normalisation rules:
- Normalise CRLF to LF, strip mainframe space padding and doubled quote characters.
- Convert every date to YYYY-MM-DD. When a date is ambiguous between DD/MM and MM/DD
  and the file gives no way to settle it, extract your best reading, mark the field
  low confidence, and record the ambiguity in extraction_warnings.
- Derive debit_credit from the format's own direction marker where one exists. Where
  direction is carried only by the sign of the amount, say so in the field's note
  rather than silently inferring it.
- Reassemble continuation records into one transaction before emitting it.

For every field of every transaction record a confidence score from 0.00 to 1.00 and
a source_line, the 1-based physical line number in the original file the value came
from, so an auditor can trace it back.

Constraints:
- Never invent, complete or infer a value that is not present in the document. Use
  null and give a reason.
- Never silently drop a transaction you could not fully parse: emit it with the
  fields you did resolve, null the rest, and list it in extraction_warnings.
- Preserve amount precision exactly as written. Do not round.
```

**Expected output**

```
A single JSON object, no prose outside it, no markdown fences:

{
  "detected_format": "MT940 | BAI2 | CAMT053 | DELIMITED_CSV | UNKNOWN",
  "format_confidence": 0.0,
  "delimiter": "for delimited formats, else null",
  "encoding_observed": "e.g. UTF-8",
  "control_record": {
    "declared_record_count": 0,
    "declared_control_total": 0.0,
    "trailer_present": true
  },
  "transactions": [
    {
      "external_txn_id": {"value": "", "confidence": 0.0, "source_line": 0, "note": null},
      "account":         {"value": "", "confidence": 0.0, "source_line": 0, "note": null},
      "currency":        {"value": "", "confidence": 0.0, "source_line": 0, "note": null},
      "amount":          {"value": 0.0, "confidence": 0.0, "source_line": 0, "note": null},
      "debit_credit":    {"value": "DR", "confidence": 0.0, "source_line": 0, "note": null},
      "booking_date":    {"value": "YYYY-MM-DD", "confidence": 0.0, "source_line": 0, "note": null},
      "value_date":      {"value": "YYYY-MM-DD", "confidence": 0.0, "source_line": 0, "note": null},
      "reference":       {"value": "", "confidence": 0.0, "source_line": 0, "note": null},
      "narrative":       {"value": "", "confidence": 0.0, "source_line": 0, "note": null}
    }
  ],
  "extraction_warnings": [
    {
      "source_line": 0,
      "issue": "what could not be resolved",
      "affected_field": "canonical field name, or null for a whole-record issue",
      "action_taken": "e.g. emitted as null, best reading marked low confidence"
    }
  ],
  "extraction_summary": {
    "transactions_extracted": 0,
    "transactions_fully_resolved": 0,
    "transactions_with_null_fields": 0,
    "mean_field_confidence": 0.0
  }
}
```

---

### Collab agent — Frontend Architecture Collab Agent

| Property | Value |
|:---------|:------|
| **Env var** | `CREWAI_AGENT_COLLAB_ID` (no default — set it from the platform) |
| **Stage hook** | `NON_PIPELINE` — never dispatched by the orchestrator |
| **Trigger** | Never. This is a developer tool, not a pipeline step |
| **Input file** | `uiux.json` plus tech-stack preferences, human-authored |
| **Backend generates it?** | ❌ No |
| **Human intervention** | ✅ Yes — the input is written by a person |

No platform prompt is documented here: this agent is configured ad hoc by whoever
is using it, its output is read by a developer rather than parsed by the pipeline,
and nothing in the backend depends on its response shape. Do not wire it to a
pipeline `stage_key` — the orchestrator treats `NON_PIPELINE` as never-dispatch.

---

## 3. Where each artefact lives

| Artefact | Path | Written by | Consumed by |
|:---------|:-----|:-----------|:------------|
| Raw statement | `data/ingestion_storage/{batch_id}_{filename}` | `ingestion_service.ingest_file()` | Stage 2 gate, extraction agent |
| Forecast input | `data/forecasts/{batch_id}_forecast_input.csv` | `run_history_service.write_forecast_input()` | **Forecast agent** |
| History snapshot | `data/forecasts/{batch_id}_run_history.csv` | `run_history_service.snapshot_history_for()` | **Forecast agent** (kept so the evidence behind a forecast stays inspectable) |
| Run history (master) | `data/forecasts/run_history.csv` | `run_history_service.record_run()` / `attach_forecast()` | Estimator calibration, `GET /run-history`, the console's history table |
| Quarantined file | `data/quarantined_batches/{filename}` | `_execute_structural_gate()` | Compliance review |
| Anomaly candidates | `File-Gen Scripts/OutPut/anomalies/{batch_id}_candidates.csv` / `.json` | `evaluate_batch()` | **Anomaly agent** |
| Matched pairs | `data/batch_results/{batch_id}_matched.csv` | `_export_recon_artifacts()` | Workbench, audit |
| Bank-only items | `data/batch_results/{batch_id}_unmatched_bank.csv` | `_export_recon_artifacts()` | Workbench, audit |
| GL-only items | `data/batch_results/{batch_id}_outstanding_gl.csv` | `_export_recon_artifacts()` | Workbench, audit |
| Ambiguous ties | `data/batch_results/{batch_id}_ambiguous.csv` | `_export_recon_artifacts()` | Workbench, audit |
| Recon exceptions | `data/batch_results/{batch_id}_recon_exceptions.csv` | `_export_recon_artifacts()` | **Recon agent** |
| SLA metrics | `data/sla_metrics/{batch_id}_sla_metrics.csv` | `export_sla_metrics()` | **SLA agent** |
| Analyst sign-offs | `data/batch_results/{batch_id}_signoffs.csv` | `audit_service.record()` | Auditor, workbench |

Every per-batch one is downloadable through
`GET /api/pipeline/batches/{batch_id}/artifacts/{kind}`, where `kind` is one of
`statement`, `forecast_input`, `run_history`, `anomaly_candidates`, `matched`,
`unmatched_bank`, `outstanding_gl`, `recon_exceptions`, `sla_metrics`. The master
history is `GET /api/pipeline/run-history` (rows + calibration summary) and
`GET /api/pipeline/run-history/file` (the CSV).

**Cross-check result: every auto-dispatched agent has its input file generated by
the backend.** The two gaps that previously blocked full automation —
`{batch_id}_sla_metrics.csv` for the SLA agent and the Stage 6 exception export for
the recon agent — are written by `time_estimator_service.export_sla_metrics()`
and `PipelineOrchestrator._export_recon_artifacts()`; the forecast bundle is
written by `run_history_service` before the Stage 1 dispatch.

### How the run history is measured and used

Each batch carries a stopwatch (`PipelineOrchestrator._clock_*`) that starts
before the file is parsed, banks **machine time** when the batch parks at the
analyst queue, banks **queue wait** when the last escalation clears, and is read
non-destructively when the run is recorded. There is no clock value to pass
around — the previous design passed one, and the resolve path passed a fresh
one, so the queue wait of every escalated batch was recorded as ~0.01 s.

`time_estimator_service` recalibrates lazily whenever the history changes:

| Constant | Derived how | Guard |
|:---------|:------------|:------|
| `baseline_throughput` | Median over eligible runs of `record_count × 1.917 / (machine − parse − gate − anomalies × 0.02)` | Needs 5 eligible runs; runs under 200 rows or 0.2 s machine time are floor noise and excluded; clamped to 100–20 000 rec/s |
| `queue_wait_per_escalation` | Median `queue_wait_seconds / escalated_count` over `ESCALATED_RESOLVED` runs | Needs 3 such runs; clamped to 1–3600 s |
| residual factor | Median measured ÷ estimated machine time | **Display only.** The per-stage coefficients (parse rate, gate divisor, stage weights) are declared, not measured — one total per run cannot separate them |

`GET /batches/{id}/estimator` reports `calibration_source`,
`calibration_sample_size` and `baseline_throughput_used` so the console can say
where a number came from. `GET /batches/{id}/forecast` returns the local
estimate, the agent forecast and the measured actual side by side.

On first start the service backfills the history from any
`{batch_id}_sla_metrics.csv` files already on disk, tagged
`provenance = BACKFILL_SLA_METRICS`. Those are real measurements from earlier
runs, but taken before queue wait was tracked, so their escalated rows fail the
eligibility filter by themselves. Backfilled rows carry the calibration only
while the deployment is young: as soon as five `LIVE` rows (measured with the
current stopwatch, on the current machine) are eligible, only those are used. A
fresh clone starts cold and reports `DEFAULT` until five eligible batches have
completed.

---

## 4. Analyst sign-off & audit trail

The recon agent's tie-breaks are advisory, so the decision has to be recorded
against a person. Sign-off is **append-only**: revising a call writes a new record
carrying `supersedes`, and the record it replaces is never edited or deleted. The
trail is what an auditor reads to see the sequence of calls actually made.

Every write is flushed to `data/batch_results/{batch_id}_signoffs.csv`, so the
trail survives a restart and can be handed over as-is.

### Actions

| Dataset | Valid actions | Meaning |
|:--------|:--------------|:--------|
| `ambiguous` | `CONFIRM_PROVISIONAL` | Settle against the candidate the waterfall provisionally chose |
| | `SELECT_ALTERNATIVE` | Re-point the tie to another candidate — **must** be one of that tie's own `candidate_internal_txn_ids` |
| | `LEAVE_UNSETTLED` | The evidence does not separate the candidates; an unmatched item is cheaper than a wrong match |
| `matched`, `unmatched_bank`, `outstanding_gl` | `ATTEST_REVIEWED` | The analyst has inspected the line and accepts the verdict |
| | `FLAG_FOR_INVESTIGATION` | Needs following up before it is accepted |

The candidate check is enforced server-side and returns `400` listing the entries
that actually competed. Settling a bank line against a GL row that never competed
for it hides two errors instead of surfacing one, and is far harder to unwind later
than an unmatched item is to clear.

### Endpoints

| Endpoint | Method | Purpose |
|:---------|:-------|:--------|
| `/api/pipeline/batches/{id}/recon/{dataset}/signoff` | `POST` | Record a decision (`row_key`, `action`, optional `chosen_internal_txn_id`, `analyst`, `analyst_notes`) |
| `/api/pipeline/batches/{id}/signoffs` | `GET` | Full trail, oldest first. `?effective_only=true` returns only the decision standing per row; `?dataset=` filters |
| `/api/pipeline/batches/{id}/signoffs/file` | `GET` | The trail as CSV |

### In the console

The reconciliation workbench shows a **Sign-off** column per row (`AWAITING` for an
unsigned ambiguous tie), and the docked inspector carries the standing decision plus
a **Sign off** / **Revise sign-off** action. The dialog offers only the actions valid
for the current dataset, lists only that tie's real candidates when re-pointing, and
requires a written rationale for any decision that departs from the engine
(`SELECT_ALTERNATIVE`, `LEAVE_UNSETTLED`, `FLAG_FOR_INVESTIGATION`).

> **Not the same thing as Stage 5b.** The Stage 5b analyst queue *gates* the
> pipeline: Stage 6 will not run until every escalated anomaly is resolved. Stage 6
> sign-off does not gate anything — reconciliation has already run and published.
> It is an attestation recorded over the result.

---

## 5. Dispatch mechanics

Dispatch runs on a background thread, so the external platform never blocks the
synchronous pipeline. Each attempt is recorded on the batch under
`agent_executions[stage_key]`:

```jsonc
{
  "stage": "STAGE_1_FORECAST",
  "agent_id": "<from CREWAI_AGENT_FORECAST_ID>",  // null when that var is unset
  "agent_name": "Processing Time Forecast & Calibration Analyst",
  "trigger": "AUTOMATIC",          // or MANUAL for a retry
  "status": "SUBMITTED",           // PENDING → SUBMITTING → SUBMITTED → IN_PROGRESS → SUCCESS/FAILED, or SKIPPED
  "success": true,
  "job_id": 12345,
  "agent_execution_id": "…",
  "target_file": "BATCH-20260907-A1B2C3_forecast_input.csv",   // primary; names the zip
  "bundled_files": [               // every member of the zip actually sent
    "BATCH-20260907-A1B2C3_forecast_input.csv",
    "BATCH-20260907-A1B2C3_run_history.csv"
  ],
  "submitted_at": "2026-09-07 18:04:11 UTC",
  "output": null,                  // filled in by polling
  "forecast_captured": false       // STAGE_1_FORECAST only: output parsed into batch.agent_forecast
}
```

A manual retry (`/agent/classify`) rebuilds the same bundle the automatic
dispatch sent — the stage → artefact mapping lives in one place
(`_bundle_for_stage`) so the two cannot drift.

`SKIPPED` is a normal outcome, not a failure. A stage is skipped when it produced
no input artefact (a clean batch has no anomalies), when the agent is not
auto-dispatched, when its `CREWAI_AGENT_*_ID` is unset, or when `CREWAI_API_URL` /
`CREWAI_API_KEY` are unset. The `message` field names the variable to set. The
deterministic local pipeline result stands in every case.

### Server-side forecast capture

Every other agent's output is fetched only when the console polls
`/agent/output`. The forecast is different: its answer has to reach the run
history whether or not anyone has the console open, or the knowledge base never
learns. So a successful `STAGE_1_FORECAST` submission starts a bounded poller
thread on the backend that checks the platform every `FORECAST_POLL_SECONDS`
(10 s) for up to `FORECAST_POLL_MAX_ATTEMPTS` (90) and then:

| Result | `batch.agent_forecast.status` | History row |
|:-------|:------------------------------|:------------|
| JSON with `forecast_seconds` | `RECEIVED`, scored once the batch has a measured wall-clock and is not parked | `forecast_seconds`, `forecast_error_pct` (signed) |
| Reply without `forecast_seconds` | `UNPARSEABLE`, raw output kept on the execution | `forecast_status` only; nothing imputed |
| Execution failed on the platform | `FAILED` | `forecast_status` only |
| No terminal state in 15 min | `TIMED_OUT` | `forecast_status` only |
| `CREWAI_AGENT_FORECAST_ID` unset | `SKIPPED` | blank |

A forecast that lands while the batch is still parked at the analyst queue is
held and scored when the batch is released; one that lands before the run row
exists (it cannot today, but the ordering is not guaranteed) is parked and merged
by the next `record_run`. The console's poll shares the same code path
(`_refresh_one`), so it can pick a result up too; both are idempotent.

Restart behaviour: batches, their execution logs and the run history are
persisted in `data/recon.db` and come back after a restart; poller threads do
not. A forecast outstanding at restart is simply never captured, and its row
keeps a blank forecast (the console's poll can still pick it up if the platform
finishes later, since `/agent/output` shares the capture path).

### Endpoints

| Endpoint | Method | Purpose |
|:---------|:-------|:--------|
| `/api/pipeline/batches/{id}/agent/status` | `GET` | Per-stage dispatch log + which artefacts exist |
| `/api/pipeline/batches/{id}/agent/output` | `GET` | Polls the platform for every in-flight execution and returns the refreshed log |
| `/api/pipeline/batches/{id}/agent/classify?stage_key=…` | `POST` | Manual re-dispatch (retry a failed submission, or run a manual-only agent) |
| `/api/pipeline/agent/available-agents` | `GET` | The roster above, including `auto_dispatch` and `human_intervention` flags |
| `/api/pipeline/agent/status` | `GET` | Platform connectivity check |
| `/api/pipeline/agent/execution/{execution_id}` | `GET` | Direct execution lookup by ID |

The anomaly queue polls `/agent/output` every 6 seconds while any execution is
non-terminal, and stops on its own once all are finished.

## 6. Aava AI platform details

| Property | Value |
|:---------|:------|
| **Submission URL** | `POST https://int-ai.aava.ai/agents/execute/agent-executions` |
| **Output retrieval** | `GET https://int-ai.aava.ai/agents/execute/history/execution?execution_id={id}` |
| **Authentication** | `Authorization: Bearer <JWT>` (`CREWAI_API_KEY`) |
| **File format** | Files **must** be `.zip` archives — a raw CSV is rejected. `submit_batch_to_agent(file_path, agent_id, extra_files)` zips the primary artefact plus any extras in memory before posting; the zip is named after the primary. |
| **Submission fields** | `agentId` (int), `userInputs` (string `"{}"`), `files` (binary zip) |
