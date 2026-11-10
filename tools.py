"""Tool handlers — deterministic tabular-data work, Python standard library only.

Handlers follow the Hermes contract: signature (args: dict, **kwargs) -> str,
always return a JSON string, never raise.
"""

import csv
import json
import re
import sqlite3
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

MAX_FILE_BYTES = 100 * 1024 * 1024  # 100 MB
MAX_ROWS = 1_000_000
QUERY_TIME_LIMIT_S = 10.0
NULL_TOKENS = {"", "na", "n/a", "null", "none", "nan"}
SUPPORTED_SUFFIXES = {".csv", ".tsv", ".json", ".jsonl"}
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def _is_null(value) -> bool:
    if value is None:
        return True
    return isinstance(value, str) and value.strip().lower() in NULL_TOKENS


def _load_table(path_str: str):
    """Load a tabular file. Returns (columns, rows, meta) or raises ValueError."""
    path = Path(path_str).expanduser()
    if not path.is_file():
        raise ValueError(f"File not found: {path_str}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"Unsupported file type '{suffix}'. Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f"File is {size} bytes; the limit is {MAX_FILE_BYTES} bytes (100 MB).")

    if suffix in (".csv", ".tsv"):
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            sample = f.read(8192)
            f.seek(0)
            dialect = "excel-tab" if suffix == ".tsv" else _sniff_dialect(sample)
            reader = csv.DictReader(f, dialect=dialect)
            if reader.fieldnames is None:
                raise ValueError("Could not read a header row from the file.")
            columns = [str(h) for h in reader.fieldnames]
            rows = []
            for raw in reader:
                rows.append({c: raw.get(c) for c in columns})
                if len(rows) > MAX_ROWS:
                    raise ValueError(f"More than {MAX_ROWS} rows; refusing to load.")
        fmt = "tsv" if suffix == ".tsv" else "csv"
    else:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if suffix == ".jsonl":
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
            fmt = "jsonl"
        else:
            data = json.loads(text)
            if isinstance(data, dict):
                # Accept {"rows": [...]} / {"data": [...]} wrappers.
                for key in ("rows", "data", "records", "items"):
                    if isinstance(data.get(key), list):
                        data = data[key]
                        break
                else:
                    data = [data]
            if not isinstance(data, list):
                raise ValueError("JSON file must be an array of objects.")
            records = data
            fmt = "json"
        columns = []
        for rec in records:
            if not isinstance(rec, dict):
                raise ValueError("Every JSON record must be an object.")
            for key in rec:
                if str(key) not in columns:
                    columns.append(str(key))
        rows = [{c: rec.get(c) for c in columns} for rec in records]
        if len(rows) > MAX_ROWS:
            raise ValueError(f"More than {MAX_ROWS} rows; refusing to load.")

    return columns, rows, {"path": str(path), "format": fmt, "bytes": size}


def _sniff_dialect(sample: str):
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return "excel"


# --------------------------------------------------------------------------
# Type inference + profiling
# --------------------------------------------------------------------------

def _looks_like_date(value: str) -> bool:
    for fmt in _DATE_FORMATS:
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False


def _infer_type(values) -> str:
    """values: non-null raw values of one column."""
    if not values:
        return "empty"
    kinds = set()
    for v in values:
        if isinstance(v, bool):
            kinds.add("boolean")
        elif isinstance(v, int):
            kinds.add("integer")
        elif isinstance(v, float):
            kinds.add("float")
        elif isinstance(v, str):
            s = v.strip()
            if s.lower() in ("true", "false", "yes", "no"):
                kinds.add("boolean")
            elif re.fullmatch(r"[+-]?\d+", s):
                kinds.add("integer")
            elif re.fullmatch(r"[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?", s):
                kinds.add("float")
            elif _looks_like_date(s):
                kinds.add("date")
            else:
                kinds.add("string")
        else:
            kinds.add("string")
    if kinds == {"integer"}:
        return "integer"
    if kinds <= {"integer", "float"}:
        return "float"
    if len(kinds) == 1:
        return kinds.pop()
    return "string"


