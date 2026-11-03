# Conversation Architecture

## Decision

The application is a local modular monolith with explicit ports for speech recognition,
translation, speech synthesis, playback, and turn routing. It does not assume that speakers
alternate or that the translation direction flips after every utterance.

Every completed utterance is classified and routed independently:

```text
captured utterance (bound to the session pair and mode at submit)
  -> speech recognition + detected language and probability
  -> turn router (automatic within the pair, or a fixed source language)
       -> held turn when the language is unclear (see below)
  -> translation along the directed edge source>target
  -> speech synthesis (only when the session's output is spoken)
  -> ordered playback
```

## Languages, pairs and usage modes

Languages are identified by BCP 47 language IDs. The registry in
`lianiq/languages/registry.py` is the only place that names languages: German (`de`) and Mandarin
(Simplified) (`zh-Hans`) are qualified; English, Spanish and French are planned and cannot be
selected. Each entry maps its ID to engine codes, such as the Whisper code `zh` for `zh-Hans`. Code
outside the registry and the settings migration refers to languages only by ID;
`tests/test_no_hardcoded_languages.py` enforces this in the default `pytest` run.

Capabilities are directed and checked one by one (`lianiq/languages/capabilities.py`): speech
recognition per language, translation per directed edge (`de>zh-Hans` and `zh-Hans>de` are two
separate models; a reverse edge is never derived), and a voice per language. Each capability has a
readiness status: `not_configured`, `missing`, `installed`, `validated` (files match
`models/model-manifest.json`) or `invalid`. `scripts/doctor.py` prints this status per capability
of the configured pair.

A session binds a language pair and a usage mode (input, routing and output) at **Start**
(`SessionPair`). The requirement table in `lianiq/languages/requirements.py` lists what each mode
needs. For example, automatic microphone routing with text output needs recognition for both
languages and both edges, while a fixed direction needs only its source recognition and one edge.
**Start** is refused, naming each missing item, when a requirement is unmet, and only the required
models are constructed and warmed. Voices are required only for spoken output.

While a session runs, the pair, routing and output are locked (`SessionController`). **Stop**
stops capture, finishes queued turns with the pair they were captured under, clears the
translation context, and discards turns that are still held.

For the current single-microphone product, "simultaneous" means low-latency turn-based
interpretation while capture continues to segment later turns. It does not mean separating two
people who speak over each other. Reliable overlap handling requires multiple microphone channels
or a future source-separation and speaker-diarization model.

## Call bridge extension

The experimental call bridge extends the same modular monolith with two isolated audio lanes. Both
lanes are directed edges of the selected pair, and `call_bridge.local_language` (default `de`)
names the local language:

- an outbound lane `local>remote` (by default `de>zh-Hans`) from the local headset microphone to
  the call application's virtual microphone; and
- an inbound lane `remote>local` (by default `zh-Hans>de`) from the call application's virtual
  speaker to the local headset output.

Unlike single-microphone automatic mode, a call-bridge lane does not infer its translation
direction from the previous turn or from speaker identity. Its physical or virtual input endpoint
defines the source language, and the lane's edge is fixed for the whole session. The two lanes may
capture and process audio concurrently while preserving order independently within each lane.

See [`call-bridge-architecture.md`](call-bridge-architecture.md) for the design,
[`call-bridge-implementation-plan.md`](call-bridge-implementation-plan.md) for the TDD delivery
plan, and [`call-bridge-operator-setup.md`](call-bridge-operator-setup.md) for the experimental Windows
device mapping.

## Conversation scenarios

The executable synthetic cases live in `tests/test_conversation_routing.py`.

Turns are written as `language ID` of the spoken turn; routes as directed edges.

| Scenario | Synthetic turns | Required behavior |
|---|---|---|
| Two participants alternate | A: `de`, B: `zh-Hans`, A: `de` | Route `de>zh-Hans`, `zh-Hans>de`, `de>zh-Hans` |
| One person continues in German | A: `de`, A: `de`, C: `de` | Route every turn `de>zh-Hans` |
| Several Mandarin turns | B: `zh-Hans`, B: `zh-Hans`, D: `zh-Hans` | Route every turn `zh-Hans>de` |
| Three-participant conversation | A: `de`, B: `zh-Hans`, C: `de`, B: `zh-Hans` | Route solely from each turn's language |
| Short acknowledgements | `Ja`, `Genau`, `嗯`, `对` | Preserve order and route independently |
| Language outside the pair | detector reports `en`, or a code the registry does not know | Hold the turn; never guess from the script |
| Low detection probability | `de` detected below `languages.detection_min_probability` (0.7) | Hold the turn; at exactly 0.7 it is routed |
| Fixed direction | routing fixed to `zh-Hans`, detector reports `en` | Recognize as `zh-Hans` and route `zh-Hans>de`; never hold |
| Silence or noise | empty transcript | Ignore it and produce no output |
| Backlog while processing | three completed utterances arrive quickly | Keep latency bounded and report dropped stale work |
| Playback echo | synthesized output reaches the microphone | Reset and gate the segmenter during playback |
| User stops during inference | Stop while translation or TTS is active | Finish queued turns with their bound pair, then release the worker |
| Overlapping speakers | `de` and `zh-Hans` overlap on one microphone | Mark as unsupported for V1; never claim speaker attribution |

