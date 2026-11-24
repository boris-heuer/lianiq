"""Unit tests of the automated-PO-rows building blocks (spec §2.1; CAP-0174 AC-08, AC-12).

Junctions are real (Windows CI); the app, the cable and the admin helper are fakes.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy
import pytest

from native_e2e import audio, fixtures, models_swap, proc, uia
from native_e2e.context import RunContext
from native_e2e.evidence.model import Status
from native_e2e.rows import c05, s04, teardown, ui
from native_e2e.uia import Node


@pytest.fixture
def ctx(tmp_path) -> RunContext:
    image_root, models = tmp_path / "image", tmp_path / "image-models"
    image_root.mkdir()
    models.mkdir()
    (models / "keep.bin").write_bytes(b"model")
    (image_root / "image.json").write_text(json.dumps({"models_dir": str(models)}), "utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    context = RunContext("a" * 40, tmp_path / "out", repo, image_root=image_root)
    context.temp = tmp_path / "temp"
    models_swap.repoint(repo / "models", models)
    return context


def test_scratch_models_swaps_and_restores_even_when_the_row_raises(ctx) -> None:
    link, models = ctx.repo / "models", models_swap.image_models(ctx)
    with pytest.raises(RuntimeError), models_swap.scratch_models(ctx, "E-16") as folder:
        assert models_swap.points_to(link, folder) and not any(folder.iterdir())
        (link / "written.txt").write_text("x", "utf-8")  # writable through the junction
        raise RuntimeError("row failed")
    assert models_swap.points_to(link, models)
    assert (models / "keep.bin").read_bytes() == b"model"  # the target is never deleted
    assert (folder / "written.txt").is_file()
    assert ctx.state["models_scratch"] == [str(folder)]


def test_t05_restores_the_junction_and_deletes_the_scratch_folders(ctx) -> None:
    folder = models_swap.scratch_folder(ctx, "E-18")
    models_swap.repoint(ctx.repo / "models", folder)  # a row left it on its scratch folder
    row = teardown.t05(ctx)
    assert row.status is Status.PASS and row.acs == ("AC-08",)
    assert models_swap.points_to(ctx.repo / "models", models_swap.image_models(ctx))
    assert not folder.exists() and (models_swap.image_models(ctx) / "keep.bin").is_file()


def test_a_real_models_folder_is_never_removed(ctx) -> None:
    link = ctx.repo / "models"
    models_swap.os.rmdir(link)
    link.mkdir()
    (link / "own.bin").write_bytes(b"x")
    with pytest.raises(RuntimeError):
        models_swap.repoint(link, ctx.temp)
    assert teardown.t05(ctx).status is Status.FAIL and (link / "own.bin").is_file()


def test_corrupt_copy_flips_one_byte_of_the_largest_file(tmp_path) -> None:
    from native_e2e import packs_import

    src = tmp_path / "pack"
    (src / "sub").mkdir(parents=True)
    (src / "small.txt").write_bytes(b"abc")
    (src / "sub" / "big.bin").write_bytes(bytes(range(200)))
    changed = packs_import.make_corrupt_copy(src, tmp_path / "copy")
    assert changed == tmp_path / "copy" / "sub" / "big.bin"
    before, after = (src / "sub" / "big.bin").read_bytes(), changed.read_bytes()
    assert sum(a != b for a, b in zip(before, after, strict=True)) == 1
    assert (tmp_path / "copy" / "small.txt").read_bytes() == b"abc"


def test_row_state_reads_the_pack_row_name() -> None:
    from native_e2e import packs_import

    nodes = [Node("opus-mt-de-zh 1", "Text"), Node("opus-mt-de-zh, Validated", "Group")]
    assert packs_import.row_state(nodes, "opus-mt-de-zh") == "Validated"
    assert packs_import.row_state(nodes, "faster-whisper-small") is None


def test_speech_span_finds_the_first_and_last_loud_frame() -> None:
    rate = 16_000
    samples = numpy.zeros(rate * 2, dtype="float32")
    samples[rate // 2 : rate] = 0.5  # 0.5 s .. 1.0 s
    assert audio.speech_span(samples, rate) == pytest.approx((0.5, 1.0))
    assert audio.speech_span(numpy.zeros(rate, dtype="<i2"), rate) is None


def test_cable_recorder_marks_positions_on_the_sample_timeline(monkeypatch) -> None:
    streams: list = []

    class Stream:
        def __init__(self, samplerate, channels, device, callback) -> None:
            self.callback = callback
            streams.append(self)

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(audio, "_capture_device", lambda: (3, 1000))
    monkeypatch.setattr(audio, "_sd", lambda: SimpleNamespace(InputStream=Stream))
    recorder = audio.CableRecorder().start()
    streams[0].callback(numpy.ones((500, 1), dtype="float32"), 500, None, None)
    assert recorder.mark() == 0.5
    rate, samples = recorder.stop()
    assert rate == 1000 and samples.shape == (500,)


def test_count_since_reads_the_wfp_count(monkeypatch, ctx) -> None:
    answers = iter([s04.admin.AdminResult(True, "3"), s04.admin.AdminResult(False, None, "x")])
    monkeypatch.setattr(s04, "_ask", lambda *args, **kwargs: next(answers))
    assert s04.count_since(ctx, "2026-11-24T10:00:00+00:00") == 3
    assert s04.count_since(ctx, "2026-11-24T10:00:00+00:00") is None


class FocusApp:
    def __init__(self, cycle: list[Node]) -> None:
        self.cycle, self.position, self.pressed = cycle, -1, 0

    def keys(self, text: str) -> None:
        assert text == "{TAB}"
        self.pressed += 1
        self.position = (self.position + 1) % len(self.cycle)

    def focused(self) -> Node:
        return self.cycle[self.position]


def test_tab_walk_stops_when_the_first_element_repeats_and_returns_no_names() -> None:
    cycle = [Node("Start", "Button"), Node("", "CheckBox"), Node("Microphone X", "ComboBox")]
    app = FocusApp(cycle)
    stops = ui.tab_walk(app)
    assert stops == [("Button", True), ("CheckBox", False), ("ComboBox", True)]
    assert app.pressed == 4
    assert len(ui.tab_walk(FocusApp(cycle), max_stops=2)) == 2


def test_launch_keeps_the_no_setup_assistant_default(monkeypatch, tmp_path) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(uia.subprocess, "Popen", lambda args, **kwargs: seen.append(args))
    uia.launch_app("py", tmp_path)
    uia.launch_app("py", tmp_path, setup_assistant=True)
    assert seen == [["py", "-m", "lianiq", "--no-setup-assistant"], ["py", "-m", "lianiq"]]


def test_fixtures_are_checked_against_their_pins(monkeypatch, tmp_path) -> None:
    for name in fixtures.PINNED:
        assert fixtures.checked(name) == fixtures.FOLDER / name
    assert fixtures.checked("conv_zh_16k.wav") is None  # not generated yet: rows block
    monkeypatch.setattr(fixtures, "FOLDER", tmp_path)
    (tmp_path / "conv_de_16k.wav").write_bytes(b"changed")
    assert fixtures.checked("conv_de_16k.wav") is None


def tool(code: int, output: str = "secret line"):
    return lambda args, cwd, timeout_s: proc.ToolResult(code, output, False)


@pytest.mark.parametrize(("row", "script"), [("c05", "self_test"), ("c06", "call_bridge")])
def test_c05_and_c06_run_their_script_and_pass_on_exit_0(monkeypatch, ctx, row, script) -> None:
    seen: list = []
    monkeypatch.setattr(
        proc, "run_tool", lambda args, cwd, t: seen.append(args) or tool(0)(args, cwd, t)
    )
    result = getattr(c05, row)(ctx)
    assert result.status is Status.PASS and result.acs == ("AC-12",)
    assert script in seen[0][1] and len(seen[0]) == 2  # no --synthetic: C-04 runs that
    monkeypatch.setattr(proc, "run_tool", tool(2))
    assert getattr(c05, row)(ctx).status is Status.FAIL


def test_c09_runs_doctor_only_and_needs_zero_connections(monkeypatch, ctx) -> None:
    seen: list = []
    monkeypatch.setattr(
        proc, "run_tool", lambda args, cwd, t: seen.append(args) or tool(0)(args, cwd, t)
    )
    monkeypatch.setattr(s04, "count_since", lambda ctx, since: 0)
    assert c05.c09(ctx).status is Status.PASS
    assert [args[1] for args in seen] == ["scripts/doctor.py"]
    monkeypatch.setattr(s04, "count_since", lambda ctx, since: 1)
    row = c05.c09(ctx)
    assert (row.status, row.checks[-1].detail) == (Status.FAIL, "count=1")


def test_first_run_launch_deletes_the_local_settings_and_the_baseline_restores(
    monkeypatch, ctx
) -> None:
    from native_e2e import uia_app

    started: list[bool] = []
    monkeypatch.setattr(
        uia_app.uia, "launch_app", lambda *a, setup_assistant: started.append(setup_assistant)
    )
    monkeypatch.setattr(
        uia_app.uia, "connect", lambda process: SimpleNamespace(set_focus=lambda: None)
    )
    with pytest.raises(RuntimeError):
        uia_app.launch(ctx, setup_assistant=True)  # no S-03 backup: nothing is deleted
    backup = ctx.repo / "backup.json"
    backup.write_text("{}", "utf-8")
    from native_e2e.evidence.sums import file_sha256

    ctx.state["settings_backup"] = {
        "existed": True,
        "path": str(backup),
        "sha256": file_sha256(backup),
    }
    ctx.local_settings.parent.mkdir(parents=True)
    ctx.local_settings.write_text('{"changed": true}', "utf-8")
    uia_app.launch(ctx, setup_assistant=True)
    assert started == [True] and not ctx.local_settings.exists()
    assert uia_app.settings_reset(ctx) and ctx.local_settings.read_text("utf-8") == "{}"
    ctx.state["settings_backup"] = {"existed": False}
    assert uia_app.settings_reset(ctx) and not ctx.local_settings.exists()


class PacksApp:
    """Language packs page, details dialog, its Import… menu and the folder dialog."""

    MODEL, LICENCE = "opus-mt-de-zh", "I accept the licence (Apache-2.0)"

    def __init__(self) -> None:
        self.page, self.state = "Conversation", "Downloadable"
        self.details = self.licence = self.menu = self.picker = False
        self.typed: list[str] = []

    def nodes(self) -> list[Node]:
        entries = [
            Node(n, "CheckBox", selected=self.page == n, parents=("Lianiq", "Workspaces"))
            for n in ("Conversation", "Language packs")
        ]
        row = f"{self.MODEL}, {self.state}"
        if self.page == "Language packs":
            entries += [Node(row, "Group"), Node("Get…", "Button", parents=("Lianiq", row))]
        return entries

    def press(self, node: Node) -> None:
        if node.parents[-1:] == ("Workspaces",):
            self.page = node.name
        elif node.name == "Get…":
            self.details = True
        elif node.name == self.LICENCE:
            self.licence = True
        elif node.name == "Import…":
            self.menu = True
        elif node.automation_id == "1":
            self._picked()

    def click(self, node: Node) -> None:
        assert node.name == "Choose folder…"
        self.menu, self.picker = False, True

    def popup_nodes(self) -> list[Node]:
        return [Node("Choose folder…", "MenuItem")] if self.menu else []

    def window_nodes(self, title: str) -> list[Node] | None:
        if title == self.MODEL and self.details:
            return [
                Node(self.LICENCE, "CheckBox", selected=self.licence),
                Node("Import…", "Button"),
            ]
        if title == "Choose folder…" and self.picker:
            return [
                Node("", "Edit", automation_id="1001"),
                Node("Select Folder", "Button", automation_id="1"),
            ]
        return None

    def type_into(self, node: Node, text: str, enter: bool = True) -> None:
        assert not enter  # Enter would navigate into the folder
        self.typed.append(text)

    def _picked(self) -> None:
        self.picker = self.details = False
        self.state = "Validated"


def test_import_folder_drives_the_dialogs_and_waits_for_validated(tmp_path) -> None:
    from native_e2e import packs_import

    (tmp_path / "lianiq-pack.json").write_text("{}", "utf-8")
    app = PacksApp()
    assert packs_import.import_folder(app, "mt-de-zh-hans", tmp_path) == "validated"
    assert app.typed == [str(tmp_path)]


def test_import_is_blocked_without_the_pack_file(tmp_path) -> None:
    from native_e2e import packs_import

    app = PacksApp()
    assert (
        packs_import.import_folder(app, "mt-de-zh-hans", tmp_path) == packs_import.PACK_FILE_MISSING
    )
    assert app.page == "Conversation" and app.typed == []
