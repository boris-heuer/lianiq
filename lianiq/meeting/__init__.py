"""Meeting dual-mic translation core (CAP-0177, ``lianiq.meeting.dual-input.v1``).

Qt-free: no PySide6 import anywhere in this package. See
``docs/products/lianiq/capabilities/meeting-dual-mic-translation/contract.md`` §1-§4 in
``boris-heuer/app-shared``: roles and endpoints (``contracts``), the per-input language gate
(``language_gate``), the no-drop turn queue (``turn_queue``) and the cross-device feedback
guard (``feedback_guard``).
"""

from lianiq.meeting.contracts import (
    EndpointConflict,
    MeetingEndpoints,
    MeetingRole,
    TableInputDuringOutput,
    endpoint_conflicts,
    suggest_table_partner,
)
from lianiq.meeting.feedback_guard import FeedbackGuard, PlaybackDecision
from lianiq.meeting.language_gate import GateDecision, LanguageGate
from lianiq.meeting.turn_queue import TURN_QUEUE_SOFT_LIMIT, Contribution, TurnQueue

__all__ = [
    "TURN_QUEUE_SOFT_LIMIT",
    "Contribution",
    "EndpointConflict",
    "FeedbackGuard",
    "GateDecision",
    "LanguageGate",
    "MeetingEndpoints",
    "MeetingRole",
    "PlaybackDecision",
    "TableInputDuringOutput",
    "TurnQueue",
    "endpoint_conflicts",
    "suggest_table_partner",
]
