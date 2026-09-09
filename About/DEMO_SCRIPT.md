# Demo script — Batch File Validator & Processing Time Estimator

Two parts. **Part A** is the teleprompter: read it, one block per screen, about six
minutes total. **Part B** is the flow guide: what to click, what must be true before
you start, and what to do if something is slow.

Keep the story to three problems, in this order. Every screen answers one of them.

| # | Problem (from the brief) | Where we show it |
|---|---|---|
| 1 | Bad data in batch files causes delays and incidents | Structural gate, Anomaly queue |
| 2 | Rectify what can be fixed, escalate the rest to a human | Anomaly queue, Reconciliation workbench |
| 3 | Predict processing time from file size **and** data quality, publish for consumers | Estimator page, Dashboard event log |

---

## Part A — Teleprompter

### 0. Opening (30 s) — on the Batch status board

> Every night a bank's own ledger and the bank statement have to be paired up, line
> by line. The files that arrive are big, they arrive in pieces, and they are
> frequently wrong: a trailer count that doesn't match, a duplicate reference, a
> date that is a day off. Today that is discovered late, by a human, after the
> batch has already sat in a queue.
>
> We built a pipeline that ingests the whole file, refuses the structurally broken
> ones at the door, finds and fixes row-level anomalies, sends only the genuinely
> ambiguous ones to an analyst, reconciles the rest against the ledger, and, before
> any of that runs, tells the downstream teams how long it will take.
>
> Four agents sit inside it. None of them can stall the pipeline. If an agent is
> slow or wrong, the deterministic path still completes and the screen says so.

### 1. Ingest (20 s) — click **Ingest batch**

> One click picks up the next statement from the SFTP dropbox. The full file is
> ingested, never split, so the control totals in the trailer still mean something.
>
> Watch the execution matrix: the stages light up in order, and the agent columns
> show what was dispatched. At this exact moment the forecast agent has already
> been handed the file's size and shape plus the run history. It is predicting
> while we talk.

### 2. Structural gate (40 s) — open **Structural integrity gate**

> Problem one: bad files. Before a single row is validated we check the file as a
> whole: header, trailer, encoding, declared record count against actual, declared
> control total against the sum.
>
> A file that fails here is quarantined in full, with the reason, and nothing
> downstream ever sees it. That is a two-second run instead of a fifteen-minute
> incident. The audit panel shows every check that was made and its result.

### 3. Anomaly queue (60 s) — open **Anomaly & escalation queue**

> Problem two: bad rows, and the split between "fix it" and "ask a human".
>
> The rule engine flags row-level anomalies. The anomaly agent then classifies
> each one: is it a known, safe, mechanical fix such as a trailing space in a
> reference or a date format, or is it something a person must judge, such as a
> duplicate that might be a legitimate repeat payment?
>
> Auto-remediated rows are re-validated after the fix, so we never trust a repair
> blindly. Escalated rows land here, with the agent's reasoning next to them, and
> an analyst either accepts, overrides with their own values, or quarantines the
> row. Every decision is logged with who and when.
>
> Note the counters: remediated, escalated, quarantined. They feed the time
> estimate, because rows waiting on a human are what actually breaks an SLA.

### 4. Reconciliation workbench (60 s) — open **Reconciliation workbench**

> Clean rows are matched against the ledger in a waterfall. Tier one is the exact
> match: same account, amount and date. Only if that finds nothing do we try tier
> two, a date within a couple of days; then tier three, a matching reference; then
> tier four, a small amount difference such as a bank fee. Strict first, loose last,
> so we never take a "probably" when a "certainly" was available.
>
> Ambiguity is the interesting case: two ledger entries that are equally good
> twins for one bank line. The recon agent proposes a tie-break with its reasoning,
> but it cannot decide alone. The analyst signs off, and the sign-off goes into an
> append-only decision log. Click a row and the inspector shows the candidates and
> why each was or wasn't chosen.

### 5. Processing time & SLA analytics (90 s) — open the **Estimator** page

