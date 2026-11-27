# Call Bridge Operator Setup

## Status

The Call Bridge is experimental. It is an utterance-based translation path, not simultaneous
interpretation. Production SystemOK remains conditional on completing the packaged two-cable and
real-call checklist in this document. A passed route test checks one path only; it does not
certify a call setup.

## Prerequisites

- Windows 11 with microphone permission enabled for desktop applications.
- A headset or separate microphone/headphones visible as input and output endpoints.
- Two independent virtual audio cables installed from a trusted vendor.
- A desktop call application with independent microphone and speaker selection, for example
  WeChat Desktop.

Install virtual audio drivers separately. Do not change system-wide default devices. Do not
redistribute a driver with the interpreter until its license and signing requirements have been
reviewed.

## The two paths

The Call Bridge page has two path boxes. Each box has two device selectors that list the full
Windows display names, filtered to the side the role needs.

| Path | Role in Lianiq | Device to select | Call application setting |
|---|---|---|---|
| **You → call** | *Your microphone* | Headset microphone | Not selected |
| **You → call** | *Call microphone cable — playback side* | Cable A, playback side | Microphone = Cable A, recording side |
| **Call → you** | *Call speaker cable — recording side* | Cable B, recording side | Speaker = Cable B, playback side |
| **Call → you** | *Your headphones* | Headset headphones | Not selected |

The box titles name the languages of the session pair, for example
"You → call · German → Mandarin (Simplified)" and "Call → you · Mandarin (Simplified) → German".

### Generic two-cable example

A virtual cable has two sides: audio played into its **playback side** comes out of its
**recording side**. Use one cable per direction:

- **Cable A, the call microphone cable.** Lianiq plays the translation into Cable A's playback
  side; the call application records Cable A's recording side as its microphone.
- **Cable B, the call speaker cable.** The call application plays the remote voice into Cable B's
  playback side; Lianiq records Cable B's recording side and translates it into your headphones.

