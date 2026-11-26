"""Unit tests of the English ↔ Mandarin rows E-39 and E-40 (english-mandarin-pair 9-E-01, 9-E-04).

The real window, pywinauto, the image packs and the voices exist only in the VM image. Here a
fake Language packs page and the shared ``FakeApp`` (Conversation with a pair combo) stand in;
the image's pack folders and manifest are written into ``tmp_path``. The tests pin the pass
rules, the ``english-packs-missing`` gate and that texts never reach the evidence.
"""

from __future__ import annotations

import json
import wave

import pytest

from native_e2e import audio, packs_import, proc, screens, speech_pair, uia_app
from native_e2e.evidence.model import Method, Status
from native_e2e.rows import e39, e40, ui
from native_e2e.uia import Node
from tests._native_fake_app import PANEL_RECTS, FakeApp, install, make_ctx
from tests._native_png import red_png

EN_PAIR, DE_PAIR = "English ↔ Mandarin (Simplified)", "German ↔ Mandarin (Simplified)"
EN, ZH = "We can deliver 250 units next Tuesday.", "我们下周不能来。"
EN_ZH = ("English: " + EN, "Mandarin (Simplified): 我们下周二可以交付250个单位。")
ZH_EN = ("Mandarin (Simplified): " + ZH, "English: We can't come next week.")
TOP = ("lianiq",)


def image_packs(ctx, sha_ok: bool = True, files: bool = True) -> None:
    """The three English packs in the image models and their manifest records."""
    artifacts, records = [], []
    for pack_id in e39.ENGLISH_PACKS:
        pack, folder = packs_import.pack(pack_id), packs_import.image_pack_dir(ctx, pack_id)
        for item in pack.files if files else ():
            (folder / item.path).parent.mkdir(parents=True, exist_ok=True)
            (folder / item.path).write_bytes(b"")
            sha = item.sha256 if sha_ok else "0" * 64
            artifacts.append({"path": f"{pack.root}/{item.path}", "sha256": sha})
        records.append(
            {
                "id": pack_id,
                "version": pack.version,
                "source": "script",
                "installed_at": "2026-11-24T10:00:00+00:00",
                "licence": pack.licence,
                "licence_accepted_at": None,
            }
        )
    manifest = {"schema_version": 1, "artifacts": artifacts, "packs": records}
    target = packs_import.models_swap.image_models(ctx) / "model-manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest), encoding="utf-8")


class PacksApp:
    rect = (100, 100, 900, 700)

    def __init__(self, state: str = "Validated") -> None:
        self.page, self.state, self.closed = "Conversation", state, False

    def nodes(self) -> list[Node]:
        out = [
            Node(name, "CheckBox", selected=name == self.page, parents=(*TOP, "Workspaces"))
            for name in ("Conversation", "Language packs")
        ]
        if self.page == "Language packs":
            out.append(Node("Models folder: C:\\Users\\po\\models — 9 GB free", "Text"))
            for pack_id in e39.ENGLISH_PACKS:
                out.append(Node(f"{packs_import.pack(pack_id).model}, {self.state}", "Group"))
        else:
            out.append(Node("Language pair", "ComboBox", value=DE_PAIR, parents=TOP))
        return out

    def press(self, node: Node) -> None:
        self.page = node.name

    def close(self) -> int:
        self.closed = True
        return 0


def e39_setup(monkeypatch, tmp_path, items=(DE_PAIR, EN_PAIR), code=0, **packs):
    ctx = make_ctx(tmp_path)
    image_packs(ctx, **packs)
    app = PacksApp()
    monkeypatch.setattr(uia_app, "launch", lambda ctx, **_: app)
    monkeypatch.setattr(screens, "grab", red_png)
    monkeypatch.setattr(audio, "endpoint_names", lambda: ["CABLE Output"])
    monkeypatch.setattr(e39, "combo_items", lambda combo: list(items))
    result = proc.ToolResult(code, "doctor output ready", False)
    monkeypatch.setattr(proc, "run_tool", lambda args, cwd, timeout: result)
    for name, value in (("TIMEOUT_S", 0.3), ("MODEL_TIMEOUT_S", 0.3), ("POLL_S", 0.01)):
        monkeypatch.setattr(ui, name, value)
    return ctx, app


def failed(row) -> set[str]:
    return {item.name for item in row.checks if item.result is Status.FAIL}


