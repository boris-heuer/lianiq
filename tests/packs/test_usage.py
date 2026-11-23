"""Usage profiles and the readiness review (CAP-0171 contract.md §7; Unit halves of AC-05, AC-19).

The Text translation row is CAP-0172 contract.md §9 (Unit half of its AC-31).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from _pack_fixtures import (
    MANIFEST,
    MT_FILES,
    MT_ROOT,
    VOICE_FILES,
    capability_catalog,
    fixture_packs,
    install,
    write_files,
)

from lianiq.config import AppConfig
from lianiq.languages import BUILTIN_REGISTRY, CapabilityCatalog, ReadinessProbe
from lianiq.languages.requirements import DeviceReadiness, RequirementKind
from lianiq.packs.catalog import BUILTIN_CATALOG_PATH, PackCatalog
from lianiq.packs.manifest import Manifest
from lianiq.packs.usage import (
    USAGE_PROFILES,
    ReviewStatus,
    UsageAvailability,
    is_device_row,
    readiness_review,
)
from lianiq.ui.shell.workspaces import WorkspaceId

PAIR = BUILTIN_REGISTRY.pair("de", "zh-Hans")
PROFILES = {profile.id: profile for profile in USAGE_PROFILES}
LISTEN = "listen-and-translate"


@pytest.fixture
def builtin() -> PackCatalog:
    return PackCatalog.load(BUILTIN_CATALOG_PATH, BUILTIN_REGISTRY)


def _review(ids, catalog, packs, devices=None, config=None):
    usages = [PROFILES[usage] for usage in ids]
    devices = devices or DeviceReadiness()
    return readiness_review(usages, PAIR, config or AppConfig(), catalog, packs, devices, 7)


def _rows(review):
    return {row.pack_id or str(row.requirements[0]): row for row in review.rows}


def test_profile_table_matches_the_contract() -> None:
    table = [(p.id, p.label, p.workspace, p.availability, p.device_roles) for p in USAGE_PROFILES]
    assert table == [
        (
            "conversation",
            "Conversation",
            WorkspaceId.CONVERSATION,
            UsageAvailability.ENABLED,
            ("Microphone", "Speakers"),
        ),
        (
            "call-bridge",
            "Call Bridge",
            WorkspaceId.CALL_BRIDGE,
            UsageAvailability.EXPERIMENTAL,
            (
                "Local microphone endpoint",
                "Call microphone endpoint",
                "Call speaker endpoint",
                "Local headphones endpoint",
            ),
        ),
        (
            "meeting",
            "Meeting dual-mic",
            WorkspaceId.MEETING,
            UsageAvailability.ENABLED,
            ("Table microphone", "Table speaker", "Your microphone"),
        ),
        (
            "text-translation",
            "Text translation",
            WorkspaceId.TEXT_TRANSLATION,
            UsageAvailability.ENABLED,
            ("Speakers",),
        ),
        (
            "listen-and-translate",
            "Listen & translate",
            WorkspaceId.LISTEN,
            UsageAvailability.ENABLED,
            ("Microphone",),
        ),
    ]


def test_required_sets_follow_cap0169_rows() -> None:
    config = AppConfig()
    kinds = {
        usage: [str(item) for item in PROFILES[usage].required(PAIR, config)]
        for usage in ("conversation", "call-bridge", "meeting", "text-translation", LISTEN)
    }
    models = ["recognition de", "recognition zh-Hans", "translation de>zh-Hans"]
    models.append("translation zh-Hans>de")
    assert kinds["conversation"] == [*models, "microphone"]
    assert kinds["call-bridge"][:6] == [*models, "voice de", "voice zh-Hans"]
    assert kinds["meeting"][:5] == [*models, "voice zh-Hans"]  # local de: table speaks Mandarin
    assert kinds["text-translation"] == ["translation de>zh-Hans", "translation zh-Hans>de"]
    assert kinds[LISTEN] == [*models, "microphone"]  # both fixed directions (CAP-0170 C §8)
    both = [p.id for p in USAGE_PROFILES if p.both_directions]
    assert both == ["text-translation", "listen-and-translate"]


def test_both_directions_needs_fixed_routing() -> None:
    profile = replace(PROFILES["conversation"], both_directions=True)  # bidirectional session
    with pytest.raises(ValueError, match="fixed-routing"):
        profile.required(PAIR, AppConfig())


def test_ac31_text_translation_alone_needs_both_directed_packs(tmp_path: Path, builtin) -> None:
    catalog = CapabilityCatalog.from_config(AppConfig(), BUILTIN_REGISTRY, ReadinessProbe(tmp_path))
    review = _review(["text-translation"], catalog, builtin, DeviceReadiness(microphone=True))
    packs = [(row.pack_id, row.optional, row.needed_by) for row in review.rows if row.pack_id]
    assert packs == [
        ("mt-de-zh-hans", False, ("Text translation",)),
        ("mt-zh-hans-de", False, ("Text translation",)),
        ("tts-zh-hans-aishell3", True, ()),
        ("tts-de-thorsten-medium", True, ()),
    ]
    devices = [row for row in review.rows if is_device_row(row)]
    assert [(row.requirements[0].kind, row.optional) for row in devices] == [
        (RequirementKind.PLAYBACK, True)
    ]  # Speakers optional; no recognition pack, no microphone


def test_cap0170_ac25_listen_alone_needs_recognition_both_edges_and_a_microphone(
    tmp_path: Path, builtin
) -> None:
    catalog = CapabilityCatalog.from_config(AppConfig(), BUILTIN_REGISTRY, ReadinessProbe(tmp_path))
    review = _review([LISTEN], catalog, builtin, DeviceReadiness(microphone=True))
    packs = [(row.pack_id, row.optional, row.needed_by) for row in review.rows if row.pack_id]
    assert packs == [
        ("stt-faster-whisper-small", False, ("Listen & translate",)),
        ("mt-de-zh-hans", False, ("Listen & translate",)),
        ("mt-zh-hans-de", False, ("Listen & translate",)),
    ]  # no voice
    devices = [row for row in review.rows if is_device_row(row)]
    assert [(row.requirements[0].kind, row.optional) for row in devices] == [
        (RequirementKind.MICROPHONE, False)
    ]  # no Speakers


def test_ac05_review_lists_required_rows_and_optional_voices(tmp_path: Path, builtin) -> None:
    catalog = CapabilityCatalog.from_config(AppConfig(), BUILTIN_REGISTRY, ReadinessProbe(tmp_path))
    devices = DeviceReadiness(microphone=True)
    review = _review(["conversation", "text-translation"], catalog, builtin, devices)

    assert [row.pack_id for row in review.rows] == [
        "stt-faster-whisper-small",
        "mt-de-zh-hans",
        "mt-zh-hans-de",
        "tts-de-thorsten-medium",
        "tts-zh-hans-aishell3",
        None,
        None,
    ]
    recognition, *_, voice_zh, microphone, playback = review.rows
    assert [str(item) for item in recognition.requirements] == [
        "recognition de",
        "recognition zh-Hans",
    ]
    assert recognition.status is ReviewStatus.NOT_INSTALLED
    assert (recognition.optional, recognition.needed_by) == (False, ("Conversation",))
    assert (voice_zh.optional, voice_zh.needed_by) == (True, ())
    assert (microphone.status, playback.status) == (ReviewStatus.READY, "device_not_found")
    assert playback.optional and playback.requirements[0].kind is RequirementKind.PLAYBACK
    assert review.missing_bytes == sum(pack.download_bytes for pack in builtin.packs())
    assert review.free_bytes == 7


def test_review_merges_usages_and_keeps_optional_only_when_no_usage_requires_it(
    tmp_path: Path, builtin
) -> None:
    catalog = CapabilityCatalog.from_config(AppConfig(), BUILTIN_REGISTRY, ReadinessProbe(tmp_path))
    rows = _rows(_review(["meeting", "conversation"], catalog, builtin))

    assert rows["stt-faster-whisper-small"].needed_by == ("Conversation", "Meeting dual-mic")
    assert rows["tts-zh-hans-aishell3"].needed_by == ("Meeting dual-mic",)
    assert not rows["tts-zh-hans-aishell3"].optional
    assert rows["tts-de-thorsten-medium"].optional  # Conversation spoken, Meeting local speech
    assert rows["meeting_endpoints local_render"].optional
    assert rows["meeting_endpoints table_capture"].status is ReviewStatus.DEVICE_NOT_FOUND


def test_ac19_models_ready_without_voices(tmp_path: Path, builtin) -> None:
    for folder in ("faster-whisper-small", "opus-mt-de-zh", "opus-mt-zh-de"):
        write_files(tmp_path, f"models/{folder}", {"model.bin": b"x"})
    catalog = CapabilityCatalog.from_config(AppConfig(), BUILTIN_REGISTRY, ReadinessProbe(tmp_path))
    devices = DeviceReadiness(microphone=True, playback=True)
    review = _review(["conversation", "meeting"], catalog, builtin, devices)
    rows = _rows(review)

    required = [row for row in review.rows if "Conversation" in row.needed_by]
    assert all(row.status is ReviewStatus.READY for row in required)  # text-only Conversation
    voice_de = rows["tts-de-thorsten-medium"]
    assert voice_de.optional and voice_de.status is ReviewStatus.NOT_INSTALLED
    voice_zh = rows["tts-zh-hans-aishell3"]
    assert voice_zh.needed_by == ("Meeting dual-mic",)
    assert voice_zh.status is ReviewStatus.NOT_INSTALLED
    voices = [rows[pack_id] for pack_id in ("tts-de-thorsten-medium", "tts-zh-hans-aishell3")]
    assert review.missing_bytes == sum(builtin.get(row.pack_id).download_bytes for row in voices)


def test_review_reports_files_missing_and_invalid(tmp_path: Path) -> None:
    packs = fixture_packs(tmp_path / "catalog")
    name, data = next(iter(MT_FILES.items()))
    write_files(tmp_path, MT_ROOT, {name: data})  # a partial translation pack
    manifest = install(tmp_path, packs.get("tts-a"), VOICE_FILES)
    (tmp_path / "models/piper" / next(iter(VOICE_FILES))).write_bytes(b"altered!!!!")
    catalog = capability_catalog(tmp_path, packs, Manifest.read(tmp_path / MANIFEST))
    rows = _rows(_review(["conversation"], catalog, packs))

    assert rows["mt-a"].status is ReviewStatus.FILES_MISSING
    assert rows["tts-a"].status is ReviewStatus.INVALID
    assert rows["recognition de"].pack_id is None  # no catalog pack provides it
    assert manifest.pack("tts-a") is not None
