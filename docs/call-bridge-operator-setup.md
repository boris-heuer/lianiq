# Call Bridge Operator Setup

## Status

The Call Bridge is experimental and disabled by default. It is an utterance-based translation path,
not simultaneous interpretation. Production SystemOK remains conditional on completing the packaged
two-cable and real-call checklist in this document.

## Prerequisites

- Windows 11 with microphone permission enabled for desktop applications.
- A headset or separate microphone/headphones visible as input and output endpoints.
- Two independent virtual audio cable pairs installed from a trusted vendor.
- A desktop call application with independent microphone and speaker selection, or a Windows
  per-application endpoint preference that demonstrably produces the same mapping.

Install virtual audio drivers separately. Do not change system-wide default devices unless the
call application cannot select devices explicitly. Do not redistribute a driver with the
interpreter until its license and signing requirements have been reviewed.

## Required endpoint mapping

| Role | Interpreter setting | Call application setting |
|---|---|---|
| Local speech source | Selected headset microphone | Not selected |
| Translated call microphone | TX cable playback endpoint | Paired TX cable recording endpoint |
| Remote call speaker | Paired RX cable recording endpoint | RX cable playback endpoint |
| Local translated playback | Selected headphones | Not selected |

For VB-Audio-style naming, the playback side is commonly named `CABLE Input` and the paired
recording side is named `CABLE Output`. The words describe the cable, not the application role.
Always verify the signal meters rather than relying only on the names.

## Setup sequence

1. Connect the chosen headset and confirm its microphone and headphones independently in Windows
   Sound settings.
2. Install two virtual cable pairs from the vendor and reboot if required.
3. In the interpreter's call-bridge panel, assign all four endpoint roles.
4. Run the outbound route test. A test phrase must move the TX meter and must not play locally.
5. Run the inbound route test. A test phrase injected into RX must play only in the selected
   headphones.
6. In the call application, select the TX recording endpoint as microphone.
7. In the call application, select the RX playback endpoint as speaker.
8. Start call-bridge mode before joining or unmuting the call.
9. Confirm with the remote participant that only Mandarin synthesized speech is received. Do not
   represent the output as certified, simultaneous, or suitable for emergencies.

The panel stores Windows MMDevice identities rather than numeric PortAudio indices. If Windows can
no longer map a saved identity after a driver reinstall, select the endpoint again; never replace
it with a default-device setting.

Export a redacted support snapshot without transcript, PCM, endpoint IDs, or endpoint names with:

```powershell
.\.venv\Scripts\python.exe .\scripts\call_bridge_diagnostics.py
```

## Acceptance checklist

- [ ] Selected microphone meter moves only on the outbound lane.
- [ ] Remote call-application audio meter moves only on the inbound lane.
- [ ] German speech produces Mandarin on the call-application microphone meter.
- [ ] Mandarin speech produces German in the selected headphones.
- [ ] Windows notification sounds do not reach the call-application microphone.
- [ ] The original remote Mandarin audio is not mixed with German unless monitoring is explicitly
      enabled.
- [ ] Disconnecting either virtual cable stops the affected route instead of selecting a default
      device.
- [ ] Reconnecting the selected headset restores the configured stable endpoint or reports a clear
      error.
- [ ] Stopping call-bridge mode releases all four endpoints.

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

Keep call-bridge mode stopped while changing endpoint assignments. A missing, ambiguous, or
wrong-direction endpoint is an unsafe route: leave the affected lane muted until the explicit
assignment and its signal path are verified. Never substitute a Windows default device.

| Symptom | Deterministic software checks | Safe remediation | Evidence boundary |
|---|---|---|---|
| A configured endpoint is missing after reboot, reconnect, or driver update | Run `scripts/call_bridge_diagnostics.py`; confirm that the saved role is reported unavailable rather than rebound to a numeric index or default device | Stop the bridge, reconnect the exact device, refresh the inventory, and explicitly select its stable endpoint again. If Windows created a new identity, treat it as a new device | A successful inventory lookup proves identity resolution only. Repeat the isolated route test and the disconnect/reconnect hardware gate |
| A virtual cable appears only on the wrong capture/render side | In Windows Sound settings, verify that the cable's playback endpoint (generic example: `TX playback`) is paired with its recording endpoint (`TX recording`). Check that the lianiq role selector exposes only the required flow | Reassign the lane using the paired endpoints: lianiq renders to TX playback while the call application captures TX recording; the call application renders to RX playback while lianiq captures RX recording | Correct capabilities and assignment validation do not prove that the driver transports audio between the pair |
| The selected microphone or RX input level does not move | Confirm the application holding the source is producing audio, the relevant endpoint is not muted in Windows, and the expected lianiq lane meter is the only meter moving | Stop the bridge, correct the source application's explicit endpoint, then run the isolated route test before restarting. Do not enable listen/monitor loops to force meter activity | Meter movement proves signal arrival, not translation accuracy, latency, or remote-call delivery |
| The remote participant hears the original German voice | Verify that the call application microphone is the paired TX recording endpoint and not the physical microphone or a Windows default | Mute or leave the call, select TX recording explicitly, and repeat the outbound route test before unmuting | Only a two-party real call proves that the remote participant receives synthesized Mandarin and no original microphone path |
| No remote audio reaches lianiq | Verify that the call application speaker is RX playback and lianiq's call-speaker input is the paired RX recording endpoint | Select both sides of the RX pair explicitly, keep the inbound lane muted until its meter and isolated playback test pass | Local playback and meter checks do not replace the application-specific real-call inbound acceptance gate |
| TX and RX activity appears on the opposite lane or the interpreter translates its own output | Compare every role with the required endpoint-mapping table; confirm TX and RX pairs are independent and Windows monitoring is disabled | Stop the bridge, remove crossed assignments or external monitoring, and rerun both isolated route tests | Software role validation rejects duplicate identities but cannot detect every external mixer or driver loop |
| Audio stops after disconnect and does not resume after reconnect | Confirm the affected lane reports endpoint loss and remains muted; verify the reappearing endpoint has the same stable identity | Reconnect the same endpoint and allow the inventory check to rebind that identity. If identity changed or is ambiguous, stop and select it again manually | Automatic recovery is acceptable only for the same stable identity; complete the packaged disconnect/reconnect gate before SystemOK |
| Remote hears Windows notification sounds | Check that TX playback is not a system default output and no external mixer sends desktop audio into TX | Remove the system-default or mixer route and repeat the outbound isolation test | A local isolation test must still be followed by a real-call confirmation |
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

1. Stop call-bridge mode.
2. Restore the physical headset as the call application's microphone and speaker if direct calling
   is required.
3. Close the interpreter.
4. Leave virtual cables installed but unused, or remove them using the vendor's supported
   uninstaller and reboot if instructed.

Rollback must not require editing the repository configuration or changing Windows system-wide
default devices.
