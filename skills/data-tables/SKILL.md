---
name: data-tables
description: Work with local CSV/TSV/JSON data files using the data-wrangler tools — profile first, answer questions with real SQL, and clean files with an exact change report instead of eyeballing previews.
---

# Working with data files (data-wrangler)

The `data-wrangler` plugin gives you three tools over local tabular files
(CSV, TSV, JSON arrays of objects, JSONL). Everything they return is computed
from the file — never estimate numbers you can compute.

## The workflow

1. **Profile first.** Call `table_profile` on any data file before answering
   questions about it. It tells you the real row count, column types, null
   counts, duplicate rows, and numeric ranges. If the user says "the file has
   about 200 rows" and the profile says 13, believe the profile.
2. **Answer with SQL.** For totals, averages, group-bys, top-N lists and
   filters, call `table_query` with a read-only `SELECT` over the table named
   `data`. Column names are the file's original headers — quote names with
   spaces using double quotes, e.g. `SELECT SUM("Price (USD)") FROM data`.
   Only one query per call; writes are rejected by design.
3. **Clean explicitly.** When the user asks to clean or dedupe a file, call
   `table_clean`. It writes a *new* file (the input is never modified) and
   reports rows dropped, cells trimmed and headers renamed. Always quote that
   report back to the user — it is the receipt for what changed.
4. **Verify after cleaning.** Profile the cleaned output once to confirm the
   numbers moved the way the user wanted (duplicates at zero, headers in
   snake_case).

## Rules

- Never invent statistics: if a number didn't come from a tool result, say
  you haven't computed it yet.
- For very wide result sets, use `LIMIT` in SQL and the `limit` argument;
  report `total_matched` when the result was truncated.
- If a query fails (unknown column, bad syntax), read the error, fix the
  SQL against the profile's column list, and retry once before giving up.
