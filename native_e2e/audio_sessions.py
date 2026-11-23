"""Processes with a WASAPI render session (CAP-0170 E-14: no output stream opened).

Windows creates an audio session for a process on a render endpoint when the process opens
its first output stream there and keeps listing it (inactive once the stream closed) until
the process exits. So the render sessions read while the app still runs show whether it
opened any output stream since it started: E-14 starts its own app instance, which opens no
output before **Start listening**.

``render_pids`` walks every active render endpoint (``IMMDeviceEnumerator``) and its
``IAudioSessionManager2`` session list and returns each session's process ID. The interfaces
are declared here with ``comtypes`` (native lock, imported lazily: VM image only); methods
that are never called keep only their vtable slot.
"""

# ruff: noqa: RUF012 - comtypes reads the ``_methods_`` lists of the interface classes

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

E_RENDER = 0
DEVICE_STATE_ACTIVE = 1
CLSCTX_ALL = 23
CLSID_ENUMERATOR = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_CONTROL_SLOTS = (  # IAudioSessionControl, before the IAudioSessionControl2 methods
    "GetState",
    "GetDisplayName",
    "SetDisplayName",
    "GetIconPath",
    "SetIconPath",
    "GetGroupingParam",
    "SetGroupingParam",
    "RegisterAudioSessionNotification",
    "UnregisterAudioSessionNotification",
)


def _interfaces() -> SimpleNamespace:
    from ctypes import POINTER, c_int, c_uint, c_void_p
    from ctypes.wintypes import DWORD

    from comtypes import GUID, HRESULT, STDMETHOD, IUnknown

    def slots(*names: str) -> list[Any]:
        return [STDMETHOD(HRESULT, name, []) for name in names]

    class Control2(IUnknown):
        _iid_ = GUID("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}")
        _methods_ = [
            *slots(*_CONTROL_SLOTS, "GetSessionIdentifier", "GetSessionInstanceIdentifier"),
            STDMETHOD(HRESULT, "GetProcessId", [POINTER(DWORD)]),
        ]

    class Sessions(IUnknown):
        _iid_ = GUID("{E2F5BB11-0570-40CA-ACDD-3AA01277DEE8}")
        _methods_ = [
            STDMETHOD(HRESULT, "GetCount", [POINTER(c_int)]),
            STDMETHOD(HRESULT, "GetSession", [c_int, POINTER(POINTER(IUnknown))]),
        ]

    class Manager2(IUnknown):
        _iid_ = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
        _methods_ = [
            *slots("GetAudioSessionControl", "GetSimpleAudioVolume"),
            STDMETHOD(HRESULT, "GetSessionEnumerator", [POINTER(POINTER(Sessions))]),
        ]

    class Device(IUnknown):
        _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
        _methods_ = [
            STDMETHOD(
                HRESULT,
                "Activate",
                [POINTER(GUID), DWORD, c_void_p, POINTER(POINTER(IUnknown))],
            ),
        ]

    class Collection(IUnknown):
        _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
        _methods_ = [
            STDMETHOD(HRESULT, "GetCount", [POINTER(c_uint)]),
            STDMETHOD(HRESULT, "Item", [c_uint, POINTER(POINTER(Device))]),
        ]

    class Enumerator(IUnknown):
        _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        _methods_ = [
            STDMETHOD(HRESULT, "EnumAudioEndpoints", [c_int, DWORD, POINTER(POINTER(Collection))]),
        ]

    return SimpleNamespace(
        control=Control2,
        sessions=Sessions,
        manager=Manager2,
        device=Device,
        collection=Collection,
        enumerator=Enumerator,
        unknown=IUnknown,
        guid=GUID,
    )


def render_pids() -> set[int]:
    """The process IDs of every audio session on an active render endpoint."""
    from ctypes import POINTER, byref, c_int, c_uint
    from ctypes.wintypes import DWORD

    import comtypes

    com = _interfaces()
    enumerator = comtypes.CoCreateInstance(
        com.guid(CLSID_ENUMERATOR), com.enumerator, comtypes.CLSCTX_INPROC_SERVER
    )
    endpoints = POINTER(com.collection)()
    enumerator.EnumAudioEndpoints(E_RENDER, DEVICE_STATE_ACTIVE, byref(endpoints))
    count, pids = c_uint(), set()
    endpoints.GetCount(byref(count))
    for index in range(count.value):
        device = POINTER(com.device)()
        endpoints.Item(index, byref(device))
        activated = POINTER(com.unknown)()
        device.Activate(byref(com.manager._iid_), CLSCTX_ALL, None, byref(activated))
        sessions = POINTER(com.sessions)()
        activated.QueryInterface(com.manager).GetSessionEnumerator(byref(sessions))
        total = c_int()
        sessions.GetCount(byref(total))
        for position in range(total.value):
            control = POINTER(com.unknown)()
            sessions.GetSession(position, byref(control))
            pid = DWORD()
            control.QueryInterface(com.control).GetProcessId(byref(pid))
            pids.add(int(pid.value))
    return pids
