# Native Windows Evidence Profile

This profile is the native Windows equivalent of a web journey-evidence gate. It
applies to a Lianiq Python/PySide6 delivered surface; browser navigation and HTTP
evidence are not substitutes for the native journey. Apply only rows relevant to
the changed or claimed mode, as required by the [Definition of Done](definition-of-done.md).

## Evidence record

Every product-verification record identifies the exact commit, package or
executable, Windows version, the user entry point, test account/data boundary, and
the operator. It records the observed result, evidence location, residual risks,
and any recovery action. Screenshots, video, sanitized logs, and repeatable steps
may support a record; their presence alone does not establish a pass.

## Native journey matrix

| Area | Required evidence | Pass condition |
| --- | --- | --- |
| Entry and state | Start from the normal packaged application entry point; navigate using the real controls. | The intended mode is discoverable and its current state is visible. |
| Approved UI contract | Compare the delivered surface with each applicable approved mockup or page specification golden sample. | Every deviation has recorded operator acceptance; otherwise the capability remains `iterating`. A draft mockup or draft PR is not approval. |
| Visible interaction states | Exercise ready, busy/loading, disabled, empty, success, actionable error, degradation, recovery, and stopped states that the scope provides. | Each state is understandable; an unsafe action is unavailable or rejected with an actionable explanation. |
| Focus and keyboard | Use keyboard-only navigation through relevant controls, including initial focus, tab order, activation, escape/stop, and focus after errors or dialogs. | No keyboard trap; focus remains visible and returns to a useful control. |
| Narrator | Exercise relevant controls and dynamic status with Windows Narrator. | Accessible names, roles, values, and state changes communicate the journey without relying only on color or sound. |
| DPI and window behavior | Exercise supported scaling, resize/minimize/restore, and multiple-monitor movement where supported. | Controls, text, error messages, and state remain usable; no hidden critical control or corrupted layout. |
| Lifecycle and stop | Start the applicable mode, then stop it during normal work and a pending/failed condition; close and reopen when relevant. | Workers, capture, playback, and UI state stop or recover safely. No background audio or stale activity persists. |
| Failure and recovery | Induce only safe, authorized failures such as a missing model, unavailable endpoint, or cancelled operation. | The app reports a useful state and recovers only through an explicit or safe path. |

Offscreen tests and deterministic UI checks may prove code behavior but cannot
replace this packaged native journey evidence.

## Mode extensions

### Conversation interpreting

Record a real two-person, consented utterance journey for each claimed direction.
Confirm source capture, transcript, directed translation, optional target playback,
visible progress and result/error state, interruption, and stop. Record the selected
model versions and whether the journey stayed offline.

### Text translation and translated speech

For text translation, enter representative source text for each claimed direction
and observe the target result and all visible input/result states. If translated
speech is claimed, invoke playback deliberately, verify the target-language voice,
then stop it. TTS/output failure must be silent and safe rather than falling back
to another output device.

### Listen & translate

Use the fixed source language and the explicitly selected capture endpoint. Verify
speech-to-text and translation appear in the intended panels without unintended
speech playback. Verify start, stop, endpoint loss, and recovery behavior.

### Experimental Call Bridge

The Call Bridge remains disabled by default and experimental until the exact
profile passes every production closure row in
[Call Bridge SystemOK Evidence](../call-bridge-system-ok.md):

1. the real-model self-test completes both lanes within three seconds;
2. the packaged executable resolves all four selected WASAPI/MMDevice pairs;
3. a two-cable loop proves separate TX/RX routing and isolation during a Windows notification;
4. physical virtual-cable and Bluetooth disconnect/reconnect either recovers the
   same stable identity or produces an actionable muted state; and
5. a consented real two-party German/Mandarin call passes the operator checklist
   for the recorded call-application profile.

Record the application and version, Windows build, driver, cable, headset, package,
model versions, and endpoint identity handling. A successful call applies only to
that recorded profile; it does not establish compatibility for another application,
application version, device, or hardware configuration. WeChat Desktop may be a
reference target but is not required for a different profile.

## Offline, privacy, and fail-closed proof

For every applicable runtime journey, show that model inference, translation, and
synthesis use the intended local assets and that no cloud request or undeclared
network dependency is required. Verify explicit endpoint selection. The Call Bridge
must never use a Windows default device or any implicit, silent, or unsafe endpoint
fallback; a normal Conversation mode may use a Windows default only when the user
explicitly selects it for that mode and the selection is visible. Missing, ambiguous,
changed, or unavailable Call Bridge endpoints must mute or stop the affected lane
without leaking audio into another lane. Evidence shared outside the operator record
must remain sanitized: no PCM, speech transcript, prompt content, endpoint display
name, or endpoint identifier.

## Current baseline

This document defines required evidence; it records no completed runtime evidence.
The current Call Bridge decision in
[Call Bridge SystemOK Evidence](../call-bridge-system-ok.md) remains **not
production SystemOK**. A future work order must attach fresh evidence for its exact
build and environment before it can claim `product verified` or `SystemOK`.
