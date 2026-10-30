# Target UI implementation backlog

Parent: [#20 — Multilingual-ready desktop experience](https://github.com/boris-heuer/lianiq/issues/20)

All issues were created at the operator's request on 2026-10-08. Priorities are part of issue titles. No assignee, deadline or project membership is implied.

| Issue | Scope | Dependencies |
|---|---|---|
| [#21](https://github.com/boris-heuer/lianiq/issues/21) | P1: replace binary language assumptions with a capability-based language-pair contract | None |
| [#22](https://github.com/boris-heuer/lianiq/issues/22) | P1: separate Conversation, Call Bridge and settings in the desktop shell | #21 |
| [#23](https://github.com/boris-heuer/lianiq/issues/23) | P1: make conversation status and stop behavior truthful and consistent | None |
| [#24](https://github.com/boris-heuer/lianiq/issues/24) | P1: correct Call Bridge readiness, route-test results and lane status | #21, #23 |
| [#25](https://github.com/boris-heuer/lianiq/issues/25) | P1: guide users through explicit two-lane Call Bridge setup and testing | #24 |
| [#26](https://github.com/boris-heuer/lianiq/issues/26) | P2: present paired multilingual conversation turns with safe transcript actions | #21, #23, #22 |
| [#27](https://github.com/boris-heuer/lianiq/issues/27) | P1: add first-run language readiness and explicit offline pack provisioning | #21, #22 |
| [#28](https://github.com/boris-heuer/lianiq/issues/28) | P2: make voice output readiness and playback controls language-aware | #21, #23, #27 |
| [#29](https://github.com/boris-heuer/lianiq/issues/29) | P1: make audio device selection, persistence and reconnect recoverable | #23, #22 |
| [#30](https://github.com/boris-heuer/lianiq/issues/30) | P2: implement accessible, resizable and multilingual-safe Qt presentation | #22, #26 |
| [#31](https://github.com/boris-heuer/lianiq/issues/31) | P1: provide persistent actionable errors and privacy-safe diagnostics | #23, #24, #21 |
| [#32](https://github.com/boris-heuer/lianiq/issues/32) | P2: establish task-based UX acceptance and native Windows regression evidence | #22, #26, #27, #25, #30, #31, #28, #29 |
| [#33](https://github.com/boris-heuer/lianiq/issues/33) | P3: qualify additional offline language packs for English, Spanish and French | #21, #27, #32 |
| [#35](https://github.com/boris-heuer/lianiq/issues/35) | P1: Local text translation with optional translated speech | #21, #22, #27, #28, #31 |
| [#36](https://github.com/boris-heuer/lianiq/issues/36) | P1: One-way speech-to-translated-text | #21, #22, #23, #26, #27, #29, #31 |

## Scope boundaries

#20 covers P1/P2 UX delivery; #33 is a separately staged language-pack qualification follow-up.
Mockups do not add language support. All UI, routing, metadata and tests must use extensible
language identifiers from #21. Existing German/Mandarin behavior must survive migration.

## GitHub Project

Issues are stored in `boris-heuer/lianiq`. Project discovery via `gh project list --owner
boris-heuer --format json` failed because the current CLI credential lacks `read:project`.
No project was guessed or created and no authentication scope was expanded. Repository
issues fulfill the requested repository-or-project destination. Optional future project
assignment requires an authorized credential with appropriate project access and an exact
project identity.
