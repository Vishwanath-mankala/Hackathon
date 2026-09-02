"""
rule_engine.py

A tiered, configurable rule engine that matches ingestion (bank statement)
transactions against a cache (GL/cashbook) of unmatched internal
transactions, simulating sequential batch arrival.

DESIGN
------
- Cache is loaded once, in memory, and shrinks as matches are found.
- Ingestion batches are processed IN ORDER (per manifest.csv), simulating
  real sequential arrival. An ingestion row unmatched in one batch is
  retried against whatever remains in the cache, but is not retried
  against later ingestion batches (bank statements don't match each other).
- Rules run as a waterfall: TIER 1 (strictest) is tried first; only if it
  finds nothing does the engine fall back to looser tiers. This avoids
  "overmatching" on a loose rule when a tight one was available.
- Direction (DR/CR) is deliberately IGNORED by default -- matching is done
  on absolute amount. This is the safe default when the sign convention
  between two systems is unknown; flip DIRECTION_MODE once you've
  confirmed the real convention from actual match outcomes.
- Every config value below is a knob, not a hardcoded assumption -- tune
  these against real results.

USAGE
-----
    python rule_engine.py --cache cache_gl_cashbook.csv \\
                           --manifest ingestion_batches/manifest.csv \\
                           --batches-dir ingestion_batches \\
                           --out-dir /mnt/user-data/outputs/recon_results
"""

import argparse
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, date

import pandas as pd

from structural_gate import run_gate, declared_counts_from_manifest


# ---------------------------------------------------------------------------
# CONFIG -- tune these once you see real match rates against real data
# ---------------------------------------------------------------------------
@dataclass
class MatchConfig:
    date_tolerance_days: int = 3          # Tier 2 fallback window
    amount_abs_tolerance: float = 1.00    # Tier 4: absolute currency slack (fees/rounding)
    amount_pct_tolerance: float = 0.0     # Tier 4: extra % slack on top of abs tolerance
    direction_mode: str = "ignore"        # "same" | "opposite" | "ignore"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_amount(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def parse_date(v):
    try:
        return pd.to_datetime(v, errors="raise").date()
    except Exception:
        return None


def direction_ok(cache_row, ingest_row, cfg: MatchConfig):
    if cfg.direction_mode == "ignore":
        return True
    c_dc = str(cache_row.get("debit_credit", "")).strip().upper()
    i_dc = str(ingest_row.get("debit_credit", "")).strip().upper()
    if cfg.direction_mode == "same":
        return c_dc == i_dc
    if cfg.direction_mode == "opposite":
        opp = {"DR": "CR", "CR": "DR"}
        return opp.get(c_dc) == i_dc
    return True


def reference_overlap(cache_row, ingest_row):
    """Loose substring check: does either reference/narrative appear in the other?"""
    fields_cache = " ".join([
        str(cache_row.get("reference", "")), str(cache_row.get("narrative", "")),
        str(cache_row.get("allocation", "")),
    ]).lower()
    fields_ingest = " ".join([
        str(ingest_row.get("reference", "")), str(ingest_row.get("narrative", "")),
    ]).lower()
    if not fields_cache.strip() or not fields_ingest.strip():
        return False
    tokens_ingest = [t for t in fields_ingest.replace("/", " ").split() if len(t) >= 5]
    return any(t in fields_cache for t in tokens_ingest)


def reference_similarity_score(cache_row, ingest_row):
    """
    Numeric version of reference_overlap, used to break ties between
    multiple equally-valid candidates (e.g. several cache rows with the
    identical account+amount+date -- a recurring/standing-instruction
    amount). Counts how many distinct meaningful tokens (len >= 5, to
    skip currency codes/short noise) from the ingestion reference and
    narrative also appear in the cache candidate's reference, narrative,
    or allocation fields. Higher score = more likely the true match.
    Returns 0 when there's nothing useful to compare (e.g. either side's
    text fields are empty) -- ties then fall through to date/amount
    closeness exactly as before.
    """
    fields_cache = " ".join([
        str(cache_row.get("reference", "")), str(cache_row.get("narrative", "")),
        str(cache_row.get("allocation", "")),
    ]).lower()
    fields_ingest = " ".join([
        str(ingest_row.get("reference", "")), str(ingest_row.get("narrative", "")),
    ]).lower()
    if not fields_cache.strip() or not fields_ingest.strip():
        return 0
    tokens_ingest = {t for t in fields_ingest.replace("/", " ").split() if len(t) >= 5}
    return sum(1 for t in tokens_ingest if t in fields_cache)


