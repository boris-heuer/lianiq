from pathlib import Path

from scripts.check_markdown_links import check_markdown_links, github_anchor


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_valid_relative_files_anchors_and_external_links(tmp_path: Path) -> None:
    guide = write(tmp_path / "docs" / "guide.md", "# Setup & safety\n\n## Setup & safety\n")
    readme = write(
        tmp_path / "README.md",
        "[guide](docs/guide.md#setup--safety)\n"
        "[duplicate](docs/guide.md#setup--safety-1)\n"
        "[external](https://example.com/missing)\n",
    )

    assert check_markdown_links(tmp_path, [readme, guide]) == []


def test_missing_relative_file_is_reported(tmp_path: Path) -> None:
    readme = write(tmp_path / "README.md", "[missing](docs/missing.md)\n")

    problems = check_markdown_links(tmp_path, [readme])

    assert len(problems) == 1
    assert problems[0].message == "relative target is missing"


def test_missing_relative_anchor_is_reported(tmp_path: Path) -> None:
    guide = write(tmp_path / "guide.md", "# Existing heading\n")
    readme = write(tmp_path / "README.md", "[missing](guide.md#not-there)\n")

    problems = check_markdown_links(tmp_path, [readme, guide])

    assert len(problems) == 1
    assert problems[0].message == "relative anchor is missing"


def test_fenced_examples_are_not_treated_as_links(tmp_path: Path) -> None:
    readme = write(tmp_path / "README.md", "```markdown\n[example](missing.md)\n```\n")

    assert check_markdown_links(tmp_path, [readme]) == []


def test_links_cannot_escape_repository(tmp_path: Path) -> None:
    readme = write(tmp_path / "README.md", "[outside](../outside.md)\n")

    problems = check_markdown_links(tmp_path, [readme])

    assert len(problems) == 1
    assert problems[0].message == "relative link leaves the repository"


def test_github_anchor_preserves_words_and_removes_markup() -> None:
    assert github_anchor("Windows **audio**: setup & safety") == "windows-audio-setup--safety"
