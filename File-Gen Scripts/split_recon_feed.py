"""
split_recon_feed.py

Splits a large A_/B_ style recon export into:

  1. cache_gl_cashbook.csv
       One file, all A-side (internal GL/cashbook) rows. This represents
       what's already sitting in your cache/DB before any ingestion runs.

  2. ingestion_batches/ingest_batch_XXXX.csv  (or ingest_<date>.csv)
       The B-side (external bank statement) rows, split into multiple
       smaller files so you can feed them into your pipeline one at a
       time to simulate real statement arrivals.

  3. ingestion_batches/manifest.csv
       Ordered list of batch files + row counts + date range, so a
       simulation harness can just iterate the manifest in order.

USAGE
-----
Fixed-size batches (e.g. 500 rows per simulated "drop"):
    python split_recon_feed.py --input recon_60k.csv --split-by size --batch-size 500

One file per calendar day (mimics a real daily bank-statement feed):
    python split_recon_feed.py --input recon_60k.csv --split-by date

Both modes write into the same output structure so your simulation
loop doesn't need to know which mode was used - it just reads manifest.csv.
"""

import argparse
import csv
import os
import sys
import pandas as pd

# ---- Canonical schema mapping (same as before) --------------------------
B_MAP = {
    "B_id": "external_txn_id",
    "B_account": "account",
    "B_currencyCode": "currency",
    "B_amount": "amount",
    "B_debitOrCredit": "debit_credit",
    "B_importDate": "booking_date",
    "B_valueDate": "value_date",
    "B_transactionReferences": "reference",
    "B_transactionAttributes": "narrative",
}

A_MAP = {
    "A_id": "internal_txn_id",
    "A_account": "account",
    "A_currencyCode": "currency",
    "A_amount": "amount",
    "A_debitOrCredit": "debit_credit",
    "A_importDate": "txn_date",
    "A_valueDate": "value_date",
    "A_allocation": "allocation",
    "A_transactionReferences": "reference",
    "A_transactionAttributes": "narrative",
}


