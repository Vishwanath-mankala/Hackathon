"""
diagnose_ambiguity.py

Reads ambiguous_matches_for_review.csv + matched_transactions.csv from a
rule_engine.py run and shows WHERE the ambiguity is concentrated: which
accounts/amounts are responsible for the bulk of it, and how many distinct
cache candidates were typically competing for the same ingestion row.

This tells you whether ambiguity is a narrow, fixable problem (e.g. one
recurring standing-instruction amount causing 90% of it) or a broad
structural one (spread evenly, meaning your matching keys genuinely
aren't specific enough across the whole dataset).

USAGE
-----
    python diagnose_ambiguity.py --results-dir "File-Gen Scripts/OutPut/recon_results"
"""

import argparse
import os
import pandas as pd


def main(results_dir):
    amb_path = os.path.join(results_dir, "ambiguous_matches_for_review.csv")
    matches_path = os.path.join(results_dir, "matched_transactions.csv")

    amb = pd.read_csv(amb_path, dtype=str, keep_default_na=False)
    matches = pd.read_csv(matches_path, dtype=str, keep_default_na=False)

    if amb.empty:
        print("No ambiguous matches recorded.")
        return

    # Count how many candidates competed, per ambiguous case.
    amb["candidate_internal_txn_ids"] = amb["candidate_internal_txn_ids"].apply(
        lambda s: s if isinstance(s, list) else eval(s) if s.strip().startswith("[") else [s]
    )
    amb["n_candidates"] = amb["candidate_internal_txn_ids"].apply(len)

    print(f"Total ambiguous cases: {len(amb)}")
    print(f"Average candidates competing per case: {amb['n_candidates'].mean():.2f}")
    print(f"Max candidates competing in a single case: {amb['n_candidates'].max()}")
    print()
    print("--- Ambiguity by tier ---")
    print(amb["tier"].value_counts().to_string())
    print()

    # This is the number that actually tells you whether the reference-text
    # tie-break fix is doing meaningful work on THIS data, as opposed to
    # just measuring how crowded the ties are (which the fix can't change).
    if "disambiguated_by_reference" in amb.columns:
        amb["disambiguated_by_reference"] = amb["disambiguated_by_reference"].astype(str).str.lower() == "true"
        resolved = amb["disambiguated_by_reference"].sum()
        total = len(amb)
        print("--- How many ambiguous cases were resolved by reference text vs. a fallback guess ---")
        print(f"Resolved using real reference/narrative evidence: {resolved} ({resolved/total:.1%})")
        print(f"Fell back to closest date/amount guess (no usable text): {total - resolved} ({(total-resolved)/total:.1%})")
        print()
        print("By tier:")
        print(amb.groupby("tier")["disambiguated_by_reference"].agg(["sum", "count"]).rename(
            columns={"sum": "resolved_by_reference", "count": "total_ambiguous"}).to_string())
        print()
    else:
        print("NOTE: 'disambiguated_by_reference' column not found in this file -- "
              "this run used an OLDER rule_engine.py, before the reference tie-break fix. "
              "Regenerate ambiguous_matches_for_review.csv with the updated engine to see "
              "how much of the ambiguity is actually being resolved with real evidence.")
        print()

    # Join to matched_transactions to get amount/account context for each
    # ambiguous case's CHOSEN match (this is what we actually kept).
    joined = amb.merge(
        matches,
        left_on=["chosen_internal_txn_id"],
        right_on=["internal_txn_id"],
        how="left",
    )

    print("--- Top 15 accounts by ambiguous-case count ---")
    print(joined["account"].value_counts().head(15).to_string())
    print()

    print("--- Top 15 amounts by ambiguous-case count (likely recurring/standing amounts) ---")
    amount_counts = joined["cache_amount"].value_counts().head(15)
    print(amount_counts.to_string())
    print()

    total_amb = len(amb)
    top15_share = amount_counts.sum() / total_amb if total_amb else 0
    print(f"Top 15 amounts account for {top15_share:.1%} of all ambiguous cases.")
    if top15_share > 0.5:
        print(">> Ambiguity is CONCENTRATED in a small set of recurring amounts. "
              "Fixing disambiguation for these specific amounts (e.g. via reference "
              "matching) will resolve the majority of cases.")
    else:
        print(">> Ambiguity is SPREAD broadly across many distinct amounts. "
              "This points to account+amount+date genuinely not being specific "
              "enough as matching keys for this dataset overall.")

    out_path = os.path.join(results_dir, "ambiguity_diagnostic_detail.csv")
    joined.to_csv(out_path, index=False)
    print(f"\nFull joined detail written to: {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", required=True)
    args = ap.parse_args()
    main(args.results_dir)