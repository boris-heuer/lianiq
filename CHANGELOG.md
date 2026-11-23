# Changelog

All notable user-visible changes are documented here.

## Unreleased

### Added

- Language pack documentation: the README explains the Language packs page, the setup
  assistant, offline import from a `.zip` or folder, *Custom path*, the licence gate and how
  packs carry over to a new release; `MODEL_LICENSES.md` lists the licence of every pack;
  `docs/troubleshooting.md` covers no connection, no space, files in use, a pack in use, a
  *Failed* pack with **Download again** and the integrity check.
- `docs/meeting-architecture.md`: how a **Meeting** works (the four device roles, the language
  filter, the no-drop queue, which microphones are muted while Lianiq speaks with *Muted* or
  *Open*), the offline and privacy statement (no audio file is ever written; a transcript only
  after **Save…**), the setup of the Jabra Speak2 75 speakerphone and the headset mark, and the
  known limits. The README has a Meeting section, and `docs/native-e2e-rows.md` lists the
  Meeting operator rows.
- A skippable **setup assistant** opens on the first launch (not after an upgrade, and not
  with `--no-setup-assistant`) and again from **Run setup assistant** on the Language packs
  page: choose what you want to do, the conversation languages, check the audio devices
  (**Test microphone** with a live level, **Play test sound** with a generated tone; no file
  is written), and review which packs and devices are ready, with **Get…** for each missing
  pack. **Skip** or Escape and **Finish** are remembered, so it does not reopen on its own.
- The **Language packs** workspace (sixth sidebar entry, Ctrl+6) is now enabled: it lists the
  speech recognition, translation and voice packs with their state (*Downloadable*,
  *Installing…*, *Validated*, *Failed*, *Custom path*), "Needed by", the models folder and its
  free space, and English, Spanish and French in a collapsed *Planned languages* group.
  **Get…** opens the pack details (source, model and version, sizes, licence, use constraints,
  SHA-256 per file); **Download** and **Import…** (a `.zip` or a folder) stay disabled until
  the licence is accepted and while disk space is short. A job shows its progress with
  **Cancel**; a cancelled or failed job, including no connection, keeps the previous state
  and offers **Retry**. **Remove** names the usages that stop being ready, and only one pack
  job runs at a time. Nothing connects to the network before **Download**.
- After every pack job the other workspaces show the new readiness without a restart.
  **Remove** and **Update…** of a pack the running Conversation, Meeting or Call Bridge
  session uses are refused with "Stop the running <mode> session first". While no language
  pair is ready, Conversation shows the notice *No language pair is ready* with **Open
  Language packs**; Settings › Diagnostics has the same link.

### Fixed

- The voice warm-up at the start of a session, including **Start meeting**, now synthesises
  in memory and no longer writes a temporary WAV file.
