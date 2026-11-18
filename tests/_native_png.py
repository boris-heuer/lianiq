"""A solid red screen capture for the native screen and row tests (CAP-0174)."""

from __future__ import annotations


def red_png(rect) -> bytes:
    """A solid red screen capture of ``rect`` (left, top, right, bottom), PNG in memory."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage

    image = QImage(rect[2] - rect[0], rect[3] - rect[1], QImage.Format.Format_RGB32)
    image.fill(QColor(255, 0, 0))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)
