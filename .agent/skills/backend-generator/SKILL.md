---
name: backend-generator
description: Analyzes existing standalone Python scripts in the project and constructs a modular FastAPI backend API layer. Use this skill whenever the user asks to wrap Python scripts into an API, build a FastAPI backend for existing Python logic, or expose Python functions as REST endpoints.
---

# FastAPI Backend Generator

## Overview

This skill automates transforming local, standalone Python scripts into a production-ready, modular **FastAPI** REST API backend. It performs deep static analysis of existing code, infers endpoint signatures, and scaffolds a fully-typed, documented API — while preserving all original script logic untouched as importable service modules.

---

## Trigger Phrases

Activate this skill when the user says any of the following (or equivalent):

- "Wrap my Python scripts into an API"
- "Build a FastAPI backend for this project"
- "Expose these Python functions as REST endpoints"
- "Create an API layer around the existing logic"
- "Turn these scripts into a web service"
- "Generate a backend for my Python code"

---

## Architectural Standards

### 1. Modular Routing
Separate endpoints into distinct routers based on functional domain inside `app/routers/`. Each router maps to one logical script or feature area. Never put all endpoints in `main.py`.

### 2. Data Validation
Define Pydantic models in `app/models/` mirroring the inputs and outputs of your Python functions. Every request body and every response body must have a named schema — no raw `dict` returns.

### 3. Service Wrapper Layer
Wrap existing raw Python scripts inside service layers (`app/services/`) **without altering original script functionality**. The service layer is an adapter: it translates between HTTP-friendly input/output shapes and the script's native API (argparse args, file paths, DataFrames, etc.).

### 4. CORS Configuration
Enable CORS middleware in `main.py` to allow external client connections. Default to permissive origins (`["*"]`) for development, with a comment noting production lock-down.

### 5. Asynchronous Execution
Use `async` handlers with `asyncio.to_thread()` or `concurrent.futures.ThreadPoolExecutor` for any function that:
- Reads/writes files (CSV, JSON, etc.)
- Processes large DataFrames
- Runs for more than ~100ms
- Calls `subprocess` or shells out

This prevents stalling the API event loop.

### 6. Error Handling Contract
Every endpoint must:
- Return structured JSON errors via `HTTPException` with meaningful `detail` messages.
- Catch known failure modes from the underlying scripts (e.g., `FileNotFoundError`, `ValueError`, `pd.errors.ParserError`) and translate them into appropriate HTTP status codes (400, 404, 422, 500).
- Never return raw Python tracebacks to clients.

### 7. Health & Metadata
Always generate a root `GET /` or `GET /health` endpoint that returns API name, version, and uptime. This is critical for deployment readiness checks and container orchestration.

---

## Execution Workflow

When activated, execute the following steps **in strict order**. Do not skip steps.

---

### Step 1: Discovery & Audit

**Goal:** Build a complete inventory of the scripts to wrap.

1. **Find all Python files** in the project (excluding `__pycache__`, `.venv`, `venv`, `node_modules`, `.git`, and any existing `backend/` directory).

2. **For each script, extract:**

   | Property | How to detect |
   |---|---|
   | **Entry points** | Look for `if __name__ == "__main__":` blocks, `main()` functions, and any functions called from `main()`. |
   | **CLI arguments** | Parse `argparse.ArgumentParser` calls — extract every `add_argument()` name, type, default, required flag, and help text. These become request body fields. |
   | **Importable functions** | Identify all public functions (no leading `_`) that accept arguments and return values. Prefer wrapping the `run()`/`main()` function with explicit params over the argparse-based CLI. |
   | **Data structures** | Find `@dataclass`, `TypedDict`, named tuples, and column-mapping dicts (e.g., `B_MAP = {...}`). These inform Pydantic model shapes. |
   | **Input formats** | Detect file reads: `pd.read_csv()`, `open()`, `json.load()`, etc. Decide whether the API should accept file uploads (`UploadFile`) or file paths. |
   | **Output formats** | Detect what `main()` produces: CSV files on disk, DataFrames, printed summaries, return values. Decide whether the API returns JSON, streamed CSV, or file download. |
   | **Inter-script dependencies** | Check `import` statements between project scripts (e.g., `from structural_gate import run_gate`). Dependent scripts must be co-located or importable from the service layer. |
   | **Heavy operations** | Flag functions that iterate large DataFrames, do nested loops, read/write files, or call `subprocess`. These must run in a thread pool. |