- A Bluetooth headset whose PortAudio name carries a suffix that Windows does not store, such
  as `Headphones (<model>)` for the Windows names `Headphones` and `Headphones (<driver> …)`,
  is listed again as microphone and speakers in Settings › Audio devices, Conversation and
  Meeting, and *Follow Windows default* resolves to it. The suffix is matched only one-to-one
  in a freshly read device list: duplicate or ambiguous names stay unmatched and are never
  guessed, and the Call Bridge keeps its exact name match (#136).
- Conversation names the microphone chosen in Settings › Audio devices next to its level, as
  the Settings list shows it (also *Follow Windows default (now: …)* and
  *`<name>` — unavailable*), and updates it after a choice or a device refresh (#137).

## 0.2.0 - 2026-11-18

### Added

- `scripts/install-release.ps1 -Version vX.Y.Z` builds a tagged release in its own folder and
  installs it per user under `%LOCALAPPDATA%\Programs\lianiq\<version>`, with **Lianiq** Desktop
  and Start-menu shortcuts to the newest installed version; older versions and local settings
  are kept, and an installed version is replaced only with `-Force`.
- A **Meeting** workspace, the second sidebar entry (**Ctrl+2**; the shortcuts are now
  **Ctrl+1** … **Ctrl+7** by position): choose the table speakerphone's microphone and speaker
  (the other half of the same device is suggested), *Your microphone* (follows the Windows
  default or a chosen microphone) and the output for German speech with its headset mark, and
  whether the table microphone is muted while Lianiq speaks Mandarin (Simplified). **Start
  meeting** stays disabled and lists every missing model or device and any device conflict.
- A running **Meeting**: the table's Mandarin (Simplified) appears as German "Table" lines and
  your recognised German as "You" lines, in speech-end order, with *Translating…* until a line
  is ready. Per input the strip shows the level, *Listening*, *Muted while speaking …* or
  *Device lost*, and how many other-language contributions were ignored; it says when
  translation falls behind (nothing is lost). **Speak German for me** can be switched while
  the meeting runs; a lost device gets a persistent notice and no other device is used. **End
  meeting** offers to save a text transcript in both languages, only if something was
  translated; audio is never saved.
- Native E2E UIA rows E-01, E-11, E-03 and E-10 (`native_e2e/rows/`, `native_e2e/audio.py`):
  the real window through UI Automation and the virtual cable, transcripts stored as SHA-256
  only and endpoint names masked in every screenshot before it is written; a full run now gives
  every Phase 1 row a status. Runbook: `docs/native-e2e-rows.md`.
- A sanitized application screenshot, repository-owned Markdown link validation, and a fail-closed
  Windows audio troubleshooting matrix.
- A Call Bridge compatibility matrix that separates design compatibility, real-call evidence, and
  production `SystemOK` for headsets and communication applications.
- `docs/troubleshooting.md`, and README and Call Bridge operator setup sections for the sidebar,
  session strip, notices, Settings › Audio devices and Settings › Diagnostics.
  `scripts/capture_readme_screenshot.py --evidence <folder>` writes a screenshot of every enabled
  workspace at 850×560, 1120×720, 1280×720 and 1440×900 to a local folder, with generic devices
  and no transcript, and prints the SHA-256 of each file.
- `docs/native-e2e-setup.md` and the `tools/native-e2e/` scripts build a disposable, GitHub-only
  Windows 11 evaluation VM on a maintainer's Hyper-V host for automated native checks; the
  application itself is unchanged.
- The native-e2e image build activates Windows once through a build-only Microsoft activation
  allow-list, takes `-LicenceSource evaluation|key` (the key is typed only on the VM console),
  and `Invoke-NativeE2eRun.ps1` refuses runs on an expired evaluation image and warns 14 days
  ahead.
- The dispatch-only `native-e2e` workflow and `python -m native_e2e run|verify` run the S, C-03,
  C-04, E-12, screenshot and cleanup rows on the native-e2e VM for an exact commit, block
  commits outside the repository's branches, and upload the hashed evidence only after a
  redaction gate; the application itself is unchanged. The image carries a pinned,
  hash-checked MinGit (GPLv2, used only inside the test VM) on the runner's `PATH` only.

### Changed

- The window has a left sidebar with Conversation, Call Bridge (Experimental) and Settings, plus
  the planned Text translation, Listen & translate and Language packs entries (Ctrl+1…Ctrl+6;
  an icon rail below 1000 px). A session strip with **Stop (F9)** stays visible in every
  workspace, and only one session (Conversation or Call Bridge) runs at a time. Conversation
  gives the transcript most of the window; a panel you scroll up stays put until you scroll back
  to the end. Model profile and compute device moved to Settings › Diagnostics, and Voice output
  is also in Settings.

- Errors no longer flash in the status bar: each failure is a persistent notice at the top of
  its workspace that says what failed, for which mode, lane and language, whether recording and
  playback continue, and what to do (**Retry**, **Reconnect**, **Choose device**). A blocking
  notice stays until its cause is resolved; repeats update one notice, and "+N more" opens the
  notice history in Settings › Diagnostics. A failed speaker playback keeps the translation as
  text and turns spoken output off for the session. Settings › Diagnostics can **Copy** or
  **Export…** the history as local text with endpoint IDs, paths and your user name removed and
  no transcript text.

- Microphone and Speakers moved to Settings › Audio devices and are remembered by device
  identity instead of a list position, so a reordered or replugged device stays selected; *Follow
  Windows default* names the current default. **Refresh** lists a headset plugged in after start
  without restarting Lianiq (while a session runs, changes are reported and the lists refresh
  after Stop), and **Test microphone** / **Test speakers** check a device before a session. A
  missing saved device shows as "— unavailable" and Start asks you to choose a device instead of
  using another one. If the microphone is unplugged during a conversation, recording stops and
  the transcript is kept; if the speakers fail, translations continue as text. **Reconnect**
  reselects the same device. A device chosen by number in older settings is matched by name once
  and reported in a notice. Settings store the new `audio.*_policy`, `audio.*_endpoint_id` and
  `audio.*_device_name` keys; delete these six keys before downgrading to an older Lianiq.

- A refreshed look from the lianiq design colours with higher-contrast control borders, Segoe
  UI / Microsoft YaHei UI fonts and text sizes that follow Windows text and display scaling.
  Every focused control shows a 2 px focus outline, Tab moves sidebar → workspace → session
  strip, and focus returns to **Export…** / **Export transcript** after their dialogs. With
  Windows high contrast on, Lianiq uses the system colours. Lianiq opens at 1280×720 or the
  largest size that fits the screen; on a small screen or with large text the workspace scrolls
  or wraps its rows, while Start, Stop and the session strip stay in view.

- Mandarin spoken output uses the sherpa-onnx voice `vits-icefall-zh-aishell3` (speaker 20,
  8 kHz, CPU), downloaded by `scripts/download_models.py` from a pinned archive verified by size
  and SHA-256 into `models/sherpa/vits-icefall-zh-aishell3/`; German stays on Piper. Settings
  select the voice engine per language in `tts.engines` (`piper` or `sherpa-onnx`, with
  `speaker_id`, `length_scale` and `num_threads` for sherpa-onnx). An existing setting that still
  names the old placeholder `models/piper/zh_CN-user-provided.onnx` loads as the new voice; any
  other `.onnx` voice keeps Piper. To keep your own Piper voice at that placeholder path, set
  `tts.engines["zh-Hans"]` to `{"engine": "piper"}` in `config/settings.local.json`.
  `scripts/doctor.py` checks the files of a sherpa-onnx voice
  directory. Voice quality is interim
  ([#81](https://github.com/boris-heuer/lianiq/issues/81)).

- Settings use schema v2: language pair, routing and output in a `languages` block, translation
  models as directed `translation.edges`, voices in `tts.voices` by language ID, and
  `call_bridge.local_language`. Existing settings migrate without loss on load, and the first save
  keeps the original `config/settings.local.json` once as `config/settings.local.v1.json`.
- Models load on **Start**, only for the selected mode: no model loads at application start,
  text output never loads a voice, and a fixed direction loads only its own recognition and
  translation models. A missing reverse translation model raises an error naming that direction
  instead of using another model. A turn in a language outside German/Mandarin is reported and not
  translated; the script-based language guess was removed. `config/glossary.json` is keyed by
  direction (`de>zh-Hans`, `zh-Hans>de`); legacy `de-zh`/`zh-de` keys still load.
- A conversation session keeps the language pair and routing selected at **Start**: the routing
  control and *Switch direction* are disabled until **Stop**, and **Start** is refused with
  "Not available: missing …" when a model the mode needs is missing. Automatic routes each turn
  only to a detected German or Mandarin language at or above `languages.detection_min_probability`
  (0.7); any other turn is held, not translated, and discarded on **Stop**. **Stop** finishes the
  already-queued turns with their original languages and clears the translation context.
  **Export transcript** writes format v2 (`# lianiq transcript v2`, language IDs per turn, ordered
  by capture time).
- The main window has a *Language pair* control: ready pairs are selectable, and English, Spanish
  and French are listed as "planned, unavailable". Routing entries, results and the window title
  use language names instead of `DE`/`ZH`. Unavailable routing entries and *Voice output* are
  disabled with a tooltip naming the missing model, voice or device, and **Start** is disabled
  with the reason in the status bar (or "No language pair is ready …" when no pair has its
  models). While a session runs, *Language pair*, routing, *Switch direction* and *Voice output*
  are disabled until **Stop**. A turn with an unclear language shows a held-turn bar with
  **Translate as** one of the pair languages or **Discard**; later turns keep flowing, and
  **Stop** discards unresolved turns.
- The experimental Call Bridge takes its lane directions from the language pair and
  `call_bridge.local_language` (local → remote to the call, remote → local to the headphones),
  fixed for the whole call. Role labels and test buttons name those languages. **Start call
  bridge** is refused before any model loads with "Not available: missing …", naming every
  missing model, voice and unassigned endpoint.
- `scripts/doctor.py` prints the readiness of each capability of the configured language pair
  (recognition per language, translation per direction, voice per language). A missing voice is a
  warning, including the German voice, which was required before; `--require-voices` replaces
  `--require-mandarin-voice`. `scripts/benchmark.py` takes `--source <language ID>` instead of
  `--mode de-zh|zh-de`.
- Renamed the product, repository metadata, Python package, command, Windows executable, and
  documentation to `lianiq`.

### Fixed

- Combo boxes keep their rounded right corners: the Windows drop-down button no longer covers
  the frame's right end (Language pair, Conversation direction and every other combo box).
- Native E2E UIA rows read the real window: sidebar entries as UIA check boxes, combo items
  chosen by a click in the expanded list, controls below a scroll area's fold pressed with the
  keyboard, the save dialog's file-name field (1001), the notice history's text field and
  unscrolled panels; `scripts/ui_self_test.py` gives model loading its own 600 s budget.
- Native E2E E-10 tests the failed export on a write-protected file in a writable folder and
  answers the "replace?" prompt, because the save dialog refuses a write-protected folder
  itself; E-03 waits up to 300 s for the models.
- Closing the window without a ready language pair no longer replaces the saved or migrated
  routing with Automatic.
- At the default window width the held-turn buttons and the *Language pair* and *Conversation
  direction* controls show their full text: the transcript excerpt is shortened to the space left,
  and *Voice output* and *CUDA GPU* moved next to *Switch direction*.
- New results stay visible after a screen reader such as Narrator has read the *Original* or
  *Translation* panel: each result scrolls its panel to the end. On Windows the native crash log
  dumps only the reporting thread, so a COM error reported while Narrator is active can no longer
  crash Lianiq.
- Screen readers such as Narrator now announce the *Microphone*, *Speakers* and *Model profile*
  controls and the *Original* and *Translation* panels by name. After you resolve a held turn with
  the keyboard, focus moves to the next held turn's first button; when no held turn is left,
  focus moves to **Stop** (**Start** after a stop) instead of jumping to an unrelated control.

## 0.1.0 - 2026-10-06

### Added

- Public contribution, conduct, support, security, citation, and AI-assisted development guidance.
- An engineering case study that separates automated evidence from pending hardware and call gates.

### Changed

- Public documentation now describes translation as near-real-time and utterance-based.
- Call Bridge documentation identifies the feature as experimental until packaged hardware and
  WeChat acceptance checks are complete.

- Local Windows German/Mandarin speech transcription, translation, and synthesis workflow.
- Experimental, disabled-by-default Call Bridge source implementation.

This file records repository changes, not compatibility, quality, or production-readiness claims.
