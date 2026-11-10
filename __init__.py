"""data-wrangler plugin — registration.

Deterministic tools for local tabular data: profile, read-only SQL query,
and clean — computed exactly from the file, never estimated by the model.
"""

import logging
from pathlib import Path

from . import schemas, tools

logger = logging.getLogger(__name__)


def register(ctx):
    """Wire schemas to handlers and bundle the data-tables skill."""
    ctx.register_tool(
        name="table_profile", toolset="data-wrangler",
        schema=schemas.TABLE_PROFILE, handler=tools.table_profile,
    )
    ctx.register_tool(
        name="table_query", toolset="data-wrangler",
        schema=schemas.TABLE_QUERY, handler=tools.table_query,
    )
    ctx.register_tool(
        name="table_clean", toolset="data-wrangler",
        schema=schemas.TABLE_CLEAN, handler=tools.table_clean,
    )

    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                ctx.register_skill(child.name, skill_md)

    logger.debug("data-wrangler: registered table_profile, table_query, table_clean")
