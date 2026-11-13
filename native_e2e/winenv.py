"""Read-only Windows probes for S-01, S-05, T-02 and T-04 (CAP-0174 contract §5).

Windows only; ``winreg``, ``psutil`` and ``sounddevice`` are imported lazily so the module
imports anywhere. No probe returns an endpoint name: ``cable_present`` answers only whether
both VB-Cable endpoints exist.
"""

from __future__ import annotations

from native_e2e.context import CABLE_NAMES

_CURRENT_VERSION = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
_WINDOW_METRICS = r"Control Panel\Desktop\WindowMetrics"
_DEFAULT_DPI = 96


def windows_build() -> str:
    """``CurrentBuild.UBR`` of the running Windows, for example ``26100.4349``."""
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _CURRENT_VERSION) as key:
        build = winreg.QueryValueEx(key, "CurrentBuild")[0]
        ubr = winreg.QueryValueEx(key, "UBR")[0]
    return f"{build}.{ubr}"


def display_scale_percent() -> int:
    """Display scale of the signed-in user; 100 when Windows never stored a custom DPI."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WINDOW_METRICS) as key:
            dpi = int(winreg.QueryValueEx(key, "AppliedDPI")[0])
    except FileNotFoundError:
        dpi = _DEFAULT_DPI
    return round(dpi * 100 / _DEFAULT_DPI)


def process_running(name: str) -> bool:
    """Whether a process with this image name (case-insensitive) runs in the guest."""
    import psutil

    wanted = name.casefold()
    for process in psutil.process_iter(["name"]):
        if (process.info.get("name") or "").casefold() == wanted:
            return True
    return False


def cable_present() -> bool:
    """Whether PortAudio lists both VB-Cable endpoints (names are compared, never kept)."""
    import sounddevice

    names = [str(device["name"]) for device in sounddevice.query_devices()]
    return all(any(name.startswith(cable) for name in names) for cable in CABLE_NAMES)
