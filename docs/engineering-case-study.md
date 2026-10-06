# Engineering Case Study: Building Evidence for an Experimental Call Bridge

## Problem and boundary

The project explores local German/Mandarin speech translation on Windows. Its experimental Call
Bridge routes two **utterance-based** translation lanes between selected physical endpoints and two
operator-installed virtual audio cables. It is not simultaneous interpretation, does not configure
WeChat automatically, and is not production SystemOK until the documented hardware and real-call
gates pass.

The core safety question is not only whether a translation result is produced. It is whether audio
reaches only the intended endpoint when devices reorder, disappear, or misbehave.

## Engineering approach

The implementation separates real-time capture from model work. Callbacks place bounded audio
frames into buffers; segmentation, speech recognition, translation, synthesis, and playback run
outside the callback. Each direction has a fixed language contract and an explicit output endpoint.
Endpoint selections are stored as Windows identities and re-resolved at runtime rather than using a
default device or a persisted numeric index.

This supports a fail-closed policy: missing or ambiguous endpoints mute the affected lane. It does
not prove a physical routing result by itself, which is why the project retains operator gates.

## TDD and evidence ladder

The work follows test-driven slices: pure routing contracts first, then buffers and resampling,
endpoint resolution, dual-lane lifecycle, and UI/configuration validation. Tests use controlled
fakes for ordering, queue pressure, endpoint loss, recovery, and synthesis failure. This makes
failure behavior repeatable without requiring a live microphone, cable driver, or call account.

Evidence is deliberately tiered:

| Gate | What it supports | What it does not support |
|---|---|---|
| Unit/component tests | Routing contracts, isolation rules, bounded queues, fail-closed behavior | Physical devices or third-party call behavior |
| Local model self-test | Both model lanes can run locally | Cable isolation or real conversation quality |
| Packaged two-cable test | Explicit endpoint mapping and physical route isolation | General compatibility across hardware |
| Consented real call | The checklist on one observed system | A guarantee for all systems or conversations |

The current status is source-level and synthetic evidence only. The packaged-device, two-cable,
disconnect/reconnect, and real two-party WeChat rows remain operator-owned gates. Details are in
[the SystemOK evidence record](call-bridge-system-ok.md) and
[operator setup](call-bridge-operator-setup.md).

## Risks and controls

| Risk | Control | Remaining decision |
|---|---|---|
| Wrong endpoint after reboot | Persist identity; reject missing/ambiguous matches | Reselect after identity-changing driver reinstall |
| Audio leakage or feedback | Two cables, explicit roles, no default fallback | Prove with the physical loop test |
| CPU contention | Bounded queues and scheduled model work | Measure on the actual device |
| Privacy exposure | Local processing and redacted diagnostics | Operator still protects files and call consent |
| Driver and voice licensing/support | Drivers are installed separately; Mandarin voice is user-provided | Review vendor/voice terms before distribution |
| Overclaiming AI output | Human review and evidence gates | Do not label experimental results as certified |

## AI and human responsibility

AI-assisted development can accelerate drafts and test ideas, but it cannot observe the user’s
audio path or certify a call result. Humans review every change, preserve privacy boundaries, run
the checks, and decide whether evidence satisfies a gate. This division is documented in
[AI_ASSISTED_DEVELOPMENT.md](../AI_ASSISTED_DEVELOPMENT.md).

## Reproducing the available evidence

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe .\scripts\call_bridge_self_test.py
```

The third command is meaningful only after local models are available. A successful command does
not close the hardware or WeChat gates. Follow the operator checklist before using the feature in a
call.
