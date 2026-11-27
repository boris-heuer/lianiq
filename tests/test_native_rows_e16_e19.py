"""Unit tests of the offline-provisioning rows E-16..E-19 with a faked window (CAP-0171).

The fake models the setup assistant, Language packs (rows, details, Import… menu, folder
picker, Download, Remove and its confirmation) and a Conversation session. The junction is
real; the scratch folder gets the fake's manifest. The image holds the pair's packs only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from native_e2e import audio, fixtures, models_swap, packs_import, screens, uia_app
from native_e2e.context import RunContext
from native_e2e.evidence.model import Check, Status
from native_e2e.rows import e16, e17, e18, e19, provisioning, s04, ui
from native_e2e.uia import Node
from tests import _native_real_tree as real
from tests._native_fake_app import make_ctx
from tests._native_png import red_png

CABLE = "CABLE Output (VB-Audio Virtual Cable)"
S = ui.strings()
CATALOG = provisioning.catalog_ids()


class ProvisioningApp:
    rect = (100, 100, 900, 700)

    def __init__(self, ctx: RunContext, **knobs) -> None:
        self.ctx, self.knobs = ctx, knobs
        self.page, self.step, self.assistant = "Conversation", 0, False
        self.details = self.menu = self.picker = self.confirm = self.licence = None
        self.states = {packs_import.pack(i).model: "Downloadable" for i in CATALOG}
        self.messages: dict[str, str] = {}
        self.running = self.warm = False
        self.texts = ["", ""]
        self.mic = "Default"

    def start(self, ctx, setup_assistant: bool = False):
        if setup_assistant:
            ctx.local_settings.unlink(missing_ok=True)
        self.assistant = not ctx.local_settings.exists() or self.knobs.get("assistant_again", False)
        self.step = 0
        return self

    def close(self) -> int:
        return 0

    # What UI Automation reads

    def nodes(self) -> list[Node]:
        top = ("Lianiq",)
        out = [
            Node(n, "CheckBox", selected=self.page == n, parents=(*top, S.NAV_REGION))
            for n in (S.NAV_CONVERSATION, S.NAV_LANGUAGE_PACKS, S.NAV_SETTINGS)
        ]
        if self.warm:
            out.append(Node(self.knobs.get("warm_text", "Loading models …"), "Text"))
            self.warm, self.running = False, True
        elif self.running:
            out.append(Node(S.SESSION_RUNNING.format(mode=S.NAV_CONVERSATION), "Text"))
        if self.page == S.NAV_LANGUAGE_PACKS:
            if all(state == "Downloadable" for state in self.states.values()):
                out.append(Node(S.PACK_EMPTY_HINT, "Text"))
            for model, state in self.states.items():
                row = f"{model}, {state}"
                out.append(Node(row, "Group", parents=top))
                labels = [S.PACK_GET] if state == "Downloadable" else [S.PACK_REMOVE]
                if model in self.messages:
                    out.append(Node(self.messages[model], "Text", parents=(*top, row)))
                    if "Download unavailable" in self.messages[model]:
                        labels += [S.PACK_IMPORT, S.PACK_RETRY]
                out += [Node(label, "Button", parents=(*top, row)) for label in labels]
        elif self.page == S.NAV_SETTINGS:
            out.append(Node(S.NOTICE_MICROPHONE, "ComboBox", value=self.mic))
        elif self.page == S.NAV_CONVERSATION:
            out += real.transcript_list((), *self.texts)
        return out

    def window_nodes(self, title: str) -> list[Node] | None:
        if title == S.ASSIST_TITLE and self.assistant:
            titles = (
                S.ASSIST_USAGE_TITLE,
                S.ASSIST_LANG_TITLE,
                S.ASSIST_AUDIO_TITLE,
                S.ASSIST_REVIEW_TITLE,
            )
            return [
                Node(titles[self.step], "Text"),
                Node(f"Microphone: {CABLE}", "Text", rect=(200, 200, 400, 220)),
                Node(S.ASSIST_NEXT, "Button"),
                Node(S.ASSIST_SKIP, "Button"),
            ]
        if title == self.details:
            definition = next(
                packs_import.pack(i) for i in CATALOG if packs_import.pack(i).model == title
            )
            box = S.PACK_ACCEPT_LICENCE.format(licence=definition.licence)
            return [
                Node(box, "CheckBox", selected=self.licence),
                Node(S.PACK_IMPORT, "Button"),
                Node(S.PACK_DOWNLOAD, "Button"),
            ]
        if title == S.PACK_IMPORT_FOLDER and self.picker:
            return [
                Node("", "Edit", automation_id="1001"),
                Node("Select Folder", "Button", automation_id="1"),
            ]
        if title == S.PACK_REMOVE and self.confirm:
            return [Node("Yes", "Button")]
        return None

    def popup_nodes(self) -> list[Node]:
        return [Node(S.PACK_IMPORT_FOLDER, "MenuItem")] if self.menu else []

    # Actions

    def press(self, node: Node) -> None:
        if node.parents[-1:] == (S.NAV_REGION,):
            self.page = node.name
        elif node.name in (S.PACK_GET, S.PACK_REMOVE):
            model = node.parents[-1].rpartition(", ")[0]
            if node.name == S.PACK_GET:
                self.details, self.licence = model, False
            else:
                self.confirm = model
        elif node.name.startswith("I accept the licence"):
            self.licence = True
        elif node.name == S.PACK_IMPORT:
            self.menu = True
        elif node.name == S.PACK_DOWNLOAD:
            self.messages[self.details] = S.PACK_DOWNLOAD_UNAVAILABLE.format(host="huggingface.co")
            self.details = None
        elif node.automation_id == "1":
            self._imported(Path(self.typed))

    def click(self, node: Node) -> None:
        if node.name == S.ASSIST_NEXT:
            self.step += 1
        elif node.name == S.ASSIST_SKIP:
            self.assistant = False
            self.ctx.local_settings.write_text(
                json.dumps({"provisioning": {"first_run": "skipped"}}), "utf-8"
            )
        elif node.name == S.PACK_IMPORT_FOLDER:
            self.menu, self.picker = False, True
        elif node.name == "Yes":
            model, self.confirm = self.confirm, None
            if self.running:
                self.messages[model] = S.PACK_IN_USE.format(mode=S.NAV_CONVERSATION)
            else:
                self.states[model] = "Downloadable"

    def type_into(self, node: Node, text: str, enter: bool = True) -> None:
        self.typed = text

    def choose(self, node: Node, item: str) -> None:
        self.mic = item

    def keys(self, text: str) -> None:
        if text == "{F8}" and self.page == S.NAV_CONVERSATION:
            self.warm = True
        elif text == "{F9}":
            self.running = False

    def hear(self) -> None:
        if self.running:
            self.texts = ["German: Guten Morgen, das ist ein Test.", "Mandarin: 早上好"]

    def _imported(self, folder: Path) -> None:
        model, self.picker, self.details = self.details, False, None
        if "corrupt" in folder.parts:
            reason = f"file {self.knobs.get('altered', 'model.bin')} failed the integrity check"
            self.messages[model] = S.PACK_IMPORT_REJECTED.format(reason=reason)
            return
        self.messages.pop(model, None)
        self.states[model] = "Validated"
        manifest = self.ctx.repo / "models" / e18.MANIFEST
        data = json.loads(manifest.read_text("utf-8")) if manifest.exists() else {"packs": []}
        pack_id = next(i for i in CATALOG if packs_import.pack(i).model == model)
        data["packs"] = [r for r in data["packs"] if r["id"] != pack_id] + [
            {"id": pack_id, "source": "import"}
        ]
        manifest.write_text(json.dumps(data), "utf-8")


@pytest.fixture
def ctx(tmp_path, monkeypatch) -> RunContext:
    context = make_ctx(tmp_path)
    models = models_swap.image_models(context)
    models.mkdir(parents=True)
    context.state["settings_backup"] = {"existed": False}
    models_swap.repoint(context.repo / "models", models)
    monkeypatch.setattr(screens, "grab", red_png)
    monkeypatch.setattr(audio, "endpoint_names", lambda: [CABLE])
    monkeypatch.setattr(audio, "wasapi_name", lambda prefix, kind: CABLE)
    monkeypatch.setattr(s04, "count_since", lambda ctx, since: 0)
    monkeypatch.setattr(uia_app, "close_open", lambda ctx: None)
    monkeypatch.setattr(ui, "TIMEOUT_S", 0.3)
    monkeypatch.setattr(ui, "MODEL_TIMEOUT_S", 0.3)
    monkeypatch.setattr(ui, "POLL_S", 0.01)
    monkeypatch.setattr(e16, "NO_ASSISTANT_S", 0.1)
    return context


def fake(monkeypatch, ctx, **knobs) -> ProvisioningApp:
    app = ProvisioningApp(ctx, **knobs)
    monkeypatch.setattr(uia_app, "launch", app.start)
    monkeypatch.setattr(e16, "relaunch", lambda ctx: app.start(ctx))
    monkeypatch.setattr(audio, "play_into_cable", lambda path: app.hear())
    return app


def image_packs(ctx: RunContext, pack_file: bool = True) -> None:
    for pack_id in provisioning.pair_ids():
        folder = packs_import.image_pack_dir(ctx, pack_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "model.bin").write_bytes(b"\x00" * 64)
        if pack_file:
            (folder / "lianiq-pack.json").write_text("{}", "utf-8")


def junction_restored(ctx: RunContext) -> bool:
    return models_swap.points_to(ctx.repo / "models", models_swap.image_models(ctx))


def test_e16_walks_the_four_steps_skips_and_relaunches_without_the_assistant(
    monkeypatch, ctx
) -> None:
    fake(monkeypatch, ctx)
    row = e16.run(ctx)
    assert row.status is Status.PASS, row.checks
    assert [a.path for a in row.artifacts][:4] == [
        f"screens/e16-step{i}-{s}.png"
        for i, s in enumerate(("usage", "languages", "audio", "readiness"), 1)
    ]
    assert junction_restored(ctx) and not ctx.local_settings.exists()  # baseline: no file


def test_e16_fails_when_the_assistant_opens_again(monkeypatch, ctx) -> None:
    fake(monkeypatch, ctx, assistant_again=True)
    row = e16.run(ctx)
    failed = {c.name for c in row.checks if c.result is Status.FAIL}
    assert row.status is Status.FAIL and "relaunch-without-assistant" in failed


def test_e17_shows_download_unavailable_and_keeps_the_count_before_the_click(
    monkeypatch, ctx
) -> None:
    fake(monkeypatch, ctx)
    ctx.state["s04"] = {"checks": [Check("block-rule-added", Status.PASS)]}
    row = e17.run(ctx)
    assert row.status is Status.PASS, row.checks
    assert f"count={len(CATALOG)}" in {c.detail for c in row.checks}
    assert junction_restored(ctx)


def test_e18_and_e19_are_blocked_without_pack_files(monkeypatch, ctx) -> None:
    app = fake(monkeypatch, ctx)
    image_packs(ctx, pack_file=False)
    row = e18.run(ctx)
    assert (row.status, row.reason) == (Status.BLOCKED, "image-packs-without-pack-file")
    assert e19.run(ctx).reason == "image-packs-without-pack-file"
    assert app.page == "Conversation"  # no UI step was taken


def test_e18_imports_protects_and_reimports_then_e19_translates_offline(monkeypatch, ctx) -> None:
    app = fake(monkeypatch, ctx)
    image_packs(ctx)
    monkeypatch.setattr(fixtures, "checked", lambda name: Path(name))
    row = e18.run(ctx)
    assert row.status is Status.PASS, row.checks
    second = e19.run(ctx)
    assert second.status is Status.PASS, second.checks
    others = set(CATALOG) - set(provisioning.pair_ids())  # english-mandarin-pair
    assert others and all(app.states[packs_import.pack(i).model] == "Downloadable" for i in others)
    assert "Guten Morgen, das ist ein Test." in ctx.secrets
    assert junction_restored(ctx)


def test_e19_fails_on_a_warm_up_percentage(monkeypatch, ctx) -> None:
    fake(monkeypatch, ctx, warm_text="Loading models … 40 %")
    image_packs(ctx)
    monkeypatch.setattr(fixtures, "checked", lambda name: Path(name))
    e18.run(ctx)
    failed = {c.name for c in e19.run(ctx).checks if c.result is Status.FAIL}
    assert failed == {"warm-up-without-percentage"}
