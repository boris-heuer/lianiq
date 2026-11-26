# Native E2E UIA rows

The rows E-01, E-11, E-03, E-10, E-14, E-13 and E-15 of `python -m native_e2e run` drive
the real Lianiq window in the VM with UI Automation (pywinauto, `backend="uia"`) and the
virtual cable (VB-Cable). They run after C-04 and before E-12 (E-13 and E-15 right after E-14),
inside the S-04 offline window, and only when S-01 passed and S-03 recorded the settings backup. Setup, image build and run approval are in
[native-e2e-setup.md](native-e2e-setup.md).

## During a run

The rows click with the real mouse and type with SendInput. Do not use the VM console (mouse,
keyboard, window focus) between approval and the end of the job: a moved window or a click
makes a row fail. Rows wait for states with timeouts (20 s; 300 s for model readiness) and are
never retried.

## What each row does

| Row | Steps | Evidence |
|---|---|---|
| E-01 | Starts the app with `--no-setup-assistant`; reads the seven sidebar entries (Meeting second; all enabled), their order, selection, enabled state and description; checks that Conversation shows no Call Bridge control, Model profile, CUDA box or hardware subtitle; checks with psutil that no app process has a file under `models\` open or mapped before **Start** | Checks; `screens/e01-conversation.png` |
| E-11 | Writes `config/settings.local.json` from `native_e2e/data/legacy-settings.template.json` with `audio.input_device` set to the PortAudio index of "CABLE Output"; starts the app; waits for "Microphone set to '…' from your previous settings"; closes the app; reads the migrated keys | `name_matches` (never the name); `screens/e11-migration-notice.png` |
| E-03 | Checks the test phrase WAV against `image.json`; in Settings › Audio devices selects "CABLE Output" as Microphone; in Conversation turns every voice switch (`Speak <language>`) off; **Start** (F8); plays the WAV into "CABLE Input"; waits for a turn in *Original* and *Translation* that two consecutive reads agree on; visits every enabled workspace; presses F9 in Settings; returns to Conversation | `name_matches` for the Microphone (never the name); transcript SHA-256 (never the text); `screens/e03-running.png`, `screens/e03-after.png` |
| E-15 | CAP-0167 spoken output (AC-25): checks the test phrase WAV; starts its own app; in Settings › Audio devices selects "CABLE Output" as Microphone and "CABLE Input" as Speakers; in Conversation turns every voice switch on (a missing or invalid voice fails the row); **Start** (F8); plays the WAV into "CABLE Input"; waits until the turn is shown, the state reads "Microphone paused while the translation is spoken" and `logs/lianiq.log` has a completed synthesis; presses F9 at once; waits until the strip and the paused state are gone and **Stop playback** is disabled; plays the WAV again | `name_matches` for both devices; whether the log since F9 has "Microphone capture stopped", a playback ended by the stop and no "Microphone capture started"; transcript SHA-256 unchanged; `screens/e15-after-stop.png`. No log line is stored |
| E-10 | Settings › Diagnostics › **Export…**: types the path into the save dialog's file-name `Edit` (`AutomationId` 1001) and presses Enter, first to `%TEMP%\lianiq-e2e\diagnostics-E10.txt`, then onto `%TEMP%\lianiq-e2e\ro\diagnostics-E10.txt`, an existing file in a writable folder whose ACL denies the test user writes (`icacls`). The dialog asks whether to replace the file; the row answers **Yes** (`CommandButton_6`), and Lianiq must show its own "Export failed" notice ("Permission denied") while the file keeps its content | Forbidden pattern classes found (none on a pass); whether the second dialog closed (`dialog-closed`); `screens/e10-export-failed.png` |
| E-14 | Checks `native_e2e/fixtures/listen_de_16k.wav` (two German sentences, Piper, 16 kHz mono) against the SHA-256 pinned in `rows/e14.py` before any app starts; starts its own app; Listen & translate: German → Mandarin (Simplified), *Microphone* "CABLE Output"; **Start listening (F8)**; waits until the page listens and the strip shows "Listen & translate running"; plays the WAV into "CABLE Input"; waits for two done rows in *Transcript* that two consecutive reads agree on; F9; waits for idle (**Start listening (F8)** enabled); checks that the app process has no WASAPI render session (no output stream was opened); closes the app | `name_matches` for the Microphone (never the name); SHA-256 of the translation texts (never the text); `render_sessions` count; `screens/e14-listen.png` with *Transcript* masked |
| E-13 | CAP-0172 Text translation (its e2e plan row E-09, AC-37). Starts the app; in Settings › Audio devices selects "CABLE Input" as Speakers; sidebar **Text translation**; types the plan's German fixture text D-03 (two paragraphs) into *Source text*; **Translate**; waits for a result in *Translation* that two consecutive reads agree on (300 s); **Play translation**; waits for "Text translation running" in the strip; presses F9; waits until the strip is gone and the button reads **Replay**; checks both texts unchanged; closes the app | `name_matches` for the Speakers (never the name); result SHA-256 (never the text); `screens/e13-result.png`, `screens/e13-playing.png` with both panes masked |
| E-23 | CAP-0172 e2e plan E-05, E-06, E-08 (image models). Settings › Audio devices: "CABLE Output" as Microphone, "CABLE Input" as Speakers; Conversation **Start** (F8); Text translation: D-03 translated while Conversation runs; **Play translation** refused with "Stop the Conversation session first"; F9 stops Conversation, Play then runs; F9 in Settings stops it; both texts unchanged on return; D-06 (5,001 code points, pasted) shows the too-long text with the count and disables **Translate**, one Backspace (5,000) enables it; the sentinel D-05 "Lianiq sentinel QX7 Textprobe." translated and played (F9), Settings › Diagnostics **Export…** to `%TEMP%\lianiq-e2e\diagnostics-E23.txt`; restart: *Source text* empty; settings reset to the S-03 baseline | `name_matches` for both devices; result SHA-256 only; `sentinel-in-no-file` with `files=N hits=N` over `logs\`, the export and `config\settings*.json` (never a line); `screens/e23-busy.png`, `screens/e23-too-long.png` with both panes masked |
| E-26 | CAP-0170 E-04, E-06, E-08. Gets `conv_de_16k.wav`, `listen_de3_16k.wav` and `listen_sentinel_16k.wav`; its own app on the image models; German → Mandarin (Simplified), cable Microphone; **Start listening**; Settings, one sentence, back; Conversation, F8, then F9 there; **Start listening**, the three sentences, F9 at once; **Start listening**, the sentinel, F9; Settings › Diagnostics **Export…** to `%TEMP%\lianiq-e2e\diagnostics-E26.txt`; restart; resets the settings | The new row after the Settings visit; "Stop the Listen & translate session first" while Listen runs; F9 stops it, rows kept; the first state after F9 (`first=stopping` or `stopped`, within 2 s), *Stopped* in `seconds=N` (≤ 40), "Microphone capture stopped" in the log; after the restart *Transcript* empty, languages and cable preselected; `files=N matches=0` for "QX7" and the row texts in `logs\`, the export and `config\settings*.json`; `count=0` new `.wav`; `screens/e26-listen.png` |
| E-16 | CAP-0171 first launch (e2e plan E-01, E-02, E-06). Scratch models `e16` (empty); deletes `config/settings.local.json` and starts the app without `--no-setup-assistant`; waits for *Set up Lianiq* on *What do you want to do?*; reads the connection count since just before the launch; walks the four steps (usage, languages, audio check, readiness) with **Next** on their defaults, screenshotting each; **Skip**; closes; starts again without the flag and with the stored settings and watches 8 s for the assistant | `no-connection-before-first-click` (`count=N`, must be 0); `skip-stored` (`provisioning.first_run`); `screens/e16-step1-usage.png` … `e16-step4-readiness.png`, `screens/e16-relaunch.png`, masked (device lines, endpoint names, the models path) |
| E-18 | CAP-0171 import and session protection (E-08, E-05); one scratch group `e18` with E-19. The image folder of every German–Mandarin pack must hold `lianiq-pack.json` (else E-18 and E-19 are `blocked`, `image-packs-without-pack-file`); packs of other pairs such as english-mandarin-pair are not imported, need no folder and stay *Downloadable*. Imports a copy of `mt-de-zh-hans` with one byte flipped in its largest file (**Get…** › licence › **Import…** › **Choose folder…**); imports the pair's image pack folders; reads the scratch `model-manifest.json`; Settings › Microphone "CABLE Output"; Conversation **Start** (F8); Language packs › recognition pack **Remove** › **Yes**; F9; **Remove** › **Yes**; re-imports it | Refusal "This pack cannot be imported: file … failed the integrity check" with the row *Downloadable*; `import-<pack>-validated` for each pair pack; `manifest-source-import` (`records=N`); "Stop the running Conversation session first" with the row still *Validated*; *Downloadable* after Stop; *Validated* after the re-import; `screens/e18-imported.png` |
| E-19 | CAP-0171 offline Conversation (E-09, E-04), on the E-18 app and scratch models once every pair pack is *Validated* (else `blocked`, `e18-packs-not-validated`). Checks `conv_de_16k.wav` against its pin; Conversation **Start** (F8), reading every warm-up text ("Loading models …") until "Conversation running"; plays the WAV into "CABLE Input"; waits for a turn in *Original* and *Translation*; F9 | `warm-up-without-percentage` (`seen=N`); transcript SHA-256 (never the text); `connection-count-0` since the row started; `screens/e19-after-stop.png` with both panels masked |
| E-20 | CAP-0172 e2e plan E-01, import instead of download. Scratch models `models-e20` (empty), no settings file: the setup assistant opens; only **Text translation** ticked; German and Mandarin (Simplified); *Audio check* **Next**; *Readiness* lists both voices *Optional — for spoken output*, no speech recognition and no microphone row; each translation row's **Get…** › licence › **Import…** › **Choose folder…** with the image pack folder until the row reads *Ready*; **Finish**; Text translation: D-03 translated without restart | `model-manifest.json` holds exactly the two translation packs (`packs=N`); result SHA-256; `screens/e20-usage.png`, `screens/e20-readiness.png`, `screens/e20-result.png` |
| E-21 | CAP-0172 e2e plan E-02, same scratch models and app (no voice): the E-20 result is current; **Play translation** disabled with "Play translation needs the Mandarin (Simplified) voice." and **Open Language packs**; **Swap languages**; D-04 translated; Play then names the German voice | Result SHA-256 per direction; `screens/e21-no-voice.png` |
| E-22 | CAP-0172 e2e plan E-03, E-04, same scratch models and app: both voices imported (Language packs); "CABLE Input" as Speakers; German → Mandarin (Simplified), D-03, **Translate**; **Copy translation**; **Play translation**, **Stop**: the button reads **Replay**; **Replay** plays to the end; one character added: stale marker within 2 s, **Copy translation** and **Replay** disabled; the target changed: still disabled. The group then closes the app, points `models` at the image again and resets the settings | Clipboard SHA-256 equal to the result SHA-256 (never the text); `screens/e22-playing.png`, `screens/e22-stale.png` |
| E-24 | CAP-0170 E-01. Scratch models `e24` (with E-25, one app); no settings file, so the setup assistant opens; only **Listen & translate**; German and Mandarin (Simplified); *Audio check*; *Readiness*: **Get…** imports the recognition pack and `de>zh-Hans` from the image folders (German–Mandarin packs only; other pairs' folders need no pack file); **Finish** | Readiness lists the recognition pack, both translation packs and the microphone, no voice and no playback device; `zh-Hans>de` still *Not installed* when **Finish** closes the assistant; `model-manifest.json` holds exactly the two packs (`packs=2`); `screens/e24-usage.png`, `screens/e24-readiness.png` |
| E-25 | CAP-0170 E-02, E-03, on the E-24 app. German → Mandarin (Simplified), cable Microphone; `listen_de3_16k.wav`; F9; **Swap languages**; Language packs: `zh-Hans>de` imported; Listen & translate: `listen_zh_de_16k.wav` (`synth.speech_wav`); F9; **Copy transcript**; **Export transcript** to `%TEMP%\lianiq-e2e\listen-E25.txt`; closes the app, restores the junction and resets the settings | Three translated rows in speech order (`rows=3`), translation SHA-256, no render session; after Swap **Start listening** disabled with "Not available: missing translation Mandarin (Simplified) → German" and **Open Language packs**; Start enabled after the import without restart; every new row Mandarin → German, one translated; clipboard equals the file (SHA-256); `de-zh=3 zh-de=N` turns of transcript v2 |
| E-27 | CAP-0167 e2e plan E-01, E-06. Resets the settings to the S-03 baseline; starts its own app on the image models; Conversation; Settings | No CheckBox named *Voice output*; "Speak German" and "Speak Mandarin (Simplified)" enabled and on, each state "{voice} · Ready"; **Replay** disabled with the tooltip "Nothing to replay yet"; Settings › Voice output shows both switches on and the Call Bridge/Meeting hint; Diagnostics lists "Voice German: Ready" and "Voice Mandarin (Simplified): Ready"; `screens/e27-conversation.png` |
| E-28 | CAP-0167 E-02, E-03. Gets `conv_zh_16k.wav` and `conv_de_16k.wav` (`synth.speech_wav`); its own app; cable Microphone and Speakers; both switches on; **Start**; plays the Mandarin fixture, then the German one (so the last spoken translation is Mandarin); **Replay** recorded on "CABLE Output"; Mandarin **Voice options…**: Rate to 1.30× (UIA RangeValue), **Close**; **Replay** recorded again; German **Voice options…**; closes the app and resets the settings | Per turn: the turn is shown on every poll with the paused state (text before speech), the paused state shows and the level bar reads 0; completed playbacks in both languages; first and second Replay speech durations and their ratio (≤ 0.85); `tts.output["zh-Hans"].rate` 1.3 saved; dialog controls (Mandarin: Voice, Rate; German: Rate, Volume); `screens/e28-spoken.png`. No PCM, text or log line |
| E-29 | CAP-0167 E-04. Gets `conv_de_16k.wav`; its own app; cable devices; both switches on; **Start**; records the cable; plays the fixture and presses **Stop playback** while the translation plays, then again and presses F9; plays the fixture once more and watches 10 s; closes the app and resets the settings | The last cable signal after each press in seconds (≤ 0.5, measured in the 1.5 s after the press); the playback ended by the stop (log); after F9 the strip and the paused state gone, *Ready* and level 0 on every poll for 10 s, no "Microphone capture started" after F9 |
| E-31 | Keyboard (CAP-0168 E-09 parts, CAP-0167 E-08). Starts its own app; Conversation: walks the Tab cycle (sidebar, workspace with the voice row, strip); Tab to the first enabled `Speak <language>` switch, Space toggles it, Space restores it; Tab to the first "Voice options for <language>", Enter opens "Voice options — <language>" (Space when Enter does not, for the walk), walks it, Escape closes it; Settings: walks the Tab cycle, Tab to **Export…**, Space opens "Export diagnostics", Escape cancels it; Ctrl+2…Ctrl+7 and Ctrl+1 select their sidebar entry; closes the app, resets the settings to the S-03 baseline | Per walk `stops=N` and the control types of unnamed stops (never a name); `space-toggles-voice-switch`, `enter-opens-voice-options`, `escape-closes-voice-options`, `focus-returns-to-export`, `ctrl-1-7-switch-pages` with `switched=N/7` |
| E-32 | Keyboard (CAP-0170 E-07, CAP-0172 E-07). Starts its own app; Listen & translate: German → Mandarin (Simplified), *Microphone* "CABLE Output", walks the Tab cycle, F8 starts listening, F9 stops it (nothing is played); Text translation: types D-03, Ctrl+Enter translates it, Tab leaves *Source text* and *Translation*, walks the Tab cycle; pastes D-03 30 more times with the keyboard, Tab to **Translate**, Enter starts it, the focused button is named **Cancel**, Escape cancels ("Translation cancelled. Your text is unchanged.") and the focused button is named **Translate** again; resets the settings | Walk counts as E-31; `f8-starts-listening`, `f9-stops-listening`, `ctrl-enter-translates` (result SHA-256), `tab-leaves-*`, `enter-on-focused-button`, `focused-button-named-*`, `escape-cancels-translation`. No text is stored |
| E-30 | CAP-0167 E-05, E-06 (Diagnostics), E-07. Gets both fixtures before the junction moves; scratch models `e30` with every German–Mandarin pack but the Mandarin voice imported (`packs_import`; packs of other pairs such as english-mandarin-pair are not imported, and their folders need no pack file); Conversation; **Open Language packs** and back; cable devices; German switch on; **Start**; German then Mandarin fixture; F9; Settings › Diagnostics; closes the app (junction restored). Then the legacy settings (template plus `languages.output: "text"`) on the image models; launch; Conversation; reset the settings | Packs *Validated* (`count=N`); Mandarin switch off and disabled, "Voice missing"; Language packs opened; both turns shown, completed playbacks in German only; Diagnostics "Voice German: Ready" and "Voice Mandarin (Simplified): Voice missing"; `screens/e30-voice-missing.png`; with the legacy settings both switches on |
| E-33 | Keyboard (CAP-0171 E-10). Starts its own app; Language packs: once no row reads "Checking…" (300 s), walks the Tab cycle; Tab to **Run setup assistant**, Space opens "Set up Lianiq", walks its first step, Escape closes it; Tab to the first **Get…**, **Update…** or **Download again**, Space opens the pack's details dialog, walks it, Escape closes it (the licence box stays unticked, so **Download** stays disabled); Tab to the first **Remove**, Space opens the confirmation, walks it, Escape cancels it; resets the settings | Walk counts as E-31; `pack-actions-shown` counts the **Update…**, **Download again**, **Remove** and *Custom path* stops the image shows; `packs-unchanged-after-escape` |
| C-05 | `scripts\self_test.py` with the run's Python from the checkout, timeout 600 s (CAP-0167 C-03) | Exit code; `logs/c05-self-test.txt` with the output's SHA-256 and the duration only (the script prints recognised and translated text) |
| C-06 | `scripts\call_bridge_self_test.py` without arguments: both lanes over the image models (CAP-0167 C-03; C-04 already runs `--synthetic`) | Exit code; `logs/c06-call-bridge-self-test.txt` (SHA-256 and duration only) |
| C-09 | `scripts\doctor.py` (CAP-0171 C-02), then the S-04 count of the app interpreter's non-loopback connections since the row started | Exit code; `logs/c09-doctor.txt` (SHA-256 and duration only); `connection-count-0` with `count=N` (a late WFP event still counts in S-04) |
| E-17 | CAP-0171 download without a connection (E-07). Runs after S-04 is recorded and before T-01, while the block rule still holds. Scratch models `e17` (empty); Language packs; **Get…** on `mt-de-zh-hans` › licence; reads the connection count; **Download** | Every catalog pack *Downloadable* (`all-downloadable`, `count=N` from `lianiq/packs/builtin_catalog.json`) and "New here? Run the setup assistant."; `no-connection-before-download` (`count=N`, must be 0); "Download unavailable: no connection to … Import the pack from a file or folder instead." with **Import…** and **Retry**; the count after the click is recorded, not judged; `screens/e17-download-unavailable.png` |
| T-05 | After T-02 and before T-03 (which deletes `%TEMP%\lianiq-e2e`): points the checkout's `models` junction at the image `models_dir` again if a scratch-model group left it elsewhere, then deletes every recorded `%TEMP%\lianiq-e2e\models-<group>` folder | `models-junction-targets-image`; `scratch-folders-deleted` with `left=N` |

E-31 and E-32 run after E-29 and before E-23, E-33 after E-30 and before C-05, inside the S-04
window, each with its own app on the image models. No key confirms a download, an import or a
removal: dialogs are only closed with Escape. A modal dialog gets its keys without the main
window being brought to the front (`App.send`).

C-05, C-06 and C-09 run after E-33 and before E-12, inside the S-04 window. C-03 already
runs `ui_self_test.py` and C-04 `call_bridge_self_test.py --synthetic`, so neither is run
again. `scripts\download_models.py` never runs: it always downloads and stages into `models`
(read-only in the VM), and a blocked download attempt counts against S-04.

E-15 runs after E-13 and closes its app at the end. It plays the translation into the cable, so
the paused microphone is what keeps Lianiq from hearing its own voice; the second WAV is played
after F9, so any capture after Stop shows in the log.

E-16, E-18 and E-19 run after E-26 and before E-20, inside the S-04 window; each scratch
group points the `models` junction back at the image models and calls `settings_reset` at
its end, also when it fails. E-17 runs after S-04 is recorded and before T-01: **Download**
makes one blocked connection attempt that would otherwise fail S-04.

E-23 runs after E-32 on the image models; after E-19, E-20, E-21 and E-22 follow as one
scratch-model group (`e20.run` runs all three with one app; E-21 and E-22 are `blocked` with
`translation-packs-not-ready` when E-20 imported no translation). A pack folder without
`lianiq-pack.json` makes all three `blocked` with `image-packs-without-pack-file` before the
junction or the settings change. No row in the S-04 window presses **Download**. E-24 and
E-25 follow E-22, then E-30 and E-33.

E-26 (CAP-0170 Listen & translate) runs after E-23 on the image models; E-24 and E-25 run after
E-22 and share one app on scratch models `e24` (the junction and the settings baseline come
back in `finally`). No row presses **Download**: packs are imported from the image folders.
Row texts go to the redaction secrets; the export, the clipboard and the diagnostics file stay
in the VM and only counts and SHA-256 are stored.

E-27..E-30 (CAP-0167 voice output) run after E-15, each with its own app, and E-28..E-30
reset the settings to the S-03 baseline at the end. The Mandarin fixtures are not committed:
`native_e2e/synth.py` renders them in the VM with the image's Mandarin and German voices
(16 kHz mono 16-bit, under `%TEMP%\lianiq-e2e\fixtures`) when `fixtures.checked` finds no
pinned file; their texts go to the redaction secrets and the WAVs never leave the VM. The cable
measurements store durations only (`audio.speech_span`).

E-03 leaves the app open for E-10, so the export holds that session's log. E-10 reads the
failure from the notice elements only: the notice history logs every posted notice title,
so the first export's "Diagnostics saved as …" line is always in it. A save dialog still
open is cancelled before the screenshot and the close. E-14 (CAP-0170 AC-31) closes any app
left open and starts and closes its own instance, so its render-session check sees only its
own Listen session: Windows lists a process's render session from its first output stream
until the process exits. T-01 restores the settings file and T-03 resets the ACLs of `%TEMP%\lianiq-e2e` and deletes it.

E-10 protects a file, not a folder: the Windows save dialog itself refuses a folder with
denied writes ("no permission to save in this path"), so that path never reaches Lianiq.
The PO chose the write-protected file after native run 44267851808.

## Building blocks of the automated PO rows

The rows of the automated PO rows (spec `native-test-automation/automated-po-rows`) share these
helpers in `native_e2e/`:

- **Scratch models** (`models_swap.scratch_models(ctx, group)`): points the checkout's
  `models` junction at a new, empty, writable `%TEMP%\lianiq-e2e\models-<group>` (one folder
  per group of scratch-model rows, not per row) and back at the image `models_dir` when the
  block ends, also when a row raises. A junction is removed with `os.rmdir`, which never
  deletes its target; a real `models` folder is never touched. The app must be closed on entry
  and on exit. T-05 checks the junction and deletes the folders before T-03 runs.
- **Pack import** (`packs_import.import_folder(app, pack_id, folder)`): Language packs › the
  pack row's **Get…** › licence box › **Import…** › **Choose folder…**; types the folder path
  into the native folder picker without Enter (Enter navigates into the folder) and presses
  **Select Folder**; waits for *Validated* (300 s). **Download** is never pressed, so no helper
  makes a network attempt inside the S-04 window. Sources are the image's read-only pack
  folders (`image_pack_dir`); a folder without `lianiq-pack.json` (images built before
  lianiq#170) returns `image-packs-without-pack-file` before the UI is touched, and the row is
  `blocked` with that reason. `make_corrupt_copy` copies a pack folder and flips one byte in
  its largest file.
- **First launch** (`uia_app.launch(ctx, setup_assistant=True)`): the assistant opens only
  without `config\settings.local.json` and with `provisioning.first_run` pending, so the
  helper deletes the local settings file first (it needs the S-03 backup) and starts without
  `--no-setup-assistant`; the default launch is unchanged. `uia_app.settings_reset`
  puts the S-03 baseline back (or deletes the file when none existed) between row groups.
- **Speech fixtures** (`native_e2e/fixtures/`, `fixtures.checked(name)`): synthetic 16 kHz
  mono WAVs, SHA-256 pinned in `native_e2e/fixtures.py`, generator
  `native_e2e/data/make_fixtures.py`, texts and licences in `native_e2e/fixtures/README.md`.
  A row adds the fixture texts to the redaction secrets (`fixtures.remember`).
- **Cable capture** (`audio.record_cable`, `audio.CableRecorder`, `audio.speech_span`):
  records "CABLE Output" into memory; only durations (first and last 20 ms frame above the RMS
  threshold, a key-press mark) are stored, never PCM.
- **Connection count per row** (`s04.count_since(ctx, since)`): the `wfp-count` verb of the
  admin helper for the app interpreter since a time; no new verb.
- **Keyboard walk** (`rows.ui.tab_walk(app)`): Tab until the first focused element repeats;
  control type and "has a name" per stop, never a name.

## Privacy of the evidence

- E-20..E-23 mask *Source text* and *Translation* in every screenshot and add D-03, D-04,
  D-05, D-06 and every result line to the redaction secrets; the clipboard is compared by
  SHA-256 only; E-23 stores only file and hit counts of its sentinel search.
- E-13 masks *Source text* and *Translation* in both screenshots whatever they show, and adds
  the fixture lines and the result lines to the redaction secrets, so any stored copy fails
  the scan.
- Transcript texts stay in memory. The row records their SHA-256, and the redaction scan
  fails the run if any of them, with or without its language label, appears in a stored
  file.
- Each screenshot is captured into memory and masked before the PNG is written. Masked are
  both transcript panels (*Original* and *Translation*) whatever they show, every shown
  element whose text contains an endpoint name or a transcript line (device combos, the
  E-11 notice, the notice history), the Microphone and Speakers combos, and every combo,
  edit or document field whose text cannot be read. The receipt's
  `redaction_scan.screens_masked` counts the screenshots written this way.
- The exported diagnostics file stays in the VM. E-10 records only the class names of what it
  found: transcript text, the test phrase, `%USERNAME%`, `%USERPROFILE%`, a drive path, an
  endpoint identifier pattern or the cable's endpoint identifier.

## Reviewing a run (e2e plan E-03, E-04)

Read the seven rows in `native-evidence.json`: each is `pass`; E-03, E-11, E-14, E-13 and E-15
use the method `automated-virtual-device`. Open the screenshots under `screens/`: every device name region
and both transcript panels are black rectangles. Run `python -m native_e2e verify <artifact-dir>`; it must pass.

## Troubleshooting

| Symptom | First thing to check |
|---|---|
| E-01 `sidebar-seven-entries-in-order` fails with 0 entries | The window was not reachable through UI Automation: the app did not start, or the console session was locked |
| E-11 `migration-notice-shown` times out | The cable is missing or renamed (T-02 also fails), or the app did not read `settings.local.json` |
| E-03 `turn-in-original-and-translation` times out | Spec assumption 4: the German model did not recognise the Piper phrase through the cable |
| E-03 `microphone-cable-selected` or `voice-output-off` fails | The cable is missing from the Microphone list (T-02 also fails), or a voice switch did not react to the click; the row does not press **Start** then |
| E-15 `speakers-cable-selected` fails | "CABLE Input" is missing from the Speakers list |
| E-15 `voice-output-on` fails with `not-ready` | A voice of the pair is missing or invalid in the VM image; provision both voices |
| E-15 `translation-spoken` times out | No turn (see E-03), or the voice did not synthesise: look for "Speech synthesis failed" in `logs/lianiq.log` in the VM |
| E-15 `playback-ended-by-stop` fails | The speech had ended before F9 (the log has "Audio playback completed"), or the stop did not end it |
| E-15 `no-capture-after-stop` fails | The microphone started again after **Stop**: a defect, never retried |
| E-03 `scroll-unchanged` fails with `unreadable` | UI Automation gave no scroll value for a transcript panel or its scroll bar |
| E-10 `overwrite-confirmed` fails | The save dialog showed no "replace?" prompt for the protected file (the file is missing, or the prompt has no `CommandButton_6`) |
| E-10 `failure-notice-shown` fails with `dialog-closed: false` | The save dialog stayed open after **Yes** (an error box over it); the row cancels it before the screenshot |
| E-10 `failure-notice-shown` fails with `dialog-closed: true` | Lianiq wrote the protected file or showed no "Export failed" notice |
| E-14 `start-listening` fails with `not-enabled` | A recognition or translation pack of German → Mandarin (Simplified) is missing, or the page shows another readiness block |
| E-14 `two-done-rows` times out | The German model did not recognise the fixture through the cable, or the VAD closed fewer than two segments |
| E-14 `no-render-stream` fails | The app opened an output stream during the session (`render_sessions=N`), or Windows audio sessions could not be read (the exception type) |
| E-13 `speakers-cable-selected` fails | "CABLE Input" is missing from the Speakers list (T-02 also fails) |
| E-13 `translation-shown` times out | The German → Mandarin (Simplified) translation pack is missing from the image (`scripts\download_models.py`) |
| E-13 `strip-text-translation-running` fails with `play-disabled` | The Mandarin (Simplified) voice is missing from the image, or no usable Speakers |
| E-13 `stopped-with-f9-idle` times out | F9 did not stop the playback, or **Replay** did not appear |
| E-20..E-22 `blocked` `image-packs-without-pack-file` | The image predates lianiq#170: rebuild it (`New-NativeE2eImage.ps1 -Replace`) |
| E-16 `assistant-on-usage-step` times out | The settings file was not deleted (no S-03 backup), or the assistant opened as a window UI Automation does not list under the app |
| E-16 `no-connection-before-first-click` fails | The app interpreter tried a connection at start (`count=N`), or the admin helper gave no count (`count=None`) |
| E-16 `relaunch-without-assistant` fails | **Skip** did not store `first_run = "skipped"` (`skip-stored` also fails) or the settings were not persisted |
| E-17 `all-downloadable` times out | The `e17` scratch folder was not empty, the junction did not move (an app still held a model), or a catalog pack has no row |
| E-17 `blocked` `s04-block-rule-missing` | S-04 did not add the firewall block rule for the app interpreter, so E-17 does not press **Download** (no real connection may leave the VM) |
| E-17 `download-unavailable-shown` times out | The download did not fail with a connection error within 300 s (a proxy answered, or DNS hung) |
| E-18 or E-19 `blocked` with `image-packs-without-pack-file` | A German–Mandarin pack folder of the image has no `lianiq-pack.json`: the image is older than lianiq#170, rebuild it (`New-NativeE2eImage.ps1 -Replace`). Folders of other pairs are not checked |
| E-18 `corrupt-copy-refused` times out | The flipped file is not listed in the catalog, or the import accepted it (a defect) |
| E-18 `import-<pack>-validated` fails | The reason names the step: `row-action-not-shown`, `licence-not-accepted`, `folder-dialog-not-opened`, `select-folder-not-shown` or `not-validated` (300 s) |
| E-18 `remove-refused-while-running` fails | `confirmation-not-shown`: the Remove question box has no **Yes**; a timeout: the pack was removed during the session (a defect) |
| E-19 `warm-up-without-percentage` fails | `seen=0`: the models loaded before the first read; `percentage=true`: a percentage was shown (a defect) |
| E-19 `translation-turn` times out | See E-03 `turn-in-original-and-translation`; the imported packs are those of the image |
| E-20 `imported-mt-…` fails with `get-not-shown`, `details-not-opened` or `folder-dialog-not-opened` | The readiness row offered no **Get…**, or the pack dialog or the folder picker did not open (see the building blocks) |
| E-20 `readiness-no-recognition-no-microphone` fails | The Text translation usage asks for a recognition pack or a microphone: a defect of the readiness review |
| E-21 `play-unavailable-…-voice` times out | A voice is already in the scratch folder, or no Speakers are usable (the speakers hint shows instead) |
| E-22 `clipboard-equals-result` fails with `differs` | Another program held the clipboard, or the copy did not take the current result |
| E-22 `stale-at-once-controls-disabled` times out | The character did not reach *Source text*, or the result stayed current: a defect |
| E-23 `play-refused-session-busy` times out | Conversation did not run (see E-03), or the playback started anyway |
| E-23 `too-long-translate-disabled` fails with `not-pasted` | The clipboard was held by another program |
| E-23 `sentinel-in-no-file` fails | A log, the export or a settings file holds the sentinel: a privacy defect (the file stays in the VM) |
| E-10 `file-written` fails | The save dialog did not close after Enter (a prompt is open), or the file-name field was not found |
| E-28, E-29 or E-30 `blocked` with `fixture-missing` | A pinned fixture changed, or the Mandarin voice (or Piper) could not synthesise the fixture in the VM: run `native_e2e\data\make_fixtures.py --models <models_dir> --only conv_zh_16k.wav --out <folder>` in the VM |
| E-27 `diagnostics-voices-ready` times out | UI Automation gave no text for the *Readiness* value, or a voice is not ready in the image |
| E-28 `text-before-speech` fails | The paused state showed before the new turn was in the panels: a defect, never retried |
| E-28 `replay-faster-at-rate-1.30` fails | The ratio in the detail is above 0.85: the Rate did not reach the replayed Mandarin voice (check `mandarin-rate-1.30-saved`) |
| E-29 `last-signal-after-…` fails | Speech went on in the cable more than 0.5 s after the press (seconds in the detail) |
| E-30 `blocked` with `image-packs-without-pack-file` | The image is older than lianiq#170: rebuild it |
| E-30 `german-spoken-mandarin-text-only` fails | The log shows a Mandarin playback although the voice is missing, or no German playback |
| E-24 and E-25 `blocked` with `image-packs-without-pack-file` | The image is older than lianiq#170: rebuild it |
| E-24 `imported-…` fails | The readiness row showed no **Get…**, the pack dialog did not import the folder, or the row never read *Ready* (reason in the detail) |
| E-25 `blocked` with `listen-packs-not-ready` | E-24 did not finish with the recognition pack and `de>zh-Hans` installed; fix E-24 first |
| E-25 `three-rows-in-order` fails | The VAD merged or split the sentences (`rows=N`), or a recognised sentence matched another position |
| E-25 `mandarin-rows-to-german` fails | A row of the Mandarin → German session showed a Mandarin target: a defect, never retried |
| E-26 `stopping-at-once` fails with `first=none` | Neither *Stopping…* nor *Stopped* showed within 2 s of F9 |
| E-26 `no-sentinel-or-row-text` fails | "QX7" or a recognised row text is in a log, the diagnostics export or a settings file (`matches=N` files) |
| E-31, E-32 or E-33 `*-tab-stops-named` fails | The detail names the control types of the unnamed stops (`unnamed=Button,Edit`) or `cycle-open` (more than 120 stops, or the focus left the window): find the control with Accessibility Insights in the VM |
| E-31 `enter-opens-voice-options` fails with `timeout` | Enter does not activate **Voice options…** (a tool button reacts to Space); the row opened the dialog with Space for the walk |
| E-31 `ctrl-1-7-switch-pages` fails | `switched=N/7`: an entry is disabled or the shortcut did not reach the main window |
| E-32 `escape-cancels-translation` times out | The long translation finished before Escape, or the cancel message did not show |
| E-33 is `blocked` with `no-details-action` | Every pack of the image is installed without an update: no row action opens the details dialog |
| E-33 is `blocked` with `no-remove-action` | No pack of the image is installed |
| C-05, C-06 or C-09 `exit-code-0` fails | Run the script in a source checkout of the same commit: the log keeps no output line (`timeout` after 600 s) |
| C-09 `connection-count-0` fails | The app interpreter tried a non-loopback connection during the row (`count=N`), or the admin helper gave no count (`unreadable`) |
| T-05 `models-junction-targets-image` fails | The checkout's `models` is no junction any more (`RuntimeError`) or `image.json` is unreadable; the next run starts from the reverted checkpoint |
| T-05 `scratch-folders-deleted` fails | A file in a scratch folder was still open (an app process left running) |

## Meeting operator rows (CAP-0177)

The Meeting rows are operator hardware rows, not VM rows: the row IDs below are those of the
CAP-0177
[e2e validation plan](https://github.com/boris-heuer/app-shared/blob/main/docs/products/lianiq/capabilities/meeting-dual-mic-translation/e2e-validation-plan.md)
and are unrelated to the `python -m native_e2e` rows of the same names above. The operator runs
them at the real window of the source build (`python run_app.py`) of the exact commit, with the
Jabra Speak2 75 on USB, the laptop microphone and speakers, one USB headset, a helper (or a
second device) speaking the plan's Mandarin phrases at the table, and Narrator for E-12. The
plan holds the full steps, data D-01..D-07 and pass rules; setup and the headset mark are in
[meeting-architecture.md](meeting-architecture.md#operator-setup).

| Row | Steps | Evidence |
|---|---|---|
| S-01 | Check out the exact commit; record commit, Windows build, Python version, start time | Values in `verification-report.md` |
| S-02 | `python scripts/doctor.py` | Recognition, both edges and both voices ready |
| S-03 | Back up `config/settings.local.json` to `%TEMP%\lianiq-e2e\`; place settings without a `meeting` block | Backup exists |
| S-04 | Airplane mode for every following row | No adapter connected |
| S-05 | Connect the Jabra; Windows default input = laptop microphone, default output = laptop speakers | Defaults recorded by role, not by endpoint ID |
| S-06 | Helper or second device at the table position | Position recorded |
| E-01 | Launch; Meeting is the second sidebar entry; **Ctrl+2**; defaults of *Your microphone*, the table-microphone option and **Speak German for me** | Screenshot SHA-256 (AC-01, AC-25, AC-29) |
| E-02 | Jabra as *Table microphone*; check the suggested *Table speaker*; make the Jabra the Windows default input and back | Screenshots of the conflict and its clearing (AC-03) |
| E-03 | **Start meeting** (`mute`); one Mandarin phrase, one German phrase | Exactly two lines; Mandarin speech only from the Jabra; both inputs muted during it (AC-04, AC-06, AC-11, AC-20, AC-24) |
| E-04 | German phrase; the helper speaks during its output, then 2 s after it | No line for the muted phrase, one for the later one (AC-24) |
| E-05 | Three overlapping phrase pairs within 1 s | Six lines in speech-end order, none missing (AC-13) |
| E-06 | Unplug the Jabra for 5 s, replug | Persistent notice; no substitute device; nothing restarts on its own (AC-15) |
| E-07 | **End meeting** → **Save…** to `%TEMP%\lianiq-e2e\meeting-E07.txt`; search for new `*.wav` files | File SHA-256 only (file stays local); `.wav` search result count (AC-16, AC-17, AC-18) |
| E-08 | Empty meeting for 10 s, **End meeting** | No save dialog (AC-27) |
| E-09 | *Open*; ten Mandarin outputs, nobody at the table speaks | Line counts: ten "You", zero "Table" (AC-23, AC-25); a fail is recorded, not hidden |
| E-10 | **Speak German for me** on a marked headset, then on the laptop speakers unmarked | Speech on the chosen output; speaker output mutes both inputs and forms no line (AC-05, AC-26) |
| E-11 | *Output for German speech* = the Jabra speaker | Switch disabled with the conflict; **Start meeting** enabled (AC-28) |
| E-12 | Keyboard and Narrator: devices → options → Start → running view → End | Announced names and order noted; no unnamed Tab stop (AC-20) |
| T-01 | Restore the S-03 settings backup | Settings as before |
| T-02 | Restore the S-05 Windows defaults; devices as before | Device state as before |
| T-03 | Delete `%TEMP%\lianiq-e2e` after copying the E-07 SHA-256 | Folder absent |
| T-04 | Stop Narrator; reconnect the network | Normal workstation state |

Evidence follows the [Native Windows Evidence Profile](sdlc/native-windows-evidence-profile.md):
commit, Windows build, Jabra display name and firmware, operator, line counts and pass or fail
per row. Never record transcript text, PCM or endpoint IDs; the E-07 file and every screenshot
(they show device names and German lines) stay in the local evidence folder, and only their
SHA-256 is recorded. The run also records the design-intent comparison of the Meeting page
against spec §2; each deviation needs the operator's recorded acceptance. A row without native evidence is
blocked, never passed. The code rows C-01..C-03 of the plan are re-read for the same commit and
never satisfy a native row.

## Language packs operator rows (CAP-0171)

The Language packs rows are operator rows: the row IDs below are those of the CAP-0171
[e2e validation plan](https://github.com/boris-heuer/app-shared/blob/main/docs/products/lianiq/capabilities/offline-language-provisioning/e2e-validation-plan.md)
and are unrelated to the `python -m native_e2e` rows of the same names above. None of them runs
in `python -m native_e2e`: that run launches with `--no-setup-assistant` and needs the image's
installed models for its own E-03, while these rows need a first launch with an empty `models\`
folder, real downloads, a USB stick or Narrator. The automated run still contributes code
evidence: its E-01 checks that Language packs is enabled, and its E-03 opens the Language packs
page inside the offline window. The PO runs the rows at the real window of the source build
(`python run_app.py`) of the exact commit: E-01..E-06 on a laptop with network, E-07..E-10 on
the CAP-0174 VM with egress blocked. The plan holds the full steps, data and pass rules.

| Row | Steps | Evidence |
|---|---|---|
| D-01..D-05 | Empty `models\` (rename to `models.backup-e2e\`); settings moved to `%TEMP%\lianiq-e2e\`; after E-03 the five pack roots copied to a USB stick; one corrupt copy of `mt-de-zh-hans`; the German test utterance | Data prepared |
| S-01..S-04 | Record commit, Windows build, Python version, start time; place D-01, D-02; laptop online, free space recorded; VM with egress blocked and a checkout without `models\` and local settings | Values in `verification-report.md`; `Test-NetConnection huggingface.co -Port 443` fails on the VM |
| E-01 | Laptop first launch | Assistant *Set up Lianiq* on *What do you want to do?*; no connection before a click (AC-01, AC-03, AC-22) |
| E-02 | Assistant: usages, languages, audio check, readiness | Screenshots of the four steps (AC-04..AC-06, AC-29) |
| E-03 | **Get…**, licence, **Download** for all five packs; **Cancel** at ~30 % once, then **Retry** | All five *Validated*; manifest records with `licence_accepted_at`; no `models\.lianiq-staging` (AC-07..AC-09) |
| E-04 | **Finish**; Conversation **Start**, German utterance, **Stop** | Warm-up without percentage; Mandarin translation (AC-18, AC-20) |
| E-05 | Remove a pack during a session, after **Stop**, then re-import it from the stick | Refusal text, confirmation, *Downloadable*, then *Validated* with `source: import` (AC-15, AC-16) |
| E-06 | Relaunch | No assistant (AC-01) |
| E-07 | VM: launch, **Skip**, Language packs, **Download** one pack | Five *Downloadable*, the empty hint and "Download unavailable: no connection to …"; egress log shows only the attempts after the click (AC-13, AC-21, AC-28) |
| E-08 | VM: import the corrupt copy, then the five folders | Corrupt copy rejected by name; five *Validated*; no egress (AC-10, AC-11) |
| E-09 | VM: Conversation **Start**, German utterance, **Stop** | Mandarin translation with zero egress (AC-21, AC-28) |
| E-10 | Keyboard and Narrator through the assistant (**Run setup assistant**) and the Language packs page with one details dialog | No unnamed Tab stop (AC-26) |
| T-01..T-03 | Restore `models\` and the settings; delete the stick copies and the VM checkout; reset the VM snapshot | State as before |

Evidence goes into the capability's `verification-report.md` (screenshots by SHA-256 only; no
recordings, transcripts or endpoint IDs). A row without native evidence is blocked, never passed.
