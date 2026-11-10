# data-wrangler — deterministic data tools for Hermes Agent

**Profile it. Query it. Clean it. With exact numbers, not vibes.**

An LLM is good at reasoning about data and bad at *counting* it. Ask a model how many
nulls a column has, what the average order value is, or whether a CSV has duplicate
rows, and it will happily estimate from whatever preview fits in context.

`data-wrangler` gives Hermes three tools that **compute** the answer from the whole
file, deterministically, using only the Python standard library:

| Tool | What it does |
|---|---|
| `table_profile` | Exact profile of a CSV/TSV/JSON/JSONL file: row & column counts, inferred column types, null counts/percentages, distinct counts, min/max/mean/median for numeric columns, top values for text columns, duplicate-row and empty-row counts. |
| `table_query` | Runs **one read-only SQL query** (`SELECT`/`WITH`) over the file, loaded into SQLite as the table `data`. Writes are denied twice: up front, and by a SQLite authorizer on the connection. Returns rows + total matched count. 10-second query budget. |
| `table_clean` | Writes a **cleaned copy** (input never modified): headers normalised to snake_case, whitespace trimmed, fully-empty rows dropped, exact duplicates removed (optionally on a column subset) — and returns a full change report: rows in/out, duplicates dropped, cells trimmed, headers renamed. |

Plus a bundled skill (`data-tables`) that teaches the agent the workflow:
**profile first → answer with SQL → clean explicitly → verify the result.**

## Why a plugin, not a prompt

A prompt can tell the model to "be careful with numbers". It cannot make the model
read 50,000 rows, count duplicates exactly, or run a `GROUP BY` without arithmetic
slips. These tools do the counting in code — the model's job goes back to deciding
*what* to ask and explaining the answer. Same input → same output, every time.

## Install

From the Hermes plugin catalog (once listed):

```bash
hermes plugins install data-wrangler
```

Or from git:

```bash
hermes plugins install yogeshchoudhary555/hermes-data-wrangler
```

Or manually: copy this directory to `~/.hermes/plugins/data-wrangler` and enable it.

Requires Hermes `>= 0.22`. No Python dependencies (standard library only), no API
keys, no configuration.

## Usage

Just talk to Hermes about a data file:

> "What's actually in `~/Downloads/messy_sales.csv`?"

→ `table_profile` reports 14 rows, one fully-empty row, one exact duplicate,
`Price (USD)` at type float with a missing value, `Region` needing a trim.

> "Which region brought in the most revenue?"

→ `table_query` runs
`SELECT " Region " , SUM("Price (USD)" * "Units Sold") AS revenue FROM data GROUP BY 1 ORDER BY 2 DESC`
and answers from the computed result.

> "Clean it up for me."

→ `table_clean` writes `messy_sales.cleaned.csv` and reports:
rows 14 → 12, 1 empty row dropped, 1 duplicate dropped, 3 cells trimmed,
headers renamed to `order_id, product_name, region, price_usd, units_sold, order_date`.

See `examples/messy_sales.csv` for the demo file used above.

## Tool reference

### `table_profile`
- `path` (required): CSV, TSV, JSON (array of objects, or an object with a
  `rows`/`data`/`records`/`items` array), or JSONL file.
- Null tokens recognised: empty, `NA`, `N/A`, `null`, `none`, `NaN` (case-insensitive).
- Limits: 100 MB file, 1,000,000 rows.

### `table_query`
- `path` (required), `sql` (required, single read-only query over table `data`),
  `limit` (optional, default 100, max 1000 returned rows; `total_matched` always reported).
- Numeric-looking columns are stored as REAL so aggregates and sorting are numeric;
  everything else is TEXT. Original column names are preserved — quote names with
  spaces: `"Price (USD)"`.

### `table_clean`
- `path` (required), `out` (optional; default `<name>.cleaned.csv` beside the input;
  `.json` suffix writes JSON), `dedupe` (optional, default `true`),
  `dedupe_columns` (optional subset, by original or cleaned name).
- The input file is **never** modified; `out` equal to the input is refused.

## Disclosure (catalog rule 13)

- **Files:** reads only the local data files the user (or agent) names in a tool
  call. Writes exactly one file per `table_clean` call — the cleaned output the
  user asked for.
- **Network:** none. **Shell commands:** none. **Credentials:** none.
- **Background processes / telemetry:** none.
- Queries run in an in-memory SQLite database; nothing is persisted anywhere,
  and no plugin state is kept between calls.

## Development

Validate exactly the way catalog CI does:

```bash
hermes plugins doctor /path/to/data-wrangler --ci
hermes plugins validate /path/to/data-wrangler --install-deps
```

## License

MIT