# ---------------------------------------------------------------------------
# Rule tiers -- each returns True/False given a prepared (cache_row, ingest_row)
# with pre-parsed 'amount_abs' and 'date_parsed' fields already attached.
# Ordered strictest -> loosest. First tier with ANY candidate wins.
# ---------------------------------------------------------------------------
def tier_1_exact(c, i, cfg):
    return (
        c["account"] == i["account"]
        and c["amount_abs"] is not None and i["amount_abs"] is not None
        and abs(c["amount_abs"] - i["amount_abs"]) < 1e-6
        and c["date_parsed"] is not None and i["date_parsed"] is not None
        and c["date_parsed"] == i["date_parsed"]
        and direction_ok(c, i, cfg)
    )


def tier_2_date_tolerance(c, i, cfg):
    if c["account"] != i["account"]:
        return False
    if c["amount_abs"] is None or i["amount_abs"] is None:
        return False
    if abs(c["amount_abs"] - i["amount_abs"]) >= 1e-6:
        return False
    if c["date_parsed"] is None or i["date_parsed"] is None:
        return False
    if abs((c["date_parsed"] - i["date_parsed"]).days) > cfg.date_tolerance_days:
        return False
    return direction_ok(c, i, cfg)


def tier_3_reference_match(c, i, cfg):
    if c["account"] != i["account"]:
        return False
    if c["amount_abs"] is None or i["amount_abs"] is None:
        return False
    if abs(c["amount_abs"] - i["amount_abs"]) >= 1e-6:
        return False
    return reference_overlap(c, i) and direction_ok(c, i, cfg)


def tier_4_amount_tolerance(c, i, cfg):
    if c["account"] != i["account"]:
        return False
    if c["amount_abs"] is None or i["amount_abs"] is None:
        return False
    diff = abs(c["amount_abs"] - i["amount_abs"])
    allowed = cfg.amount_abs_tolerance + cfg.amount_pct_tolerance * max(c["amount_abs"], i["amount_abs"])
    if diff > allowed:
        return False
    if c["date_parsed"] is None or i["date_parsed"] is None:
        return False
    if abs((c["date_parsed"] - i["date_parsed"]).days) > cfg.date_tolerance_days:
        return False
    return direction_ok(c, i, cfg)


