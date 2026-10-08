# Lianiq Software Factory Adoption Baseline

**Tracker:** [#37](https://github.com/boris-heuer/lianiq/issues/37)
**Work order:** [#38](https://github.com/boris-heuer/lianiq/issues/38)
**Status:** planned; catalog registration blocked by the canonical factory baseline described below.

## Purpose and scope

This plan adopts the Software Factory delivery lifecycle for `lianiq`, an
independent Python/Qt Windows product. It does not authorize application-feature
implementation, change runtime behaviour, claim runtime SystemOK, or alter
global factory policy.

The existing product backlog ([#20](https://github.com/boris-heuer/lianiq/issues/20))
and UI design pull request ([#34](https://github.com/boris-heuer/lianiq/pull/34))
remain their own sources of intent and evidence. They are not retrospective
approvals and are not changed by this adoption work.

## Canonical ownership

| Concern | Owner and source of truth | Lianiq action |
|---|---|---|
| Factory policy, schemas, catalog tooling, and canonical capability artefacts | Current [`boris-heuer/app-shared`](https://github.com/boris-heuer/app-shared) `main`; `repo-config/skills/implement-capability/references/repo-ownership-routing.md` and `.claude/rules/coordination.md` | Consume by pointer; do not copy, fork, or modify factory policy here. |
| Lianiq runtime, Qt UI, Windows packaging, local-only privacy behaviour, and audio routing | This repository | Keep product behaviour and product evidence here. |
| Formal capability folder and catalog registration | `app-shared/docs/products/lianiq/capabilities/<slug>/` and the canonical materializer lane | Do not create a local substitute catalog or capability folder. |
| Local adoption instructions and product-specific evidence | This repository under `docs/sdlc/` and local guidance/configuration once admitted | Keep records English, link to the canonical artefacts, and preserve the existing issue and PR references. |

Historical inspection evidence was captured from
[`app-shared` commit `dd9895bbec6b8ae1838347e8c79c5694f4987d8f`](https://github.com/boris-heuer/app-shared/commit/dd9895bbec6b8ae1838347e8c79c5694f4987d8f)
on 2026-10-08. It is not an operational pin. Before any registration, refetch
current `app-shared/main`, record the resolved commit, and reassess the
catalog-registration blocker. The public configuration contract is
`repo-config/marketplace-public/factory.config.schema.json`. It is a closed
schema: use only its documented `factory`, `github`, `repositories`, `paths`,
and `capabilities` sections, with optional `workflows`, `agent_conventions`, and
`harness` sections. A later local configuration must leave hooks and MCP disabled
by default and must not introduce unrecognised keys.

## Catalog-registration dependency

The current canonical sources disagree about whether a consumer may use
`catalog.delta/v3`:

- `repo-config/skills/spec-interview/references/folder-bootstrap.md` requires a
  v3 `create` event for each new capability after the CAP-ID migration and rejects
  new v1/v2 registrations.
- `docs/products/software-factory/integration-contract.yml` declares
  `software-factory.catalog-delta.v3` as `proposed` and states that no consumer
  may rely on it while proposed.

The second statement is a consumer-admission boundary. The operator chose to
wait for the normal WI-09 implementation and baseline closure through
[app-shared#4862](https://github.com/boris-heuer/app-shared/issues/4862), with
no create-only exception. Until that work closes the conflict, Lianiq must not
emit a catalog delta, create a canonical capability folder, or invent a local
catalog alternative. This is a dependency, not a completed gate and not a
runtime SystemOK finding.

## Definition of Done and evidence boundary

The binding adoption Definition of Done is issue [#37](https://github.com/boris-heuer/lianiq/issues/37).
Its repository-local rendering and the Python/Qt/Windows evidence profile are
owned by SDLC-02 ([#39](https://github.com/boris-heuer/lianiq/issues/39)). This
plan may link to `docs/sdlc/definition-of-done.md` only after that work merges.

For application changes, deterministic tests, mockups, and documentation prove
only their stated mechanisms. They do not establish packaged Windows, hardware,
reconnect, language-quality, or real-call acceptance. The Call Bridge remains
experimental unless the existing packaged-device and operator evidence records
pass for the exact claimed profile. The local product boundaries remain
[`CONTRIBUTING.md`](../../CONTRIBUTING.md),
[`docs/call-bridge-system-ok.md`](../call-bridge-system-ok.md), and
[`docs/call-bridge-operator-setup.md`](../call-bridge-operator-setup.md).

## Child work orders and dependencies

| Order | Prerequisites | Deliverable and acceptance boundary |
|---|---|---|
| SDLC-02: local Definition of Done and native evidence profile | None; tracked by [#39](https://github.com/boris-heuer/lianiq/issues/39) | English local DoD and a Python/Qt/Windows applicability profile. It records unavailable evidence as open, never as SystemOK. |
| SDLC-03: canonical product model and backlog mapping | **Blocked** by [app-shared#4862](https://github.com/boris-heuer/app-shared/issues/4862), including normal WI-09 implementation and baseline closure; tracked by [#40](https://github.com/boris-heuer/lianiq/issues/40) | Factory-owned product/capability artefacts plus a v3 registration only if the accepted contract admits it. Existing issue/PR links are retained as external provenance. |
| SDLC-04: contributor and agent entrypoints | [#38](https://github.com/boris-heuer/lianiq/issues/38) and [#39](https://github.com/boris-heuer/lianiq/issues/39) complete; tracked by [#41](https://github.com/boris-heuer/lianiq/issues/41) | Pointer-oriented local agent guidance and CONTRIBUTING alignment; add schema-valid `factory.config.yml` only if the selected harness requires it. Hooks, MCP, automatic writes, and Blazor-only gates remain disabled or omitted. |
| SDLC-05: first scoped capability lifecycle | SDLC-03 and SDLC-04 complete and an approved product outcome | A canonical specification, work items, independent review, exact-head CI, and evidence appropriate to the changed surface. Runtime SystemOK stays open until native packaged and operator acceptance is recorded. |

## Reproducible walkthrough

1. Read this plan with [#37](https://github.com/boris-heuer/lianiq/issues/37) and
   [#38](https://github.com/boris-heuer/lianiq/issues/38).
2. Refetch `app-shared/main`, record its resolved commit, and resolve factory
   policy from that current source rather than from an old consumer checkout or
   copied rules.
3. Reassess the catalog-registration blocker and confirm SDLC-03 has reconciled
   v3 consumer admission before attempting any
   capability registration.
4. Complete SDLC-02 and SDLC-04 before treating local configuration or guidance
   as active.
5. For every future product change, preserve the local-first and fail-closed
   audio-routing rules, use the applicable deterministic and native evidence,
   and leave unmet evidence open with cause, impact, responsible actor, and the
   exact unblock action.