> Problem three: predict how long this takes, from size and from quality, and
> publish it.
>
> Three answers to the same question, side by side.
>
> **Local estimate.** The pipeline's own formula: a per-stage model driven by file
> size and row count, plus the analyst queue wait for escalated rows. Its constants
> start as declared defaults and, once enough runs exist, are re-derived from this
> machine's own history. The badge says which is in play.
>
> **Agent forecast.** An independent prediction, issued at ingest before anything
> ran, from the file's shape and the history of comparable batches. It gives a
> point estimate, a p10 to p90 range and a breach probability, and names the
> batches it compared against so an operator can check the reasoning. Open the
> agent report to see it.
>
> **Measured actual.** What it really took, with machine time and queue wait
> separated. Both predictions are scored against it, and the score is written
> back into the run history, so the next estimate and the next forecast learn.
>
> *(Hover the "i" markers or open "How to read this page" if anyone asks what a
> number means.)*
>
> Two honesty points worth saying out loud. If the agent replies with something
> other than the contract, the page says "no prediction recorded" and shows the
> raw reply. It never invents a number. And while a batch is parked at the analyst
> queue, the actual is shown "and counting", because that wait is the real SLA
> risk, not the compute.

### 6. Publish and close (30 s) — back to the **Batch status board**

> When the batch is reconciled, publish. The downstream event bus log shows the
> event every consumer receives: batch id, counts, outcome, and the timing.
>
> What we have solved: broken files stop at the gate; row anomalies are fixed
> where it is safe and escalated where it is not, with a full audit trail; matching
> is tiered so the strictest rule always wins; and processing time is predicted
> before the run from size and quality, scored after it, and published to the
> people who depend on it.

---

## Part B — Flow guide

### Before the demo (10 minutes, once)

1. `.env` at the repo root has the four agent IDs set (`CREWAI_AGENT_FORECAST_ID`,
   `CREWAI_AGENT_ANOMALY_ID`, `CREWAI_AGENT_RECON_ID`, `CREWAI_AGENT_SLA_ID`) and
   the API key. A blank ID shows as SKIPPED on screen, which is honest but flat.
2. Start the API with a single worker, then the frontend. Confirm the header shows
   the backend as connected.
3. Put at least two statements in `incoming_sftp/`: one clean, one with anomalies
   that will escalate. A file with a wrong trailer count is a bonus for the gate.
4. Run one clean batch end to end and publish it **before** the audience arrives.
   That gives the run history a fresh row, gives the estimator a calibrated badge
   if enough history exists, and warms the agents.
5. Check the forecast agent on the platform returns the JSON contract from
   AGENTS.md, not a narrative. Open the estimator page for the warm-up batch: the
   agent column should say RECEIVED. If it says UNPARSEABLE, fix the agent's
   Expected Output on the platform before the demo, or plan to use it as the
   honesty talking point in section 5.

### Click path

| Step | Screen | Action | What to point at |
|---|---|---|---|
| 0 | Batch status board | Nothing yet | Stage matrix, event bus log at the bottom |
| 1 | Batch status board | **Ingest batch** | Stages turning on, agent columns dispatching |
| 2 | Structural integrity gate | Select the batch | Gate checks and the audit verification panel. If you have a broken file, ingest it here and show the quarantine |
| 3 | Anomaly & escalation queue | Select the batch | Counters, an auto-remediated row, one escalated row. Accept or override one so the queue wait stops |
| 4 | Reconciliation workbench | Select the batch | Tier pills on matched rows, an ambiguous row, the inspector, one sign-off |
| 5 | Estimator | Select the batch | Headline estimate and SLA badge, the three columns, agent report, run history table |
| 6 | Batch status board | **Publish** | New event in the bus log |

### If something is slow or wrong

- **Agent still PENDING on the estimator page.** The backend polls the platform
  itself; the page refreshes every six seconds. Move on and come back at step 6.
  The deterministic estimate and the measured actual are already there.
- **Forecast shows UNPARSEABLE.** Say it: the agent answered in prose, the system
  refused to guess, the raw reply is one click away. Then show the run history
  row with a blank forecast column. This is a feature, not a failure.
- **Anomaly agent SKIPPED.** The rule engine still flags rows; they all route to
  the human queue. The story still works, just without the auto-fix column.
- **Backend disconnected.** Restart the API. Batches and history are on disk and
  reload; in-flight agent polls resume on the next refresh.

### Things not to say

- Do not quote throughput or timing numbers from memory. Read them off the screen;
  they change per machine and per run.
- Do not claim the agents "decide". They classify, propose and predict. Humans
  decide on escalations and ambiguous matches, and the audit log proves it.
