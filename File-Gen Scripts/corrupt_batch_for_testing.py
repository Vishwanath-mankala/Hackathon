"""
corrupt_batch_for_testing.py

Injects ONE realistic real-world data problem into an existing ingestion
batch file, so you can point structural_gate.py at it and watch it get
caught. Makes a .bak copy first, so you can restore the original after.

Each mode mimics something that genuinely happens in production bank
feeds:

  truncate        - Transfer cut off partway through (SFTP drop, timeout).
                     Removes the last row(s) without updating any totals.
                     -> should fail RECORD_COUNT and CONTROL_TOTAL.

  dropped_row     - A row silently disappears mid-file (processing bug,
                     dedup logic gone wrong, a retry that skipped one row).
                     -> should fail RECORD_COUNT and CONTROL_TOTAL.

  duplicate_row   - The bank (or an upstream retry) sends the same
                     transaction twice.
                     -> should fail RECORD_COUNT and CONTROL_TOTAL.

  tampered_amount - A single amount gets manually edited or corrupted in
                     transit (classic: someone "fixes" a value in Excel).
                     Row count stays correct - only the total is wrong.
                     -> should fail CONTROL_TOTAL only.

  missing_column  - A required field gets dropped or renamed upstream
                     (schema drift after a source-system change).
                     -> should fail REQUIRED_SECTIONS.

  bad_encoding    - A legacy source writes an accented name in Windows-1252
                     / Latin-1 instead of UTF-8 (very common with European
                     merchant/counterparty names: "Café", "Müller").
                     -> should fail ENCODING.

USAGE
-----
    python corrupt_batch_for_testing.py --file ingest_batch_0001.csv --mode truncate
    python corrupt_batch_for_testing.py --file ingest_batch_0001.csv --mode bad_encoding
    ...
    # restore afterwards:
    python corrupt_batch_for_testing.py --file ingest_batch_0001.csv --restore
"""

import argparse
import os
import shutil
import pandas as pd


def backup_path(path):
    return path + ".bak"


def do_backup(path):
    bak = backup_path(path)
    if not os.path.exists(bak):
        shutil.copy(path, bak)
        print(f"Backed up original to {bak}")
    else:
        print(f"Backup already exists at {bak} (not overwritten)")


def do_restore(path):
    bak = backup_path(path)
    if not os.path.exists(bak):
        print(f"No backup found at {bak} -- nothing to restore.")
        return
    shutil.copy(bak, path)
    print(f"Restored {path} from backup.")


def corrupt_truncate(path, n=1):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df = df.iloc[:-n]
    df.to_csv(path, index=False)
    print(f"Removed last {n} row(s) -- simulates an interrupted transfer.")


def corrupt_dropped_row(path):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    mid = len(df) // 2
    df = df.drop(df.index[mid]).reset_index(drop=True)
    df.to_csv(path, index=False)
    print(f"Silently dropped row at position {mid} -- simulates a processing bug.")


def corrupt_duplicate_row(path):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    dup = df.iloc[[0]]
    df = pd.concat([df, dup], ignore_index=True)
    df.to_csv(path, index=False)
    print("Duplicated the first row -- simulates a duplicate send/retry.")


def corrupt_tampered_amount(path):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    original = df.loc[0, "amount"]
    try:
        new_val = round(float(original) + 500.00, 2)
    except ValueError:
        new_val = 999999.99
    df.loc[0, "amount"] = str(new_val)
    df.to_csv(path, index=False)
    print(f"Changed row 0 amount from {original} to {new_val} -- "
          f"simulates a manual edit/data-entry error. Row count is untouched.")


def corrupt_missing_column(path, column="reference"):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if column not in df.columns:
        print(f"Column '{column}' not present anyway -- picking 'narrative' instead.")
        column = "narrative"
    df = df.drop(columns=[column])
    df.to_csv(path, index=False)
    print(f"Dropped column '{column}' -- simulates upstream schema drift.")


def corrupt_bad_encoding(path):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if "narrative" in df.columns:
        df.loc[0, "narrative"] = "Payment to Caf\xe9 M\xfcller"  # will be written as raw latin-1 bytes below
    csv_text = df.to_csv(index=False)
    with open(path, "wb") as f:
        f.write(csv_text.encode("latin-1"))
    print("Rewrote row 0 narrative with an accented name and saved the WHOLE "
          "file as Latin-1 -- simulates a legacy source system that never "
          "switched to UTF-8.")


MODES = {
    "truncate": corrupt_truncate,
    "dropped_row": corrupt_dropped_row,
    "duplicate_row": corrupt_duplicate_row,
    "tampered_amount": corrupt_tampered_amount,
    "missing_column": corrupt_missing_column,
    "bad_encoding": corrupt_bad_encoding,
}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="Path to the batch CSV to corrupt")
    ap.add_argument("--mode", choices=list(MODES.keys()), help="Which corruption to inject")
    ap.add_argument("--restore", action="store_true", help="Restore from .bak instead of corrupting")
    args = ap.parse_args()

    if args.restore:
        do_restore(args.file)
    else:
        if not args.mode:
            ap.error("--mode is required unless --restore is passed")
        do_backup(args.file)
        MODES[args.mode](args.file)
        print(f"\nNow run structural_gate.py against this file's batch dir "
              f"and watch it fail. Restore with:\n"
              f"  python corrupt_batch_for_testing.py --file {args.file} --restore")