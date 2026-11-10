"""Tool schemas — what the LLM sees."""

TABLE_PROFILE = {
    "name": "table_profile",
    "description": (
        "Profile a local tabular data file (CSV, TSV, JSON array of objects, or JSONL) "
        "and return exact, computed facts about it: row and column counts, per-column "
        "inferred type (integer/float/boolean/date/string), null counts and percentages, "
        "distinct-value counts, min/max/mean/median for numeric columns, the most common "
        "values for text columns, and how many rows are exact duplicates or fully empty. "
        "Use this before answering any question about a data file, and whenever the user "
        "asks what a dataset contains, whether it is clean, or how big it is. The numbers "
        "are computed from the file, never estimated."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the data file (e.g. 'sales.csv', '/home/user/data/users.json').",
            },
        },
        "required": ["path"],
    },
}

TABLE_QUERY = {
    "name": "table_query",
    "description": (
        "Run a read-only SQL query against a local tabular data file (CSV, TSV, JSON, "
        "JSONL). The file is loaded as a single table named `data` with its original "
        "column names; numeric-looking columns are stored as numbers so SUM/AVG/ORDER BY "
        "behave numerically. Only SELECT/WITH queries are allowed — writes are rejected. "
        "Returns the result rows plus the total matched count. Use this to answer exact "
        "questions about a dataset (totals, averages, group-bys, top-N, filters) instead "
        "of guessing from a preview."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the data file.",
            },
            "sql": {
                "type": "string",
                "description": "A single read-only SQL query over the table `data` (e.g. \"SELECT region, SUM(amount) FROM data GROUP BY region ORDER BY 2 DESC\").",
            },
            "limit": {
                "type": "integer",
                "description": "Max rows to return (default 100, max 1000). The total matched count is always reported.",
            },
        },
        "required": ["path", "sql"],
    },
}

TABLE_CLEAN = {
    "name": "table_clean",
    "description": (
        "Write a cleaned copy of a local tabular data file (CSV, TSV, JSON, JSONL) and "
        "report exactly what changed. Cleaning: column names normalised to snake_case, "
        "leading/trailing whitespace trimmed from headers and text cells, fully-empty "
        "rows dropped, and exact duplicate rows removed (optionally on a subset of "
        "columns). The input file is never modified. Output is CSV by default (or JSON "
        "when `out` ends in .json). Use this when the user asks to clean, tidy, dedupe "
        "or normalise a dataset."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the input data file.",
            },
            "out": {
                "type": "string",
                "description": "Output path (default: '<name>.cleaned.csv' next to the input). Must differ from the input path.",
            },
            "dedupe": {
                "type": "boolean",
                "description": "Remove duplicate rows (default true).",
            },
            "dedupe_columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Only consider these columns when deciding duplicates (default: all columns).",
            },
        },
        "required": ["path"],
    },
}
