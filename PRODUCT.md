# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Enterprise Treasury & Finance Operations Teams handling high-volume multi-bank reconciliations, strict regulatory audits, and daily settlement closing under time-critical deadlines.

## Product Purpose
Vanguard Ledger automates the transformation, structural verification, and tiered matching of complex GL cashbook records against sequential bank statement feeds. It eliminates manual spreadsheet matching, isolates corrupted files before rule processing, and provides transparent break resolution.

## Positioning
A deterministic, tiered waterfall reconciliation operating system that pairs rigorous 4-point structural pre-flight gating (encoding, canonical headers, count parity, control totals) with multi-tier matching and narrative token disambiguation.

## Operating Context
- **Environments:** High-throughput financial back-office operations and treasury management workstations.
- **Datasets:** Monolithic 60,000+ row GL cashbook caches and sequential daily/size-batched bank statement drops.
- **Workflows:** 1) Ingest & manifest generation → 2) Structural gatekeeper & quarantine → 3) Tiered waterfall auto-matching → 4) Exception triage & break resolution → 5) Ambiguity analytics & simulation.

## Capabilities and Constraints
- **Deterministic Structural Gate:** Every file must pass 4 mechanical checks (Encoding, 9 Required Headers, Record Count, Control Total sum) before any row reaches the rule engine.
- **Strict Auditability:** Side-by-side GL internal ID vs Bank external ID paired records with immutable export trails.
- **High-Density Performance:** Monospace decimal alignment for currency amounts and sub-second rendering for 50k+ row grids.
- **Defensive Resilience:** Active chaos error injection (`truncate`, `dropped_row`, `duplicate_row`, `tampered_amount`, `missing_column`, `bad_encoding`) and instant `.bak` rollback.

## Brand Commitments
- **Name:** Vanguard Ledger (V-Ledger)
- **Aesthetic & Tone:** Vanguard Precision (Slate & Cyanide). Authoritative, clinical, data-dense, with high-contrast semantic indicators and zero decorative fluff.

## Evidence on Hand
- Full-stack codebase: FastAPI backend (`backend/`) and modern Angular v17+ / Tailwind CSS frontend (`frontend/`).
- Real-world evaluation datasets (`File-Gen Scripts/BenchRec_cash_v1.0_eval.csv`, `OutPut/`).
- Complete REST API specification (`backend/openapi.json`, `backend/openapi.yaml`).

## Product Principles
1. **Precision Over Decoration:** Data is the primary design material; tabular alignment and exact decimal precision outrank visual embellishments.
2. **Defensive Pre-Flight Verification:** Broken or corrupted files are quarantined deterministically before matching to prevent corrupted settlement ledgers.
3. **Waterfall Transparency:** Strictest match rules execute first (Tier 1 Exact → Tier 2 Date Window → Tier 3 Narrative Overlap → Tier 4 Amount Tolerance) to eliminate false over-matching.
4. **Actionable Exception Routing:** Every unmatched row or ambiguous multi-candidate tie is surfaced with full context, evidence scores, and audit trails.