def _to_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def table_profile(args: dict, **kwargs) -> str:
    """Profile a data file with exact computed statistics."""
    path = (args.get("path") or "").strip()
    if not path:
        return json.dumps({"error": "No path provided"})
    try:
        columns, rows, meta = _load_table(path)
    except (ValueError, json.JSONDecodeError, OSError) as e:
        return json.dumps({"error": str(e)})

    seen = set()
    duplicate_rows = 0
    empty_rows = 0
    for r in rows:
        if all(_is_null(r.get(c)) for c in columns):
            empty_rows += 1
        key = tuple(None if _is_null(r.get(c)) else str(r.get(c)).strip() for c in columns)
        if key in seen:
            duplicate_rows += 1
        else:
            seen.add(key)

    col_stats = []
    for c in columns:
        raw = [r.get(c) for r in rows]
        non_null = [v for v in raw if not _is_null(v)]
        nulls = len(raw) - len(non_null)
        col_type = _infer_type(non_null)
        stat = {
            "name": c,
            "type": col_type,
            "nulls": nulls,
            "null_pct": round(100.0 * nulls / len(raw), 2) if raw else 0.0,
            "unique": len({str(v).strip() for v in non_null}),
        }
        if col_type in ("integer", "float"):
            nums = [n for n in (_to_number(v) for v in non_null) if n is not None]
            if nums:
                stat.update(
                    min=min(nums),
                    max=max(nums),
                    mean=round(statistics.fmean(nums), 6),
                    median=statistics.median(nums),
                )
        elif col_type in ("string", "boolean", "date"):
            top = Counter(str(v).strip() for v in non_null).most_common(5)
            stat["top_values"] = [{"value": v, "count": n} for v, n in top]
            if col_type == "string" and non_null:
                stat["max_length"] = max(len(str(v)) for v in non_null)
        col_stats.append(stat)

    return json.dumps(
        {
            "file": meta["path"],
            "format": meta["format"],
            "bytes": meta["bytes"],
            "rows": len(rows),
            "row_count_includes_empty": True,
            "empty_rows": empty_rows,
            "duplicate_rows": duplicate_rows,
            "columns": col_stats,
        },
        ensure_ascii=False,
    )


# --------------------------------------------------------------------------
# Read-only SQL query
# --------------------------------------------------------------------------

_DENIED_ACTIONS = {
    sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
    sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_CREATE_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_INDEX, sqlite3.SQLITE_CREATE_TEMP_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_TRIGGER, sqlite3.SQLITE_CREATE_TEMP_VIEW,
    sqlite3.SQLITE_CREATE_TRIGGER, sqlite3.SQLITE_CREATE_VIEW,
    sqlite3.SQLITE_DROP_INDEX, sqlite3.SQLITE_DROP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_INDEX, sqlite3.SQLITE_DROP_TEMP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_TRIGGER, sqlite3.SQLITE_DROP_TEMP_VIEW,
    sqlite3.SQLITE_DROP_TRIGGER, sqlite3.SQLITE_DROP_VIEW,
    sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH,
    sqlite3.SQLITE_PRAGMA, sqlite3.SQLITE_REINDEX, sqlite3.SQLITE_ANALYZE,
    sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_TRANSACTION,
}


