# Personal Data Hub

A local SQLite workspace for personal records: import spreadsheets, CSV, JSON and PDF tables; browse and edit them in a local Web interface; share a consistent, audited data model with CLI, REST and MCP clients. Sensitive fields are masked by default.

**Python 3.11+ · version 0.1.0 · MIT · no cloud services or accounts**

## Install

```bash
git clone https://github.com/GuoHaoyu1688/personal-data-hub.git
cd personal-data-hub
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

Use `pip install -e .` for runtime only. Dependencies provide local YAML, spreadsheet/PDF extraction, FastAPI, offline Swagger assets and the official MCP SDK. The MCP dependency is constrained to `>=1.16,<2` to use official FastMCP v1. No runtime command downloads data or models. Optional dependency installation itself requires package access.

## Quick start: three commands

From the installed checkout:

```bash
hub --data-dir ./data/demo import examples/projects.xlsx --table projects --dry-run --json
hub --data-dir ./data/demo import examples/projects.xlsx --table projects --yes --json
hub --data-dir ./data/demo query projects --where 'status=active' --json
```

The first command displays suggested column mappings, a five-row sample and validation errors without importing records. The second inserts **2** fictional projects; repeating it skips **2** unchanged rows. The query returns the active Cooling study project. Initialization and additive migrations run automatically; an explicit `hub init` is also available.

To open the working Web interface:

```bash
hub --data-dir ./data/demo serve --host 127.0.0.1 --port 8766
```

Visit [the local workspace](http://127.0.0.1:8766/) or [the offline API documentation](http://127.0.0.1:8766/docs). The Web UI supports table navigation, text search, safe expression filters, add, inline edit with stale-edit protection, delete, audit history, sensitive-value reveal, due dates and CSV export matching the active search/filter. Mobile layouts keep wide tables scrollable.

## Built-in tables

Every record includes `id`, `created_at`, `updated_at`, `source_file` and `actor`. IDs are UUIDs unless restored from an export. Business schemas are YAML:

| Table | Example fields | Unique key | Sensitive fields |
|---|---|---|---|
| `profile` | name, email, phone, city, summary | name | email, phone |
| `education` | institution, degree, major, start/end date | institution + degree + start_date | none |
| `work_history` | company, role, dates, description | company + role + start_date | none |
| `projects` | name, role, dates, status, description | name | none |
| `trips` | destination, dates, purpose, cost | destination + start_date | cost |
| `income` | date, category, reference, amount, currency | date + category + reference | amount |
| `health_metrics` | date, metric, value, unit, notes | date + metric | value, notes |
| `documents` | name, category, reference, expiry, location | name | reference, location |
| `important_dates` | name, date, category, notes | name + date | none |

These are general records, not medical/financial calculations or eligibility decisions. All examples are fictional. Example contact values use the reserved `.invalid` domain and explicit fictional markers.

## Paths and configuration

Default data directory: `./data`. `--data-dir` overrides `HUB_DATA_DIR`, which overrides TOML `data_dir`. The database is `<data-dir>/hub.db`. First startup copies packaged built-in schemas into `<data-dir>/schemas`; later startups preserve customized files. `--schema-dir DIR` or TOML `schema_dir` selects another directory. Root `schemas/` contains editable copies and can be selected explicitly with `--schema-dir ./schemas`.

```toml
# Use --config examples/config.toml
[hub]
data_dir = "./data/example"
timezone = "Asia/Shanghai"
actor = "agent:example"
```

Timestamps are UTC ISO 8601. Naive datetimes, due-date calculations and backup filenames use the configured timezone, default `Asia/Shanghai`. Use local disk storage: SQLite WAL with a 30-second busy timeout is not designed for network filesystem sharing. Each mutation and its audit event commit in one transaction.

## Extend schemas without losing data

Copy `examples/custom_schema.yaml` to `<data-dir>/schemas/reading_list.yaml`, then run `hub init` or restart the server. Accepted column types: `text`, `integer`, `decimal`, `boolean`, `date`, `datetime`. Options include `required`, `default`, `sensitive`, `label` and `aliases`. Each schema defines `table`, `columns`, `unique` and optionally `due_fields` (date columns).

```yaml
table: reading_list
label: Reading List
unique: [title]
columns:
  title: {type: text, required: true}
  status: {type: text, default: planned}
  private_note: {type: text, sensitive: true}
