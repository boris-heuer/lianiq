# Multilingual-ready Lianiq UI proposal

Status: **Draft for operator design review**, 2026-10-08. This package implements a
clickable design preview only. It does not change the Qt application, provision models,
add language support, or prove audio routing, latency, accessibility or SystemOK.

## Open the mockups

Open [index.html](index.html) locally, or serve this folder:

```powershell
.\.venv\Scripts\python.exe -m http.server 8765 --bind 127.0.0.1 --directory docs/ui/target
```

Then open `http://127.0.0.1:8765/`. No build, CDN, font download or network service is
required. The server is loopback-only. Copy uses the browser clipboard when permitted;
all audio, device tests, provisioning and export operations are explicitly simulated.

The Scenario selector is a review control outside the proposed application shell.
It exposes eleven states across four primary surfaces:

| Surface | Preview states | Design intent |
|---|---|---|
| Conversation | Listening, ready/empty, loading, translating, speaking, device lost | Paired turns dominate the screen; capture state is explicit |
| Call Bridge | Setup, active, incoming lane muted | Two understandable routes with independent health |
| Language packs | Ready, missing voice, unvalidated language/direction | Show capabilities rather than a misleading supported-language list |
| Settings / first run | Choose languages, check audio, review readiness | A short path to the first successful turn |

Static previews are in the [gallery](gallery.md). They show synthetic text and generic
devices. Use the HTML to explore the states; GitHub displays the HTML source rather than
executing it. The local browser preview is reviewable design intent, not native Qt evidence.

## Product and interaction contract

- Desktop-first landscape layout: persistent left sidebar, Settings at the bottom, and a wide workspace. At smaller widths the sidebar becomes an accessible icon rail, never top tabs. Primary review sizes are 1440x900 and 1280x720; smaller windows are resilience checks.
- Retain the dark, restrained visual identity. Use the transcript as the primary workspace.
- Separate Conversation, experimental Call Bridge, Language packs and Settings. Stop must
  remain accessible across the real app while a session is active. The preview switches
  illustrative screens; it is not a production navigation/session controller.
- English UI copy is independent of conversation languages. Do not use flags as language
  identifiers. Show native names as a useful secondary label.
- Conversation uses **one selected pair**, with automatic detection within that pair or
  explicit fixed-source mode. More than two simultaneous conversation languages are out of
  scope. English, Spanish and French are future examples, not supported-model promises.
- A direction is available only with validated recognition and directed MT capabilities.
  Reverse support is not inferred. Voice readiness is evaluated separately. No implicit
  pivot translation or cloud fallback is introduced.
- The preview's fixture matrix contains de↔zh and en↔es text directions; Spanish has a
  missing voice, and French has no validated direction. Other combinations are blocked.
  These fixtures do not describe the actual machine or shipping application.
- Call Bridge assigns the user's language to outbound recognition and the partner's to
  inbound recognition. Both lanes keep their configured directions for the entire session.
  Both output voices must be ready; text-only mode is an in-person option.
- Stop before changing a pair, devices or bridge profile. Queued work retains its original
  source/target metadata and cannot leak into a newly selected pair.
- Empty copy invites Start, listening copy invites speech, and speaking explicitly says
  microphone paused. Do not conflate ready, routing configured, test passed and running.
- Preserve transcript on stop, recoverable errors and navigation. New conversation needs
  loss confirmation if content has not been exported. No automatic transcript persistence.
- Route tests have their own state and destination confirmation. They are not call acceptance.
  Missing/ambiguous bridge devices mute the affected lane without default-device fallback.
- Report actionable persistent errors near the affected surface. Diagnostic details remain
  secondary, local and redacted on explicit export.

## Qt implementation mapping

The shipped platform is PySide6. This HTML is a lightweight design artifact, **not a web
rewrite**. Use QStackedWidget/navigation buttons, QComboBox language and device selectors,
QAbstractItemModel-backed paired turns, accessible QLabel buddies, native dialogs and a
single session controller. The project has no App Platform/Radzen design-system contract;
the Blazor-specific skill assets and approval pipeline are not dependencies for this proposal.
The user's explicit mockup request authorizes these review drafts; it is not recorded as
approval to implement the final design.

`styles.css` establishes proposal-level color, spacing, type, focus and radius tokens.
Map them into a small Qt theme/component baseline during implementation. Do not import an
unrelated enterprise design system. The prototype uses responsive stacking; the native
application must separately prove behavior at small windows and Windows DPI settings.

## State and edge-case requirements

| Trigger | Required result | Implementation issue |
|---|---|---|
| First launch / missing files | Show readiness, provisioning and retry; microphone stays off | #27 |
| Unsupported pair / one-way model | Explain the missing direction; no arbitrary fallback | #21, #27 |
| Uncertain or out-of-pair speech | Ask for correction; no arbitrary target or wrong-language playback | #21, #31 |
| Local speech output | Show microphone paused, restore only if session still active | #23, #28 |
| Queue overload / discarded turn | Identify lost work and invite repetition | #23, #31 |
| Stop / shutdown timeout | Immediate acknowledgement, truthful stopping state, no false success | #23 |
| Route test succeeds | Test passed; session stays stopped | #24, #25 |
| Endpoint missing or ambiguous | Explicit muted lane / reconnect action; never silently default | #24, #29 |
| Pair/device changes | Stop first; invalidate old route tests and context | #21, #25 |
| Missing output voice | Explain text-only option or block bridge; setup action | #27, #28 |
| Long, multilingual or RTL text | Preserve pairing and reading order; no clipped actions | #26, #30 |
| Export fails or is cancelled | Keep content and offer recovery; no false Saved notice | #26, #31 |
| Reading older turns | Do not steal scroll position; offer Jump to latest | #26 |

Not every row is an executable engine in this preview. Fixed-source selection, detection
correction, actual pack details/download progress, full transcript operations, diagnostics,
high contrast and production keyboard/focus behavior are specified for implementation in
the linked issues. No interaction in this preview is an acceptance certificate.

## Delivery order and acceptance

1. Fix truthful states and stop guards (#23, #24) while introducing the registry contract (#21).
2. Build the shell, device recovery and actionable errors (#22, #29, #31).
3. Implement bridge setup, transcript, provisioning and voice readiness (#25–#28).
4. Verify native accessibility and representative task completion (#30, #32).
5. Qualify additional language packs separately (#33); keep unsupported capabilities visible
   as planned/unavailable until evidence exists.

Use task completion and state comprehension, not an arbitrary visual score. Proposed target:
at least four of five representative participants complete core tasks without help after
provisioning, and all understand whether the microphone is recording or paused. Establish
baseline timings before judging improvements. Native DPI/Narrator, device isolation,
reconnect and consenting real-call checks are distinct evidence tracks.

## Backlog

The authoritative tracker is [issue #20](https://github.com/boris-heuer/lianiq/issues/20).
See [issue-index.md](issue-index.md) for all work items and dependencies.

## Preview validation

See [verification.md](verification.md) for checks actually performed and limitations.
