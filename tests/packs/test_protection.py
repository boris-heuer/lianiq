"""CAP-0171 contract.md §8 (Integration half of AC-16): the packs the active session uses.

``ActiveUsageTracker`` holds the usage bound right after ``request_start``; ``packs_in_use``
maps its requirements through the built-in catalog. Update and remove of such a pack raise
``PackInUse(mode)``; install of an unused pack stays allowed.
"""

from __future__ import annotations

import pytest

from lianiq.languages import (
    BUILTIN_REGISTRY,
    CALL_BRIDGE_MODE,
    MEETING_MODE,
    InputKind,
    LanguageId,
    LanguagePair,
    OutputKind,
    RoutingKind,
    SessionPair,
    UsageMode,
)
from lianiq.packs.catalog import BUILTIN_CATALOG_PATH, PackCatalog
from lianiq.packs.errors import PackInUse
from lianiq.packs.protection import ActiveUsage, ActiveUsageTracker, in_use_guard, packs_in_use
from lianiq.ui.shell.session_owner import ActiveSessionOwner
from lianiq.ui.shell.workspaces import WorkspaceId, label

DE, ZH = LanguageId("de"), LanguageId("zh-Hans")
PAIR = LanguagePair(DE, ZH)
TEXT = UsageMode(InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.TEXT)
SPOKEN = UsageMode(InputKind.MICROPHONE, RoutingKind.BIDIRECTIONAL, OutputKind.SPOKEN)
STT = "stt-faster-whisper-small"
MT = {"mt-de-zh-hans", "mt-zh-hans-de"}
VOICE_DE, VOICE_ZH = "tts-de-thorsten-medium", "tts-zh-hans-aishell3"


@pytest.fixture(scope="module")
def packs() -> PackCatalog:
    return PackCatalog.load(BUILTIN_CATALOG_PATH, BUILTIN_REGISTRY)


def started(mode: WorkspaceId, usage: ActiveUsage | None):
    owner = ActiveSessionOwner()
    tracker = ActiveUsageTracker(owner)
    owner.request_start(mode)
    if usage is not None:
        tracker.bind(usage)
    return owner, tracker


def test_nothing_is_in_use_while_idle(packs) -> None:
    owner = ActiveSessionOwner()
    tracker = ActiveUsageTracker(owner)
    assert tracker.current is None
    assert packs_in_use(owner, tracker, packs) == frozenset()


def test_a_text_conversation_uses_recognition_and_translation(packs) -> None:
    usage = ActiveUsage(WorkspaceId.CONVERSATION, SessionPair(PAIR, TEXT), False)
    owner, tracker = started(WorkspaceId.CONVERSATION, usage)
    assert tracker.current == usage
    assert packs_in_use(owner, tracker, packs) == {STT, *MT}


def test_a_spoken_conversation_also_uses_both_voices(packs) -> None:
    usage = ActiveUsage(WorkspaceId.CONVERSATION, SessionPair(PAIR, SPOKEN), False)
    owner, tracker = started(WorkspaceId.CONVERSATION, usage)
    assert packs_in_use(owner, tracker, packs) == {STT, *MT, VOICE_DE, VOICE_ZH}


def test_a_meeting_uses_the_table_voice_and_the_local_voice_only_with_local_speech(
    packs,
) -> None:
    session = SessionPair(PAIR, MEETING_MODE, local_language=DE)
    owner, tracker = started(WorkspaceId.MEETING, ActiveUsage(WorkspaceId.MEETING, session, False))
    assert packs_in_use(owner, tracker, packs) == {STT, *MT, VOICE_ZH}

    tracker.set_local_speech(True)
    assert tracker.current is not None and tracker.current.local_speech
    assert packs_in_use(owner, tracker, packs) == {STT, *MT, VOICE_ZH, VOICE_DE}


def test_a_call_bridge_uses_every_model_of_its_session(packs) -> None:
    session = SessionPair(PAIR, CALL_BRIDGE_MODE, local_language=ZH)
    usage = ActiveUsage(WorkspaceId.CALL_BRIDGE, session, False)
    owner, tracker = started(WorkspaceId.CALL_BRIDGE, usage)
    assert packs_in_use(owner, tracker, packs) == {STT, *MT, VOICE_DE, VOICE_ZH}


def test_a_running_session_without_a_bound_usage_protects_every_installed_pack(packs) -> None:
    owner, tracker = started(WorkspaceId.CONVERSATION, None)
    assert packs_in_use(owner, tracker, packs, {STT, VOICE_DE, "unknown"}) == {STT, VOICE_DE}
    assert packs_in_use(owner, tracker, packs, ()) == frozenset()
    # Without the installed ids every catalog pack counts as installed.
    assert packs_in_use(owner, tracker, packs) == {pack.id for pack in packs.packs()}


def test_an_unbound_session_still_allows_installing_a_pack_that_is_not_installed(packs) -> None:
    owner, tracker = started(WorkspaceId.CONVERSATION, None)
    guard = in_use_guard(owner, tracker, packs, lambda: {STT})
    guard(packs.get(VOICE_DE), "install")
    with pytest.raises(PackInUse):
        guard(packs.get(STT), "remove")


def test_the_tracker_clears_when_the_owner_becomes_idle(packs) -> None:
    usage = ActiveUsage(WorkspaceId.CONVERSATION, SessionPair(PAIR, TEXT), False)
    owner, tracker = started(WorkspaceId.CONVERSATION, usage)
    owner.mark_running(owner.generation)
    owner.stop()
    assert tracker.current is None
    assert packs_in_use(owner, tracker, packs) == frozenset()


def test_set_local_speech_without_a_usage_is_ignored() -> None:
    tracker = ActiveUsageTracker(ActiveSessionOwner())
    tracker.set_local_speech(True)
    assert tracker.current is None


def test_ac16_update_and_remove_of_a_used_pack_are_refused_until_stop(packs) -> None:
    usage = ActiveUsage(WorkspaceId.CONVERSATION, SessionPair(PAIR, TEXT), False)
    owner, tracker = started(WorkspaceId.CONVERSATION, usage)
    guard = in_use_guard(owner, tracker, packs)
    used, unused = packs.get("mt-de-zh-hans"), packs.get(VOICE_DE)

    for operation in ("update", "remove"):
        with pytest.raises(PackInUse) as caught:
            guard(used, operation)
        assert caught.value.mode == label(WorkspaceId.CONVERSATION)
    guard(unused, "install")  # an unused pack can be installed meanwhile
    guard(unused, "remove")
    with pytest.raises(PackInUse):  # "Download again" over a pack the session uses
        guard(used, "install")

    owner.stop()
    guard(used, "update")
    guard(used, "remove")


def test_ac16_an_unbound_session_names_the_owner_mode(packs) -> None:
    owner, tracker = started(WorkspaceId.MEETING, None)
    with pytest.raises(PackInUse) as caught:
        in_use_guard(owner, tracker, packs)(packs.get(STT), "remove")
    assert caught.value.mode == label(WorkspaceId.MEETING)


def test_c2_a_running_owner_without_a_mode_still_names_a_workspace(packs) -> None:
    owner, tracker = started(WorkspaceId.CONVERSATION, None)
    owner.active = None  # defensive: the owner always records its mode while not idle
    with pytest.raises(PackInUse) as caught:
        in_use_guard(owner, tracker, packs)(packs.get(STT), "update")
    labels = {label(workspace) for workspace in WorkspaceId}
    assert caught.value.mode in labels and "SessionState" not in caught.value.mode