```

Migrations only add tables/columns. Removed columns remain available through the effective persisted schema. Existing types, unique keys and required constraints cannot change. New required fields on populated tables need a valid default. Default backfills are audited as `schema:migration`; mandatory defaults cannot be reverted to invalid null values. Previously sensitive fields remain sensitive even if a YAML flag is removed. Restart long-running Web/MCP processes after changing schemas. Backups contain the **effective** schemas, including retained fields.

Identifiers are limited to lowercase letters, digits and underscores. Unique keys must be nonempty on each record; import requires a declared unique key for deterministic upsert. Monetary values use decimal strings in SQLite, with exact Decimal comparisons; quote decimal defaults in YAML to avoid YAML float conversion.

## Import mappings and deduplication

Supported input: UTF-8 CSV (BOM accepted), JSON arrays, `.xlsx` worksheets and text-based PDF tables. XLSX uses the first worksheet unless `--sheet NAME` is supplied. PDFs use pdfplumber's ruled-table extraction; scanned/image-only PDFs need separate OCR. Multiple PDF tables must have the same header row. Legacy `.xls`, arbitrary layout guessing and OCR are not included.

```bash
hub import examples/documents.pdf --table documents --dry-run --json
hub import examples/documents.pdf --table documents --yes --json
hub import examples/projects.csv --table projects --map examples/project-map.json --yes --json
```

`--map` is a JSON source-header → target-field object. Automatic suggestions compare normalized field names, labels and aliases with a 0.72 similarity threshold; inspect the preview before applying. Preview returns `mapping`, `unmapped_columns`, `sample`, `rows_in`, `valid_rows`, `errors`, and file `sha1`. Sensitive sample fields are masked. Unknown source columns are omitted, not displayed as raw sample values.

No import writes records unless `--yes` is present; `--dry-run` always wins. To bind application to a reviewed file, pass the preview's `--expected-sha1`. All records validate before a single atomic transaction. Unique-key matches update mapped business fields; omitted fields survive. Unchanged rows skip without a new change event. Reimporting the same XLSX/PDF does not duplicate rows. Each successful application records a file-level import log, even if no business rows change.

JSON/CSV exports include record IDs and metadata. Imports preserve supplied IDs for newly inserted rows; creation/update timestamps and import provenance describe the new import rather than claiming original provenance. Use a backup to restore the exact database/history. Masked exports are safe for review but cannot be reimported as real sensitive values: `[REDACTED]` is rejected. Explicitly use `--reveal` only when you need a private full-data transfer.

## Safe queries

```bash
hub query projects --where 'start_date>=2026-01-01 AND status=active' --fields name,role,status --limit 50 --json
hub query profile --where "name~'Ali'" --json
hub query income --where 'amount>=1000.01' --reveal --json
```

Grammar: `FIELD OP VALUE`, optionally joined by `AND`; operators `= != > < >= <= ~`. Quote values containing spaces. `~` is a literal substring match: `%` and `_` are escaped. `=null`/`!=null` test nulls. Raw SQL, OR, joins and arbitrary expressions are not accepted. Columns are validated against the schema and values are bound parameters. Numeric comparisons use Python Decimal rather than binary floats. Default search excludes sensitive fields; filtering those fields requires explicit `--reveal` to avoid leaking private values through match results. Results use stable created-at/ID ordering with `--limit` and `--offset`.

## CLI reference

Global options may appear before or after subcommands: `--data-dir`, `--schema-dir`, `--config`, `--actor`, `--json`, `--quiet`, `--reveal`, `--progress`, `--version`.

| Command | Purpose / important flags |
|---|---|
| `init` | Initialize and migrate schemas |
| `tables` / `schema TABLE` | List tables / describe effective fields |
| `import PATH --table TABLE` | Preview; `--dry-run`, `--map`, `--sheet`, `--expected-sha1`, `--yes` |
| `query TABLE` | `--where`, `--fields a,b`, `--search`, `--limit`, `--offset` |
| `add TABLE --data '{...}'` | Create a record and audit it |
| `update TABLE ID --data '{...}'` | Patch supplied fields; optional `--expected-updated-at` prevents stale edits |
| `delete TABLE ID --yes` | Delete; original values remain in reversible audit history |
| `history` | `--table`, `--row-id`, `--limit` |
| `revert CHANGE_ID --yes` | Apply the inverse change only if later state does not conflict |
| `due --within 30d` | Upcoming and overdue documents/important dates |
| `export TABLE --format json/csv --out PATH` | Masked by default; `--where`, `--search`, `--utf8` |
| `backup` | Dated ZIP; optional `--out PATH` |
| `serve --host 127.0.0.1 --port 8766` | Local Web/API only; other public bind addresses are rejected |
| `mcp` | Official FastMCP stdio |

Success: `{"ok":true,"data":...,"warnings":[]}`. Failure: `{"ok":false,"error":{"code":"...","message":"..."}}`. Exit codes: 0 success, 1 I/O/runtime, 2 arguments/conflict, 3 missing data. `--quiet` suppresses successful human output; `--json` wins. `--progress` emits a start message on stderr. No CLI command prompts. Long imports are synchronous; very large files can exceed the small-data two-second target.

## Audit and reversal

Every inserted, changed or deleted business record has a `changes` entry with before/after snapshots, actor and timestamp. Default CLI/MCP/REST history masks sensitive fields in both snapshots. Idempotent no-op updates do not create extra change events. `hub revert ID --yes` reverses insertion, update or deletion and audits that inverse with a `reverses` link. It rejects already-reverted changes, reused IDs, key conflicts and intervening edits; it does not silently overwrite newer work.

Deleted values remain in audit and backups. Masking is a presentation control, not encryption or secure deletion. A process with filesystem access can read the entire database. Use filesystem permissions and operating-system disk encryption for private records.

## REST and MCP

The Web API shares the CLI's core and masking:

- `GET /api/tables`, `GET /api/schema/{table}`.
- `GET/POST /api/rows/{table}`; `GET/PATCH/DELETE /api/rows/{table}/{id}`.
- `GET /api/history`, `POST /api/revert/{change_id}?confirm=true`.
- `GET /api/due`, `GET /api/export/{table}?format=csv`.
- `GET /openapi.json`, `/docs` (Swagger assets served locally).

Mutations accept `X-Actor`; use `reveal=true` explicitly to reveal sensitive results. Deletion requires `confirm=true`. Optionally set `HUB_TOKEN` before `hub serve` and send `Authorization: Bearer <token>` on all `/api/` calls. The Web UI's Access token field keeps it only in memory. There is no login/multi-user permission system. Host checks and cross-origin-write rejection protect local browser access; do not expose this service to the internet.

Eight MCP tools: `list_tables`, `describe_table`, `query_rows`, `insert_row`, `update_row`, `delete_row`, `list_due_items`, `get_history`. Typed signatures expose JSON Schemas through the official SDK. Mutation descriptions state side effects, and delete requires `confirm=true`. All default to masked responses.

Claude Desktop or a generic stdio MCP client:

```json
{"mcpServers":{"personal-data":{"command":"/workspace/apps/personal-data-hub/.venv/bin/hub","args":["--data-dir","/workspace/data/personal-data-hub","--actor","agent:example","mcp"]}}}
```

Codex CLI:

```toml
[mcp_servers.personal_data]
command = "/workspace/apps/personal-data-hub/.venv/bin/hub"
args = ["--data-dir", "/workspace/data/personal-data-hub", "--actor", "agent:example", "mcp"]
```

See [AGENTS.md](AGENTS.md) for headless installation, parameter schemas and recipes.

## Backups and recovery

`hub backup` uses SQLite's online backup API, including committed WAL content, and stores `hub.db`, effective `schemas/*.yaml` and a manifest in a dated ZIP. Filenames include seconds/microseconds to avoid collisions. Backups are **unmasked private data**, including deleted audit snapshots.

To restore, stop all clients, extract into a **new empty data directory**, then run `hub --data-dir /path/to/restored init` and query a known record. Do not mix restored database files with old `-wal`/`-shm` files. Export/backup refuses to overwrite the active database. Back up before updates, deletion, reversal and schema changes.

## Test

```bash
ruff check .
ruff format --check .
pytest -q --cov=personal_data_hub --cov-report=term-missing
```

Tests cover actual fictional XLSX/PDF extraction and repeat imports, mappings, rollback, additive schema preservation, injection probes, masked interface/history/export responses, exact decimals, due reminders, online backup restore, REST/OpenAPI, all MCP tools with the official in-memory client and real stdio initialization. CI runs Ubuntu Python 3.11/3.12. To regenerate examples: `python examples/generate_fixtures.py` with dev dependencies installed.

## FAQ and roadmap

- **Why are secrets still in the DB?** Masking prevents accidental display; no encrypted-database or multi-user system is claimed.
- **Why did a PDF fail?** The extractor needs actual table text/lines. Review and normalize complex or scanned documents before import.
- **Can I remove a schema column?** Runtime migrations only add. Use a separately reviewed offline migration and backup for destructive changes.
- **Can I edit a hidden value in the browser?** Enable Reveal explicitly; otherwise hidden cells are disabled so placeholders never overwrite private data.
- **Why does revert report a conflict?** The record changed since that audit event. Inspect history and choose a newer compatible change or restore a backup to a separate path.
- **What is next?** Larger-file streaming, import preview UI uploads, richer schema constraints and optional encrypted storage are potential future work. The current CLI handles imports; the Web UI handles browsing and editing.

Local verification on 2026-10-15 (Python 3.12.13): **34 tests passed, 92% coverage**, Ruff lint/format passed, README quick start executed, and wheel resources verified. Browser checks passed at 1440×980 and 390×844 with no console errors or external requests, including inline editing, masked filtered export and offline Swagger. One upstream Starlette TestClient deprecation warning for httpx remains; it does not affect runtime behavior. CI configuration is provided; remote CI execution is not claimed here.

[MIT license](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [Changelog](CHANGELOG.md) · [Agent manual](AGENTS.md)
