# Native E2E UIA rows

The rows E-01, E-11, E-03 and E-10 of `python -m native_e2e run` drive the real Lianiq window
in the VM with UI Automation (pywinauto, `backend="uia"`) and the virtual cable (VB-Cable).
They run after C-04 and before E-12, inside the S-04 offline window, and only when S-01 passed
and S-03 recorded the settings backup. Setup, image build and run approval are in
[native-e2e-setup.md](native-e2e-setup.md).

## During a run

The rows click with the real mouse and type with SendInput. Do not use the VM console (mouse,
keyboard, window focus) between approval and the end of the job: a moved window or a click
makes a row fail. Rows wait for states with timeouts (20 s; 120 s for model readiness) and are
never retried.

## What each row does

| Row | Steps | Evidence |
|---|---|---|
| E-01 | Starts the app; reads the six sidebar entries, their order, selection, enabled state and description; checks that Conversation shows no Call Bridge control, Model profile, CUDA box or hardware subtitle; checks with psutil that no app process has a file under `models\` open or mapped before **Start** | Checks; `screens/e01-conversation.png` |
| E-11 | Writes `config/settings.local.json` from `native_e2e/data/legacy-settings.template.json` with `audio.input_device` set to the PortAudio index of "CABLE Output"; starts the app; waits for "Microphone set to '…' from your previous settings"; closes the app; reads the migrated keys | `name_matches` (never the name); `screens/e11-migration-notice.png` |
| E-03 | Checks the test phrase WAV against `image.json`; in Settings › Audio devices selects "CABLE Output" as Microphone; in Conversation unticks *Voice output*; **Start** (F8); plays the WAV into "CABLE Input"; waits for a turn in *Original* and *Translation* that two consecutive reads agree on; visits every enabled workspace; presses F9 in Settings; returns to Conversation | `name_matches` for the Microphone (never the name); transcript SHA-256 (never the text); `screens/e03-running.png`, `screens/e03-after.png` |
| E-10 | Settings › Diagnostics › **Export…**: types the path into the save dialog's file-name field (`AutomationId` 1148) and presses Enter, first to `%TEMP%\lianiq-e2e\diagnostics-E10.txt`, then into `%TEMP%\lianiq-e2e\ro\`, whose ACL denies the test user writes (`icacls`) | Forbidden pattern classes found (none on a pass); whether the second dialog closed (`dialog-closed`); `screens/e10-export-failed.png` |

E-03 leaves the app open for E-10, so the export holds that session's log. E-10 reads the
failure from the notice elements only: the notice history logs every posted notice title,
so the first export's "Diagnostics saved as …" line is always in it. A save dialog still
open is cancelled before the screenshot and the close. T-01 restores the settings file and T-03 resets the ACL of `%TEMP%\lianiq-e2e` and deletes it.

## Privacy of the evidence

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

Read the four rows in `native-evidence.json`: each is `pass`, E-03 and E-11 use the method
`automated-virtual-device`. Open the screenshots under `screens/`: every device name region
and both transcript panels are black rectangles. Run `python -m native_e2e verify <artifact-dir>`; it must pass.

## Troubleshooting

| Symptom | First thing to check |
|---|---|
| E-01 `sidebar-six-entries-in-order` fails with 0 entries | The window was not reachable through UI Automation: the app did not start, or the console session was locked |
| E-11 `migration-notice-shown` times out | The cable is missing or renamed (T-02 also fails), or the app did not read `settings.local.json` |
| E-03 `turn-in-original-and-translation` times out | Spec assumption 4: the German model did not recognise the Piper phrase through the cable |
| E-03 `microphone-cable-selected` or `voice-output-off` fails | The cable is missing from the Microphone list (T-02 also fails), or *Voice output* did not react to the click; the row does not press **Start** then |
| E-03 `scroll-unchanged` fails with `unreadable` | UI Automation gave no scroll value for a transcript panel or its scroll bar |
| E-10 `failure-notice-shown` fails with `dialog-closed: false` | The save dialog stayed open after Enter into `ro\` (a prompt or an error box over it); the row cancels it before the screenshot |
| E-10 `file-written` fails | The save dialog did not close after Enter (a prompt is open), or the file-name field was not found |