3. **Classify each script:**
   - **Instant** (< 1 second typical): simple transformations, lookups, validators → synchronous handler OK.
   - **Batch/Heavy** (seconds to minutes): file processing, matching engines, large CSV operations → must use `asyncio.to_thread()`.
   - **Side-effecting** (writes files, modifies state): needs idempotency guards and clear output path management.

4. **Output:** Create a structured audit summary (in your reasoning or as a scratch file) listing every endpoint you plan to create, with method, path, request model, response model, and which script function backs it.

---

### Step 2: Scaffold Backend Structure

Generate the backend layout inside a `backend/` directory at the project root:

```text
backend/
├── app/
│   ├── __init__.py           # Package marker (can be empty)
│   ├── main.py               # FastAPI app creation, CORS, router mounting, health check
│   ├── config.py             # Settings via pydantic-settings or environment variables
│   ├── routers/
│   │   ├── __init__.py
│   │   └── <domain>.py       # One router per functional domain / script group
│   ├── models/
│   │   ├── __init__.py
│   │   └── <domain>.py       # Pydantic Request/Response schemas per domain
│   └── services/
│       ├── __init__.py
│       └── <domain>_service.py  # Thin wrapper calling original script functions
├── requirements.txt          # Pinned dependencies
└── run.py                    # Uvicorn entry point with CLI args
```

**Naming conventions:**
- Router files: `snake_case` matching the domain (e.g., `recon.py`, `feed_processing.py`).
- Model files: match the router they serve.
- Service files: `<domain>_service.py` — never name them the same as the original scripts to avoid import shadowing.

---

### Step 3: Generate `main.py`

```python
"""
Auto-generated FastAPI application entry point.
"""
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import routers
from app.routers import <router_module_1>, <router_module_2>  # fill in

_start_time = datetime.utcnow()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic (e.g., preload caches, warm models)
    yield
    # Shutdown logic (e.g., close DB connections, flush logs)


app = FastAPI(
    title="<Project Name> API",
    description="Auto-generated REST API wrapping existing Python scripts.",
    version="0.1.0",
    lifespan=lifespan,
)

# -- CORS (permissive for development; lock down origins in production) --
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- Mount routers --
app.include_router(<router_module_1>.router, prefix="/<prefix>", tags=["<Tag>"])
app.include_router(<router_module_2>.router, prefix="/<prefix>", tags=["<Tag>"])


@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "uptime_seconds": (datetime.utcnow() - _start_time).total_seconds(),
        "version": app.version,
    }
```

---

### Step 4: Generate Pydantic Models (`app/models/`)

For each endpoint, create **separate Request and Response models**.

**Heuristics for converting script arguments to Pydantic fields:**

| Script pattern | Pydantic mapping |
|---|---|
| `argparse` `--flag` with `type=int` | `field_name: int` |
| `argparse` `--flag` with `default=X` | `field_name: int = X` |
| `argparse` `--flag` with `required=True` | `field_name: int` (no default) |
| `argparse` `choices=["a","b"]` | `field_name: Literal["a", "b"]` |
| `argparse` `action="store_true"` | `field_name: bool = False` |
| `@dataclass` fields | Mirror directly as Pydantic `BaseModel` fields |
| DataFrame column dicts (e.g., `B_MAP`) | Use as documentation / field descriptions |
| File path arguments | `field_name: str` with `Field(description="Path to ...")` or `UploadFile` if the API should accept file uploads |

**Response models** should capture:
- Summary statistics (row counts, match rates, pass/fail counts).
- Output file paths (if the API writes files to disk).
- Inline data previews (first N rows as list of dicts, for small results).
- Structured error detail for partial failures.

**Always use `Field(...)` with `description=` and `example=` for every field.** Pull descriptions from the original script's `argparse` help strings.

