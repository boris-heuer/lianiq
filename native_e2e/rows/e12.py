"""E-12: the shell docs test and the Markdown link check pass on the commit (contract §5).

Only presence and links are automated; content accuracy stays with PR review.
"""

from __future__ import annotations

from native_e2e import proc
from native_e2e.context import RunContext
from native_e2e.evidence.model import Row
from native_e2e.rows.common import make_row

TIMEOUT_S = 300
TOOLS = (
    ("shell-docs-test", ["-m", "pytest", "-p", "no:cacheprovider", "tests/test_shell_docs.py"]),
    ("markdown-links", ["scripts/check_markdown_links.py"]),
)


def run(ctx: RunContext) -> Row:
    checks, artifacts = [], []
    for name, script in TOOLS:
        result = proc.run_tool([ctx.python, *script], ctx.repo, TIMEOUT_S)
        artifacts.append(ctx.write_log(f"logs/e12-{name}.txt", result.output))
        checks.append(proc.tool_check(name, result))
    return make_row("E-12", checks, artifacts, reason="tool-failed")
