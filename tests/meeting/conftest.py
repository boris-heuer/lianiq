"""The ``meeting`` fixture: a ``MeetingController`` on synthetic adapters (CAP-0177 WI-03)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from lianiq.call_bridge.contracts import EndpointFlow
from lianiq.languages import MEETING_MODE, SessionPair
from lianiq.meeting import MeetingEndpoints, TableInputDuringOutput
from lianiq.meeting.controller import MeetingController, MeetingOptions, SharedEngines
from lianiq.ui.shell.session_owner import ActiveSessionOwner
from tests.languages.synthetic import SpyTranslator
from tests.meeting.support import (
    AUDIO,
    DE,
    DE_ZH,
    LOCAL_OUTPUT,
    TABLE_MIC,
    TABLE_SPEAKER,
    USER_MIC,
    Events,
    FakeClock,
    PcmSynthesizer,
    ScriptedRecognizer,
    SyntheticRenders,
    SyntheticStreams,
    WallClock,
    endpoint,
)

CAPTURE, RENDER = EndpointFlow.CAPTURE, EndpointFlow.RENDER


def meeting_endpoints(local: bool = True, headset: bool = False) -> MeetingEndpoints:
    return MeetingEndpoints(
        table_capture=endpoint("Microphone (Jabra Speak2 75)", CAPTURE, None, TABLE_MIC, 16_000),
        table_render=endpoint("Speakers (Jabra Speak2 75)", RENDER, None, TABLE_SPEAKER),
        user_capture=endpoint("Microphone (Laptop)", CAPTURE, None, USER_MIC, 16_000),
        local_render=endpoint("Headset", RENDER, None, LOCAL_OUTPUT) if local else None,
        local_render_is_headset=headset,
    )


@dataclass
class Meeting:
    controller: MeetingController
    recognizer: ScriptedRecognizer
    translator: SpyTranslator
    synthesizer: PcmSynthesizer
    renders: SyntheticRenders
    events: Events
    owner: ActiveSessionOwner
    clock: FakeClock
    streams: SyntheticStreams


@pytest.fixture
def meeting(monkeypatch):
    """``meeting(script, **options)`` builds an unstarted meeting; teardown stops it."""
    built: list[Meeting] = []

    def build(
        script,
        *,
        speak_local: bool = False,
        mode: TableInputDuringOutput = TableInputDuringOutput.MUTE,
        guard_tail_ms: int = 300,
        max_playback_defer_ms: int = 5_000,
        endpoints: MeetingEndpoints | None = None,
        owner: ActiveSessionOwner | None = None,
        step_ms: float = 400.0,
    ) -> Meeting:
        recognizer = ScriptedRecognizer(dict(script))
        synthesizer = PcmSynthesizer()
        renders = SyntheticRenders(synthesizer)
        monkeypatch.setattr("lianiq.audio.playback_stream.play_pcm", renders)
        harness = Meeting(
            controller=None,  # type: ignore[arg-type]
            recognizer=recognizer,
            translator=SpyTranslator(),
            synthesizer=synthesizer,
            renders=renders,
            events=Events(),
            owner=owner or ActiveSessionOwner(),
            clock=FakeClock(),
            streams=SyntheticStreams(),
        )
        harness.controller = MeetingController(
            SessionPair(DE_ZH, MEETING_MODE, local_language=DE),
            endpoints or meeting_endpoints(),
            MeetingOptions(speak_local, mode, guard_tail_ms, max_playback_defer_ms),
            SharedEngines(recognizer, harness.translator, synthesizer),
            harness.owner,
            harness.events,
            harness.clock,
            audio=AUDIO,
            stream_factory=harness.streams,
            wall_clock=WallClock(step_ms),
        )
        built.append(harness)
        return harness

    yield build
    for harness in built:
        if harness.renders.gate is not None:
            harness.renders.gate.set()
        harness.controller.stop(timeout=5.0)
