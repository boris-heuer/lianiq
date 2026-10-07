from __future__ import annotations

import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

INLINE_LINK_RE = re.compile(
    r"!?\[[^\]]*\]\(\s*(?:<(?P<angle>[^>]+)>|(?P<plain>[^\s)]+))"
)
REFERENCE_LINK_RE = re.compile(
    r"^\s*\[[^\]]+\]:\s*(?:<(?P<angle>[^>]+)>|(?P<plain>\S+))"
)
ATX_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(?P<text>.+?)\s*#*\s*$")
SETEXT_HEADING_RE = re.compile(r"^\s{0,3}(?:=+|-+)\s*$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
IGNORED_PARTS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
    "node_modules",
}


@dataclass(frozen=True, slots=True)
class LinkProblem:
    source: Path
    line: int
    target: str
    message: str

    def render(self, root: Path) -> str:
        source = self.source.relative_to(root).as_posix()
        return f"{source}:{self.line}: {self.message}: {self.target}"


def tracked_markdown_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--", "*.md"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [
        root / relative
        for relative in result.stdout.splitlines()
        if relative and not IGNORED_PARTS.intersection(Path(relative).parts)
    ]


def check_markdown_links(root: Path, files: list[Path] | None = None) -> list[LinkProblem]:
    root = root.resolve()
    markdown_files = files if files is not None else tracked_markdown_files(root)
    problems: list[LinkProblem] = []
    anchor_cache: dict[Path, set[str]] = {}

    for source in markdown_files:
        source = source.resolve()
        for line_number, target in markdown_targets(source):
            split = urlsplit(target)
            if split.scheme or split.netloc:
                continue

            relative_path = unquote(split.path)
            candidate = (
                root / relative_path.lstrip("/")
                if relative_path.startswith("/")
                else source.parent / relative_path
            ).resolve()
            if not candidate.is_relative_to(root):
                problems.append(
                    LinkProblem(source, line_number, target, "relative link leaves the repository")
                )
                continue
            if relative_path and not candidate.exists():
                problems.append(LinkProblem(source, line_number, target, "relative target is missing"))
                continue

            if not split.fragment:
                continue
            anchor_source = candidate if relative_path else source
            if anchor_source.suffix.casefold() not in {".md", ".markdown"}:
                continue
            if not anchor_source.is_file():
                problems.append(LinkProblem(source, line_number, target, "anchor target is not a file"))
                continue
            anchors = anchor_cache.setdefault(anchor_source, markdown_anchors(anchor_source))
            fragment = unquote(split.fragment).removeprefix("user-content-").casefold()
            if fragment not in anchors:
                problems.append(LinkProblem(source, line_number, target, "relative anchor is missing"))

    return problems


def markdown_targets(path: Path) -> list[tuple[int, str]]:
    targets: list[tuple[int, str]] = []
    fence: str | None = None
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)[0]
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence is not None:
            continue
        for match in INLINE_LINK_RE.finditer(line):
            targets.append((line_number, match.group("angle") or match.group("plain")))
        reference = REFERENCE_LINK_RE.match(line)
        if reference:
            targets.append((line_number, reference.group("angle") or reference.group("plain")))
    return targets


def markdown_anchors(path: Path) -> set[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    fence: str | None = None
    for index, line in enumerate(lines):
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)[0]
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence is not None:
            continue
        heading = ATX_HEADING_RE.match(line)
        text = heading.group("text") if heading else None
        if text is None and index + 1 < len(lines) and SETEXT_HEADING_RE.match(lines[index + 1]):
            text = line.strip()
        if not text:
            continue
        base = github_anchor(text)
        duplicate = counts.get(base, 0)
        counts[base] = duplicate + 1
        anchors.add(base if duplicate == 0 else f"{base}-{duplicate}")
    return anchors


def github_anchor(heading: str) -> str:
    heading = re.sub(r"<[^>]+>", "", heading)
    heading = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", heading)
    heading = re.sub(r"[`*_~]", "", heading).strip().casefold()
    heading = "".join(
        character
        for character in heading
        if character in {"-", "_", " "}
        or not unicodedata.category(character).startswith(("P", "S"))
    )
    return re.sub(r"\s", "-", heading)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    try:
        problems = check_markdown_links(root)
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        print(f"Markdown link validation could not run: {exc}", file=sys.stderr)
        return 2
    if problems:
        for problem in problems:
            print(problem.render(root), file=sys.stderr)
        print(f"Markdown link validation failed with {len(problems)} problem(s).", file=sys.stderr)
        return 1
    print("Markdown link validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
