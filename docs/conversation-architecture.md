# Conversation Architecture

## Decision

The application is a local modular monolith with explicit ports for speech recognition,
translation, speech synthesis, playback, and turn routing. It does not assume that speakers
alternate or that the translation direction flips after every utterance.

Every completed utterance is classified and routed independently:

```text
captured utterance
  -> speech recognition + detected language
  -> turn router (automatic or manual override)
  -> translation into the other configured language
  -> speech synthesis
  -> ordered playback
```

For the current single-microphone product, "simultaneous" means low-latency turn-based
interpretation while capture continues to segment later turns. It does not mean separating two
people who speak over each other. Reliable overlap handling requires multiple microphone channels
or a future source-separation and speaker-diarization model.

## Conversation scenarios

The executable synthetic cases live in `tests/test_conversation_routing.py`.

| Scenario | Synthetic turns | Required behavior |
|---|---|---|
| Two participants alternate | A: DE, B: ZH, A: DE | Route DE→ZH, ZH→DE, DE→ZH |
| One person continues in German | A: DE, A: DE, C: DE | Route every turn DE→ZH |
| Several Mandarin turns | B: ZH, B: ZH, D: ZH | Route every turn ZH→DE |
| Three-participant conversation | A: DE, B: ZH, C: DE, B: ZH | Route solely from each turn's language |
| Short acknowledgements | `Ja`, `Genau`, `嗯`, `对` | Preserve order and route independently |
| Unsupported detector label | detector says EN, transcript is German or Han script | Infer DE or ZH without terminating the pipeline |
| Silence or noise | empty transcript | Ignore it and produce no output |
| Backlog while processing | three completed utterances arrive quickly | Keep latency bounded and report dropped stale work |
| Playback echo | synthesized output reaches the microphone | Reset and gate the segmenter during playback |
| User stops during inference | Stop while translation or TTS is active | Finish the active native call before worker shutdown |
| Overlapping speakers | DE and ZH overlap on one microphone | Mark as unsupported for V1; never claim speaker attribution |

## Components and ownership

```text
offline_translator/
  audio/
    capture.py          # PortAudio input adapter and playback gate
    segmenter.py        # Pure utterance endpointing
    playback.py         # Output adapter
    wav.py              # Deterministic WAV test input adapter
  conversation/
    routing.py          # Stateless per-turn language routing
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
tests/
  test_conversation_routing.py
  test_pipeline.py
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
  -> ROUTED(source, target)
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
produce two DE→ZH turns. A later diarization adapter may assign `speaker_id` values without
changing language routing or translation.

## TDD build order

1. **Conversation contracts:** Pure synthetic turns verify direction, ordering, repeated-language
   turns, manual overrides, and unsupported-language fallback.
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
language, not by an assumed alternating speaker. This supports several statements in the same
language without reversing direction. Speaker-specific context requires reliable diarization and
is therefore intentionally deferred.

## Failure isolation

- Python exceptions are caught at the pipeline boundary and shown in the status bar.
- Native faults are recorded in `logs/native-crash.log` with all Python thread stacks.
- Each pipeline stage logs completion and elapsed time without logging audio or transcript text.
- Automatic detection never terminates the pipeline merely because Whisper reports a language
  outside DE/ZH; the transcript script provides a deterministic fallback.
- Stop waits for an active native inference call before releasing the worker.
- Qt uses software rendering on this Radeon-based target to avoid coupling inference stability to
  intermittent display-driver timeouts.

## Vendor independence

- Speech recognition, translation, and synthesis are accessed through Python protocols.
- All runtime model paths are local and configurable.
- Replacing Faster-Whisper, MarianMT, or Piper does not change capture, routing, or UI contracts.
- No cloud SDK, remote API, or provider-specific service boundary is present.
