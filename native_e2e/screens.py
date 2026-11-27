"""Masked screenshots of the app window for the UIA rows (CAP-0174 contract §7.2, AC-11).

``capture`` grabs the window rectangle into memory, finds the rectangles to mask from the
same UIA read and writes the PNG only after ``evidence.redaction.mask`` filled them: the
unmasked image is never written to disk. Masked is every shown element whose name, help text
or value contains an endpoint name or a transcript needle (device combos, the E-11 notice,
the notice history), every device combo by its accessible name, the *Transcript* list of Conversation and
Listen whatever it shows, and every combo, edit or document field
whose text cannot be read. Each written screenshot counts in ``ctx.state["screens_masked"]``,
the receipt's ``screens_masked``.

``grab`` uses pywin32 (``win32gui``/``win32ui``, imported lazily: VM image only) and encodes
the pixels with QImage in memory.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from native_e2e.evidence.redaction import mask

if TYPE_CHECKING:
    from native_e2e.context import RunContext
    from native_e2e.evidence.model import Artifact
    from native_e2e.uia import Node

Rect = tuple[int, int, int, int]  # left, top, right, bottom in screen pixels
_TEXT_FIELDS = ("ComboBox", "Edit", "Document")  # masked when their text cannot be read
# The *Transcript* list of Conversation and Listen (``TRANSCRIPT_LIST``,
# ui/transcript/view.py): its rows show transcript text, so it is always masked (AC-11).
TRANSCRIPT_FIELDS = ("Transcript",)


def mask_rects(
    nodes: Iterable[Node],
    names: Iterable[str],
    device_combos: Sequence[str] = (),
    fields: Sequence[str] = TRANSCRIPT_FIELDS,
) -> list[Rect]:
    """Rectangles of the shown elements that show or may show an endpoint name or a
    transcript: those whose text holds one of ``names``, the ``device_combos`` and the
    ``fields`` (any control but their heading label) and every unreadable text field."""
    needles = [name.casefold() for name in names if name]
    rects: list[Rect] = []
    for node in nodes:
        if not node.visible:
            continue
        combo = node.control_type == "ComboBox"
        unreadable = node.control_type in _TEXT_FIELDS and node.value is None
        panel = node.name in fields and node.control_type not in ("Text", "")
        text = " ".join(node.texts()).casefold()
        if (
            any(needle in text for needle in needles)
            or (combo and node.name in device_combos)
            or panel
            or unreadable
        ):
            rects.append(node.rect)
    return rects


def encode_png(raw: bytes, width: int, height: int) -> bytes:
    """32-bit BGRX pixels (top-down rows) as PNG bytes, in memory."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage

    image = QImage(raw, width, height, 4 * width, QImage.Format.Format_RGB32).copy()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValueError("screenshot could not be encoded")
    buffer.close()
    return bytes(data)


def grab(rect: Rect) -> bytes:
    """The screen pixels inside ``rect`` as PNG bytes (never written here)."""
    import win32con
    import win32gui
    import win32ui

    left, top, right, bottom = rect
    width, height = right - left, bottom - top
    desktop = win32gui.GetDesktopWindow()
    source = win32gui.GetWindowDC(desktop)
    source_dc = win32ui.CreateDCFromHandle(source)
    memory_dc = source_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    try:
        bitmap.CreateCompatibleBitmap(source_dc, width, height)
        memory_dc.SelectObject(bitmap)
        memory_dc.BitBlt((0, 0), (width, height), source_dc, (left, top), win32con.SRCCOPY)
        raw = bitmap.GetBitmapBits(True)
    finally:
        memory_dc.DeleteDC()
        source_dc.DeleteDC()
        win32gui.ReleaseDC(desktop, source)
        win32gui.DeleteObject(bitmap.GetHandle())
    return encode_png(raw, width, height)


def write_masked(
    ctx: RunContext, relative: str, png: bytes, origin: tuple[int, int], rects: Iterable[Rect]
) -> Artifact:
    """Mask ``rects`` (screen pixels; ``origin`` is the capture's top left), then write."""
    from PySide6.QtCore import QRect

    left, top = origin
    local = [QRect(x0 - left, y0 - top, x1 - x0, y1 - y0) for x0, y0, x1, y1 in rects]
    masked = mask(png, local)
    target = ctx.out / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(masked)
    ctx.state["screens_masked"] = int(ctx.state.get("screens_masked", 0)) + 1
    return ctx.artifact(relative)


def capture(
    ctx: RunContext,
    app: Any,
    relative: str,
    names: Iterable[str],
    device_combos: Sequence[str] = (),
    fields: Sequence[str] = TRANSCRIPT_FIELDS,
) -> tuple[Artifact, int]:
    """Screenshot ``app``'s window to ``relative``, masked; return it and the mask count.

    The tree is read before and after the grab and both sets of rectangles are masked, so an
    element that appears or moves while the pixels are copied is still covered. ``fields``
    are the always-masked panels (E-13: *Source text* and *Translation*).
    """
    names = list(names)
    before = mask_rects(app.nodes(), names, device_combos, fields)
    window = app.rect
    png = grab(window)
    rects = list(dict.fromkeys(before + mask_rects(app.nodes(), names, device_combos, fields)))
    artifact = write_masked(ctx, relative, png, window[:2], rects)
    return artifact, len(rects)
