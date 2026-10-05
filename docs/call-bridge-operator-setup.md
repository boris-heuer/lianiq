# Call Bridge Operator Setup

## Status

Proposed setup for the planned call-bridge feature. The current application does not yet expose
these controls. Keep this document aligned with the implementation as it is delivered.

## Prerequisites

- Windows 11 with microphone permission enabled for desktop applications.
- Bose headset paired and visible as input and output endpoints.
- Two independent virtual audio cable pairs installed from a trusted vendor.
- WeChat desktop with access to microphone and speaker selection, or a Windows per-application
  endpoint preference that produces the same mapping.

Install virtual audio drivers separately. Do not change system-wide default devices unless the
call application cannot select devices explicitly. Do not redistribute a driver with the
interpreter until its license and signing requirements have been reviewed.

## Required endpoint mapping

| Role | Interpreter setting | WeChat setting |
|---|---|---|
| Local speech source | Bose microphone | Not selected |
| Translated call microphone | TX cable playback endpoint | Paired TX cable recording endpoint |
| Remote call speaker | Paired RX cable recording endpoint | RX cable playback endpoint |
| Local translated playback | Bose headphones | Not selected |

For VB-Audio-style naming, the playback side is commonly named `CABLE Input` and the paired
recording side is named `CABLE Output`. The words describe the cable, not the application role.
Always verify the signal meters rather than relying only on the names.

## Planned setup sequence

1. Connect the Bose headset and confirm its microphone and headphones independently in Windows
   Sound settings.
2. Install two virtual cable pairs from the vendor and reboot if required.
3. In the interpreter's call-bridge panel, assign all four endpoint roles.
4. Run the outbound route test. A test phrase must move the TX meter and must not play on Bose.
5. Run the inbound route test. A test phrase injected into RX must play only on Bose.
6. In WeChat, select the TX recording endpoint as microphone.
7. In WeChat, select the RX playback endpoint as speaker.
8. Start call-bridge mode before joining or unmuting the call.
9. Confirm with the remote participant that only Mandarin synthesized speech is received.

## Acceptance checklist

- [ ] Bose microphone meter moves only on the outbound lane.
- [ ] Remote WeChat audio meter moves only on the inbound lane.
- [ ] German speech produces Mandarin on the WeChat microphone meter.
- [ ] Mandarin speech produces German in the Bose headphones.
- [ ] Windows notification sounds do not reach the WeChat microphone.
- [ ] The original remote Mandarin audio is not mixed with German unless monitoring is explicitly
      enabled.
- [ ] Disconnecting either virtual cable stops the affected route instead of selecting a default
      device.
- [ ] Reconnecting the Bose headset restores the configured stable endpoint or reports a clear
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
4. use Bose only for playback and a separate USB microphone for capture.

## Troubleshooting boundaries

| Symptom | First check |
|---|---|
| Remote participant hears the original German voice | WeChat is still using the Bose microphone |
| No remote audio reaches the interpreter | WeChat speaker is not assigned to the RX playback endpoint |
| Remote hears Windows sounds | TX cable is configured as a system default output or is being mixed externally |
| Interpreter translates its own output | TX and RX cable roles are crossed or externally monitored |
| Device selection changes after reboot | Persisted runtime index was used instead of stable endpoint identity |
| Bose audio becomes mono | Bluetooth communication profile or missing LE Audio support |
| Translation falls increasingly behind | Queue-age limit or model scheduling is not enforcing bounded latency |

## Rollback

1. Stop call-bridge mode.
2. Restore Bose as WeChat microphone and speaker if direct calling is required.
3. Close the interpreter.
4. Leave virtual cables installed but unused, or remove them using the vendor's supported
   uninstaller and reboot if instructed.

Rollback must not require editing the repository configuration or changing Windows system-wide
default devices.