def _authorizer(action, _arg1, _arg2, _db, _source):
    if action in _DENIED_ACTIONS:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_query(args: dict, **kwargs) -> str:
    """Run one read-only SQL query over the file, exposed as table `data`."""
    path = (args.get("path") or "").strip()
    sql = (args.get("sql") or "").strip()
    if not path:
        return json.dumps({"error": "No path provided"})
    if not sql:
        return json.dumps({"error": "No sql provided"})
    first = re.split(r"[\s(]+", sql.lstrip("("), 1)[0].lower() if sql else ""
    if first not in ("select", "with"):
        return json.dumps({"error": "Only read-only SELECT / WITH queries are allowed."})
    if ";" in sql.rstrip(";"):
        return json.dumps({"error": "Send a single query (no semicolon-separated statements)."})
    try:
        limit = int(args.get("limit") or 100)
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 1000))

    try:
        columns, rows, _meta = _load_table(path)
    except (ValueError, json.JSONDecodeError, OSError) as e:
        return json.dumps({"error": str(e)})

    col_types = {}
    for c in columns:
        non_null = [r.get(c) for r in rows if not _is_null(r.get(c))]
        col_types[c] = _infer_type(non_null)

    conn = sqlite3.connect(":memory:")
    try:
        defs = ", ".join(
            f"{_quote_ident(c)} {'REAL' if col_types[c] in ('integer', 'float') else 'TEXT'}"
            for c in columns
        )
        conn.execute(f"CREATE TABLE data ({defs})")
        insert = f"INSERT INTO data VALUES ({', '.join('?' for _ in columns)})"
        batch = []
        for r in rows:
            vals = []
            for c in columns:
                v = r.get(c)
                if _is_null(v):
                    vals.append(None)
                elif col_types[c] in ("integer", "float"):
                    vals.append(_to_number(v))
                else:
                    vals.append(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
            batch.append(vals)
        conn.executemany(insert, batch)

        # Lock the connection down only now that our own data is loaded:
        # from here on, just the user's single read-only query may run.
        conn.set_authorizer(_authorizer)
        start = time.monotonic()
        conn.set_progress_handler(
            lambda: 1 if time.monotonic() - start > QUERY_TIME_LIMIT_S else 0, 10_000
        )
        try:
            cur = conn.execute(sql.rstrip(";"))
            out_columns = [d[0] for d in cur.description] if cur.description else []
            fetched = cur.fetchmany(limit + 1)
        except sqlite3.Error as e:
            return json.dumps({"error": f"Query failed: {e}"})
        truncated = len(fetched) > limit
        fetched = fetched[:limit]
        # Total matched count: re-run without the return cap via a counting wrapper.
        try:
            total = conn.execute(
                f"SELECT COUNT(*) FROM ({sql.rstrip(';')})"
            ).fetchone()[0]
        except sqlite3.Error:
            total = None
        result_rows = [dict(zip(out_columns, row)) for row in fetched]
        return json.dumps(
            {
                "columns": out_columns,
                "rows": result_rows,
                "returned": len(result_rows),
                "total_matched": total,
                "truncated": truncated,
            },
            ensure_ascii=False,
            default=str,
        )
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Cleaning
# --------------------------------------------------------------------------

def _snake_case(name: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip())
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    s = re.sub(r"_+", "_", s).strip("_").lower()
    return s or "column"


def table_clean(args: dict, **kwargs) -> str:
    """Write a cleaned copy of the file and report exactly what changed."""
    path = (args.get("path") or "").strip()
    if not path:
        return json.dumps({"error": "No path provided"})
    try:
        columns, rows, meta = _load_table(path)
    except (ValueError, json.JSONDecodeError, OSError) as e:
        return json.dumps({"error": str(e)})

    in_path = Path(meta["path"])
    out_str = (args.get("out") or "").strip()
    out_path = Path(out_str).expanduser() if out_str else in_path.with_name(
        in_path.stem + ".cleaned.csv"
    )
    if out_path.resolve() == in_path.resolve():
        return json.dumps({"error": "Output path must differ from the input path — the input is never modified."})
    as_json = out_path.suffix.lower() == ".json"

    # Header normalisation with collision handling.
    renamed = {}
    new_columns = []
    used = set()
    for c in columns:
        base = _snake_case(c)
        name = base
        n = 2
        while name in used:
            name = f"{base}_{n}"
            n += 1
        used.add(name)
        new_columns.append(name)
        if name != c:
            renamed[c] = name

    dedupe = args.get("dedupe", True)
    dedupe_cols = args.get("dedupe_columns") or None
    if dedupe_cols:
        unknown = [c for c in dedupe_cols if c not in new_columns and c not in columns]
        if unknown:
            return json.dumps({"error": f"Unknown dedupe_columns: {unknown}. Columns: {columns}"})
        dedupe_idx = [columns.index(c) if c in columns else new_columns.index(c) for c in dedupe_cols]
    else:
        dedupe_idx = list(range(len(columns)))

    cleaned = []
    seen = set()
    empty_dropped = 0
    dup_dropped = 0
    cells_trimmed = 0
    for r in rows:
        vals = []
        for c in columns:
            v = r.get(c)
            if isinstance(v, str):
                trimmed = v.strip()
                if trimmed != v:
                    cells_trimmed += 1
                v = trimmed
            vals.append(v)
        if all(_is_null(v) for v in vals):
            empty_dropped += 1
            continue
        if dedupe:
            key = tuple(None if _is_null(vals[i]) else str(vals[i]) for i in dedupe_idx)
            if key in seen:
                dup_dropped += 1
                continue
            seen.add(key)
        cleaned.append({new_columns[i]: vals[i] for i in range(len(columns))})

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if as_json:
            out_path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=new_columns)
                writer.writeheader()
                for rec in cleaned:
                    writer.writerow({k: ("" if v is None else v) for k, v in rec.items()})
    except OSError as e:
        return json.dumps({"error": f"Could not write output: {e}"})

    return json.dumps(
        {
            "input": meta["path"],
            "output": str(out_path),
            "rows_in": len(rows),
            "rows_out": len(cleaned),
            "empty_rows_dropped": empty_dropped,
            "duplicate_rows_dropped": dup_dropped,
            "cells_trimmed": cells_trimmed,
            "headers_renamed": renamed,
            "columns": new_columns,
        },
        ensure_ascii=False,
    )