def test_e39_passes_on_validated_english_packs_the_pair_choice_and_doctor(
    monkeypatch, tmp_path
) -> None:
    ctx, app = e39_setup(monkeypatch, tmp_path)
    row = e39.run(ctx)
    assert row.status is Status.PASS, row.checks
    assert row.acs == ("AC-03", "AC-06") and app.closed
    details = {item.name: item.detail for item in row.checks}
    assert details["tts-en-us-ljspeech-high-source-licence-sha256"] == (
        "source=script licence=true sha256=3/3"
    )
    assert [a.path for a in row.artifacts] == [e39.SCREEN, e39.DOCTOR_LOG]
    log = (ctx.out / e39.DOCTOR_LOG).read_text(encoding="utf-8")
    assert "doctor output" not in log and "output_sha256=" in log


@pytest.mark.parametrize(
    ("setup", "name"),
    [
        ({"items": (EN_PAIR, "German ↔ English")}, "german-english-not-offered"),
        ({"items": (DE_PAIR,)}, "english-mandarin-offered"),
        ({"code": 1}, "doctor-exit-code-0"),
        ({"sha_ok": False}, "mt-en-zh-hans-source-licence-sha256"),
    ],
)
def test_e39_fails_each_rule(monkeypatch, tmp_path, setup, name) -> None:
    ctx, _app = e39_setup(monkeypatch, tmp_path, **setup)
    row = e39.run(ctx)
    assert row.status is Status.FAIL and name in failed(row)


def test_e39_fails_a_pack_row_that_is_not_validated(monkeypatch, tmp_path) -> None:
    ctx, app = e39_setup(monkeypatch, tmp_path)
    app.state = "Downloadable"
    assert "mt-zh-hans-en-validated" in failed(e39.run(ctx))


def test_both_rows_are_blocked_without_the_english_packs(monkeypatch, tmp_path) -> None:
    ctx, _app = e39_setup(monkeypatch, tmp_path, files=False)
    monkeypatch.setattr(uia_app, "launch", lambda ctx, **_: pytest.fail("no app"))
    for module, row_id in ((e39, "E-39"), (e40, "E-40")):
        row = module.run(ctx)
        assert (row.id, row.status, row.reason) == (row_id, Status.BLOCKED, e39.MISSING)


class PairApp(FakeApp):
    """``FakeApp`` with a pair combo and turns per synthesised WAV."""

    def __init__(self, **knobs) -> None:
        super().__init__(**knobs)
        self.pair = DE_PAIR
        self.voices = dict.fromkeys(("Speak English", "Speak Mandarin (Simplified)"), True)

    def _conversation(self, top) -> list[Node]:
        a, b = self.pair.split(" ↔ ")
        return [
            Node("Language pair", "ComboBox", value=self.pair, parents=top),
            Node("Conversation direction", "ComboBox", value=f"Automatic ({a} ↔ {b})"),
            *(Node(n, "CheckBox", selected=on, parents=top) for n, on in self.voices.items()),
            Node("Original", "Text"),
            Node("Original", "Edit", value=self.original, rect=PANEL_RECTS[0]),
            Node("Translation", "Text"),
            Node("Translation", "Edit", value=self.translation, rect=PANEL_RECTS[1]),
        ]

    def choose(self, node: Node, item: str) -> None:
        if node.name != "Language pair":
            return super().choose(node, item)
        if self.knobs.get("no_english"):
            raise IndexError("item not found")
        self.pair = item

    def hear(self, path) -> None:
        if not self.running or self.knobs.get("deaf") == path.name:
            return
        source, target = EN_ZH if path.name == speech_pair.EN else ZH_EN
        self.original += source + "\n\n"
        self.translation += target + "\n\n"


def e40_setup(monkeypatch, tmp_path, **knobs):
    ctx = make_ctx(tmp_path)
    app = PairApp(**knobs)
    install(monkeypatch, app)
    monkeypatch.setattr(audio, "play_into_cable", app.hear)
    monkeypatch.setattr(e39, "packs_missing", lambda ctx: 0)
    made = []

    def wavs(ctx):
        for name in (speech_pair.EN, speech_pair.ZH):
            ctx.secrets += [text for _lang, text in speech_pair.SPEECH[name]]
            path = ctx.temp / "speech" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"RIFF")
            made.append(path)
        return list(made)

    monkeypatch.setattr(speech_pair, "speech_wavs", wavs)
    return ctx, app, made


