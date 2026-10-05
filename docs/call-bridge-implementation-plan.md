# Call Bridge Implementation Plan

## Status and scope

Planned. The objective is a test-driven Windows call bridge for WeChat and other applications that
can select standard Windows microphone and speaker endpoints.

The first milestone provides full-duplex capture with utterance-based translation. It does not
include streaming partial translations, speaker diarization, overlapping-speaker separation, a
custom virtual audio driver, or automatic configuration of WeChat.

## Acceptance criteria

1. A local German utterance captured from the selected physical microphone is translated and
   rendered as Mandarin only to the configured TX virtual cable.
2. A remote Mandarin utterance captured from the configured RX virtual cable is translated and
   rendered as German only to the selected physical headphones.
3. Both lanes can capture concurrently and preserve sequence order independently.
4. Consecutive utterances in either direction never cause an implicit direction change.
5. No physical microphone audio, system sound, remote source audio, or translated audio crosses
   into the wrong output endpoint.
6. Endpoint loss fails closed and never falls back silently to a Windows default device.
7. The packaged application completes both real-model lanes within the measured latency budget.
8. Existing single-microphone conversation mode and all existing tests continue to pass.

## Synthetic conversation scenarios

| ID | Timeline | Synthetic data | Expected output |
|---|---|---|---|
| CB-01 | Outbound only | Local A: `Guten Morgen.` | One Mandarin utterance on TX; no Bose playback |
| CB-02 | Inbound only | Remote B: `我们下午三点开会。` | One German utterance on Bose; no TX output |
| CB-03 | Consecutive outbound | A: `Ich habe zwei Fragen.` then A: `Die erste betrifft den Preis.` | Two ordered Mandarin outputs |
| CB-04 | Consecutive inbound | B: `好的。`, B: `请继续。`, C: `我同意。` | Three ordered German outputs |
| CB-05 | Full duplex | Local and remote PCM begin within 100 ms | Both lanes finish independently without cross-routing |
| CB-06 | Short acknowledgements | Local: `Ja.`; remote: `嗯。` | Both short turns survive VAD and route correctly |
| CB-07 | Sample-rate mismatch | 48 kHz stereo cable input and 16 kHz mono fixture | Deterministic mono resampling without clipping |
| CB-08 | Queue pressure | Four utterances arrive faster than inference | Stale work is dropped and reported; current turn proceeds |
| CB-09 | Endpoint loss | RX endpoint disappears during capture | RX becomes degraded and muted; TX remains safe |
| CB-10 | Reconnect | Same stable RX endpoint returns with a new runtime index | Endpoint is rebound by stable identity |
| CB-11 | Routing isolation | Synthetic Windows notification on a non-selected device | No call-microphone samples are produced |
| CB-12 | Model failure | TTS raises after successful translation | Target output remains silent and error is surfaced |
| CB-13 | Stop under load | Stop while both lanes have active work | Workers terminate within the shutdown contract |
| CB-14 | Existing mode | Run current one-microphone scenario suite | No regression |

PCM fixtures should use deterministic tones, silence, impulses, and locally synthesized speech.
Unit and component tests must not require WeChat, audio hardware, or an installed virtual driver.

## TDD delivery order

### Phase 1: Pure contracts and lane behavior

Write failing tests before production code for:

- endpoint roles and incompatible-assignment validation;
- fixed translation direction per lane;
- independent sequence ordering;
- bounded queue age and drop events;
- fail-closed output behavior; and
- full-duplex controller lifecycle.

Implement only pure Python contracts and fake capture/playback ports. No sound device is opened in
this phase.

Target files:

```text
offline_translator/call_bridge/contracts.py
offline_translator/call_bridge/translation_lane.py
offline_translator/call_bridge/controller.py
tests/call_bridge/test_translation_lane.py
tests/call_bridge/test_full_duplex_controller.py
tests/call_bridge/test_call_bridge_scenarios.py
```

Exit gate: all synthetic routing, ordering, overload, and failure-policy tests pass.

### Phase 2: Audio buffers and format conversion

Write failing tests for ring-buffer boundaries, timestamps, stereo downmix, sample-rate conversion,
clipping, partial frames, underruns, and overruns. Reuse existing segmentation and WAV helpers where
possible.

Target files:

```text
offline_translator/audio/ring_buffer.py
offline_translator/audio/resampler.py
tests/audio/test_ring_buffer.py
tests/audio/test_resampler.py
```

Exit gate: deterministic 48-kHz stereo fixtures produce the expected 16-kHz mono samples, and
audio callbacks perform no model work.

