# Meeting Architecture

## Status

Implemented in the source build (CAP-0177 `meeting-dual-mic-translation`). Unit, integration
and offscreen UI tests cover the meeting core, the controller and the workspace. The native
journeys with the reference speakerphone still need operator evidence (see
[Native verification](#native-verification)); tests alone do not establish product
verification. Packaged-executable SystemOK is out of scope.

The canonical specification, module contract and e2e validation plan are in
[`app-shared/docs/products/lianiq/capabilities/meeting-dual-mic-translation/`](https://github.com/boris-heuer/app-shared/tree/main/docs/products/lianiq/capabilities/meeting-dual-mic-translation).
This document describes the shipped code and the operator setup; it does not restate the
acceptance criteria.

## Objective

A face-to-face meeting at a table with two concurrent inputs, fully offline:

- the customers speak the **table language** (by default Mandarin (Simplified)) into a USB
  speakerphone on the table;
- the user speaks the **local language** (`meeting.local_language`, by default German) into a
  separate microphone;
- the user reads the table's contributions as running local-language text, optionally also
  hears them as local-language speech on a headset or a speaker; and
- the table hears the user's contributions as table-language speech from the speakerphone.

The pair is the CAP-0169 session pair; the table language is always the other member of the
pair. The code is pair-neutral: no module under `lianiq/meeting/` names a language.

## Roles

Four fixed roles (`MeetingRole` in `lianiq/meeting/contracts.py`). Each resolves to one Windows
endpoint by identity (`AudioEndpointRef.endpoint_id`), never by PortAudio index or display name.

| Role | Endpoint | Carries | Selection |
|---|---|---|---|
| `table_capture` | Speakerphone microphone (*Table microphone*) | Table-language speech of the customers | Explicit only |
| `table_render` | Speakerphone speaker (*Table speaker*) | Table-language speech of the user's contributions | Explicit only |
| `user_capture` | User microphone (*Your microphone*) | Local-language speech of the user | Follows the Windows default, or explicit |
| `local_render` | Headset or laptop speaker (*Output for German speech*) | Local-language speech of the table's contributions | Explicit only; needed only while **Speak German for me** is on |

Choosing a table endpoint suggests the other-flow endpoint of the same device
(`suggest_table_partner`: the text in the last parentheses of the WASAPI name, normalised; a
suggestion only when exactly one endpoint matches). The suggestion fills an unassigned partner
only; the user can always override it.

Two conflicts compare the endpoint IDs of the **resolved** endpoints (`endpoint_conflicts`):

| Conflict | Effect |
|---|---|
| `user_is_table`: *Your microphone* resolves to the table microphone (explicitly or through the Windows default) | **Start meeting** is disabled; "Your microphone is the table microphone" is listed |
| `local_is_table`: the local-speech output is the table speaker | **Speak German for me** is disabled with "German speech cannot use the table speaker"; **Start meeting** stays available |

## Signal flow

```text
table_capture (speakerphone mic)                user_capture (your mic)
  -> MeetingCapture: segmenter, guard mute        -> MeetingCapture: segmenter, guard mute
  -> Contribution(role, ended_at)                 -> Contribution(role, ended_at)
          \                                          /
           -> TurnQueue (one, no drop, ordered by ended_at)
           -> one inference worker:
                detection pass -> LanguageGate -> (forced pass) -> STT text
                  table: MT table>local -> "Table" line -> [local speech on local_render]
                  user:  "You" line -> MT local>table -> table speech on table_render
                every playback: FeedbackGuard.before_playback / playback_started / _ended
```

## Module map

The meeting core is Qt-free (`lianiq/meeting/`; no PySide6 import). The workspace is split
into mixins to keep every file under the UI size limit.

| Module | Responsibility |
|---|---|
| `lianiq/meeting/contracts.py` | `MeetingRole`, `TableInputDuringOutput` (`mute` / `open`), `EndpointConflict`, `MeetingEndpoints`, `endpoint_conflicts`, `suggest_table_partner` |
| `lianiq/meeting/language_gate.py` | `LanguageGate.decide`: `ACCEPT`, `DISCARD` or `FORCE_EXPECTED` per input |
| `lianiq/meeting/turn_queue.py` | `Contribution`, `TurnQueue` (sorted by speech end, never drops), `TURN_QUEUE_SOFT_LIMIT` (6) |
| `lianiq/meeting/feedback_guard.py` | `FeedbackGuard`: which captures a playback target mutes, the guard tail, playback deferral |
| `lianiq/meeting/capture.py` | `MeetingCapture`: an `EndpointCaptureStream` with its own `UtteranceSegmenter` that obeys the guard; `flush` closes a running contribution |
| `lianiq/meeting/controller.py` | `MeetingController`: start, stop and drain, `set_speak_local`, endpoint loss, `results` |
| `lianiq/meeting/processing.py` | `ContributionProcessing`: the worker loop and one contribution's STT → gate → MT → TTS → playback |
| `lianiq/meeting/events.py` | `MeetingEventKind`, `MeetingEvent`, `MeetingLine`, `MeetingOptions`, `SharedEngines` |
| `lianiq/meeting/transcript.py` | `meeting_transcript_text` (transcript v2) and `write_meeting_transcript` (UTF-8, atomic replace) |
| `lianiq/ui/workspaces/meeting.py` | `MeetingWorkspace`: session pair, row 8 availability, the speech switch, option handlers |
| `lianiq/ui/workspaces/meeting_layout.py` | Widgets: pair row, device panel, options, **Start meeting** / **End meeting** |
| `lianiq/ui/workspaces/meeting_devices.py` | The four endpoint combos, resolution by identity, conflicts, partner suggestion, `DeviceReadiness` |
| `lianiq/ui/workspaces/meeting_lifecycle.py` | Start (models, controller factory), the asynchronous stopper, the `STOPPED` hand-off |
| `lianiq/ui/workspaces/meeting_running.py` | Status strip and running text view |
| `lianiq/ui/workspaces/meeting_notices.py` | Device-loss notices and the end-of-meeting save dialog |

Related changes outside these folders: `UsageMode.meeting`, `MEETING_MODE` and requirement
row 8 in `lianiq/languages/`; `MeetingConfig` in `lianiq/config.py` with validation in
`lianiq/config_meeting.py`; the strings in `lianiq/ui/strings_meeting.py`; `play_pcm` and
`on_playback_state` in `lianiq/audio/playback_stream.py`; in-memory `synthesize_pcm` in the
TTS engines; `build_meeting_controller` in `lianiq/app.py`.

## Start availability

**Start meeting** follows requirement row 8 (`MEETING_MODE`): speech recognition for both pair
languages, both translation edges, a voice for the table language, and the three roles
`table_capture`, `table_render` and `user_capture` assigned and free of conflict. Every missing
item is listed under the options. The local-language voice and `local_render` gate only the
speech switch (`meeting_local_speech_requirements`). No model is loaded before **Start
meeting**; Start loads only what row 8 needs.

## Language gate

Each input expects one pair language: the table input the table language, the user microphone
the local language. The detection pass decides, with `languages.detection_min_probability`
(default 0.7) as threshold:

| Detection | Decision | Result |
|---|---|---|
| Expected language, probability ≥ threshold | `ACCEPT` | The detection-pass text is used |
| The other pair language, probability ≥ threshold | `DISCARD` | Not translated; keeps no text anywhere; the input's ignored counter increments |
| Anything else (low probability, outside the pair, unknown) | `FORCE_EXPECTED` | A second pass forced to the expected language is used; empty text is dropped as silence, not counted |

In a real room both microphones hear both sides; the gate is what keeps the customer's speech
on the user microphone (and the reverse) from being translated twice.

## No-drop turn queue

Both captures put into one `TurnQueue`; the single worker takes. Contributions come out ordered
by speech end (`ended_at`, which becomes `TranslationResult.captured_at`); equal ends keep
their insertion order. Unlike the Call Bridge lane queues, there is no age expiry and no
capacity limit. Above the soft limit of 6 queued contributions the strip shows "Translation is
falling behind — nothing is lost" until the queue is back at or below the limit.

## Feedback guard

There is no acoustic echo cancellation in software. Lianiq instead mutes the captures that
would hear its own output, keyed by the playback target and `meeting.table_input_during_output`.
A capture is muted from playback start until playback end plus `meeting.guard_tail_ms`
(default 300 ms):

| Playback target | `mute` (default) | `open` |
|---|---|---|
| `table_render` (table-language speech) | Table and user microphone | User microphone only |
| `local_render`, not marked as headset | Table and user microphone | Table and user microphone |
| `local_render`, marked as headset | Nothing | Nothing |

- A muted capture discards every block and resets its segmenter: muted audio never becomes a
  contribution and is not buffered. The strip shows *Muted while speaking {language}* for each
  muted input.
- With `mute`, customer speech during table-language output is not captured. This is the
  accepted trade-off of the default; the strip makes it visible.
- With `open`, the table microphone stays live during table-language output and relies on the
  speakerphone's own echo cancellation. The language gate cannot help there, because the echo
  is in the table language on the table input. `open` is evidence-gated (e2e row E-09).
- Local-language speech on a speaker would pass the user microphone's gate and be translated
  again, so a speaker output mutes both inputs. Only an output marked *This output is a headset
  (no sound reaches the room)* mutes nothing. The mark is off by default (fail-safe: unknown
  counts as a speaker).

**Playback deferral.** Before a playback the worker asks `before_playback`. While a capture
that this target will mute is mid-contribution, the playback waits, at most
`meeting.max_playback_defer_ms` (default 5000 ms). Then that contribution is closed at that
point (`MeetingCapture.flush`; it is queued and processed, not dropped), the capture is muted
and the output plays. Captures the target does not mute are never waited for, so with `open`
table-language output never waits for the table microphone. Playbacks never overlap: one
worker serialises them.

## Controller lifecycle and the session owner

One session runs at a time across all modes (`ActiveSessionOwner`,
`lianiq.shell.active-session.v1`).

1. **Start meeting** asks `owner.request_start(MEETING)` before any model loads. While
   Conversation or Call Bridge holds the session, Start is refused with the busy notice and
   nothing opens; their starts are refused while the meeting holds it.
2. The models of row 8 are prepared in the background. Only then does the page build the
   `MeetingController` through the factory registered by `lianiq.app`
   (`MainWindow(meeting_factory=...)`). The controller sees the owner through
   `_ControllerOwner`, which hands back the page's reservation and keeps the page's stopper.
3. `MeetingController.start` opens the table capture, then the user capture, then the worker
   thread, and marks the session running. A capture that fails to open closes the ones already
   open and returns the session to idle.
4. **Speak German for me** can change while the meeting runs (`set_speak_local`). The device
   combos, the headset mark and the *Table microphone while Lianiq speaks …* option are locked
   (*Available when no meeting is running*); they apply at the next Start.
5. **End meeting**, **Stop (F9)** or closing the window call the page's asynchronous stopper.
   `controller.stop()` runs on a `meeting-stop` thread, never on the GUI thread: it stops both
   captures (a failing stop does not keep the other input open), lets the worker drain queued
   and in-flight contributions, then publishes `STOPPED`. The owner stays *stopping* until
   `STOPPED` reaches the GUI thread and the page calls `mark_idle`; until then every other
   start is refused, so no other mode opens audio while the meeting still holds its devices.
6. After `STOPPED` the page offers the save dialog only if at least one contribution was
   translated and the window is still shown.

The drain waits at most 120 s; after that the remaining contributions are withdrawn and their
count is logged. Events reach the GUI thread through queued signals (the `UiBridge` pattern).

## Device loss

While a meeting runs, the shell's 2 s identity monitor (`DeviceWatch.monitor_tick`) calls
`check_endpoints`. Each assigned endpoint whose identity has left the inventory is reported
once (`MeetingController.endpoint_lost`):

- a lost capture stops; its strip shows *Device lost*;
- a lost render is skipped: pending speech for it is not played, the text stays in the
  running view and the transcript;
- a persistent blocking notice names the device and its role, until the next Start;
- no other device is opened, and queued contributions still finish. Nothing restarts on its
  own; end the meeting and start it again after replugging.

## Known limits

- **A stream failure without identity loss is not detected as a device loss.** Loss is
  detected by endpoint identity only. If a capture stream reports an error or stops
  delivering audio while its endpoint is still listed, the meeting keeps running, that input
  simply forms no contributions, and no *Device lost* notice appears. A playback error is
  logged and that output is skipped for that contribution only.
- **A `capture.stop()` that never returns leaves the session owner *stopping*.** The stopping
  thread calls the capture stops before it drains. If the audio driver never returns from a
  stop, `STOPPED` is never published, the owner stays *stopping* and no other mode can start
  until Lianiq is restarted.
- **The drain is bounded.** Contributions still queued after the 120 s drain timeout are
  withdrawn, not translated. If a contribution is still being spoken when the timeout ends,
  `STOPPED` is published after a short join and the owner goes idle while that last output may
  still be playing; the withdrawn count is logged once the worker returns to its loop.
- **No software echo cancellation.** `open` is only as good as the speakerphone's built-in
  echo cancellation, and in `mute` customers cannot be heard while Lianiq speaks to them.

## Offline and privacy

- **Offline.** All engines are the pipeline's local adapters (Faster-Whisper, MarianMT per
  directed edge, the voice per language), loaded from local model packs. The meeting makes no
  network call.
- **No audio file is ever written.** Speech is synthesised in memory (`synthesize_pcm`) and
  played from memory (`play_pcm`); no temporary WAV is created. This includes the voice
  warm-up at **Start meeting**, which synthesises the native-name sample in memory. Captured audio lives in memory
  only and is released after speech recognition.
- **Transcript only on explicit Save.** The running view and the results live in memory. The
  end-of-meeting dialog says "Save a text transcript in both languages on this computer? Audio
  is never saved." Only **Save…** writes a transcript v2 text file (both languages per turn,
  ordered by speech end, default name `lianiq-meeting-<date>.txt`) to the path chosen in the
  file dialog, through an atomic replace. **Don't save** or closing the dialog writes nothing
  and forgets the results. A meeting with no translated contribution shows no dialog. A write
  error shows a notice with the redacted reason and **Retry**.
- **Discarded contributions keep no text** in memory, view, transcript or logs; only the
  ignored counter of their input changes.
- **Logs** carry roles, stage categories, counts and timings only, never recognised or
  translated text and never PCM.
- **Table-language text is never shown.** "Table" lines carry the local-language translation,
  "You" lines the user's recognised local-language text.

## Operator setup

### Table speakerphone (Jabra Speak2 75)

The reference speakerphone is the Jabra Speak2 75 on USB. Other speakerphones may work but are
not verified.

1. Connect the speakerphone by USB before starting Lianiq, or press **Refresh** in the device
   panel. Place it in the middle of the table, about 1 m from the customers, volume around
   50 %.
2. Leave the Windows default input on the laptop microphone (or a headset microphone) and the
   default output on the laptop speakers. Do not make the speakerphone the Windows default
   input: *Your microphone* follows the default and would then resolve to the table
   microphone, which blocks **Start meeting**.
3. Open **Meeting** (sidebar, second entry, or **Ctrl+2**). Under *Table speakerphone* choose
   the speakerphone as *Table microphone*; the *Table speaker* of the same device is suggested.
   Check that both name the speakerphone.
4. Keep *Your microphone* on `Follow Windows default (now: <name>)`, or choose a headset or
   lapel microphone explicitly. Speak about 50 cm from the laptop microphone.
5. Leave *Table microphone while Lianiq speaks Mandarin (Simplified)* on *Muted
   (recommended)* unless the speakerphone's echo cancellation has been verified for `open`.
6. **Start meeting** is enabled once every model and device is ready; otherwise each missing
   item or conflict is listed below the options.

### Local speech and the headset mark

**Speak German for me** plays the translation of every table contribution as local-language
speech on *Output for German speech*:

- Choose a headset output and tick *This output is a headset (no sound reaches the room)*.
  Nothing is muted while it speaks, and the customers do not hear it.
- Choose the laptop speakers and leave the mark off. While it speaks, both inputs show *Muted
  while speaking German*, so the room cannot feed it back into the meeting.
- Tick the mark only for an output whose sound cannot reach either microphone. A speaker
  marked as headset would let the local-language speech reach the user microphone and be
  translated again.
- The table speaker cannot be the local-speech output.

The headset mark and the table-microphone option are saved as `meeting.local_output_is_headset`
and `meeting.table_input_during_output` in `config/settings.local.json`, with the other
`meeting.*` keys. Endpoint IDs are saved; display names are not.

## Native verification

The native journeys (VoR-01..VoR-03) run on the operator workstation with the Jabra Speak2 75,
the laptop microphone and speakers, one USB headset and a helper at the table. The rows are
summarised in [native-e2e-rows.md](native-e2e-rows.md#meeting-operator-rows-cap-0177) and
recorded per the [Native Windows Evidence Profile](sdlc/native-windows-evidence-profile.md).
Missing native evidence leaves a row blocked, never passed.

## Related documents

- [Conversation architecture](conversation-architecture.md): the single-microphone pipeline,
  routing and held turns.
- [Call Bridge architecture](call-bridge-architecture.md): the two-lane design whose capture
  and endpoint-loss structure the meeting reuses (but not its dropping lane queues).
- [Troubleshooting](troubleshooting.md): notices, device problems and settings keys.