def test_e40_passes_with_one_translation_each_way(monkeypatch, tmp_path) -> None:
    ctx, app, made = e40_setup(monkeypatch, tmp_path)
    row = e40.run(ctx)
    assert row.status is Status.PASS, row.checks
    assert row.method is Method.VIRTUAL_DEVICE and row.acs == ("AC-14",)
    details = {item.name: item.detail for item in row.checks}
    assert details["en-to-zh-hans-turn"] == details["zh-hans-to-en-turn"] == "turns=1"
    assert app.pair == EN_PAIR and not app.running and app.closed
    assert not any(path.exists() for path in made)
    assert {EN, ZH} <= set(ctx.secrets) and EN_ZH[1] in ctx.secrets
    stored = repr(row)
    assert EN not in stored and ZH not in stored and "交付" not in stored


@pytest.mark.parametrize(
    ("knobs", "name"),
    [
        ({"deaf": speech_pair.ZH}, "zh-hans-to-en-turn"),
        ({"deaf": speech_pair.EN}, "en-to-zh-hans-turn"),
        ({"no_english": True}, "pair-english-mandarin"),
    ],
)
def test_e40_fails_without_a_turn_or_the_pair(monkeypatch, tmp_path, knobs, name) -> None:
    ctx, app, made = e40_setup(monkeypatch, tmp_path, **knobs)
    row = e40.run(ctx)
    assert row.status is Status.FAIL and name in failed(row)
    assert app.closed and not app.running and not any(path.exists() for path in made)


def test_e40_fails_when_speech_cannot_be_synthesised(monkeypatch, tmp_path) -> None:
    ctx, _app, _made = e40_setup(monkeypatch, tmp_path)

    def broken(ctx):
        raise FileNotFoundError("C:\\Users\\po\\models\\voice.onnx")

    monkeypatch.setattr(speech_pair, "speech_wavs", broken)
    monkeypatch.setattr(uia_app, "launch", lambda ctx, **_: pytest.fail("no app"))
    row = e40.run(ctx)
    assert row.status is Status.FAIL and row.reason == "english-speech"
    assert [item.detail for item in row.checks] == ["FileNotFoundError"]


def test_speech_wav_is_16k_mono_pcm_and_its_text_a_secret(tmp_path) -> None:
    import numpy

    class Engine:
        def synthesize_pcm(self, text, language):
            return (numpy.ones(22_050, dtype="<i2") * 1000, 22_050)

    ctx = make_ctx(tmp_path)
    path = speech_pair.speech_wav(ctx, speech_pair.ZH, Engine())
    with wave.open(str(path), "rb") as handle:
        params = (handle.getnchannels(), handle.getsampwidth(), handle.getframerate())
        frames = handle.getnframes()
    assert params == (1, 2, 16_000) and frames >= 16_000 * 2.5  # lead + 1 s + tail
    assert ZH in ctx.secrets and path.parent == ctx.temp / "speech"


def test_e39_is_blocked_when_the_catalog_lacks_an_english_pack(monkeypatch, tmp_path) -> None:
    from lianiq.packs.errors import UnknownPackError

    ctx, _app = e39_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(
        packs_import, "pack", lambda pack_id: (_ for _ in ()).throw(UnknownPackError(pack_id))
    )
    assert e39.packs_missing(ctx) == len(e39.ENGLISH_PACKS)
    assert e39.run(ctx).status is Status.BLOCKED


def test_e40_resets_the_settings_and_deletes_the_wavs_when_the_flow_raises(
    monkeypatch, tmp_path
) -> None:
    ctx, app, made = e40_setup(monkeypatch, tmp_path)
    resets = []
    monkeypatch.setattr(uia_app, "settings_reset", lambda ctx: resets.append(ctx))
    monkeypatch.setattr(e40, "_session", lambda *args: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(RuntimeError):
        e40.run(ctx)
    assert resets == [ctx] and app.closed and not any(path.exists() for path in made)


def test_speech_wavs_leaves_no_wav_when_a_synthesis_fails(monkeypatch, tmp_path) -> None:
    import numpy

    class Engine:
        def synthesize_pcm(self, text, language):
            if language != "en":
                raise OSError("no Mandarin voice")
            return (numpy.ones(16_000, dtype="<i2"), 16_000)

    ctx = make_ctx(tmp_path)
    monkeypatch.setattr(speech_pair, "synthesizer", Engine)
    with pytest.raises(OSError):
        speech_pair.speech_wavs(ctx)
    assert not (ctx.temp / "speech" / speech_pair.EN).exists()
