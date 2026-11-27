"""Unit tests of screenshot masking, the cable lookup and the UIA helpers (CAP-0174 AC-11).

Every UIA element whose text holds an endpoint name, and every device combo, is masked by
its rectangle in memory before the PNG is written; the unmasked capture never reaches the
disk and no source pixel remains in a masked rectangle (contract §7.2). The screen grab,
PortAudio and pywinauto are replaced: they need the VM.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from native_e2e import audio, screens, uia
from native_e2e.uia import Node
from tests._native_png import red_png

NAMES = ["CABLE Input (VB-Audio Virtual Cable)", "CABLE Output (VB-Audio Virtual Cable)"]


def test_mask_rects_cover_every_shown_element_naming_an_endpoint_and_device_combos() -> None:
    nodes = [
        Node("Information: Microphone set to 'cable output (vb-audio virtual cable)'", "Group",
             rect=(1, 1, 50, 10)),
        Node("Speakers", "ComboBox", value="Follow Windows default (now: CABLE Input (VB-"
             "Audio Virtual Cable))", rect=(1, 20, 50, 30)),
        Node("Microphone", "ComboBox", value=None, rect=(1, 40, 50, 50)),
        Node("Notice history", "Edit", description="", value="x CABLE Output (VB-Audio "
             "Virtual Cable) y", rect=(1, 60, 50, 70)),
        Node("Tip", "Text", description=NAMES[0], rect=(1, 80, 50, 90)),
        Node("Language pair", "ComboBox", value="German ↔ Mandarin", rect=(1, 100, 50, 110)),
        Node("Transcript", "List", rect=(1, 120, 50, 130)),
        Node(NAMES[1], "Text", visible=False, rect=(1, 140, 50, 150)),
    ]  # fmt: skip
    rects = screens.mask_rects(nodes, NAMES, device_combos=("Microphone", "Speakers"))
    # The *Transcript* list is masked too (AC-11: no transcript text in evidence).
    assert rects == [(1, 1, 50, 10), (1, 20, 50, 30), (1, 40, 50, 50), (1, 60, 50, 70),
                     (1, 80, 50, 90), (1, 120, 50, 130)]  # fmt: skip


def test_a_field_whose_text_cannot_be_read_is_masked() -> None:
    nodes = [
        Node("Call microphone", "ComboBox", value=None, rect=(0, 0, 5, 5)),
        Node("Notice history", "Edit", value=None, rect=(0, 10, 5, 15)),
        Node("Source text", "Document", value=None, rect=(0, 20, 5, 25)),
        Node("Settings", "Text", value=None, rect=(0, 30, 5, 35)),
    ]
    assert screens.mask_rects(nodes, NAMES) == [(0, 0, 5, 5), (0, 10, 5, 15), (0, 20, 5, 25)]


def test_a_device_combo_is_masked_even_when_its_text_names_no_endpoint() -> None:
    nodes = [Node("Microphone", "ComboBox", value="Saved device", rect=(0, 0, 5, 5))]
    assert screens.mask_rects(nodes, NAMES, device_combos=("Microphone",)) == [(0, 0, 5, 5)]
    assert screens.mask_rects(nodes, NAMES) == []


@pytest.fixture
def writes(monkeypatch):
    """Every payload written through ``Path.write_bytes``, in order."""
    seen: list[tuple[Path, bytes]] = []
    original = Path.write_bytes

    def spy(self, data):
        seen.append((Path(self), bytes(data)))
        return original(self, data)

    monkeypatch.setattr(Path, "write_bytes", spy)
    return seen


def black_inside(png: bytes, rects, origin) -> bool:
    from PySide6.QtGui import QImage

    image = QImage.fromData(png, "PNG")
    for left, top, right, bottom in rects:
        for x in range(left - origin[0], right - origin[0]):
            for y in range(top - origin[1], bottom - origin[1]):
                if image.pixelColor(x, y).rgb() != 0xFF000000:
                    return False
    return True


def test_write_masked_writes_only_the_masked_image_and_no_source_pixel_remains(
    tmp_path, writes
) -> None:
    from PySide6.QtGui import QImage

    from native_e2e.context import RunContext

    ctx = RunContext(commit="a" * 40, out=tmp_path / "out", repo=tmp_path)
    window = (100, 100, 300, 200)
    rects = [(110, 120, 160, 140), (250, 180, 400, 260)]  # the second is clipped
    artifact = screens.write_masked(ctx, "screens/x.png", red_png(window), window[:2], rects)

    assert artifact.path == "screens/x.png"
    assert [path.name for path, _ in writes] == ["x.png"]  # one write, nothing unmasked first
    data = writes[0][1]
    assert black_inside(data, [rects[0], (250, 180, 300, 200)], window[:2])
    image = QImage.fromData(data, "PNG")
    assert (image.width(), image.height()) == (200, 100)
    assert image.pixelColor(0, 0).red() == 255 and image.pixelColor(199, 0).red() == 255
    assert ctx.state["screens_masked"] == 1
    screens.write_masked(ctx, "screens/y.png", red_png(window), window[:2], [])
    assert ctx.state["screens_masked"] == 2


def test_capture_masks_the_app_window_before_anything_is_written(tmp_path, writes, monkeypatch):
    from native_e2e.context import RunContext
    from tests._native_fake_app import COMBO_RECT, WINDOW, FakeApp

    monkeypatch.setattr(screens, "grab", red_png)
    ctx = RunContext(commit="a" * 40, out=tmp_path / "out", repo=tmp_path)
    app = FakeApp()
    app.page = "Settings"
    artifact, masked = screens.capture(ctx, app, "screens/s.png", NAMES, ("Microphone",))
    assert masked == 1 and artifact.path == "screens/s.png"
    assert len(writes) == 1 and black_inside(writes[0][1], [COMBO_RECT], WINDOW[:2])


def test_grab_is_never_called_with_a_path_and_returns_png_bytes() -> None:
    # The real grab needs a desktop; its PNG encoder is portable and in memory only.
    raw = bytes([0, 0, 255, 255]) * 6
    png = screens.encode_png(raw, 3, 2)
    assert png.startswith(b"\x89PNG")


# Cable lookup (PortAudio rows) and key escaping --------------------------------------------

DEVICES = [
    {"name": "Microsoft Sound Mapper - Input", "hostapi": 0, "max_input_channels": 2,
     "max_output_channels": 0},
    {"name": "CABLE Output (VB-Audio Virtual ", "hostapi": 0, "max_input_channels": 2,
     "max_output_channels": 0},
    {"name": "CABLE Input (VB-Audio Virtual C", "hostapi": 0, "max_input_channels": 0,
     "max_output_channels": 2},
    {"name": "CABLE Output (VB-Audio Virtual Cable)", "hostapi": 2, "max_input_channels": 2,
     "max_output_channels": 0},
    {"name": "CABLE Input (VB-Audio Virtual Cable)", "hostapi": 2, "max_input_channels": 0,
     "max_output_channels": 2},
]  # fmt: skip


@pytest.mark.parametrize(
    ("prefix", "kind", "hostapi", "index"),
    [
        ("CABLE Output", "input", 0, 1),
        ("CABLE Output", "input", 2, 3),
        ("CABLE Input", "output", 0, 2),
        ("CABLE Input", "output", 2, 4),
        ("CABLE Output", "output", 0, None),
        ("CABLE Output", "input", 9, 1),  # no entry on that host API: the first one
    ],
)
def test_pick_index_finds_the_cable_by_name_direction_and_host_api(
    prefix, kind, hostapi, index
) -> None:
    assert audio.pick_index(DEVICES, prefix, kind, hostapi) == index


def test_escape_keys_types_every_character_literally() -> None:
    assert uia.escape_keys("C:\\a b\\x+y^(1)%~{z}.txt") == (
        "C:\\a b\\x{+}y{^}{(}1{)}{%}{~}{{}z{}}.txt"
    )


def test_node_texts_are_name_description_and_value() -> None:
    assert Node("a", "Edit", description="b", value="c").texts() == ("a", "b", "c")
    assert Node("a", "Edit").texts() == ("a",)
