"""
SQLite persistence — the durable copy of the pipeline's state.

One file, `settings.db_path` (data/recon.db by default). Pydantic records are
stored as JSON blobs so the schema never drifts from the models; the typed
columns beside them exist for browsing the file during a demo, not for reads.

Connection per operation: `sqlite3.connect` is ~100µs, WAL lets readers proceed
while a writer is mid-transaction, and it sidesteps the shared-connection
problem where two threads' BEGIN/COMMIT interleave on one handle. Every write
goes through `tx()`, which takes an immediate (write) lock up front so a
transaction never has to upgrade mid-way.

Single-process only: multiple API workers would each hold their own in-memory
cache of these tables.
"""
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Set

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
  batch_id       TEXT PRIMARY KEY,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL,
  stage          TEXT NOT NULL,
  source         TEXT NOT NULL,
  filename       TEXT NOT NULL,
  record_json    TEXT NOT NULL,
  machine_accum  REAL NOT NULL DEFAULT 0,
  queue_accum    REAL NOT NULL DEFAULT 0,
  held_at_epoch  REAL
);
CREATE TABLE IF NOT EXISTS batch_anomalies (
  batch_id   TEXT PRIMARY KEY,
  items_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batch_match_results (
  batch_id     TEXT PRIMARY KEY,
  results_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feed_queue (
  sequence               INTEGER PRIMARY KEY,
  file                   TEXT NOT NULL UNIQUE,
  row_count              INTEGER,
  declared_record_count  INTEGER,
  declared_control_total REAL,
  min_booking_date       TEXT,
  max_booking_date       TEXT,
  status                 TEXT NOT NULL DEFAULT 'PENDING',
  batch_id               TEXT,
  ingested_at            TEXT,
  error                  TEXT
);
CREATE TABLE IF NOT EXISTS run_history (
  batch_id     TEXT PRIMARY KEY,
  completed_at TEXT,
  outcome      TEXT,
  provenance   TEXT,
  row_json     TEXT NOT NULL
);
"""

_initialised: Set[str] = set()
_init_lock = threading.Lock()


def path() -> Path:
    return Path(settings.db_path)


def connect() -> sqlite3.Connection:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(str(p), isolation_level=None, timeout=5)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA journal_mode=WAL")
    cx.execute("PRAGMA synchronous=NORMAL")
    cx.execute("PRAGMA busy_timeout=5000")
    return cx


def init_schema() -> None:
    """Creates the tables. Runs once per distinct db path, so tests that point
    settings.db_path elsewhere get a fresh schema too."""
    key = str(path().resolve())
    with _init_lock:
        if key in _initialised:
            return
        cx = connect()
        try:
            cx.executescript(SCHEMA)
        finally:
            cx.close()
        _initialised.add(key)


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """One write transaction. BEGIN IMMEDIATE takes the write lock up front."""
    init_schema()
    cx = connect()
    try:
        cx.execute("BEGIN IMMEDIATE")
        yield cx
        cx.execute("COMMIT")
    except BaseException:
        try:
            cx.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        cx.close()


@contextmanager
def read() -> Iterator[sqlite3.Connection]:
    """A read-only handle; WAL means it never blocks on a writer."""
    init_schema()
    cx = connect()
    try:
        yield cx
    finally:
        cx.close()


def clear_tables(cx: sqlite3.Connection, *names: str) -> None:
    for name in names:
        cx.execute(f"DELETE FROM {name}")
