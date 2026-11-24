"""English Call Bridge role labels and readiness texts (CAP-0166 spec §2.2.2, §3.4).

Qt-free, so ``evaluate_readiness`` can name its reasons; ``lianiq/ui/strings_call_bridge.py``
re-exports them as its ``CB_ROLE_*`` and ``CB_R_*`` strings instead of copying them.
"""

from __future__ import annotations

from types import MappingProxyType

from lianiq.call_bridge.contracts import EndpointRole

# In the order of the path boxes: You → call, then Call → you.
ROLE_LABELS = MappingProxyType(
    {
        EndpointRole.LOCAL_MICROPHONE: "Your microphone",
        EndpointRole.CALL_MICROPHONE_RENDER: "Call microphone cable — playback side",
        EndpointRole.CALL_SPEAKER_CAPTURE: "Call speaker cable — recording side",
        EndpointRole.LOCAL_HEADPHONES: "Your headphones",
    }
)

R_SELECT = "{role}: select a device"
R_NOT_FOUND = "{role}: device not found"
R_NEEDS_CAPTURE = "{role}: needs a recording device"
R_NEEDS_RENDER = "{role}: needs a playback device"
R_DUPLICATE = "{role_a} and {role_b} use the same device"
R_SAME_CABLE = (
    "Both call cables are the same virtual cable. "
    "Install a second cable and select it for one path."
)
R_AMBIGUOUS = "{role}: several devices have this name — unavailable"
R_MODE_UNAVAILABLE = "Not available: missing {item}"  # ``strings.MODE_UNAVAILABLE``, per item
R_MODELS_WARMING = "Preparing models…"
R_RUNNING = "The call bridge is running."