### Phase 3: Stable Windows endpoint adapters

Replace persisted numeric device indices with stable endpoint references while retaining backward
compatibility for existing configuration. Add endpoint capability inspection and explicit WASAPI
shared-mode capture/playback adapters.

Write tests against a fake device inventory for reboot reorder, duplicate display names,
unavailable endpoints, and reconnect with a changed runtime index.

Target files:

```text
offline_translator/audio/endpoints.py
offline_translator/audio/capture_stream.py
offline_translator/audio/playback_stream.py
tests/audio/test_endpoints.py
tests/call_bridge/test_endpoint_recovery.py
```

Exit gate: every configured endpoint resolves by stable identity or produces an actionable error;
there is no silent default-device fallback.

### Phase 4: Model scheduling and full-duplex integration

Connect two `TranslationLane` instances to the existing STT, translation, and TTS ports. Add a
bounded inference scheduler so concurrent lanes cannot saturate the machine or starve audio
callbacks.

Write integration tests with fake models that block, fail, or complete out of order. Then run real
local models with synthetic German and Mandarin WAV fixtures.

Target files:

```text
offline_translator/call_bridge/inference_scheduler.py
offline_translator/call_bridge/health.py
scripts/call_bridge_self_test.py
```

Exit gate: both real-model directions complete, lane output remains isolated, and queue/latency
metrics are logged without transcript or PCM content.

### Phase 5: Configuration and UI

Add a disabled-by-default call-bridge mode with four explicit endpoint selectors:

1. local microphone;
2. call microphone output;
3. call speaker input; and
4. local headphones.

Show semantic role, Windows endpoint name, level, connection state, and a route-test control.
Prevent start when assignments are missing or conflicting. Preserve the current conversation UI.

Target files:

```text
offline_translator/ui/call_bridge_panel.py
offline_translator/config.py
config/settings.json
tests/test_config.py
tests/ui/test_call_bridge_panel.py
```

Exit gate: configuration round-trips stable endpoint identifiers, invalid mappings cannot start,
and UI tests do not modify the checked-in configuration.

### Phase 6: Packaged-device and WeChat acceptance

Extend packaging and diagnostics to verify the selected Windows audio backend and virtual endpoint
availability. Do not bundle a third-party virtual audio driver until its redistribution terms have
been reviewed and approved.

Run:

1. packaged synthetic dual-lane self-test;
2. virtual-cable loop test without WeChat;
3. local WeChat echo/test call if available;
4. real two-party German/Mandarin call; and
5. Bluetooth disconnect/reconnect and application restart tests.

Exit gate: the packaged executable passes the operator checklist in
`docs/call-bridge-operator-setup.md`, existing application tests remain green, and the build can be
removed without changing Windows default audio devices.

## Configuration migration

The current `audio.input_device` and `audio.output_device` settings remain valid for conversation
mode. Add a separate call-bridge section so incomplete setup cannot alter existing behavior:

```json
{
  "call_bridge": {
    "enabled": false,
    "local_microphone_endpoint_id": null,
    "call_microphone_render_endpoint_id": null,
    "call_speaker_capture_endpoint_id": null,
    "local_headphones_endpoint_id": null,
    "failure_policy": "mute",
    "max_pending_age_ms": 4000
  }
}
```

The implementation may read legacy numeric indices, but every successful save must migrate the
selected endpoints to stable identifiers.

## Observability

Record per lane:

- captured utterance duration;
- queue age and dropped-turn count;
- STT, translation, TTS, and playback durations;
- endpoint connect, disconnect, and reconnect events; and
- state transitions and sanitized failure categories.

Do not log transcripts, raw PCM, model prompts, or synthesized output. Add a diagnostic export that
contains configuration roles and endpoint capabilities but redacts user-specific identifiers where
possible.

## Definition of done

- All new tests and all existing tests pass.
- Ruff and dependency checks pass.
- Real-model self-tests pass in both directions.
- The packaged executable passes the two-cable loop test.
- A real WeChat call passes the operator acceptance checklist.
- Endpoint removal fails closed with no audio leakage.
- Documentation and configuration examples match the shipped UI.
- Third-party driver licensing is documented; no unapproved driver is redistributed.
- The implementation commit and CI status are available remotely.

## Deferred work

- streaming partial STT and translation;
- chunked/cancellable TTS;
- process-specific WASAPI loopback;
- acoustic echo cancellation;
- speaker diarization and overlapping-speaker separation;
- automatic call-application configuration; and
- a first-party signed virtual audio driver.