## Held turns

In automatic routing, a turn is translated only when its detected language is a member of the
session pair with a probability of at least `languages.detection_min_probability`. Any other turn
becomes a `HeldTurn` with the reason `out_of_pair`, `unregistered` or `low_confidence`. Its audio is
kept in memory only. The held-turn bar in the main window shows the transcript and the detected
language and offers **Translate as** for each pair language and **Discard**. **Translate as**
recognizes the retained audio again with that language forced and translates it as the same turn;
**Discard** and **Stop** release the audio without a result. Later turns are not blocked by a held
turn, and the transcript export keeps capture order (`# lianiq transcript v2`).

## Components and ownership

```text
lianiq/
  audio/
    capture.py          # PortAudio input adapter and playback gate
    segmenter.py        # Pure utterance endpointing
    playback.py         # Output adapter
    wav.py              # Deterministic WAV test input adapter
  languages/
    registry.py         # Language IDs, registry, pairs
    capabilities.py     # Directed capabilities and readiness
    modes.py            # Usage modes and the session pair
    requirements.py     # Requirements per mode and the availability check
    session.py          # Session lock, stop and transcript export v2
  conversation/
    routing.py          # Stateless, pair-scoped per-turn routing and held turns
  stt/
    faster_whisper_engine.py
  translation/
    marian_engine.py
    context.py
  tts/
    piper_engine.py
  pipeline.py           # Ordered conversation coordinator through protocols
  ui/
    main_window.py
    held_turn_bar.py
tests/
  languages/            # Registry, capabilities, requirements, session (synthetic qaa/qab)
  test_conversation_routing.py
  test_pipeline.py
  test_no_hardcoded_languages.py
  test_segmenter.py
  test_wav.py
scripts/
  self_test.py          # Headless real-model acceptance test
  ui_self_test.py       # UI, microphone, model, TTS, and playback test
```

The application remains one process because all stages share a strict latency budget, models are
large, and no stage needs independent deployment or scaling. Splitting these stages into services
would add serialization, process coordination, and operational failure modes without improving
the offline desktop use case.

## Turn lifecycle

```text
LISTENING
  -> SEGMENT_READY(sequence)
  -> RECOGNIZING
  -> ROUTED(source, target) | HELD(reason) -> resolved (RECOGNIZING with forced language) or discarded
  -> TRANSLATING
  -> SYNTHESIZING
  -> PLAYING
  -> COMPLETED
```

The worker is single-consumer and output is ordered by capture sequence. New audio may be
segmented while a turn is processed, but the bounded queue drops stale pending work instead of
allowing latency to grow without limit. During playback, microphone segmentation is gated to
avoid interpreting the application's own voice.

Speaker identity is metadata, not a routing input. Two German speakers in succession still
produce two `de>zh-Hans` turns. A later diarization adapter may assign `speaker_id` values without
changing language routing or translation.

## TDD build order

1. **Conversation contracts:** Pure synthetic turns verify direction, ordering, repeated-language
   turns, fixed directions, and held turns. The synthetic languages `qaa` and `qab` prove that
   nothing depends on German or Mandarin.
2. **Audio primitives:** Generated NumPy frames and PCM16 WAV files verify segmentation,
   resampling, pause detection, maximum duration, and playback gating without hardware.
3. **STT and TTS ports:** Fake recognizers and synthesizers verify orchestration. Real local models
   are covered separately by `scripts/self_test.py` to keep unit tests deterministic.
4. **Capture and playback adapters:** Device probes and `scripts/ui_self_test.py` exercise the real
   microphone, speakers, Qt event loop, and worker shutdown.
5. **Translation adapter:** Synthetic translators first verify routing and context. MarianMT then
   closes the real-model acceptance test in both directions.
6. **Packaged application:** A diagnostic WAV is injected through the packaged UI pipeline, then
   a manual two-person acceptance conversation validates the real room acoustics.

This order is preferable to implementing model adapters first: the conversation policy and failure
semantics are proven with fast deterministic tests before slow native models are involved.

## Context and multiple participants

Conversation history is stored in capture order. Translation context is selected by source
language ID, not by an assumed alternating speaker, and it is cleared when the session stops. This supports several statements in the same
language without reversing direction. Speaker-specific context requires reliable diarization and
is therefore intentionally deferred.

## Failure isolation

- Python exceptions are caught at the pipeline boundary and shown in the status bar.
- Native faults are recorded in `logs/native-crash.log` with all Python thread stacks.
- Each pipeline stage logs completion and elapsed time without logging audio or transcript text.
- Automatic detection never terminates the pipeline, and never guesses, when Whisper reports a
  language outside the pair or with low probability; the turn is held for the user.
- A missing model fails closed: **Start** is refused and names the missing capability, and a
  translator never falls back to another edge.
- Stop waits for an active native inference call before releasing the worker.
- Qt uses software rendering on this Radeon-based target to avoid coupling inference stability to
  intermittent display-driver timeouts.

## Vendor independence

- Speech recognition, translation, and synthesis are accessed through Python protocols.
- All runtime model paths are local and configurable.
- Replacing Faster-Whisper, MarianMT, or Piper does not change capture, routing, or UI contracts.
- No cloud SDK, remote API, or provider-specific service boundary is present.
