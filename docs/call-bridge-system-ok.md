# Call Bridge SystemOK Evidence

## Decision

The automated design gates pass, but the implementation is **not production SystemOK**.
Deterministic routing, failure isolation, compatibility, privacy, observability, and UI
reachability are implemented and covered by automated tests. Production closure is intentionally
blocked until the same packaged build passes the two-cable and real-call operator rows on the
target Windows machine.

## User-reachable surface inventory

| Surface | Reachable path | Safety gate |
|---|---|---|
| Enable call bridge | Main window → Full-duplex call bridge → Enable | Disabled by default |
| Four endpoint selectors | Same panel | Capture/render role validation, all roles required, IDs unique |
| Start/stop | Same panel | Start rejects incomplete/unsafe mapping; stop releases both streams and workers |
| Outbound route test | Same panel → Test Mandarin → call mic | Explicit action; targets only configured TX render endpoint |
| Inbound route test | Same panel → Test German → headphones | Explicit action; targets only configured local render endpoint |
| State and levels | Same panel | Shows lane levels and stopped/running/degraded state without speech content |
| Redacted diagnostics | `scripts/call_bridge_diagnostics.py` | Excludes endpoint IDs, display names, transcript, prompts, and PCM |

## Quality characteristics

| Characteristic | Evidence | Status |
|---|---|---|
| Correct routing | Fixed-language `TranslationLane`, explicit output adapter, CB-01–CB-05 tests | Pass |
| No implicit direction change | Language is a construction-time lane contract; consecutive-turn tests | Pass |
| Fail closed | No default device is accepted; synthesis/output errors remain silent; endpoint loss mutes lane | Pass |
| Full-duplex lifecycle | Controller starts/stops both lanes and capture ports; stop-under-load contract is tested | Pass |
| Bounded latency | Bounded queues, stale-age rejection, scheduler, per-stage metrics | Pass for mechanism; target latency pending real-model/package evidence |
| Format tolerance | Deterministic stereo downmix, clipping, partial-frame handling, 48→16 kHz conversion | Pass |
| Stable selection | Native Windows MMDevice identity persisted; runtime WASAPI index re-resolved; ambiguity rejected | Pass on current Windows endpoint inventory |
| Recovery | Two-second inventory reconciliation restores only the same stable identity | Pass in deterministic tests; physical disconnect row pending |
| Privacy | No PCM/transcript logging; redacted diagnostic schema has a leakage regression test | Pass |
| Backward compatibility | Call bridge has a separate disabled-by-default config section; legacy conversation suite remains required | Pass |
| User reachability | Main window exposes selectors, state, level, start/stop, and route tests | Pass in offscreen UI tests |
| Reversibility | Stop releases endpoints; feature can be disabled without changing Windows defaults | Pass in code; packaged operator row pending |

## Adversarial route sweep

| Scenario | Automated evidence | Result |
|---|---|---|
| CB-01 / CB-02 one-way routing | Translation-lane and sink-isolation tests | Pass |
| CB-03 / CB-04 consecutive same-direction turns | Per-lane ordered queue test | Pass |
| CB-05 simultaneous lanes | Barrier-based two-lane test | Pass |
| CB-06 short acknowledgement | Existing segmenter minimum-speech regression coverage | Pass |
| CB-07 48 kHz stereo input | Resampler and real callback-handoff tests | Pass |
| CB-08 queue pressure | Overflow and stale-age drop-event test | Pass |
| CB-09 endpoint loss | Controller degradation and unaffected-lane test | Pass |
| CB-10 new runtime index | Native identity recovery/rebind test | Pass |
| CB-11 unrelated Windows sound | Only explicitly selected capture stream can submit lane audio | Pass by construction; physical notification test pending |
| CB-12 TTS failure | Fail-closed synthesis test | Pass |
| CB-13 stop under load | Worker shutdown and controller lifecycle tests | Pass |
| CB-14 existing conversation mode | Full repository test suite | Required on every closure run |

## Production closure gates

Run these against the packaged executable and attach the outputs/checklist before changing the
decision to `SystemOK`:

1. `scripts/call_bridge_self_test.py` passes both real-model lanes within three seconds.
2. The packaged executable resolves all four selected WASAPI/MMDevice pairs.
3. A two-cable loop test proves TX and RX isolation, including a Windows notification.
4. Physical cable and Bluetooth disconnect/reconnect recover or produce an actionable muted state.
5. A real two-party German/Mandarin call using the application named in the compatibility profile
   passes every operator checklist row. WeChat Desktop is the current reference target, not a
   prerequisite for certifying a different application profile.

This gate can establish evidence only for the recorded call application, Windows, driver,
virtual-cable, and headset profile. It does not certify another application, application version,
or headset. Each claimed profile must pass the application-specific acceptance defined in
[`call-bridge-compatibility.md`](call-bridge-compatibility.md).

Windows documents endpoint IDs as unique and stable across restart and USB replug, while noting
that driver reinstall can change them. Windows 11 24H2 also exposes the more durable
`PKEY_AudioEndpoint_StableId`; adopting that property is the trigger if driver-update continuity
becomes a product requirement:

- <https://learn.microsoft.com/windows/desktop/CoreAudio/endpoint-id-strings>
- <https://learn.microsoft.com/windows/win32/coreaudio/pkey-audioendpoint-stableid>
