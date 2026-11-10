"""Standalone test for the data-wrangler plugin — no Hermes install needed.

Loads the plugin package the same way Hermes does (package import so the
relative imports in __init__.py work), captures register(ctx) calls with a
fake context, then exercises every tool handler against examples/.

Run:  python3 tests/test_local.py
"""

import importlib.util
import json
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
EXAMPLE = PLUGIN_DIR / "examples" / "messy_sales.csv"


class FakeCtx:
    def __init__(self):
        self.tools = {}
        self.skills = {}

    def register_tool(self, name, toolset, schema, handler):
        assert schema["name"] == name, f"schema name mismatch for {name}"
        self.tools[name] = handler

    def register_skill(self, name, path):
        assert Path(path).is_file(), f"skill file missing: {path}"
        self.skills[name] = str(path)


def load_plugin():
    spec = importlib.util.spec_from_file_location(
        "data_wrangler", PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["data_wrangler"] = module
    spec.loader.exec_module(module)
    return module


def main():
    plugin = load_plugin()
    ctx = FakeCtx()
    plugin.register(ctx)
    print("registered tools:", sorted(ctx.tools))
    print("registered skills:", sorted(ctx.skills))
    assert set(ctx.tools) == {"table_profile", "table_query", "table_clean"}
    assert "data-tables" in ctx.skills

    profile = json.loads(ctx.tools["table_profile"]({"path": str(EXAMPLE)}))
    print("\nPROFILE:", json.dumps(profile, indent=2)[:1200])
    assert profile["rows"] == 14, profile["rows"]
    assert profile["empty_rows"] == 1
    assert profile["duplicate_rows"] == 1
    price = next(c for c in profile["columns"] if c["name"] == "Price (USD)")
    assert price["type"] == "float" and price["nulls"] == 2, price  # 1 real gap + 1 from the empty row
    region = next(c for c in profile["columns"] if c["name"] == " Region ")
    assert region["type"] == "string", region

    q = json.loads(ctx.tools["table_query"]({
        "path": str(EXAMPLE),
        "sql": 'SELECT " Region " AS region, SUM("Price (USD)" * "Units Sold") AS revenue '
               "FROM data GROUP BY 1 ORDER BY 2 DESC",
    }))
    print("\nQUERY:", json.dumps(q, indent=2))
    # 4 real regions + 1 NULL group (the empty row). East wins on exact math —
    # West only looks bigger until the duplicate row is accounted for.
    assert q["total_matched"] == 5
    assert q["rows"][0]["region"].strip() == "East"
    assert abs(q["rows"][0]["revenue"] - 381.73) < 1e-9

    blocked = json.loads(ctx.tools["table_query"]({
        "path": str(EXAMPLE), "sql": "DELETE FROM data",
    }))
    print("\nWRITE BLOCKED:", blocked)
    assert "error" in blocked

    out = EXAMPLE.parent / "messy_sales.cleaned.csv"
    if out.exists():
        out.unlink()
    clean = json.loads(ctx.tools["table_clean"]({"path": str(EXAMPLE), "out": str(out)}))
    print("\nCLEAN:", json.dumps(clean, indent=2))
    assert clean["rows_in"] == 14 and clean["rows_out"] == 12
    assert clean["empty_rows_dropped"] == 1 and clean["duplicate_rows_dropped"] == 1
    assert clean["headers_renamed"].get("Price (USD)") == "price_usd"

    after = json.loads(ctx.tools["table_profile"]({"path": str(out)}))
    assert after["duplicate_rows"] == 0 and after["empty_rows"] == 0
    print("\nPROFILE AFTER CLEAN: rows =", after["rows"],
          "| columns =", [c["name"] for c in after["columns"]])
    out.unlink()

    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()
