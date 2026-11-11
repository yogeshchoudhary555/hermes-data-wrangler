"""Standalone test for the data-wrangler plugin — no Hermes install needed.

Loads the plugin package the same way Hermes does (package import so the
relative imports in __init__.py work), captures register(ctx) calls with a
fake context, then exercises every tool handler against examples/.

Run:  python3 tests/test_local.py
"""

import importlib.util
import json
import sys
import tempfile
import types
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

    # Default `out` lands in the input file's own directory.
    defaulted = json.loads(ctx.tools["table_clean"]({"path": str(EXAMPLE)}))
    print("\nCLEAN (default out):", defaulted["output"])
    assert Path(defaulted["output"]).parent == EXAMPLE.parent
    assert Path(defaulted["output"]).name == "messy_sales.cleaned.csv"
    Path(defaulted["output"]).unlink()

    # --- File-safety guards: fake agent.file_safety via sys.modules ---
    # Proves _load_table consults get_read_block_error and returns its
    # message, and table_clean consults get_write_denied_error BEFORE
    # creating any directory or file.
    fake_pkg = types.ModuleType("agent")
    fake_pkg.__path__ = []
    fake_fs = types.ModuleType("agent.file_safety")

    def _fake_read_block(path):
        if path.endswith("auth.json"):
            return f"Access denied: {path} is a protected credential file."
        return None

    def _fake_write_denied(path, *, verb="Write"):
        if "/.ssh/" in path.replace("\\", "/"):
            return f"{verb} denied: '{path}' is a protected system/credential file."
        return None

    fake_fs.get_read_block_error = staticmethod(_fake_read_block)
    fake_fs.get_write_denied_error = staticmethod(_fake_write_denied)
    fake_pkg.file_safety = fake_fs
    sys.modules["agent"] = fake_pkg
    sys.modules["agent.file_safety"] = fake_fs
    try:
        with tempfile.TemporaryDirectory() as tmp:
            auth = Path(tmp) / "auth.json"
            auth.write_text(json.dumps([{"token": "sekrit"}]), encoding="utf-8")
            blocked_read = json.loads(ctx.tools["table_profile"]({"path": str(auth)}))
            print("\nBLOCKED READ:", blocked_read)
            assert "error" in blocked_read
            assert "Access denied" in blocked_read["error"]

            denied_out = Path(tmp) / ".ssh" / "authorized_keys"
            blocked_write = json.loads(ctx.tools["table_clean"]({
                "path": str(EXAMPLE), "out": str(denied_out),
            }))
            print("\nBLOCKED WRITE:", blocked_write)
            assert "error" in blocked_write
            assert "denied" in blocked_write["error"]
            assert not denied_out.exists(), "guard must refuse before creating the file"
            assert not (Path(tmp) / ".ssh").exists(), "guard must refuse before mkdir"
    finally:
        del sys.modules["agent"]
        del sys.modules["agent.file_safety"]

    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()
