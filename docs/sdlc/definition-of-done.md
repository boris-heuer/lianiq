# Definition of Done

This definition is binding for Lianiq work orders. It applies the Software Factory
SystemOK objective to this local/offline, privacy-preserving Python/PySide6 Windows
product. It does not replace the product requirements in [Call Bridge SystemOK Evidence](../call-bridge-system-ok.md).

## Status vocabulary

Use the narrowest truthful status. The progressive delivery ladder is `draft` →
`implemented` → `code verified` → `product verified` → `SystemOK`; each later
progressive status requires the evidence of the preceding progressive statuses.
`iterating` and `blocked` are exception states, not ladder steps, and do not imply
that an earlier progressive status passed.

| Status | Meaning | It does not prove |
| --- | --- | --- |
| `draft` | Scope or proposed artifact exists. | Implementation, review, or acceptance. |
| `implemented` | The approved change is present in the branch. | Deterministic checks, user outcome, or runtime fitness. |
| `code verified` | Applicable deterministic checks and exact-head review evidence pass. | Packaged Windows behavior, hardware, language quality, or a real call. |
| `product verified` | The intended user journey passed on the delivered surface with the applicable native evidence profile. | SystemOK for another build, device, Windows version, language pair, or call application. |
| `SystemOK` | All applicable runtime and operational closure evidence is recorded for the named profile. | A general compatibility or production claim outside that profile. |
| `iterating` | Applicable product evidence is missing or failed, or a changed journey requires re-verification. | A prior `product verified` or `SystemOK` claim remains current. |
| `blocked` | An applicable gate lacks evidence or cannot be run. | `N/A`; report the blocker instead. |

Missing real-device, user, packaged-build, language, or call evidence is never a
pass and is never `N/A` merely because it is unavailable. Unit tests, offscreen UI
tests, mockups, and synthetic audio are code evidence; they do not establish runtime
SystemOK.

## Required closure record

A work order is Done only when its closure record names the owning
product/capability, source-of-truth path, acceptance criteria (ACs), dependencies,
delivery authority, and the evidence below.

1. **AC traceability.** Every applicable AC maps to changed files, a verification
   result, its exact commit and build/package identity, and any residual risk.
   Untested or failed ACs remain open.
2. **Change integrity.** The staged tree has an independent review at its exact
   tree hash (the exact tree hash is recorded in the review receipt). Applicable local checks and required CI pass on the reviewed PR head;
   a result for another commit does not satisfy this gate.
3. **Product verification.** A user or operator completes the intended journey on
   the real delivered surface. Visible, focus, loading, disabled, error, recovery,
   stop, accessibility, and supported-environment behavior are coherent. Native
   requirements are defined in the
   [Native Windows Evidence Profile](native-windows-evidence-profile.md). Where an
   approved mockup or page specification exists, compare the delivered UI with that
   golden sample. A deviation needs recorded operator acceptance; otherwise the
   capability remains `iterating`. A draft mockup or draft PR is not approved by
   implication.
4. **Safety and privacy.** The delivered scope preserves offline operation,
   privacy, explicit endpoint selection, and fail-closed audio routing. No cloud,
   implicit, silent, or unsafe endpoint fallback is introduced. The Call Bridge
   never selects a Windows default endpoint; a normal Conversation mode may use one
   only after the user explicitly selects it for that mode and the choice is visible.
   Failures leave the affected route muted, stopped, or otherwise visibly safe.
5. **Runtime evidence.** When the scope includes models, audio, hardware, a
   packaged executable, or a call application, record the applicable real evidence
   for that exact profile. Evidence for one profile does not transfer to another.
6. **Publication and merge.** The reviewed change is committed, published,
   merged through the protected workflow, and verified on the target branch.
   Cleanup is safe and the source-of-truth issue/work item reflects the result.
7. **Recovery.** Residual risks, rollback or recovery steps, and operational
   limits are documented before closure.

For an artifact-only work order, the applicable closure requirements are
schema/tool compatibility, ownership, non-contradiction, link integrity, and a
reproducible operator/document walkthrough. These replace product-verification and
runtime-evidence rows only when those rows are genuinely scope-based `N/A`; the
record must say why. An artifact-only work order does not certify the running
application. Actual runtime changes retain every applicable product and SystemOK
closure gate above.

## Mode applicability

The evidence must cover only the modes changed or claimed. It must not require
unrelated models, devices, or call hardware.

| Mode | Required product and runtime evidence when applicable |
| --- | --- |
| Conversation interpreting | A real two-party utterance journey proves capture, source recognition, directed translation, optional speech output, transcript/state updates, interruption/stop, and safe failure. |
| Text translation | A typed source-to-target journey proves translation, visible pending/error/empty states, copy or result handling, and source/target direction. |
| Text translation with translated speech | Text-mode evidence plus explicit user-requested playback, the correct target-language voice, stop behavior, and silent failure when synthesis or output is unsafe. |
| Listen & translate | A fixed-source speech-to-text journey proves the selected capture endpoint, transcript and translation updates, no unintended playback, and stop behavior. |
| Experimental Call Bridge | All closure rows in [Call Bridge SystemOK Evidence](../call-bridge-system-ok.md) apply. It remains experimental and disabled by default until its named profile passes them. |

## Language, offline, and hardware boundaries

For every claimed directed language path, record the independently applicable STT,
machine-translation, and TTS readiness. A German-to-Mandarin result does not prove
Mandarin-to-German, and text-only evidence does not prove STT or TTS. Functional
multilingual samples remain test data and may be multilingual; project artifacts and
operator records are English.

For a packaged or hardware-dependent claim, record the package identity, Windows
build, model versions, selected endpoint identities, device/driver and virtual-cable
versions, and privacy/offline observations. Do not log PCM, transcript content,
endpoint display names, or endpoint identifiers in shared diagnostics.

## Blocking and `N/A`

`N/A` requires a concrete, scope-based explanation of why the requirement cannot
apply. Lack of a device, model, operator, environment, call peer, or time is a
blocker. A blocker record must state:

- cause;
- impact on the work order and claimed status;
- responsible actor; and
- exact unblock action.

Questions and decisions are routed to the originating operator chat, never to a
separate agent chat. No historical approval, review, runtime pass, or SystemOK
result may be inferred or fabricated.