With VB-Audio-style naming, the playback side is named `CABLE Input` and the recording side
`CABLE Output`; a second cable has its own pair with a different name. The words describe the
cable, not the application role. Verify the level meters rather than relying only on the names.
Selecting the same cable for both paths is refused (see [Readiness list](#readiness-list)).

## Where the Call Bridge is in Lianiq

Start the packaged `lianiq.exe` (or `.\.venv\Scripts\python.exe -m lianiq`) and select
**Call Bridge** (marked "Experimental") in the left sidebar, or press **Ctrl+5**. The page shows:

- the note "Experimental. A passed test checks one path; it does not certify your call setup."
  with the *Real-call checklist* link, which opens this document locally;
- the **You → call** and **Call → you** boxes, each with its two selectors, a level meter
  (*Microphone level* or *Call audio level*), the lane status line, the route-test row and the
  collapsible *How to set up the call app* help;
- the readiness list *Before you can start*;
- the live text view;
- **Start call bridge** and **Stop call bridge**, which stay in view when the page scrolls.

Opening the page only lists the endpoints; no audio stream opens. The selectors are separate from
Settings › Audio devices, which sets the Conversation microphone and speakers only. The Call
Bridge never offers or uses a Windows default endpoint.

## Setup sequence

1. Connect the headset and confirm its microphone and headphones in Windows Sound settings.
2. Install two virtual cables from the vendor and reboot if required.
3. In **You → call**, select *Your microphone* and *Call microphone cable — playback side*
   (Cable A). In **Call → you**, select *Call speaker cable — recording side* (Cable B) and
   *Your headphones*. If a device was connected after Lianiq started, stop every session and
   press **Refresh** in Settings › Audio devices; it also re-reads the Call Bridge lists and keeps
   existing selections by identity.
4. Set up the call application (see [WeChat Desktop](#wechat-desktop)).
5. Run both [route tests](#route-tests).
6. When the readiness list is empty, press **Start call bridge** before joining or unmuting the
   call.
7. Confirm with the remote participant that only synthesized speech in the remote language is
   received. Do not represent the output as certified, simultaneous, or suitable for emergencies.

### Readiness list

Under the paths, *Before you can start* names everything still missing; **Start call bridge** is
enabled once nothing is. Examples:

- "Your microphone: select a device" or "Your headphones: device not found".
- "Call speaker cable — recording side: needs a recording device".
- "Your microphone and Your headphones use the same device".
- "Both call cables are the same virtual cable. Install a second cable and select it for one
  path."
- "Your microphone: several devices have this name — unavailable".
- A missing recognition, translation or voice pack, one line per item, with
  **Open Language packs**; "Preparing models…" while models warm up.
- While another session runs, **Start call bridge** is disabled with the tooltip
  "Stop the Conversation session first"; press **Stop (F9)** in the session strip first.

### Route tests

**Test** in a path box plays a test phrase on that path's playback device only: the remote
language into the call microphone cable, the local language into your headphones. The row shows
*Playing test…* with **Cancel**, then asks *Did your partner hear it?* (You → call) or
*Did you hear it?* (Call → you). **Yes** records *Test passed*; **No** records
*Test failed — check the call app's microphone setting* (or *speaker setting*). A playback error
shows *Test could not play: …*. Changing a device of that path, the pair or the local language
returns that path to *Not tested*. Tests are disabled while the bridge runs
("Stop the call bridge to test a path").

## WeChat Desktop

1. Open **WeChat › Settings › Audio**.
2. **Microphone:** select the recording side of the call microphone cable (Cable A).
3. **Speaker:** select the playback side of the call speaker cable (Cable B).
4. Do not select your headset in WeChat; Lianiq uses it directly.

The same two settings apply to any call application. Each path box repeats them under
*How to set up the call app*.

## During a call

- **Lane status.** Each path box shows its own lane: *Listening*, *Translating…*, *Speaking*,
  *Muted — <reason>*, *Device lost — <device>* or *Reconnecting…*; *Starting…* and *Stopped*
  around a session.
- **Level meters.** They move only while a stream is open (running or a route test). The caption
  shows *Signal*, *No signal for 5 s — …* with a hint, or *Too loud (clipping) — …* with the
  volume to lower.
- **Live text.** Each completed turn appears with its direction (**You → call** or
  **Call → you**), the original and the translation, newest at the bottom, at most 200 turns.
  The view is cleared at each Start and is never saved, logged, exported or shown in the
  Conversation transcript. Before the first turn it reads "Nothing translated yet."
- **Echo pause.** While a translation plays in your headphones, **You → call** reads
  *Paused while you hear the translation* and discards your microphone, so the bridge does not
  translate its own output.
- **Stop.** **Stop call bridge**, or **Stop (F9)** in the session strip from any workspace, stops
  both lanes and all playback and unlocks the selectors and tests. While the Call Bridge runs, the
  strip shows "Call Bridge running" in every workspace.
- **Device loss.** If an endpoint disappears, only the affected lane shows
  *Device lost — <device>* with a notice at the top of the page, for example
  "Call Bridge · You → call lane failed closed: Device lost — …" with "This lane is muted; the other lane
  continues." No default device is opened. The lane recovers (*Reconnecting…*, then *Listening*)
  only when the same device identity returns; otherwise stop and select the device again.

The notice history is in Settings › Diagnostics. For problems outside the Call Bridge, see
[Troubleshooting](troubleshooting.md).

Lianiq stores Windows MMDevice identities rather than numeric PortAudio indices. If Windows can no
longer map a saved identity after a driver reinstall, select the endpoint again; never replace it
with a default-device setting.

Export a redacted support snapshot without transcript, PCM, endpoint IDs, or endpoint names with:

```powershell
.\.venv\Scripts\python.exe .\scripts\call_bridge_diagnostics.py
```

In the application, Settings › Diagnostics **Copy** or **Export…** gives the notice history with
endpoint IDs, absolute paths and the Windows user name replaced and no transcript text. Unlike
the script above, it keeps device display names that appear in notice titles.

## Acceptance checklist

- [ ] Opening the page opens no audio stream; the readiness list names every missing device.
- [ ] Selecting one cable for both paths lists the same-cable reason and keeps Start disabled.
- [ ] Each route test plays only on its own path; Yes/No records the result.
- [ ] Local speech produces the remote language on the call microphone cable only.
- [ ] Remote speech produces the local language in the selected headphones only.
- [ ] Windows notification sounds do not reach the call microphone cable.
- [ ] While a translation plays in the headphones, You → call shows the echo pause.
- [ ] Disconnecting a device mutes only the affected lane instead of selecting a default device.
- [ ] Reconnecting the same device restores the lane or reports a clear error.
- [ ] Stop or F9 releases all four endpoints.
- [ ] In a real call, the partner hears only the remote language and you hear only the local
      language; the live text shows both directions.

## Bluetooth considerations

Some Windows and Bluetooth combinations switch to lower-quality mono audio while the headset
microphone is active. Bluetooth LE Audio stereo during microphone use requires support from
Windows, the computer's Bluetooth hardware and drivers, and the exact headset model.

If audio quality or stability is unacceptable:

1. update Windows and the computer manufacturer's Bluetooth drivers;
2. test the headset's available communication and stereo endpoint variants;
3. use a wired or USB connection if the headset supports it; or
4. use the headset only for playback and a separate USB microphone for capture.

## Windows audio troubleshooting matrix

Keep the Call Bridge stopped while changing device selections. A missing, ambiguous, or
wrong-side endpoint is an unsafe route: leave the affected lane muted until the selection and its
signal path are verified. Never substitute a Windows default device.

| Symptom | Deterministic software checks | Safe remediation | Evidence boundary |
|---|---|---|---|
| A selected endpoint is missing after reboot, reconnect, or driver update | Run `scripts/call_bridge_diagnostics.py`; confirm that the readiness list reports the role as not found rather than rebinding it to a numeric index or default device | Stop the bridge, reconnect the exact device, press **Refresh** in Settings › Audio devices while no session runs, and select it again. If Windows created a new identity, treat it as a new device | A successful inventory lookup proves identity resolution only. Repeat the route test and the disconnect/reconnect hardware gate |
| A virtual cable appears only on the wrong side | In Windows Sound settings, verify that the cable's playback side is paired with its recording side; the Lianiq selectors list only the side each role needs | Lianiq plays into the call microphone cable's playback side while the call application records its recording side; the call application plays into the call speaker cable's playback side while Lianiq records its recording side | Correct selection does not prove that the driver transports audio between the sides |
| The *Microphone level* or *Call audio level* does not move | Confirm the source is producing audio, the endpoint is not muted in Windows, and only the expected path meter moves | Stop the bridge, correct the source application's device, then run the route test before restarting. Do not enable listen/monitor loops to force meter activity | Meter movement proves signal arrival, not translation accuracy, latency, or remote-call delivery |
| The remote participant hears your original voice | Verify that the call application microphone is the call microphone cable's recording side, not the physical microphone or a Windows default | Mute or leave the call, select the cable explicitly, and repeat the You → call route test before unmuting | Only a two-party real call proves that the remote participant receives synthesized speech and no original microphone path |
| No remote audio reaches Lianiq | Verify that the call application speaker is the call speaker cable's playback side and Lianiq's *Call speaker cable — recording side* is the same cable | Select both sides of that cable explicitly; keep the bridge stopped until the Call → you meter and route test pass | Local playback and meter checks do not replace the application-specific real-call gate |
| Activity appears on the opposite path or the interpreter translates its own output | Compare every role with the two-path table; confirm the two cables are independent and Windows monitoring is disabled | Stop the bridge, remove crossed selections or external monitoring, and rerun both route tests | Readiness rejects duplicate devices and one cable for both paths but cannot detect every external mixer or driver loop |
| Audio stops after disconnect and does not resume after reconnect | Confirm the affected lane shows *Device lost — <device>*; verify the reappearing endpoint has the same identity | Reconnect the same endpoint and let the inventory check rebind that identity. If identity changed or is ambiguous, stop and select it again | Automatic recovery is acceptable only for the same identity; complete the packaged disconnect/reconnect gate before SystemOK |
| Remote hears Windows notification sounds | Check that the call microphone cable is not a system default output and no external mixer sends desktop audio into it | Remove the system-default or mixer route and repeat the You → call route test | A local test must still be followed by a real-call confirmation |
| Headset audio becomes mono | Check which Bluetooth communication profile Windows activated and whether the adapter, driver, and headset support LE Audio during microphone use | Update supported drivers, test documented endpoint variants, or use USB/wired playback or a separate microphone | This is a hardware/profile limitation, not a software pass or failure |
| Translation falls increasingly behind | Run the deterministic self-test and inspect sanitized dropped-work/latency categories; confirm the bounded queue and age limit are active | Stop the call, reduce host load, and use the validated model profile. Do not remove queue or age bounds to hide overload | Synthetic timing is diagnostic evidence only; packaged two-lane latency under a real call remains required |

The following checks are deterministic and safe to repeat without a call:

```powershell
.\.venv\Scripts\python.exe .\scripts\call_bridge_self_test.py
.\.venv\Scripts\python.exe .\scripts\call_bridge_diagnostics.py
```

They validate contracts, configuration, and sanitized diagnostics. They do not satisfy the
two-cable signal-isolation, packaged latency, disconnect/reconnect, or application-specific
two-party real-call gates in the acceptance checklist.

## Rollback

1. Press **Stop call bridge**, or **Stop (F9)** in the session strip.
2. Restore the physical headset as the call application's microphone and speaker if direct calling
   is required.
3. Close the interpreter.
4. Leave virtual cables installed but unused, or remove them using the vendor's supported
   uninstaller and reboot if instructed.

Rollback must not require editing the repository configuration or changing Windows system-wide
default devices.