TIERS = [
    ("TIER_1_EXACT", tier_1_exact),
    ("TIER_2_DATE_TOLERANCE", tier_2_date_tolerance),
    ("TIER_3_REFERENCE_MATCH", tier_3_reference_match),
    ("TIER_4_AMOUNT_TOLERANCE", tier_4_amount_tolerance),
]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class RuleEngine:
    def __init__(self, cache_df: pd.DataFrame, cfg: MatchConfig):
        self.cfg = cfg
        self.cache = []
        for _, row in cache_df.iterrows():
            r = row.to_dict()
            r["amount_abs"] = abs(parse_amount(r.get("amount"))) if parse_amount(r.get("amount")) is not None else None
            r["date_parsed"] = parse_date(r.get("value_date") or r.get("txn_date"))
            self.cache.append(r)

        self.matches = []
        self.ambiguous = []
        self.unmatched_ingest = []

    def _prep_ingest(self, row: dict):
        r = dict(row)
        amt = parse_amount(r.get("amount"))
        r["amount_abs"] = abs(amt) if amt is not None else None
        r["date_parsed"] = parse_date(r.get("value_date") or r.get("booking_date"))
        return r

    def process_batch(self, batch_df: pd.DataFrame, batch_file: str):
        for _, raw in batch_df.iterrows():
            ingest_row = self._prep_ingest(raw.to_dict())
            matched = self._match_one(ingest_row, batch_file)
            if not matched:
                ingest_row["_source_batch"] = batch_file
                self.unmatched_ingest.append(ingest_row)

    def _match_one(self, ingest_row, batch_file):
        for tier_name, tier_fn in TIERS:
            candidates = [c for c in self.cache if tier_fn(c, ingest_row, self.cfg)]
            if not candidates:
                continue
            if len(candidates) > 1:
                # Tie-break priority: 1) reference/narrative text overlap
                # (highest similarity wins -- this is the actual evidence
                # that distinguishes two otherwise-identical candidates,
                # e.g. two standing-instruction payments of the same
                # amount on the same day), 2) closest date, 3) smallest
                # amount diff, as a last resort when there's no text signal
                # at all.
                candidates.sort(key=lambda c: (
                    -reference_similarity_score(c, ingest_row),
                    abs((c["date_parsed"] - ingest_row["date_parsed"]).days)
                    if c["date_parsed"] and ingest_row["date_parsed"] else 999,
                    abs((c["amount_abs"] or 0) - (ingest_row["amount_abs"] or 0)),
                ))
                top_score = reference_similarity_score(candidates[0], ingest_row)
                self.ambiguous.append({
                    "tier": tier_name,
                    "ingest_external_txn_id": ingest_row.get("external_txn_id"),
                    "candidate_internal_txn_ids": [c.get("internal_txn_id") for c in candidates],
                    "chosen_internal_txn_id": candidates[0].get("internal_txn_id"),
                    "chosen_by_reference_score": top_score,
                    "disambiguated_by_reference": top_score > 0,
                    "batch_file": batch_file,
                })
            chosen = candidates[0]
            self._record_match(chosen, ingest_row, tier_name, batch_file)
            self.cache.remove(chosen)
            return True
        return False

    def _record_match(self, cache_row, ingest_row, tier_name, batch_file):
        self.matches.append({
            "matchId": str(uuid.uuid4()),
            "matchDate": datetime.now().date().isoformat(),
            "matchRule": tier_name,
            "matchedBy": "rule_engine",
            "wasPreviouslyMismatched": 0,
            "internal_txn_id": cache_row.get("internal_txn_id"),
            "external_txn_id": ingest_row.get("external_txn_id"),
            "account": cache_row.get("account"),
            "currency": cache_row.get("currency"),
            "cache_amount": cache_row.get("amount"),
            "ingest_amount": ingest_row.get("amount"),
            "cache_date": cache_row.get("value_date") or cache_row.get("txn_date"),
            "ingest_date": ingest_row.get("value_date") or ingest_row.get("booking_date"),
            "cache_reference": cache_row.get("reference"),
            "ingest_reference": ingest_row.get("reference"),
            "batch_file": batch_file,
        })

    def remaining_cache_df(self):
        cols = [c for c in self.cache[0].keys() if c not in ("amount_abs", "date_parsed")] if self.cache else []
        return pd.DataFrame([{k: v for k, v in r.items() if k in cols} for r in self.cache], columns=cols)

    def unmatched_ingest_df(self):
        if not self.unmatched_ingest:
            return pd.DataFrame()
        cols = [c for c in self.unmatched_ingest[0].keys() if c not in ("amount_abs", "date_parsed")]
        return pd.DataFrame([{k: v for k, v in r.items() if k in cols} for r in self.unmatched_ingest], columns=cols)

    def matches_df(self):
        return pd.DataFrame(self.matches)

    def ambiguous_df(self):
        return pd.DataFrame(self.ambiguous)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run(cache_path, manifest_path, batches_dir, out_dir, cfg: MatchConfig, single_batch=None):
    os.makedirs(out_dir, exist_ok=True)

    cache_df = pd.read_csv(cache_path, dtype=str, keep_default_na=False)
    engine = RuleEngine(cache_df, cfg)
    print(f"Loaded cache: {len(cache_df)} rows")

    manifest = pd.read_csv(manifest_path, dtype=str, keep_default_na=False)
    manifest = manifest.sort_values("sequence", key=lambda s: s.astype(int))

    if single_batch:
        manifest = manifest[manifest["file"] == single_batch]
        if manifest.empty:
            print(f"ERROR: '{single_batch}' not found in manifest. "
                  f"Check the filename matches exactly what's listed in manifest.csv.")
            return
        print(f"Running against a single batch only: {single_batch}")

    quarantine_dir = os.path.join(out_dir, "quarantined_batches")
    gate_log = []

    for _, m in manifest.iterrows():
        batch_file = m["file"]
        batch_path = os.path.join(batches_dir, batch_file)

        declared_rc, declared_ct = declared_counts_from_manifest(manifest, batch_file)
        gate_result = run_gate(batch_path, declared_rc, declared_ct)
        gate_log.append({
            "file": batch_file,
            "passed": gate_result.passed,
            "reasons": "; ".join(gate_result.reasons),
        })

        if not gate_result.passed:
            os.makedirs(quarantine_dir, exist_ok=True)
            import shutil
            shutil.copy(batch_path, os.path.join(quarantine_dir, batch_file))
            print(f"[STRUCTURAL GATE FAIL] {batch_file}: {'; '.join(gate_result.reasons)} -> quarantined, SKIPPED")
            continue

        batch_df = pd.read_csv(batch_path, dtype=str, keep_default_na=False)
        engine.process_batch(batch_df, batch_file)
        print(f"Processed {batch_file}: {len(batch_df)} rows | "
              f"running totals -> matched: {len(engine.matches)}, "
              f"cache remaining: {len(engine.cache)}, "
              f"ingest unmatched: {len(engine.unmatched_ingest)}")

    pd.DataFrame(gate_log).to_csv(os.path.join(out_dir, "structural_gate_log.csv"), index=False)

    matches_df = engine.matches_df()
    remaining_cache_df = engine.remaining_cache_df()
    unmatched_ingest_df = engine.unmatched_ingest_df()
    ambiguous_df = engine.ambiguous_df()

    matches_df.to_csv(os.path.join(out_dir, "matched_transactions.csv"), index=False)
    remaining_cache_df.to_csv(os.path.join(out_dir, "unmatched_cache_remaining.csv"), index=False)
    unmatched_ingest_df.to_csv(os.path.join(out_dir, "unmatched_ingestion_exceptions.csv"), index=False)
    ambiguous_df.to_csv(os.path.join(out_dir, "ambiguous_matches_for_review.csv"), index=False)

    print("\n--- SUMMARY ---")
    print(f"Total matched:            {len(matches_df)}")
    if len(matches_df):
        print(matches_df["matchRule"].value_counts().to_string())
    print(f"Cache items unmatched:    {len(remaining_cache_df)}")
    print(f"Ingest items unmatched:   {len(unmatched_ingest_df)}")
    print(f"Ambiguous (multi-cand.):  {len(ambiguous_df)}")
    print(f"\nResults written to: {out_dir}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True, help="Path to cache_gl_cashbook.csv")
    ap.add_argument("--manifest", required=True, help="Path to ingestion_batches/manifest.csv")
    ap.add_argument("--batches-dir", required=True, help="Directory containing the batch CSVs")
    ap.add_argument("--out-dir", default="/mnt/user-data/outputs/recon_results")
    ap.add_argument("--date-tolerance-days", type=int, default=3)
    ap.add_argument("--amount-abs-tolerance", type=float, default=1.00)
    ap.add_argument("--amount-pct-tolerance", type=float, default=0.0)
    ap.add_argument("--direction-mode", choices=["same", "opposite", "ignore"], default="ignore")
    ap.add_argument("--single-batch", default=None,
                     help="Filename (e.g. ingest_batch_0001.csv) to run just one batch, for quick testing")
    args = ap.parse_args()

    cfg = MatchConfig(
        date_tolerance_days=args.date_tolerance_days,
        amount_abs_tolerance=args.amount_abs_tolerance,
        amount_pct_tolerance=args.amount_pct_tolerance,
        direction_mode=args.direction_mode,
    )
    run(args.cache, args.manifest, args.batches_dir, args.out_dir, cfg, single_batch=args.single_batch)