---

### Step 5: Generate Service Layer (`app/services/`)

The service layer is the **critical bridge**. It must:

1. **Import the original script's functions** — adjust `sys.path` if needed so that scripts in sibling directories are importable.

   ```python
   import sys
   from pathlib import Path

   # Make project scripts importable
   PROJECT_ROOT = Path(__file__).resolve().parents[2]
   sys.path.insert(0, str(PROJECT_ROOT / "Rule Engine"))
   sys.path.insert(0, str(PROJECT_ROOT / "File-Gen Scripts"))

   from rule_engine import RuleEngine, MatchConfig, run as run_rule_engine
   from structural_gate import run_gate, run_all as run_all_gates
   ```

2. **Translate between HTTP and script worlds:**
   - Convert request model fields → function arguments or `MatchConfig` dataclass instances.
   - Convert DataFrame outputs → list of dicts (for JSON) or streaming CSV responses.
   - Convert file path arguments → resolved absolute paths with validation.
   - Handle `argparse`-style defaults by mirroring them in the request model defaults.

3. **Capture script output that was originally `print()`-ed:**
   - If the script uses `print()` for summaries, redirect stdout via `contextlib.redirect_stdout` to capture logs, and include them in the response.
   - Alternatively, refactor the service call to return structured data instead of printing.

4. **Thread-safety:** If a script uses module-level mutable state, ensure each API call gets its own instance (e.g., `RuleEngine` is instantiated per-call, not shared).

---

### Step 6: Generate Routers (`app/routers/`)

**Router design rules:**

1. **One router per domain.** Group related endpoints logically.

2. **HTTP method selection:**
   | Script behavior | HTTP method | Why |
   |---|---|---|
   | Read-only query / analysis | `GET` | Idempotent, cacheable |
   | Creates output files / processes data | `POST` | Side-effecting, non-idempotent |
   | File uploads | `POST` with `UploadFile` | Multipart form data |
   | Modifies existing state | `PUT` or `PATCH` | Update semantics |

3. **Path naming:** Use kebab-case nouns, not verbs. E.g., `/recon/matches` not `/recon/runMatching`.

4. **Always wrap blocking calls:**
   ```python
   from asyncio import to_thread

   @router.post("/recon/run", response_model=ReconRunResponse)
   async def run_reconciliation(request: ReconRunRequest):
       result = await to_thread(recon_service.run_matching, request)
       return result
   ```

5. **File download endpoints** should use `StreamingResponse` with appropriate media type:
   ```python
   from fastapi.responses import StreamingResponse
   import io

   @router.get("/recon/results/{filename}")
   async def download_result(filename: str):
       # validate filename, read file, return streaming CSV
       ...
   ```

6. **Add docstrings** to every endpoint function. FastAPI uses these as the OpenAPI description.

---

### Step 7: Generate `requirements.txt`

```text
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
pydantic>=2.0
pydantic-settings>=2.0
python-multipart>=0.0.9
pandas>=2.0
```

Add any additional dependencies the original scripts use (detect from their `import` statements). Pin to minimum compatible versions, not exact versions, unless the user specifies otherwise.

---

### Step 8: Generate `run.py`

```python
"""
Convenience entry point: python run.py
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # auto-reload during development
    )
```

---

### Step 9: Generate `config.py` (Settings Management)

```python
"""
Centralized configuration via environment variables or .env file.
"""
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    app_name: str = "<Project Name> API"
    debug: bool = True
    data_dir: Path = Path(".")  # root dir for file I/O
    max_upload_size_mb: int = 100

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
```

---

### Step 10: Verification & Smoke Test

After generating all files:

1. **Syntax check** — Run `python -m py_compile backend/app/main.py` and every generated `.py` file.
2. **Import check** — Run `python -c "from app.main import app"` from the `backend/` directory to verify all imports resolve.
3. **Start server** — Run `python run.py` and confirm the server starts without errors.
4. **OpenAPI spec** — Verify `http://localhost:8000/docs` loads and shows all expected endpoints with correct schemas.
5. **Smoke request** — Make at least one test request to the health endpoint: `curl http://localhost:8000/health`.
6. **Report** — Tell the user what was generated, how many endpoints were created, and how to start the server.

