"""
structural_gate.py

The first checkpoint a file passes through -- BEFORE any row reaches the
rule engine. Purely deterministic: every check is pass/fail, no fuzzy
logic, no tolerances tuned by trial and error. A file that fails here is
quarantined, not partially processed -- a structurally broken file (wrong
record count, corrupted totals, wrong encoding) cannot be trusted to
produce meaningful matches even if some rows look fine.

FOUR CHECKS
-----------
1. Encoding      - file must decode cleanly as the expected charset.
2. Required      - every canonical column the rule engine depends on
   sections        must be present in the header row.
3. Record count  - actual data-row count must equal a DECLARED count.
4. Control total - sum of the amount column must equal a DECLARED total
   (within a small tolerance for float rounding, not business tolerance).

The "declared" values in checks 3 and 4 stand in for a real bank file's
header/trailer record (e.g. BAI2's '98'/'99' trailer, MT940's ':62F:'
closing balance). Here they come from manifest.csv, which
split_recon_feed.py populates at generation time. If your real bank
files carry native header/trailer records instead, swap
`declared_counts_from_manifest()` for a parser that reads them directly
from the file - the four checks below don't change.

USAGE (standalone)
-------------------
    python structural_gate.py --batches-dir ingestion_batches \\
                               --manifest ingestion_batches/manifest.csv \\
                               --quarantine-dir ingestion_batches/quarantine
"""

import argparse
import os
import shutil
from dataclasses import dataclass, field

import pandas as pd

REQUIRED_COLUMNS = [
    "external_txn_id", "account", "currency", "amount",
    "debit_credit", "booking_date", "value_date", "reference", "narrative",
]

CONTROL_TOTAL_TOLERANCE = 0.01  # float-rounding slack only, not a business tolerance


@dataclass
class GateResult:
    file: str
    passed: bool
    checks: dict = field(default_factory=dict)   # check_name -> (passed: bool, detail: str)
    reasons: list = field(default_factory=list)   # human-readable failure reasons


def check_encoding(path, expected="utf-8"):
    try:
        with open(path, "rb") as f:
            raw = f.read()
        raw.decode(expected)
        return True, f"decoded cleanly as {expected}"
    except UnicodeDecodeError as e:
        return False, f"failed to decode as {expected}: {e}"


def check_required_columns(df, required=REQUIRED_COLUMNS):
    missing = [c for c in required if c not in df.columns]
    if missing:
        return False, f"missing required column(s): {missing}"
    return True, "all required columns present"


def check_record_count(actual_count, declared_count):
    if declared_count is None:
        return False, "no declared record count available to check against"
    if actual_count != declared_count:
        return False, f"actual={actual_count} vs declared={declared_count}"
    return True, f"actual matches declared ({actual_count})"


def check_control_total(df, declared_total, tolerance=CONTROL_TOTAL_TOLERANCE):
    if declared_total is None:
        return False, "no declared control total available to check against"
    amounts = pd.to_numeric(df["amount"], errors="coerce")
    if amounts.isna().any():
        bad = amounts.isna().sum()
        return False, f"{bad} row(s) had non-numeric amount, cannot compute total"
    actual_total = round(float(amounts.sum()), 2)
    diff = abs(actual_total - float(declared_total))
    if diff > tolerance:
        return False, f"actual={actual_total} vs declared={declared_total} (diff={diff:.2f})"
    return True, f"actual matches declared ({actual_total})"


def run_gate(batch_path, declared_record_count=None, declared_control_total=None,
             expected_encoding="utf-8", required_columns=REQUIRED_COLUMNS):
    fname = os.path.basename(batch_path)
    result = GateResult(file=fname, passed=True)

    enc_ok, enc_detail = check_encoding(batch_path, expected_encoding)
    result.checks["encoding"] = (enc_ok, enc_detail)
    if not enc_ok:
        result.passed = False
        result.reasons.append(f"ENCODING: {enc_detail}")
        # Can't safely parse further if encoding is broken - stop here.
        return result

    df = pd.read_csv(batch_path, dtype=str, keep_default_na=False)

    cols_ok, cols_detail = check_required_columns(df, required_columns)
    result.checks["required_sections"] = (cols_ok, cols_detail)
    if not cols_ok:
        result.passed = False
        result.reasons.append(f"REQUIRED_SECTIONS: {cols_detail}")
        # Can't reliably compute a control total without the amount column etc.
        return result

    count_ok, count_detail = check_record_count(len(df), declared_record_count)
    result.checks["record_count"] = (count_ok, count_detail)
    if not count_ok:
        result.passed = False
        result.reasons.append(f"RECORD_COUNT: {count_detail}")

    total_ok, total_detail = check_control_total(df, declared_control_total)
    result.checks["control_total"] = (total_ok, total_detail)
    if not total_ok:
        result.passed = False
        result.reasons.append(f"CONTROL_TOTAL: {total_detail}")

    return result


def declared_counts_from_manifest(manifest_df, filename):
    row = manifest_df[manifest_df["file"] == filename]
    if row.empty:
        return None, None
    row = row.iloc[0]
    rc = row.get("declared_record_count")
    ct = row.get("declared_control_total")
    rc = int(rc) if pd.notna(rc) and str(rc).strip() != "" else None
    ct = float(ct) if pd.notna(ct) and str(ct).strip() != "" else None
    return rc, ct


def run_all(batches_dir, manifest_path, quarantine_dir=None):
    manifest_df = pd.read_csv(manifest_path, dtype=str, keep_default_na=False)
    results = []
    for _, m in manifest_df.iterrows():
        fname = m["file"]
        path = os.path.join(batches_dir, fname)
        declared_rc, declared_ct = declared_counts_from_manifest(manifest_df, fname)
        result = run_gate(path, declared_rc, declared_ct)
        results.append(result)

        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {fname}")
        if not result.passed:
            for reason in result.reasons:
                print(f"    - {reason}")
            if quarantine_dir:
                os.makedirs(quarantine_dir, exist_ok=True)
                shutil.copy(path, os.path.join(quarantine_dir, fname))

    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]
    print(f"\n{len(passed)} passed, {len(failed)} failed out of {len(results)} batch file(s).")
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches-dir", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--quarantine-dir", default=None)
    args = ap.parse_args()
    run_all(args.batches_dir, args.manifest, args.quarantine_dir)