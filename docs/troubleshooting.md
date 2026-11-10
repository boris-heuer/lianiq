# Troubleshooting

This guide covers the desktop shell of the source build (`python -m lianiq` or
`python run_app.py`): the sidebar, the session strip, notices, Settings › Audio devices and
Settings › Diagnostics. For the experimental Call Bridge routes, use the
[Windows audio troubleshooting matrix](call-bridge-operator-setup.md#windows-audio-troubleshooting-matrix)
in the operator setup.

## Where Lianiq reports a problem

- **Notices.** Each failure is a persistent notice at the top of the workspace it belongs to.
  It says what failed, for which mode, lane and language, whether recording and playback
  continue, and what to do. Its label starts with *Action needed* (blocking), *Warning* or
  *Information*. A blocking notice stays until its cause is resolved; a warning or information
  notice can also be closed with **Dismiss**. Repeats update one notice instead of stacking.
  **+N more** opens the notice history in Settings › Diagnostics.
- **Status bar.** It shows readiness and progress only, for example the missing items that keep
  **Start** disabled.
- **Settings › Diagnostics.** Model profile, compute device, a readiness summary of the selected
  pair (Conversation, Voice output, Call Bridge) and the notice history with **Copy** and
  **Export…**.

## Start is disabled or refused

| What you see | Cause | What to do |
|---|---|---|
| **Start (F8)** is disabled and the status bar says `Not available: missing …` | A model, voice or device the selected mode needs is missing | Run `.\.venv\Scripts\python.exe .\scripts\doctor.py`; provision what it reports with `scripts\setup.ps1` or `scripts\download_models.py`. A missing voice only disables **Voice output**; text output still works |
| A Start button is disabled with the tooltip `Stop the Conversation session first` (or `Stop the Call Bridge session first`) | Only one session runs at a time | Press **Stop (F9)** in the session strip, then start the other mode |
| A blocking notice `<name> — unavailable` with **Choose device**, and "Recording has not started." | The saved microphone or speakers are not connected | Connect the device and press **Refresh** in Settings › Audio devices, or press **Choose device** and pick another one. Lianiq never switches to another device by itself |
| A device is listed greyed out as `<name> — This device has no usable input channels` (or output) | The endpoint has no channel for that direction | Choose another device; an unusable device cannot be started |
| Text translation, Listen & translate and Language packs cannot be opened | They are planned entries ("Planned — not available yet") | Nothing to fix; they are not available in this version |

## Audio devices

Settings › Audio devices lists **Microphone** and **Speakers**. The first entry,
`Follow Windows default (now: <name>)`, uses the current Windows default; any other entry is
remembered by device identity, so a reordered or replugged device stays selected. Tooltips show
the full name, host API and channel count, never an endpoint ID.

| What you see | What to do |
|---|---|
| A headset plugged in after Lianiq started is not listed | Stop any session, then press **Refresh**. While a session or a device test runs, **Refresh** only reports the change (`Audio devices changed: …`) and the lists refresh after **Stop** |
| `No signal from '<name>'. Check mute or choose another microphone.` | **Test microphone** heard nothing for 3 s, or a running conversation heard nothing for 10 s. Check the hardware mute switch and the Windows input level, or choose another microphone |
| **Test speakers** played no tone | Answer **No**; the hint "Reconnect the device, or choose another one." appears. Check the Windows output level or choose other speakers |
| `Microphone '<name>' disconnected. Recording stopped. Your transcript is kept.` | The session stopped and does not restart on its own. Replug the device and press **Reconnect** (it reselects the same device), then **Start**; or press **Choose device** |
| `Speakers '<name>' disconnected. Spoken output stopped; translations still appear as text.` | The conversation continues as text. **Reconnect** is disabled with "Available after Stop" while capture runs; press **Stop (F9)**, replug, then **Reconnect** |
| `Windows default microphone is now '<name>'` after **Refresh** | Information only: the entry that follows the Windows default now uses that device |
| `Microphone set to '<name>' from your previous settings` (or Speakers) | An older settings file chose the device by list position. Lianiq matched it by name once; check the choice. If the name was ambiguous or missing, the entry shows `— unavailable`; choose the device again |

**Test microphone** and **Test speakers** are disabled while a session runs.

## Window size, scaling and accessibility

- Lianiq opens at 1280×720, or at the largest size that fits the screen's work area. On a small
  screen or with large text, the workspace scrolls or wraps its rows; **Start**, **Stop** and the
  session strip stay in view.
- Below 1000 px window width the sidebar becomes an icon rail. The labels move to the tooltips;
  the accessible names stay the same. **Ctrl+1** … **Ctrl+6** select the sidebar entries in
  order (planned entries are ignored).
- Text sizes follow Windows text scaling ("Make text bigger") and display scaling. With Windows
  high contrast on, Lianiq uses the system colours instead of its own.
- **Tab** moves sidebar → workspace → session strip. Every focused control shows a 2 px outline.
  A notice change is announced through the banner's accessible name and description; it never
  moves keyboard focus.

## Diagnostics export

**Copy** and **Export…** in Settings › Diagnostics produce the same local text. Endpoint IDs
become `<endpoint-N>`, absolute paths become `<path>/<last component>`, your home folder becomes
`~` and your Windows user name becomes `<user>`; transcript text is never recorded. Nothing is
sent anywhere. Notice titles are recorded as shown, so device display names (for example in
`Microphone '<name>' disconnected.`) stay in the text; review it before you share it.

- A cancelled dialog keeps the log and writes nothing ("Export cancelled. Nothing was written;
  the log is kept.").
- A folder you cannot write to shows `Export failed: <reason>. Nothing was lost; try another
  folder.` with **Retry**; no "saved" notice appears.

`logs\lianiq.log` and `logs\native-crash.log` are local application logs. They contain no
audio, but they are not redacted (for example, model paths are absolute). Share the Diagnostics
export instead of the raw logs.

## Settings file

Runtime choices are saved to the ignored `config/settings.local.json` (settings schema v2). The
devices are stored in six keys: `audio.input_policy`, `audio.output_policy`,
`audio.input_endpoint_id`, `audio.output_endpoint_id`, `audio.input_device_name` and
`audio.output_device_name`. Saving sets the older index keys `audio.input_device` and
`audio.output_device` to `null`.

- **Downgrade.** A Lianiq build older than these keys fails to load the file. Delete the six keys
  from `config/settings.local.json` before you run an older build.
- **Do not share** `config/settings.local.json`: it contains private Windows endpoint IDs.

## Screenshots for a bug report or evidence

`scripts/capture_readme_screenshot.py --evidence <folder>` opens the window with generic devices
(*Microphone*, *Speakers*) and ready-reporting models, so no real device, model file or
transcript is shown. It writes one PNG per enabled workspace (Conversation, Call Bridge,
Settings) at 850×560, 1120×720, 1280×720 and 1440×900 into that local folder, named
`<workspace>-<width>x<height>@<scale>x.png`, and prints one `<sha256>  <file>` line per PNG:

```powershell
.\.venv\Scripts\python.exe .\scripts\capture_readme_screenshot.py --evidence "$env:TEMP\lianiq-evidence"
```

`<scale>` is the device pixel ratio: the Windows display scaling of the screen times
`QT_SCALE_FACTOR` (the script sets it to 1 unless you set it), so runs at different display
scalings can share one folder. Windows text scaling does not change `<scale>`: use a separate
folder for a text-scaling run, or it overwrites the screenshots of the run at the same display
scaling. Keep the screenshots local and record their SHA-256 lines; do
not attach transcripts, recordings or endpoint IDs to a report.