---

## Decision Heuristics (Agent Intelligence)

Use these rules to make smart choices without asking the user:

### File Uploads vs. File Paths
- If the original script reads CSV/JSON from a path supplied via `--input`, **default to file upload** (`UploadFile`) for the API endpoint. This is more API-friendly than requiring the client to know server-side paths.
- If the script operates on pre-existing data directories with many files (like `batches_dir` with a manifest), **use a path-based approach** with a configurable `data_dir` setting. The API trusts that the files exist on the server.

### Inline Results vs. File Downloads
- If the output is < 1000 rows, return it inline as JSON (list of dicts).
- If the output is > 1000 rows or the script writes multiple output files, return download links and let the client fetch them via a separate `GET` endpoint.
- Always include summary statistics (counts, totals, pass/fail rates) in the primary response, even if full data is file-based.

### Endpoint Granularity
- If a script has one `main()` that does everything, create **one POST endpoint** for the full run, plus **separate GET endpoints** for retrieving individual outputs.
- If a script has multiple independent public functions (e.g., `build_cache()`, `build_ingest()`, `write_batches_by_size()`), consider exposing them as separate endpoints only if they are independently useful. Otherwise, keep them as internal service implementation.

### Handling `argparse` Enums
- Convert `choices=[...]` into `Literal[...]` or a Python `Enum`. Prefer `Literal` for short lists (≤ 5 options) and `Enum` for longer ones.

### Inter-Script Dependencies
- If script A imports from script B (e.g., `rule_engine.py` imports `structural_gate.py`), ensure both are importable from the service layer. Add the necessary `sys.path` entries in the service module, or create `__init__.py` files in the script directories.

### Error Propagation
- Map `sys.exit(1)` calls in scripts to `HTTPException(status_code=422, detail="...")`.
- Map `FileNotFoundError` to `HTTPException(status_code=404, ...)`.
- Map `ValueError` / `csv.Error` / `pd.errors.ParserError` to `HTTPException(status_code=400, ...)`.
- All other unhandled exceptions → `HTTPException(status_code=500, detail="Internal processing error")` with server-side logging.

---

## Anti-Patterns to Avoid

| ❌ Don't | ✅ Do instead |
|---|---|
| Modify original script files | Create service wrappers that import and call them |
| Return raw DataFrames from endpoints | Convert to `.to_dict(orient="records")` or use Pydantic models |
| Use `print()` for API output | Return structured JSON responses |
| Hardcode file paths in routers | Use `config.py` settings or request parameters |
| Create one giant router file | Split by domain into separate router modules |
| Skip type hints on endpoint functions | Fully type every parameter and return value |
| Use `def` for I/O-bound handlers | Use `async def` with `await to_thread(...)` |
| Return 200 for errors | Use appropriate HTTP status codes (400, 404, 422, 500) |
| Expose internal implementation details in error messages | Return user-friendly error descriptions |

---

## Example: Mapping a Real Script to an Endpoint

Given a script with:
```python
# argparse: --input (required), --split-by (choices=["size","date"]), --batch-size (int, default=500)
# output: writes CSV files to --out-dir
def main():
    ...
```

The skill should generate:

**Model:**
```python
class SplitReconRequest(BaseModel):
    split_by: Literal["size", "date"] = Field("size", description="Split strategy")
    batch_size: int = Field(500, ge=1, description="Rows per batch when split_by='size'")

class SplitReconResponse(BaseModel):
    total_rows_loaded: int
    cache_rows: int
    ingest_rows: int
    batches_created: int
    output_directory: str
    manifest_path: str
```

**Router:**
```python
@router.post("/feed/split", response_model=SplitReconResponse)
async def split_recon_feed(file: UploadFile, request: SplitReconRequest = Depends()):
    result = await to_thread(feed_service.split_feed, file, request)
    return result
```

**Service:**
```python
def split_feed(file: UploadFile, request: SplitReconRequest) -> SplitReconResponse:
    # Save upload to temp path, call original script functions, return structured result
    ...
```
