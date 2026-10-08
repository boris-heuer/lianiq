# Call Bridge Compatibility

## Status

Last reviewed: 2026-10-08.

The Call Bridge is experimental and disabled by default. It does not claim universal headset or
communication-application support. No call application is production `SystemOK` until the packaged
build passes the application-specific real-call acceptance described below.

## Compatibility terms

The project uses these terms deliberately:

- **Design-compatible** means the documented device model can provide the four endpoint roles that
  the Call Bridge requires. It is an architecture assessment, not execution evidence.
- **Tested** means the packaged lianiq build completed the isolated two-cable checks and a real
  two-party call with the recorded application, application version, Windows build, audio driver,
  and headset.
- **SystemOK** means every production closure gate in
  [`call-bridge-system-ok.md`](call-bridge-system-ok.md) passed for that exact supported profile.
- **Unsupported** means the application cannot provide the required independent microphone and
  speaker mapping, or Windows cannot expose safe and unambiguous endpoints.

A pass for one application, version, Windows build, driver, or headset does not certify another.

## Required audio contract

A compatible profile must provide the complete path without using an implicit Windows default:

1. physical headset microphone captured by lianiq;
2. lianiq outbound Mandarin rendered to the TX cable playback endpoint;
3. the call application microphone set to the paired TX cable recording endpoint;
4. the call application speaker set to the RX cable playback endpoint;
5. lianiq inbound capture set to the paired RX cable recording endpoint; and
6. lianiq German playback rendered only to the physical headset output.

The call application must expose independent microphone and speaker selection, or an equivalent
Windows per-application configuration must demonstrably produce the same fixed mapping. An
application that forces a single combined audio device, ignores its selected endpoint, or can use
only system defaults is not safely supported.

## Communication-application matrix

| Application | Design assessment | Current evidence | SystemOK | Required next evidence |
|---|---|---|---|---|
| WeChat Desktop | Compatible in principle and the reference acceptance target | Deterministic software gates only; packaged two-cable and real-call rows remain open | No | Complete every operator checklist row in a real German/Mandarin two-party call |
| Microsoft Teams desktop | Compatible in principle when its separate Speaker and Microphone selectors expose both cable endpoints | No lianiq real-call evidence | No | Record the installed Teams version and complete the full application acceptance profile |
| WhatsApp for Windows | Conditional; public documentation confirms microphone and audio-output use but does not establish the required independent endpoint mapping for every version | No lianiq real-call evidence | No | Confirm both cable endpoints are independently selectable, then complete the full profile |
| Telegram Desktop | Conditional; call-device behavior and Windows microphone access must be verified for the installed version | No lianiq real-call evidence | No | Confirm both cable endpoints and microphone permission, then complete the full profile |
| Other desktop call applications | Conditional on the required audio contract | No lianiq real-call evidence | No | Prove the audio contract before starting the full profile |

The matrix reports lianiq evidence, not a general quality judgment about any third-party product.
Third-party interfaces and device behavior may change independently of this repository.

Application documentation consulted for the design assessment:

- [Microsoft Teams device settings](https://support.microsoft.com/en-us/teams/notifications-settings/manage-your-device-settings-in-microsoft-teams)
- [WhatsApp for Windows requirements](https://faq.whatsapp.com/451924530376167/?cms_platform=windows-desktop)
- [Telegram Desktop issue tracker: historical output-device selection behavior](https://github.com/telegramdesktop/tdesktop/issues/8435)
- [Telegram Desktop issue tracker: Windows microphone-permission report](https://github.com/telegramdesktop/tdesktop/issues/31356)

Issue reports are risk signals, not proof that every current Telegram installation is affected.

## Headset compatibility

The Call Bridge is headset-brand-agnostic, but it cannot guarantee every device. A usable headset
profile must:

- appear in Windows 11 as usable capture and playback endpoints;
- provide native endpoint identities that lianiq can resolve unambiguously;
- permit simultaneous microphone capture and translated playback;
- retain the selected identity across the acceptance scenario or fail closed when it changes; and
- meet the measured audio-quality and latency threshold for the supported profile.

| Headset profile | Design assessment | Principal risk |
|---|---|---|
| Wired or USB headset | Compatible in principle | Driver replacement, ambiguous endpoints, or exclusive access can still invalidate the profile |
| Bluetooth Classic headset | Conditional | Activating the microphone can switch playback to a lower-quality mono/telephony profile |
| Bluetooth LE Audio headset | Conditional | Stereo during microphone use depends on Windows, adapter, driver, and headset support |
| Separate microphone and headphones | Compatible in principle | Acoustic leakage and incorrect endpoint assignment require explicit isolation checks |

## Application-specific acceptance profile

Before marking an application `Tested` or `SystemOK`, record the application version, Windows build,
headset model and connection type, virtual-cable product and version, and lianiq commit. Then verify:

1. the application exposes the paired TX recording endpoint as its microphone;
2. the application exposes the RX playback endpoint as its speaker;
3. outbound German produces synthesized Mandarin remotely without leaking the physical microphone;
4. remote Mandarin produces German only in the selected local headset;
5. TX and RX remain isolated and Windows notifications do not enter TX;
6. the supported latency target passes under both active lanes;
7. virtual-cable and headset disconnect/reconnect either recover the same stable identity or leave
   the affected lane safely muted with an actionable error; and
8. application restart and system restart preserve or safely reject the configured mapping.

Attach the completed operator checklist and sanitized diagnostics to the evidence record. Automated
tests, visible meters, or a successful model self-test cannot replace the real two-party call.

## Maintenance rule

Change a matrix row only with evidence for the named profile. If an application update changes its
device controls or invalidates routing, return the row to `Conditional` or `No` until the acceptance
profile passes again. Do not use `supported`, `certified`, or `SystemOK` as synonyms for
design-compatible.