def sniff_delimiter(path, sample_size=8192):
    """Detect the real delimiter instead of assuming comma or tab."""
    with open(path, "r", newline="", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(sample_size)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        return dialect.delimiter
    except csv.Error:
        return ","  # sensible fallback


def clean_cell(v):
    """
    Some source exports (mainframe/legacy systems in particular) store
    values with literal quote characters and fixed-width space padding
    baked into the data itself, e.g. a cell whose real content is:
        ' "286051609972"   '
    (leading space, literal quote marks, trailing padding) rather than
    just '286051609972'. Left alone, this re-quotes and doubles quotes
    every time the value is written back out to CSV, producing the
    "" ""123"" "" mess. Strip it once, at the source, before anything
    else touches the data.
    """
    if v is None:
        return ""
    v = str(v).strip()
    # Repeatedly peel matching outer quote characters + padding.
    while len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        v = v[1:-1].strip()
    return v


def load_source(path):
    delim = sniff_delimiter(path)
    print(f"Detected delimiter: {repr(delim)}")
    df = pd.read_csv(path, sep=delim, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    df = df.map(clean_cell) if hasattr(df, "map") else df.applymap(clean_cell)
    missing = [c for c in ["A_id", "B_id"] if c not in df.columns]
    if missing:
        print(f"ERROR: expected columns {missing} not found. Actual columns:\n{list(df.columns)}")
        sys.exit(1)
    return df


def build_cache(df):
    rows = []
    for _, row in df.iterrows():
        if row.get("A_id", "").strip():
            rec = {v: row.get(k, "") for k, v in A_MAP.items()}
            rec["status"] = "unmatched"
            rows.append(rec)
    return pd.DataFrame(rows, columns=list(A_MAP.values()) + ["status"])


def build_ingest(df):
    rows = []
    for _, row in df.iterrows():
        if row.get("B_id", "").strip():
            rec = {v: row.get(k, "") for k, v in B_MAP.items()}
            rows.append(rec)
    ingest_df = pd.DataFrame(rows, columns=list(B_MAP.values()))
    # Parse booking_date for sorting/date-based batching; keep original string too.
    ingest_df["_booking_date_parsed"] = pd.to_datetime(
        ingest_df["booking_date"], errors="coerce"
    )
    ingest_df = ingest_df.sort_values("_booking_date_parsed", kind="stable").reset_index(drop=True)
    return ingest_df


def _control_total(chunk):
    """Sum of amounts, as a real file's trailer record would declare it."""
    amounts = pd.to_numeric(chunk["amount"], errors="coerce")
    return round(float(amounts.sum()), 2)


def write_batches_by_size(ingest_df, out_dir, batch_size):
    manifest = []
    n = len(ingest_df)
    n_batches = (n + batch_size - 1) // batch_size
    for i in range(n_batches):
        chunk = ingest_df.iloc[i * batch_size:(i + 1) * batch_size].drop(columns=["_booking_date_parsed"])
        fname = f"ingest_batch_{i+1:04d}.csv"
        chunk.to_csv(os.path.join(out_dir, fname), index=False)
        manifest.append({
            "sequence": i + 1,
            "file": fname,
            "row_count": len(chunk),
            "declared_record_count": len(chunk),
            "declared_control_total": _control_total(chunk),
            "min_booking_date": chunk["booking_date"].min(),
            "max_booking_date": chunk["booking_date"].max(),
        })
    return manifest


def write_batches_by_date(ingest_df, out_dir):
    manifest = []
    ingest_df["_date_key"] = ingest_df["_booking_date_parsed"].dt.date
    seq = 1
    for date_key, chunk in ingest_df.groupby("_date_key", sort=True, dropna=False):
        chunk = chunk.drop(columns=["_booking_date_parsed", "_date_key"])
        label = str(date_key) if pd.notna(date_key) else "unknown_date"
        fname = f"ingest_{label}.csv"
        chunk.to_csv(os.path.join(out_dir, fname), index=False)
        manifest.append({
            "sequence": seq,
            "file": fname,
            "row_count": len(chunk),
            "declared_record_count": len(chunk),
            "declared_control_total": _control_total(chunk),
            "min_booking_date": chunk["booking_date"].min(),
            "max_booking_date": chunk["booking_date"].max(),
        })
        seq += 1
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to the raw 60k+ row recon CSV")
    ap.add_argument("--out-dir", default="/mnt/user-data/outputs", help="Output directory")
    ap.add_argument("--split-by", choices=["size", "date"], default="size",
                     help="'size' = fixed-row batches, 'date' = one file per booking_date")
    ap.add_argument("--batch-size", type=int, default=500,
                     help="Rows per batch file when --split-by size")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    batches_dir = os.path.join(args.out_dir, "ingestion_batches")
    os.makedirs(batches_dir, exist_ok=True)

    df = load_source(args.input)
    print(f"Loaded {len(df)} total rows.")

    cache_df = build_cache(df)
    cache_path = os.path.join(args.out_dir, "cache_gl_cashbook.csv")
    cache_df.to_csv(cache_path, index=False)
    print(f"Cache (GL/cashbook): {len(cache_df)} rows -> {cache_path}")

    ingest_df = build_ingest(df)
    print(f"Ingestion (bank statement) total: {len(ingest_df)} rows")

    if args.split_by == "size":
        manifest = write_batches_by_size(ingest_df, batches_dir, args.batch_size)
    else:
        manifest = write_batches_by_date(ingest_df, batches_dir)

    manifest_df = pd.DataFrame(manifest)
    manifest_path = os.path.join(batches_dir, "manifest.csv")
    manifest_df.to_csv(manifest_path, index=False)

    print(f"Wrote {len(manifest)} ingestion batch file(s) to {batches_dir}")
    print(f"Manifest (ordered, for your simulation loop): {manifest_path}")


if __name__ == "__main__":
    main()